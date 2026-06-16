import { useState, useEffect } from "react";
import { Download, X } from "lucide-react";

export default function InstallPrompt() {
  const [prompt, setPrompt] = useState(null);
  const [visible, setVisible] = useState(false);
  const [dismissed, setDismissed] = useState(
    () => sessionStorage.getItem("cv-install-dismissed") === "1"
  );

  useEffect(() => {
    if (dismissed) return;
    // Already running in standalone (installed) — don't show
    if (window.matchMedia("(display-mode: standalone)").matches) return;

    const handler = (e) => {
      e.preventDefault();
      setPrompt(e);
      setVisible(true);
    };
    window.addEventListener("beforeinstallprompt", handler);
    return () => window.removeEventListener("beforeinstallprompt", handler);
  }, [dismissed]);

  if (!visible || dismissed) return null;

  async function handleInstall() {
    if (!prompt) return;
    prompt.prompt();
    const { outcome } = await prompt.userChoice;
    if (outcome === "accepted") {
      setVisible(false);
    }
  }

  function handleDismiss() {
    setVisible(false);
    setDismissed(true);
    sessionStorage.setItem("cv-install-dismissed", "1");
  }

  return (
    <div className="install-banner">
      <Download size={16} className="install-banner-icon" />
      <span className="install-banner-text">
        Install CreditVoice on your phone — works offline
      </span>
      <button className="install-banner-btn" onClick={handleInstall}>
        Install
      </button>
      <button className="install-banner-dismiss" onClick={handleDismiss} aria-label="Dismiss">
        <X size={14} />
      </button>
    </div>
  );
}
