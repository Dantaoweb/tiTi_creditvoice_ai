import { useEffect, useState } from "react";
import { apiFetch, apiPost } from "../lib/api";
import CreditNoteResult, { MoneyModeChoice } from "./CreditNoteResult";

/* Goods from a sale that were delivered and came back. Back into stock when
   they can be sold again, kept out when damaged; a credit note for the money.
   Owner / authorised staff. */
export default function ReturnGoodsModal({ saleId, onClose }) {
  const [data, setData] = useState(null);
  const [qty, setQty] = useState({});
  const [mode, setMode] = useState("REFUND");
  const [restock, setRestock] = useState("SELLABLE");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState(null);

  useEffect(() => {
    apiFetch(`sales/${saleId}/returnable`)
      .then(d => { setData(d); if (d.has_customer) setMode("CREDIT"); })
      .catch(e => setErr(e.message));
  }, [saleId]);

  async function save() {
    const lines = (data?.lines || [])
      .map(l => ({ line_id: l.line_id, quantity: Number(qty[l.line_id] || 0) }))
      .filter(l => l.quantity > 0);
    if (!lines.length) { setErr("Enter how many came back."); return; }
    if (!reason.trim()) { setErr("Say why — the reason is kept for any dispute later."); return; }
    setSaving(true); setErr("");
    try {
      setResult(await apiPost(`sales/${saleId}/return`, { lines, mode, restock, reason: reason.trim() }));
    } catch (e) { setErr(e.message); }
    finally { setSaving(false); }
  }

  const choice = (value, title, hint) => (
    <label style={{ display: "flex", gap: 8, alignItems: "flex-start", padding: "8px 10px", border: "1px solid var(--line)", borderRadius: 8, cursor: "pointer", background: restock === value ? "var(--bg)" : "transparent" }}>
      <input type="radio" name="cn-restock" checked={restock === value} onChange={() => setRestock(value)} style={{ width: "auto", marginTop: 3 }} />
      <span><strong style={{ fontSize: 13 }}>{title}</strong><div className="td-muted" style={{ fontSize: 12 }}>{hint}</div></span>
    </label>
  );

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">Return goods{data?.receipt_number ? ` — receipt #${data.receipt_number}` : ""}</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        {result ? <CreditNoteResult result={result} onClose={onClose} /> : (
          <>
            <div className="modal-body" style={{ display: "grid", gap: 10 }}>
              {!data && !err && <div className="td-muted">Loading…</div>}
              {data && (
                <>
                  <div>
                    <label className="form-label">How many came back?</label>
                    {data.lines.map(l => (
                      <div key={l.line_id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginTop: 6, fontSize: 13 }}>
                        <span style={{ minWidth: 0 }}>
                          {l.product}
                          <span className="td-muted"> · delivered {l.delivered}{l.returned ? ` · ${l.returned} back already` : ""}</span>
                        </span>
                        <input type="number" min={0} max={l.returnable} disabled={!l.returnable}
                          value={qty[l.line_id] ?? ""} placeholder="0"
                          onChange={e => setQty(p => ({ ...p, [l.line_id]: e.target.value }))}
                          style={{ width: 70 }} />
                      </div>
                    ))}
                  </div>
                  <div>
                    <label className="form-label">The goods</label>
                    <div style={{ display: "grid", gap: 6 }}>
                      {choice("SELLABLE", "Can be sold again", "They go back into stock.")}
                      {choice("DAMAGED", "Damaged / can't be sold", "They stay out of stock.")}
                    </div>
                  </div>
                  <div>
                    <label className="form-label">Money</label>
                    <MoneyModeChoice mode={mode} setMode={setMode} allowCredit={data.has_customer} />
                  </div>
                  <div>
                    <label className="form-label">Reason *</label>
                    <input value={reason} maxLength={300} onChange={e => setReason(e.target.value)}
                      placeholder="e.g. Wrong brand delivered" style={{ width: "100%" }} />
                  </div>
                  <span className="form-hint">
                    The sale is not changed — a numbered credit note records the return, and the customer gets a copy.
                  </span>
                </>
              )}
              {err && <div className="modal-error">{err}</div>}
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={onClose}>Back</button>
              <button className="btn btn-primary" onClick={save} disabled={saving || !data}>
                {saving ? "Saving…" : "Issue credit note"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
