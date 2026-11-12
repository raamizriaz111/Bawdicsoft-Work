#!/usr/bin/env python3
"""
Interactive Terminal CLI for Universal Client Chatbot.
Test your client's chatbot directly from the command line.
"""

import uuid
from bot_config import BOT_NAME, COMPANY_OR_SOFTWARE_NAME, WELCOME_MESSAGE
from backend.llm_client import ChatClient
from backend.lead_manager import (
    extract_lead_from_message,
    validate_candidate_name,
    save_lead,
    init_lead_storage
)
from backend.session_manager import (
    get_or_create_session,
    update_session_profile,
    append_session_message,
    get_session_history,
    init_session_storage
)

def run_cli():
    init_lead_storage()
    init_session_storage()
    
    chat_client = ChatClient()
    session_id = f"cli_{uuid.uuid4().hex[:8]}"
    session = get_or_create_session(session_id)
    profile = session.get("user_profile", {})

    print("\n" + "=" * 65)
    print(f"🤖 {BOT_NAME} — {COMPANY_OR_SOFTWARE_NAME} Interactive Terminal")
    print("=" * 65)
    print(f"{BOT_NAME}: {WELCOME_MESSAGE}")
    print("Type 'exit' or 'quit' to end the session.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSession ended.")
            break

        if not user_input:
            continue

        if user_input.lower() in ["exit", "quit"]:
            print(f"\n{BOT_NAME}: Goodbye! Thank you for chatting with {COMPANY_OR_SOFTWARE_NAME}.\n")
            break

        prior_history = get_session_history(session_id)
        prev_assistant_msg = next(
            (m.get("content") for m in reversed(prior_history) if m.get("role") == "assistant"),
            None,
        )

        # Lead extraction (name, email, phone)
        extracted = extract_lead_from_message(user_input, prev_assistant_msg=prev_assistant_msg)
        if extracted["name"]:
            profile["name"] = extracted["name"]
            update_session_profile(session_id, name=extracted["name"])
        if extracted["email"]:
            profile["email"] = extracted["email"]
            update_session_profile(session_id, email=extracted["email"])
        if extracted["phone"]:
            profile["phone"] = extracted["phone"]
            update_session_profile(session_id, phone=extracted["phone"])

        # Session tracking & structured sales analysis
        append_session_message(session_id, "user", user_input)
        history = get_session_history(session_id)
        analysis = chat_client.generate_analysis(history, user_profile=profile)
        reply = analysis["reply"]

        if not extracted["name"] and analysis.get("extracted_name"):
            llm_name = validate_candidate_name(analysis["extracted_name"])
            if llm_name:
                extracted["name"] = llm_name
                profile["name"] = llm_name

        qual_update = {
            "sales_stage": analysis.get("sales_stage"),
            "specific_need": analysis.get("specific_need"),
            "budget": analysis.get("budget"),
            "timeline": analysis.get("timeline"),
            "preferred_slot": analysis.get("preferred_slot"),
            "objection_reason": analysis.get("objection_reason"),
            "lead_score": analysis.get("lead_score"),
            "deal_summary": analysis.get("deal_summary"),
        }
        update_session_profile(
            session_id,
            name=profile.get("name"),
            sales_stage=analysis.get("sales_stage"),
            qualification=qual_update,
            emotion_entry={"emotion": analysis["emotion"], "buyer_intent": analysis["buyer_intent"]},
        )

        has_known_contact = bool(profile.get("email") or profile.get("phone"))
        newly_shared_contact = bool(extracted["email"] or extracted["phone"])
        if newly_shared_contact or (has_known_contact and extracted["name"]):
            saved_lead = save_lead(
                session_id=session_id,
                name=profile.get("name"),
                email=profile.get("email"),
                phone=profile.get("phone"),
                interest=qual_update.get("deal_summary") or user_input[:100],
                notes=f"Captured via CLI: '{user_input}'",
                business_name=COMPANY_OR_SOFTWARE_NAME,
                emotion=analysis["emotion"],
                buyer_intent=analysis["buyer_intent"],
                sales_tactic=analysis["sales_tactic"],
                qualification=qual_update,
            )
            contact_info = " / ".join(filter(None, [saved_lead.get("email"), saved_lead.get("phone")]))
            print(f"   [Lead Saved: {contact_info} ({saved_lead.get('name')})]")

        append_session_message(session_id, "assistant", reply)

        print(f"\n{BOT_NAME}: {reply}\n")

if __name__ == "__main__":
    run_cli()
