import { useState, useEffect, useRef } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { Send, Package, Users, ShoppingCart, Bell } from "lucide-react";
import { useAuth } from "../context/AuthContext";

const FEATURES = [
  { icon: ShoppingCart, text: "Record sales — cash or on credit" },
  { icon: Users,        text: "Track who owes you, receive payments" },
  { icon: Package,      text: "Manage your stock, know when to restock" },
  { icon: Bell,         text: "Send payment reminders on WhatsApp" },
];

const TITI_INTRO =
  "Hi! I'm tiTi 👋\n\nI help small businesses record sales, track customer debts, and manage stock — just by typing or speaking. Try me below.";

export default function Landing() {
  const { isAuthed } = useAuth();
  const navigate = useNavigate();

  const [titiNumber, setTitiNumber] = useState("");
  const [input, setInput]           = useState("");
  const [reply, setReply]           = useState(TITI_INTRO);
  const [busy, setBusy]             = useState(false);
  const inputRef = useRef(null);

  useEffect(() => {
    fetch("/app/api/auth/config")
      .then(r => r.json())
      .then(d => setTitiNumber(d.titi_whatsapp || ""))
      .catch(() => {});
  }, []);

  if (isAuthed) return <Navigate to="/home" replace />;

  const waLink = titiNumber ? `https://wa.me/${titiNumber}?text=${encodeURIComponent("Hello")}` : null;

  async function handleSend(e) {
    e.preventDefault();
    const text = input.trim();
    if (!text) return;
    setBusy(true);
    setReply("…");
    try {
      const res = await fetch("/app/api/chat/demo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const data = await res.json();
      setReply(data.reply || "Something went wrong.");
    } catch {
      setReply("Could not reach tiTi. Check your connection.");
    } finally {
      setBusy(false);
      setInput("");
      inputRef.current?.focus();
    }
  }

  return (
    <div className="landing-shell">

      {/* ── Header ── */}
      <header className="landing-header">
        <div className="landing-brand">
          <div className="sidebar-mark" style={{ width: 36, height: 36, fontSize: 14 }}>CV</div>
          <span className="landing-brand-name">CreditVoice</span>
        </div>
        <div className="landing-header-actions">
          {waLink && (
            <a href={waLink} target="_blank" rel="noopener noreferrer" className="btn btn-whatsapp btn-sm">
              Start on WhatsApp
            </a>
          )}
          <button className="btn btn-primary btn-sm" onClick={() => navigate("/login")}>
            Sign In
          </button>
        </div>
      </header>

      {/* ── Hero ── */}
      <section className="landing-hero">
        <h1 className="landing-h1">Meet tiTi</h1>
        <p className="landing-tagline">
          The AI business assistant that works for you.
          <br />
          Record sales, track debts, and manage stock — in plain language.
        </p>

        <div className="landing-features">
          {FEATURES.map(({ icon: Icon, text }) => (
            <div key={text} className="landing-feature">
              <Icon size={18} className="landing-feature-icon" />
              <span>{text}</span>
            </div>
          ))}
        </div>
      </section>

      {/* ── Demo chat ── */}
      <section className="landing-chat-section">
        <div className="landing-chat-label">Try tiTi — no account needed</div>

        <div className="landing-chat-box">
          {/* tiTi bubble */}
          <div className="landing-titi-row">
            <div className="landing-titi-avatar">Ti</div>
            <div className="landing-titi-bubble">
              {reply.split("\n").map((line, i) =>
                line ? <p key={i} style={{ margin: 0 }}>{line}</p> : <br key={i} />
              )}
            </div>
          </div>

          {/* Input */}
          <form onSubmit={handleSend} className="landing-chat-input-row">
            <input
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder="e.g. Sold 3 bags of rice to Emeka for ₦4,500"
              disabled={busy}
              autoComplete="off"
            />
            <button type="submit" className="btn btn-primary" disabled={busy || !input.trim()}>
              <Send size={15} />
            </button>
          </form>
        </div>

        {/* Bottom CTA */}
        <div className="landing-cta">
          <span className="landing-cta-text">Ready to use tiTi for your business?</span>
          <div className="landing-cta-btns">
            <button className="btn btn-primary" onClick={() => navigate("/login?mode=register")}>
              Create Account
            </button>
            {waLink && (
              <a href={waLink} target="_blank" rel="noopener noreferrer" className="btn btn-whatsapp">
                Start on WhatsApp
              </a>
            )}
          </div>
        </div>
      </section>

    </div>
  );
}
