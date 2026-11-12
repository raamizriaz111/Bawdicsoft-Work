/**
 * Universal Client Chat Widget
 * Pure JavaScript embeddable widget. Auto-syncs with backend configuration.
 * Can be embedded into any external website (Shopify, WordPress, Webflow, React, HTML).
 */
(function () {
  // Automatically detect backend API host from the script src itself so it works on any customer domain!
  let scriptOrigin = "";
  if (document.currentScript && document.currentScript.src) {
    try {
      scriptOrigin = new URL(document.currentScript.src).origin;
    } catch (e) {}
  }

  const CONFIG = {
    apiBase: window.CHATBOT_API_BASE || scriptOrigin || "",
    storageKey: "universal_chatbot_session_id",
  };

  function safeStorageGet(key) {
    try {
      return localStorage.getItem(key);
    } catch (e) {
      return null;
    }
  }

  function safeStorageSet(key, val) {
    try {
      localStorage.setItem(key, val);
    } catch (e) {}
  }

  let sessionId = safeStorageGet(CONFIG.storageKey);
  if (!sessionId) {
    sessionId = "session_" + Math.random().toString(36).substring(2, 11) + "_" + Date.now();
    safeStorageSet(CONFIG.storageKey, sessionId);
  }

  let botConfig = {
    agentName: "Assistant",
    businessName: "Company",
    welcomeMessage: "Hello! How can I assist you today?",
    brandColor: "#00a884",
    quickPrompts: []
  };

  // Build DOM Structure
  const launcher = document.createElement("button");
  launcher.className = "chat-widget-launcher";
  launcher.setAttribute("aria-label", "Open Chat");
  launcher.innerHTML = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
    </svg>
  `;

  const container = document.createElement("div");
  container.className = "chat-widget-container";
  container.innerHTML = `
    <div class="chat-widget-header">
      <div class="chat-widget-header-info">
        <div class="chat-widget-avatar" id="cw-avatar">A</div>
        <div class="chat-widget-title-wrap">
          <h4 id="cw-header-title">Assistant</h4>
          <div class="chat-widget-status">
            <span class="chat-widget-status-dot"></span>
            <span>Online</span>
          </div>
        </div>
      </div>
      <div class="chat-widget-actions">
        <button class="chat-widget-btn-icon" id="cw-reset-btn" title="Start new conversation" aria-label="Start new conversation">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="23 4 23 10 17 10"></polyline>
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
          </svg>
        </button>
        <button class="chat-widget-btn-icon" id="cw-close-btn" title="Close chat" aria-label="Close chat">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>
    </div>
    <div class="chat-widget-messages" id="cw-messages"></div>
    <div class="chat-widget-prompts" id="cw-prompts"></div>
    <div class="chat-widget-input-area">
      <input type="text" class="chat-widget-input" id="cw-input" placeholder="Type your message..." autocomplete="off" />
      <button class="chat-widget-send-btn" id="cw-send-btn" title="Send message">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="22" y1="2" x2="11" y2="13"></line>
          <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
        </svg>
      </button>
    </div>
  `;

  document.body.appendChild(launcher);
  document.body.appendChild(container);

  const messagesEl = document.getElementById("cw-messages");
  const promptsEl = document.getElementById("cw-prompts");
  const inputEl = document.getElementById("cw-input");
  const sendBtn = document.getElementById("cw-send-btn");
  const resetBtn = document.getElementById("cw-reset-btn");
  const closeBtn = document.getElementById("cw-close-btn");
  const headerTitle = document.getElementById("cw-header-title");
  const avatarEl = document.getElementById("cw-avatar");
  const headerEl = container.querySelector(".chat-widget-header");

  let isOpen = false;

  function toggleWidget() {
    isOpen = !isOpen;
    if (isOpen) {
      container.classList.add("active");
      launcher.style.transform = "rotate(90deg) scale(0.9)";
      setTimeout(() => inputEl.focus(), 250);
    } else {
      container.classList.remove("active");
      launcher.style.transform = "none";
    }
  }

  launcher.addEventListener("click", toggleWidget);
  closeBtn.addEventListener("click", toggleWidget);

  function formatTime() {
    const now = new Date();
    return now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function appendMessage(role, text, timeStr) {
    const msgDiv = document.createElement("div");
    msgDiv.className = `chat-widget-msg ${role}`;
    msgDiv.innerHTML = `
      <div class="chat-widget-bubble">${escapeHtml(text)}</div>
      <div class="chat-widget-timestamp">${timeStr || formatTime()}</div>
    `;
    messagesEl.appendChild(msgDiv);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function showTypingIndicator() {
    const typing = document.createElement("div");
    typing.className = "chat-widget-typing";
    typing.id = "cw-typing";
    typing.innerHTML = `
      <div class="chat-widget-typing-dot"></div>
      <div class="chat-widget-typing-dot"></div>
      <div class="chat-widget-typing-dot"></div>
    `;
    messagesEl.appendChild(typing);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function hideTypingIndicator() {
    const typing = document.getElementById("cw-typing");
    if (typing) typing.remove();
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.innerText = text || "";
    return div.innerHTML;
  }

  function renderWidgetQuickPrompts(prompts) {
    promptsEl.innerHTML = "";
    if (!prompts || prompts.length === 0) {
      promptsEl.style.display = "none";
      return;
    }
    promptsEl.style.display = "flex";
    prompts.forEach((p) => {
      const pill = document.createElement("button");
      pill.className = "chat-widget-pill";
      pill.textContent = p;
      pill.addEventListener("click", () => {
        inputEl.value = p;
        sendMessage();
      });
      promptsEl.appendChild(pill);
    });
  }

  function getContrastColor(hex) {
    if (!hex) return "#ffffff";
    let c = String(hex).replace("#", "").trim();
    if (c.length === 3) {
      c = c.split("").map((ch) => ch + ch).join("");
    }
    const r = parseInt(c.substr(0, 2), 16) || 0;
    const g = parseInt(c.substr(2, 2), 16) || 0;
    const b = parseInt(c.substr(4, 2), 16) || 0;
    return (r * 299 + g * 587 + b * 114) / 1000 >= 165 ? "#090c13" : "#ffffff";
  }

  // Fetch dynamic config from backend
  async function loadConfig() {
    try {
      const res = await fetch(`${CONFIG.apiBase}/api/config`, {
        headers: { "bypass-tunnel-reminder": "1" }
      });
      if (res.ok) {
        botConfig = await res.json();
        const agent = botConfig.agentName || botConfig.botName || "Assistant";
        const biz = botConfig.businessName || "";
        headerTitle.innerText = biz ? `${agent} at ${biz}` : agent;
        if (avatarEl) avatarEl.innerText = agent.charAt(0).toUpperCase();

        if (botConfig.brandColor) {
          document.documentElement.style.setProperty("--chat-primary", botConfig.brandColor);
          document.documentElement.style.setProperty("--chat-primary-gradient", botConfig.brandColor);
          const contrast = getContrastColor(botConfig.brandColor);
          document.documentElement.style.setProperty("--chat-primary-contrast", contrast);
          launcher.style.background = botConfig.brandColor;
          launcher.style.color = contrast;
          if (headerEl) {
            headerEl.style.background = botConfig.brandColor;
            headerEl.style.color = contrast;
          }
        }

        renderWidgetQuickPrompts(botConfig.quickPrompts || []);
      }
    } catch (e) {
      console.warn("Could not fetch /api/config, using defaults", e);
    }
  }

  // Restore session history or display welcome message
  async function initSession() {
    await loadConfig();
    try {
      const res = await fetch(`${CONFIG.apiBase}/api/session?sessionId=${encodeURIComponent(sessionId)}`, {
        headers: { "bypass-tunnel-reminder": "1" }
      });
      if (res.ok) {
        const data = await res.json();
        if (data.history && data.history.length > 0) {
          data.history.forEach((m) => {
            appendMessage(m.role === "assistant" ? "bot" : "user", m.content);
          });
          return;
        }
      }
    } catch (e) {
      console.warn("Session fetch fallback", e);
    }
    // New visitor: show configured welcome message
    appendMessage("bot", botConfig.welcomeMessage || "Hello! How can I help you today?");
  }

  // Send message handler
  async function sendMessage() {
    const text = inputEl.value.trim();
    if (!text) return;

    appendMessage("user", text);
    inputEl.value = "";
    inputEl.disabled = true;
    sendBtn.disabled = true;
    showTypingIndicator();

    try {
      const res = await fetch(`${CONFIG.apiBase}/api/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "bypass-tunnel-reminder": "1"
        },
        body: JSON.stringify({
          sessionId: sessionId,
          message: text,
        }),
      });

      hideTypingIndicator();
      if (!res.ok) throw new Error("Chat request failed");

      const data = await res.json();
      appendMessage("bot", data.reply || "How else can I assist you?");
    } catch (err) {
      hideTypingIndicator();
      appendMessage("bot", "I am having trouble connecting right now. Please try again shortly.");
      console.error("Chat error:", err);
    } finally {
      inputEl.disabled = false;
      sendBtn.disabled = false;
      inputEl.focus();
    }
  }

  if (resetBtn) {
    resetBtn.addEventListener("click", async () => {
      try {
        await fetch(`${CONFIG.apiBase}/api/session/reset`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "bypass-tunnel-reminder": "1"
          },
          body: JSON.stringify({ sessionId: sessionId })
        });
      } catch (e) {}
      sessionId = "session_" + Math.random().toString(36).substring(2, 11) + "_" + Date.now();
      safeStorageSet(CONFIG.storageKey, sessionId);
      messagesEl.innerHTML = "";
      appendMessage("bot", botConfig.welcomeMessage || "Hello! How can I help you today?");
    });
  }

  sendBtn.addEventListener("click", sendMessage);
  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Initialize on load
  initSession();
})();
