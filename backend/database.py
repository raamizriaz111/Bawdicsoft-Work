"""
Database engine and session management for Universal Client Chatbot Studio.
Supports PostgreSQL (production) with automatic fallback to local SQLite for zero-config local dev.
"""

import os
from pathlib import Path
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SQLITE_PATH = DATA_DIR / "chatbot.db"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if not DATABASE_URL:
    DATABASE_URL = f"sqlite:///{DEFAULT_SQLITE_PATH}"

# Fix legacy 'postgres://' URLs emitted by some cloud hosts (Render, Heroku, Supabase)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db() -> Generator[Session, None, None]:
    """Dependency / context provider yielding a SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Create all tables and seed default tenant if not exists."""
    from backend import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    
    # Ensure default tenant exists
    with SessionLocal() as db:
        default_tenant = db.query(models.Tenant).filter_by(id="default").first()
        if not default_tenant:
            default_tenant = models.Tenant(
                id="default",
                name="BawdicSoft",
                slug="bawdicsoft"
            )
            db.add(default_tenant)
            db.commit()
