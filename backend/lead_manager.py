"""
Lead extraction, persistence, and statistics manager for Universal Client Chatbot Studio.
Backed by PostgreSQL/SQLAlchemy with multi-tenant isolation.
Preserves all legacy public function signatures so app.py and CLI operate unchanged.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session as DBSession

from backend.database import SessionLocal, init_db
from backend.models import LeadModel

DATA_DIR = Path(__file__).parent.parent / "data"
LEGACY_LEADS_FILE = DATA_DIR / "leads.json"

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
PHONE_CANDIDATE_REGEX = re.compile(
    r"(?<![A-Za-z0-9.,$])((?:\+?\d|\(\d{2,4}\))[\d\s\-().]{5,20}\d)(?![A-Za-z0-9,])"
)
PHONE_CONTEXT_WORDS = {
    "phone", "number", "mobile", "cell", "whatsapp", "call", "tel", "telephone", "contact", "reach", "sms", "text"
}
CURRENCY_MARKERS = ("pkr", "rs", "usd", "eur", "gbp", "aed", "inr", "$", "€", "£", "/-")

INVALID_NAMES = {
    "hi", "hello", "hey", "yes", "no", "sure", "ok", "okay", "thanks", "thank",
    "please", "fine", "cool", "test", "demo", "website", "blockchain", "ai",
    "software", "app", "quote", "price", "pricing", "service", "services",
    "product", "products", "project", "work", "help", "info", "question",
    "ceo", "founder", "director", "manager", "lead", "leads", "user", "guest",
    "interested", "looking", "back", "later", "tomorrow", "today", "now", "soon",
    "urgent", "asap", "confused", "frustrated", "skeptical", "worried", "ready",
    "not", "available", "free", "busy", "here", "there", "someone", "anyone",
    "human", "agent", "doctor", "dentist", "representative", "person", "support",
    "client", "customer", "visitor", "friend", "phone", "email", "number",
    "mobile", "cell", "whatsapp", "call", "contact", "booking", "appointment",
    "consultation", "schedule", "visit", "too", "expensive", "very", "quite",
    "really", "pretty", "maybe", "nope", "nah", "pass", "why", "how", "what",
    "when", "where", "which", "who", "dont", "don't", "never", "neither",
    "intersted", "intrested", "intereseted", "mad", "angry", "happy", "sad",
    "serious", "joking", "kidding", "asking", "wondering", "checking", "browsing",
    "planning", "building", "creating", "developing", "launching", "starting",
    "thinking", "trying", "hoping", "working", "searching", "exploring", "going",
    "wanting", "needing", "willing", "running", "testing", "selling", "buying",
    "sorry", "oops", "apologies", "pardon", "actually", "correct", "corrected",
    "fixed", "updated", "typo", "mistake", "try", "again", "done", "sent",
    "gmail", "yahoo", "outlook", "hotmail", "icloud", "its", "thats"
}

NON_NAME_WORDS = INVALID_NAMES | {
    "and", "my", "mail", "is", "are", "was", "am", "the", "a", "an", "with",
    "at", "on", "in", "to", "for", "from", "of", "by", "or", "as", "it",
    "this", "that", "these", "those", "you", "your", "me", "we", "our", "us",
    "send", "share", "reach", "follow", "give", "take", "need", "want", "details",
    "dental", "teeth", "tooth", "crown", "crowns", "implant", "implants",
    "veneer", "veneers", "whitening", "braces", "aligner", "aligners", "canal",
    "cleaning", "checkup", "exam", "clinic", "office", "location", "address",
    "hours", "timing", "timings", "package", "packages", "discount", "offer",
    "installment", "installments", "karachi", "clifton", "dha", "morning",
    "afternoon", "evening", "weekend", "monday", "tuesday", "wednesday",
    "thursday", "friday", "saturday", "sunday", "good", "bad", "great",
    "over", "right", "up", "down", "look", "stay", "come", "get", "just", "still"
}

def init_lead_storage():
    """Ensure database tables exist and migrate legacy leads.json if present."""
    init_db()
    _migrate_legacy_leads()

def _migrate_legacy_leads():
    """Migrate legacy leads.json into PostgreSQL if DB table is empty."""
    if not LEGACY_LEADS_FILE.exists():
        return
    try:
        with SessionLocal() as db:
            count = db.query(LeadModel).count()
            if count > 0:
                return  # DB already has leads

            with open(LEGACY_LEADS_FILE, "r", encoding="utf-8") as f:
                raw_leads = json.load(f)

            if not isinstance(raw_leads, list):
                return

            for item in raw_leads:
                if not isinstance(item, dict):
                    continue
                lead_obj = LeadModel(
                    tenant_id=item.get("tenant_id") or "default",
                    session_id=item.get("session_id"),
                    name=item.get("name") or "Interested Visitor",
                    email=item.get("email"),
                    phone=item.get("phone"),
                    interest=item.get("interest"),
                    specific_need=item.get("specific_need"),
                    budget=item.get("budget"),
                    timeline=item.get("timeline"),
                    preferred_slot=item.get("preferred_slot"),
                    objection_reason=item.get("objection_reason"),
                    lead_score=int(item.get("lead_score") or 0),
                    deal_summary=item.get("deal_summary"),
                    buyer_intent=item.get("buyer_intent"),
                    sales_stage=item.get("sales_stage"),
                    sales_tactic=item.get("sales_tactic"),
                    emotion=item.get("emotion"),
                    business_name=item.get("business_name") or "General Client",
                    notes=item.get("notes"),
                    created_at=datetime.fromisoformat(item["created_at"]) if item.get("created_at") else datetime.utcnow(),
                    updated_at=datetime.fromisoformat(item["updated_at"]) if item.get("updated_at") else datetime.utcnow(),
                )
                db.add(lead_obj)
            db.commit()
    except Exception as e:
        print(f"[LeadManager] Legacy migration note: {e}")

def _lead_to_dict(lead: LeadModel) -> Dict[str, Any]:
    """Convert LeadModel to dictionary matching original lead_manager contract."""
    return {
        "id": f"lead_{lead.id:04d}",
        "session_id": lead.session_id,
        "business_name": lead.business_name or "General Client",
        "name": lead.name,
        "email": lead.email,
        "phone": lead.phone,
        "interest": lead.interest,
        "specific_need": lead.specific_need,
        "budget": lead.budget,
        "timeline": lead.timeline,
        "preferred_slot": lead.preferred_slot,
        "objection_reason": lead.objection_reason,
        "lead_score": lead.lead_score,
        "deal_summary": lead.deal_summary,
        "buyer_intent": lead.buyer_intent,
        "sales_stage": lead.sales_stage,
        "sales_tactic": lead.sales_tactic,
        "emotion": lead.emotion,
        "notes": lead.notes,
        "created_at": lead.created_at.isoformat() if lead.created_at else datetime.utcnow().isoformat(),
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else datetime.utcnow().isoformat(),
        "tenant_id": lead.tenant_id,
    }

def is_valid_name(name_candidate: str) -> bool:
    """Validate that candidate string is an actual plausible name, not gibberish or noise."""
    if not name_candidate:
        return False
    clean = name_candidate.strip()
    if len(clean) < 2 or len(clean) > 40:
        return False
    if clean.lower() in INVALID_NAMES:
        return False
    vowels = set("aeiouyAEIOUY")
    if not any(char in vowels for char in clean):
        return False
    if not re.match(r"^[A-Za-z\s\-']+$", clean):
        return False
    return True

def canonical_phone_digits(phone: Optional[str]) -> str:
    """Return digits-only representation (stripping leading 00 international exit prefix) for matching."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00") and len(digits) > 10:
        digits = digits[2:]
    return digits

