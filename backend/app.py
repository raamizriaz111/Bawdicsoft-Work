"""
Universal Chatbot Studio & Agent Desk API Server.
Supports multi-industry presets, live preview configuration, real-time chat, lead capture & CSV export.
"""

import os
import re
import io
import csv
import json
import socket
from pathlib import Path
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, FileResponse, Response
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles

from backend.presets import PRESETS
from backend.llm_client import ChatClient
from backend.lead_manager import (
    extract_lead_from_message,
    detect_invalid_contact_attempt,
    validate_candidate_name,
    _is_substantive_summary,
    save_lead,
    get_all_leads,
    delete_lead_by_id,
    clear_all_leads,
    init_lead_storage
)
from backend.session_manager import (
    get_or_create_session,
    reset_session,
    update_session_profile,
    append_session_message,
    get_session_history,
    get_total_chats_count,
    init_session_storage
)

# Initialize storage and LLM client
init_lead_storage()
init_session_storage()
chat_client = ChatClient()

BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "static"
CONFIG_FILE = BASE_DIR / "data" / "active_config.json"

def load_active_config() -> dict:
    """Load active configuration or initialize with Dental Clinic preset."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return PRESETS["dental"]

def save_active_config(cfg: dict):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

active_config = load_active_config()

async def home(request):
    """Serve the Agent Desk Prototype interface."""
    index_path = STATIC_DIR / "index.html"
    return FileResponse(index_path)

async def presets_endpoint(request):
    """Return all pre-built client presets."""
    return JSONResponse(PRESETS)

async def config_endpoint(request):
    """Get or update active chatbot configuration."""
    global active_config
    if request.method == "GET":
        active_config = load_active_config()
        return JSONResponse(active_config)
    elif request.method == "POST":
        try:
            data = await request.json()
            active_config = load_active_config()
            active_config.update(data)
            save_active_config(active_config)
            return JSONResponse({"status": "success", "config": active_config})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

async def session_endpoint(request):
    """Get or initialize visitor session."""
    session_id = request.query_params.get("sessionId", "guest-session")
    session = get_or_create_session(session_id)
    return JSONResponse({
        "sessionId": session["session_id"],
        "userProfile": session["user_profile"],
        "history": session.get("messages", []),
        "isReturning": session.get("is_returning", False)
    })

async def transcript_endpoint(request):
    """Return full message transcript of a specific session for lead auditing."""
    session_id = request.query_params.get("sessionId")
    if not session_id:
        return JSONResponse({"error": "Missing sessionId parameter"}, status_code=400)
    session = get_or_create_session(session_id)
    return JSONResponse({
        "sessionId": session_id,
        "userProfile": session.get("user_profile", {}),
        "messages": session.get("messages", [])
    })

async def reset_session_endpoint(request):
    """Reset session history to simulate a brand-new visitor."""
    try:
        body = await request.json()
        session_id = body.get("sessionId", "guest-session")
    except Exception:
        session_id = "guest-session"
    
    reset = reset_session(session_id)
    return JSONResponse({"status": "reset", "session": reset})

async def chat_endpoint(request):
    """Handle chat messages, dynamic persona responses & silent lead detection."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    session_id = body.get("sessionId", "guest-session")
    user_message = body.get("message", "").strip()
    override_config = body.get("config") or active_config

    if not user_message:
        return JSONResponse({"error": "Empty message"}, status_code=400)

    # 1. Retrieve persistent session & profile
    session = get_or_create_session(session_id)
    profile = session.get("user_profile", {})

    prior_history = get_session_history(session_id)
    prev_assistant_msg = next(
        (m.get("content") for m in reversed(prior_history) if m.get("role") == "assistant"),
        None,
    )

    # 2. Extract lead details (saving deferred until emotional analysis completes)
    extracted = extract_lead_from_message(user_message, prev_assistant_msg=prev_assistant_msg)
    saved_lead = None
    lead_updated = False

    explicit_name_intro = bool(
        re.search(r"\b(?:my name is|name is|name\s*[:\-]|i am|i'm|this is|call me)\b", user_message, re.IGNORECASE)
    )
    if extracted["name"] and (not profile.get("name") or explicit_name_intro):
        profile["name"] = extracted["name"]
        update_session_profile(session_id, name=extracted["name"])

    if extracted["email"]:
        profile["email"] = extracted["email"]
        update_session_profile(session_id, email=extracted["email"])

    if extracted["phone"]:
        profile["phone"] = extracted["phone"]
        update_session_profile(session_id, phone=extracted["phone"])

    # 3. Persist user message to history
    append_session_message(session_id, "user", user_message)
    conversation_history = get_session_history(session_id)

    # 4. Generate grounded 1-2 sentence salesperson reply + live emotional intelligence
    runtime_profile = dict(profile)
    runtime_profile["_user_turn_count"] = sum(1 for m in conversation_history if m.get("role") == "user")
    inv_contact = detect_invalid_contact_attempt(
        user_message,
        found_email=extracted["email"],
        found_phone=extracted["phone"],
        prev_assistant_msg=prev_assistant_msg,
    )
    if inv_contact and not profile.get(inv_contact.get("type", "")):
        runtime_profile["_contact_validation_issue"] = inv_contact

    analysis = chat_client.generate_analysis(
        conversation_history=conversation_history,
        user_profile=runtime_profile,
        config=override_config
    )
    reply = analysis["reply"]

    # 5. Merge LLM qualification, sales stage & casual name extraction back into profile + save lead
    if not extracted["name"] and analysis.get("extracted_name"):
        # Avoid pulling malformed email local-parts (like 'ahmedabid@') as a name when standalone
        if not (inv_contact and len(user_message.split()) <= 2):
            llm_name = validate_candidate_name(analysis["extracted_name"])
            if llm_name:
                extracted["name"] = llm_name
                profile["name"] = llm_name

    has_known_contact = bool(profile.get("email") or profile.get("phone"))
    newly_shared_contact = bool(extracted["email"] or extracted["phone"])
    if newly_shared_contact:
        # Sharing a direct email or phone number is an explicit Hot Lead signal
        if analysis["buyer_intent"] != "hot":
            analysis["buyer_intent"] = "hot"
            if analysis["emotion"] == "neutral":
                analysis["emotion"] = "curious"
            if analysis["sales_tactic"] in ("Warm Hospitality", "Friendly Qualification", "Polite Business Pivot"):
                analysis["sales_tactic"] = "VIP Follow-up Confirmation"
        analysis["sales_stage"] = "post_capture"
        analysis["lead_score"] = max(int(analysis.get("lead_score") or 0), 85)

    raw_summary = analysis.get("deal_summary")
    effective_summary = (
        raw_summary
        if (_is_substantive_summary(raw_summary, analysis["buyer_intent"]) or not profile.get("deal_summary"))
        else profile.get("deal_summary")
    )
    qual_update = {
        "sales_stage": analysis.get("sales_stage"),
        "specific_need": analysis.get("specific_need"),
        "budget": analysis.get("budget"),
        "timeline": analysis.get("timeline"),
        "preferred_slot": analysis.get("preferred_slot"),
        "objection_reason": analysis.get("objection_reason"),
        "lead_score": analysis.get("lead_score"),
        "deal_summary": effective_summary,
    }
    update_session_profile(
        session_id,
        name=profile.get("name"),
        sales_stage=analysis.get("sales_stage"),
        qualification=qual_update,
        emotion_entry={"emotion": analysis["emotion"], "buyer_intent": analysis["buyer_intent"]},
    )
    for q_key in ("specific_need", "budget", "timeline", "preferred_slot", "objection_reason", "deal_summary", "sales_stage"):
        if qual_update.get(q_key):
            profile[q_key] = qual_update[q_key]
    if isinstance(qual_update.get("lead_score"), (int, float)):
        profile["lead_score"] = max(int(profile.get("lead_score") or 0), int(qual_update["lead_score"]))

    if newly_shared_contact:
        saved_lead = save_lead(
            session_id=session_id,
            name=profile.get("name"),
            email=profile.get("email"),
            phone=profile.get("phone"),
            interest=qual_update.get("deal_summary") or user_message[:120],
            notes=f"Inquiry: '{user_message}'",
            business_name=override_config.get("businessName"),
            emotion=analysis["emotion"],
            buyer_intent=analysis["buyer_intent"],
            sales_tactic=analysis["sales_tactic"],
            qualification=qual_update,
        )
        print(f"[Lead Manager] Captured Lead for {override_config.get('businessName')}: {saved_lead}")
    elif has_known_contact and (
        extracted["name"]
        or analysis["buyer_intent"] in ("hot", "warm")
        or any(qual_update.get(k) for k in ("specific_need", "budget", "timeline", "preferred_slot"))
    ):
        save_lead(
            session_id=session_id,
            name=profile.get("name"),
            email=profile.get("email"),
            phone=profile.get("phone"),
            interest=qual_update.get("deal_summary"),
            notes=None,
            business_name=override_config.get("businessName"),
            emotion=analysis["emotion"],
            buyer_intent=analysis["buyer_intent"],
            sales_tactic=analysis["sales_tactic"],
            qualification=qual_update,
        )
        lead_updated = True

    # 6. Persist assistant reply to history
    append_session_message(session_id, "assistant", reply)

    # Return reply along with live behavioral intelligence, qualification, lead info, and updated stats
    return JSONResponse({
        "reply": reply,
        "analysis": {
            "emotion": analysis["emotion"],
            "buyer_intent": analysis["buyer_intent"],
            "sales_stage": analysis.get("sales_stage"),
            "sales_tactic": analysis["sales_tactic"],
            "lead_score": analysis.get("lead_score"),
            "deal_summary": analysis.get("deal_summary"),
            "source": analysis.get("source"),
        },
        "leadCaptured": saved_lead,
        "leadUpdated": lead_updated,
        "userProfile": profile,
        "chatsCount": get_total_chats_count(),
        "leadsCount": len(get_all_leads()),
        "isMockMode": chat_client.client is None
    })

