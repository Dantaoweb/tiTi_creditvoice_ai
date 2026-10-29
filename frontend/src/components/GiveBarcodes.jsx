import { useState, useEffect } from "react";
import { apiFetch, apiPost } from "../lib/api";

/* Inventory → Barcodes: products with no barcode get the shop's own code
   (starts with 2, works in this business's shops and branches). */
export default function GiveBarcodes({ onClose, onChanged }) {
  const [items, setItems] = useState(null);
  const [tick, setTick] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  function load() {
    apiFetch("barcodes/missing")
      .then(d => { setItems(d.items); setTick(new Set(d.items.map(i => i.id))); })
      .catch(e => setErr(e.message));
  }
  useEffect(() => { load(); }, []);

  async function give() {
    setBusy(true); setErr("");
    try {
      const r = await apiPost("barcodes/give", { item_ids: [...tick] });
      setMsg(`${r.given} product${r.given !== 1 ? "s" : ""} now ${r.given !== 1 ? "have" : "has"} a barcode.`);
      load(); onChanged?.();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  const toggle = (id, on) => setTick(p => { const n = new Set(p); if (on) n.add(id); else n.delete(id); return n; });

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 520 }}>
        <div className="modal-header">
          <span className="modal-title">Give products a barcode</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body" style={{ display: "grid", gap: 10, fontSize: 14 }}>
          <div className="td-muted" style={{ fontSize: 13 }}>
            For home-made, repacked or loose goods with no barcode. Each gets its own code starting with 2, which
            scanners and the phone camera read at your till. It works in your shop and branches only — to sell your
            product to supermarkets or other shops, you need an official barcode from GS1 Nigeria.
          </div>
          {err && <div className="modal-error">{err}</div>}
          {msg && <div style={{ color: "#166534", fontWeight: 600 }}>{msg}</div>}
          {!items ? <div className="td-muted">Loading…</div> : items.length === 0 ? (
            <div className="td-muted">Every product has a barcode.</div>
          ) : (
            <>
              <div style={{ display: "flex", gap: 8 }}>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setTick(new Set(items.map(i => i.id)))}>Tick all</button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setTick(new Set())}>Untick all</button>
              </div>
              <div style={{ maxHeight: 300, overflowY: "auto", border: "1px solid var(--border)", borderRadius: 8, padding: "4px 10px" }}>
                {items.map(i => (
                  <label key={i.id} style={{ display: "flex", gap: 8, alignItems: "center", padding: "4px 0" }}>
                    <input type="checkbox" style={{ width: "auto" }} checked={tick.has(i.id)} onChange={e => toggle(i.id, e.target.checked)} />
                    {i.name}
                  </label>
                ))}
              </div>
              <span className="form-hint">Untick goods you sell loose by weight — they can stay without a barcode.</span>
            </>
          )}
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>Close</button>
          {items?.length > 0 && (
            <button className="btn btn-primary" onClick={give} disabled={busy || !tick.size}>
              {busy ? "Making…" : `Make ${tick.size} barcode${tick.size !== 1 ? "s" : ""}`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
