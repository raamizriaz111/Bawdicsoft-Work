"""
Session and conversation history manager for Universal Client Chatbot Studio.
Handles session persistence, distinguishing between new and returning users.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

DATA_DIR = Path(__file__).parent.parent / "data"
SESSIONS_FILE = DATA_DIR / "sessions.json"

def init_session_storage():
    """Ensure data directory and sessions.json exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not SESSIONS_FILE.exists():
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2)

def load_sessions() -> Dict[str, Any]:
    init_session_storage()
    try:
        with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_sessions(sessions: Dict[str, Any]):
    init_session_storage()
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=2)

def _default_user_profile() -> Dict[str, Any]:
    return {
        "name": None,
        "email": None,
        "phone": None,
        "is_lead_captured": False,
        "sales_stage": "greeting",
        "specific_need": None,
        "budget": None,
        "timeline": None,
        "preferred_slot": None,
        "objection_reason": None,
        "lead_score": 0,
        "deal_summary": None,
        "emotion_history": [],
    }


def _ensure_profile_defaults(profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Backfill newly added profile keys onto existing sessions seamlessly."""
    merged = _default_user_profile()
    if isinstance(profile, dict):
        merged.update(profile)
    if not isinstance(merged.get("emotion_history"), list):
        merged["emotion_history"] = []
    if merged.get("lead_score") is None:
        merged["lead_score"] = 0
    return merged


def get_or_create_session(session_id: str) -> Dict[str, Any]:
    """Retrieve an existing session or initialize a new one."""
    sessions = load_sessions()
    now = datetime.now().isoformat()
    
    if session_id in sessions:
        session = sessions[session_id]
        session["last_active"] = now
        session["is_returning"] = True
        session["user_profile"] = _ensure_profile_defaults(session.get("user_profile"))
    else:
        session = {
            "session_id": session_id,
            "created_at": now,
            "last_active": now,
            "is_returning": False,
            "user_profile": _default_user_profile(),
            "messages": []
        }
        sessions[session_id] = session

    save_sessions(sessions)
    return session

def reset_session(session_id: str) -> Dict[str, Any]:
    """Reset a session to simulate a brand-new visitor."""
    sessions = load_sessions()
    now = datetime.now().isoformat()
    session = {
        "session_id": session_id,
        "created_at": now,
        "last_active": now,
        "is_returning": False,
        "user_profile": _default_user_profile(),
        "messages": []
    }
    sessions[session_id] = session
    save_sessions(sessions)
    return session

def update_session_profile(
    session_id: str,
    name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    sales_stage: Optional[str] = None,
    qualification: Optional[Dict[str, Any]] = None,
    emotion_entry: Optional[Dict[str, str]] = None,
):
    """Update known user profile, sales stage, qualification fields, and emotion trajectory."""
    sessions = load_sessions()
    if session_id not in sessions:
        get_or_create_session(session_id)
        sessions = load_sessions()

    session = sessions[session_id]
    profile = _ensure_profile_defaults(session.get("user_profile"))
    if name:
        profile["name"] = name
    if email:
        profile["email"] = email
    if phone:
        profile["phone"] = phone
    if sales_stage:
        profile["sales_stage"] = sales_stage

    if isinstance(qualification, dict):
        for field in ("specific_need", "budget", "timeline", "preferred_slot", "objection_reason", "deal_summary"):
            val = qualification.get(field)
            if isinstance(val, str) and val.strip():
                profile[field] = val.strip()
        raw_score = qualification.get("lead_score")
        if isinstance(raw_score, (int, float)):
            profile["lead_score"] = max(int(profile.get("lead_score") or 0), max(0, min(100, int(raw_score))))

    if isinstance(emotion_entry, dict) and emotion_entry.get("emotion"):
        history = list(profile.get("emotion_history") or [])
        history.append({
            "emotion": emotion_entry.get("emotion"),
            "buyer_intent": emotion_entry.get("buyer_intent"),
        })
        profile["emotion_history"] = history[-6:]

    if profile.get("email") or profile.get("phone"):
        profile["is_lead_captured"] = True
        if profile.get("sales_stage") in ("greeting", "discovery"):
            profile["sales_stage"] = "post_capture"

    session["user_profile"] = profile
    session["last_active"] = datetime.now().isoformat()
    sessions[session_id] = session
    save_sessions(sessions)

def append_session_message(session_id: str, role: str, content: str):
    """Append a message to the persistent session history."""
    sessions = load_sessions()
    if session_id not in sessions:
        get_or_create_session(session_id)
        sessions = load_sessions()

    session = sessions[session_id]
    session["messages"].append({
        "role": role,
        "content": content,
        "timestamp": datetime.now().isoformat()
    })
    session["last_active"] = datetime.now().isoformat()
    sessions[session_id] = session
    save_sessions(sessions)

def get_session_history(session_id: str) -> List[Dict[str, str]]:
    """Return list of messages formatted for LLM consumption [{'role': ..., 'content': ...}]."""
    session = get_or_create_session(session_id)
    return [
        {"role": m["role"], "content": m["content"]}
        for m in session.get("messages", [])
    ]

def get_total_chats_count() -> int:
    """Return total number of chat sessions that have messages."""
    sessions = load_sessions()
    return sum(1 for s in sessions.values() if len(s.get("messages", [])) > 0)
