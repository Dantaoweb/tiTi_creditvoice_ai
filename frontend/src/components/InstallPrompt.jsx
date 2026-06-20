import { useState, useEffect } from "react";
import { Download, X } from "lucide-react";

const DISMISSED_KEY = "cv-install-dismissed-until";
const SNOOZE_DAYS   = 7;

export default function InstallPrompt() {
  const [prompt, setPrompt]   = useState(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    // Already installed — never show
    if (window.matchMedia("(display-mode: standalone)").matches) return;

    // Snoozed — don't show until snooze expires
    const until = localStorage.getItem(DISMISSED_KEY);
    if (until && Date.now() < Number(until)) return;

    const handler = (e) => {
      e.preventDefault();
      setPrompt(e);
      // Delay the banner slightly so it doesn't flash on first load
      setTimeout(() => setVisible(true), 8000);
    };
    window.addEventListener("beforeinstallprompt", handler);
    return () => window.removeEventListener("beforeinstallprompt", handler);
  }, []);

  if (!visible) return null;

  async function handleInstall() {
    if (!prompt) return;
    prompt.prompt();
    const { outcome } = await prompt.userChoice;
    setVisible(false);
    if (outcome === "accepted") {
      localStorage.setItem(DISMISSED_KEY, String(Date.now() + 365 * 86400 * 1000));
    }
  }

  function handleDismiss() {
    setVisible(false);
    localStorage.setItem(
      DISMISSED_KEY,
      String(Date.now() + SNOOZE_DAYS * 86400 * 1000)
    );
  }

  return (
    <div className="install-banner">
      <Download size={16} className="install-banner-icon" />
      <span className="install-banner-text">
        Install CreditVoice on your phone — works offline, no app store needed
      </span>
      <button className="install-banner-btn" onClick={handleInstall}>
        Install
      </button>
      <button className="install-banner-dismiss" onClick={handleDismiss} aria-label="Not now">
        <X size={14} />
      </button>
    </div>
  );
}