def phones_match(p1: Optional[str], p2: Optional[str]) -> bool:
    """Check if two raw phone numbers resolve to the same canonical digits."""
    d1 = canonical_phone_digits(p1)
    d2 = canonical_phone_digits(p2)
    if not d1 or not d2:
        return False
    if d1 == d2:
        return True
    if len(d1) >= 9 and len(d2) >= 9:
        return d1[-9:] == d2[-9:]
    return False

def validate_candidate_name(raw_name: Optional[str]) -> Optional[str]:
    """Clean and validate candidate name."""
    if not raw_name:
        return None
    name = raw_name.strip()
    name = re.sub(r"^(?:my name is|name is|i am|i'm|this is|call me)\s+", "", name, flags=re.IGNORECASE).strip()
    name = re.sub(r"[,\-_|].*$", "", name).strip()
    name = re.sub(r"[^A-Za-z\s\-']", "", name).strip()
    tokens = [t for t in name.split() if t.lower() not in NON_NAME_WORDS]
    if not tokens:
        return None
    filtered_name = " ".join(tokens)
    if not is_valid_name(filtered_name):
        return None
    return filtered_name.title()

def extract_phone_from_message(clean_msg: str, masked_email: Optional[str] = None) -> Optional[str]:
    """Extract phone number safely protecting prices, dates, times, and emails."""
    text_to_scan = clean_msg
    if masked_email:
        text_to_scan = text_to_scan.replace(masked_email, " ")

    matches = list(PHONE_CANDIDATE_REGEX.finditer(text_to_scan))
    if not matches:
        return None

    low_msg = clean_msg.lower()
    has_explicit_phone_ctx = any(re.search(r"\b" + re.escape(w) + r"\b", low_msg) for w in PHONE_CONTEXT_WORDS)

    for m in matches:
        cand = m.group(1).strip()
        start, end = m.start(), m.end()

        prefix = text_to_scan[max(0, start - 10):start].lower()
        suffix = text_to_scan[end:min(len(text_to_scan), end + 10)].lower()
        if any(marker in prefix or marker in suffix for marker in CURRENCY_MARKERS):
            continue
        if re.search(r":|\b(?:am|pm)\b", suffix) or ":" in cand:
            continue

        digits = re.sub(r"\D", "", cand)
        if len(digits) < 7 or len(digits) > 15:
            continue

        if len(digits) == 4 and not cand.startswith("+") and not cand.startswith("0"):
            continue

        if re.search(r"\b(?:suite|apt|room|building|floor)\s*#?$", prefix):
            continue

        if len(digits) >= 10:
            return cand
        if len(digits) >= 7 and (cand.startswith("+") or cand.startswith("0") or has_explicit_phone_ctx or "-" in cand or " " in cand):
            return cand

    return None

