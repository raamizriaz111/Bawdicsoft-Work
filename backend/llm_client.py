"""
Gemini LLM Client for Universal Client Chatbot Studio.
Handles real API communication, multi-model fallback resiliency, and dynamic prompt configuration.
"""

import os
import re
import concurrent.futures
from pathlib import Path
from typing import List, Dict, Any, Optional

ROOT_DIR = Path(__file__).parent.parent
try:
    from dotenv import load_dotenv
    env_file = ROOT_DIR / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=True)
    else:
        load_dotenv()
except ImportError:
    pass

from backend.prompt_builder import build_system_prompt
from bot_config import COMPANY_OR_SOFTWARE_NAME, BOT_NAME

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

class ChatClient:
    def __init__(self):
        self.client = None
        self.model_name = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
        self.api_key = os.environ.get("GEMINI_API_KEY", "").strip()

        # If local .env is blank, check parent .env as fallback so live AI works immediately
        if not self.api_key:
            parent_env = ROOT_DIR.parent / ".env"
            if parent_env.exists():
                try:
                    from dotenv import dotenv_values
                    parent_vals = dotenv_values(parent_env)
                    parent_key = parent_vals.get("GEMINI_API_KEY", "").strip()
                    if parent_key:
                        self.api_key = parent_key
                        print(f"[ChatClient] Using fallback Gemini API Key from root environment.")
                except Exception:
                    pass

        if self.api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
                print(f"[ChatClient] Initialized Google GenAI ({self.model_name}) for {COMPANY_OR_SOFTWARE_NAME}")
            except Exception as e:
                print(f"[ChatClient] Failed to initialize Google GenAI: {e}")
                self.client = None
        else:
            print(f"[ChatClient] No GEMINI_API_KEY found in universal_client_chatbot/.env. Running in Smart Demo Mode.")

    def reload_credentials(self):
        """Reload API key if .env was changed while running."""
        new_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if new_key and new_key != self.api_key:
            self.api_key = new_key
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
                print(f"[ChatClient] Re-initialized Google GenAI with new API key.")
            except Exception as e:
                print(f"[ChatClient] Re-initialization failed: {e}")

    @staticmethod
    def _get_analysis_schema():
        """Lazily build and cache the Pydantic schema for single-pass emotional sales analysis."""
        schema_cls = getattr(ChatClient, "_sales_analysis_schema", None)
        if schema_cls is not None:
            return schema_cls

        from typing import Literal
        from pydantic import BaseModel, Field

        class SalesChatAnalysis(BaseModel):
            emotion: Literal[
                "excited",
                "urgent",
                "price_hesitant",
                "skeptical",
                "frustrated",
                "confused",
                "curious",
                "neutral",
            ] = Field(
                description=(
                    "Dominant emotional state in the visitor's latest message ONLY: "
                    "excited = enthusiastic/eager; urgent = needs immediate help; "
                    "price_hesitant = worried about cost/budget; skeptical = doubting trust/proof; "
                    "frustrated = annoyed/impatient; confused = unsure what to pick; "
                    "curious = actively asking questions or exploring details; "
                    "neutral = plain greetings, farewells, matter-of-fact info, or short confirmations/acks (e.g. 'done', 'ok', 'thanks', 'got it')."
                )
            )
            buyer_intent: Literal["hot", "warm", "cold", "off_topic"] = Field(
                description=(
                    "hot = ready to book, buy, visit urgently, or sharing contact info; "
                    "warm = evaluating pricing, services, trust, or comparisons; "
                    "cold = casual greeting, farewell, short ack, or low urgency; "
                    "off_topic = general query unrelated to the business."
                )
            )
            sales_stage: Literal[
                "greeting",
                "discovery",
                "recommendation",
                "objection_handling",
                "closing",
                "post_capture",
            ] = Field(description="Current consultative sales stage after the visitor's message.")
            sales_tactic: str = Field(
                description=(
                    "2-5 word Title Case consultative human sales tactic used in reply (e.g. 'Warm Hospitality', 'Consultative Discovery', 'Value Anchor + Milestone Scoping', 'Social Proof + Guarantee'). "
                    "NEVER use robotic or machine terms like 'System Operational Ready' or 'System Operational'."
                )
            )
            extracted_name: Optional[str] = Field(
                default=None,
                description="Visitor's personal name ONLY if explicitly shared (e.g. 'Ali here', 'naam Bilal hai'), else null."
            )
            specific_need: Optional[str] = Field(
                default=None,
                description="Concise product, service, or property the visitor wants, else null."
            )
            budget: Optional[str] = Field(
                default=None,
                description="Visitor's stated budget or price range if mentioned, else null."
            )
            timeline: Optional[str] = Field(
                default=None,
                description="Visitor's urgency or desired timeframe (e.g. 'this week', 'next month', 'today'), else null."
            )
            preferred_slot: Optional[str] = Field(
                default=None,
                description="Preferred appointment, demo, or viewing time/day if stated, else null."
            )
            objection_reason: Optional[str] = Field(
                default=None,
                description="Brief blocker or objection (e.g. 'price_hesitant', 'needs trust proof', 'timing'), else null."
            )
            lead_score: int = Field(
                description="0 to 100 conversion readiness score based on intent, urgency, contact info, and qualification clarity."
            )
            deal_summary: str = Field(
                description=(
                    "Crisp 1-sentence 3rd-person internal brief summarizing the visitor's real product/service requirements, budget, and readiness. "
                    "Never write in 1st person ('I am maintaining...'), and if this turn is off-topic or a short ack, summarize their prior business inquiry."
                )
            )
            reply: str = Field(
                description=(
                    "Natural, human-sounding 1-3 sentence reply written strictly in the configured CONVERSATIONAL TONE, "
                    "grounded in the KNOWLEDGE BASE, and paced appropriately to advance the CONVERSION OBJECTIVE."
                )
            )

        ChatClient._sales_analysis_schema = SalesChatAnalysis
        return SalesChatAnalysis

    _OPTOUT_PHRASES = (
        "not interested", "no longer interested", "not anymore", "changed my mind",
        "change my mind", "no thanks", "no thank you", "never mind", "nevermind",
        "don't want", "dont want", "stop texting", "stop messaging", "leave me alone",
        "unsubscribe", "already found", "found someone", "went with another",
        "booked elsewhere", "booked somewhere else", "not looking", "forget it",
        "no need", "i'll pass", "ill pass", "remove my email", "delete my data",
    )
    _OPTOUT_EXACT = {"no", "nope", "nah", "pass"}
    _DEFERRAL_PHRASES = (
        "after some hours", "after a few hours", "in a few hours",
        "discuss later", "discuss it later", "talk later", "call later",
        "some other time", "get back to you", "think about it", "busy right now",
        "too busy", "later today", "next week", "next month", "next payday",
        "in a meeting", "driving right now", "check back later", "wait a bit",
    )
    _BOT_IDENTITY_PHRASES = (
        "are you a bot", "are you ai", "are you real", "real person",
        "human or ai", "bot or human", "who am i talking", "who are you",
        "what is your name", "what's your name", "whats your name",
        "tell me your name", "may i know your name", "who is this",
    )
    _HUMAN_HANDOFF_PHRASES = (
        "talk to a human", "speak to a human", "real human", "real agent",
        "speak with someone", "talk to someone", "customer support",
        "speak to a manager", "call me", "human support", "representative",
    )
    _GREETING_EXACT = {
        "hi", "hello", "hey", "hi there", "hello there", "good morning",
        "good afternoon", "good evening", "assalam o alaikum", "salam", "salam alaikum",
        "how are you", "how are you doing", "how are you doing today", "how are you today",
        "how r u", "how are u", "hows it going", "how is it going", "how is your day",
        "how's your day", "how is everything", "whats up", "what's up", "wassup", "sup",
        "good to see you", "hope you are well", "hope all is well", "are you good", "how do you do",
    }

    @classmethod
    def _is_greeting_message(cls, text: str) -> bool:
        """Check if message is primarily a greeting or small talk check-in."""
        import re
        clean = re.sub(r"[^a-z\s']", "", (text or "").lower()).strip()
        if clean in cls._GREETING_EXACT:
            return True
        return bool(
            re.match(
                r"^(?:hi|hello|hey|hiya|howdy|good\s+(?:morning|afternoon|evening)|salam|assalam(?:\s+o\s+alaikum)?|"
                r"how\s+are\s+you(?:\s+doing)?(?:\s+today)?|how\s+r\s+u|hows\s+(?:it\s+going|your\s+day)|"
                r"how\s+is\s+(?:it\s+going|your\s+day|everything)|what'?s\s+up|sup)\b",
                clean
            ) and len(clean.split()) <= 7 and not any(w in clean for w in ("quote", "price", "cost", "hiring", "job", "career", "service", "build"))
        )
    _ACK_EXACT = {
        "ok", "okay", "k", "cool", "ok cool", "haha ok cool", "alright",
        "sounds good", "gotcha", "fair enough", "hmm", "hm", "nice", "wow",
        "perfect", "thanks", "thank you", "great", "got it", "understood", "lol",
        "done", "all set",
    }

    @staticmethod
    def _is_career_inquiry(text: str) -> bool:
        """Detect job/career/internship/resume questions without matching phrases like 'good job'."""
        import re

        low = (text or "").lower().strip()
        if not low or re.search(r"\b(?:(?:good|great|nice|awesome|amazing)\s+job|(?:get|do)\s+the\s+job)\b", low):
            return False
        if re.search(
            r"\b(?:jobs|career|careers|hiring|vacancy|vacancies|openings|internship|internships|resume|cv|recruitment|recruiting)\b",
            low,
        ):
            return True
        return bool(
            re.search(
                r"\b(?:job\s+(?:available|openings?|opportunities?|opportunity|offer|offers|post|posting|search)|"
                r"apply(?:ing)?\s+for\s+(?:a\s+|an\s+)?(?:job|role|position|internship)|"
                r"(?:looking\s+for|need|want|seeking|find|get|any)\s+(?:a\s+)?job|"
                r"open\s+(?:roles?|positions?)|hire\s+me|"
                r"work\s+(?:at|for|with)\s+(?:you|your\s+team)|join\s+(?:your|the)\s+team)\b",
                low,
            )
        )

    @staticmethod
    def _build_career_referral_reply(biz_name: str, kb: str, tone: str = "") -> str:
        """Direct job/career applicants to the KB careers/company email without pitching services."""
        import re

        emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", kb or "")
        # Prefer explicit careers/hr email if present, otherwise use general/first company email
        target_email = next(
            (e for e in emails if any(k in e.lower() for k in ("career", "hr", "job", "talent", "recruit"))),
            emails[0] if emails else None,
        )
        low_tone = (tone or "").lower()
        is_blunt = any(w in low_tone for w in ("rude", "aggressive", "blunt", "abusive", "harsh", "impatient", "direct", "sarcastic"))
        is_formal = any(w in low_tone for w in ("formal", "confidential", "executive", "legal"))

        if target_email:
            if is_blunt:
                return f"This chat isn't for hiring. Email your CV/resume directly to {target_email}."
            if is_formal:
                return (
                    f"Thank you for your interest in career opportunities at {biz_name}. "
                    f"Please email your CV/resume and portfolio to {target_email} for our hiring team's review."
                )
            return (
                f"For job and career opportunities at {biz_name}, please email your CV/resume and portfolio directly to {target_email} "
                f"so our hiring team can review your profile."
            )
        return (
            f"For job and career opportunities at {biz_name}, please reach out through our official company contact email or website with your CV/resume."
        )

    @staticmethod
    def _build_company_contact_reply(biz_name: str, kb: str, tone: str = "") -> str:
        """Provide official company contact details from the KB and strictly protect customer leads."""
        import re

        is_blunt = any(w in (tone or "").lower() for w in ("rude", "aggressive", "blunt", "abusive", "harsh", "impatient", "direct", "sarcastic"))
        contact_items = []
        for line in (kb or "").split("\n"):
            clean = line.strip().lstrip("-*• ")
            low = clean.lower()
            if any(w in low for w in ("requirement", "viewing policy", "careers & job", "please email your cv", "open or upcoming")):
                continue
            if re.search(r"\b(?:company email|direct ceo email|email|whatsapp|direct phone|phone|front desk phone|headquarters address|address)\s*:", low):
                contact_items.append(clean)

        if not contact_items:
            # Free-form / prose extraction
            emails = list(dict.fromkeys(re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", kb or "")))
            emails = [e for e in emails if not e.endswith(("@example.com", "@domain.com", "name@gmail.com"))]

            phones = list(dict.fromkeys(re.findall(r"(?:\+?\d{1,3}[\s\-]?)?(?:\(?\d{2,4}\)?[\s\-]?)?\d{3,4}[\s\-]?\d{3,4}", kb or "")))
            valid_phones = []
            for p in phones:
                digits = re.sub(r"\D", "", p)
                if len(digits) >= 8 and not re.match(r"^(?:19|20)\d{2}$", digits):
                    valid_phones.append(p.strip())

            address = None
            m_head = re.search(r"(?:headquartered at|headquarters in|located at|office at)\s+([^.\n]+)", kb or "", re.IGNORECASE)
            if m_head:
                address = m_head.group(1).strip()
            else:
                m_bldg = re.search(r"([^.\n]*(?:building|suite|tower|plaza|road|street|dha|clifton)[^.\n]*)", kb or "", re.IGNORECASE)
                if m_bldg:
                    clean_addr = m_bldg.group(1).strip()
                    clean_addr = re.sub(r"^(?:and\s+|at\s+)", "", clean_addr, flags=re.IGNORECASE).strip()
                    if len(clean_addr) <= 80:
                        address = clean_addr

            if emails:
                contact_items.append(f"Company Email: {emails[0]}")
            if valid_phones:
                contact_items.append(f"Phone: {valid_phones[0]}")
            if address:
                contact_items.append(f"Headquarters Address: {address}")

        if contact_items:
            details = " | ".join(contact_items)
            if is_blunt:
                return f"Contact {biz_name}: {details}."
            return f"You can reach {biz_name} directly: {details}."
        return f"You can reach our team at {biz_name} directly during business hours."

    @staticmethod
    def _build_leadership_inquiry_reply(
        biz_name: str,
        kb: str,
        last_user_msg: str,
        tone: str = "",
        greeting_name: str = "",
        has_known_contact: bool = False,
        goal_hook = None
    ) -> str:
        """
        Deliver a warm, executive-level introduction to company founders, leadership, or directors,
        pairing domain prestige with consultative sales discovery rather than bare contacts.
        """
        import re
        msg_low = last_user_msg.lower()
        is_blunt = any(w in (tone or "").lower() for w in ("rude", "aggressive", "blunt", "abusive", "harsh", "impatient", "direct", "sarcastic"))
        is_formal = any(w in (tone or "").lower() for w in ("formal", "confidential", "executive", "legal"))

        # 1. Syed Bilal Hashmi / Founder / CEO
        if any(k in msg_low for k in ("bilal", "hashmi", "ceo", "founder", "who started", "who founded", "who created", "who owns")):
            if "bilal" in kb.lower() or "founder" in kb.lower():
                if is_blunt:
                    return f"Syed Bilal Hashmi is the Founder & CEO of {biz_name}. What do you need help with?"
                if is_formal:
                    return f"Syed Bilal Hashmi is the Founder and CEO of {biz_name}. Are you looking to discuss a partnership or schedule a consultation with our leadership?"
                return f"Syed Bilal Hashmi is the Founder & CEO of {biz_name}. Are you looking to connect with him regarding an upcoming project?"

        # 2. Muhammad Zubair / Director
        if "zubair" in msg_low:
            if "zubair" in kb.lower() or "director" in kb.lower():
                if is_blunt:
                    return f"Muhammad Zubair is a Director at {biz_name}. What's your project?"
                return f"Muhammad Zubair is a Director at {biz_name}. Are you exploring a project or collaboration with our team?"

        # 3. General Leadership / Executive Team inquiry
        if any(k in msg_low for k in ("who runs", "who leads", "who heads", "leads the", "leadership", "executive", "director", "management team", "owner", "who is in charge", "in charge")):
            leaders = []
            for line in kb.split("\n"):
                cl = line.strip().lstrip("-*• ")
                if not cl or re.match(r"^#{1,6}\s+|^\d+\.\s+", cl) or (cl.endswith(":") and len(cl) <= 45):
                    continue
                has_role = any(
                    re.search(r"\b" + re.escape(role) + r"\b", cl, re.IGNORECASE)
                    for role in ("founder", "ceo", "director", "dentist", "managing partner", "head trainer", "attorney", "counsel")
                )
                if has_role and not any(w in cl.lower() for w in ("dentistry", "policy", "hours", "requirement")):
                    clean_line = cl.replace("**", "").replace("*", "").strip().rstrip(".!?;, ")
                    if len(clean_line) <= 130 and not clean_line.endswith(":"):
                        leaders.append(clean_line)
            if leaders:
                leader_str = "; ".join(leaders[:2])
                if is_blunt:
                    return f"{biz_name} is led by {leader_str}. What's your project?"
                return f"{biz_name} is led by {leader_str}. Are you looking to discuss a project with our team?"

        # 4. Unknown team member query ("who is Alex", "who is John")
        stop_name_tokens = {
            "who", "the", "and", "for", "with", "about", "tell", "name", "leads", "runs", "heads",
            "company", "organization", "firm", "business", "this", "that", "there", "team", "agency",
            "charge", "clinic", "practice", "gym", "store", "studio", "office", "desk", "hospital"
        }
        tokens = [w for w in re.findall(r"[a-z]{3,}", msg_low) if w not in stop_name_tokens]
        unmatched_name = tokens[0].title() if tokens else "that person"
        if "bawdicsoft" in biz_name.lower():
            team_info = "Our core leadership includes Syed Bilal Hashmi (Founder & CEO) and Muhammad Zubair (Director)."
        else:
            team_info = f"Our team at {biz_name} is led by experienced practitioners and leadership."
        return (
            f"I don't have a team member named {unmatched_name} listed with {biz_name}. "
            f"{team_info} What specific area or question can our team help you with?"
        )

    @staticmethod
    def _classify_behavior_heuristic(
        conversation_history: List[Dict[str, str]],
        user_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """Fast keyword fallback for emotion, buyer_intent, and sales_tactic when running offline."""
        import re

        raw_last_msg = ""
        for msg in reversed(conversation_history or []):
            if msg.get("role") == "user":
                raw_last_msg = (msg.get("content") or "").strip()
                break
        last_msg = raw_last_msg.lower()

        clean_msg = re.sub(r"[^a-z\s']", "", last_msg).strip()
        if clean_msg in ChatClient._OPTOUT_EXACT:
            return {"emotion": "neutral", "buyer_intent": "cold", "sales_tactic": "Graceful Exit + Door Open"}

        has_contact = bool((user_profile or {}).get("email") or (user_profile or {}).get("phone"))
        if ChatClient._is_greeting_message(raw_last_msg):
            return {
                "emotion": "neutral",
                "buyer_intent": "warm" if has_contact else "cold",
                "sales_tactic": "Warm Hospitality",
            }

        rules = [
            ("neutral", "off_topic", "Polite Business Pivot",
             ("weather", "capital of", "president", "write a python", "write python", "write code", "binary search", "linked list", "write javascript", "code for me", "debug my", "joke", "poem", "recipe", "cricket score", "football", "world cup", "who won", "2+2", "solve ")),
            ("neutral", "cold", "Graceful Exit + Door Open", ChatClient._OPTOUT_PHRASES),
            ("neutral", "warm", "Human Handoff Offer", ChatClient._HUMAN_HANDOFF_PHRASES),
            ("neutral", "cold", "Transparent AI Introduction", ChatClient._BOT_IDENTITY_PHRASES),
            ("neutral", "cold", "Warm Hospitality",
             ("hi there", "hello there", "good morning", "good afternoon", "good evening", "how are you", "how are you doing", "how are you today", "hows it going", "how is it going", "how is your day", "hows your day", "whats up", "what's up", "wassup", "hello,")),
            ("frustrated", "warm", "Empathy + Direct Answer",
             ("stop asking", "just tell me", "annoying", "frustrated", "useless", "waste of time", "not helping", "already asked", "make no sense", "makes no sense", "so unhelpful", "repeating yourself")),
            ("neutral", "cold", "Respect Timing + Follow-Up", ChatClient._DEFERRAL_PHRASES),
            ("urgent", "hot", "Immediate Action Close",
             ("urgent", "asap", "emergency", "immediately", "pain", "hurt", "broken", "deadline")),
            ("skeptical", "warm", "Social Proof + Guarantee",
             ("how do i know", "actually work", "legit", "scam", "trust", "guarantee", "proof", "real results", "really work", "reviews")),
            ("price_hesitant", "warm", "Value Anchor + Payment Plan",
             ("expensive", "too much", "costly", "overpriced", "budget", "cheaper", "discount", "afford", "installment", "150k")),
            ("urgent", "hot", "Immediate Action Close",
             ("right now", "today")),
            ("excited", "hot", "Momentum Booking Close",
             ("book now", "sign me up", "count me in", "lets do it", "let's do it", "ready to start", "awesome", "perfect", "excited", "love to")),
            ("confused", "warm", "Simplified Two-Option Guide",
             ("confused", "not sure", "don't know", "dont know", "which one", "recommend", "help me choose", "what should i")),
            ("excited", "warm", "Consultative Project Scoping",
             ("want to build", "want to create", "want to launch", "want to start", "want to make", "want a website", "want an app", "want a store", "need a website", "need an app", "need a store", "need a chatbot", "looking to build", "looking to launch", "looking to start", "looking to create", "planning to build", "planning to launch", "shopify", "woocommerce", "ecommerce", "e-commerce", "online store", "online shop", "intersted", "interested in")),
            ("curious", "warm", "Consultative Discovery",
             ("price", "cost", "fee", "package", "service", "location", "address", "opening hours", "office hours", "business hours", "what hours", "timing", "timings", "portfolio", "appointment", "weekend", "?")),
        ]

        from backend.lead_manager import detect_invalid_contact_attempt, extract_lead_from_message

        extracted_contact = extract_lead_from_message(raw_last_msg)
        if extracted_contact.get("email") or extracted_contact.get("phone"):
            return {
                "emotion": "excited",
                "buyer_intent": "hot",
                "sales_tactic": "VIP Follow-up Confirmation",
            }
        invalid_now = (user_profile or {}).get("_contact_validation_issue") or detect_invalid_contact_attempt(
            raw_last_msg,
            found_email=extracted_contact.get("email"),
            found_phone=extracted_contact.get("phone"),
        )
        if invalid_now:
            return {
                "emotion": "curious",
                "buyer_intent": "warm",
                "sales_tactic": "Contact Format Clarification",
            }
        if ChatClient._is_career_inquiry(last_msg):
            return {
                "emotion": "curious",
                "buyer_intent": "cold",
                "sales_tactic": "Careers Email Referral",
            }

        for emotion, intent, tactic, keywords in rules:
            if any(kw in last_msg for kw in keywords):
                return {"emotion": emotion, "buyer_intent": intent, "sales_tactic": tactic}

        has_contact = bool((user_profile or {}).get("email") or (user_profile or {}).get("phone"))
        clean_ack = re.sub(r"[^a-z\s]", "", last_msg).strip()
        greetings = ("hi", "hello", "hey", "hiya", "howdy", "good morning", "good afternoon", "good evening", "salam", "assalam", "yo")
        is_greeting = any(clean_ack == g or clean_ack.startswith(g + " ") for g in greetings)

        if is_greeting:
            return {
                "emotion": "neutral",
                "buyer_intent": "warm" if has_contact else "cold",
                "sales_tactic": "Warm Hospitality",
            }

        return {
            "emotion": "curious",
            "buyer_intent": "warm" if has_contact else "cold",
            "sales_tactic": "Consultative Discovery",
        }

    @staticmethod
    def _extract_qualification_heuristic(
        raw_last_msg: str,
        user_profile: Optional[Dict[str, Any]],
        behavior: Dict[str, str],
    ) -> Dict[str, Any]:
        """Extract basic stage, budget, timeline, and readiness score when running offline or filling defaults."""
        import re

        low = (raw_last_msg or "").lower()
        profile = user_profile or {}
        has_contact = bool(profile.get("email") or profile.get("phone"))

        budget = profile.get("budget")
        budget_match = re.search(
            r"(?:pkr|rs\.?|\$|usd|eur|aed)\s*[\d,]+(?:\.\d+)?(?:\s*(?:crore|cr|lakh|lac|k|m))?|[\d,]+(?:\.\d+)?\s*(?:crore|cr|lakh|lac|k)\b",
            raw_last_msg or "",
            re.IGNORECASE,
        )
        if budget_match:
            budget = budget_match.group(0).strip()

        is_greeting = ChatClient._is_greeting_message(raw_last_msg or "")

        timeline = profile.get("timeline")
        if not is_greeting:
            for marker in ("tomorrow", "this week", "next week", "this month", "next month", "asap", "immediately", "urgent"):
                if marker in low:
                    timeline = marker
                    break
            if not timeline and "today" in low:
                if not any(w in low for w in ("how are", "how r", "hows", "how is", "doing today", "you today", "your day")):
                    timeline = "today"

        objection = profile.get("objection_reason")
        if behavior["emotion"] in ("price_hesitant", "skeptical"):
            objection = behavior["emotion"]

        preferred_slot = profile.get("preferred_slot")
        if not is_greeting:
            slot_match = re.search(
                r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|weekend)(?:\s+(?:at\s+)?(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)|morning|afternoon|evening))?\b|\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
                raw_last_msg or "",
                re.IGNORECASE,
            )
            if slot_match:
                preferred_slot = slot_match.group(0).strip()
            elif "today" in low and any(w in low for w in ("schedule", "book", "meeting", "call", "appointment", "slot", "consultation", "available", "at ")):
                preferred_slot = "today"

        intent = behavior["buyer_intent"]
        if has_contact:
            sales_stage = "post_capture"
        elif intent == "hot":
            sales_stage = "closing"
        elif behavior["emotion"] in ("price_hesitant", "skeptical", "frustrated"):
            sales_stage = "objection_handling"
        elif behavior["emotion"] == "confused":
            sales_stage = "recommendation"
        elif behavior.get("sales_tactic") == "Warm Hospitality" or is_greeting:
            sales_stage = "greeting"
        else:
            sales_stage = "discovery"

        base_score = {"hot": 78, "warm": 48, "cold": 18, "off_topic": 5}.get(intent, 25)
        if has_contact:
            base_score = max(base_score, 85)
        if budget:
            base_score = min(100, base_score + 7)
        if timeline:
            base_score = min(100, base_score + 5)
        if preferred_slot:
            base_score = min(100, base_score + 5)

        need = profile.get("specific_need")
        clean_ack_need = re.sub(r"[^a-z\s']", "", (raw_last_msg or "").lower()).strip()
        vague_prompts = {"tell me", "tell me more", "explain", "go on", "what do you do", "what can you do", "overview", "what are your services", "what services"}
        if (
            not need
            and intent != "off_topic"
            and behavior.get("sales_tactic") != "Graceful Exit + Door Open"
            and not is_greeting
            and clean_ack_need not in vague_prompts
        ):
            stripped_need = re.sub(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", "", raw_last_msg or "", flags=re.IGNORECASE)
            stripped_need = re.sub(r"\+?\d[\d\s\-().]{6,}\d", "", stripped_need).strip(" ,.-:")
            clean_sub = re.sub(r"[^a-z\s]", "", stripped_need.lower()).strip()
            if (
                len(stripped_need) > 6
                and clean_sub not in ChatClient._GREETING_EXACT
                and clean_sub not in ChatClient._ACK_EXACT
                and clean_sub not in vague_prompts
                and not ChatClient._is_greeting_message(stripped_need)
            ):
                need = stripped_need[:80]

        summary_parts = [
            p for p in [
                need,
                f"Budget: {budget}" if budget else None,
                f"Timeline: {timeline}" if timeline else None,
                f"Slot: {preferred_slot}" if preferred_slot else None,
            ] if p
        ]
        deal_summary = " | ".join(summary_parts) if summary_parts else "Visitor evaluating options."

        return {
            "sales_stage": sales_stage,
            "extracted_name": None,
            "specific_need": need,
            "budget": budget,
            "timeline": timeline,
            "preferred_slot": preferred_slot,
            "objection_reason": objection,
            "lead_score": max(int(profile.get("lead_score") or 0), base_score),
            "deal_summary": deal_summary,
        }

    def _parse_analysis_response(
        self,
        response: Any,
        fallback_behavior: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Safely extract and validate structured JSON output from Gemini."""
        import json

        valid_emotions = {
            "excited", "urgent", "price_hesitant", "skeptical",
            "frustrated", "confused", "curious", "neutral",
        }
        valid_intents = {"hot", "warm", "cold", "off_topic"}
        valid_stages = {
            "greeting", "discovery", "recommendation",
            "objection_handling", "closing", "post_capture",
        }

        def clean_opt_str(val: Any) -> Optional[str]:
            if val is None:
                return None
            s = str(val).strip()
            if not s or s.lower() in {"null", "none", "n/a", "unknown", "not specified"}:
                return None
            return s

        data: Optional[Dict[str, Any]] = None
        parsed = getattr(response, "parsed", None)
        if parsed is not None:
            data = parsed.model_dump() if hasattr(parsed, "model_dump") else dict(parsed)
        elif getattr(response, "text", None):
            raw = response.text.strip()
            if raw.startswith("```"):
                raw = raw.strip("`")
                if raw.lower().startswith("json"):
                    raw = raw[4:].strip()
            data = json.loads(raw)

        if not isinstance(data, dict):
            return None

        reply_text = str(data.get("reply") or "").strip()
        if not reply_text:
            return None

        emotion = str(data.get("emotion") or "").strip().lower()
        if emotion not in valid_emotions:
            emotion = fallback_behavior["emotion"]

        buyer_intent = str(data.get("buyer_intent") or "").strip().lower()
        if buyer_intent not in valid_intents:
            buyer_intent = fallback_behavior["buyer_intent"]

        sales_stage = str(data.get("sales_stage") or "").strip().lower()
        if sales_stage not in valid_stages:
            sales_stage = fallback_behavior.get("sales_stage", "discovery")

        sales_tactic = str(data.get("sales_tactic") or "").strip() or fallback_behavior["sales_tactic"]
        if any(tok in sales_tactic.lower() for tok in ("operational ready", "system operational", "system ready", "diagnostic", "cpu", "server", "peak efficiency")):
            sales_tactic = "Warm Hospitality" if sales_stage == "greeting" else "Consultative Discovery"

        # Safety filter: prevent any robotic machine responses from ever reaching the client
        if re.search(r"^(?:systems?\s+(?:are|is)\s+(?:fully\s+)?(?:online|operational|optimized|running)|firing\s+on\s+all\s+cylinders)\b", reply_text, re.IGNORECASE):
            reply_text = re.sub(
                r"^(?:systems?\s+(?:are|is)\s+(?:fully\s+)?(?:online|operational|optimized|running)[^.!?]*[.!?]\s*|firing\s+on\s+all\s+cylinders[^.!?]*[.!?]\s*)",
                "Doing great, thank you for asking! ",
                reply_text,
                flags=re.IGNORECASE
            ).strip()

        raw_score = data.get("lead_score")
        try:
            lead_score = max(0, min(100, int(raw_score))) if raw_score is not None else int(fallback_behavior.get("lead_score", 25))
        except Exception:
            lead_score = int(fallback_behavior.get("lead_score", 25))

        deal_summary = clean_opt_str(data.get("deal_summary")) or fallback_behavior.get("deal_summary") or "Visitor evaluating options."

        return {
            "reply": reply_text,
            "emotion": emotion,
            "buyer_intent": buyer_intent,
            "sales_stage": sales_stage,
            "sales_tactic": sales_tactic,
            "extracted_name": clean_opt_str(data.get("extracted_name")),
            "specific_need": clean_opt_str(data.get("specific_need")) or fallback_behavior.get("specific_need"),
            "budget": clean_opt_str(data.get("budget")) or fallback_behavior.get("budget"),
            "timeline": clean_opt_str(data.get("timeline")) or fallback_behavior.get("timeline"),
            "preferred_slot": clean_opt_str(data.get("preferred_slot")) or fallback_behavior.get("preferred_slot"),
            "objection_reason": clean_opt_str(data.get("objection_reason")) or fallback_behavior.get("objection_reason"),
            "lead_score": lead_score,
            "deal_summary": deal_summary,
        }

    def generate_analysis(
        self,
        conversation_history: List[Dict[str, str]],
        user_profile: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Single-pass structured LLM inference returning both the salesperson reply
        and live emotion, buyer_intent, and sales_tactic metadata.
        """
        system_instruction = build_system_prompt(user_profile=user_profile, config=config)
        fallback_behavior = self._classify_behavior_heuristic(conversation_history, user_profile)
        last_user_raw = ""
        for msg in reversed(conversation_history or []):
            if msg.get("role") == "user":
                last_user_raw = (msg.get("content") or "").strip()
                break
        fallback_behavior = {
            **fallback_behavior,
            **self._extract_qualification_heuristic(last_user_raw, user_profile, fallback_behavior),
        }

        if self.client:
            from google.genai import types

            recent_history = conversation_history[-12:] if conversation_history else []
            contents = []
            for msg in recent_history:
                role = "user" if msg["role"] == "user" else "model"
                contents.append(
                    types.Content(
                        role=role,
                        parts=[types.Part.from_text(text=msg["content"])]
                    )
                )

            import time

            analysis_schema = self._get_analysis_schema()
            models_to_try = [
                self.model_name,
                "gemini-3.1-flash-lite",
                "gemini-3.8-flash",
                "gemini-3.5-flash-lite",
            ]
            unique_models = []
            for m in models_to_try:
                if m and m not in unique_models:
                    unique_models.append(m)

            # Enforce a 25.0s total failover budget so visitors never stall indefinitely
            deadline = time.monotonic() + 25.0
            for model_to_call in unique_models[:3]:
                for attempt in range(2):
                    remaining = deadline - time.monotonic()
                    if remaining < 1.5:
                        break
                    executor = None
                    model_timeout = round(min(12.0, remaining), 2)
                    try:
                        def _call_model():
                            cfg_kwargs = {
                                "system_instruction": system_instruction,
                                "temperature": 0.45,
                                "max_output_tokens": 620,
                                "response_mime_type": "application/json",
                                "response_schema": analysis_schema,
                            }
                            if "3.1" in model_to_call or "3.8" in model_to_call:
                                cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
                            return self.client.models.generate_content(
                                model=model_to_call,
                                contents=contents,
                                config=types.GenerateContentConfig(**cfg_kwargs)
                            )

                        # Avoid `with ThreadPoolExecutor`: __exit__ blocks on shutdown(wait=True) if HTTP stalls.
                        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                        future = executor.submit(_call_model)
                        response = future.result(timeout=model_timeout)
                        executor.shutdown(wait=False)
                        parsed_result = self._parse_analysis_response(response, fallback_behavior)
                        if parsed_result:
                            parsed_result = self._enforce_contact_integrity(
                                parsed_result,
                                last_user_raw=last_user_raw,
                                user_profile=user_profile,
                                config=config,
                            )
                            parsed_result = self._enforce_greeting_pacing(
                                parsed_result,
                                last_user_raw=last_user_raw,
                                config=config,
                            )
                            parsed_result["source"] = model_to_call
                            return parsed_result
                        break
                    except concurrent.futures.TimeoutError:
                        if executor is not None:
                            executor.shutdown(wait=False, cancel_futures=True)
                        print(f"[ChatClient] Model {model_to_call} timed out after {model_timeout}s. Fast-switching to next model...")
                        break
                    except Exception as e:
                        if executor is not None:
                            executor.shutdown(wait=False, cancel_futures=True)
                        err_str = str(e).lower()
                        is_transient = any(tok in err_str for tok in ("503", "unavailable", "overloaded", "429", "resource_exhausted", "500", "internal"))
                        if attempt == 0 and is_transient and (deadline - time.monotonic()) >= 3.5:
                            print(f"[ChatClient] Model {model_to_call} transient error ({e}). Quick retry...")
                            time.sleep(0.35)
                            continue
                        print(f"[ChatClient] Model {model_to_call} error: {e}. Fast-switching to next model...")
                        break

        # Smart fallback responder for testing or when offline
        return {
            "reply": self._smart_mock_response(conversation_history, user_profile, config),
            **fallback_behavior,
            "source": "mock_fallback",
        }

    def generate_response(
        self,
        conversation_history: List[Dict[str, str]],
        user_profile: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Backwards-compatible plain-text wrapper returning the salesperson reply.
        """
        return self.generate_analysis(
            conversation_history=conversation_history,
            user_profile=user_profile,
            config=config,
        )["reply"]

    @staticmethod
    def _build_contact_correction_reply(
        issue: Dict[str, str],
        user_name: Optional[str] = None,
        tone: str = "",
    ) -> str:
        """Ask visitor in the configured tone to fix an incomplete or malformed email/phone."""
        low_tone = (tone or "").lower()
        name_prefix = f"{user_name}, " if user_name else ""
        ctype = issue.get("type", "contact")
        val = issue.get("value", "")
        reason = issue.get("reason", "incomplete format")
        example = "name@gmail.com" if ctype == "email" else "e.g. +92 300 1234567"

        if any(w in low_tone for w in ("rude", "aggressive", "blunt", "abusive", "harsh", "impatient", "direct", "sarcastic")):
            return f"{name_prefix}'{val}' isn't a valid {ctype} ({reason}). Send the full {ctype} ({example}) so I can actually log it."
        if any(w in low_tone for w in ("formal", "confidential", "executive", "legal")):
            return f"{name_prefix}thank you, though '{val}' appears incomplete ({reason}). Could you please provide your complete {ctype} ({example}) so our team can reach you?"
        return f"{name_prefix}it looks like '{val}' is incomplete ({reason}). Could you share your full {ctype} ({example}) so our team can reach out?"

    @classmethod
    def _enforce_contact_integrity(
        cls,
        parsed: Dict[str, Any],
        last_user_raw: str,
        user_profile: Optional[Dict[str, Any]],
        config: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Prevent the LLM from falsely confirming capture when a malformed email/phone was sent."""
        from backend.lead_manager import detect_invalid_contact_attempt, extract_lead_from_message

        profile = user_profile or {}
        issue = profile.get("_contact_validation_issue")
        if not issue:
            ex = extract_lead_from_message(last_user_raw)
            issue = detect_invalid_contact_attempt(
                last_user_raw,
                found_email=ex.get("email"),
                found_phone=ex.get("phone"),
            )

        if not issue or profile.get(issue.get("type", "")):
            return parsed

        reply_low = (parsed.get("reply") or "").lower()
        already_flagged = any(
            w in reply_low
            for w in (
                "incomplete", "invalid", "missing", "full email", "complete email",
                "valid email", "double check", "double-check", "typo", "full number",
                "complete phone", "valid phone", "re-enter", "looks off",
            )
        )
        false_confirm = bool(
            re.search(
                r"\b(noted your (?:email|contact|number|details)|saved your (?:email|contact|number|details)|"
                r"got your (?:email|contact|number)|recorded your (?:email|contact|number)|"
                r"in your inbox|to your inbox|reach out (?:soon|shortly)|on file)\b",
                reply_low,
            )
        )
        if not already_flagged or false_confirm:
            tone = (config or {}).get("tone") or ""
            parsed["reply"] = cls._build_contact_correction_reply(
                issue=issue,
                user_name=profile.get("name"),
                tone=tone,
            )
            parsed["sales_tactic"] = "Contact Format Clarification"

        if parsed.get("sales_stage") == "post_capture":
            parsed["sales_stage"] = "closing"
        parsed["lead_score"] = min(int(parsed.get("lead_score") or 55), 70)

        # Privacy guard: if user asked for company contact, ensure reply never leaks visitor's stored lead data
        company_contact_phrases = (
            "contact detail", "contact details", "contact info", "contact information",
            "your contact", "how to contact", "how can i contact", "how do i contact",
            "who can i contact", "where can i contact", "company email", "your email",
            "official email", "support email", "phone number", "phone no", "mobile number",
            "whatsapp number", "call you", "reach you", "reach out", "how to reach",
            "contact number", "contact us", "contact you",
        )
        msg_low = (last_user_raw or "").lower()
        if any(p in msg_low for p in company_contact_phrases):
            is_asking_own = any(k in msg_low for k in ("my name", "my email", "my phone", "my contact", "what is my", "whats my", "do you know my"))
            if not is_asking_own:
                user_email = profile.get("email")
                user_phone = profile.get("phone")
                rep = parsed.get("reply") or ""
                if (user_email and user_email.lower() in rep.lower()) or (user_phone and user_phone in rep):
                    biz_name = (config or {}).get("businessName") or COMPANY_OR_SOFTWARE_NAME
                    kb = (config or {}).get("knowledgeBase") or ""
                    parsed["reply"] = cls._build_company_contact_reply(biz_name, kb, (config or {}).get("tone") or "")

        return parsed

    @classmethod
    def _enforce_greeting_pacing(
        cls,
        parsed: Dict[str, Any],
        last_user_raw: str,
        config: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Prevent over-replying or unsolicited status reports on simple standalone greetings (e.g. 'hi' or 'hello')."""
        import re
        clean_user = re.sub(r"[^a-z\s']", "", (last_user_raw or "").lower()).strip()
        standalone_greetings = {"hi", "hello", "hey", "hiya", "howdy", "salam", "assalam", "assalam o alaikum", "good morning", "good afternoon", "good evening"}

        is_bare = clean_user in standalone_greetings
        has_question = any(q in clean_user for q in ("how are", "how r", "hows", "how is", "how do you", "what", "where", "can you", "?")) or "?" in (last_user_raw or "")

        if is_bare and not has_question:
            reply = parsed.get("reply", "")
            biz_name = (config or {}).get("businessName") or "our team"

            has_unsolicited_status = bool(re.search(r"\b(?:doing\s+(?:great|well)|thanks\s+for\s+(?:asking|stopping\s+by))\b", reply, re.IGNORECASE))
            has_multi_menu = bool(re.search(r"\b(?:are\s+you\s+looking\s+to|whether\s+you(?:'re|\s+are))\b.*\b(?:or\s+just|or\s+perhaps|or\s+check)\b", reply, re.IGNORECASE))
            is_too_long = len(reply.split()) > 20

            if has_unsolicited_status or has_multi_menu or is_too_long:
                tone = ((config or {}).get("tone") or "").lower()
                if "motivat" in tone or "energy" in tone:
                    parsed["reply"] = f"Hey! Welcome to {biz_name}. How can I help you crush your goals today?"
                elif "calm" in tone or "reassur" in tone:
                    parsed["reply"] = f"Hello! Welcome to {biz_name}. How can I help you today?"
                elif "formal" in tone or "legal" in tone:
                    parsed["reply"] = f"Good day. Welcome to {biz_name}. How may I assist you today?"
                elif "style" in tone or "sophisticat" in tone:
                    parsed["reply"] = f"Hello! Welcome to {biz_name}. How may I assist you today?"
                else:
                    parsed["reply"] = f"Hi! Welcome to {biz_name}. How can I help you today?"
                parsed["sales_stage"] = "greeting"
                parsed["sales_tactic"] = "Warm Hospitality"
        return parsed

    @staticmethod
    def _format_kb_prose(lines: List[str]) -> str:
        """Convert raw KB bullet lines or sentences into clean, conversational prose."""
        cleaned = []
        for raw in lines:
            s = re.sub(r"^\s*[-*•#]+\s*", "", raw or "").strip()
            if not s:
                continue
            # Strip markdown bold/italic asterisks cleanly
            s = s.replace("**", "").replace("*", "").strip()
            # Discard incomplete hanging lead-ins like "including:" or "such as:"
            if any(s.lower().endswith(w) for w in ("including:", "including", "such as:", "such as", "as follows:")):
                continue
            if ":" in s and not s.lower().startswith(("http://", "https://")):
                head, tail = s.split(":", 1)
                tail = tail.strip()
                if tail and len(head.strip()) <= 36:
                    s = f"{head.strip()} — {tail}"
            clean_end = s.rstrip('”"\'’):')
            if clean_end and clean_end[-1] not in ".!?":
                s = clean_end + "."
            cleaned.append(s)
        return " ".join(cleaned)

    @staticmethod
    def _split_into_sentences(text: str) -> List[str]:
        """Split prose text into clean natural sentences protecting decimals, quotes, and abbreviations."""
        if not text:
            return []
        masked = re.sub(r"(\d+)\.(\d+)", r"\1__DEC__\2", text)
        for abbr in ("Dr.", "Mr.", "Ms.", "Prof.", "Inc.", "Ltd.", "vs.", "e.g.", "i.e.", "approx."):
            masked = masked.replace(abbr, abbr.replace(".", "__DOT__"))
        def _mask_inner_quote_dots(m):
            content = m.group(0)
            inner = content[1:-2]
            tail = content[-2:]
            return content[0] + inner.replace(".", "__QDOT__") + tail
        masked = re.sub(r"[“\"][^”\"]+[”\"]", _mask_inner_quote_dots, masked)
        marked = re.sub(r'([.!?][”"’\']?)\s+([A-Z0-9“"‘\'])', r'\1__SPLIT__\2', masked)
        raw_sents = marked.split('__SPLIT__')
        parts = []
        for s in raw_sents:
            clean = s.replace("__DEC__", ".").replace("__DOT__", ".").replace("__QDOT__", ".").strip()
            if clean:
                parts.append(clean)
        return parts

    @classmethod
    def _parse_kb_units(cls, kb: str) -> List[Dict[str, Any]]:
        """Parse any KB into structured units with section context, sentence boundaries, and heading flags."""
        if not kb or not kb.strip():
            return []
        lines = kb.splitlines()
        units: List[Dict[str, Any]] = []
        current_section = "General"

        heading_keywords = {
            "about", "overview", "services", "capabilities", "specialties", "products",
            "portfolio", "case studies", "projects", "track record", "clients",
            "pricing", "plans", "packages", "cost", "fees", "contact", "location",
            "hours", "team", "mission", "values", "faq", "holovox"
        }

        def _is_heading(s: str) -> bool:
            s = s.strip()
            if not s:
                return False
            if re.match(r"^#{1,6}\s+", s):
                return True
            if re.match(r"^\d+\.\s+[A-Za-z0-9\s&/,\-–—]+:?$", s):
                return True
            if s.endswith(":") and len(s) <= 60 and not s.lower().startswith(("http://", "https://")):
                return True
            if len(s) <= 50 and s[-1] not in ".!?;,":
                low = s.lower()
                if s.isupper() or s.istitle() or any(hw in low for hw in heading_keywords):
                    return True
            return False

        def _clean_heading(s: str) -> str:
            s = re.sub(r"^#{1,6}\s+", "", s).strip()
            s = re.sub(r"^\d+\.\s+", "", s).strip()
            s = s.rstrip(":")
            return s.strip()

        for raw in lines:
            raw_strip = raw.strip()
            if not raw_strip:
                continue
            if _is_heading(raw_strip):
                current_section = _clean_heading(raw_strip)
                continue

            is_bullet = bool(re.match(r"^\s*[-*•]\s+|\s*\d+\.\s+", raw_strip))
            if is_bullet:
                clean_b = re.sub(r"^\s*[-*•]\s+|\s*\d+\.\s+", "", raw_strip).strip()
                if clean_b:
                    units.append({
                        "section": current_section,
                        "text": clean_b,
                        "is_heading": False,
                        "tokens": set(re.findall(r"[a-z0-9]{2,}", clean_b.lower()))
                    })
            else:
                sents = cls._split_into_sentences(raw_strip)
                for sent in sents:
                    if len(sent) >= 5:
                        units.append({
                            "section": current_section,
                            "text": sent,
                            "is_heading": False,
                            "tokens": set(re.findall(r"[a-z0-9]{2,}", sent.lower()))
                        })
        return units

    @classmethod
    def _extract_kb_section(cls, kb: str, section_keywords: tuple, limit: int = 5) -> List[str]:
        """Collect content units under matching KB section headings (e.g. Services, Portfolio, Pricing)."""
        if not kb:
            return []
        units = cls._parse_kb_units(kb)
        collected = []
        for u in units:
            sec_low = u["section"].lower()
            if any(kw in sec_low for kw in section_keywords):
                collected.append(u["text"])
                if len(collected) >= limit:
                    break
        return collected

    @classmethod
    def _search_kb_lines(
        cls,
        kb: str,
        keywords: List[str],
        limit: int = 2,
        whole_word: bool = False,
    ) -> List[str]:
        """Return the highest-relevance KB sentences or bullets, strictly excluding raw headings."""
        if not kb or not keywords:
            return []
        units = cls._parse_kb_units(kb)
        if not units:
            return []

        stop_words = {
            "am", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "it",
            "of", "on", "or", "that", "the", "this", "to", "with", "what", "how", "who", "where",
            "do", "does", "can", "tell", "me", "about"
        }
        clean_kws = [kw.lower() for kw in keywords if kw.lower() not in stop_words and len(kw) >= 2]
        if not clean_kws:
            clean_kws = [kw.lower() for kw in keywords]

        scored = []
        for u in units:
            text_low = u["text"].lower()
            sec_low = u["section"].lower()
            score = 0
            for kw in clean_kws:
                if whole_word:
                    pat = r"\b" + re.escape(kw) + r"\b"
                    hit_text = bool(re.search(pat, text_low))
                    hit_sec = bool(re.search(pat, sec_low))
                else:
                    hit_text = kw in text_low
                    hit_sec = kw in sec_low

                # Phonetic & typo variations (e.g. w <-> v, or stripped hyphens)
                if not hit_text and not hit_sec and len(kw) >= 4:
                    variants = [
                        kw.replace("w", "v"),
                        kw.replace("v", "w"),
                        kw.replace("-", ""),
                        kw.replace(" ", "")
                    ]
                    for var in variants:
                        if var != kw:
                            if whole_word:
                                vpat = r"\b" + re.escape(var) + r"\b"
                                if re.search(vpat, text_low):
                                    hit_text = True
                                    break
                                if re.search(vpat, sec_low):
                                    hit_sec = True
                                    break
                            else:
                                if var in text_low:
                                    hit_text = True
                                    break
                                if var in sec_low:
                                    hit_sec = True
                                    break

                # Fuzzy similarity for longer tokens (len >= 5)
                if not hit_text and not hit_sec and len(kw) >= 5:
                    import difflib
                    for word in u["tokens"]:
                        if abs(len(word) - len(kw)) <= 2:
                            if difflib.SequenceMatcher(None, kw, word).ratio() >= 0.82:
                                hit_text = True
                                break
                    if not hit_sec:
                        for sec_word in re.findall(r"[a-z0-9]{3,}", sec_low):
                            if abs(len(sec_word) - len(kw)) <= 2:
                                if difflib.SequenceMatcher(None, kw, sec_word).ratio() >= 0.82:
                                    hit_sec = True
                                    break

                if hit_text:
                    score += 3
                    if ":" in text_low and kw in text_low.split(":", 1)[0]:
                        score += 4
                    # Canonical definition bonus: "X is..." or "X are..." or starts with keyword
                    if (
                        text_low.startswith(f"{kw} is")
                        or text_low.startswith(f"{kw} are")
                        or any(text_low.startswith(f"{var} is") for var in (kw.replace("w", "v"), kw.replace("v", "w")))
                    ):
                        score += 8
                    elif text_low.startswith(kw) or any(text_low.startswith(f"{w} {kw}") for w in ("in", "for", "our", "the", "it is", "among")):
                        score += 4
                if hit_sec:
                    score += 4

            # Boost relevant units when specific intents are queried
            if any(k in clean_kws for k in ("price", "cost", "pricing", "$", "pkr", "rate", "fee")) and any(m in text_low for m in ("$", "pkr", "rs", "usd", "starting at", "starting from")):
                score += 6
            if any(k in clean_kws for k in ("address", "located", "location", "office", "headquarters", "where")) and any(m in text_low for m in ("headquartered", "suite", "building", "road", "street", "clifton", "dha", "karachi")):
                score += 5
            if any(k in clean_kws for k in ("ceo", "director", "founder", "leads", "who", "bilal", "hashmi", "zubair")) and any(m in text_low for m in ("ceo", "director", "founder", "syed bilal hashmi", "muhammad zubair")):
                score += 15
            if any(k in clean_kws for k in ("who", "bilal", "hashmi", "zubair", "founder", "ceo", "director")) and any(m in text_low for m in ("phone and whatsapp", "+92", "tel:", "call:", "email:")):
                score -= 10
            if any(k in clean_kws for k in ("motto", "values", "mission")) and "motto" in text_low:
                score += 6
            if any(k in clean_kws for k in ("sla", "uptime", "support", "coverage")) and any(m in text_low for m in ("sla", "uptime", "24/7", "iso 27001")):
                score += 6
            if any(k in clean_kws for k in ("clients", "customers")) and any(m in text_low for m in ("clients are", "among its clients", "worked with")):
                score += 6

            if score > 0:
                scored.append((score, u["text"]))

        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored:
            return []
        best_score = scored[0][0]
        if best_score >= 6:
            scored = [item for item in scored if item[0] >= best_score - 2]
        return [text for _, text in scored[:limit]]

    def _smart_mock_response(
        self,
        history: List[Dict[str, str]],
        user_profile: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> str:
        """Rule-based KB-grounded fallback when offline or live API budget is exhausted."""
        import re

        cfg = config or {}
        biz_name = cfg.get("businessName") or COMPANY_OR_SOFTWARE_NAME
        agent_name = cfg.get("agentName") or BOT_NAME
        tone = (cfg.get("tone") or "").lower()
        goal = (cfg.get("agentGoal") or "book a consultation or share your contact details").strip()
        kb = cfg.get("knowledgeBase") or ""

        is_blunt = any(w in tone for w in ("rude", "aggressive", "blunt", "abusive", "harsh", "impatient", "direct", "sarcastic"))
        is_formal = any(w in tone for w in ("formal", "confidential", "executive", "legal"))
        is_energetic = any(w in tone for w in ("high-energy", "energetic", "motivational", "excited", "playful"))

        if not history:
            return f"Hello! I'm {agent_name} from {biz_name}. Let's get started — are you ready to {goal[0].lower() + goal[1:] if len(goal) > 1 else goal}?"

        from backend.lead_manager import detect_invalid_contact_attempt, extract_lead_from_message

        last_user_raw = history[-1]["content"].strip()
        last_user_msg = last_user_raw.lower()
        user_name = user_profile.get("name") if user_profile else None
        user_email = user_profile.get("email") if user_profile else None
        user_phone = user_profile.get("phone") if user_profile else None
        contact_label = user_email or user_phone
        has_known_contact = bool(contact_label)
        extracted_now = extract_lead_from_message(last_user_raw)
        newly_shared_contact = bool(extracted_now.get("email") or extracted_now.get("phone"))
        invalid_contact = (user_profile or {}).get("_contact_validation_issue") or detect_invalid_contact_attempt(
            last_user_raw,
            found_email=extracted_now.get("email"),
            found_phone=extracted_now.get("phone"),
        )
        greeting_name = f", {user_name}" if user_name else ""
        behavior = self._classify_behavior_heuristic(history, user_profile)

        if invalid_contact and not (user_profile or {}).get(invalid_contact.get("type", "")):
            return self._build_contact_correction_reply(
                issue=invalid_contact,
                user_name=user_name,
                tone=tone,
            )

        def goal_hook() -> str:
            if has_known_contact:
                return ""
            goal_lower = goal[0].lower() + goal[1:] if len(goal) > 1 else goal
            if is_blunt:
                return f" Share your phone or email now if you want us to {goal_lower}."
            if is_formal:
                return f" Should you wish to proceed, please provide your name and contact details to {goal_lower}."
            return f" Ready to {goal_lower}? Share your name and phone or email to get started."

        # 1. Off-topic general query fallback
        if behavior["buyer_intent"] == "off_topic":
            if is_blunt:
                return f"Stick to {biz_name} topics—we don't handle random trivia here.{goal_hook()}"
            return f"My focus is strictly on assisting you with {biz_name}.{goal_hook()}"

        # 2. Explicit disinterest / opt-out / competitor switch
        if behavior["sales_tactic"] == "Graceful Exit + Door Open":
            if is_blunt:
                return f"Fine{greeting_name}, noted. Reach out to {biz_name} whenever you're serious."
            return f"Understood{greeting_name}. Thank you for considering {biz_name}, and reach back out anytime if your plans change."

        # 3. Transparent AI identity / human handoff requests
        if behavior["sales_tactic"] == "Transparent AI Introduction":
            if has_known_contact:
                return f"I'm {agent_name}, {biz_name}'s virtual AI assistant, and our team already has your contact info on file."
            return f"I'm {agent_name}, {biz_name}'s virtual AI assistant.{goal_hook()}"

        if behavior["sales_tactic"] == "Human Handoff Offer":
            if has_known_contact:
                return f"Done{greeting_name}—our human team at {biz_name} already has {contact_label} on file."
            return f"Drop your name and phone or email{greeting_name} so a specialist at {biz_name} can follow up."

        # 4. Polite time deferral / revisit later
        if any(p in last_user_msg for p in self._DEFERRAL_PHRASES):
            if has_known_contact:
                return f"Noted{greeting_name}—we already have {contact_label} and {biz_name} is ready whenever you are."
            return f"Reach back out to {biz_name} whenever you're ready{greeting_name}, or drop your email/phone now to lock in your spot."

        # 4.5. Personal Check-in / How are you
        is_check_in = any(p in last_user_msg for p in (
            "how are you", "how r u", "how are u", "how are you doing", "how do you do",
            "how is your day", "how's your day", "hows your day", "how is it going",
            "hows it going", "how are things", "hope you are well", "hope all is well", "are you good"
        ))
        if is_check_in:
            if is_blunt:
                return f"Doing well{greeting_name}. What software or AI project can {biz_name} help you evaluate today?"
            return f"I'm doing great, thank you for asking{greeting_name}! Hope you're having a productive day as well. How can {biz_name} help you today?"

        # 5. Pure greeting
        clean_ack = re.sub(r"[^a-z\s']", "", last_user_msg).strip()
        is_pure_greeting = clean_ack in self._GREETING_EXACT or self._is_greeting_message(last_user_msg)
        if is_pure_greeting:
            if is_blunt:
                return f"{agent_name} at {biz_name} here. Tell me what you need so we can {goal[0].lower() + goal[1:] if len(goal) > 1 else goal}."
            if is_energetic:
                return f"Hey{greeting_name}! {agent_name} from {biz_name} here — what can we help you accomplish today?"
            return f"Hello{greeting_name}! I'm {agent_name} at {biz_name}. How can I help you today?"

        # 5.5 Short vague continuation ("tell me", "what do you do", "go on")
        if clean_ack in ("tell me", "tell me more", "explain", "go on", "what do you do", "what can you do", "overview", "what are your services", "what services"):
            return f"At {biz_name}, we specialize in 3 core engineering pillars: Custom AI & Autonomous Agents, Audited Blockchain & Web3 Systems, and High-Performance Web & Mobile platforms (plus our call-coaching product HOLOVOX). Are you looking to scope a new build from scratch, or automate something in your existing business?"

        # 6. Farewell
        if any(w in last_user_msg for w in ["bye", "goodbye", "see you", "cya", "have to go"]):
            if has_known_contact:
                return f"Goodbye{greeting_name}! Our team at {biz_name} has your details and will follow up shortly."
            return f"Goodbye{greeting_name}!{goal_hook()}"

        # 7. Short casual acknowledgment / thinking noise ("hmm", "alright", "sounds good")
        if clean_ack in self._ACK_EXACT:
            if is_blunt:
                return f"Got it{greeting_name}.{goal_hook() or f' Tell me your next question about {biz_name}.'}"
            return f"Understood{greeting_name}.{goal_hook() or f' Let me know what else you need from {biz_name}.'}"

        # 8. Job / Career inquiries (refer to company/careers email instead of pitching services)
        if self._is_career_inquiry(last_user_msg):
            return self._build_career_referral_reply(biz_name, kb, tone)

        # 5. Schedule / Hours / Location (checked BEFORE booking so "consultation hours" isn't hijacked)
        hours_phrases = (
            "timing", "timings", "consultation hours", "opening hours", "office hours",
            "business hours", "what hours", "hours", "weekday", "weekdays", "weekend",
            "saturday", "sunday", "are you open", "when do you open", "open today",
        )
        address_phrases = ("location", "address", "where are you", "where is your", "located", "headquarters", "head office")
        wants_hours = any(w in last_user_msg for w in hours_phrases)
        wants_address = any(w in last_user_msg for w in address_phrases)
        if wants_hours or wants_address:
            loc_keywords: List[str] = []
            if wants_address:
                loc_keywords.extend(["address", "headquarters address", "headquarters", "headquartered", "head office", "located", "location", "building", "suite", "road", "street", "karachi"])
            if wants_hours:
                loc_keywords.extend(["working hours", "office hours", "hours", "hour", "mon", "tue", "fri", "sat", "sun", "weekday", "weekend"])
            matches = self._search_kb_lines(kb, loc_keywords, limit=2 if (wants_hours and wants_address) else 1)
            if not matches and wants_address:
                matches = self._search_kb_lines(kb, ["suite", "building", "road", "phase", "clifton", "dha", "karachi"], limit=1)
            if matches:
                prose = self._format_kb_prose(matches)
                suffix = goal_hook() if is_blunt else ""
                return f"{prose}{suffix}"
            suffix = goal_hook() if is_blunt else ""
            return f"{biz_name} operates during listed business hours; check with us to confirm exact availability.{suffix}"

        # 6. Company Contact Information (Official channels from KB) vs Customer Lead Privacy
        company_contact_phrases = (
            "contact detail", "contact details", "contact info", "contact information",
            "your contact", "how to contact", "how can i contact", "how do i contact",
            "who can i contact", "where can i contact", "company email", "your email",
            "official email", "support email", "phone number", "phone no", "mobile number",
            "whatsapp number", "call you", "reach you", "reach out", "how to reach",
            "contact number", "contact us", "contact you",
        )
        is_asking_company_contact = any(p in last_user_msg for p in company_contact_phrases) and not newly_shared_contact
        is_asking_own_info = not newly_shared_contact and (
            any(k in last_user_msg for k in (
                "what is my", "whats my", "what's my", "do you know my", "do you have my",
                "on file for me", "what email do you have", "what phone do you have",
                "what number do you have", "what details do you have", "what info do you have",
                "what do you have for me", "who am i", "which email do you have"
            )) or (
                any(k in last_user_msg for k in ("my email?", "my phone?", "my name?", "my number?", "my contact?"))
            ) or (
                ("?" in last_user_msg) and any(k in last_user_msg for k in ("for me", "about me", "my email", "my phone", "my name")) and not any(v in last_user_msg for v in ("build", "create", "launch", "make", "recommend", "quote", "cost", "price"))
            )
        )
        if is_asking_company_contact and not is_asking_own_info:
            return self._build_company_contact_reply(biz_name, kb, tone)
        if is_asking_own_info:
            if has_known_contact or user_name:
                if "email" in last_user_msg and user_email and not ("phone" in last_user_msg or "name" in last_user_msg):
                    return f"We have {user_email} on file as your email{greeting_name}."
                if ("name" in last_user_msg or "who am i" in last_user_msg) and user_name and not ("email" in last_user_msg or "phone" in last_user_msg):
                    return f"We have your name saved as {user_name}{greeting_name}."
                if ("phone" in last_user_msg or "number" in last_user_msg) and user_phone and not "email" in last_user_msg:
                    return f"We have {user_phone} on file as your phone number{greeting_name}."
                parts = []
                if user_name: parts.append(f"name: {user_name}")
                if user_email: parts.append(f"email: {user_email}")
                if user_phone: parts.append(f"phone: {user_phone}")
                return f"We have your {', '.join(parts)} on file{greeting_name}."
            return f"I don't have your contact details saved yet{greeting_name}."

        # 6a. Leadership / Founder / Executive Team inquiries ("who is bilal", "who is the ceo", "who founded")
        leadership_triggers = (
            "bilal", "hashmi", "zubair", "ceo", "founder", "co-founder", "director", "owner",
            "who founded", "who started", "who created", "who leads", "who runs", "leadership",
            "executive team", "management team", "who is in charge"
        )
        is_leadership_query = any(t in last_user_msg for t in leadership_triggers) and not newly_shared_contact
        if is_leadership_query and not any(p in last_user_msg for p in ("my name is", "i am bilal", "i'm bilal", "call me bilal")):
            leadership_reply = self._build_leadership_inquiry_reply(
                biz_name=biz_name,
                kb=kb,
                last_user_msg=last_user_msg,
                tone=tone,
                greeting_name=greeting_name,
                has_known_contact=has_known_contact,
                goal_hook=goal_hook,
            )
            if leadership_reply:
                return leadership_reply

        # 6. Skeptical / Trust / Proof inquiries
        if behavior["emotion"] == "skeptical":
            proof_matches = self._search_kb_lines(
                kb,
                ["4,500", "120+", "950", "4.9", "award", "medal", "rating", "years", "experience", "enterprise", "client", "guarantee", "certified", "specialist"],
            )
            if proof_matches:
                prose = self._format_kb_prose(proof_matches)
                lead_in = "" if is_blunt else "Fair question — here's what backs us up: "
                suffix = "" if behavior["emotion"] == "frustrated" else goal_hook()
                return f"{lead_in}{prose}{suffix}"

        # 7. Pricing / Installments / Cost objections
        if behavior["emotion"] == "price_hesitant" or any(
            w in last_user_msg for w in ["price", "pricing", "cost", "how much", "rate", "fee", "installment"]
        ):
            price_matches = self._search_kb_lines(kb, ["pkr", "$", "price", "starting", "plan", "installment", "0%", "free", "cost"])
            if price_matches:
                prose = self._format_kb_prose(price_matches)
                if behavior["emotion"] == "price_hesitant" and not is_blunt:
                    lead_in = "I completely understand keeping budget in mind — "
                else:
                    lead_in = ""
                suffix = "" if behavior["emotion"] == "frustrated" else goal_hook()
                return f"{lead_in}{prose}{suffix}"
            return f"Pricing depends on your selected option at {biz_name}.{goal_hook()}"

        # 8. Out-of-KB city / entity trap vs direct KB query match
        known_external_cities = ["new york", "nyc", "london", "dubai", "islamabad", "lahore"]
        mentioned_missing_city = next((c for c in known_external_cities if c in last_user_msg and c not in kb.lower()), None)
        if mentioned_missing_city:
            loc_matches = self._search_kb_lines(kb, ["address", "located", "dha", "clifton", "karachi", "office", "exclusively"])
            loc_note = f" Our confirmed service coverage is {self._format_kb_prose(loc_matches[:1])}" if loc_matches else ""
            return f"We do not have listings or services confirmed in {mentioned_missing_city.title()}.{loc_note}"

        stop_words = {
            "am", "an", "and", "any", "are", "as", "at", "be", "before", "built", "by",
            "can", "com", "could", "did", "do", "does", "done", "email", "for", "from",
            "get", "give", "gmail", "have", "help", "hotmail", "how", "if", "in", "into",
            "io", "is", "it", "just", "know", "make", "me", "more", "much", "my", "name",
            "need", "net", "no", "not", "now", "of", "offer", "on", "only", "oops", "or",
            "org", "our", "outlook", "over", "perform", "please", "provide", "sell",
            "share", "should", "so", "some", "sorry", "take", "tell", "that", "the",
            "their", "them", "there", "these", "they", "this", "those", "to", "too",
            "us", "very", "want", "we", "what", "when", "where", "which", "who", "why",
            "will", "with", "work", "would", "yahoo", "yes", "you", "your", "about",
            "interested", "anymore", "been", "good",
            "next", "step", "steps", "after", "then", "way", "start", "begin",
            "phase", "part", "process", "roadmap", "road", "map", "today", "here", "there",
        }
        if newly_shared_contact and "?" not in last_user_msg:
            return f"Saved your contact info{greeting_name}. Our team at {biz_name} will follow up regarding your inquiry."
        user_turns = sum(1 for m in (history or []) if m.get("role") == "user")
        wants_booking = any(
            w in last_user_msg
            for w in ("book", "appointment", "viewing", "schedule", "demo", "trial", "consultation", "call me")
        )

        def _finish_kb_reply(prose_text: str) -> str:
            if behavior["emotion"] == "frustrated" or has_known_contact or "?" in prose_text:
                return prose_text
            if wants_booking or behavior["emotion"] in ("urgent", "excited") or behavior["buyer_intent"] in ("hot", "urgent") or is_blunt:
                return f"{prose_text}{goal_hook()}"
            if len(prose_text.split()) > 24:
                return prose_text
            if user_turns <= 1:
                return f"{prose_text} Are you looking to start a new project?"
            return f"{prose_text} What specific features are you looking to build?"

        # Check explicit unconfirmed policy terms absent from KB (e.g., NDA, refunds, SLA)
        for policy_kw in ("nda", "non-disclosure", "refund", "money-back", "warranty", "sla"):
            kw_pat = r"\b" + re.escape(policy_kw) + r"\b"
            if re.search(kw_pat, last_user_msg) and not re.search(kw_pat, kb.lower()):
                return (
                    f"I don't have our exact {policy_kw.upper() if len(policy_kw) <= 3 else policy_kw} terms handy right here — "
                    f"our team at {biz_name} can confirm that with you on a quick call.{'' if (has_known_contact or behavior['emotion'] == 'frustrated') else goal_hook()}"
                )

        # Educational roadmap requests & context-aware "next step" follow-ups (checked early before token search)
        guidance_reply = self._build_contextual_guidance_reply(
            last_user_msg=last_user_msg,
            history=history,
            biz_name=biz_name,
            greeting_name=greeting_name,
            is_blunt=is_blunt,
            behavior=behavior,
        )
        if guidance_reply:
            return guidance_reply

        # Check previous bot message in conversation history
        prev_bot_text = ""
        for m in reversed(history[:-1] if len(history) > 1 else []):
            if m.get("role") == "assistant" and m.get("content"):
                prev_bot_text = m["content"].lower()
                break

        # Continuation & detail requests ("details of these", "give details", "explain more", "details?")
        clean_follow = re.sub(r"[^a-z\s]", "", last_user_msg).strip()
        is_detail_req = bool(
            re.search(r"\b(?:details?|detail|explain|elaborate|breakdown|break down|tell me more|more info|information on|deep details)\b", last_user_msg)
            or clean_follow in {"more", "details", "what else", "anything else", "go on", "continue", "aur", "aur batao"}
        )

        prev_offered_services = any(w in prev_bot_text for w in ("core capabilities", "capabilities include", "services include", "our services", "software services", "deep details on any of these"))
        prev_offered_portfolio = any(w in prev_bot_text for w in ("featured portfolio", "portfolio projects", "past projects"))

        if is_detail_req:
            # Check if user specified a particular domain in their detail request
            if re.search(r"\b(?:ai|artificial intelligence|machine learning|ml|nlp|chatbots?)\b", last_user_msg):
                ai_lines = self._search_kb_lines(kb, ["ai", "chatbots", "machine learning", "nlp"], limit=2)
                if ai_lines:
                    return _finish_kb_reply(self._format_kb_prose(ai_lines))
            if re.search(r"\b(?:blockchain|web3|smart contracts?|crypto|defi|tokens?|wallets?)\b", last_user_msg):
                bc_lines = self._search_kb_lines(kb, ["blockchain", "smart contracts", "web3"], limit=2)
                if bc_lines:
                    return _finish_kb_reply(self._format_kb_prose(bc_lines))
            if re.search(r"\b(?:web|web development|crm|saas|e-commerce|ecommerce|dashboards?)\b", last_user_msg):
                web_lines = self._search_kb_lines(kb, ["web development", "crm", "saas", "e-commerce"], limit=2)
                if web_lines:
                    return _finish_kb_reply(self._format_kb_prose(web_lines))
            if re.search(r"\b(?:holovox|holowox|call coaching|holo glasses|glasses|coaching)\b", last_user_msg):
                holo_lines = self._search_kb_lines(kb, ["holovox", "coaching", "glasses"], limit=2)
                if holo_lines:
                    return _finish_kb_reply(self._format_kb_prose(holo_lines))

            # General detail request following an overview (e.g. "Details of these", "details on all of them", "explain more")
            if prev_offered_services or re.search(r"\b(?:services?|capabilities|these|all of these|all of them|all|both|each)\b", last_user_msg):
                svc_lines = self._extract_kb_section(kb, ("service", "capabilit", "specialt", "program", "product"), limit=6)
                if svc_lines:
                    return _finish_kb_reply(self._format_kb_prose(svc_lines))

            if prev_offered_portfolio or re.search(r"\b(?:portfolio|projects?|case stud)\b", last_user_msg):
                port_lines = self._extract_kb_section(kb, ("portfolio", "case stud", "featured project", "past project"), limit=8)
                if port_lines:
                    return _finish_kb_reply(self._format_kb_prose(port_lines))

            candidate_lines = (
                self._extract_kb_section(kb, ("service", "capabilit", "specialt", "program", "product"), limit=6)
                + self._extract_kb_section(kb, ("portfolio", "case stud", "track record", "featured"), limit=4)
                + self._extract_kb_section(kb, ("pric", "fee", "engagement", "plan", "package"), limit=3)
            )
            fresh_lines = []
            for ln in candidate_lines:
                head = ln.split(":", 1)[0].strip().lstrip("-*• ").lower() if ":" in ln else ln[:28].lower()
                if head and head not in prev_bot_text:
                    fresh_lines.append(ln)
                if len(fresh_lines) >= 2:
                    break
            if fresh_lines:
                return _finish_kb_reply(self._format_kb_prose(fresh_lines))
            return (
                f"At {biz_name}, I can share specifics on our services, past projects, or engagement pricing — "
                f"which would be most useful for you next?"
            )

        # Broad Services / Portfolio section summaries
        if re.search(r"\b(?:services?|capabilities|what do you do|what can you build|offerings?)\b", last_user_msg):
            svc_lines = self._extract_kb_section(kb, ("service", "capabilit", "specialt", "program", "product"), limit=6)
            if svc_lines:
                if is_detail_req:
                    return _finish_kb_reply(self._format_kb_prose(svc_lines))
                heads = [ln.split(":", 1)[0].strip().lstrip("-*• ") for ln in svc_lines if ":" in ln and len(ln.split(":", 1)[0]) <= 36]
                if heads:
                    head_summary = ", ".join(heads[:3])
                    return f"At {biz_name}, our core capabilities include {head_summary}. If you'd like deep details on any of these, let me know which area you're exploring!"
                lead_phrases = []
                for item in svc_lines:
                    m = re.match(r"^(?:in\s+)?([A-Za-z0-9\s&/\-]+?)(?:,|\s+—|\s+-|\s+bawdicsoft|\s+we|\s+it\s+delivers|\s+builds)", item, re.IGNORECASE)
                    if m and len(m.group(1).strip()) <= 30:
                        lead_phrases.append(m.group(1).strip().title())
                    elif len(item) <= 40:
                        lead_phrases.append(item.strip().rstrip("."))
                has_holovox = "holovox" in kb.lower()
                product_note = " and our flagship AI call coaching product HOLOVOX" if has_holovox and "holovox" not in "".join(lead_phrases).lower() else ""
                if lead_phrases:
                    unique_leads = list(dict.fromkeys(lead_phrases))[:3]
                    return f"At {biz_name}, our core capabilities include {', '.join(unique_leads)}{product_note}. If you'd like deep details on any of these, let me know which area you're exploring!"
                return _finish_kb_reply(self._format_kb_prose(svc_lines[:2]))

        is_portfolio_req = (
            re.search(r"\b(?:portfolio|past work|case stud(?:y|ies)|featured projects?)\b", last_user_msg)
            or bool(re.search(r"\b(?:projects? (?:have you|did you) (?:built|done|created|developed|worked on))\b", last_user_msg))
            or ("project" in last_user_msg and any(w in last_user_msg for w in ("show", "list", "see", "samples", "examples", "portfolio", "what projects")))
        ) and not any(m in last_user_msg for m in ("how many", "number of", "count"))
        if is_portfolio_req:
            port_lines = self._extract_kb_section(kb, ("portfolio", "case stud", "featured project", "past project"), limit=8)
            if port_lines:
                if is_detail_req:
                    return _finish_kb_reply(self._format_kb_prose(port_lines))
                featured_projects = []
                for item in port_lines:
                    m = re.match(r"^([A-Z0-9\-\s]{3,24}|[A-Z][a-zA-Z0-9\-]+(?:\s+[A-Za-z0-9\-]+){0,2})\s+(?:is|—|-|offers|provides|tracks|delivers)", item)
                    if m:
                        pname = m.group(1).strip()
                        if pname.lower() not in ("bawdicsoft", "we", "it", "our", "the", "the company"):
                            featured_projects.append(pname)
                if featured_projects:
                    unique_p = list(dict.fromkeys(featured_projects))[:4]
                    return f"Our featured portfolio projects at {biz_name} include {', '.join(unique_p)}. Would you like deep technical details on any of these?"
                return _finish_kb_reply(self._format_kb_prose(port_lines[:2]))

        sanitized_msg = re.sub(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9-.]+", " ", last_user_msg)
        query_tokens = [t for t in re.findall(r"[a-z0-9]{2,}", sanitized_msg) if t not in stop_words]
        kb_hits = self._search_kb_lines(kb, query_tokens, limit=2, whole_word=True)

        # Consultative project / product goal scoping (e.g. "i want to build a shopify store")
        if not wants_booking:
            project_scoping = self._build_project_scoping_reply(
                last_user_msg=last_user_msg,
                kb=kb,
                biz_name=biz_name,
                greeting_name=greeting_name,
                user_profile=user_profile,
                user_turns=user_turns,
                has_known_contact=has_known_contact,
                is_blunt=is_blunt,
                is_formal=is_formal,
                goal_hook=goal_hook,
                behavior=behavior,
                has_direct_kb_hit=bool(kb_hits),
            )
            if project_scoping:
                return project_scoping

        if kb_hits:
            return _finish_kb_reply(self._format_kb_prose(kb_hits))

        # 9. Booking / Appointment / Demo -> Lead Capture (never re-ask contact if known)
        if not newly_shared_contact and any(w in last_user_msg for w in ["book", "appointment", "viewing", "schedule", "demo", "trial", "consultation"]):
            if has_known_contact:
                return f"We have {contact_label} on file{greeting_name}—our team at {biz_name} will finalize that shortly."
            return f"To {goal[0].lower() + goal[1:] if len(goal) > 1 else goal}, share your name along with your phone number or email."

        # 10. Email or phone provided
        if newly_shared_contact:
            return f"Saved your contact info{greeting_name}. Our team at {biz_name} will follow up regarding your inquiry."

        # 11. Frustrated non-KB complaint vs unconfirmed question vs consultative conversational reply
        if behavior["emotion"] == "frustrated":
            if is_blunt:
                return f"Tell me the exact detail you want from {biz_name}, or share your phone/email for direct follow-up."
            return f"I'm sorry for the trouble{greeting_name}. Share your exact question or leave your phone/email for a specialist at {biz_name}."
        question_starters = ("who ", "what ", "when ", "where ", "why ", "how ", "do you", "can you", "is there", "are you", "does ")
        if "?" in last_user_msg or last_user_msg.startswith(question_starters):
            if has_known_contact:
                return f"I don't have that exact detail handy right here{greeting_name}, though our team at {biz_name} has your details and can confirm it directly."
            if is_blunt:
                return f"I don't have that exact detail handy — tell me what specifically you need or share your phone/email so our team can confirm."
            return f"I don't have those exact details handy right here — could you share what specifically you're looking for, or leave your name and email/phone so {biz_name} can confirm directly?"
        if len(query_tokens) >= 2 and not is_blunt:
            if has_known_contact:
                return f"Thanks for sharing that{greeting_name} — what specific requirements, features, or timeline do you have in mind so our team at {biz_name} can point you in the right direction?"
            return f"Thanks for sharing that{greeting_name} — what specific requirements or timeline do you have in mind so {biz_name} can help best?"
        if is_blunt:
            return f"Got it{greeting_name}.{goal_hook() or f' Tell me specifically what you want from {biz_name}.'}"
        return f"Got it{greeting_name} — what specifically would you like to explore with {biz_name} today?"

    _PROJECT_SCOPING_SPECS = (
        (
            ("shopify", "woocommerce", "magento", "ecommerce", "e-commerce", "online store", "online shop", "storefront", "store"),
            ("shopify", "ecommerce", "e-commerce", "store", "full-stack", "web", "next.js", "react", "ui/ux", "design", "mobile"),
            lambda msg: "a Shopify store" if "shopify" in msg else ("a WooCommerce store" if "woocommerce" in msg else "an online store"),
            "what products you're planning to sell, whether you need custom design or payment/shipping integrations",
        ),
        (
            ("chatbot", "ai bot", "ai agent", "voice bot", "voice agent", "llm", "rag", "automation", "gpt", "gemini"),
            ("ai", "llm", "rag", "chatbot", "agent", "automation", "gemini", "openai", "workflow"),
            lambda msg: "an AI chatbot" if ("chatbot" in msg or "bot" in msg) else "an AI automation solution",
            "what main workflows or channels (like website or WhatsApp) you want it to handle and any CRM/tool integrations you need",
        ),
        (
            ("mobile app", "ios app", "android app", "flutter", "react native", "web app", "website", "saas", "dashboard", "portal", "crm", "erp", "platform", "software", "mvp", "app"),
            ("full-stack", "web", "mobile", "flutter", "react", "next.js", "saas", "ui/ux", "cloud", "aws"),
            lambda msg: (
                "a mobile app" if any(k in msg for k in ("mobile app", "ios app", "android app", "flutter", "react native"))
                else ("a SaaS platform" if "saas" in msg or "platform" in msg
                else ("a CRM or portal" if any(k in msg for k in ("crm", "erp", "portal", "dashboard"))
                else "a custom website or app"))
            ),
            "the core features or user flow you have in mind and your target platforms",
        ),
    )

    _NEXT_STEP_PHRASES = {
        "next step", "now next step", "what next", "whats next", "what is next",
        "now what", "and then", "after that", "whats the next step",
        "what is the next step", "how do i start", "how to start",
        "where to start", "next", "next phase", "next steps", "what now",
    }

    @staticmethod
    def _build_contextual_guidance_reply(
        last_user_msg: str,
        history: Optional[List[Dict[str, str]]],
        biz_name: str,
        greeting_name: str,
        is_blunt: bool,
        behavior: Dict[str, str],
    ) -> Optional[str]:
        """Handle low-pressure roadmap requests and context-aware 'next step' follow-ups without derailing."""
        import re

        if behavior.get("emotion") in ("frustrated", "price_hesitant", "skeptical"):
            return None

        clean_follow = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", last_user_msg)).strip()
        is_roadmap_req = any(
            p in last_user_msg
            for p in (
                "roadmap", "road map", "how to build", "how do i build",
                "steps to build", "steps to create", "how to make", "how to create",
            )
        )
        is_next_step = clean_follow in ChatClient._NEXT_STEP_PHRASES

        if not is_roadmap_req and not is_next_step:
            return None

        prior_text = " ".join(
            (m.get("content") or "").lower()
            for m in (history or [])[:-1][-6:]
        )
        topic_text = f"{prior_text} {last_user_msg}"

        if is_roadmap_req:
            if any(k in topic_text for k in ("chatbot", "chat bot", "ai bot", "llm", "rag")):
                if is_blunt:
                    return "Step 1: gather clean FAQs/docs. Step 2: index embeddings + system prompt. Step 3: test accuracy and deploy via API/widget. Which step do you need next?"
                return (
                    f"No problem{greeting_name}—here is a clean roadmap to build an AI chatbot: start by defining the main questions/use cases and organizing clean docs, "
                    "then wire your LLM with retrieval (RAG) and clear guardrails, and finally test edge cases before embedding the widget. Which step would you like to dig into?"
                )
            if any(k in topic_text for k in ("shopify", "ecommerce", "e-commerce", "online store", "store")):
                return (
                    f"Sure{greeting_name}—to build an online store, start by finalizing your catalog and brand layout, then configure theme/custom features plus payment and shipping integrations, "
                    "and test checkout end-to-end before launch. Which stage are you currently focused on?"
                )
            return (
                f"Of course{greeting_name}—a practical build roadmap starts with locking down core user goals and key features, designing the core flow/architecture, "
                "building and testing incrementally, and rolling out live with monitoring. Which stage would you like to explore next?"
            )

        # Contextual "next step" follow-up based on what was just discussed
        if any(k in prior_text for k in ("chatbot", "chat bot", "rag", "vector", "embedding", "prompt optimization", "api deployment", "llm")):
            if any(k in prior_text for k in ("api deployment", "deployment", "vector", "rag", "orchestration")):
                return (
                    f"Once the pipeline and API are built{greeting_name}, the immediate next step is testing with real user questions—verifying accuracy, fallback handling, and latency—then embedding the chat widget and tracking live conversations. "
                    "Would you like to go deeper into testing/evaluation or launching the widget?"
                )
            return (
                f"The immediate next step{greeting_name} is listing your top customer questions and gathering clean business docs/FAQs so your retrieval data is solid before wiring the model. "
                "Do you already have that content ready, or want help structuring it?"
            )
        if any(k in prior_text for k in ("shopify", "ecommerce", "e-commerce", "online store", "storefront")):
            return (
                f"Next step{greeting_name} is organizing your product list, deciding between a standard theme or custom design, and picking payment/shipping integrations so the build scope is clear. "
                "Which piece are you tackling first?"
            )
        if any(k in prior_text for k in ("app", "website", "web", "saas", "blockchain", "web3", "software")):
            return (
                f"Next step{greeting_name} is narrowing down your must-have version-one features and target users before locking design and architecture. "
                "Which core workflow do you want to define first?"
            )
        return (
            f"The best next step{greeting_name} depends on where you are starting—tell me the specific goal or stage you're focusing on at {biz_name} and I'll walk you through what comes next."
        )

    def _build_project_scoping_reply(
        self,
        last_user_msg: str,
        kb: str,
        biz_name: str,
        greeting_name: str,
        user_profile: Optional[Dict[str, Any]],
        user_turns: int,
        has_known_contact: bool,
        is_blunt: bool,
        is_formal: bool,
        goal_hook: Any,
        behavior: Dict[str, str],
        has_direct_kb_hit: bool = False,
    ) -> Optional[str]:
        """Build a warm, consultative scoping reply when a visitor states a project, store, or purchase goal."""
        import re

        if behavior.get("emotion") in ("frustrated", "price_hesitant", "skeptical"):
            return None

        goal_triggers = (
            "want to build", "want to create", "want to launch", "want to start",
            "want to make", "want a ", "want an ", "need a ", "need an ",
            "looking to build", "looking to launch", "looking to start",
            "looking to create", "looking to buy", "looking for a ", "looking for an ",
            "planning to build", "planning to launch", "would like to build",
            "build a ", "build me ", "create a ", "launch a ", "develop a ",
            "interested in", "intersted",
        )
        has_explicit_goal = any(t in last_user_msg for t in goal_triggers)

        matched_spec = None
        for triggers, kb_tokens, label_fn, detail_prompt in self._PROJECT_SCOPING_SPECS:
            pat = r"\b(?:" + "|".join(re.escape(t) for t in triggers) + r")\b"
            if re.search(pat, last_user_msg):
                matched_spec = (kb_tokens, label_fn(last_user_msg), detail_prompt)
                break

        # Pure factual questions or exact KB service/product requests without build-project framing use direct KB answers first.
        if (not matched_spec and has_direct_kb_hit) or (
            not has_explicit_goal and (
                not matched_spec or "?" in last_user_msg or last_user_msg.startswith(("do you", "can you", "what ", "how ", "does ", "is "))
            )
        ):
            return None

        has_timeline = bool((user_profile or {}).get("timeline"))
        timeline_q = "" if has_timeline else ", plus your target launch timeline"
        action_verb = "Launching" if "launch" in last_user_msg else "Building"

        if matched_spec:
            kb_tokens, topic_label, detail_prompt = matched_spec
            kb_matches = self._search_kb_lines(kb, list(kb_tokens), limit=1)
            cap_head = ""
            if kb_matches:
                cap_head = kb_matches[0].split(":", 1)[0].strip().lstrip("-*• ") if ":" in kb_matches[0] else ""

            if is_blunt:
                base = f"Let's scope {topic_label}{greeting_name}. Tell me {detail_prompt}{timeline_q}."
                return f"{base}{goal_hook() if not has_known_contact else ''}"

            if is_formal:
                opener = f"I would be delighted to help you plan {topic_label} with {biz_name}{greeting_name}."
            else:
                opener = f"{action_verb} {topic_label} is an exciting step{greeting_name}!"

            if cap_head:
                bridge = f"To help our {cap_head} team scope the right fit for you, could you share {detail_prompt}{timeline_q}?"
            else:
                bridge = f"To guide you properly at {biz_name}, could you share {detail_prompt}{timeline_q}?"
            return f"{opener} {bridge}"

        # Non-tech general goal/interest statement (e.g., "i am intersted", "looking to buy a home")
        if has_explicit_goal:
            if is_blunt:
                return f"Tell me specifically what you need from {biz_name}{greeting_name}{'' if has_timeline else ' and your timeline'}.{goal_hook() if not has_known_contact else ''}"
            if is_formal:
                return f"Thank you for reaching out to {biz_name}{greeting_name}. Could you share your specific requirements{'' if has_timeline else ' and timeline'} so we can advise you accurately?"
            return f"Glad you're looking into this with {biz_name}{greeting_name}! Could you share a bit more about what specifically you're aiming for{'' if has_timeline else ' and your preferred timeline'}?"

        return None
