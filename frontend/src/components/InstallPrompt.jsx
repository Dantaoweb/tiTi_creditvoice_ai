import { useState, useEffect } from "react";
import { Download, X, Share2 } from "lucide-react";
import { isIOS, isStandalone, canPromptInstall, promptInstall, onInstallChange } from "../lib/pwaInstall";

const DISMISSED_KEY = "cv-install-dismissed-until";
const SNOOZE_DAYS   = 14;

// First-time cue after sign-in inviting the user to add CreditVoice to their
// home screen. Android fires the native prompt; iOS shows the Share → Add steps.
// A blinking pointer draws the eye. The permanent entry lives in the sidebar.
export default function InstallPrompt() {
  const [visible, setVisible]     = useState(false);
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
    // Android: show once the browser says it's installable.
    let timer = null;
    const check = () => { if (canPromptInstall()) timer = setTimeout(() => setVisible(true), 2500); };
    check();
    const off = onInstallChange(check);
    return () => { off(); if (timer) clearTimeout(timer); };
  }, [ios]);

  if (!visible) return null;

  function snooze() {
    localStorage.setItem(DISMISSED_KEY, String(Date.now() + SNOOZE_DAYS * 86400 * 1000));
  }
  function dismiss() { setVisible(false); snooze(); }

  async function handleAction() {
    if (ios) { setStepsOpen((o) => !o); return; }
    const outcome = await promptInstall();
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
