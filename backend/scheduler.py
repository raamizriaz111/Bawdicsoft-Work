"""
Background Job Scheduler & Follow-up Automation Engine for Universal Client Chatbot Sales Agent.
Implements the multi-day sequence:
  - Day 0: Instant confirmation email (1 min after lead capture)
  - Day 2: WhatsApp check-in ("Hey {name}, did you get a chance to review the notes?")
  - Day 5: Final email ("Last call — our consultation slots for this week are closing")
  - Cancel condition: If visitor replies or books a meeting, cancel all remaining scheduled jobs.

Uses APScheduler with database persistence (jobs table in PostgreSQL / SQLite).
"""

import logging
from html import escape
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session as DBSession

from backend.database import SessionLocal, init_db
from backend.models import JobModel, LeadModel, ActionModel
from backend.tools import send_email, send_whatsapp

logger = logging.getLogger("SalesAgentScheduler")

_scheduler = None
_scheduler_started = False


def schedule_followup_sequence(
    lead_id: int,
    tenant_id: str = "default",
    lead_data: Optional[Dict[str, Any]] = None,
    is_test_fast: bool = False,
) -> List[Dict[str, Any]]:
    """
    Schedule the 3-step follow-up sequence for a newly captured or qualified lead.
    - Day 0: Email confirmation (1 min)
    - Day 2: WhatsApp check-in (48 hours)
    - Day 5: Final closing email (120 hours)
    """
    if not lead_id:
        return []

    init_db()
    with SessionLocal() as db:
        # Avoid duplicate scheduling if active jobs already exist
        existing = db.query(JobModel).filter_by(
            tenant_id=tenant_id, lead_id=lead_id, status="pending"
        ).first()
        if existing:
            logger.info(f"[Scheduler] Pending jobs already exist for lead #{lead_id}. Skipping duplicate scheduling.")
            return []

        lead = db.query(LeadModel).filter_by(tenant_id=tenant_id, id=lead_id).first()
        name = (lead.name if lead and lead.name and lead.name != "Interested Visitor" else (lead_data or {}).get("name") or "there")
        email = (lead.email if lead and lead.email else (lead_data or {}).get("email"))
        phone = (lead.phone if lead and lead.phone else (lead_data or {}).get("phone"))
        biz_name = (lead.business_name if lead and lead.business_name else (lead_data or {}).get("business_name") or "BawdicSoft")
        specific_need = (lead.specific_need if lead and lead.specific_need else (lead_data or {}).get("specific_need") or "your project")

        now = datetime.utcnow()
        if is_test_fast:
            t_day0 = now + timedelta(seconds=10)
            t_day2 = now + timedelta(seconds=20)
            t_day5 = now + timedelta(seconds=30)
        else:
            t_day0 = now + timedelta(minutes=1)
            t_day2 = now + timedelta(days=2)
            t_day5 = now + timedelta(days=5)

        scheduled_jobs = []

        # 1. Day 0: Instant Confirmation Email
        if email:
            day0_payload = {
                "to_email": email,
                "name": name,
                "business_name": biz_name,
                "subject": f"Thank you for contacting {biz_name} — Next Steps",
                "content": (
                    f"Hi {name},\n\n"
                    f"Thank you for reaching out to {biz_name}! We've noted your interest in {specific_need}. "
                    f"Our senior engineering team is reviewing your requirements and will reach out shortly.\n\n"
                    f"Best regards,\n{biz_name} Sales Engineering"
                ),
            }
            job0 = JobModel(
                tenant_id=tenant_id,
                lead_id=lead_id,
                channel="email",
                step_number=0,
                status="pending",
                scheduled_at=t_day0,
                payload=day0_payload,
                created_at=now,
            )
            db.add(job0)
            scheduled_jobs.append(job0)

        # 2. Day 2: WhatsApp Check-in
        if phone:
            day2_payload = {
                "to_phone": phone,
                "name": name,
                "business_name": biz_name,
                "message": (
                    f"Hey {name}! Bilal from {biz_name} here — just wanted to check if you had a chance to "
                    f"review our notes on {specific_need}? Let me know if you'd like to set up a quick 15-minute consultation."
                ),
            }
            job2 = JobModel(
                tenant_id=tenant_id,
                lead_id=lead_id,
                channel="whatsapp",
                step_number=2,
                status="pending",
                scheduled_at=t_day2,
                payload=day2_payload,
                created_at=now,
            )
            db.add(job2)
            scheduled_jobs.append(job2)

        # 3. Day 5: Final Closing Email
        if email:
            day5_payload = {
                "to_email": email,
                "name": name,
                "business_name": biz_name,
                "subject": f"Following up on your {specific_need} inquiry with {biz_name}",
                "content": (
                    f"Hi {name},\n\n"
                    f"I'm following up to see if you're still looking to proceed with {specific_need}. "
                    f"Our engineering consultation slots for this week are closing up. "
                    f"If you'd like to reserve time with our team, feel free to reply directly to this email.\n\n"
                    f"Best,\n{biz_name} Team"
                ),
            }
            job5 = JobModel(
                tenant_id=tenant_id,
                lead_id=lead_id,
                channel="email",
                step_number=5,
                status="pending",
                scheduled_at=t_day5,
                payload=day5_payload,
                created_at=now,
            )
            db.add(job5)
            scheduled_jobs.append(job5)

        db.commit()

        # Log scheduled action to audit table
        action = ActionModel(
            tenant_id=tenant_id,
            lead_id=lead_id,
            tool_name="schedule_followups",
            status="scheduled",
            input_data={"lead_id": lead_id, "jobs_count": len(scheduled_jobs)},
            output_data={"steps_scheduled": [j.step_number for j in scheduled_jobs]},
            created_at=now,
        )
        db.add(action)
        db.commit()

        logger.info(f"[Scheduler] Enqueued {len(scheduled_jobs)} follow-up jobs for lead #{lead_id}")
        return [_job_to_dict(j) for j in scheduled_jobs]


