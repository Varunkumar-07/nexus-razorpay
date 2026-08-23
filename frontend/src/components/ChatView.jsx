import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { chatHistoryRaw, chatMessage, chatStart, getSessionId, setSessionId } from "../api";

// Mirrors the old static UI's renderAgentReply() status-card detection —
// same regex rules, same status kinds, just producing data instead of
// mutating the DOM directly.
function detectStatus(text) {
  const orderMatch = text.match(/Order placed\. Order ID (\S+)\.?/);
  if (orderMatch) {
    return { kind: "success", label: `Order confirmed — Order ID ${orderMatch[1]}` };
  }
  if (/order cancelled/i.test(text)) {
    return { kind: "cancelled", label: "Order cancelled" };
  }
  if (/exceeds Rs\.[\d,.]+ auto-approval limit|can't place that order|went wrong placing the order/i.test(text)) {
    return { kind: "rejected", label: "Order not placed — see message above" };
  }
  if (/Confirm order for Rs\./.test(text)) {
    return { kind: "confirm-prompt", label: "Awaiting your confirmation (yes/no)" };
  }
  if (/Confirm both items for Rs\./.test(text)) {
    return {
      kind: "confirm-prompt",
      label: "Awaiting your confirmation (yes / primary only / no)",
    };
  }
  return null;
}

export default function ChatView() {
  const location = useLocation();
  const [messages, setMessages] = useState([]); // {role, text, action}
  // Lazy initializer runs once, on this ChatView instance's first render —
  // exactly when navigating here from "Ask about this" on the Catalog
  // page. Pure UI convenience: pre-fills the input, never auto-sends. The
  // buyer still has to click Send/press Enter, at which point this is just
  // a normal chat message like any other — no special handling downstream.
  const [input, setInput] = useState(() => location.state?.prefillMessage ?? "");
  const [sending, setSending] = useState(false);
  const [sessionId, setSessionIdState] = useState(null);
  const bottomRef = useRef(null);
  const inputRef = useRef(null);
  const initStarted = useRef(false);
  const navigate = useNavigate();

  useEffect(() => {
    // Guard against React StrictMode's dev-only double-invoke of effects —
    // without this, mount would fire two POST /chat/start calls (a race on
    // the not-yet-written cookie) and leave one orphaned session server-side.
    //
    // This must be the ONLY guard here. An earlier version combined this
    // ref with a `cancelled` flag set in a cleanup function — but
    // StrictMode still invokes that cleanup for the first (real) effect
    // run as part of its synthetic unmount/remount, which flipped
    // `cancelled` to true while the first run's async init() was still
    // in flight. Since initStarted.current made the second invocation a
    // no-op (no new cleanup registered), the first run's own
    // `if (!cancelled) setSessionIdState(sid)` was permanently skipped —
    // sessionId state stayed null forever, so handleSend()'s
    // `if (!sessionId) return` silently no-opped on every click/Enter,
    // with zero network calls. See FAILURE_LOG.md Entry 4.
    if (initStarted.current) return;
    initStarted.current = true;

    async function init() {
      let sid = getSessionId();
      if (!sid) {
        const data = await chatStart();
        sid = data.session_id;
        setSessionId(sid);
      } else {
        // Confirm the session still exists server-side (e.g. the backend
        // may have restarted since the cookie was set); start fresh if not.
        const resp = await chatHistoryRaw(sid);
        if (!resp.ok) {
          const data = await chatStart();
          sid = data.session_id;
          setSessionId(sid);
        } else {
          const history = await resp.json();
          setMessages(history);
        }
      }
      setSessionIdState(sid);
    }

    init();
  }, []);

  // If we arrived here with a pre-filled message (from "Ask about this"),
  // focus the input so the buyer can immediately see/edit/send it.
  useEffect(() => {
    if (location.state?.prefillMessage) {
      inputRef.current?.focus();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend() {
    const text = input.trim();
    if (!text || !sessionId || sending) return;

    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    setSending(true);

    try {
      const data = await chatMessage(sessionId, text);
      setMessages((prev) => [...prev, { role: "agent", text: data.reply, action: data.suggested_action }]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "agent", text: "Something went wrong talking to NEXUS.", action: null },
      ]);
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Enter") handleSend();
  }

  return (
    <>
      <main className="messages">
        {messages.map((m, i) =>
          m.role === "user" ? (
            <div className="bubble user" key={i}>
              {m.text}
            </div>
          ) : (
            <AgentTurn key={i} text={m.text} action={m.action} onBrowse={() => navigate("/products")} />
          )
        )}
        <div ref={bottomRef} />
      </main>

      <footer className="composer">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="e.g. I need a good sleeping bag for winter camping, budget around Rs.3000."
          autoComplete="off"
          disabled={sending}
        />
        <button onClick={handleSend} disabled={sending}>
          Send
        </button>
      </footer>
    </>
  );
}

function AgentTurn({ text, action, onBrowse }) {
  const status = detectStatus(text);
  return (
    <>
      <div className="bubble agent">{text}</div>
      {status && <div className={`status-card ${status.kind}`}>{status.label}</div>}
      {action === "browse_catalog" && (
        <button className="browse-catalog-btn" onClick={onBrowse}>
          Browse Catalog →
        </button>
      )}
    </>
  );
}