async def get_leads_endpoint(request):
    """API endpoint to view all captured leads and metrics."""
    leads = get_all_leads()
    chats_count = get_total_chats_count()
    return JSONResponse({
        "total": len(leads),
        "leads": leads,
        "chatsCount": chats_count,
        "leadsCount": len(leads)
    })

async def export_leads_csv(request):
    """Export captured leads to CSV format for download."""
    leads = get_all_leads()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Lead ID", "Business", "Name", "Email", "Phone",
        "Lead Score", "Buyer Intent", "Emotion", "Specific Need",
        "Budget", "Timeline", "Preferred Slot", "Deal Summary",
        "Interest", "Captured At"
    ])
    for l in leads:
        writer.writerow([
            l.get("id", ""),
            l.get("business_name", ""),
            l.get("name", ""),
            l.get("email") or "",
            l.get("phone") or "",
            l.get("lead_score") if l.get("lead_score") is not None else "",
            l.get("buyer_intent") or "",
            l.get("emotion") or "",
            l.get("specific_need") or "",
            l.get("budget") or "",
            l.get("timeline") or "",
            l.get("preferred_slot") or "",
            l.get("deal_summary") or "",
            l.get("interest", ""),
            l.get("created_at", "")
        ])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="captured_leads.csv"'}
    )

