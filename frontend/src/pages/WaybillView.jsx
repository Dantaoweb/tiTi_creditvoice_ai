import { useState, useEffect } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { Printer, ArrowLeft, Share2, XCircle } from "lucide-react";
import { apiFetch, apiPost } from "../lib/api";
import { dateTimeStr } from "../lib/format";
import PrintHeader from "../components/PrintHeader";
import { paperClass } from "../lib/print";

const qtyLabel = (n, unit) => `${Number(n).toLocaleString()}${unit ? ` ${unit}` : ""}`;

/* The waybill / loading order the loaders and the driver take with the goods:
   what is on the truck (no prices), who is driving, where it's going, and
   lines to sign — issued by, driver, received by the customer. */
export default function WaybillView() {
  const { id } = useParams();
  const navigate = useNavigate();
  const justMade = useLocation().state?.justMade;
  const [doc, setDoc] = useState(null);
  const [err, setErr] = useState("");
  const [shareMsg, setShareMsg] = useState("");
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");
  const [cancelErr, setCancelErr] = useState("");

  function load() {
    apiFetch(`waybills/${id}`).then(setDoc).catch(e => setErr(e.message));
  }
  useEffect(load, [id]);

  if (err) return <div className="pos-error" style={{ margin: 24 }}>{err}</div>;
  if (!doc) return <div className="page-loading">Loading waybill…</div>;

  async function share() {
    try {
      if (navigator.share) await navigator.share({ title: `Waybill ${doc.number}`, text: doc.message });
      else {
        await navigator.clipboard.writeText(doc.message);
        setShareMsg("Copied — paste it into WhatsApp or anywhere.");
        setTimeout(() => setShareMsg(""), 3000);
      }
    } catch { /* cancelled */ }
  }

  async function cancel() {
    if (!reason.trim()) { setCancelErr("Say why — the reason is kept on the waybill."); return; }
    try {
      await apiPost(`waybills/${id}/cancel`, { reason: reason.trim() });
      setCancelling(false);
      load();
    } catch (e) { setCancelErr(e.message); }
  }

  const back = doc.transaction_id ? `/pos/receipt/${doc.transaction_id}`
    : doc.invoice_id ? `/invoices/${doc.invoice_id}` : "/deliveries";
  const sign = label => (
    <div style={{ flex: 1, minWidth: 140 }}>
      <div style={{ borderBottom: "1px solid #333", height: 36 }} />
      <div className="receipt-muted" style={{ fontSize: 12, marginTop: 4 }}>{label}</div>
    </div>
  );

  return (
    <div className="receipt-shell">
      <div className="receipt-actions no-print">
        <button className="btn btn-ghost" onClick={() => navigate(back)}>
          <ArrowLeft size={15} /> Back
        </button>
        {doc.can_cancel && !doc.cancelled_at && (
          <button className="btn btn-ghost" onClick={() => setCancelling(true)}>
            <XCircle size={15} /> Cancel waybill
          </button>
        )}
        <button className="btn btn-ghost" onClick={share}>
          <Share2 size={15} /> Share
        </button>
        <button className="btn btn-primary" onClick={() => window.print()}>
          <Printer size={15} /> Download / Print
        </button>
      </div>

      {justMade && !doc.cancelled_at && (
        <div className="no-print" style={{ textAlign: "center", margin: "0 0 10px", fontSize: 13, color: "#166534" }}>
          ✓ Waybill {doc.number} made.{" "}
          {justMade.sent ? `${doc.customer?.name || "The customer"} was told on WhatsApp.`
            : justMade.wa_link ? (
              <a href={justMade.wa_link} target="_blank" rel="noreferrer">Send the note from my WhatsApp</a>
            ) : ""}
        </div>
      )}
      {shareMsg && (
        <div className="no-print" style={{ textAlign: "center", margin: "0 0 8px", fontSize: 13, color: "#166534" }}>{shareMsg}</div>
      )}

      <div className={paperClass(doc)}>
        <PrintHeader doc={doc} title="WAYBILL / LOADING ORDER" date={dateTimeStr(doc.created_at)}
          refText={`${doc.number}${doc.ref ? ` · ${doc.ref}` : ""}`} />

        {doc.cancelled_at && (
          <div style={{ textAlign: "center", color: "#b91c1c", fontWeight: 700, margin: "8px 0" }}>
            CANCELLED{doc.cancel_reason ? ` — ${doc.cancel_reason}` : ""}
          </div>
        )}

        {doc.customer && (
          <div className="receipt-customer">
            <span className="receipt-label">Deliver to</span>
            <span>{doc.customer.name}</span>
            {doc.customer.phone && <span className="receipt-muted">{doc.customer.phone}</span>}
            {doc.address && <span className="receipt-muted" style={{ whiteSpace: "pre-line" }}>{doc.address}</span>}
          </div>
        )}

        <table className="receipt-table">
          <thead>
            <tr>
              <th style={{ width: 28 }}>✓</th>
              <th>Item</th>
              <th className="receipt-right">Qty</th>
            </tr>
          </thead>
          <tbody>
            {doc.lines.map((l, i) => (
              <tr key={i}>
                <td>☐</td>
                <td>{l.product}</td>
                <td className="receipt-right">{qtyLabel(l.quantity, l.unit)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {doc.still_to_deliver.length > 0 && (
          <div style={{ borderTop: "1px dashed var(--border)", marginTop: 8, paddingTop: 8, fontSize: 13 }}>
            <strong>Still to deliver after this trip:</strong>{" "}
            {doc.still_to_deliver.map(s => `${qtyLabel(s.quantity, s.unit)} ${s.product}`).join(", ")}
          </div>
        )}

        <div style={{ borderTop: "1px dashed var(--border)", marginTop: 8, paddingTop: 8, fontSize: 13, display: "grid", gap: 4 }}>
          {doc.driver_name && <div>Driver: <strong>{doc.driver_name}</strong>{doc.driver_phone ? ` · ${doc.driver_phone}` : ""}</div>}
          {!doc.driver_name && doc.driver_phone && <div>Driver's phone: {doc.driver_phone}</div>}
          {doc.vehicle && <div>Vehicle no.: <strong>{doc.vehicle}</strong></div>}
          {doc.loaders && <div>Loaders: {doc.loaders}</div>}
          {doc.note && <div>Note: {doc.note}</div>}
          {doc.issued_by && <div className="receipt-muted">Issued by: {doc.issued_by}</div>}
        </div>

        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 28 }}>
          {sign("Issued by (sign)")}
          {sign("Driver (sign)")}
          {sign("Received in good condition by (name & sign)")}
        </div>
        <div className="receipt-muted" style={{ fontSize: 11, marginTop: 14, textAlign: "center" }}>
          Check the goods before signing. Keep one copy; the driver brings one back signed.
        </div>
      </div>

      {cancelling && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setCancelling(false)}>
          <div className="modal">
            <div className="modal-header">
              <span className="modal-title">Cancel waybill {doc.number}</span>
              <button className="modal-close" onClick={() => setCancelling(false)}>×</button>
            </div>
            <div className="modal-body">
              <div style={{ fontSize: 13, marginBottom: 8 }}>
                The goods go back into the store and back on the customer's still-to-deliver list.
              </div>
              <label className="form-label">Why?</label>
              <input value={reason} maxLength={300} onChange={e => setReason(e.target.value)}
                placeholder="e.g. Truck broke down" style={{ width: "100%" }} autoFocus />
              {cancelErr && <div className="modal-error">{cancelErr}</div>}
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={() => setCancelling(false)}>Keep it</button>
              <button className="btn btn-primary" onClick={cancel}>Cancel waybill</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
