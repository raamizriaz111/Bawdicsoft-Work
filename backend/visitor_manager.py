"""
Visitor memory and returning customer manager for Universal Client Chatbot Studio.
Tracks persistent visitor_id cookies across sessions, links visitors to leads,
and stores concise 1-2 sentence summaries so returning visitors are greeted by name.
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session as DBSession

from backend.database import SessionLocal, init_db
from backend.models import Visitor, LeadModel, SessionModel

def get_or_create_visitor(
    visitor_cookie_id: str,
    tenant_id: str = "default",
    increment_session: bool = False,
) -> Dict[str, Any]:
    """Retrieve an existing visitor by cookie ID or create a new visitor record."""
    if not visitor_cookie_id:
        visitor_cookie_id = f"vis_anon_{datetime.utcnow().timestamp()}"

    init_db()
    with SessionLocal() as db:
        vis = db.query(Visitor).filter_by(
            tenant_id=tenant_id, visitor_cookie_id=visitor_cookie_id
        ).first()

        now = datetime.utcnow()
        if vis:
            vis.last_seen_at = now
            if increment_session:
                vis.total_sessions = int(vis.total_sessions or 1) + 1
            db.commit()
            return _visitor_to_dict(vis)
        else:
            new_vis = Visitor(
                tenant_id=tenant_id,
                visitor_cookie_id=visitor_cookie_id,
                total_sessions=1,
                first_seen_at=now,
                last_seen_at=now,
            )
            db.add(new_vis)
            db.commit()
            return _visitor_to_dict(new_vis)

def link_visitor_to_lead(
    visitor_cookie_id: str,
    lead_id: Optional[int] = None,
    name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    summary: Optional[str] = None,
    sales_stage: Optional[str] = None,
    tenant_id: str = "default",
):
    """Link captured contact and qualification memory to the persistent visitor record."""
    if not visitor_cookie_id:
        return

    init_db()
    with SessionLocal() as db:
        vis = db.query(Visitor).filter_by(
            tenant_id=tenant_id, visitor_cookie_id=visitor_cookie_id
        ).first()

        if not vis:
            vis = Visitor(
                tenant_id=tenant_id,
                visitor_cookie_id=visitor_cookie_id,
                first_seen_at=datetime.utcnow(),
                last_seen_at=datetime.utcnow(),
                total_sessions=1,
            )
            db.add(vis)

        if lead_id:
            vis.lead_id = lead_id
        if name and name.strip() and name != "Interested Visitor":
            vis.name = name.strip()
        if email and email.strip():
            vis.email = email.strip().lower()
        if phone and phone.strip():
            vis.phone = phone.strip()
        if summary and summary.strip() and len(summary.strip()) > 5:
            vis.past_summary = summary.strip()
        if sales_stage:
            vis.sales_stage = sales_stage

        vis.last_seen_at = datetime.utcnow()
        db.commit()

def update_visitor_summary(
    visitor_cookie_id: str,
    deal_summary: Optional[str],
    sales_stage: Optional[str] = None,
    open_questions: Optional[List[str]] = None,
    tenant_id: str = "default",
):
    """Store a short 1-2 sentence summary after session rather than full transcripts."""
    if not visitor_cookie_id or not deal_summary:
        return

    init_db()
    with SessionLocal() as db:
        vis = db.query(Visitor).filter_by(
            tenant_id=tenant_id, visitor_cookie_id=visitor_cookie_id
        ).first()
        if vis:
            if deal_summary and len(deal_summary.strip()) > 5:
                vis.past_summary = deal_summary.strip()
            if sales_stage:
                vis.sales_stage = sales_stage
            if open_questions:
                vis.open_questions = open_questions
            vis.last_seen_at = datetime.utcnow()
            db.commit()

def get_visitor_memory(
    visitor_cookie_id: str,
    tenant_id: str = "default",
) -> Dict[str, Any]:
    """Retrieve persistent memory profile for returning visitor detection."""
    if not visitor_cookie_id:
        return {"is_returning_visitor": False}

    init_db()
    with SessionLocal() as db:
        vis = db.query(Visitor).filter_by(
            tenant_id=tenant_id, visitor_cookie_id=visitor_cookie_id
        ).first()
        if not vis:
            return {"is_returning_visitor": False}
        return _visitor_to_dict(vis)

def _visitor_to_dict(vis: Visitor) -> Dict[str, Any]:
    """Convert Visitor model to memory dictionary."""
    is_returning = bool(
        (vis.total_sessions and vis.total_sessions > 1)
        or vis.name
        or vis.email
        or vis.phone
        or vis.past_summary
    )
    return {
        "id": vis.id,
        "tenant_id": vis.tenant_id,
        "visitor_cookie_id": vis.visitor_cookie_id,
        "name": vis.name,
        "email": vis.email,
        "phone": vis.phone,
        "lead_id": vis.lead_id,
        "past_summary": vis.past_summary,
        "sales_stage": vis.sales_stage,
        "open_questions": vis.open_questions or [],
        "total_sessions": vis.total_sessions or 1,
        "is_returning_visitor": is_returning,
        "first_seen_at": vis.first_seen_at.isoformat() if vis.first_seen_at else None,
        "last_seen_at": vis.last_seen_at.isoformat() if vis.last_seen_at else None,
    }
