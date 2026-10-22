import { useState, useEffect } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { Printer, ArrowLeft, FileText, Send, Share2, RotateCcw, Truck } from "lucide-react";
import { apiFetch, apiPost } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import ReturnGoodsModal from "../components/ReturnGoodsModal";
import WaybillModal from "../components/WaybillModal";
import WaybillList from "../components/WaybillList";
import PrintHeader, { PrintBank } from "../components/PrintHeader";
import { paperClass } from "../lib/print";
import { nairaFull, dateTimeStr, dateStr, fmtAmt } from "../lib/format";

export default function Receipt() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [receipt, setReceipt] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [sending, setSending] = useState(false);
  const [sendErr, setSendErr] = useState("");
  const [shareMsg, setShareMsg] = useState("");
  const [returning, setReturning] = useState(false);
  const [waybill, setWaybill] = useState(false);
  const { user } = useAuth();

  function load() {
    apiFetch(`pos/receipt/${id}`)
      .then(setReceipt)
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false));
  }
  useEffect(load, [id]);

  // An older invoice — a number once put on a credit sale — can still be shown
  // as the invoice it was. New invoices are written on the Invoices page; a
  // sale already recorded is not turned into one.
  const invoiceMode = searchParams.get("doc") === "invoice";

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
  const discount  = receipt.discount ?? 0;          // taken off the whole sale
  // Debt carried from earlier sales, and everything owed as at this receipt —
  // "Balance" alone only covers this sale and hides the rest.
  const prevBalance = receipt.previous_balance ?? 0;
  const owedNow = receipt.total_owed_now ?? owed;
  // A credit note: money off a customer's account or handed back for goods
  // cancelled or returned after a sale (recorded at a negative amount).
  const cn = receipt.credit_note;
  const typeLabel = cn ? `Credit note ${cn.number}` : isPayment ? "Payment" : (isCredit ? "Credit Sale" : "Cash Sale");
  const canReturn = !!user?.full_access && !cn && !isPayment && receipt.total > 0;
  // A waybill / loading order for the loaders and driver — any sale with goods
  const canWaybill = !cn && !isPayment && receipt.total > 0 && !receipt.is_voided;

  // ── Invoice mode (older invoices only) ──────────────────────────────────────
  const isInvoice   = invoiceMode && !!receipt.invoice_number;
  const invoiceNo   = receipt.invoice_number ? `INV-${String(receipt.invoice_number).padStart(4, "0")}` : null;
  const dueStr = receipt.due_date
    ? new Date(receipt.due_date).toLocaleDateString("en-NG", { day: "numeric", month: "short", year: "numeric" })
    : null;

  const hasCustomerPhone = !!(receipt.customer && receipt.customer.phone);
  const sentAt = receipt.invoice_sent_at;

  // Part delivery on a line: what went out at the sale, each later waybill
  // (with its date), and what is still to come.
  function deliveryLines(it) {
    if (it.delivered_qty == null) return [];
    const L = [`Delivered now: ${it.delivered_qty ?? 0}`];
    (it.delivered_later || []).forEach(d => L.push(d.number
      ? `${d.number} · ${dateStr(d.date)}: ${d.quantity} delivered`
      : `Delivered later: ${d.quantity}`));
    L.push(it.still_to_deliver > 0 ? `Still to deliver: ${it.still_to_deliver}` : "All delivered ✓");
    return L;
  }

  // Plain-text version of this receipt/invoice for sharing (WhatsApp, etc.)
  function buildShareText() {
    const L = [];
    L.push((isInvoice ? "INVOICE — " : "") + bizName);
    const addr = receipt.branch_address || receipt.biz_address;
    if (addr) L.push(addr);
    if (isInvoice && invoiceNo) L.push(invoiceNo);
    else L.push(`Receipt #${receipt.receipt_number ?? receipt.id}`);   // per-business number, as printed
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
        deliveryLines(it).forEach(t => L.push(`   ${t}`));
      });
      L.push("--------------------");
      if (discount > 0) {
        L.push(`Subtotal: ${nairaFull(receipt.subtotal ?? receipt.total + discount)}`);
        L.push(`Discount: -${nairaFull(discount)}`);
      }
      L.push(`Total: ${nairaFull(receipt.total)}`);
      if (!isInvoice) L.push(`Paid: ${nairaFull(paid)}`);
      if (owed > 0) {
        L.push(isInvoice
          ? `Amount due${prevBalance > 0 ? " (this invoice)" : ""}: ${nairaFull(owed)}`
          : `Balance this sale: ${nairaFull(owed)}`);
      }
      else if (!isInvoice) L.push("Status: Paid in full");
      if (priorDebt > 0) {
        L.push(`Previous debt settled: ${nairaFull(priorDebt)}`);
        L.push(`Total received: ${nairaFull(receipt.grand_total_collected ?? (paid + priorDebt))}`);
      }
      if (prevBalance > 0) L.push(`Previous balance: ${nairaFull(prevBalance)}`);
      if (prevBalance > 0 || priorDebt > 0) {
        L.push(`${isInvoice ? "Total due now" : "Total owed now"}: ${nairaFull(owedNow)}`);
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
        {receipt.invoice_number && !isInvoice && (
          <button className="btn btn-ghost" onClick={() => setSearchParams({ doc: "invoice" })}>
            <FileText size={15} /> View as Invoice
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
        {canReturn && !isInvoice && (
          <button className="btn btn-ghost" onClick={() => setReturning(true)}>
            <RotateCcw size={15} /> Return goods
          </button>
        )}
        {canWaybill && !isInvoice && (
          <button className="btn btn-ghost" onClick={() => setWaybill(true)}>
            <Truck size={15} /> Waybill
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

      <div className={paperClass(receipt)}>
        <PrintHeader
          doc={{ ...receipt, biz_name: bizName }}
          title={isInvoice ? "INVOICE" : cn ? `CREDIT NOTE ${cn.number}` : (isPayment ? "Payment Receipt" : title)}
          date={dateTimeStr(receipt.created_at)}
          refText={isInvoice && invoiceNo ? invoiceNo : `Receipt #${receipt.receipt_number ?? receipt.id}`}
        />

        {receipt.customer && (
          <div className="receipt-customer">
            <span className="receipt-label">{isInvoice ? "Bill to" : custLabel}</span>
            <span>{receipt.customer.name}</span>
            {receipt.customer.phone && <span className="receipt-muted">{receipt.customer.phone}</span>}
          </div>
        )}

        {isInvoice && (
          <div className="receipt-customer" style={{ borderTop: "1px dashed var(--border)", marginTop: 8, paddingTop: 8 }}>
            <span className="receipt-label" style={{ fontWeight: 700 }}>
              {prevBalance > 0 ? "Amount Due (this invoice)" : "Amount Due"}
            </span>
            <span style={{ fontWeight: 700, color: owed > 0 ? "#b91c1c" : "#166534" }}>{nairaFull(owed)}</span>
            {/* Earlier debt belongs on the invoice too, or it understates what
                the customer owes the business. */}
            {prevBalance > 0 && (
              <>
                <span className="receipt-muted">Previous balance: {nairaFull(prevBalance)}</span>
                <span style={{ fontWeight: 700, color: owedNow > 0 ? "#b91c1c" : "#166534" }}>
                  Total due now: {nairaFull(owedNow)}
                </span>
              </>
            )}
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
                  {deliveryLines(it).length > 0 && (
                    <div className="receipt-item-attrs">
                      {deliveryLines(it).map((t, j) => (
                        <span key={j} style={{ fontWeight: j === deliveryLines(it).length - 1 ? 600 : undefined }}>{t}</span>
                      ))}
                    </div>
                  )}
                  {(it.cancelled_qty > 0 || it.returned_qty > 0) && (
                    <div className="receipt-item-attrs">
                      <span>
                        {it.cancelled_qty > 0 ? `Cancelled later: ${it.cancelled_qty}` : ""}
                        {it.cancelled_qty > 0 && it.returned_qty > 0 ? " · " : ""}
                        {it.returned_qty > 0 ? `Returned later: ${it.returned_qty}` : ""}
                      </span>
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
            {/* A discount off the whole sale, so the lines add up to the total. */}
            {discount > 0 && (
              <>
                <tr>
                  <td colSpan={3}>Subtotal</td>
                  <td className="receipt-right">{nairaFull(receipt.subtotal ?? receipt.total + discount)}</td>
                </tr>
                <tr>
                  <td colSpan={3}>Discount</td>
                  <td className="receipt-right">−{nairaFull(discount)}</td>
                </tr>
              </>
            )}
            <tr className="receipt-total-row">
              <td colSpan={3}>Total</td>
              <td className="receipt-right">{nairaFull(receipt.total)}</td>
            </tr>
            {cn && (
              <tr style={{ fontWeight: 700 }}>
                <td colSpan={3}>{cn.mode === "REFUND" ? "Refunded to customer" : "Taken off their balance"}</td>
                <td className="receipt-right">{nairaFull(Math.abs(receipt.total))}</td>
              </tr>
            )}
            {(isCredit || isCash) && !cn && (
              <>
                <tr>
                  <td colSpan={3}>Paid</td>
                  <td className="receipt-right">{nairaFull(paid)}</td>
                </tr>
                <tr style={{ fontWeight: 700, color: owed > 0 ? "#b91c1c" : "#166534" }}>
                  <td colSpan={3}>
                    {owed <= 0 ? "Paid in full"
                      : isInvoice ? (prevBalance > 0 ? "Amount due (this invoice)" : "Amount due")
                      : prevBalance > 0 ? "Balance this sale" : "Balance owed"}
                  </td>
                  <td className="receipt-right">{owed > 0 ? nairaFull(owed) : "✓"}</td>
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
            {prevBalance > 0 && (
              <tr>
                <td colSpan={3}>Previous balance</td>
                <td className="receipt-right">{nairaFull(prevBalance)}</td>
              </tr>
            )}
            {(prevBalance > 0 || priorDebt > 0) && (
              <tr className="receipt-total-row" style={{ color: owedNow > 0 ? "#b91c1c" : "#166534" }}>
                <td colSpan={3}>{isInvoice ? "Total due now" : "Total owed now"}</td>
                <td className="receipt-right">{owedNow > 0 ? nairaFull(owedNow) : "✓"}</td>
              </tr>
            )}
          </tfoot>
        </table>
        )}

        {/* What happened after this sale: undelivered goods cancelled, goods returned */}
        {(receipt.credit_notes || []).length > 0 && (
          <div style={{ borderTop: "1px dashed var(--border)", marginTop: 8, paddingTop: 8, fontSize: 13 }}>
            {receipt.credit_notes.map(n => (
              <div key={n.number} style={{ marginBottom: 6 }}>
                <strong>Credit note {n.number}</strong> · {n.lines.map(l => `${l.quantity}${l.unit ? ` ${l.unit}` : ""} ${l.product}`).join(", ")}{" "}
                {n.kind === "UNDELIVERED" ? "not delivered, cancelled" : "returned"} ·{" "}
                {nairaFull(n.amount)} {n.mode === "REFUND" ? "refunded" : "taken off balance"}
                <div className="receipt-muted" style={{ fontSize: 12 }}>{dateStr(n.created_at)} · Reason: {n.reason}</div>
              </div>
            ))}
          </div>
        )}
        {cn && (
          <div className="receipt-muted" style={{ borderTop: "1px dashed var(--border)", marginTop: 8, paddingTop: 8, fontSize: 12 }}>
            For receipt #{cn.sale_receipt} · {cn.kind === "UNDELIVERED" ? "goods not delivered, cancelled" : `goods returned${cn.restock === "DAMAGED" ? " (damaged)" : ""}`} · Reason: {cn.reason}
          </div>
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
          <PrintBank doc={receipt} />
          <div className="receipt-muted" style={{ marginTop: 12 }}>
            {isInvoice ? invoiceFooter : receiptFooter}
          </div>
        </div>
      </div>
      {!isPayment && !cn && <WaybillList query={`tx_id=${receipt.id}`} />}
      {returning && (
        <ReturnGoodsModal saleId={receipt.id} onClose={() => { setReturning(false); load(); }} />
      )}
      {waybill && <WaybillModal source={{ tx_id: receipt.id }} onClose={() => setWaybill(false)} />}
    </div>
  );
}
