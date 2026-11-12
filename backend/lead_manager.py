"""
Lead extraction, persistence, and statistics manager for Universal Client Chatbot Studio.
Guarantees clean lead validation, prevents false positives, and persists to local JSON.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

DATA_DIR = Path(__file__).parent.parent / "data"
LEADS_FILE = DATA_DIR / "leads.json"

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
    "thursday", "friday", "saturday", "sunday", "good", "bad", "great"
}

def init_lead_storage():
    """Ensure data directory and leads.json exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not LEADS_FILE.exists():
        with open(LEADS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2)

def is_valid_name(name_candidate: str) -> bool:
    """Validate that candidate string is an actual plausible name, not gibberish or noise."""
    if not name_candidate:
        return False
    
    clean = name_candidate.strip()
    if len(clean) < 2 or len(clean) > 40:
        return False

    if clean.lower() in INVALID_NAMES:
        return False

    # Check for vowels (prevents keyboard mash like 'jfjfjd')
    vowels = set("aeiouyAEIOUY")
    if not any(char in vowels for char in clean):
        return False

    # Must contain only alphabetic characters, spaces, hyphens
    if not re.match(r"^[A-Za-z\s\-']+$", clean):
        return False

    return True

def canonical_phone_digits(phone: Optional[str]) -> str:
    """Return digits-only representation (stripping leading 00 international exit prefix) for matching."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00") and len(digits) > 10:
        digits = digits[2:]
    return digits


def phones_match(phone_a: Optional[str], phone_b: Optional[str]) -> bool:
    """Check whether two formatted phone numbers refer to the same number across local/country formats."""
    da = canonical_phone_digits(phone_a)
    db = canonical_phone_digits(phone_b)
    if not da or not db:
        return False
    if da == db:
        return True
    return len(da) >= 10 and len(db) >= 10 and da[-10:] == db[-10:]


def extract_phone_from_message(message: str, masked_email: Optional[str] = None) -> Optional[str]:
    """Extract a realistic phone number while ignoring currency figures, dates, and street numbers."""
    if not message:
        return None

    scan_text = message
    if masked_email:
        idx = scan_text.lower().find(masked_email.lower())
        if idx != -1:
            scan_text = scan_text[:idx] + (" " * len(masked_email)) + scan_text[idx + len(masked_email):]

    has_phone_context = any(
        re.search(r"\b" + re.escape(w) + r"\b", scan_text, re.IGNORECASE)
        for w in PHONE_CONTEXT_WORDS
    )

    for match in PHONE_CANDIDATE_REGEX.finditer(scan_text):
        cand = re.sub(r"\s+", " ", match.group(1)).strip()
        if "," in cand:
            continue
        # Reject ISO / localized dates such as 2026-11-12 or 12-11-2026
        if re.match(r"^(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})$", cand):
            continue

        prefix = scan_text[max(0, match.start() - 8):match.start()].lower()
        suffix = scan_text[match.end():min(len(scan_text), match.end() + 8)].lower()
        if any(marker in prefix or marker in suffix for marker in CURRENCY_MARKERS):
            continue

        digits = re.sub(r"\D", "", cand)
        if not (7 <= len(digits) <= 15):
            continue
        if len(digits) < 10 and not (has_phone_context or any(ch in cand for ch in ("+", "-", "(", ")"))):
            continue
        return cand

    return None


def detect_invalid_contact_attempt(
    message: str,
    found_email: Optional[str],
    found_phone: Optional[str],
    prev_assistant_msg: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    """Detect malformed/incomplete email or too-short phone attempts so the bot asks for correction instead of falsely confirming."""
    clean_msg = (message or "").strip()
    if not clean_msg:
        return None

    if not found_email:
        for match in re.finditer(r"[^\s,;\"'<>()]+@[^\s,;\"'<>()]*|@[^\s,;\"'<>()]+", clean_msg):
            tok = match.group(0).rstrip(".,;:!?")
            if tok == "@":
                continue
            local, _, domain = tok.partition("@")
            if not domain:
                return {
                    "type": "email",
                    "value": tok,
                    "reason": "missing the domain after '@' (for example, name@gmail.com)",
                }
            if not local:
                asked_email = bool(prev_assistant_msg and re.search(r"\b(e-?mail|inbox)\b", prev_assistant_msg, re.IGNORECASE))
                if "." in domain or asked_email:
                    return {
                        "type": "email",
                        "value": tok,
                        "reason": "missing the username before '@' (for example, name@gmail.com)",
                    }
                continue
            if "@" in domain or ".." in tok or domain.startswith(".") or domain.endswith("."):
                return {
                    "type": "email",
                    "value": tok,
                    "reason": "incomplete or invalid domain format (for example, name@gmail.com)",
                }
            if "." not in domain or len(domain.rsplit(".", 1)[-1]) < 2:
                return {
                    "type": "email",
                    "value": tok,
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
    """
    Extract email, phone number, and customer name from user message.
    Strictly ignores prices, addresses, gibberish, and generic non-name inputs.
    """
    clean_msg = message.strip()

    # 1. Email & Phone extraction (mask email before scanning for digits)
    found_email = None
    email_match = EMAIL_REGEX.search(clean_msg)
    if email_match:
        cand_email = email_match.group(0).lower()
        if "." in cand_email.split("@")[-1] and len(cand_email.split(".")[-1]) >= 2:
            found_email = cand_email

    found_phone = extract_phone_from_message(clean_msg, masked_email=found_email)

    # 2. Name extraction: explicit intro, Name: X, paired "<Name>, <contact>", or leftover name around contact/name prompt
    found_name = None
    name_patterns = [
        r"(?:my name is|name is|name\s*[:\-]|i am|i'm|this is|call me)\s+([A-Za-z]+(?:\s+[A-Za-z]+)*)",
        r"^([A-Za-z]+(?:\s+[A-Za-z]+){0,2})\s*[,|\-]\s*(?:.*@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+|\+?\d|\(\d)",
    ]

    for pattern in name_patterns:
        match = re.search(pattern, clean_msg, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            valid_words = []
            for w in candidate.split():
                if w.lower() in NON_NAME_WORDS:
                    break
                valid_words.append(w)

            if valid_words and len(valid_words) <= 3:
                candidate_name = " ".join(valid_words).title()
                if is_valid_name(candidate_name):
                    found_name = candidate_name
                    break

    if not found_name:
        prompted_for_name = bool(
            prev_assistant_msg and re.search(r"\byour name\b|\bhave your name\b", prev_assistant_msg, re.IGNORECASE)
        )
        if found_email or found_phone:
            # Strip extracted contact tokens and separators to inspect any leading/trailing clean name
            remainder = clean_msg
            if found_email:
                remainder = re.sub(re.escape(found_email), " ", remainder, flags=re.IGNORECASE)
            if found_phone:
                remainder = remainder.replace(found_phone, " ")
            remainder = re.sub(r"[,:|;\-/]+", " ", remainder).strip()
            words = remainder.split()
            if 1 <= len(words) <= 3 and all(w.lower() not in NON_NAME_WORDS for w in words):
                cand = " ".join(words).title()
                if is_valid_name(cand):
                    found_name = cand
        elif prompted_for_name and "?" not in clean_msg and "!" not in clean_msg:
            words = clean_msg.split()
            if 1 <= len(words) <= 3 and all(w.lower() not in NON_NAME_WORDS for w in words):
                cand = " ".join(words).title()
                if is_valid_name(cand):
                    found_name = cand

    return {"name": found_name, "email": found_email, "phone": found_phone}

def validate_candidate_name(name_candidate: Optional[str]) -> Optional[str]:
    """Validate an extracted name (from regex or LLM) against strict non-name and gibberish guards."""
    if not name_candidate or not isinstance(name_candidate, str):
        return None
    clean = re.sub(r"\s+", " ", name_candidate).strip(" .,:-!?")
    words = clean.split()
    if not (1 <= len(words) <= 3):
        return None
    if any(w.lower() in NON_NAME_WORDS for w in words):
        return None
    if not is_valid_name(clean):
        return None
    return clean.title()


def _is_substantive_summary(text: Optional[str], buyer_intent: Optional[str] = None) -> bool:
    """Return False for off-topic/filler summaries that should not overwrite an existing qualified brief."""
    if not text or not isinstance(text, str):
        return False
    if buyer_intent == "off_topic":
        return False
    low = text.strip().lower()
    if len(low) < 12:
        return False
    boilerplate_markers = (
        "off-topic", "off topic", "professional boundaries", "maintaining boundaries",
        "redirecting back", "evaluating options", "general inquiry", "short ack",
        "visitor said", "unrelated query",
    )
    return not any(marker in low for marker in boilerplate_markers)


def save_lead(
    session_id: str,
    name: Optional[str],
    email: Optional[str] = None,
    phone: Optional[str] = None,
    interest: Optional[str] = None,
    notes: Optional[str] = None,
    business_name: Optional[str] = None,
    emotion: Optional[str] = None,
    buyer_intent: Optional[str] = None,
    sales_tactic: Optional[str] = None,
    qualification: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Save or update a lead in leads.json with progressive qualification & contact merge."""
    init_lead_storage()

    clean_email = email.strip().lower() if email and email.strip() else None
    clean_phone = re.sub(r"\s+", " ", phone).strip() if phone and phone.strip() else None

    try:
        with open(LEADS_FILE, "r", encoding="utf-8") as f:
            leads: List[Dict[str, Any]] = json.load(f)
    except Exception:
        leads = []

    # Match existing lead by email, normalized phone digits, or active session (without clobbering a distinct contact)
    existing_index = None
    for idx, item in enumerate(leads):
        item_email = (item.get("email") or "").lower()
        item_phone = item.get("phone")
        if clean_email and item_email == clean_email:
            existing_index = idx
            break
        if clean_phone and item_phone and phones_match(item_phone, clean_phone):
            existing_index = idx
            break

    if existing_index is None and session_id:
        for idx, item in enumerate(leads):
            if item.get("session_id") != session_id:
                continue
            item_email = (item.get("email") or "").lower()
            item_phone = item.get("phone")
            email_compatible = not clean_email or not item_email or item_email == clean_email
            phone_compatible = not clean_phone or not item_phone or phones_match(item_phone, clean_phone)
            if email_compatible and phone_compatible:
                existing_index = idx
                break

    timestamp = datetime.now().isoformat()
    clean_name = validate_candidate_name(name)
    qual = qualification or {}

    if existing_index is not None:
        existing_lead = leads[existing_index]
        existing_name = existing_lead.get("name")
        if clean_name and (not existing_name or existing_name == "Interested Visitor"):
            existing_lead["name"] = clean_name
        if clean_email and not existing_lead.get("email"):
            existing_lead["email"] = clean_email
        if clean_phone and not existing_lead.get("phone"):
            existing_lead["phone"] = clean_phone
        if interest and (
            _is_substantive_summary(interest, buyer_intent)
            or not existing_lead.get("interest")
            or existing_lead.get("interest") == "General Inquiry"
        ):
            existing_lead["interest"] = interest
        if business_name:
            existing_lead["business_name"] = business_name
        if emotion:
            existing_lead["emotion"] = emotion
        if buyer_intent:
            intent_rank = {"off_topic": 0, "cold": 1, "warm": 2, "hot": 3}
            prev_intent = existing_lead.get("buyer_intent")
            if intent_rank.get(buyer_intent, 0) >= intent_rank.get(prev_intent, 0):
                existing_lead["buyer_intent"] = buyer_intent
        if sales_tactic:
            existing_lead["sales_tactic"] = sales_tactic

        for field in ("specific_need", "budget", "timeline", "preferred_slot", "objection_reason", "sales_stage", "deal_summary"):
            val = qual.get(field)
            if isinstance(val, str) and val.strip():
                if field == "deal_summary" and existing_lead.get("deal_summary") and not _is_substantive_summary(val, buyer_intent):
                    continue
                existing_lead[field] = val.strip()
        if isinstance(qual.get("lead_score"), (int, float)):
            prev_score = int(existing_lead.get("lead_score") or 0)
            existing_lead["lead_score"] = max(prev_score, max(0, min(100, int(qual["lead_score"]))))

        existing_lead["updated_at"] = timestamp
        saved_lead = existing_lead
    else:
        if not clean_email and not clean_phone:
            raise ValueError("At least an email or phone number is required to create a new lead.")
        raw_score = qual.get("lead_score")
        lead_score = max(0, min(100, int(raw_score))) if isinstance(raw_score, (int, float)) else 75
        existing_nums = [
            int(str(item.get("id", "")).split("_")[1])
            for item in leads
            if str(item.get("id", "")).startswith("lead_") and str(item.get("id", "")).split("_")[1].isdigit()
        ]
        next_num = max(existing_nums, default=0) + 1
        saved_lead = {
            "id": f"lead_{next_num:04d}",
            "session_id": session_id,
            "business_name": business_name or "General Client",
            "name": clean_name or "Interested Visitor",
            "email": clean_email,
            "phone": clean_phone,
            "interest": interest or "General Inquiry",
            "notes": notes or "Captured via Chatbot",
            "emotion": emotion or "curious",
            "buyer_intent": buyer_intent or "hot",
            "sales_tactic": sales_tactic or "Direct Lead Close",
            "sales_stage": qual.get("sales_stage") or "post_capture",
            "specific_need": qual.get("specific_need"),
            "budget": qual.get("budget"),
            "timeline": qual.get("timeline"),
            "preferred_slot": qual.get("preferred_slot"),
            "objection_reason": qual.get("objection_reason"),
            "lead_score": lead_score,
            "deal_summary": qual.get("deal_summary") or interest or "Verified Lead",
            "created_at": timestamp,
            "updated_at": timestamp
        }
        leads.insert(0, saved_lead)

    with open(LEADS_FILE, "w", encoding="utf-8") as f:
        json.dump(leads, f, indent=2)

    return saved_lead

def get_all_leads() -> List[Dict[str, Any]]:
    """Retrieve all leads stored in leads.json."""
    init_lead_storage()
    try:
        with open(LEADS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def delete_lead_by_id(lead_id: str) -> bool:
    """Remove a single lead by id and return whether a record was deleted."""
    if not lead_id:
        return False
    leads = get_all_leads()
    remaining = [item for item in leads if item.get("id") != lead_id]
    if len(remaining) == len(leads):
        return False
    with open(LEADS_FILE, "w", encoding="utf-8") as f:
        json.dump(remaining, f, indent=2)
    return True


def clear_all_leads():
    """Clear all captured leads."""
    init_lead_storage()
    with open(LEADS_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)
