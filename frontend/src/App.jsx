import { useEffect, useRef, useState } from "react";

const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

// A new session starts on every page load.
const newSessionId = () =>
  "s-" + Math.random().toString(36).slice(2, 8) + Date.now().toString(36).slice(-4);

function readableError(status, data) {
  if (status === 503) return "Every AI provider is unavailable right now. Wait a moment and send your message again.";
  if (status === 422) {
    const d = data?.detail;
    if (Array.isArray(d)) return "That message can't be sent: " + d.map((e) => e.msg).join("; ");
    return "That message can't be sent" + (typeof d === "string" ? ": " + d : ".");
  }
  if (typeof data?.detail === "string") return data.detail;
  return `The server returned an error (HTTP ${status}). Try again.`;
}

export default function App() {
  const [sessionId, setSessionId] = useState(newSessionId);
  const [items, setItems] = useState([]); // {kind: user|assistant|error, ...}
  const [input, setInput] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [simulate, setSimulate] = useState("");
  const [loading, setLoading] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [items, loading]);

  async function send() {
    if (loading) return;
    const text = input;
    setInput("");
    setItems((prev) => [...prev, { kind: "user", content: text.trim() || "(empty message)" }]);
    setLoading(true);

    const body = { session_id: sessionId, message: text };
    if (systemPrompt.trim()) body.system_prompt = systemPrompt.trim();
    const headers = { "Content-Type": "application/json" };
    if (simulate.trim()) headers["X-Simulate-Failure"] = simulate.trim();

    try {
      const res = await fetch(`${API_URL}/chat`, { method: "POST", headers, body: JSON.stringify(body) });
      let data = null;
      try {
        data = await res.json();
      } catch {
        /* non-JSON body */
      }
      if (res.ok && data?.reply) {
        setItems((prev) => [...prev, { kind: "assistant", content: data.reply, metadata: data.metadata }]);
      } else {
        setItems((prev) => [...prev, { kind: "error", content: readableError(res.status, data) }]);
      }
    } catch {
      setItems((prev) => [
        ...prev,
        { kind: "error", content: "Can't reach the server. Check your connection and try again." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function onKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  function newChat() {
    setSessionId(newSessionId());
    setItems([]);
  }

  return (
    <div className="app">
      <header className="top">
        <div>
          <h1>Resilient Chat</h1>
          <p className="sub">Session {sessionId}</p>
        </div>
        <button className="ghost" onClick={newChat}>New chat</button>
      </header>

      <section className="settings">
        <label>
          System prompt
          <textarea
            data-testid="system-prompt-input"
            rows={2}
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            placeholder="Optional. Overrides the default system prompt for this session."
          />
        </label>
        <label>
          Simulate key failure
          <input
            value={simulate}
            onChange={(e) => setSimulate(e.target.value)}
            placeholder="e.g. key_1=429 or *=429 (sent as X-Simulate-Failure)"
          />
        </label>
      </section>

      <main className="thread">
        {items.length === 0 && (
          <p className="empty">Ask anything. Send the same message in a new chat to see a cache hit.</p>
        )}
        {items.map((m, i) => {
          if (m.kind === "user") {
            return (
              <div key={i} className="row user">
                <div className="bubble">{m.content}</div>
              </div>
            );
          }
          if (m.kind === "error") {
            return (
              <div key={i} className="row">
                <div className="bubble error" role="alert" data-testid="error-message">{m.content}</div>
              </div>
            );
          }
          const md = m.metadata || {};
          return (
            <div key={i} className="row">
              <div className="assistant" data-testid="assistant-message">
                <div className="bubble">{m.content}</div>
                <dl className="meta">
                  <div>
                    <dt>Source</dt>
                    <dd data-testid="meta-source" className={md.resolution_source === "LLM_CACHE" ? "cache" : "live"}>
                      {md.resolution_source}
                    </dd>
                  </div>
                  <div>
                    <dt>Model</dt>
                    <dd data-testid="meta-model">{md.model}</dd>
                  </div>
                  <div>
                    <dt>Latency</dt>
                    <dd data-testid="meta-latency">{md.latency_ms} ms</dd>
                  </div>
                  <div>
                    <dt>Input tokens</dt>
                    <dd data-testid="meta-input-tokens">{md.input_tokens}</dd>
                  </div>
                  <div>
                    <dt>Output tokens</dt>
                    <dd data-testid="meta-output-tokens">{md.output_tokens}</dd>
                  </div>
                  <div>
                    <dt>Key</dt>
                    <dd>{md.key_id ?? "none (cache)"}</dd>
                  </div>
                  <div>
                    <dt>Fallbacks</dt>
                    <dd>{md.fallback_attempts}</dd>
                  </div>
                </dl>
              </div>
            </div>
          );
        })}
        {loading && <p className="typing">Thinking…</p>}
        <div ref={endRef} />
      </main>

      <footer className="composer">
        <textarea
          data-testid="chat-input"
          rows={2}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Type a message. Enter sends, Shift+Enter adds a line."
        />
        <button data-testid="send-button" onClick={send} disabled={loading}>
          Send
        </button>
      </footer>
    </div>
  );
}
