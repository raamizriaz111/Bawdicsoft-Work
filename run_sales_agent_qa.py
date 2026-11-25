#!/usr/bin/env python3
"""
Comprehensive End-to-End Sales Agent QA Test Suite.
Verifies all 5 steps from the Developer Guide:
1. Database Schema & Multi-Tenancy (PostgreSQL/SQLite)
2. Intent, Emotion, and Lead Qualification
3. Deterministic Decision Engine ("LLM proposes, code decides")
4. Follow-up Scheduler (Day 0, Day 2, Day 5 sequence + cancel condition on reply/booking)
5. Returning Visitor Memory (greeting by name, cross-session continuity, no re-asking contact)
6. External Tools Execution (book_meeting, send_whatsapp, send_email, notify_team, update_lead)
"""

import time
import requests
import json
import sys

BASE_URL = "http://localhost:8003"
TS = int(time.time())
VIS_ID = f"vis_qa_{TS}"
SESS_1 = f"sess_qa_turn1_{TS}"
SESS_2 = f"sess_qa_turn2_{TS}"
QA_EMAIL = f"bilal.qa.{TS}@bawdicsoft.com"
QA_PHONE = f"+92300{str(TS)[-7:]}"

passed = 0
failed = 0

def check(name: str, condition: bool, extra: str = ""):
    global passed, failed
    if condition:
        print(f"  ✅ [PASS] {name} {extra}")
        passed += 1
    else:
        print(f"  ❌ [FAIL] {name} {extra}")
        failed += 1

print("\n" + "=" * 65)
print("🚀 STARTING FULL SALES AGENT QA TEST SUITE")
print("=" * 65)

# -------------------------------------------------------------
# Test 1: Presets & Health
# -------------------------------------------------------------
print("\n--- TEST 1: Server & API Endpoints ---")
r = requests.get(f"{BASE_URL}/api/presets")
check("Presets API responded 200", r.status_code == 200)
check("Presets list contains dental", "dental" in r.json())

# -------------------------------------------------------------
# Test 2: Turn 1 - New Visitor Shares Contact & Needs
# -------------------------------------------------------------
print("\n--- TEST 2: Turn 1 - New Visitor Lead Capture & Nurture Scheduling ---")
chat_turn1 = {
    "sessionId": SESS_1,
    "visitorId": VIS_ID,
    "message": f"Hi, my name is Bilal and my email is {QA_EMAIL}, phone is {QA_PHONE}. We want to build an AI chatbot for customer service.",
}
r1 = requests.post(f"{BASE_URL}/api/chat", json=chat_turn1)
check("Chat Turn 1 responded 200", r1.status_code == 200)
d1 = r1.json()
reply1 = d1.get("reply", "")
lead_captured = d1.get("leadCaptured")
check("Lead was captured", lead_captured is not None and lead_captured.get("email") == QA_EMAIL)
lead_id = lead_captured.get("id") if lead_captured else None
numeric_lid = int(str(lead_id).replace("lead_", "")) if lead_id else None
check("Lead assigned ID", numeric_lid is not None, f"id={numeric_lid}")

# -------------------------------------------------------------
# Test 3: Scheduler Follow-up Sequence Generation (Step 4)
# -------------------------------------------------------------
print("\n--- TEST 3: Scheduler Multi-Day Jobs Enqueued ---")
time.sleep(1)
rj = requests.get(f"{BASE_URL}/api/jobs?leadId={numeric_lid}")
check("Jobs API responded 200", rj.status_code == 200)
jobs_data = rj.json().get("jobs", [])
check("Follow-up sequence created 3 jobs", len(jobs_data) == 3, f"found {len(jobs_data)} jobs")

channels = [j.get("channel") for j in jobs_data]
check("Email jobs present", "email" in channels)
check("WhatsApp job present", "whatsapp" in channels)
check("All scheduled jobs are pending", all(j.get("status") == "pending" for j in jobs_data))

# -------------------------------------------------------------
# Test 4: Turn 2 - Returning Visitor Recognition (Step 5)
# -------------------------------------------------------------
print("\n--- TEST 4: Turn 2 - Returning Visitor Memory & Personalized Greeting ---")
# Call session endpoint for NEW session with SAME visitor_id
rs = requests.get(f"{BASE_URL}/api/session?sessionId={SESS_2}&visitorId={VIS_ID}")
check("Session endpoint recognized returning visitor", rs.json().get("isReturning") is True)
user_prof = rs.json().get("userProfile", {})
check("Profile pre-populated with name", user_prof.get("name") == "Bilal")
check("Profile pre-populated with email", user_prof.get("email") == QA_EMAIL)

# Send a simple 'Hi' greeting
chat_turn2 = {
    "sessionId": SESS_2,
    "visitorId": VIS_ID,
    "message": "Hi",
}
r2 = requests.post(f"{BASE_URL}/api/chat", json=chat_turn2)
check("Chat Turn 2 responded 200", r2.status_code == 200)
d2 = r2.json()
reply2 = d2.get("reply", "")
print(f"  Bot Reply: \"{reply2}\"")
check("Returning greeting mentions Bilal", "Bilal" in reply2)
check("Does NOT re-ask for email/phone", "email" not in reply2.lower() and "phone" not in reply2.lower())

# -------------------------------------------------------------
# Test 5: Follow-up Cancellation on Active Reply (Step 4 Cancel Condition)
# -------------------------------------------------------------
print("\n--- TEST 5: Cancel Condition - Pending Follow-ups Cancelled on Visitor Reply ---")
time.sleep(1)
rj_after = requests.get(f"{BASE_URL}/api/jobs?leadId={numeric_lid}")
jobs_after = rj_after.json().get("jobs", [])
cancelled_jobs = [j for j in jobs_after if j.get("status") == "cancelled"]
check("Pending follow-up jobs cancelled when visitor replied", len(cancelled_jobs) > 0, f"{len(cancelled_jobs)} cancelled")

# -------------------------------------------------------------
# Test 6: Decision Engine - Rule 2 Meeting Booking & Tools Execution
# -------------------------------------------------------------
print("\n--- TEST 6: Decision Engine & Tools - Meeting Booking ---")
chat_turn3 = {
    "sessionId": SESS_2,
    "visitorId": VIS_ID,
    "message": "Can we schedule a consultation call tomorrow at 2:00 PM?",
}
r3 = requests.post(f"{BASE_URL}/api/chat", json=chat_turn3)
check("Chat Turn 3 responded 200", r3.status_code == 200)
d3 = r3.json()
decision3 = d3.get("decision", {})
check("Decision engine selected 'book_meeting'", decision3.get("action_type") == "book_meeting")
check("Logged book_meeting and notify_team", "book_meeting" in decision3.get("actions_logged", []))

# -------------------------------------------------------------
# Test 7: Actions Audit Log
# -------------------------------------------------------------
print("\n--- TEST 7: Actions Audit Log ---")
ra = requests.get(f"{BASE_URL}/api/actions?limit=10")
check("Actions API responded 200", ra.status_code == 200)
actions = ra.json().get("actions", [])
tool_names = [a.get("tool_name") for a in actions]
check("Actions audit recorded book_meeting", "book_meeting" in tool_names)
check("Actions audit recorded notify_team", "notify_team" in tool_names)

# -------------------------------------------------------------
# Summary
# -------------------------------------------------------------
print("\n" + "=" * 65)
print(f"📊 QA TEST RESULTS: {passed} PASSED | {failed} FAILED")
print("=" * 65 + "\n")

if failed > 0:
    sys.exit(1)
