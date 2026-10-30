import { useState, useEffect } from "react";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull, dateTimeStr } from "../lib/format";

// The reasons stock can leave without a sale (stock_removal.py REASONS)
const REMOVE_REASONS = [
  ["damaged", "Damaged / broken"],
  ["expired", "Expired"],
  ["stolen", "Stolen / missing"],
  ["own_use", "Used in the business"],
  ["free", "Given free / sample"],
  ["returned", "Returned to supplier"],
  ["correction", "Counting correction"],
  ["other", "Other"],
];

/* Pick why — every removal is accounted for */
export function ReasonPicker({ reason, onReason, note, onNote }) {
  return (
    <>
      <div className="form-group">
        <label className="form-label">Why is it being removed? *</label>
        <select value={reason} onChange={e => onReason(e.target.value)}>
          <option value="">— Pick a reason —</option>
          {REMOVE_REASONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </div>
      <div className="form-group">
        <label className="form-label">Note {reason === "other" ? "*" : <span className="text-subtle">(optional)</span>}</label>
        <input value={note} maxLength={500} onChange={e => onNote(e.target.value)}
          placeholder={reason === "other" ? "Say what happened" : "e.g. rats got into the store"} />
      </div>
    </>
  );
}

/* Remove a product from the business: its stock goes out with the reason,
   the product is hidden — past sales and receipts stay. */
export function RemoveProductModal({ item, onClose, onRemoved }) {
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const left = Number(item.quantity || 0);
  async function remove() {
    if (!reason) { setErr("Pick why the product is being removed."); return; }
    if (reason === "other" && !note.trim()) { setErr("Say what happened."); return; }
    setBusy(true); setErr("");
    try { await apiPost(`inventory/${item.id}/remove`, { reason, note: note.trim() || null }); onRemoved(); }
    catch (e) { setErr(e.message); setBusy(false); }
  }
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">Remove {item.name}</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body" style={{ fontSize: 14 }}>
          <p style={{ marginTop: 0 }}>
            The product will no longer show in your stock or at the till. Its past sales, receipts and stock history are kept.
            {left > 0 && !item.is_service && <> The <strong>{left.toLocaleString()}{item.unit ? ` ${item.unit}` : ""}</strong> still in stock will be taken out and recorded with this reason.</>}
          </p>
          <ReasonPicker reason={reason} onReason={setReason} note={note} onNote={setNote} />
          {err && <div className="modal-error">{err}</div>}
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-danger" onClick={remove} disabled={busy}>{busy ? "Removing…" : "Remove product"}</button>
        </div>
      </div>
    </div>
  );
}

/* Inventory → Removed stock: every loss, why, and what it was worth */
export function RemovedStockModal({ onClose }) {
  const [days, setDays] = useState(30);
  const [reason, setReason] = useState("");
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let live = true;
    apiFetch("inventory/removed", reason ? { days, reason } : { days })
      .then(d => { if (live) setData(d); }).catch(e => live && setErr(e.message));
    return () => { live = false; };
  }, [days, reason]);

  function download() {
    const head = ["Date", "Product", "Quantity", "Reason", "Note", "Value (NGN)", "By"];
    const lines = data.rows.map(r => [dateTimeStr(r.date), r.product, r.quantity, r.reason_label, r.note || "", r.value, r.by]
      .map(v => `"${String(v ?? "").replace(/"/g, '""')}"`).join(","));
    const blob = new Blob([[head.join(","), ...lines].join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = `removed-stock-${days}-days.csv`; a.click();
    URL.revokeObjectURL(a.href);
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal modal-wide">
        <div className="modal-header">
          <span className="modal-title">Removed stock</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body" style={{ display: "grid", gap: 12, fontSize: 14 }}>
          <div className="td-muted" style={{ fontSize: 13 }}>
            Stock that left without being sold — taken out by hand, products removed, expired write-offs and shortages found at stock counts. Value is at cost price.
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
            {[[7, "7 days"], [30, "30 days"], [90, "3 months"], [365, "1 year"]].map(([d, l]) => (
              <button key={d} className={`btn btn-sm ${days === d ? "btn-primary" : "btn-ghost"}`} onClick={() => { setData(null); setDays(d); }}>{l}</button>
            ))}
            <select value={reason} onChange={e => { setData(null); setReason(e.target.value); }} style={{ marginLeft: "auto" }}>
              <option value="">All reasons</option>
              {REMOVE_REASONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              <option value="count_short">Short at stock count</option>
            </select>
          </div>
          {err && <div className="modal-error">{err}</div>}
          {!data ? <div className="td-muted">Loading…</div> : (
            <>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <div className="card" style={{ padding: "8px 12px" }}>
                  <div className="td-muted" style={{ fontSize: 12 }}>Total lost</div>
                  <strong style={{ fontSize: 17 }}>{nairaFull(data.total_value)}</strong>
                </div>
                {data.totals.map(t => (
                  <div key={t.reason} className="card" style={{ padding: "8px 12px" }}>
                    <div className="td-muted" style={{ fontSize: 12 }}>{t.label} ({t.count})</div>
                    <strong>{nairaFull(t.value)}</strong>
                  </div>
                ))}
              </div>
              {data.rows.length === 0 ? <div className="td-muted">Nothing removed in this time.</div> : (
                <div style={{ overflowX: "auto" }}>
                  <table className="data-table" style={{ width: "100%" }}>
                    <thead><tr><th>Date</th><th>Product</th><th style={{ textAlign: "right" }}>Qty</th><th>Reason</th><th style={{ textAlign: "right" }}>Value</th><th>By</th></tr></thead>
                    <tbody>
                      {data.rows.map(r => (
                        <tr key={r.id}>
                          <td className="td-muted">{dateTimeStr(r.date)}</td>
                          <td>{r.product}{r.product_removed && <span className="td-muted"> · product removed</span>}</td>
                          <td style={{ textAlign: "right" }}>{Number(r.quantity).toLocaleString()}{r.unit ? ` ${r.unit}` : ""}</td>
                          <td>{r.reason_label}{r.note && <div className="td-muted" style={{ fontSize: 12 }}>{r.note}</div>}</td>
                          <td style={{ textAlign: "right" }}>{r.value ? nairaFull(r.value) : "—"}</td>
                          <td className="td-muted">{r.by}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>Close</button>
          {data?.rows.length > 0 && <button className="btn btn-secondary" onClick={download}>Download (Excel / CSV)</button>}
        </div>
      </div>
    </div>
  );
}
