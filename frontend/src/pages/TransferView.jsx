import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Printer, Share2, XCircle, PackageCheck } from "lucide-react";
import { apiFetch, apiPost } from "../lib/api";
import { dateTimeStr } from "../lib/format";
import PrintHeader from "../components/PrintHeader";
import { paperClass } from "../lib/print";

const qtyLabel = (n, unit) => `${Number(n).toLocaleString()}${unit ? ` ${unit}` : ""}`;
const STATUS = { on_the_way: "ON THE WAY", received: "RECEIVED", cancelled: "CANCELLED" };

/* The transfer note (TR-0001) that goes with stock moved between branches:
   what was sent (no prices), from where to where, who carries it, and lines to
   sign. When the receiving branch confirms, this is where they say what came. */
export default function TransferView() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [doc, setDoc] = useState(null);
  const [err, setErr] = useState("");
  const [got, setGot] = useState({});          // line id → what arrived
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [actErr, setActErr] = useState("");
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");
  const [shareMsg, setShareMsg] = useState("");

  function load() {
    apiFetch(`transfers/${id}`).then(d => {
      setDoc(d);
      setGot(Object.fromEntries(d.lines.map(l => [l.id, String(l.sent)])));
    }).catch(e => setErr(e.message));
  }
  useEffect(load, [id]);

  if (err) return <div className="pos-error" style={{ margin: 24 }}>{err}</div>;
  if (!doc) return <div className="page-loading">Loading transfer…</div>;

  const text = [`${doc.number} — ${doc.from_branch} → ${doc.to_branch}`,
    ...doc.lines.map(l => `• ${qtyLabel(l.sent, l.unit)} ${l.product}`),
    doc.carried_by ? `Carried by: ${doc.carried_by}${doc.carrier_phone ? ` (${doc.carrier_phone})` : ""}` : ""]
    .filter(Boolean).join("\n");

  async function share() {
    try {
      if (navigator.share) await navigator.share({ title: `Transfer ${doc.number}`, text });
      else {
        await navigator.clipboard.writeText(text);
        setShareMsg("Copied — paste it into WhatsApp or anywhere.");
        setTimeout(() => setShareMsg(""), 3000);
      }
    } catch { /* cancelled */ }
  }

  async function receive() {
    const bad = doc.lines.find(l => got[l.id] === "" || Number(got[l.id]) < 0 || Number(got[l.id]) > l.sent);
    if (bad) { setActErr(`${bad.product}: enter what arrived, from 0 to ${bad.sent}.`); return; }
    setBusy(true); setActErr("");
    try {
      const d = await apiPost(`transfers/${id}/receive`, {
        received: Object.fromEntries(doc.lines.map(l => [l.id, Number(got[l.id])])), note: note.trim() || null });
      setDoc(d);
    } catch (e) { setActErr(e.message); }
    finally { setBusy(false); }
  }

  async function cancel() {
    if (!reason.trim()) { setActErr("Say why — the reason is kept on the transfer."); return; }
    try {
      setDoc(await apiPost(`transfers/${id}/cancel`, { reason: reason.trim() }));
      setCancelling(false); setActErr("");
    } catch (e) { setActErr(e.message); }
  }

  const sign = label => (
    <div style={{ flex: 1, minWidth: 140 }}>
      <div style={{ borderBottom: "1px solid #333", height: 36 }} />
      <div className="receipt-muted" style={{ fontSize: 12, marginTop: 4 }}>{label}</div>
    </div>
  );
  const shortLines = doc.lines.filter(l => l.received != null && l.received < l.sent);

  return (
    <div className="receipt-shell">
      <div className="receipt-actions no-print">
        <button className="btn btn-ghost" onClick={() => navigate("/inventory?transfers")}>
          <ArrowLeft size={15} /> Back
        </button>
        {doc.can_cancel && (
          <button className="btn btn-ghost" onClick={() => setCancelling(true)}>
            <XCircle size={15} /> Cancel transfer
          </button>
        )}
        <button className="btn btn-ghost" onClick={share}><Share2 size={15} /> Share</button>
        <button className="btn btn-primary" onClick={() => window.print()}>
          <Printer size={15} /> Download / Print
        </button>
      </div>
      {shareMsg && <div className="no-print" style={{ textAlign: "center", margin: "0 0 8px", fontSize: 13, color: "#166534" }}>{shareMsg}</div>}

      {doc.can_receive && (
        <div className="card no-print" style={{ maxWidth: 520, margin: "0 auto 12px", padding: 14, display: "grid", gap: 8 }}>
          <strong><PackageCheck size={15} style={{ verticalAlign: -2 }} /> Goods arrived at {doc.to_branch}?</strong>
          <span className="form-hint">Count what came and put the number for each. Anything less is recorded as missing on the way.</span>
          {doc.lines.map(l => (
            <label key={l.id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ flex: 1 }}>{l.product} <span className="td-muted">(sent {qtyLabel(l.sent, l.unit)})</span></span>
              <input type="number" min="0" max={l.sent} step="any" value={got[l.id] ?? ""} style={{ width: 90, textAlign: "right" }}
                onChange={e => setGot(g => ({ ...g, [l.id]: e.target.value }))} />
            </label>
          ))}
          <input value={note} maxLength={300} onChange={e => setNote(e.target.value)} placeholder="Note (optional), e.g. 2 bags torn" />
          {actErr && <div className="modal-error">{actErr}</div>}
          <div><button className="btn btn-primary" disabled={busy} onClick={receive}>{busy ? "Saving…" : "Received"}</button></div>
        </div>
      )}

      <div className={paperClass(doc)}>
        <PrintHeader doc={doc} title="STOCK TRANSFER" date={dateTimeStr(doc.created_at)} refText={doc.number} />
        <div style={{ textAlign: "center", fontWeight: 700, margin: "6px 0", color: doc.status === "cancelled" ? "#b91c1c" : undefined }}>
          {STATUS[doc.status] || doc.status}{doc.status === "cancelled" && doc.receive_note ? ` — ${doc.receive_note}` : ""}
        </div>
        <div className="receipt-customer">
          <span className="receipt-label">From</span><span>{doc.from_branch}</span>
          <span className="receipt-label" style={{ marginTop: 4 }}>To</span><span>{doc.to_branch}</span>
        </div>

        <table className="receipt-table">
          <thead>
            <tr><th style={{ width: 28 }}>✓</th><th>Item</th><th className="receipt-right">Sent</th>
              {doc.status === "received" && <th className="receipt-right">Arrived</th>}</tr>
          </thead>
          <tbody>
            {doc.lines.map(l => (
              <tr key={l.id}>
                <td>☐</td><td>{l.product}</td>
                <td className="receipt-right">{qtyLabel(l.sent, l.unit)}</td>
                {doc.status === "received" && (
                  <td className="receipt-right" style={l.received < l.sent ? { color: "#b91c1c", fontWeight: 700 } : undefined}>
                    {qtyLabel(l.received, l.unit)}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>

        {shortLines.length > 0 && (
          <div style={{ borderTop: "1px dashed var(--border)", marginTop: 8, paddingTop: 8, fontSize: 13, color: "#b91c1c" }}>
            <strong>Missing on the way:</strong>{" "}
            {shortLines.map(l => `${qtyLabel(l.sent - l.received, l.unit)} ${l.product}`).join(", ")}
          </div>
        )}

        <div style={{ borderTop: "1px dashed var(--border)", marginTop: 8, paddingTop: 8, fontSize: 13, display: "grid", gap: 4 }}>
          {doc.carried_by && <div>Carried by: <strong>{doc.carried_by}</strong>{doc.carrier_phone ? ` · ${doc.carrier_phone}` : ""}</div>}
          {doc.note && <div>Note: {doc.note}</div>}
          {doc.issued_by && <div className="receipt-muted">Sent by: {doc.issued_by}</div>}
          {doc.status === "received" && (
            <div className="receipt-muted">
              Received{doc.received_by ? ` by ${doc.received_by}` : ""}{doc.received_at ? ` · ${dateTimeStr(doc.received_at)}` : ""}
              {doc.receive_note ? ` — ${doc.receive_note}` : ""}
            </div>
          )}
        </div>

        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 28 }}>
          {sign(`Sent by — ${doc.from_branch} (sign)`)}
          {sign("Carried by (sign)")}
          {sign(`Received by — ${doc.to_branch} (name & sign)`)}
        </div>
        <div className="receipt-muted" style={{ fontSize: 11, marginTop: 14, textAlign: "center" }}>
          Count the goods before signing. Keep one copy; the carrier brings one back signed.
        </div>
      </div>

      {cancelling && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setCancelling(false)}>
          <div className="modal">
            <div className="modal-header">
              <span className="modal-title">Cancel transfer {doc.number}</span>
              <button className="modal-close" onClick={() => setCancelling(false)}>×</button>
            </div>
            <div className="modal-body">
              <div style={{ fontSize: 13, marginBottom: 8 }}>The goods go back into {doc.from_branch}'s stock.</div>
              <label className="form-label">Why?</label>
              <input value={reason} maxLength={300} onChange={e => setReason(e.target.value)}
                placeholder="e.g. The bus didn't come" style={{ width: "100%" }} autoFocus />
              {actErr && <div className="modal-error">{actErr}</div>}
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={() => setCancelling(false)}>Keep it</button>
              <button className="btn btn-primary" onClick={cancel}>Cancel transfer</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
