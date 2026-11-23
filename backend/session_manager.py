"""
Session and conversation history manager for Universal Client Chatbot Studio.
Backed by PostgreSQL/SQLAlchemy with multi-tenant isolation.
Preserves all legacy public function signatures so app.py and CLI operate unchanged.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session as DBSession

from backend.database import SessionLocal, init_db
from backend.models import SessionModel, MessageModel

DATA_DIR = Path(__file__).parent.parent / "data"
LEGACY_SESSIONS_FILE = DATA_DIR / "sessions.json"

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

def init_session_storage():
    """Initialize database tables and migrate legacy sessions.json if present."""
    init_db()
    _migrate_legacy_sessions()

def _migrate_legacy_sessions():
    """Migrate legacy sessions.json into PostgreSQL if DB is empty."""
    if not LEGACY_SESSIONS_FILE.exists():
        return
    try:
        with SessionLocal() as db:
            count = db.query(SessionModel).count()
            if count > 0:
                return  # DB already has sessions

            with open(LEGACY_SESSIONS_FILE, "r", encoding="utf-8") as f:
                raw_data = json.load(f)

            if not isinstance(raw_data, dict):
                return

            for sid, sdata in raw_data.items():
                if not isinstance(sdata, dict):
                    continue
                sess_obj = SessionModel(
                    tenant_id="default",
                    session_id=sid,
                    is_returning=bool(sdata.get("is_returning", False)),
                    user_profile=_ensure_profile_defaults(sdata.get("user_profile")),
                    created_at=datetime.fromisoformat(sdata["created_at"]) if sdata.get("created_at") else datetime.utcnow(),
                    last_active=datetime.fromisoformat(sdata["last_active"]) if sdata.get("last_active") else datetime.utcnow(),
                )
                db.add(sess_obj)
                db.flush()

                for msg in sdata.get("messages", []):
                    if isinstance(msg, dict) and msg.get("role") and msg.get("content"):
                        m_obj = MessageModel(
                            tenant_id="default",
                            session_id=sid,
                            db_session_id=sess_obj.id,
                            role=msg["role"],
                            content=msg["content"],
                            created_at=datetime.fromisoformat(msg["timestamp"]) if msg.get("timestamp") else datetime.utcnow(),
                        )
                        db.add(m_obj)

            db.commit()
    except Exception as e:
        print(f"[SessionManager] Legacy migration note: {e}")

def _session_to_dict(sess: SessionModel, messages: Optional[List[MessageModel]] = None) -> Dict[str, Any]:
    """Convert SessionModel to dictionary matching original session_manager contract."""
    msg_list = []
    if messages is not None:
        for m in messages:
            msg_list.append({
                "role": m.role,
                "content": m.content,
                "timestamp": m.created_at.isoformat() if m.created_at else datetime.utcnow().isoformat()
            })
    return {
        "session_id": sess.session_id,
        "created_at": sess.created_at.isoformat() if sess.created_at else datetime.utcnow().isoformat(),
        "last_active": sess.last_active.isoformat() if sess.last_active else datetime.utcnow().isoformat(),
        "is_returning": sess.is_returning,
        "user_profile": _ensure_profile_defaults(sess.user_profile),
        "messages": msg_list,
        "tenant_id": sess.tenant_id,
    }

def get_or_create_session(session_id: str, tenant_id: str = "default") -> Dict[str, Any]:
    """Retrieve an existing session or initialize a new one in the database."""
    init_db()
    with SessionLocal() as db:
        sess = db.query(SessionModel).filter_by(tenant_id=tenant_id, session_id=session_id).first()
        now = datetime.utcnow()
        if sess:
            sess.last_active = now
            sess.is_returning = True
            sess.user_profile = _ensure_profile_defaults(sess.user_profile)
            db.commit()
            messages = db.query(MessageModel).filter_by(tenant_id=tenant_id, session_id=session_id).order_by(MessageModel.id.asc()).all()
            return _session_to_dict(sess, messages)
        else:
            new_sess = SessionModel(
                tenant_id=tenant_id,
                session_id=session_id,
                is_returning=False,
                user_profile=_default_user_profile(),
                created_at=now,
                last_active=now,
            )
            db.add(new_sess)
            db.commit()
            return _session_to_dict(new_sess, [])

def reset_session(session_id: str, tenant_id: str = "default") -> Dict[str, Any]:
    """Reset a session and its message history to simulate a brand-new visitor."""
    init_db()
    with SessionLocal() as db:
        now = datetime.utcnow()
        db.query(MessageModel).filter_by(tenant_id=tenant_id, session_id=session_id).delete()
        sess = db.query(SessionModel).filter_by(tenant_id=tenant_id, session_id=session_id).first()
        if sess:
            sess.user_profile = _default_user_profile()
            sess.is_returning = False
            sess.created_at = now
            sess.last_active = now
        else:
            sess = SessionModel(
                tenant_id=tenant_id,
                session_id=session_id,
                is_returning=False,
                user_profile=_default_user_profile(),
                created_at=now,
                last_active=now,
            )
            db.add(sess)
        db.commit()
        return _session_to_dict(sess, [])

def update_session_profile(
    session_id: str,
    name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    sales_stage: Optional[str] = None,
    qualification: Optional[Dict[str, Any]] = None,
    emotion_entry: Optional[Dict[str, str]] = None,
    tenant_id: str = "default",
):
    """Update known user profile, sales stage, qualification fields, and emotion trajectory."""
    init_db()
    with SessionLocal() as db:
        sess = db.query(SessionModel).filter_by(tenant_id=tenant_id, session_id=session_id).first()
        if not sess:
            sess = SessionModel(
                tenant_id=tenant_id,
                session_id=session_id,
                is_returning=False,
                user_profile=_default_user_profile(),
            )
            db.add(sess)
            db.flush()

        profile = _ensure_profile_defaults(sess.user_profile)
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

        sess.user_profile = dict(profile)
        sess.last_active = datetime.utcnow()
        db.commit()

def append_session_message(session_id: str, role: str, content: str, tenant_id: str = "default"):
    """Append a message to the persistent session history in the database."""
    init_db()
    with SessionLocal() as db:
        sess = db.query(SessionModel).filter_by(tenant_id=tenant_id, session_id=session_id).first()
        now = datetime.utcnow()
        if not sess:
            sess = SessionModel(
                tenant_id=tenant_id,
                session_id=session_id,
                is_returning=False,
                user_profile=_default_user_profile(),
                created_at=now,
                last_active=now,
            )
            db.add(sess)
            db.flush()
        else:
            sess.last_active = now

        msg = MessageModel(
            tenant_id=tenant_id,
            session_id=session_id,
            db_session_id=sess.id,
            role=role,
            content=content,
            created_at=now,
        )
        db.add(msg)
        db.commit()

def get_session_history(session_id: str, tenant_id: str = "default") -> List[Dict[str, str]]:
    """Return list of messages formatted for LLM consumption [{'role': ..., 'content': ...}]."""
    init_db()
    with SessionLocal() as db:
        messages = db.query(MessageModel).filter_by(
            tenant_id=tenant_id, session_id=session_id
        ).order_by(MessageModel.id.asc()).all()
        return [{"role": m.role, "content": m.content} for m in messages]

def get_total_chats_count(tenant_id: str = "default") -> int:
    """Return total number of chat sessions that have at least one message for the tenant."""
    init_db()
    with SessionLocal() as db:
        distinct_sessions = db.query(MessageModel.session_id).filter_by(tenant_id=tenant_id).distinct().count()
        return distinct_sessions
