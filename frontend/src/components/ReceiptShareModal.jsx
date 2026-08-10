import { useState } from "react";
import { Copy, Share2, CheckCircle } from "lucide-react";

// Shows a plain-text receipt the owner can copy or share (suppliers have no
// phone on file, so the owner shares it manually if they want to).
export default function ReceiptShareModal({ title = "Receipt", text, onClose }) {
  const [copied, setCopied] = useState(false);

  function copy() {
    navigator.clipboard.writeText(text || "").then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  async function share() {
    if (navigator.share) {
      try { await navigator.share({ title, text }); return; } catch { /* cancelled */ }
    }
    copy();
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">{title}</span>
          <button type="button" className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <pre style={{
            whiteSpace: "pre-wrap", wordBreak: "break-word", fontFamily: "inherit",
            background: "var(--surface, #f8fafc)", border: "1px solid var(--border)",
            borderRadius: 8, padding: 14, margin: 0, fontSize: 13.5, lineHeight: 1.6,
          }}>{text}</pre>
        </div>
        <div className="modal-footer">
          <button type="button" className="btn btn-secondary" onClick={copy}>
            {copied ? <><CheckCircle size={14} /> Copied!</> : <><Copy size={14} /> Copy</>}
          </button>
          <button type="button" className="btn btn-primary" onClick={share}>
            <Share2 size={14} /> Share
          </button>
        </div>
      </div>
    </div>
  );
}
