import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Rocket, X, Check, Package } from "lucide-react";
import { apiFetch, apiPost } from "../lib/api";
import { useAuth } from "../context/AuthContext";

const DISMISS_KEY = "cv_getstarted_dismissed";

// Category → business-type picker (used from "Not quite" / "Choose business type").
function TypePicker({ onPick, onClose, busy }) {
  const [cats, setCats] = useState([]);
  const [cat, setCat] = useState(null);

  useEffect(() => {
    apiFetch("auth/business-categories").then(d => setCats(d.categories || [])).catch(() => {});
  }, []);

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">{cat ? cat.label : "What kind of business is it?"}</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          {!cat ? (
            <div className="getstarted-grid">
              {cats.map(c => (
                <button key={c.key} className="getstarted-pick" onClick={() => setCat(c)}>{c.label}</button>
              ))}
            </div>
          ) : (
            <>
              <button className="btn btn-ghost btn-sm" onClick={() => setCat(null)}>← Back to categories</button>
              <div className="getstarted-grid" style={{ marginTop: 10 }}>
                {cat.businesses.map(b => (
                  <button key={b.key} className="getstarted-pick" disabled={busy} onClick={() => onPick(b.key)}>{b.label}</button>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function GettingStarted() {
  const { refreshUser } = useAuth();
  const [data, setData] = useState(null);
  const [dismissed, setDismissed] = useState(() => localStorage.getItem(DISMISS_KEY) === "1");
  const [picker, setPicker] = useState(false);
  const [busy, setBusy] = useState(false);

  function load() { apiFetch("getting-started").then(setData).catch(() => {}); }
  useEffect(() => { load(); }, []);

  if (dismissed || !data) return null;
  const showSuggest = data.needs_type && data.suggestion;
  const showEmpty = !data.has_priced_stock;
  if (!showSuggest && !showEmpty) return null;

  async function setType(typeKey) {
    setBusy(true);
    try {
      await apiPost("getting-started/business-type", { business_type: typeKey });
      // Clear the dismissal so the (now type-aware) card can still guide adding stock.
      load();
      if (refreshUser) refreshUser();
      setPicker(false);
    } catch (e) {
      alert(e.message || "Could not set business type.");
    } finally {
      setBusy(false);
    }
  }

  function dismiss() {
    localStorage.setItem(DISMISS_KEY, "1");
    setDismissed(true);
  }

  return (
    <div className="getstarted-card">
      <button className="getstarted-close" onClick={dismiss} title="Dismiss"><X size={16} /></button>
      <div className="getstarted-head"><Rocket size={17} /> Let's set up your shop</div>

      {showSuggest && (
        <div className="getstarted-suggest">
          It looks like you sell <strong>{data.suggestion.label}</strong>. Set your business type so your
          price list, stock fields and receipts match?
          <div className="getstarted-actions">
            <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => setType(data.suggestion.type)}>
              <Check size={13} /> Yes, I sell {data.suggestion.label}
            </button>
            <button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => setPicker(true)}>Not quite</button>
          </div>
        </div>
      )}

      {showEmpty && (
        <div className="getstarted-body">
          <p style={{ margin: "6px 0 10px" }}>
            What are you selling or doing? Add your products (with prices) so you can record sales and print receipts.
          </p>
          <div className="getstarted-actions">
            <Link to="/inventory" className="btn btn-primary btn-sm"><Package size={13} /> Add your products</Link>
            {data.needs_type && !data.suggestion && (
              <button className="btn btn-secondary btn-sm" onClick={() => setPicker(true)}>Choose business type</button>
            )}
          </div>
        </div>
      )}

      {picker && <TypePicker onPick={setType} onClose={() => setPicker(false)} busy={busy} />}
    </div>
  );
}
