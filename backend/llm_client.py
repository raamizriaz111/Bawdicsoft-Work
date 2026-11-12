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
                description="2-5 word Title Case consultative sales tactic used in reply (e.g. 'Value Anchor + Payment Plan')."
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
    )
    _HUMAN_HANDOFF_PHRASES = (
        "talk to a human", "speak to a human", "real human", "real agent",
        "speak with someone", "talk to someone", "customer support",
        "speak to a manager", "call me", "human support", "representative",
    )
    _GREETING_EXACT = {
        "hi", "hello", "hey", "hi there", "hello there", "good morning",
        "good afternoon", "good evening", "assalam o alaikum", "salam", "how are you",
    }
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

        rules = [
            ("neutral", "off_topic", "Polite Business Pivot",
             ("weather", "capital of", "president", "write a python", "write python", "write code", "binary search", "linked list", "write javascript", "code for me", "debug my", "joke", "poem", "recipe", "cricket score", "football", "world cup", "who won", "2+2", "solve ")),
            ("neutral", "cold", "Graceful Exit + Door Open", ChatClient._OPTOUT_PHRASES),
            ("neutral", "warm", "Human Handoff Offer", ChatClient._HUMAN_HANDOFF_PHRASES),
            ("neutral", "cold", "Transparent AI Introduction", ChatClient._BOT_IDENTITY_PHRASES),
            ("neutral", "cold", "Warm Hospitality",
             ("hi there", "hello there", "good morning", "good afternoon", "good evening", "how are you", "hello,")),
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
        return {
            "emotion": "neutral",
            "buyer_intent": "warm" if has_contact else "cold",
            "sales_tactic": "Warm Hospitality" if len(last_msg) <= 25 else "Friendly Qualification",
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

        timeline = profile.get("timeline")
        for marker in ("today", "tomorrow", "this week", "next week", "this month", "next month", "asap", "immediately", "urgent"):
            if marker in low:
                timeline = marker
                break

        objection = profile.get("objection_reason")
        if behavior["emotion"] in ("price_hesitant", "skeptical"):
            objection = behavior["emotion"]

        preferred_slot = profile.get("preferred_slot")
        slot_match = re.search(
            r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|today|weekend)(?:\s+(?:at\s+)?(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)|morning|afternoon|evening))?\b|\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
            raw_last_msg or "",
            re.IGNORECASE,
        )
        if slot_match:
            preferred_slot = slot_match.group(0).strip()

        intent = behavior["buyer_intent"]
        if has_contact:
            sales_stage = "post_capture"
        elif intent == "hot":
            sales_stage = "closing"
        elif behavior["emotion"] in ("price_hesitant", "skeptical", "frustrated"):
            sales_stage = "objection_handling"
        elif behavior["emotion"] == "confused":
            sales_stage = "recommendation"
        elif len(low) <= 18 and intent == "cold":
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
        if not need and intent != "off_topic" and behavior.get("sales_tactic") != "Graceful Exit + Door Open":
            stripped_need = re.sub(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", "", raw_last_msg or "", flags=re.IGNORECASE)
            stripped_need = re.sub(r"\+?\d[\d\s\-().]{6,}\d", "", stripped_need).strip(" ,.-:")
            clean_ack_need = re.sub(r"[^a-z\s]", "", stripped_need.lower()).strip()
            if (
                len(stripped_need) > 6
                and clean_ack_need not in ChatClient._GREETING_EXACT
                and clean_ack_need not in ChatClient._ACK_EXACT
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
                "gemini-3.5-flash-lite",
                "gemini-3.1-flash-lite",
            ]
            unique_models = []
            for m in models_to_try:
                if m and m not in unique_models:
                    unique_models.append(m)

            # Enforce a hard 18.0s total failover budget so visitors never stall indefinitely
            deadline = time.monotonic() + 18.0
            for model_to_call in unique_models[:2]:
                remaining = deadline - time.monotonic()
                if remaining < 1.5:
                    break
                executor = None
                per_model_cap = 9.0 if "3.5" in model_to_call else 10.0
                model_timeout = round(min(per_model_cap, remaining), 2)
                try:
                    def _call_model():
                        cfg_kwargs = {
                            "system_instruction": system_instruction,
                            "temperature": 0.45,
                            "max_output_tokens": 620,
                            "response_mime_type": "application/json",
                            "response_schema": analysis_schema,
                        }
                        if "3.1" in model_to_call:
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
                        parsed_result["source"] = model_to_call
                        return parsed_result
                except concurrent.futures.TimeoutError:
                    if executor is not None:
                        executor.shutdown(wait=False, cancel_futures=True)
                    print(f"[ChatClient] Model {model_to_call} timed out after {model_timeout}s. Fast-switching to next model...")
                    continue
                except Exception as e:
                    if executor is not None:
                        executor.shutdown(wait=False, cancel_futures=True)
                    print(f"[ChatClient] Model {model_to_call} error: {e}. Fast-switching to next model...")
                    continue

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
        return parsed

    @staticmethod
    def _format_kb_prose(lines: List[str]) -> str:
        """Convert raw KB bullet lines into clean, conversational sentences."""
        cleaned = []
        for raw in lines:
            s = re.sub(r"^\s*[-*•#]+\s*", "", raw or "").strip()
            if not s:
                continue
            if ":" in s and not s.lower().startswith(("http://", "https://")):
                head, tail = s.split(":", 1)
                tail = tail.strip()
                if tail and len(head.strip()) <= 36:
                    s = f"{head.strip()} — {tail}"
            if s and s[-1] not in ".!?":
                s += "."
            cleaned.append(s)
        return " ".join(cleaned)

    @staticmethod
    def _search_kb_lines(
        kb: str,
        keywords: List[str],
        limit: int = 2,
        whole_word: bool = False,
    ) -> List[str]:
        """Return the highest-overlap KB detail lines, prioritizing topic-heading matches."""
        import re

        if not kb or not keywords:
            return []

        def _count_hits(text: str) -> int:
            if whole_word:
                return sum(1 for kw in keywords if re.search(r"\b" + re.escape(kw) + r"\b", text))
            return sum(1 for kw in keywords if kw in text)

        scored = []
        for raw_line in kb.splitlines():
            line = raw_line.strip()
            if len(line) < 6 or line.endswith(":"):
                continue
            low = line.lower()
            hits = _count_hits(low)
            if hits > 0:
                head_bonus = 0
                if ":" in low and not low.startswith(("http://", "https://")):
                    head = low.split(":", 1)[0]
                    head_bonus = _count_hits(head) * 4
                # Prefer concrete bullet/detail lines over section headings and reward title matches
                bonus = 0 if line.endswith(":") else 1
                scored.append((hits * 2 + bonus + head_bonus, line))
        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored:
            return []
        best_score = scored[0][0]
        if best_score >= 6:
            # Drop incidental background mentions when a topic heading matched directly
            scored = [item for item in scored if item[0] >= best_score - 1]
        return [line for _, line in scored[:limit]]

    @staticmethod
    def _extract_kb_section(kb: str, section_keywords: tuple, limit: int = 3) -> List[str]:
        """Collect bullet lines under matching KB section headings (e.g., SERVICES or PORTFOLIO)."""
        if not kb:
            return []
        collected: List[str] = []
        in_section = False
        for raw_line in kb.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            low = line.lower()
            if line.endswith(":") and (line[0].isdigit() or line.isupper() or ":" in line):
                in_section = any(kw in low for kw in section_keywords)
                continue
            if in_section:
                collected.append(line)
                if len(collected) >= limit:
                    break
        return collected

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

        # 5. Greeting (works on any turn, not only empty history)
        clean_ack = re.sub(r"[^a-z\s]", "", last_user_msg).strip()
        if clean_ack in self._GREETING_EXACT or clean_ack.startswith(("hi ", "hello ", "hey ", "good morning", "good afternoon", "good evening", "how are you")):
            if is_blunt:
                return f"{agent_name} at {biz_name} here. Tell me what you need so we can {goal[0].lower() + goal[1:] if len(goal) > 1 else goal}."
            if is_energetic:
                return f"Hey{greeting_name}! {agent_name} from {biz_name} here—let's get you set up to {goal[0].lower() + goal[1:] if len(goal) > 1 else goal}!"
            return f"Hello{greeting_name}! I'm {agent_name} at {biz_name}. Let me know what you're looking for so we can {goal[0].lower() + goal[1:] if len(goal) > 1 else goal}."

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
        address_phrases = ("location", "address", "where are you", "where is your", "located")
        wants_hours = any(w in last_user_msg for w in hours_phrases)
        wants_address = any(w in last_user_msg for w in address_phrases)
        if wants_hours or wants_address:
            loc_keywords: List[str] = []
            if wants_address:
                loc_keywords.extend(["address", "headquarters address", "headquarters", "head office", "located", "location"])
            if wants_hours:
                loc_keywords.extend(["working hours", "office hours", "hours", "hour", "mon", "tue", "fri", "sat", "sun", "weekday", "weekend"])
            matches = self._search_kb_lines(kb, loc_keywords, limit=2 if (wants_hours and wants_address) else 1)
            if not matches and wants_address:
                matches = self._search_kb_lines(kb, ["suite", "building", "road", "phase", "clifton", "dha", "karachi"], limit=1)
            if matches:
                prose = self._format_kb_prose(matches)
                suffix = "" if behavior["emotion"] == "frustrated" else goal_hook()
                return f"{prose}{suffix}"
            suffix = "" if behavior["emotion"] == "frustrated" else goal_hook()
            return f"{biz_name} operates during listed business hours; check with us to confirm exact availability.{suffix}"

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
            return f"We do not have listings or services confirmed in {mentioned_missing_city.title()} in our knowledge base.{loc_note}"

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
        }
        if newly_shared_contact and "?" not in last_user_msg:
            return f"Saved your contact info{greeting_name}. Our team at {biz_name} will follow up regarding your inquiry."
        user_turns = sum(1 for m in (history or []) if m.get("role") == "user")
        wants_booking = any(
            w in last_user_msg
            for w in ("book", "appointment", "viewing", "schedule", "demo", "trial", "consultation", "contact", "call", "quote")
        )

        def _finish_kb_reply(prose_text: str) -> str:
            if behavior["emotion"] == "frustrated" or has_known_contact:
                return prose_text
            if user_turns <= 1 and not is_blunt and not wants_booking and behavior["emotion"] not in ("urgent", "excited"):
                return f"{prose_text} Are you exploring a specific project or use case here?"
            return f"{prose_text}{goal_hook()}"

        # Check explicit unconfirmed policy terms absent from KB (e.g., NDA, refunds, SLA)
        for policy_kw in ("nda", "non-disclosure", "refund", "money-back", "warranty", "sla"):
            kw_pat = r"\b" + re.escape(policy_kw) + r"\b"
            if re.search(kw_pat, last_user_msg) and not re.search(kw_pat, kb.lower()):
                return (
                    f"Our knowledge base doesn't specify our {policy_kw.upper() if len(policy_kw) <= 3 else policy_kw} policy directly — "
                    f"our team at {biz_name} can confirm that with you on a quick call.{'' if (has_known_contact or behavior['emotion'] == 'frustrated') else goal_hook()}"
                )

        # Broad Services / Portfolio section summaries
        if re.search(r"\b(?:services?|capabilities|what do you do|what can you build|offerings?)\b", last_user_msg):
            svc_lines = self._extract_kb_section(kb, ("service", "capabilit", "specialt", "program", "product"), limit=3)
            if svc_lines:
                return _finish_kb_reply(self._format_kb_prose(svc_lines))

        if re.search(r"\b(?:portfolio|past work|past projects?|projects? have you|case stud(?:y|ies)|track record)\b", last_user_msg):
            port_lines = self._extract_kb_section(kb, ("portfolio", "case stud", "track record", "featured"), limit=3)
            if port_lines:
                return _finish_kb_reply(self._format_kb_prose(port_lines))

        sanitized_msg = re.sub(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9-.]+", " ", last_user_msg)
        query_tokens = [t for t in re.findall(r"[a-z0-9]{2,}", sanitized_msg) if t not in stop_words]
        kb_hits = self._search_kb_lines(kb, query_tokens, limit=2, whole_word=True)
        if kb_hits:
            return _finish_kb_reply(self._format_kb_prose(kb_hits))

        # 9. Booking / Trial / Viewing / Contact -> Lead Capture (never re-ask contact if known)
        if not newly_shared_contact and any(w in last_user_msg for w in ["book", "appointment", "viewing", "schedule", "demo", "trial", "visit", "consultation", "contact"]):
            if has_known_contact:
                return f"We have {contact_label} on file{greeting_name}—our team at {biz_name} will finalize that shortly."
            return f"To {goal[0].lower() + goal[1:] if len(goal) > 1 else goal}, share your name along with your phone number or email."

        # 10. Email or phone provided
        if newly_shared_contact:
            return f"Saved your contact info{greeting_name}. Our team at {biz_name} will follow up regarding your inquiry."

        # 11. Frustrated non-KB complaint vs unconfirmed question vs conversational reply
        if behavior["emotion"] == "frustrated":
            if is_blunt:
                return f"Tell me the exact detail you want from {biz_name}, or share your phone/email for direct follow-up."
            return f"I'm sorry for the trouble{greeting_name}. Share your exact question or leave your phone/email for a specialist at {biz_name}."
        question_starters = ("who ", "what ", "when ", "where ", "why ", "how ", "do you", "can you", "is there", "are you", "does ")
        if "?" in last_user_msg or last_user_msg.startswith(question_starters):
            return f"That specific detail isn't listed in {biz_name}'s knowledge base.{goal_hook()}"
        return f"Noted{greeting_name}.{goal_hook() or f' How else can {biz_name} help?'}"
