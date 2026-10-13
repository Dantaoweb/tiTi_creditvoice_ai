import { useState } from "react";
import { apiPost } from "../lib/api";
import CreditNoteResult, { MoneyModeChoice } from "./CreditNoteResult";

const qtyLabel = (n, unit) => `${Number(n).toLocaleString()}${unit ? ` ${unit}` : ""}`;

/* Cancel goods a customer bought that were never delivered. They never left
   the store, so they stop being reserved and can be sold again straight away;
   a credit note takes the money off their balance or records it handed back.
   `goods` is one row from the deliveries "goods" list. Owner / authorised staff. */
export default function CancelGoodsModal({ goods, onClose }) {
  const [qty, setQty] = useState(String(goods.remaining));
  const [mode, setMode] = useState("CREDIT");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState(null);

  async function save() {
    const n = Number(qty);
    if (!n || n <= 0) { setErr("Enter how many to cancel."); return; }
    if (n > goods.remaining) { setErr(`Only ${qtyLabel(goods.remaining, goods.unit)} still to deliver.`); return; }
    if (!reason.trim()) { setErr("Say why — the reason is kept for any dispute later."); return; }
    setSaving(true); setErr("");
    try {
      setResult(await apiPost("deliveries/goods/cancel", {
        customer_id: goods.customer_id, key: goods.key, quantity: n, mode, reason: reason.trim(),
      }));
    } catch (e) { setErr(e.message); }
    finally { setSaving(false); }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">Cancel / refund {goods.product} — {goods.customer}</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        {result ? <CreditNoteResult result={result} onClose={onClose} /> : (
          <>
            <div className="modal-body" style={{ display: "grid", gap: 10 }}>
              <div className="td-muted" style={{ fontSize: 13 }}>
                Bought {qtyLabel(goods.bought, goods.unit)} · delivered {qtyLabel(goods.delivered, goods.unit)} ·{" "}
                <strong>{qtyLabel(goods.remaining, goods.unit)} not delivered</strong>
              </div>
              <div>
                <label className="form-label">How many to cancel?</label>
                <input type="number" min={1} max={goods.remaining} inputMode="decimal"
                  value={qty} onChange={e => setQty(e.target.value)} style={{ width: "100%" }} />
              </div>
              <div>
                <label className="form-label">Money</label>
                <MoneyModeChoice mode={mode} setMode={setMode} />
              </div>
              <div>
                <label className="form-label">Reason *</label>
                <input value={reason} maxLength={300} onChange={e => setReason(e.target.value)}
                  placeholder="e.g. Customer no longer needs the rest" style={{ width: "100%" }} />
              </div>
              <span className="form-hint">
                The cancelled goods never left your store, so they become available to sell again.
                The sale itself is not changed — a numbered credit note records this, and the customer gets a copy.
              </span>
              {err && <div className="modal-error">{err}</div>}
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={onClose}>Back</button>
              <button className="btn btn-primary" onClick={save} disabled={saving}>
                {saving ? "Saving…" : "Issue credit note"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
