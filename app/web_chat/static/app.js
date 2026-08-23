const COOKIE_NAME = "nexus_session_id";

function getCookie(name) {
  const match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
  return match ? match[2] : null;
}

function setCookie(name, value) {
  document.cookie = `${name}=${value}; path=/; max-age=${60 * 60 * 24 * 7}`;
}

const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("send");

let sessionId = getCookie(COOKIE_NAME);

function addBubble(role, text) {
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}`;
  bubble.textContent = text;
  messagesEl.appendChild(bubble);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function addStatusCard(kind, text) {
  const card = document.createElement("div");
  card.className = `status-card ${kind}`;
  card.textContent = text;
  messagesEl.appendChild(card);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function renderAgentReply(text) {
  addBubble("agent", text);

  const orderMatch = text.match(/Order placed\. Order ID (\S+)\.?/);
  if (orderMatch) {
    addStatusCard("success", `Order confirmed — Order ID ${orderMatch[1]}`);
    return;
  }
  if (/order cancelled/i.test(text)) {
    addStatusCard("cancelled", "Order cancelled");
    return;
  }
  if (/exceeds Rs\.[\d,.]+ auto-approval limit|can't place that order|went wrong placing the order/i.test(text)) {
    addStatusCard("rejected", "Order not placed — see message above");
    return;
  }
  if (/Confirm order for Rs\./.test(text)) {
    addStatusCard("confirm-prompt", "Awaiting your confirmation (yes/no)");
  }
}

async function startSession() {
  const resp = await fetch("/chat/start", { method: "POST" });
  const data = await resp.json();
  sessionId = data.session_id;
  setCookie(COOKIE_NAME, sessionId);
}

async function loadHistory() {
  const resp = await fetch(`/chat/history/${sessionId}`);
  if (!resp.ok) {
    // Unknown/stale session (e.g. server restarted) — start fresh.
    await startSession();
    return;
  }
  const history = await resp.json();
  messagesEl.innerHTML = "";
  for (const entry of history) {
    if (entry.role === "agent") {
      renderAgentReply(entry.text);
    } else {
      addBubble("user", entry.text);
    }
  }
}

async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text) return;

  addBubble("user", text);
  inputEl.value = "";
  sendBtn.disabled = true;

  try {
    const resp = await fetch("/chat/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: text }),
    });
    if (!resp.ok) {
      addStatusCard("rejected", "Session expired — refresh the page to start a new one.");
      return;
    }
    const data = await resp.json();
    renderAgentReply(data.reply);
  } catch (err) {
    addStatusCard("rejected", "Something went wrong talking to NEXUS.");
  } finally {
    sendBtn.disabled = false;
    inputEl.focus();
  }
}

sendBtn.addEventListener("click", sendMessage);
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});

(async function init() {
  if (!sessionId) {
    await startSession();
  } else {
    await loadHistory();
  }
})();
