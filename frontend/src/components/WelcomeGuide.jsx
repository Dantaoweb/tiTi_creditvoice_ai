import { useState } from "react";
import { Menu, MessageSquare, PlusCircle, LayoutGrid, X } from "lucide-react";

const SEEN_KEY = "cv_welcome_seen";

/**
 * First-time guide. Shows once per device right after a new user lands in the
 * app, so they know the ☰ menu (top-left) and how to start recording — the bits
 * that are easy to miss when the keyboard/first screen scrolls into view.
 * Dismissing it remembers the choice and scrolls back to the top so the header
 * (and its menu button) is in view.
 */
export default function WelcomeGuide() {
  const [open, setOpen] = useState(() => localStorage.getItem(SEEN_KEY) !== "1");

  if (!open) return null;

  function dismiss() {
    localStorage.setItem(SEEN_KEY, "1");
    setOpen(false);
    // Return to the top so the header + menu button are the first thing they see.
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const steps = [
    {
      icon: Menu,
      title: "Your menu is up top",
      body: "Tap the ☰ menu at the top-left any time to reach every feature — customers, stock, dashboard, reminders and more.",
    },
    {
      icon: MessageSquare,
      title: "Just talk to tiTi",
      body: "On the Chat screen, type what happened in your own words — “Ada bought 2 bags rice 3000” — and tiTi records it for you.",
    },
    {
      icon: PlusCircle,
      title: "Or use Quick Record",
      body: "Prefer buttons? Use Quick Record to log a sale, credit or payment step by step.",
    },
    {
      icon: LayoutGrid,
      title: "Shortcuts at the bottom",
      body: "On your phone, the bar at the bottom jumps you straight to tiTi, records, customers and more.",
    },
  ];

  return (
    <div className="modal-overlay welcome-overlay" onClick={dismiss}>
      <div className="modal welcome-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Welcome to CreditVoice">
        <button className="welcome-close" onClick={dismiss} aria-label="Close">
          <X size={18} />
        </button>

        <div className="welcome-head">
          <img src="/app/logo.png" alt="" className="welcome-logo" />
          <h2 className="welcome-title">Welcome to CreditVoice 🎉</h2>
          <p className="welcome-sub">A quick tour — takes 20 seconds.</p>
        </div>

        <div className="welcome-steps">
          {steps.map((s) => (
            <div key={s.title} className="welcome-step">
              <div className="welcome-step-icon"><s.icon size={18} /></div>
              <div>
                <div className="welcome-step-title">{s.title}</div>
                <div className="welcome-step-body">{s.body}</div>
              </div>
            </div>
          ))}
        </div>

        <button className="btn btn-primary welcome-cta" onClick={dismiss}>
          Got it — let's go
        </button>
      </div>
    </div>
  );
}
