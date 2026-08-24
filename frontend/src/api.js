// Thin fetch wrapper around the existing NEXUS FastAPI backend
// (app/agent_api/main.py, including app/web_chat/routes.py and
// app/web_chat/catalog_routes.py). This frontend is a genuinely separate
// app — a different origin, different dev server — talking to the same
// unmodified backend endpoints over CORS.

const API_BASE_URL = "http://127.0.0.1:8000";
const COOKIE_NAME = "nexus_session_id";

// Same cookie-based session_id approach the old static UI used: the
// backend itself has no cookie logic at all — session_id is just a normal
// request field/path param. The cookie only persists it in the browser
// across page reloads, and works identically regardless of which origin
// serves this page.
export function getCookie(name) {
  const match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
  return match ? match[2] : null;
}

export function setCookie(name, value) {
  document.cookie = `${name}=${value}; path=/; max-age=${60 * 60 * 24 * 7}`;
}

export function getSessionId() {
  return getCookie(COOKIE_NAME);
}

export function setSessionId(id) {
  setCookie(COOKIE_NAME, id);
}

async function postJson(path, body) {
  const resp = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    throw new Error(`${path} failed: ${resp.status}`);
  }
  return resp.json();
}

export async function chatStart() {
  return postJson("/chat/start", {});
}

export async function chatMessage(sessionId, message) {
  return postJson("/chat/message", { session_id: sessionId, message });
}

// Returns the raw Response (not parsed) so callers can distinguish
// "unknown session" (404 — start a fresh one) from other failures.
export async function chatHistoryRaw(sessionId) {
  return fetch(`${API_BASE_URL}/chat/history/${sessionId}`);
}

export async function catalogAll() {
  const resp = await fetch(`${API_BASE_URL}/catalog/all`);
  if (!resp.ok) {
    throw new Error(`/catalog/all failed: ${resp.status}`);
  }
  return resp.json();
}

export async function metricsSummary() {
  const resp = await fetch(`${API_BASE_URL}/metrics/summary`);
  if (!resp.ok) {
    throw new Error(`/metrics/summary failed: ${resp.status}`);
  }
  return resp.json();
}
