import { useState } from "react";
import { apiPost } from "../lib/api";

const qtyLabel = (n, unit) => `${Number(n).toLocaleString()}${unit ? ` ${unit}` : ""}`;

/* Record a trip of goods a customer already bought: it leaves stock now and
   the customer gets a WhatsApp delivery note (bought · delivered · still to
   deliver). When WhatsApp can't reach them, offer to send it from the owner's
   own phone. `goods` is one row from the deliveries "goods" list. */
export default function DeliverGoodsModal({ goods, onClose, onDone }) {
  const [qty, setQty] = useState(String(goods.remaining));
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState(null);

  async function save() {
    const n = Number(qty);
    if (!n || n <= 0) { setErr("Enter how many were delivered."); return; }
    if (n > goods.remaining) { setErr(`Only ${qtyLabel(goods.remaining, goods.unit)} left to deliver.`); return; }
    setSaving(true); setErr("");
    try {
      const r = await apiPost("deliveries/goods", {
        customer_id: goods.customer_id, key: goods.key, quantity: n, note: note.trim() || null,
      });
      setResult(r);
      onDone?.(r);
    } catch (e) { setErr(e.message); }
    finally { setSaving(false); }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">Deliver {goods.product} to {goods.customer}</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        {!result ? (
          <>
            <div className="modal-body">
              <div className="td-muted" style={{ fontSize: 13, marginBottom: 10 }}>
                Bought {qtyLabel(goods.bought, goods.unit)} · delivered {qtyLabel(goods.delivered, goods.unit)} ·{" "}
                <strong style={{ color: "var(--rose)" }}>{qtyLabel(goods.remaining, goods.unit)} to deliver</strong>
              </div>
              <label className="form-label">How many went out today?</label>
              <input type="number" min={1} max={goods.remaining} inputMode="decimal"
                value={qty} onChange={e => setQty(e.target.value)} style={{ width: "100%" }} autoFocus />
              <label className="form-label" style={{ marginTop: 10 }}>
                Driver / truck no. <span style={{ opacity: 0.55, fontWeight: 400 }}>(optional)</span>
              </label>
              <input value={note} maxLength={200} onChange={e => setNote(e.target.value)}
                placeholder="e.g. Musa, truck KJA 123" style={{ width: "100%" }} />
              <span className="form-hint">
                These leave stock now. {goods.customer_phone
                  ? "The customer gets a delivery note on WhatsApp."
                  : "No phone saved for this customer, so no delivery note can be sent."}
              </span>
              {err && <div className="modal-error">{err}</div>}
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
              <button className="btn btn-primary" onClick={save} disabled={saving}>
                {saving ? "Saving…" : "Record delivery"}
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="modal-body">
              <div style={{ fontWeight: 600, marginBottom: 8 }}>
                ✓ {qtyLabel(result.delivered_now, result.unit)} delivered ·{" "}
                {result.remaining ? `${qtyLabel(result.remaining, result.unit)} still to deliver` : "all delivered"}
              </div>
              <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: 13, background: "var(--bg)", padding: 10, borderRadius: 8, margin: 0 }}>
                {result.message}
              </pre>
              <span className="form-hint">
                {result.sent ? "Sent to the customer's WhatsApp."
                  : result.wa_link ? "WhatsApp couldn't deliver it from tiTi — send it from your own phone."
                  : "No phone saved — share this note with the customer yourself."}
              </span>
            </div>
            <div className="modal-footer">
              {result.wa_link && (
                <a className="btn btn-secondary" href={result.wa_link} target="_blank" rel="noreferrer">
                  Send from my WhatsApp
                </a>
              )}
              <button className="btn btn-primary" onClick={onClose}>Done</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
