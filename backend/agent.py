"""
Agent Decision Engine for Universal Client Chatbot Studio.
Implements deterministic code rules: "The LLM proposes, the code decides."
Turns LLM analysis into concrete tool actions, updates leads, and logs every action to the database.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field

from backend.database import SessionLocal, init_db
from backend.models import ActionModel, LeadModel, JobModel
from backend.tools import book_meeting as tool_book_meeting, notify_team as tool_notify_team, update_lead as tool_update_lead
from backend.scheduler import schedule_followup_sequence, cancel_pending_jobs

class AgentDecision(BaseModel):
    """Structured result of the agent decision rules."""
    action_type: str = Field(description="Action to take: 'book_meeting', 'offer_slots', 'start_nurture', 'handoff', 'reply_only'")
    actions_logged: List[str] = Field(default_factory=list, description="List of tools logged to actions table")
    runtime_note: Optional[str] = Field(default=None, description="Truth note injected into runtime context")
    suggested_reply_patch: Optional[str] = Field(default=None, description="Truthful phrasing to ensure reply matches action")
    slots_offered: List[str] = Field(default_factory=list, description="Calendar slots presented to the visitor")
    meta: Dict[str, Any] = Field(default_factory=dict, description="Metadata and parameters for the actions")


class SalesAgent:
    """Deterministic decision engine governing chatbot actions and tool dispatch."""

    HUMAN_REQUEST_PHRASES = (
        "talk to a human", "speak to a human", "real human", "real person",
        "speak with someone", "talk to someone", "customer support",
        "speak to a manager", "call me", "human support", "representative",
        "contact person", "speak to an agent", "connect me to a human"
    )

    @classmethod
    def get_default_slots(cls) -> List[str]:
        """Generate 3 smart, natural business consultation slots based on current day."""
        now = datetime.now()
        # Tomorrow
        d1 = now + timedelta(days=1)
        if d1.weekday() >= 5:  # Weekend roll to Monday
            d1 += timedelta(days=(7 - d1.weekday()))
        # Day after tomorrow
        d2 = d1 + timedelta(days=1)
        if d2.weekday() >= 5:
            d2 += timedelta(days=(7 - d2.weekday()))

        day1_str = d1.strftime("%A at 2:00 PM")
        day1_alt = d1.strftime("%A at 4:00 PM")
        day2_str = d2.strftime("%A at 11:00 AM")
        return [day1_str, day1_alt, day2_str]

    @classmethod
    def decide_and_act(
        cls,
        session_id: str,
        user_message: str,
        analysis: Dict[str, Any],
        user_profile: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
        tenant_id: str = "default",
        lead_id: Optional[int] = None,
    ) -> AgentDecision:
        """
        Evaluate deterministic business rules based on LLM output & session profile.
        Rule hierarchy:
          1. Human Request or Repeated Frustration -> Handoff + notify_team
          2. Hot + Verified Contact + Preferred Slot -> book_meeting + notify_team
          3. Hot + Verified Contact (No Slot) -> Offer 3 slots
          4. Warm + Verified Contact -> Start nurture sequence
          5. Cold or Off-topic -> Reply only
        """
        init_db()
        cfg = config or {}
        biz_name = cfg.get("businessName") or "our team"
        user_msg_low = (user_message or "").lower()

        # Contact and qualification signals
        user_email = user_profile.get("email")
        user_phone = user_profile.get("phone")
        user_name = user_profile.get("name")
        contact_label = user_email or user_phone
        has_known_contact = bool(contact_label)

        buyer_intent = analysis.get("buyer_intent") or "cold"
        lead_score = int(analysis.get("lead_score") or 0)
        emotion = analysis.get("emotion") or "neutral"
        preferred_slot = analysis.get("preferred_slot") or user_profile.get("preferred_slot")

        emotion_history = user_profile.get("emotion_history") or []
        frustrated_count = sum(1 for e in emotion_history if str(e.get("emotion")).lower() == "frustrated")

        # -------------------------------------------------------------
        # Rule 1: Repeated Frustration or Explicit Human Handoff Request
        # -------------------------------------------------------------
        is_human_request = any(p in user_msg_low for p in cls.HUMAN_REQUEST_PHRASES)
        is_repeated_frustration = frustrated_count >= 2 or (frustrated_count >= 1 and emotion == "frustrated")

        if is_human_request or is_repeated_frustration:
            action_name = "notify_team"
            trigger_reason = "human_handoff" if is_human_request else "repeated_frustration"
            input_payload = {
                "trigger": trigger_reason,
                "customer_name": user_name,
                "contact": contact_label,
                "last_message": user_message,
                "frustration_count": frustrated_count,
            }
            # Execute tool notify_team
            tool_notify_team(
                event=trigger_reason,
                details=input_payload,
                lead_id=lead_id,
                session_id=session_id,
                tenant_id=tenant_id,
            )
            note = f"Human handoff requested. Acknowledge with genuine warmth that {biz_name}'s human leadership has been notified and will reach out directly."
            return AgentDecision(
                action_type="handoff",
                actions_logged=[action_name],
                runtime_note=note,
                suggested_reply_patch=f"I've flagged our human engineering lead at {biz_name} to take over directly. Someone from our team will follow up with you shortly.",
                meta={"trigger": input_payload["trigger"]},
            )

        # -------------------------------------------------------------
        # Rule 2: Hot + Verified Contact + Preferred Slot -> book_meeting
        # -------------------------------------------------------------
        is_hot = buyer_intent == "hot" or lead_score >= 80
        if is_hot and has_known_contact and preferred_slot:
            # 1. Execute book_meeting tool
            book_result = tool_book_meeting(
                lead_id=lead_id,
                attendee_name=user_name or "Interested Client",
                attendee_email=user_email,
                attendee_phone=user_phone,
                slot=preferred_slot,
                deal_summary=analysis.get("deal_summary") or user_profile.get("deal_summary"),
                session_id=session_id,
                tenant_id=tenant_id,
            )

            # 2. Execute notify_team tool
            notify_payload = {
                "event": "meeting_booked",
                "slot": preferred_slot,
                "contact": contact_label,
                "customer_name": user_name,
                "lead_score": lead_score,
            }
            tool_notify_team(
                event="meeting_booked",
                details=notify_payload,
                lead_id=lead_id,
                session_id=session_id,
                tenant_id=tenant_id,
            )

            # 3. Cancel any remaining pending nurture jobs since meeting is booked
            if lead_id:
                cancel_pending_jobs(lead_id=lead_id, tenant_id=tenant_id, reason="meeting_booked")

            note = f"Meeting requested for '{preferred_slot}' with confirmed contact '{contact_label}'. Confirm truthfully that this slot is locked and an invite is being prepared."
            return AgentDecision(
                action_type="book_meeting",
                actions_logged=["book_meeting", "notify_team"],
                runtime_note=note,
                suggested_reply_patch=f"Perfect! I have marked down {preferred_slot} for your consultation, and our team will send calendar confirmation to {contact_label}.",
                meta={"slot": preferred_slot, "contact": contact_label, "booking": book_result},
            )

        # -------------------------------------------------------------
        # Rule 3: Hot + Verified Contact (No Slot) -> Offer 3 Slots
        # -------------------------------------------------------------
        if is_hot and has_known_contact and not preferred_slot:
            default_slots = cls.get_default_slots()
            slots_str = ", ".join(default_slots[:2]) + f", or {default_slots[2]}"

            note = f"Contact is verified ({contact_label}). Present 3 free consultation slots ({slots_str}) so the visitor can pick the best time."
            return AgentDecision(
                action_type="offer_slots",
                actions_logged=["offer_slots"],
                runtime_note=note,
                slots_offered=default_slots,
                suggested_reply_patch=f"We have your details saved! Our engineering leads currently have openings {slots_str}. Do any of those work best for a quick consultation?",
                meta={"offered_slots": default_slots},
            )

        # -------------------------------------------------------------
        # Rule 4: Warm + Verified Contact -> Start Nurture Sequence
        # -------------------------------------------------------------
        is_warm = buyer_intent == "warm" or (50 <= lead_score < 80)
        if is_warm and has_known_contact:
            # 1. Update lead record with stage and score
            if lead_id:
                tool_update_lead(
                    lead_id=lead_id,
                    updates={"sales_stage": "nurture", "lead_score": lead_score},
                    session_id=session_id,
                    tenant_id=tenant_id,
                )
                # 2. Schedule follow-up jobs (Day 0 email, Day 2 WhatsApp, Day 5 email)
                schedule_followup_sequence(
                    lead_id=lead_id,
                    tenant_id=tenant_id,
                    lead_data=user_profile,
                )

            note = "Warm qualified lead. Follow-up sequence registered. Answer their specific questions clearly with zero aggressive pressure."
            return AgentDecision(
                action_type="start_nurture",
                actions_logged=["update_lead", "schedule_followups"],
                runtime_note=note,
                meta={"sequence": ["day0_email", "day2_whatsapp", "day5_email"]},
            )

        # -------------------------------------------------------------
        # Rule 5: Cold or Off-Topic -> Reply Only
        # -------------------------------------------------------------
        return AgentDecision(
            action_type="reply_only",
            actions_logged=[],
            runtime_note="Standard discovery or small talk turn. Converse naturally within persona.",
            meta={"buyer_intent": buyer_intent},
        )

    @classmethod
    def harmonize_reply(
        cls,
        llm_reply: str,
        decision: AgentDecision,
        user_profile: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Ensure the final chat message truthfully reflects the deterministic code decision.
        If the LLM forgot to mention booked slots or offered times, blend the truth seamlessly.
        """
        if not llm_reply or decision.action_type == "reply_only":
            return llm_reply or ""

        reply_clean = llm_reply.strip()
        user_name = user_profile.get("name")
        name_prefix = f"{user_name}, " if user_name and not reply_clean.lower().startswith(user_name.lower()) else ""

        # Case 1: Meeting Booked
        if decision.action_type == "book_meeting":
            slot = decision.meta.get("slot", "")
            if slot and slot.lower() not in reply_clean.lower() and "confirm" not in reply_clean.lower():
                return f"{reply_clean} I've noted {slot} for your consultation—our team will send an invite shortly."

        # Case 2: Offer Slots
        if decision.action_type == "offer_slots":
            if not any(day in reply_clean.lower() for day in ("monday", "tuesday", "wednesday", "thursday", "friday", "tomorrow", "pm", "am")):
                slots = decision.slots_offered or cls.get_default_slots()
                slots_text = f"{slots[0]}, {slots[1]}, or {slots[2]}"
                return f"{reply_clean} Would any of our open slots work for you ({slots_text})?"

        # Case 3: Human Handoff
        if decision.action_type == "handoff":
            if not any(k in reply_clean.lower() for k in ("human", "team", "specialist", "follow up", "reach out")):
                return f"{reply_clean} I've alerted our team directly so a human specialist can follow up with you."

        return reply_clean

    @staticmethod
    def _log_action(
        tenant_id: str,
        session_id: str,
        tool_name: str,
        input_data: Dict[str, Any],
        output_data: Dict[str, Any],
        status: str = "success",
    ):
        """Record an entry in the actions audit table."""
        try:
            with SessionLocal() as db:
                action = ActionModel(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    tool_name=tool_name,
                    input_data=input_data,
                    output_data=output_data,
                    status=status,
                    created_at=datetime.utcnow(),
                )
                db.add(action)
                db.commit()
        except Exception as e:
            print(f"[SalesAgent] Action logging error: {e}")
