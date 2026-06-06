import { useState, useRef, useEffect } from "react";
import { Send, Mic, MicOff } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { apiPost } from "../lib/api";

const CHIPS = [
  { label: "Record a sale",     text: "Sold " },
  { label: "Customer payment",  text: "Customer paid " },
  { label: "Restock",           text: "Restocked " },
];

const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;

export default function Chat() {
  const { user } = useAuth();
  const [input, setInput]         = useState("");
  const [reply, setReply]         = useState(null);
  const [busy, setBusy]           = useState(false);
  const [ok, setOk]               = useState(null); // true = success, false = error
  const [listening, setListening] = useState(false);
  const inputRef  = useRef(null);
  const replyRef  = useRef(null);

  const firstName = user?.name?.split(" ")[0] || "there";

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    if (reply) replyRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [reply]);

  async function handleSend(e) {
    e?.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setBusy(true);
    setReply(null);
    try {
      const data = await apiPost("chat/send", { text });
      setReply(data.reply || "Done!");
      setOk(data.ok !== false);
      setInput("");
    } catch (err) {
      setReply(err.message || "Something went wrong.");
      setOk(false);
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  }

  function handleChip(text) {
    setInput(text);
    inputRef.current?.focus();
  }

  function handleKey(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function startListening() {
    if (!SpeechRec || listening) return;
    const rec = new SpeechRec();
    rec.lang = "en-NG";
    rec.continuous = false;
    rec.interimResults = false;
    rec.onstart  = () => setListening(true);
    rec.onend    = () => setListening(false);
    rec.onerror  = () => setListening(false);
    rec.onresult = e => {
      const transcript = e.results[0][0].transcript;
      setInput(transcript);
    };
    rec.start();
  }

  return (
    <div className="chat-shell">

      {/* ── Greeting ── */}
      <div className="chat-greeting">
        <div className="chat-titi-avatar">Ti</div>
        <div>
          <div className="chat-greeting-name">Hi {firstName}! 👋</div>
          <div className="chat-greeting-sub">
            What can I record for you today? Type a sale, payment, or restock below.
          </div>
        </div>
      </div>

      {/* ── Quick chips ── */}
      {!reply && (
        <div className="chat-chips">
          {CHIPS.map(c => (
            <button key={c.label} className="chat-chip" onClick={() => handleChip(c.text)}>
              {c.label}
            </button>
          ))}
        </div>
      )}

      {/* ── tiTi reply ── */}
      {reply && (
        <div ref={replyRef} className={`chat-reply ${ok ? "chat-reply-ok" : "chat-reply-err"}`}>
          <div className="chat-titi-avatar chat-titi-avatar-sm">Ti</div>
          <div className="chat-reply-bubble">
            {reply.split("\n").map((line, i) =>
              line ? <p key={i} style={{ margin: 0 }}>{line}</p> : <br key={i} />
            )}
          </div>
        </div>
      )}

      {/* ── Input bar ── */}
      <form onSubmit={handleSend} className="chat-input-bar">
        <input
          ref={inputRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKey}
          placeholder="Type a transaction…"
          disabled={busy}
          autoComplete="off"
        />

        {SpeechRec && (
          <button
            type="button"
            className={`chat-mic-btn ${listening ? "chat-mic-active" : ""}`}
            onClick={startListening}
            disabled={busy}
            title="Speak your transaction"
          >
            {listening ? <MicOff size={18} /> : <Mic size={18} />}
          </button>
        )}

        <button
          type="submit"
          className="btn btn-primary"
          disabled={busy || !input.trim()}
        >
          {busy ? "…" : <Send size={15} />}
        </button>
      </form>

      {reply && (
        <button className="chat-new-btn" onClick={() => { setReply(null); setOk(null); inputRef.current?.focus(); }}>
          + New transaction
        </button>
      )}

    </div>
  );
}
