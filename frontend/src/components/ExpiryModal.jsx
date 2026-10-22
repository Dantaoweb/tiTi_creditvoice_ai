import { useState, useEffect } from "react";
import { apiFetch, apiPost } from "../lib/api";

const fmt = d => new Date(d).toLocaleDateString("en-NG", { day: "numeric", month: "short", year: "numeric" });

/* Goods that are expired or expire soon (Settings → Stock sets how soon).
   Expired goods can be written off — out of stock, counted as a loss. Sell
   the rest first. */
export default function ExpiryModal({ canManage, onClose }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(null);

  function load() { apiFetch("inventory/expiry").then(setData).catch(e => setErr(e.message)); }
  useEffect(load, []);

  async function writeOff(r) {
    if (!window.confirm(`Write off ${r.expired_qty}${r.unit ? ` ${r.unit}` : ""} of expired ${r.name}? They leave stock and count as a loss.`)) return;
    setBusy(r.item_id); setErr("");
    try { await apiPost(`inventory/${r.item_id}/write-off-expired`, { quantity: r.expired_qty }); load(); }
    catch (e) { setErr(e.message); }
    finally { setBusy(null); }
  }

  const today = new Date().toISOString().slice(0, 10);
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 560 }}>
        <div className="modal-header">
          <span className="modal-title">Expiry</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          {!data && !err && <div className="td-muted">Loading…</div>}
          {data && (
            <>
              <div className="td-muted" style={{ fontSize: 13, marginBottom: 8 }}>
                Expired goods, and goods that expire within {data.warn_days} days (change this in Settings → Stock).
                Add expiry dates when you record stock received.
              </div>
              {data.items.length === 0 && <div style={{ padding: "12px 0" }}>Nothing expired or expiring soon ✓</div>}
              {data.items.map(r => (
                <div key={r.item_id} style={{ padding: "10px 0", borderBottom: "1px solid var(--border)", fontSize: 13 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                    <strong>{r.name}</strong>
                    {r.expired_qty > 0 && canManage && (
                      <button className="btn btn-ghost btn-sm" style={{ color: "#b91c1c" }} disabled={busy === r.item_id}
                        onClick={() => writeOff(r)}>{busy === r.item_id ? "Writing off…" : "Write off expired"}</button>
                    )}
                  </div>
                  {r.rows.map((x, i) => (
                    <div key={i} style={{ color: x.expiry < today ? "#b91c1c" : undefined }}>
                      {x.quantity}{r.unit ? ` ${r.unit}` : ""} {x.expiry < today ? "expired" : "expire"} {fmt(x.expiry)}
                      {x.batch_no ? ` · batch ${x.batch_no}` : ""}
                    </div>
                  ))}
                  {r.expired_qty === 0 && <div className="td-muted">Sell these first.</div>}
                </div>
              ))}
            </>
          )}
          {err && <div className="modal-error">{err}</div>}
        </div>
        <div className="modal-footer"><button className="btn btn-primary" onClick={onClose}>Done</button></div>
      </div>
    </div>
  );
}
