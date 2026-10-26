import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Printer, Send, PackageCheck, Pencil, Ban, Lock } from "lucide-react";
import { apiFetch, apiPost } from "../lib/api";
import { dateStr, dateTimeStr, nairaFull, fmtAmt, parseAmt } from "../lib/format";
import PrintHeader from "../components/PrintHeader";
import { paperClass } from "../lib/print";

/* One purchase order: send it, receive what arrives (stock + supplier
   purchase, like stock received), close it keeping any shortfall, print it. */
export default function PurchaseOrderView() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [doc, setDoc] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");
  const [receiving, setReceiving] = useState(null);     // {line id: {quantity, expiry_date, batch_no}}
  const [paid, setPaid] = useState("");
  const [due, setDue] = useState("");

  function load() { apiFetch(`purchase-orders/${id}`).then(setDoc).catch(e => setErr(e.message)); }
  useEffect(load, [id]);

  async function act(name, path, body) {
    setBusy(name); setErr("");
    try {
      const d = await apiPost(`purchase-orders/${id}/${path}`, body || {});
      setDoc(d);
      return d;
    } catch (e) { setErr(e.message); return null; }
    finally { setBusy(""); }
  }

  async function send() {
    const d = await act("send", "send");
    if (!d) return;
    if (d.sent) setNote(`Sent to ${d.supplier?.name} on WhatsApp.`);
    else if (d.wa_link) { setNote("WhatsApp couldn't reach them from tiTi — opening your WhatsApp to send it."); window.open(d.wa_link, "_blank"); }
    else setNote("No phone saved for this supplier — print or share it yourself.");
  }

  function openReceive() {
    setReceiving(Object.fromEntries(doc.lines.filter(l => l.expected > 0)
      .map(l => [l.id, { quantity: String(l.expected), expiry_date: "", batch_no: "" }])));
    setPaid(""); setDue("");
  }

  async function receive() {
    const lines = Object.entries(receiving)
      .map(([line_id, v]) => ({ line_id: Number(line_id), quantity: Number(v.quantity) || 0,
                                expiry_date: v.expiry_date || null, batch_no: v.batch_no || null }))
      .filter(l => l.quantity > 0);
    const d = await act("receive", "receive", { lines, paid_now: paid === "" ? null : parseAmt(paid), due_date: due || null });
    if (d) { setReceiving(null); setNote("Received — added to stock and to the supplier's account."); }
  }

  if (err && !doc) return <div className="pos-error" style={{ margin: 24 }}>{err}</div>;
  if (!doc) return <div className="page-loading">Loading order…</div>;
  const open = ["draft", "sent", "part_received"].includes(doc.status);
  const arrivingTotal = receiving ? doc.lines.reduce((s, l) => s + (Number(receiving[l.id]?.quantity) || 0) * (l.unit_cost || 0), 0) : 0;

  return (
    <div className="receipt-shell">
      <div className="receipt-actions no-print" style={{ flexWrap: "wrap" }}>
        <button className="btn btn-ghost" onClick={() => navigate("/purchase-orders")}><ArrowLeft size={15} /> Orders</button>
        {["draft", "sent"].includes(doc.status) && (
          <button className="btn btn-ghost" onClick={() => navigate(`/purchase-orders/${id}/edit`)}><Pencil size={15} /> Edit</button>
        )}
        {open && <button className="btn btn-ghost" onClick={send} disabled={!!busy}><Send size={15} /> {doc.sent_at ? "Send again" : "Send to supplier"}</button>}
        {open && <button className="btn btn-primary" onClick={openReceive} disabled={!!busy}><PackageCheck size={15} /> Goods arrived</button>}
        <button className="btn btn-ghost" onClick={() => window.print()}><Printer size={15} /> Download / Print</button>
      </div>
      {note && <div className="no-print" style={{ fontSize: 13, color: "#166534", textAlign: "center" }}>{note}</div>}
      {err && <div className="modal-error no-print">{err}</div>}

      <div className={paperClass(doc)}>
        <PrintHeader doc={doc} title="PURCHASE ORDER" date={dateTimeStr(doc.created_at)} refText={doc.number}>
          <div className="receipt-muted" style={{ fontWeight: 700, marginTop: 4 }}>{doc.status_label}</div>
        </PrintHeader>
        {doc.supplier && (
          <div className="receipt-customer">
            <span className="receipt-label">Supplier</span>
            <span>{doc.supplier.name}</span>
            {doc.supplier.phone && <span className="receipt-muted">{doc.supplier.phone}</span>}
          </div>
        )}
        <table className="receipt-table" style={{ width: "100%" }}>
          <thead><tr><th>Item</th><th className="receipt-right">Qty</th><th className="receipt-right">Cost (₦)</th><th className="receipt-right">Total (₦)</th></tr></thead>
          <tbody>
            {doc.lines.map(l => (
              <tr key={l.id}>
                <td>{l.product}{l.unit ? ` (${l.unit})` : ""}
                  {(l.received > 0 || l.short > 0) && (
                    <div className="receipt-item-attrs">
                      <span>Received: {l.received}</span>
                      {l.expected > 0 && doc.status !== "closed" && <span>Still expected: {l.expected}</span>}
                      {l.short > 0 && <span>Never arrived: {l.short}</span>}
                    </div>
                  )}
                </td>
                <td className="receipt-right">{l.quantity}</td>
                <td className="receipt-right">{l.unit_cost != null ? fmtAmt(String(l.unit_cost)) : "—"}</td>
                <td className="receipt-right">{fmtAmt(String(l.total))}</td>
              </tr>
            ))}
          </tbody>
          <tfoot><tr className="receipt-total-row"><td colSpan={3}>Total</td><td className="receipt-right">{nairaFull(doc.total)}</td></tr></tfoot>
        </table>
        <div className="receipt-footer">
          {doc.expected_date && <div style={{ fontWeight: 700 }}>Please deliver by {dateStr(doc.expected_date)}</div>}
          {doc.note && <div className="receipt-muted" style={{ marginTop: 6 }}>{doc.note}</div>}
          {doc.close_reason && <div className="receipt-muted" style={{ marginTop: 6 }}>Closed: {doc.close_reason}</div>}
        </div>
      </div>

      {open && (
        <div className="no-print" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {doc.status === "part_received" && (
            <button className="btn btn-ghost" disabled={!!busy} onClick={() => {
              const reason = window.prompt("Stop expecting the rest? What never came stays on record. Reason (optional):", "");
              if (reason !== null) act("close", "close", { reason });
            }}><Lock size={15} /> Close order</button>
          )}
          {["draft", "sent"].includes(doc.status) && (
            <button className="btn btn-ghost" style={{ color: "#b91c1c" }} disabled={!!busy}
              onClick={() => window.confirm("Cancel this order?") && act("cancel", "cancel")}><Ban size={15} /> Cancel order</button>
          )}
        </div>
      )}

      {receiving && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setReceiving(null)}>
          <div className="modal" style={{ maxWidth: 560 }}>
            <div className="modal-header">
              <span className="modal-title">Goods arrived — {doc.number}</span>
              <button className="modal-close" onClick={() => setReceiving(null)}>×</button>
            </div>
            <div className="modal-body" style={{ display: "grid", gap: 10 }}>
              <div className="td-muted" style={{ fontSize: 13 }}>Enter how many of each came. They go into stock and onto {doc.supplier?.name}'s account.</div>
              {doc.lines.filter(l => receiving[l.id]).map(l => (
                <div key={l.id} style={{ borderBottom: "1px solid var(--border)", paddingBottom: 8 }}>
                  <strong>{l.product}</strong> <span className="td-muted">· {l.expected} expected</span>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6, marginTop: 4 }}>
                    <input inputMode="numeric" value={receiving[l.id].quantity} aria-label="Arrived"
                      onChange={e => setReceiving(r => ({ ...r, [l.id]: { ...r[l.id], quantity: e.target.value.replace(/\D/g, "") } }))} />
                    <input type="date" value={receiving[l.id].expiry_date} title="Expiry date (optional)"
                      onChange={e => setReceiving(r => ({ ...r, [l.id]: { ...r[l.id], expiry_date: e.target.value } }))} />
                    <input value={receiving[l.id].batch_no} placeholder="Batch (optional)" maxLength={60}
                      onChange={e => setReceiving(r => ({ ...r, [l.id]: { ...r[l.id], batch_no: e.target.value } }))} />
                  </div>
                </div>
              ))}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                <div>
                  <label className="form-label">Paid now (₦) <span className="text-subtle">— empty = all paid</span></label>
                  <input inputMode="numeric" value={paid} onChange={e => setPaid(fmtAmt(e.target.value))} placeholder={fmtAmt(String(arrivingTotal))} />
                </div>
                <div>
                  <label className="form-label">Balance due <span className="text-subtle">(if owing)</span></label>
                  <input type="date" value={due} onChange={e => setDue(e.target.value)} />
                </div>
              </div>
              <div style={{ fontSize: 13 }}>Arriving now: <strong>{nairaFull(arrivingTotal)}</strong></div>
              {err && <div className="modal-error">{err}</div>}
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={() => setReceiving(null)}>Cancel</button>
              <button className="btn btn-primary" onClick={receive} disabled={!!busy}>{busy === "receive" ? "Saving…" : "Add to stock"}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
