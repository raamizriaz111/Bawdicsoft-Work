---
title: BawdicSoft AI Agent Studio
emoji: 🤖
colorFrom: cyan
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# 🤖 AI Agent Studio

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI / Starlette](https://img.shields.io/badge/Framework-Starlette%20%2F%20FastAPI-009688.svg)](https://www.starlette.io/)
[![Google Gemini](https://img.shields.io/badge/LLM-Gemini%203.1%20Flash--Lite-4285F4.svg)](https://ai.google.dev/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

An enterprise-grade, white-label AI assistant platform and visual management studio built for agencies, SaaS companies, and modern businesses. 

Configure custom agent personas, knowledge bases, and brand aesthetics in real-time — then embed a responsive chat widget onto any client website in **2 lines of code**.

---

## ✨ Key Features

- **🎨 Visual Agent Studio:** Live 3-column control center to customize bot identity, conversational tone, conversion goals, brand color palette (with automatic YIQ contrast detection), and markdown knowledge base.
- **⚡ Sub-Second Response Latency:** Optimized with Google Gemini 3.1 Flash-Lite, token streaming limits, sliding context window, and thread-pool circuit breakers delivering ultra-fast answers in **0.6s – 0.9s**.
- **🎯 Silent Lead Capture Engine:** Non-intrusive extraction of visitor names, emails, phone numbers, and service interests during natural conversation.
- **📋 Lead Management & Transcripts:** Built-in captured leads drawer, full-session conversation transcript inspection, and 1-click **CSV Export**.
- **🌓 Executive Light & Dark Mode:** Polished Linear/Raycast design language with instant theme toggle and audio feedback micro-interactions.
- **📱 100% Mobile Responsive:** Adaptive segmented mobile navigation (`Chat`, `Settings`, `Leads`) with pinned bottom inputs, `100dvh` viewport handling, and iOS auto-zoom prevention.
- **🔌 Universal 2-Line Embed:** Drop-in compatibility with standard HTML, React / Next.js, WordPress, Webflow, and Shopify.
- **🐳 Cloud & Container Ready:** Includes standard `Dockerfile`, `Procfile`, and `requirements.txt` for 1-click deployment on Render, Railway, Fly.io, or VPS.

---

## 🏗️ Architecture & Project Structure

```
AI-Agent-Studio/
├── backend/
│   ├── app.py               # Starlette ASGI server & REST endpoints
│   ├── llm_client.py        # Gemini 3.1 client with latency breaker & retry engine
│   ├── lead_manager.py      # Regex & context-based lead capture & CSV export
│   ├── prompt_builder.py    # Strict anti-hallucination prompt generator
│   ├── presets.py           # Multi-industry templates (Dental, Real Estate, Legal, SaaS)
│   └── session_manager.py   # Multi-turn visitor memory & session tracking
├── static/
│   ├── index.html           # Agent Studio live workspace interface
│   ├── agent-desk.css       # Studio stylesheet (Dark/Light themes & mobile breakpoints)
│   ├── agent-desk.js        # Real-time studio logic, live color morphing, audio feedback
│   ├── chat-widget.js       # Standalone embeddable client widget script
│   └── chat-widget.css      # Standalone embeddable client widget stylesheet
├── data/
│   └── active_config.json   # Live agent configuration state
├── Dockerfile               # Production container blueprint
├── Procfile                 # Production web process runner
├── requirements.txt         # Pinned Python dependencies
├── .env.example             # Environment configuration template
└── README.md                # Documentation
```

---

## 🚀 Quick Start (Local Setup)

### 1. Clone the Repository
```bash
git clone https://github.com/raamizriaz111/AI-Agent-Studio.git
cd AI-Agent-Studio
```

### 2. Set Up a Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure Your Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Add your Google Gemini API key:
```env
GEMINI_API_KEY=your_actual_gemini_api_key_here
GEMINI_MODEL=gemini-3.1-flash-lite
PORT=8003
```
*(Get a free Gemini API key from [Google AI Studio](https://aistudio.google.com/)).*

### 4. Run the Server
```bash
python3 -m backend.app
```
Open your browser at:
- **Studio Interface:** `http://localhost:8003`
- **Leads API:** `http://localhost:8003/api/leads`
- **Presets API:** `http://localhost:8003/api/presets`

---

## 🔌 Embedding into Client Websites

To add the AI chatbot to any external website, paste these two lines before `</head>` or `</body>`:

### Standard HTML / Webflow / Shopify
```html
<!-- AI Agent Studio Widget -->
<link rel="stylesheet" href="https://your-domain.com/static/chat-widget.css">
<script src="https://your-domain.com/static/chat-widget.js" defer></script>
```

### React / Next.js
```jsx
import Script from 'next/script';

export default function ChatbotWidget() {
  return (
    <>
      <link rel="stylesheet" href="https://your-domain.com/static/chat-widget.css" />
      <Script src="https://your-domain.com/static/chat-widget.js" strategy="lazyOnload" />
    </>
  );
}
```

### WordPress
Paste into your theme's `header.php` or use the **"Insert Headers and Footers"** plugin:
```html
<link rel="stylesheet" href="https://your-domain.com/static/chat-widget.css">
<script src="https://your-domain.com/static/chat-widget.js" defer></script>
```

---

## 📡 REST API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Serves the Agent Studio management interface |
| `GET` | `/api/presets` | Retrieves all pre-built industry templates |
| `GET` | `/api/config` | Retrieves the current active bot configuration |
| `POST` | `/api/config` | Updates agent persona, colors, tone, and knowledge base |
| `POST` | `/api/chat` | Main conversational endpoint with Gemini engine |
| `GET` | `/api/leads` | Lists all captured qualified leads and counts |
| `GET` | `/api/leads/export` | Downloads captured leads as a `.csv` file |
| `POST` | `/api/leads/clear` | Clears lead history |
| `GET` | `/api/session/transcript` | Retrieves full conversation transcript for a session |
| `POST` | `/api/session/reset` | Resets a visitor conversation session |

---

## 🐳 Docker & Cloud Deployment

### Run with Docker Locally
```bash
docker build -t ai-agent-studio .
docker run -p 8003:8003 --env-file .env ai-agent-studio
```

### 1-Click Cloud Deployment (Render / Railway / VPS)
1. Fork or push this repository to your GitHub account.
2. Connect your repo to [Render](https://render.com) or [Railway](https://railway.app).
3. The platform will automatically detect `Dockerfile` or `Procfile` + `requirements.txt`.
4. Add your `GEMINI_API_KEY` under Environment Variables in the cloud dashboard.
5. Deploy!

---

## 🛡️ License

Distributed under the **MIT License**. See `LICENSE` for more information.
# Bawdicsoft-Work
