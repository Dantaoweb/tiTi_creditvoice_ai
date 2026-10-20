import { useState } from "react";
import { apiPost } from "../lib/api";

const qtyLabel = (n, unit) => `${Number(n).toLocaleString()}${unit ? ` ${unit}` : ""}`;

/* Keep some of a customer's goods aside in the store so no one else can buy
   them — or release them (0): still owed, but sellable to anyone. Owner and
   authorised staff only. `goods` is one row from the deliveries "goods" list. */
export default function KeepAsideModal({ goods, onClose }) {
  const most = Math.min(goods.remaining, goods.kept + (goods.in_store_free ?? goods.remaining));
  const [qty, setQty] = useState(String(goods.kept > 0 ? goods.kept : most));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  async function save(n) {
    if (Number.isNaN(n) || n < 0) { setErr("Enter how many to keep aside."); return; }
    if (n > most) { setErr(`Only ${qtyLabel(most, goods.unit)} can be kept aside — that's what is in the store.`); return; }
    setSaving(true); setErr("");
    try {
      await apiPost("deliveries/goods/keep", { customer_id: goods.customer_id, key: goods.key, kept: n });
      onClose();
    } catch (e) { setErr(e.message); setSaving(false); }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">Keep {goods.product} aside for {goods.customer}</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <div className="td-muted" style={{ fontSize: 13, marginBottom: 10 }}>
            Waiting for {qtyLabel(goods.remaining, goods.unit)} · kept aside now {qtyLabel(goods.kept, goods.unit)}
            {goods.in_store_free != null && ` · ${qtyLabel(goods.in_store_free, goods.unit)} in store not kept for anyone`}
          </div>
          <label className="form-label">How many to keep aside for {goods.customer}?</label>
          <input type="number" min={0} max={most} inputMode="decimal" value={qty}
            onChange={e => setQty(e.target.value)} style={{ width: "100%" }} autoFocus />
          <span className="form-hint">
            Kept-aside goods can't be sold to anyone else. What isn't kept aside is still owed to {goods.customer} —
            it just stays free to sell until you keep it aside or make a waybill.
          </span>
          {err && <div className="modal-error">{err}</div>}
        </div>
        <div className="modal-footer">
          {goods.kept > 0 && (
            <button className="btn btn-ghost" onClick={() => save(0)} disabled={saving}>Release all</button>
          )}
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={() => save(Number(qty))} disabled={saving}>
            {saving ? "Saving…" : "Keep aside"}
          </button>
        </div>
      </div>
    </div>
  );
}