def detect_invalid_contact_attempt(
    message: str,
    found_email: Optional[str] = None,
    found_phone: Optional[str] = None,
    prev_assistant_msg: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    """Detect malformed emails and too-short phone submissions."""
    clean_msg = message.strip()
    if not clean_msg:
        return None

    if not found_email:
        malformed_tokens = re.findall(r"\b[A-Za-z0-9_.+-]+@\S*", clean_msg)
        for tok in malformed_tokens:
            tok_clean = tok.rstrip(".,;:!?'\"")
            if "@" not in tok_clean:
                continue
            parts = tok_clean.split("@", 1)
            domain = parts[1] if len(parts) > 1 else ""
            if not domain:
                return {
                    "type": "email",
                    "value": tok_clean,
                    "reason": "missing the domain after '@' (e.g. '@gmail.com')",
                }
            if "." not in domain or len(domain.rsplit(".", 1)[-1]) < 2:
                return {
                    "type": "email",
                    "value": tok_clean,
                    "reason": "missing a full domain extension such as '.com'",
                }

        missing_at = re.search(r"\b([a-z0-9_.+-]+(?:gmail|yahoo|outlook|hotmail|icloud)\.com)\b", clean_msg, re.IGNORECASE)
        if missing_at and "@" not in clean_msg:
            return {
                "type": "email",
                "value": missing_at.group(1),
                "reason": "missing '@' before the email provider",
            }

    if not found_phone:
        low = clean_msg.lower()
        has_phone_ctx = any(re.search(r"\b" + re.escape(w) + r"\b", low) for w in PHONE_CONTEXT_WORDS)
        asked_phone = bool(prev_assistant_msg and re.search(r"\b(phone|whatsapp|mobile|cell|number)\b", prev_assistant_msg, re.IGNORECASE))
        if has_phone_ctx or asked_phone:
            for m in re.finditer(r"(?<![A-Za-z0-9.,$])(\+?\d[\d\s\-().]{1,10}\d)(?![A-Za-z0-9,])", clean_msg):
                cand = m.group(1).strip()
                prefix = clean_msg[max(0, m.start() - 8):m.start()].lower()
                suffix = clean_msg[m.end():min(len(clean_msg), m.end() + 8)].lower()
                if any(marker in prefix or marker in suffix for marker in CURRENCY_MARKERS):
                    continue
                if re.search(r":|\b(?:am|pm)\b", suffix) or ":" in cand:
                    continue
                digits = re.sub(r"\D", "", cand)
                if 3 <= len(digits) <= 6:
                    if len(digits) == 4 and re.match(r"^(?:19|20)\d{2}$", digits) and not has_phone_ctx and not cand.startswith("0"):
                        continue
                    return {
                        "type": "phone",
                        "value": cand,
                        "reason": f"only {len(digits)} digits provided; a complete phone number is needed",
                    }

    return None

def extract_lead_from_message(
    message: str,
    prev_assistant_msg: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """Extract email, phone number, and customer name from user message."""
    clean_msg = message.strip()

    found_email = None
    email_match = EMAIL_REGEX.search(clean_msg)
    if email_match:
        cand_email = email_match.group(0).lower().rstrip(".,;:!?'\"")
        if "." in cand_email.split("@")[-1] and len(cand_email.split(".")[-1]) >= 2:
            found_email = cand_email

    found_phone = extract_phone_from_message(clean_msg, masked_email=found_email)

    found_name = None
    name_patterns = [
        r"(?:my name is|name is|name\s*[:\-]|i am|i'm|this is|call me)\s+([A-Za-z]+(?:\s+[A-Za-z]+){0,3})(?:\s+(?:and|my|email|phone|from|at|with|working|here)\b|[,.\-;!?]|\s*$)",
        r"^([A-Za-z]+(?:\s+[A-Za-z]+){0,2})\s+here\b",
        r"^([A-Za-z]+(?:\s+[A-Za-z]+){0,2})\s*[,|\-]\s*(?:.*@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+|\+?\d|\(\d)",
    ]

    for pattern in name_patterns:
        match = re.search(pattern, clean_msg, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            validated = validate_candidate_name(candidate)
            if validated:
                found_name = validated
                break

    if not found_name and (found_email or found_phone):
        rem = clean_msg
        if found_email:
            rem = rem.replace(found_email, " ")
        if found_phone:
            rem = rem.replace(found_phone, " ")
        for noise in ("email", "phone", "number", "contact", "whatsapp", "is", ":", "-", ","):
            rem = re.sub(r"\b" + re.escape(noise) + r"\b", " ", rem, flags=re.IGNORECASE)
        cand = rem.strip()
        if cand and len(cand.split()) <= 3:
            validated = validate_candidate_name(cand)
            if validated:
                found_name = validated

    if not found_name and prev_assistant_msg:
        low_prev = prev_assistant_msg.lower()
        if any(p in low_prev for p in ("your name", "who am i speaking with", "may i have your name", "who is this")):
            first_clause = re.split(r"[,.?!\n]", clean_msg)[0].strip()
            validated = validate_candidate_name(first_clause)
            if validated and len(validated.split()) <= 3:
                found_name = validated

    return {
        "email": found_email,
        "phone": found_phone,
        "name": found_name
    }

def _is_substantive_summary(text: Optional[str], buyer_intent: Optional[str] = None) -> bool:
    """Return True if text has actual topic content rather than generic intent label."""
    if not text:
        return False
    low = text.strip().lower()
    placeholders = {
        "interested visitor", "verified lead", "general inquiry", "inquiry",
        "chat inquiry", "hot", "warm", "cold", "off_topic"
    }
    if low in placeholders:
        return False
    if buyer_intent and low == buyer_intent.lower():
        return False
    tokens = [w for w in re.findall(r"[a-z0-9]{3,}", low) if w not in {"the", "and", "for", "with", "lead", "deal", "summary"}]
    return len(tokens) >= 2

def save_lead(
    session_id: Optional[str] = None,
    name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    interest: Optional[str] = None,
    notes: Optional[str] = None,
    business_name: Optional[str] = None,
    emotion: Optional[str] = None,
    buyer_intent: Optional[str] = None,
    sales_tactic: Optional[str] = None,
    qualification: Optional[Dict[str, Any]] = None,
    tenant_id: str = "default",
) -> Dict[str, Any]:
    """Save or update a lead in the database with progressive qualification & contact merge."""
    init_db()

    clean_email = email.strip().lower() if email and email.strip() else None
    clean_phone = re.sub(r"\s+", " ", phone).strip() if phone and phone.strip() else None
    clean_name = validate_candidate_name(name)
    qual = qualification or {}
    now = datetime.utcnow()

    with SessionLocal() as db:
        existing_lead = None

        # 1. Match by email or phone within tenant
        if clean_email:
            existing_lead = db.query(LeadModel).filter_by(tenant_id=tenant_id, email=clean_email).first()
        if not existing_lead and clean_phone:
            candidates = db.query(LeadModel).filter_by(tenant_id=tenant_id).filter(LeadModel.phone.isnot(None)).all()
            for cand in candidates:
                if phones_match(cand.phone, clean_phone):
                    existing_lead = cand
                    break

        # 2. Match by active session within tenant
        if not existing_lead and session_id:
            candidates = db.query(LeadModel).filter_by(tenant_id=tenant_id, session_id=session_id).all()
            for cand in candidates:
                email_compat = not clean_email or not cand.email or cand.email == clean_email
                phone_compat = not clean_phone or not cand.phone or phones_match(cand.phone, clean_phone)
                if email_compat and phone_compat:
                    existing_lead = cand
                    break

        if existing_lead:
            if clean_name and (not existing_lead.name or existing_lead.name == "Interested Visitor"):
                existing_lead.name = clean_name
            if clean_email and not existing_lead.email:
                existing_lead.email = clean_email
            if clean_phone and not existing_lead.phone:
                existing_lead.phone = clean_phone
            if interest and (
                _is_substantive_summary(interest, buyer_intent)
                or not existing_lead.interest
                or existing_lead.interest == "General Inquiry"
            ):
                existing_lead.interest = interest
            if business_name:
                existing_lead.business_name = business_name
            if emotion:
                existing_lead.emotion = emotion
            if buyer_intent:
                intent_rank = {"off_topic": 0, "cold": 1, "warm": 2, "hot": 3}
                prev_intent = existing_lead.buyer_intent
                if intent_rank.get(buyer_intent, 0) >= intent_rank.get(prev_intent, 0):
                    existing_lead.buyer_intent = buyer_intent
            if sales_tactic:
                existing_lead.sales_tactic = sales_tactic

            for field in ("specific_need", "budget", "timeline", "preferred_slot", "objection_reason", "sales_stage", "deal_summary"):
                val = qual.get(field)
                if isinstance(val, str) and val.strip():
                    if field == "deal_summary" and existing_lead.deal_summary and not _is_substantive_summary(val, buyer_intent):
                        continue
                    setattr(existing_lead, field, val.strip())

            if isinstance(qual.get("lead_score"), (int, float)):
                prev_score = int(existing_lead.lead_score or 0)
                existing_lead.lead_score = max(prev_score, max(0, min(100, int(qual["lead_score"]))))

            existing_lead.updated_at = now
            db.commit()
            return _lead_to_dict(existing_lead)
        else:
            if not clean_email and not clean_phone:
                raise ValueError("At least an email or phone number is required to create a new lead.")
            raw_score = qual.get("lead_score")
            lead_score = max(0, min(100, int(raw_score))) if isinstance(raw_score, (int, float)) else 75

            new_lead = LeadModel(
                tenant_id=tenant_id,
                session_id=session_id,
                name=clean_name or "Interested Visitor",
                email=clean_email,
                phone=clean_phone,
                interest=interest or "General Inquiry",
                notes=notes or "Captured via Chatbot",
                emotion=emotion or "curious",
                buyer_intent=buyer_intent or "hot",
                sales_tactic=sales_tactic or "Direct Lead Close",
                sales_stage=qual.get("sales_stage") or "post_capture",
                specific_need=qual.get("specific_need"),
                budget=qual.get("budget"),
                timeline=qual.get("timeline"),
                preferred_slot=qual.get("preferred_slot"),
                objection_reason=qual.get("objection_reason"),
                lead_score=lead_score,
                deal_summary=qual.get("deal_summary") or interest or "Verified Lead",
                business_name=business_name or "General Client",
                created_at=now,
                updated_at=now,
            )
            db.add(new_lead)
            db.commit()
            return _lead_to_dict(new_lead)

def get_all_leads(tenant_id: str = "default") -> List[Dict[str, Any]]:
    """Retrieve all leads for a tenant ordered by latest first."""
    init_db()
    with SessionLocal() as db:
        leads = db.query(LeadModel).filter_by(tenant_id=tenant_id).order_by(LeadModel.id.desc()).all()
        return [_lead_to_dict(item) for item in leads]

def delete_lead_by_id(lead_id: str, tenant_id: str = "default") -> bool:
    """Remove a single lead by id (supports 'lead_0001' or integer string) and return success status."""
    if not lead_id:
        return False
    init_db()
    try:
        numeric_id = int(str(lead_id).lower().replace("lead_", ""))
    except ValueError:
        return False

    with SessionLocal() as db:
        lead = db.query(LeadModel).filter_by(tenant_id=tenant_id, id=numeric_id).first()
        if not lead:
            return False
        db.delete(lead)
        db.commit()
        return True

def clear_all_leads(tenant_id: str = "default"):
    """Clear all captured leads for a tenant."""
    init_db()
    with SessionLocal() as db:
        db.query(LeadModel).filter_by(tenant_id=tenant_id).delete()
        db.commit()
