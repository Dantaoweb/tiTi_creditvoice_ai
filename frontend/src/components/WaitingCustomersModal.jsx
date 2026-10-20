import { useState, useEffect } from "react";
import { apiFetch, apiPost } from "../lib/api";

/* After stock is added: the customers still waiting for this product. The
   owner ticks whom to keep goods aside for — nothing is kept unless ticked.
   Renders nothing (and calls onDone at once) when no one is waiting, or for
   staff who can't keep goods aside. */
export default function WaitingCustomersModal({ itemId, itemName, canKeep, onDone }) {
  const [data, setData] = useState(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!itemId || !canKeep) { onDone(); return; }
    apiFetch(`inventory/${itemId}/waiting`)
      .then(w => {
        const rows = (w.waiting || []).filter(r => r.remaining > r.kept);
        if (!rows.length) { onDone(); return; }
        let left = w.item.free || 0;
        setData({
          free: w.item.free || 0,
          unit: w.item.unit,
          rows: rows.map(r => {
            const q = Math.max(0, Math.min(r.remaining - r.kept, left));
            left -= q;
            return { ...r, tick: false, qty: String(q) };
          }),
        });
      })
      .catch(() => onDone());               // the stock is added; this is only a help
  }, [itemId]);

  if (!data) return null;

  // Stock still free for each row: what the rows above it have taken
  const freeBefore = data.rows.map((_, i) => data.rows.slice(0, i).reduce(
    (left, r) => left - (r.tick ? Math.max(0, Math.min(Number(r.qty) || 0, r.remaining - r.kept)) : 0),
    data.free));
  const setRow = (i, k, v) => setData(d => ({ ...d, rows: d.rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)) }));

  async function keep() {
    setSaving(true); setErr("");
    try {
      for (const w of data.rows.filter(w => w.tick && Number(w.qty) > 0)) {
        await apiPost("deliveries/goods/keep", { customer_id: w.customer_id, key: w.key, kept: w.kept + Number(w.qty) });
      }
      onDone();
    } catch (e) { setErr(e.message); setSaving(false); }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onDone()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">Customers waiting for {itemName}</span>
          <button className="modal-close" onClick={onDone}>×</button>
        </div>
        <div className="modal-body">
          <div style={{ fontSize: 13, marginBottom: 10 }}>
            Stock added. These customers bought {itemName} and are still waiting. Tick to keep some aside
            for them — no one else can buy kept-aside goods. Leave it unticked to keep it free to sell.
          </div>
          {data.rows.map((w, i) => {
            const most = Math.max(0, Math.min(w.remaining - w.kept, freeBefore[i]));
            return (
              <label key={w.key + w.customer_id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0", fontSize: 13 }}>
                <input type="checkbox" checked={w.tick} style={{ width: "auto" }} disabled={most <= 0 && !w.tick}
                  onChange={e => setRow(i, "tick", e.target.checked)} />
                <span style={{ flex: 1 }}>
                  Keep aside for <strong>{w.customer}</strong>
                  <span className="td-muted"> · waiting for {w.remaining}{w.kept > 0 ? `, ${w.kept} already kept` : ""}</span>
                </span>
                {w.tick && (
                  <input type="number" min={0} max={most} value={w.qty} style={{ width: 70 }}
                    onChange={e => setRow(i, "qty", e.target.value)} />
                )}
              </label>
            );
          })}
          {err && <div className="modal-error">{err}</div>}
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onDone}>Not now</button>
          <button className="btn btn-primary" onClick={keep}
            disabled={saving || !data.rows.some(w => w.tick && Number(w.qty) > 0)}>
            {saving ? "Saving…" : "Keep aside"}
          </button>
        </div>
      </div>
    </div>
  );
}