async def delete_lead_endpoint(request):
    """Delete a single captured lead by id."""
    try:
        body = await request.json()
        lead_id = (body.get("leadId") or "").strip()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    if not lead_id:
        return JSONResponse({"error": "Missing leadId"}, status_code=400)
    deleted = delete_lead_by_id(lead_id)
    leads = get_all_leads()
    return JSONResponse({
        "status": "deleted" if deleted else "not_found",
        "leads": leads,
        "leadsCount": len(leads),
        "chatsCount": get_total_chats_count(),
    })

async def clear_leads_endpoint(request):
    """Clear captured leads."""
    clear_all_leads()
    return JSONResponse({"status": "cleared", "total": 0, "leads": []})

def is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) != 0

def find_available_port(preferred: int = 8003) -> int:
    if is_port_available(preferred):
        return preferred
    for port in range(preferred + 1, preferred + 50):
        if is_port_available(port):
            return port
    return preferred

# Starlette Middleware
middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
]

# Starlette Routes
routes = [
    Route("/", home),
    Route("/api/presets", presets_endpoint, methods=["GET"]),
    Route("/api/config", config_endpoint, methods=["GET", "POST"]),
    Route("/api/session", session_endpoint, methods=["GET"]),
    Route("/api/session/transcript", transcript_endpoint, methods=["GET"]),
    Route("/api/session/reset", reset_session_endpoint, methods=["POST"]),
    Route("/api/chat", chat_endpoint, methods=["POST"]),
    Route("/api/leads", get_leads_endpoint, methods=["GET"]),
    Route("/api/leads/export", export_leads_csv, methods=["GET"]),
    Route("/api/leads/delete", delete_lead_endpoint, methods=["POST"]),
    Route("/api/leads/clear", clear_leads_endpoint, methods=["POST"]),
    Mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static"),
]

app = Starlette(debug=True, routes=routes, middleware=middleware)

if __name__ == "__main__":
    import uvicorn
    preferred_port = int(os.environ.get("PORT", 8003))
    port = find_available_port(preferred_port)

    print("\n" + "=" * 65)
    print(f"🚀 Universal Chatbot Studio & Agent Desk is running!")
    print(f"👉 Open in browser:  http://localhost:{port}")
    print(f"👉 Leads API:        http://localhost:{port}/api/leads")
    print(f"👉 Presets API:      http://localhost:{port}/api/presets")
    print("=" * 65 + "\n")
    uvicorn.run("backend.app:app", host="0.0.0.0", port=port, reload=True)