def cancel_pending_jobs(
    lead_id: int,
    tenant_id: str = "default",
    reason: str = "client_replied",
) -> int:
    """
    Cancel all pending jobs for a lead (e.g. when visitor replies or books a meeting).
    Returns count of jobs cancelled.
    """
    if not lead_id:
        return 0

    init_db()
    with SessionLocal() as db:
        pending_jobs = db.query(JobModel).filter_by(
            tenant_id=tenant_id, lead_id=lead_id, status="pending"
        ).all()

        if not pending_jobs:
            return 0

        cancelled_count = len(pending_jobs)
        now = datetime.utcnow()
        for job in pending_jobs:
            job.status = "cancelled"
            job.executed_at = now
            p = dict(job.payload or {})
            p["cancelled_reason"] = reason
            p["cancelled_at"] = now.isoformat()
            job.payload = p

        action = ActionModel(
            tenant_id=tenant_id,
            lead_id=lead_id,
            tool_name="cancel_followups",
            status="cancelled",
            input_data={"lead_id": lead_id, "reason": reason},
            output_data={"jobs_cancelled": cancelled_count},
            created_at=now,
        )
        db.add(action)
        db.commit()

        logger.info(f"[Scheduler] Cancelled {cancelled_count} pending jobs for lead #{lead_id} (Reason: {reason})")
        return cancelled_count


def process_due_jobs() -> int:
    """
    Check database for all due pending jobs and dispatch them.
    SELECT * FROM jobs WHERE status = 'pending' AND scheduled_at <= NOW()
    Returns count of jobs processed.
    """
    init_db()
    now = datetime.utcnow()
    processed_count = 0

    with SessionLocal() as db:
        due_jobs = db.query(JobModel).filter(
            JobModel.status == "pending",
            JobModel.scheduled_at <= now,
        ).order_by(JobModel.scheduled_at.asc()).all()

        if not due_jobs:
            return 0

        for job in due_jobs:
            payload = job.payload or {}
            success = False
            error_msg = None

            try:
                if job.channel == "email":
                    to_email = payload.get("to_email")
                    if to_email:
                        content = str(payload.get("content") or "")
                        result = send_email(
                            to_email=to_email,
                            subject=payload.get("subject", "Follow-up"),
                            html_content=f"<p>{escape(content)}</p>",
                            text_content=content,
                            lead_id=job.lead_id,
                            tenant_id=job.tenant_id,
                        )
                        success = result.get("status") in ("sent", "simulated")
                        if not success:
                            error_msg = result.get("error", "Email delivery failed")
                    else:
                        error_msg = "Missing recipient email"

                elif job.channel == "whatsapp":
                    to_phone = payload.get("to_phone")
                    if to_phone:
                        send_whatsapp(
                            to_phone=to_phone,
                            message=payload.get("message", ""),
                            lead_id=job.lead_id,
                            tenant_id=job.tenant_id,
                        )
                        success = True
                    else:
                        error_msg = "Missing recipient phone"

                else:
                    error_msg = f"Unknown channel '{job.channel}'"

            except Exception as e:
                logger.error(f"[Scheduler] Error executing job #{job.id}: {e}")
                error_msg = str(e)

            job.executed_at = datetime.utcnow()
            if success:
                job.status = "completed"
                processed_count += 1
            else:
                job.status = "failed"
                p = dict(job.payload or {})
                p["error"] = error_msg
                job.payload = p

        db.commit()

    if processed_count > 0:
        logger.info(f"[Scheduler] Successfully processed {processed_count} due jobs")
    return processed_count


def get_jobs(
    tenant_id: str = "default",
    lead_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Retrieve audit log of jobs for inspection and management."""
    init_db()
    with SessionLocal() as db:
        q = db.query(JobModel).filter_by(tenant_id=tenant_id)
        if lead_id:
            q = q.filter_by(lead_id=lead_id)
        if status:
            q = q.filter_by(status=status)
        jobs = q.order_by(JobModel.created_at.desc()).limit(limit).all()
        return [_job_to_dict(j) for j in jobs]


def start_scheduler():
    """Start APScheduler in a background thread."""
    global _scheduler, _scheduler_started
    if _scheduler_started:
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler(daemon=True)
        # Check every 30 seconds for due follow-up jobs
        _scheduler.add_job(
            process_due_jobs,
            "interval",
            seconds=30,
            id="process_due_jobs_interval",
            replace_existing=True,
        )
        _scheduler.start()
        _scheduler_started = True
        logger.info("[Scheduler] APScheduler background engine started (polling every 30s)")
    except Exception as e:
        logger.warning(f"[Scheduler] Could not start APScheduler: {e}. Will process jobs synchronously.")


def stop_scheduler():
    """Stop the scheduler background thread."""
    global _scheduler, _scheduler_started
    if _scheduler and _scheduler_started:
        try:
            _scheduler.shutdown(wait=False)
            _scheduler_started = False
            logger.info("[Scheduler] APScheduler background engine stopped")
        except Exception as e:
            logger.warning(f"[Scheduler] Error stopping scheduler: {e}")


def _job_to_dict(job: JobModel) -> Dict[str, Any]:
    return {
        "id": job.id,
        "tenant_id": job.tenant_id,
        "lead_id": job.lead_id,
        "channel": job.channel,
        "step_number": job.step_number,
        "status": job.status,
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
        "executed_at": job.executed_at.isoformat() if job.executed_at else None,
        "payload": job.payload or {},
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }
