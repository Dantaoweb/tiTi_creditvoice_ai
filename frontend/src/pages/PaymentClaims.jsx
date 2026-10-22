import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { apiFetch, apiPost } from "../lib/api";
import { dateTimeStr, nairaFull } from "../lib/format";

/* Customers who say they've paid (pay link page or "PAID" on WhatsApp).
   Check your bank: Confirm records the payment and sends the receipt; Not
   received tells the customer. Nothing is recorded until you confirm. */
export default function PaymentClaims() {
  const [rows, setRows] = useState(null);
  const [open, setOpen] = useState(null);       // claim with its photo
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");

  function load() { apiFetch("payment-claims").then(d => setRows(d.claims || [])).catch(e => setErr(e.message)); }
  useEffect(load, []);

  async function show(c) {
    setErr(""); setReason(""); setAmount(String(c.amount));
    try { setOpen(await apiFetch(`payment-claims/${c.id}`)); } catch (e) { setErr(e.message); }
  }

  async function act(kind) {
    setBusy(kind); setErr("");
    try {
      await apiPost(`payment-claims/${open.id}/${kind}`, kind === "confirm"
        ? { amount: Number(String(amount).replace(/,/g, "")) } : { reason });
      setOpen(null); load();
      window.dispatchEvent(new Event("cv-payment-claims"));
    } catch (e) { setErr(e.message); }
    finally { setBusy(""); }
  }

  return (
    <div className="card" style={{ maxWidth: 720 }}>
      <div className="card-header"><span className="card-title">Payments to confirm</span></div>
      <div className="td-muted" style={{ padding: "0 16px 8px", fontSize: 13 }}>
        Customers who say they've paid by transfer. Check your bank first — nothing is recorded until you confirm.
        They get the link in invoices, receipts and balance messages once your bank account is on <Link to="/profile">My Profile</Link>.
      </div>
      {err && !open && <div className="modal-error" style={{ margin: 12 }}>{err}</div>}
      {rows === null ? <div className="td-muted" style={{ padding: 16 }}>Loading…</div>
        : rows.length === 0 ? <div className="td-muted" style={{ padding: 16 }}>Nothing yet.</div>
        : rows.map(c => (
          <div key={c.id} style={{
            display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap",
            padding: "12px 16px", borderBottom: "1px solid var(--border)", opacity: c.status === "pending" ? 1 : 0.65,
          }}>
            <div style={{ minWidth: 0 }}>
              <strong>{c.payer_name || c.customer || "Customer"}</strong> · {nairaFull(c.amount)}
              <div className="td-muted" style={{ fontSize: 12 }}>
                {c.label} · {dateTimeStr(c.created_at)} · {c.source === "whatsapp" ? "said on WhatsApp" : "pay link"}
                {c.has_proof ? " · 📷 photo" : ""}{c.note ? ` · "${c.note}"` : ""}
              </div>
            </div>
            {c.status === "pending"
              ? <button className="btn btn-primary btn-sm" onClick={() => show(c)}>Check</button>
              : <span style={{ fontSize: 12, fontWeight: 700, color: c.status === "confirmed" ? "#166534" : "#b91c1c" }}>
                  {c.status === "confirmed" ? "Confirmed" : `Not received — ${c.reject_reason}`}
                </span>}
          </div>
        ))}

      {open && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setOpen(null)}>
          <div className="modal">
            <div className="modal-header">
              <span className="modal-title">{open.payer_name || open.customer} · {nairaFull(open.amount)}</span>
              <button className="modal-close" onClick={() => setOpen(null)}>×</button>
            </div>
            <div className="modal-body" style={{ display: "grid", gap: 10 }}>
              <div style={{ fontSize: 13 }}>
                For <strong>{open.label}</strong>{open.customer ? ` (${open.customer})` : ""}. Check that the money is in your bank.
              </div>
              {open.note && <div style={{ fontSize: 13 }}>They wrote: "{open.note}"</div>}
              {open.proof && <img src={open.proof} alt="Transfer receipt" style={{ maxWidth: "100%", borderRadius: 8 }} />}
              <label className="form-label" style={{ margin: 0 }}>Amount that arrived (₦)</label>
              <input inputMode="numeric" value={amount} onChange={e => setAmount(e.target.value.replace(/[^\d,]/g, ""))} />
              <label className="form-label" style={{ margin: 0 }}>If it hasn't arrived, say why <span style={{ opacity: 0.6 }}>(the customer is told)</span></label>
              <input value={reason} maxLength={200} onChange={e => setReason(e.target.value)} placeholder="e.g. Not in my account yet" />
              {err && <div className="modal-error">{err}</div>}
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" style={{ color: "#b91c1c" }} disabled={!!busy || !reason.trim()} onClick={() => act("reject")}>
                {busy === "reject" ? "Saving…" : "Not received"}
              </button>
              <button className="btn btn-primary" disabled={!!busy} onClick={() => act("confirm")}>
                {busy === "confirm" ? "Recording…" : "Confirm — money is in"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
