import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { Smartphone, Share2 } from "lucide-react";
import { isIOS, isStandalone, canPromptInstall, promptInstall, onInstallChange } from "../lib/pwaInstall";

// Permanent "Add to Home Screen" entry for the sidebar. Always visible until the
// app is installed. Android → native prompt (or manual steps if the browser
// hasn't offered it); iOS → Share → Add to Home Screen steps.
export default function InstallMenuItem({ onNavigate }) {
  const [installed, setInstalled] = useState(isStandalone());
  const [, force] = useState(0);
  const [modal, setModal] = useState(null);   // "ios" | "android" | null
  const ios = isIOS();

  useEffect(() => onInstallChange(() => force((n) => n + 1)), []);

  if (installed) return null;

  async function handleClick() {
    if (onNavigate) onNavigate();              // close the mobile drawer first
    if (ios) { setModal("ios"); return; }
    if (canPromptInstall()) {
      const outcome = await promptInstall();
      if (outcome === "accepted") setInstalled(true);
      return;
    }
    setModal("android");                       // browser hasn't offered it — show steps
  }

  return (
    <>
      <button
        type="button"
        className="nav-link"
        onClick={handleClick}
        style={{ margin: "2px 8px", background: "rgba(245,166,35,0.14)", color: "#f5a623", fontWeight: 600 }}
        title="Install CreditVoice on your phone"
      >
        <Smartphone size={16} />
        <span className="nav-label">Add to Home Screen</span>
      </button>

      {modal && createPortal(
        <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && setModal(null)}>
          <div className="modal">
            <div className="modal-header">
              <span className="modal-title">Add CreditVoice to your Home Screen</span>
              <button className="modal-close" onClick={() => setModal(null)}>×</button>
            </div>
            <div className="modal-body">
              {modal === "ios" ? (
                <ol style={{ lineHeight: 1.9, paddingLeft: 18, margin: 0 }}>
                  <li>Tap the <Share2 size={13} style={{ verticalAlign: "-2px" }} /> <strong>Share</strong> button in Safari's toolbar</li>
                  <li>Scroll down and choose <strong>Add to Home Screen</strong></li>
                  <li>Tap <strong>Add</strong> — the CreditVoice icon appears on your home screen</li>
                </ol>
              ) : (
                <>
                  <ol style={{ lineHeight: 1.9, paddingLeft: 18, margin: 0 }}>
                    <li>Open your browser menu (the <strong>⋮</strong> at the top-right)</li>
                    <li>Tap <strong>Install app</strong> or <strong>Add to Home screen</strong></li>
                    <li>Confirm — CreditVoice then opens like an app</li>
                  </ol>
                  <div style={{ marginTop: 12, fontSize: 12.5, color: "var(--text-muted)", background: "var(--surface, #f8fafc)", border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px" }}>
                    Phone says <strong>"Home screen layout locked"</strong>? That's an Android
                    setting. Long-press your home screen → <strong>Home settings</strong> →
                    turn off <strong>Lock Home screen layout</strong>, then try again.
                  </div>
                </>
              )}
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
