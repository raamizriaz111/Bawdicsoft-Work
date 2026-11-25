"""
External tool adapters for Universal Client Chatbot Sales Agent.
Implements the 5 core sales agent tools:
1. book_meeting (Cal.com / Google Calendar)
2. send_whatsapp (Green API / Twilio)
3. send_email (Resend / SendGrid / SMTP)
4. notify_team (WhatsApp alert to sales team / Slack webhook)
5. update_lead (Database score, stage & qualification updates)

Operates with real APIs when environment keys are present,
with graceful zero-config simulation/fallback for testing and local dev.
"""

import os
import json
import logging
import smtplib
import ssl
import urllib.request
import urllib.parse
from datetime import datetime
from email.message import EmailMessage
from typing import Dict, Any, Optional

import resend

from backend.database import SessionLocal, init_db
from backend.models import ActionModel, LeadModel

logger = logging.getLogger("SalesAgentTools")


# =====================================================================
# 1. book_meeting (Cal.com / Google Calendar)
# =====================================================================
def book_meeting(
    lead_id: Optional[int],
    attendee_name: str,
    attendee_email: Optional[str],
    attendee_phone: Optional[str],
    slot: str,
    deal_summary: Optional[str] = None,
    session_id: Optional[str] = None,
    tenant_id: str = "default",
) -> Dict[str, Any]:
    """
    Book a consultation meeting via Cal.com or Google Calendar.
    Falls back to simulated booking confirmation if API keys are not configured.
    """
    calcom_api_key = os.getenv("CALCOM_API_KEY")
    calcom_event_type = os.getenv("CALCOM_EVENT_TYPE_ID", "12345")

    booking_id = f"book_{int(datetime.utcnow().timestamp())}"
    provider = "Cal.com" if calcom_api_key else "simulated_calendar"

    if calcom_api_key:
        try:
            url = f"https://api.cal.com/v1/bookings?apiKey={calcom_api_key}"
            payload = {
                "eventTypeId": int(calcom_event_type),
                "start": slot,
                "name": attendee_name,
                "email": attendee_email or "client@example.com",
                "notes": deal_summary or "Booked via BawdicSoft Chatbot Agent",
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                booking_id = str(data.get("id") or booking_id)
                provider = "Cal.com (Live)"
        except Exception as e:
            logger.warning(f"Cal.com live booking failed: {e}. Falling back to simulation.")
            provider = "Cal.com (Fallback)"

    result = {
        "status": "confirmed",
        "provider": provider,
        "booking_id": booking_id,
        "slot": slot,
        "attendee": attendee_name,
        "contact": attendee_email or attendee_phone,
        "calendar_url": f"https://cal.com/bawdicsoft/consultation?ref={booking_id}",
    }

    _log_tool_execution(
        tenant_id=tenant_id,
        lead_id=lead_id,
        session_id=session_id,
        tool_name="book_meeting",
        input_data={"attendee": attendee_name, "slot": slot, "email": attendee_email, "phone": attendee_phone},
        output_data=result,
        status="completed",
    )
    return result


# =====================================================================
# 2. send_whatsapp (Green API / Twilio)
# =====================================================================
def send_whatsapp(
    to_phone: str,
    message: str,
    lead_id: Optional[int] = None,
    session_id: Optional[str] = None,
    tenant_id: str = "default",
) -> Dict[str, Any]:
    """
    Dispatch WhatsApp message via Green API or Twilio WhatsApp API.
    Zero-config fallback logs delivery when credentials are not configured.
    """
    clean_phone = "".join(c for c in to_phone if c.isdigit() or c == "+").lstrip("+")
    green_instance = os.getenv("GREEN_API_INSTANCE_ID")
    green_token = os.getenv("GREEN_API_TOKEN")

    twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
    twilio_token = os.getenv("TWILIO_AUTH_TOKEN")
    twilio_from = os.getenv("TWILIO_WHATSAPP_NUMBER", "+14155238886")

    provider = "simulated_whatsapp"
    msg_id = f"wa_{int(datetime.utcnow().timestamp())}"

    # Try Green API
    if green_instance and green_token:
        try:
            url = f"https://api.green-api.com/waInstance{green_instance}/sendMessage/{green_token}"
            payload = {"chatId": f"{clean_phone}@c.us", "message": message}
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                msg_id = str(data.get("idMessage") or msg_id)
                provider = "Green API (Live)"
        except Exception as e:
            logger.warning(f"Green API dispatch error: {e}")
            provider = "Green API (Fallback)"

    # Try Twilio WhatsApp
    elif twilio_sid and twilio_token:
        try:
            import base64
            url = f"https://api.twilio.com/2010-04-01/Accounts/{twilio_sid}/Messages.json"
            post_data = urllib.parse.urlencode({
                "From": f"whatsapp:{twilio_from}",
                "To": f"whatsapp:+{clean_phone}",
                "Body": message,
            }).encode("utf-8")
            auth_str = base64.b64encode(f"{twilio_sid}:{twilio_token}".encode("utf-8")).decode("utf-8")
            req = urllib.request.Request(
                url,
                data=post_data,
                headers={"Authorization": f"Basic {auth_str}", "Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                msg_id = str(data.get("sid") or msg_id)
                provider = "Twilio WhatsApp (Live)"
        except Exception as e:
            logger.warning(f"Twilio WhatsApp dispatch error: {e}")
            provider = "Twilio WhatsApp (Fallback)"

    result = {
        "status": "sent",
        "provider": provider,
        "message_id": msg_id,
        "recipient": to_phone,
        "timestamp": datetime.utcnow().isoformat(),
    }

    _log_tool_execution(
        tenant_id=tenant_id,
        lead_id=lead_id,
        session_id=session_id,
        tool_name="send_whatsapp",
        input_data={"to": to_phone, "message_preview": message[:120]},
        output_data=result,
        status="completed",
    )
    return result


# =====================================================================
# 3. send_email (Resend / SendGrid / SMTP)
# =====================================================================
def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: Optional[str] = None,
    lead_id: Optional[int] = None,
    session_id: Optional[str] = None,
    tenant_id: str = "default",
) -> Dict[str, Any]:
    """
    Dispatch transactional email via Resend, SendGrid, or SMTP.
    Simulated sandbox fallback when keys are absent.
    """
    resend_key = os.getenv("RESEND_API_KEY")
    sendgrid_key = os.getenv("SENDGRID_API_KEY")
    from_email = os.getenv("SENDER_EMAIL") or "team@bawdicsoft.com"
    gmail_app_password = os.getenv("GMAIL_APP_PASSWORD")

    provider = "simulated_email"
    email_id = f"email_{int(datetime.utcnow().timestamp())}"
    delivery_status = "simulated"
    delivery_error = None

    if from_email.lower().endswith("@gmail.com"):
        if not gmail_app_password:
            provider = "Gmail SMTP (Not Configured)"
            delivery_status = "failed"
            delivery_error = "Set GMAIL_APP_PASSWORD to enable Gmail SMTP delivery."
        else:
            try:
                message = EmailMessage()
                message["From"] = from_email
                message["To"] = to_email
                message["Subject"] = subject
                message.set_content(text_content or subject)
                message.add_alternative(html_content, subtype="html")

                with smtplib.SMTP("smtp.gmail.com", 587, timeout=8) as smtp:
                    smtp.ehlo()
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                    smtp.login(from_email, gmail_app_password)
                    smtp.send_message(message)
                provider = "Gmail SMTP (Live)"
                delivery_status = "sent"
            except Exception as e:
                logger.warning(f"Gmail SMTP error: {e}")
                provider = "Gmail SMTP (Failed)"
                delivery_status = "failed"
                delivery_error = "Gmail SMTP request failed; check the application logs."

    # Use Resend for senders on a verified custom domain.
    elif resend_key:
        try:
            resend.api_key = resend_key
            response = resend.Emails.send({
                "from": from_email,
                "to": [to_email],
                "subject": subject,
                "html": html_content,
                "text": text_content or subject,
            })
            email_id = str(response.get("id") or email_id)
            provider = "Resend (Live)"
            delivery_status = "sent"
        except Exception as e:
            logger.warning(f"Resend error: {e}")
            provider = "Resend (Failed)"
            delivery_status = "failed"
            delivery_error = "Email provider request failed; check the application logs."

    # Try SendGrid
    elif sendgrid_key:
        try:
            url = "https://api.sendgrid.com/v3/mail/send"
            payload = {
                "personalizations": [{"to": [{"email": to_email}]}],
                "from": {"email": from_email},
                "subject": subject,
                "content": [{"type": "text/html", "value": html_content}],
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Authorization": f"Bearer {sendgrid_key}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                provider = "SendGrid (Live)"
                delivery_status = "sent"
        except Exception as e:
            logger.warning(f"SendGrid error: {e}")
            provider = "SendGrid (Failed)"
            delivery_status = "failed"
            delivery_error = "Email provider request failed; check the application logs."

    result = {
        "status": delivery_status,
        "provider": provider,
        "email_id": email_id,
        "recipient": to_email,
        "subject": subject,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if delivery_error:
        result["error"] = delivery_error

    _log_tool_execution(
        tenant_id=tenant_id,
        lead_id=lead_id,
        session_id=session_id,
        tool_name="send_email",
        input_data={"to": to_email, "subject": subject},
        output_data=result,
        status=delivery_status,
    )
    return result


# =====================================================================
# 4. notify_team (WhatsApp alert / Webhook)
# =====================================================================
def notify_team(
    event: str,
    details: Dict[str, Any],
    lead_id: Optional[int] = None,
    session_id: Optional[str] = None,
    tenant_id: str = "default",
) -> Dict[str, Any]:
    """
    Send high-priority notification to the BawdicSoft sales team
    via WhatsApp (Green API/Twilio) or Team Webhook (Slack/Discord/Teams).
    """
    team_phone = os.getenv("SALES_TEAM_WHATSAPP")
    webhook_url = os.getenv("SALES_TEAM_WEBHOOK_URL")

    summary_text = (
        f"🚨 *Sales Team Alert: {event.upper()}*\n"
        f"Client: {details.get('customer_name') or details.get('attendee') or 'Interested Client'}\n"
        f"Contact: {details.get('contact') or details.get('email') or details.get('phone')}\n"
        f"Details: {details.get('slot') or details.get('deal_summary') or details.get('last_message') or 'Action requested'}"
    )

    channels_dispatched = []

    if team_phone:
        send_whatsapp(to_phone=team_phone, message=summary_text, lead_id=lead_id, session_id=session_id, tenant_id=tenant_id)
        channels_dispatched.append(f"whatsapp:{team_phone}")

    if webhook_url:
        try:
            payload = {"text": summary_text, "event": event, "details": details}
            req = urllib.request.Request(
                webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5):
                channels_dispatched.append("webhook")
        except Exception as e:
            logger.warning(f"Webhook alert failed: {e}")

    if not channels_dispatched:
        channels_dispatched.append("internal_audit_log")

    result = {
        "status": "alert_dispatched",
        "event": event,
        "channels": channels_dispatched,
        "summary": summary_text[:120],
        "timestamp": datetime.utcnow().isoformat(),
    }

    _log_tool_execution(
        tenant_id=tenant_id,
        lead_id=lead_id,
        session_id=session_id,
        tool_name="notify_team",
        input_data={"event": event, "details": details},
        output_data=result,
        status="completed",
    )
    return result


# =====================================================================
# 5. update_lead (Database score, stage & qualification updates)
# =====================================================================
def update_lead(
    lead_id: int,
    updates: Dict[str, Any],
    session_id: Optional[str] = None,
    tenant_id: str = "default",
) -> Dict[str, Any]:
    """Update lead score, sales stage, or status in PostgreSQL/SQLite."""
    init_db()
    with SessionLocal() as db:
        lead = db.query(LeadModel).filter_by(tenant_id=tenant_id, id=lead_id).first()
        if not lead:
            return {"status": "not_found", "lead_id": lead_id}

        for field in ("lead_score", "sales_stage", "sales_tactic", "deal_summary", "buyer_intent", "preferred_slot", "notes"):
            if field in updates and updates[field] is not None:
                setattr(lead, field, updates[field])

        lead.updated_at = datetime.utcnow()
        db.commit()

        result = {
            "status": "updated",
            "lead_id": lead_id,
            "lead_score": lead.lead_score,
            "sales_stage": lead.sales_stage,
            "updated_at": lead.updated_at.isoformat(),
        }

    _log_tool_execution(
        tenant_id=tenant_id,
        lead_id=lead_id,
        session_id=session_id,
        tool_name="update_lead",
        input_data={"lead_id": lead_id, "updates": updates},
        output_data=result,
        status="completed",
    )
    return result


# =====================================================================
# Internal audit logger
# =====================================================================
def _log_tool_execution(
    tenant_id: str,
    lead_id: Optional[int],
    tool_name: str,
    input_data: Dict[str, Any],
    output_data: Dict[str, Any],
    status: str = "completed",
    session_id: Optional[str] = None,
):
    """Write tool execution to actions audit table."""
    try:
        init_db()
        with SessionLocal() as db:
            action = ActionModel(
                tenant_id=tenant_id,
                session_id=session_id,
                lead_id=lead_id,
                tool_name=tool_name,
                status=status,
                input_data=input_data,
                output_data=output_data,
                created_at=datetime.utcnow(),
            )
            db.add(action)
            db.commit()
    except Exception as e:
        logger.warning(f"Failed to record action log for {tool_name}: {e}")

