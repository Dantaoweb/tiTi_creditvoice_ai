import { useState, useEffect } from "react";
import { Download, X, Share2 } from "lucide-react";

const DISMISSED_KEY = "cv-install-dismissed-until";
const SNOOZE_DAYS   = 14;

function isIOS() {
  return /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream;
}
function isStandalone() {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true
  );
}

// After sign-in, invites the user to add CreditVoice to their home screen so it
// opens like an app. Android fires a native install prompt; iOS Safari can't, so
// we show the Share → Add to Home Screen steps. A blinking pointer draws the eye.
export default function InstallPrompt() {
  const [deferred, setDeferred] = useState(null);   // Android beforeinstallprompt
  const [visible, setVisible]   = useState(false);
  const [stepsOpen, setStepsOpen] = useState(false);
  const ios = isIOS();

  useEffect(() => {
    if (isStandalone()) return;                       // already installed
    const until = localStorage.getItem(DISMISSED_KEY);
    if (until && Date.now() < Number(until)) return;  // snoozed

    if (ios) {
      const t = setTimeout(() => setVisible(true), 2500);
      return () => clearTimeout(t);
    }
    const onPrompt = (e) => {
      e.preventDefault();
      setDeferred(e);
      setTimeout(() => setVisible(true), 2500);
    };
    const onInstalled = () => {
      setVisible(false);
      localStorage.setItem(DISMISSED_KEY, String(Date.now() + 365 * 86400 * 1000));
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, [ios]);

  if (!visible) return null;

  function snooze() {
    localStorage.setItem(DISMISSED_KEY, String(Date.now() + SNOOZE_DAYS * 86400 * 1000));
  }
  function dismiss() { setVisible(false); snooze(); }

  async function handleAction() {
    if (ios) { setStepsOpen((o) => !o); return; }
    if (!deferred) return;
    deferred.prompt();
    const { outcome } = await deferred.userChoice;
    setVisible(false);
    if (outcome === "accepted") {
      localStorage.setItem(DISMISSED_KEY, String(Date.now() + 365 * 86400 * 1000));
    } else {
      snooze();
    }
  }

  return (
    <div className="install-cue">
      <span className="install-cue-pointer" aria-hidden="true">👉</span>
      <div className="install-cue-icon"><Download size={18} /></div>
      <div className="install-cue-body">
        <div className="install-cue-title">Add CreditVoice to your phone</div>
        <div className="install-cue-sub">
          {ios ? "Open it like an app — no browser bar, no app store." : "One tap — works like an app, no app store."}
        </div>
        {ios && stepsOpen && (
          <ol className="install-cue-steps">
            <li>Tap the <Share2 size={12} style={{ verticalAlign: "-2px" }} /> <strong>Share</strong> button in your browser</li>
            <li>Scroll and choose <strong>Add to Home Screen</strong></li>
            <li>Tap <strong>Add</strong></li>
          </ol>
        )}
      </div>
      <button className="install-cue-btn" onClick={handleAction}>
        {ios ? (stepsOpen ? "Got it" : "Show me how") : "Install"}
      </button>
      <button className="install-cue-x" onClick={dismiss} aria-label="Not now">
        <X size={14} />
      </button>
    </div>
  );
}
