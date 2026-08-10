import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Printer, ArrowLeft, Share2 } from "lucide-react";
import { apiFetch } from "../lib/api";
import { nairaFull, dateTimeStr, dateStr, fmtAmt } from "../lib/format";

// Supplier-side receipt (stock received or supplier payment), styled to match
// the sale receipt (same receipt-* classes).
export default function SupplierReceipt() {
  const { kind, id } = useParams();
  const navigate = useNavigate();
  const [r, setR] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [shareMsg, setShareMsg] = useState("");

  useEffect(() => {
    apiFetch(`suppliers/receipt/${kind}/${id}`)
      .then(setR)
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false));
  }, [kind, id]);

  if (loading) return <div className="page-loading">Loading receipt…</div>;
  if (err || !r) return <div className="pos-error" style={{ margin: 24 }}>{err || "Receipt not found."}</div>;

  const isPayment = r.kind === "payment";
  const owed = r.balance ?? 0;

  function buildShareText() {
    const L = [];
    L.push(r.biz_name);
    if (r.biz_phone) L.push(`Tel: ${r.biz_phone}`);
    if (r.biz_address) L.push(r.biz_address);
    L.push((r.title || "Receipt").toUpperCase());
    L.push(dateTimeStr(r.created_at));
    L.push(`Ref #${r.id}`);
    L.push(`Supplier: ${r.supplier?.name || "—"}`);
    L.push("--------------------");
    if (isPayment) {
      L.push(`Amount paid: ${nairaFull(r.amount)}`);
      L.push(`Balance: ${nairaFull(owed)}`);
    } else {
      (r.items || []).forEach(it => L.push(`${it.product}${it.unit ? ` (${it.unit})` : ""}  x${it.qty} = ${nairaFull(it.total)}`));
      L.push("--------------------");
      L.push(`Total: ${nairaFull(r.total)}`);
      L.push(`Paid: ${nairaFull(r.paid)}`);
      if (owed > 0) L.push(`Balance: ${nairaFull(owed)}`);
    }
    return L.join("\n");
  }

  async function handleShare() {
    const text = buildShareText();
    try {
      if (navigator.share) await navigator.share({ title: `${r.title} — ${r.biz_name}`, text });
      else { await navigator.clipboard.writeText(text); setShareMsg("Copied — paste it into WhatsApp or anywhere."); setTimeout(() => setShareMsg(""), 3000); }
    } catch { /* cancelled */ }
  }

  return (
    <div className="receipt-shell">
      <div className="receipt-actions no-print">
        <button className="btn btn-ghost" onClick={() => navigate("/receipts")}>
          <ArrowLeft size={15} /> Receipts
        </button>
        <button className="btn btn-ghost" onClick={handleShare}>
          <Share2 size={15} /> Share
        </button>
        <button className="btn btn-primary" onClick={() => window.print()}>
          <Printer size={15} /> Download / Print
        </button>
      </div>

      {shareMsg && (
        <div className="no-print" style={{ textAlign: "center", margin: "0 0 8px", fontSize: 13, color: "#166534" }}>{shareMsg}</div>
      )}

      <div className="receipt-paper">
        <div className="receipt-header">
          <div className="receipt-brand">{r.biz_name}</div>
          {r.biz_phone && <div className="receipt-muted" style={{ fontSize: 12 }}>Tel: {r.biz_phone}</div>}
          {r.biz_address && <div className="receipt-muted" style={{ fontSize: 12, whiteSpace: "pre-line" }}>{r.biz_address}</div>}
          <div className="receipt-sub">{r.title}</div>
          <div className="receipt-date">{dateTimeStr(r.created_at)}</div>
          <div className="receipt-ref">Ref #{r.id}</div>
        </div>

        <div className="receipt-customer">
          <span className="receipt-label">Supplier</span>
          <span>{r.supplier?.name || "—"}</span>
          {r.supplier?.phone && <span className="receipt-muted">{r.supplier.phone}</span>}
        </div>

        {isPayment ? (
          <div style={{ margin: "16px 0" }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 700, fontSize: "1.05rem" }}>
              <span>Amount Paid</span><span>{nairaFull(r.amount)}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8, fontWeight: 700, color: owed > 0 ? "#b91c1c" : "#166534" }}>
              <span>Balance owed</span><span>{nairaFull(owed)}</span>
            </div>
            {r.note && <div className="receipt-muted" style={{ marginTop: 10, fontSize: 12 }}>Note: {r.note}</div>}
          </div>
        ) : (
          <table className="receipt-table">
            <thead>
              <tr><th>Item</th><th className="receipt-right">Qty</th><th className="receipt-right">Cost (₦)</th><th className="receipt-right">Total (₦)</th></tr>
            </thead>
            <tbody>
              {(r.items || []).map((it, i) => (
                <tr key={i}>
                  <td>{it.product}{it.unit ? ` (${it.unit})` : ""}</td>
                  <td className="receipt-right">{it.qty}</td>
                  <td className="receipt-right">{fmtAmt(it.unit_price)}</td>
                  <td className="receipt-right">{fmtAmt(it.total)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="receipt-total-row"><td colSpan={3}>Total</td><td className="receipt-right">{nairaFull(r.total)}</td></tr>
              <tr><td colSpan={3}>Paid</td><td className="receipt-right">{nairaFull(r.paid)}</td></tr>
              <tr style={{ fontWeight: 700, color: owed > 0 ? "#b91c1c" : "#166534" }}>
                <td colSpan={3}>Balance owed</td><td className="receipt-right">{nairaFull(owed)}</td>
              </tr>
            </tfoot>
          </table>
        )}

        <div className="receipt-footer">
          <div className="receipt-type-badge">{isPayment ? "Supplier Payment" : "Stock Received"}</div>
          {!isPayment && r.due_date && (
            <div className="receipt-muted" style={{ marginTop: 4 }}>Payment due: {dateStr(r.due_date)}</div>
          )}
          {r.recorded_by && <div className="receipt-muted">Recorded by: {r.recorded_by}</div>}
          <div className="receipt-muted" style={{ marginTop: 12 }}>Keep this receipt for your records.</div>
        </div>
      </div>
    </div>
  );
}
