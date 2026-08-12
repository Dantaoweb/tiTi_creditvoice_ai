import { useState, useEffect } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { Printer, ArrowLeft, FileText, Send, Share2 } from "lucide-react";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull, dateTimeStr, dateStr, fmtAmt } from "../lib/format";

export default function Receipt() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [receipt, setReceipt] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [issuing, setIssuing] = useState(false);
  const [sending, setSending] = useState(false);
  const [sendErr, setSendErr] = useState("");
  const [shareMsg, setShareMsg] = useState("");

  useEffect(() => {
    apiFetch(`pos/receipt/${id}`)
      .then(setReceipt)
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  // Arriving directly in invoice mode (e.g. from a customer's history) for a
  // credit sale with no number yet: assign it so the document shows INV-xxxx.
  const invoiceMode = searchParams.get("doc") === "invoice";
  useEffect(() => {
    if (!receipt || issuing) return;
    const owedAmt = receipt.balance_owed ?? 0;
    const canInvoice = receipt.type === "BUY" && owedAmt > 0;
    if (invoiceMode && canInvoice && !receipt.invoice_number) {
      setIssuing(true);
      apiPost(`invoices/${id}/issue`, {})
        .then(setReceipt)
        .catch(() => {})
        .finally(() => setIssuing(false));
    }
  }, [receipt, invoiceMode, id, issuing]);

  if (loading) return <div className="page-loading">Loading receipt…</div>;
  if (err || !receipt) return <div className="pos-error" style={{ margin: 24 }}>{err || "Receipt not found."}</div>;

  const config = receipt.config || {};
  const title       = config.title        || "Receipt";
  const custLabel   = config.customer_label || "Customer";
  // An invoice requests payment, so the receipt footer ("Keep this receipt for
  // reference.") reads wrong on it — use the invoice wording instead.
  const receiptFooter = config.footer || "Thank you for your business.";
  const invoiceFooter = config.invoice_footer || "Please settle this invoice by the due date. Thank you.";
  const bizName     = receipt.biz_name    || "CreditVoice";

  const isCash    = receipt.type === "SALE";
  const isCredit  = receipt.type === "BUY";
  const isPayment = receipt.type === "PAY";
  const paid      = receipt.paid ?? receipt.total;
  const owed      = receipt.balance_owed ?? 0;
  const priorDebt = receipt.prior_debt_paid ?? 0;   // old debt cleared in this checkout
  const typeLabel = isPayment ? "Payment" : (isCredit ? "Credit Sale" : "Cash Sale");

  // ── Invoice mode ────────────────────────────────────────────────────────────
  // The same document can be shown as an invoice ("amount due") for a credit
  // sale. A sale is invoiceable when the customer owes on it.
  const isInvoice   = invoiceMode;
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

  const hasCustomerPhone = !!(receipt.customer && receipt.customer.phone);
  const sentAt = receipt.invoice_sent_at;

  // Plain-text version of this receipt/invoice for sharing (WhatsApp, etc.)
  function buildShareText() {
    const L = [];
    L.push((isInvoice ? "INVOICE — " : "") + bizName);
    const addr = receipt.branch_address || receipt.biz_address;
    if (addr) L.push(addr);
    if (isInvoice && invoiceNo) L.push(invoiceNo);
    else L.push(`Receipt #${receipt.id}`);
    L.push(dateTimeStr(receipt.created_at));
    if (receipt.customer?.name) L.push(`${isInvoice ? "Bill to" : custLabel}: ${receipt.customer.name}`);
    L.push("--------------------");
    if (isPayment) {
      L.push(`Amount paid: ${nairaFull(receipt.paid)}`);
      L.push(`Balance: ${nairaFull(owed)}`);
    } else {
      (receipt.items || []).forEach(it => {
        L.push(`${it.product}${it.unit ? ` (${it.unit})` : ""}  x${it.qty} = ${nairaFull(it.total)}`);
        (it.attributes || []).forEach(a => L.push(`   ${a.label}: ${a.value}`));
      });
      L.push("--------------------");
      L.push(`Total: ${nairaFull(receipt.total)}`);
      if (owed > 0) L.push(`${isInvoice ? "Amount due" : "Balance"}: ${nairaFull(owed)}`);
      if (priorDebt > 0) {
        L.push(`Previous debt settled: ${nairaFull(priorDebt)}`);
        L.push(`Total received: ${nairaFull(receipt.grand_total_collected ?? (paid + priorDebt))}`);
      }
    }
    L.push("--------------------");
    L.push(isInvoice ? invoiceFooter : receiptFooter);
    return L.join("\n");
  }

  async function handleShare() {
    const text = buildShareText();
    const title = `${isInvoice ? "Invoice" : "Receipt"} — ${bizName}`;
    try {
      if (navigator.share) {
        await navigator.share({ title, text });
      } else {
        await navigator.clipboard.writeText(text);
        setShareMsg("Copied — paste it into WhatsApp or anywhere.");
        setTimeout(() => setShareMsg(""), 3000);
      }
    } catch { /* user cancelled share — ignore */ }
  }

  async function sendInvoice() {
    setSending(true); setSendErr("");
    try {
      const res = await apiPost(`invoices/${id}/send`, {});
      setReceipt(r => ({ ...r, invoice_sent_at: res.sent_at, invoice_number: res.invoice_number }));
    } catch (e) {
      setSendErr(e.message);
    } finally {
      setSending(false);
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
        {isInvoice && hasCustomerPhone && (
          <button className="btn btn-ghost" onClick={sendInvoice} disabled={sending}>
            <Send size={15} /> {sending ? "Sending…" : (sentAt ? "Resend to customer" : "Send to customer")}
          </button>
        )}
        <button className="btn btn-ghost" onClick={handleShare}>
          <Share2 size={15} /> Share
        </button>
        <button className="btn btn-primary" onClick={() => window.print()}>
          <Printer size={15} /> Download / Print
        </button>
      </div>

      {shareMsg && (
        <div className="no-print" style={{ textAlign: "center", margin: "0 0 8px", fontSize: 13, color: "#166534" }}>
          {shareMsg}
        </div>
      )}

      {isInvoice && (sentAt || sendErr || !hasCustomerPhone) && (
        <div className="no-print" style={{ textAlign: "center", margin: "0 0 10px", fontSize: 13 }}>
          {sendErr
            ? <span style={{ color: "#b91c1c" }}>{sendErr}</span>
            : sentAt
              ? <span style={{ color: "#166534" }}>Sent to customer on {dateStr(sentAt)}.</span>
              : <span style={{ color: "var(--text-muted)" }}>No phone on file — print or download to share this invoice.</span>}
        </div>
      )}

      <div className="receipt-paper">
        <div className="receipt-header">
          <div className="receipt-brand">{bizName}</div>
          {receipt.biz_phone && (
            <div className="receipt-muted" style={{ fontSize: 12 }}>Tel: {receipt.biz_phone}</div>
          )}
          {(receipt.branch_address || receipt.biz_address) && (
            <div className="receipt-muted" style={{ fontSize: 12, whiteSpace: "pre-line" }}>
              {receipt.branch_address || receipt.biz_address}
            </div>
          )}
          {receipt.branch_name && (
            <div className="receipt-muted" style={{ fontSize: 12 }}>{receipt.branch_name} branch</div>
          )}
          <div className="receipt-sub">{isInvoice ? "INVOICE" : (isPayment ? "Payment Receipt" : title)}</div>
          <div className="receipt-date">{dateTimeStr(receipt.created_at)}</div>
          <div className="receipt-ref">{isInvoice && invoiceNo ? invoiceNo : `Receipt #${receipt.receipt_number ?? receipt.id}`}</div>
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
                <td>
                  {it.product}{it.unit ? ` (${it.unit})` : ""}
                  {(it.attributes || []).length > 0 && (
                    <div className="receipt-item-attrs">
                      {it.attributes.map((a, j) => (
                        <span key={j}>{a.label}: {a.value}</span>
                      ))}
                    </div>
                  )}
                </td>
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
            {priorDebt > 0 && (
              <>
                <tr>
                  <td colSpan={3}>Previous debt settled</td>
                  <td className="receipt-right">{nairaFull(priorDebt)}</td>
                </tr>
                <tr className="receipt-total-row">
                  <td colSpan={3}>Total received</td>
                  <td className="receipt-right">{nairaFull(receipt.grand_total_collected ?? (paid + priorDebt))}</td>
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
            {isInvoice ? invoiceFooter : receiptFooter}
          </div>
        </div>
      </div>
    </div>
  );
}
