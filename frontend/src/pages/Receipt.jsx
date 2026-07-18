import { useState, useEffect } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { Printer, ArrowLeft, FileText } from "lucide-react";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull, dateTimeStr, fmtAmt } from "../lib/format";

export default function Receipt() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [receipt, setReceipt] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [issuing, setIssuing] = useState(false);

  useEffect(() => {
    apiFetch(`pos/receipt/${id}`)
      .then(setReceipt)
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="page-loading">Loading receipt…</div>;
  if (err || !receipt) return <div className="pos-error" style={{ margin: 24 }}>{err || "Receipt not found."}</div>;

  const config = receipt.config || {};
  const title       = config.title        || "Receipt";
  const custLabel   = config.customer_label || "Customer";
  const footer      = config.footer       || "Thank you for your business.";
  const bizName     = receipt.biz_name    || "CreditVoice";

  const isCash    = receipt.type === "SALE";
  const isCredit  = receipt.type === "BUY";
  const isPayment = receipt.type === "PAY";
  const paid      = receipt.paid ?? receipt.total;
  const owed      = receipt.balance_owed ?? 0;
  const typeLabel = isPayment ? "Payment" : (isCredit ? "Credit Sale" : "Cash Sale");

  // ── Invoice mode ────────────────────────────────────────────────────────────
  // The same document can be shown as an invoice ("amount due") for a credit
  // sale. A sale is invoiceable when the customer owes on it.
  const isInvoice   = searchParams.get("doc") === "invoice";
  const invoiceable = isCredit && owed > 0;
  const invoiceNo   = receipt.invoice_number ? `INV-${String(receipt.invoice_number).padStart(4, "0")}` : null;
  const dueStr = receipt.due_date
    ? new Date(receipt.due_date).toLocaleDateString("en-NG", { day: "numeric", month: "short", year: "numeric" })
    : null;

  async function viewAsInvoice() {
    setIssuing(true);
    try {
      // Assign the invoice number if this sale doesn't have one yet.
      const updated = receipt.invoice_number
        ? receipt
        : await apiPost(`invoices/${id}/issue`, {});
      setReceipt(updated);
      setSearchParams({ doc: "invoice" });
    } catch (e) {
      setErr(e.message);
    } finally {
      setIssuing(false);
    }
  }

  return (
    <div className="receipt-shell">
      <div className="receipt-actions no-print">
        <button className="btn btn-ghost" onClick={() => navigate("/pos")}>
          <ArrowLeft size={15} /> New Sale
        </button>
        {invoiceable && !isInvoice && (
          <button className="btn btn-ghost" onClick={viewAsInvoice} disabled={issuing}>
            <FileText size={15} /> {issuing ? "Preparing…" : "View as Invoice"}
          </button>
        )}
        {isInvoice && (
          <button className="btn btn-ghost" onClick={() => setSearchParams({})}>
            <FileText size={15} /> View as Receipt
          </button>
        )}
        <button className="btn btn-primary" onClick={() => window.print()}>
          <Printer size={15} /> Print
        </button>
      </div>

      <div className="receipt-paper">
        <div className="receipt-header">
          <div className="receipt-brand">{bizName}</div>
          <div className="receipt-sub">{isInvoice ? "INVOICE" : (isPayment ? "Payment Receipt" : title)}</div>
          <div className="receipt-date">{dateTimeStr(receipt.created_at)}</div>
          <div className="receipt-ref">{isInvoice && invoiceNo ? invoiceNo : `Receipt #${receipt.id}`}</div>
        </div>

        {receipt.customer && (
          <div className="receipt-customer">
            <span className="receipt-label">{isInvoice ? "Bill to" : custLabel}</span>
            <span>{receipt.customer.name}</span>
            {receipt.customer.phone && <span className="receipt-muted">{receipt.customer.phone}</span>}
          </div>
        )}

        {isInvoice && (
          <div className="receipt-customer" style={{ borderTop: "1px dashed var(--border)", marginTop: 8, paddingTop: 8 }}>
            <span className="receipt-label" style={{ fontWeight: 700 }}>Amount Due</span>
            <span style={{ fontWeight: 700, color: owed > 0 ? "#b91c1c" : "#166534" }}>{nairaFull(owed)}</span>
            {dueStr && <span className="receipt-muted">Due by {dueStr}</span>}
          </div>
        )}

        {isPayment ? (
          <div style={{ margin: "16px 0" }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 700, fontSize: "1.05rem" }}>
              <span>Amount Paid</span>
              <span>{nairaFull(receipt.paid)}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8, fontWeight: 700, color: owed > 0 ? "#b91c1c" : "#166534" }}>
              <span>Balance</span>
              <span>{nairaFull(owed)}</span>
            </div>
            {receipt.note && receipt.note !== "Payment" && (
              <div className="receipt-muted" style={{ marginTop: 10, fontSize: 12 }}>Note: {receipt.note}</div>
            )}
          </div>
        ) : (
        <table className="receipt-table">
          <thead>
            <tr>
              <th>Item</th>
              <th className="receipt-right">Qty</th>
              <th className="receipt-right">Price (₦)</th>
              <th className="receipt-right">Total (₦)</th>
            </tr>
          </thead>
          <tbody>
            {receipt.items.map((it, i) => (
              <tr key={i}>
                <td>{it.product}{it.unit ? ` (${it.unit})` : ""}</td>
                <td className="receipt-right">{it.qty}</td>
                <td className="receipt-right">{fmtAmt(it.unit_price)}</td>
                <td className="receipt-right">{fmtAmt(it.total)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="receipt-total-row">
              <td colSpan={3}>Total</td>
              <td className="receipt-right">{nairaFull(receipt.total)}</td>
            </tr>
            {isCredit && (
              <>
                <tr>
                  <td colSpan={3}>Paid</td>
                  <td className="receipt-right">{nairaFull(paid)}</td>
                </tr>
                <tr style={{ fontWeight: 700, color: owed > 0 ? "#b91c1c" : "#166534" }}>
                  <td colSpan={3}>Balance owed</td>
                  <td className="receipt-right">{nairaFull(owed)}</td>
                </tr>
              </>
            )}
          </tfoot>
        </table>
        )}

        <div className="receipt-footer">
          <div className="receipt-type-badge">{typeLabel}</div>
          {isCredit && receipt.due_date && (
            <div className="receipt-muted" style={{ marginTop: 4 }}>
              Payment due: {new Date(receipt.due_date).toLocaleDateString("en-NG", { day: "numeric", month: "short", year: "numeric" })}
            </div>
          )}
          {receipt.service_date && (
            <div className="receipt-muted" style={{ marginTop: 4 }}>
              Deliver / ready by: {new Date(receipt.service_date).toLocaleDateString("en-NG", { day: "numeric", month: "short", year: "numeric" })}
            </div>
          )}
          {receipt.recorded_by && (
            <div className="receipt-muted">Served by: {receipt.recorded_by}</div>
          )}
          <div className="receipt-muted" style={{ marginTop: 12 }}>
            {footer}
          </div>
        </div>
      </div>
    </div>
  );
}
