"""
SQLAlchemy models for Universal Client Chatbot Studio.
Implements multi-tenant schema with tenant_id on every table.
Tables: tenants, visitors, sessions, messages, leads, actions, jobs.
"""

from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    JSON,
    Index
)
from sqlalchemy.orm import relationship
from backend.database import Base

class Tenant(Base):
    """Business or client account hosting the chatbot."""
    __tablename__ = "tenants"

    id = Column(String(64), primary_key=True)  # e.g. "default", "bawdicsoft"
    name = Column(String(128), nullable=False)
    slug = Column(String(64), unique=True, nullable=False, index=True)
    domain = Column(String(256), nullable=True)
    bot_config = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    visitors = relationship("Visitor", back_populates="tenant", cascade="all, delete-orphan")
    sessions = relationship("SessionModel", back_populates="tenant", cascade="all, delete-orphan")
    messages = relationship("MessageModel", back_populates="tenant", cascade="all, delete-orphan")
    leads = relationship("LeadModel", back_populates="tenant", cascade="all, delete-orphan")
    actions = relationship("ActionModel", back_populates="tenant", cascade="all, delete-orphan")
    jobs = relationship("JobModel", back_populates="tenant", cascade="all, delete-orphan")


class Visitor(Base):
    """End-user browser or caller recognized across multiple sessions."""
    __tablename__ = "visitors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    visitor_cookie_id = Column(String(128), nullable=False, index=True)
    name = Column(String(128), nullable=True)
    email = Column(String(256), nullable=True, index=True)
    phone = Column(String(64), nullable=True, index=True)
    
    # Persistent cross-session memory
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="SET NULL"), nullable=True)
    past_summary = Column(Text, nullable=True)  # Short 1-2 sentence recap of past discussions
    sales_stage = Column(String(64), nullable=True)  # Last active sales stage
    open_questions = Column(JSON, default=list, nullable=True)  # Pending scoping items
    total_sessions = Column(Integer, default=1, nullable=False)

    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    tenant = relationship("Tenant", back_populates="visitors")
    sessions = relationship("SessionModel", back_populates="visitor")
    leads = relationship("LeadModel", back_populates="visitor", foreign_keys="[LeadModel.visitor_id]")

    __table_args__ = (
        Index("ix_visitors_tenant_cookie", "tenant_id", "visitor_cookie_id", unique=True),
    )


class SessionModel(Base):
    """Individual conversation session (browser session or inbound thread)."""
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String(128), nullable=False, index=True)
    visitor_id = Column(Integer, ForeignKey("visitors.id", ondelete="SET NULL"), nullable=True)
    is_returning = Column(Boolean, default=False, nullable=False)
    user_profile = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_active = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    tenant = relationship("Tenant", back_populates="sessions")
    visitor = relationship("Visitor", back_populates="sessions")
    messages = relationship("MessageModel", back_populates="session", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_sessions_tenant_session", "tenant_id", "session_id", unique=True),
    )


class MessageModel(Base):
    """Individual chat turn within a session."""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String(128), nullable=False, index=True)
    db_session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True)
    role = Column(String(32), nullable=False)  # "user", "assistant", "system"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    tenant = relationship("Tenant", back_populates="messages")
    session = relationship("SessionModel", back_populates="messages")

    __table_args__ = (
        Index("ix_messages_tenant_session", "tenant_id", "session_id"),
    )


class LeadModel(Base):
    """Captured sales lead with qualification scores and contact info."""
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String(128), nullable=True, index=True)
    visitor_id = Column(Integer, ForeignKey("visitors.id", ondelete="SET NULL"), nullable=True)
    
    name = Column(String(128), nullable=False, default="Interested Visitor")
    email = Column(String(256), nullable=True, index=True)
    phone = Column(String(64), nullable=True, index=True)
    
    interest = Column(String(256), nullable=True)
    specific_need = Column(String(256), nullable=True)
    budget = Column(String(128), nullable=True)
    timeline = Column(String(128), nullable=True)
    preferred_slot = Column(String(128), nullable=True)
    objection_reason = Column(String(256), nullable=True)
    lead_score = Column(Integer, default=0, nullable=False)
    deal_summary = Column(Text, nullable=True)
    buyer_intent = Column(String(64), nullable=True)
    sales_stage = Column(String(64), nullable=True)
    sales_tactic = Column(String(128), nullable=True)
    emotion = Column(String(64), nullable=True)
    business_name = Column(String(128), nullable=True)
    notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    tenant = relationship("Tenant", back_populates="leads")
    visitor = relationship("Visitor", back_populates="leads", foreign_keys=[visitor_id])
    jobs = relationship("JobModel", back_populates="lead", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_leads_tenant_email", "tenant_id", "email"),
        Index("ix_leads_tenant_phone", "tenant_id", "phone"),
    )


class ActionModel(Base):
    """Audit log of every tool call executed by the agent."""
    __tablename__ = "actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String(128), nullable=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True)
    tool_name = Column(String(64), nullable=False)  # "book_meeting", "send_whatsapp", "send_email", "notify_team"
    input_data = Column(JSON, default=dict, nullable=False)
    output_data = Column(JSON, default=dict, nullable=False)
    status = Column(String(32), default="success", nullable=False)  # "success", "failed", "retried"
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    tenant = relationship("Tenant", back_populates="actions")

    __table_args__ = (
        Index("ix_actions_tenant_session", "tenant_id", "session_id"),
    )


class JobModel(Base):
    """Scheduled follow-up tasks (Day 0 email, Day 2 WhatsApp, Day 5 email)."""
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=True)
    channel = Column(String(32), nullable=False)  # "email", "whatsapp"
    step_number = Column(Integer, default=0, nullable=False)  # 0, 2, 5
    status = Column(String(32), default="pending", nullable=False)  # "pending", "completed", "cancelled", "failed"
    scheduled_at = Column(DateTime, nullable=False)
    executed_at = Column(DateTime, nullable=True)
    payload = Column(JSON, default=dict, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    tenant = relationship("Tenant", back_populates="jobs")
    lead = relationship("LeadModel", back_populates="jobs")

    __table_args__ = (
        Index("ix_jobs_tenant_status_sched", "tenant_id", "status", "scheduled_at"),
    )
