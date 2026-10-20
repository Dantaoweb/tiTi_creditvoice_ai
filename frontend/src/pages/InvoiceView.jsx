import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Printer, Send, Share2, Pencil, PackageCheck, Banknote, Ban, Truck, Receipt as ReceiptIcon } from "lucide-react";
import WaybillModal from "../components/WaybillModal";
import WaybillList from "../components/WaybillList";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull, dateStr, fmtAmt, parseAmt } from "../lib/format";

const STATUS = {
  draft:     { label: "Draft",     bg: "rgba(100,116,139,0.14)", fg: "#475569" },
  sent:      { label: "Sent",      bg: "rgba(59,130,246,0.12)",  fg: "#2563eb" },
  // The older invoices (a number on a credit sale) take their status from the
  // customer's debt: "open" means still owed.
  open:      { label: "Open",      bg: "rgba(59,130,246,0.12)",  fg: "#2563eb" },
  overdue:   { label: "Overdue",   bg: "rgba(239,68,68,0.12)",   fg: "#b91c1c" },
  part_paid: { label: "Part paid", bg: "rgba(245,158,11,0.14)",  fg: "#b45309" },
  // Jobs: a quotation waiting for a yes; the deposit in, so work can start
  quote:        { label: "Quotation",    bg: "rgba(124,58,237,0.12)", fg: "#6d28d9" },
  deposit_paid: { label: "Deposit paid", bg: "rgba(13,148,136,0.14)", fg: "#0f766e" },
  paid:      { label: "Paid",      bg: "rgba(22,163,74,0.12)",   fg: "#166534" },
  cancelled: { label: "Cancelled", bg: "rgba(100,116,139,0.14)", fg: "#475569" },
};

export function InvoiceStatusBadge({ status }) {
  const s = STATUS[status] || STATUS.draft;
  return (
    <span style={{
      fontSize: 12, fontWeight: 700, padding: "2px 10px", borderRadius: 999,
      background: s.bg, color: s.fg, whiteSpace: "nowrap",
    }}>{s.label}</span>
  );
}

const qtyStr = q => (Number.isInteger(Number(q)) ? String(Number(q)) : String(q));

export default function InvoiceView() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [doc, setDoc] = useState(null);
  const [err, setErr] = useState("");
  const [actionErr, setActionErr] = useState("");
  const [busy, setBusy] = useState("");
  const [paying, setPaying] = useState(false);
  const [amount, setAmount] = useState("");
  const [shareMsg, setShareMsg] = useState("");
  const [waybill, setWaybill] = useState(false);

  useEffect(() => {
    apiFetch(`invoices/doc/${id}`).then(setDoc).catch(e => setErr(e.message));
  }, [id]);

  if (err) return <div className="pos-error" style={{ margin: 24 }}>{err}</div>;
  if (!doc) return <div className="page-loading">Loading invoice…</div>;

  const waiting   = ["draft", "sent", "overdue"].includes(doc.status);
  const isQuote   = doc.status === "quote";
  const someOwed  = doc.status === "part_paid" || doc.status === "deposit_paid";
  const hasDeposit = doc.deposit_amount > 0;
  const docName   = isQuote ? "quotation" : "invoice";
  const cancelled = doc.status === "cancelled";
  const delivered = !!doc.delivered_at;
  const partDelivered = !!doc.part_delivered;       // some went out on waybills
  const phone     = doc.customer?.phone;
  const custName  = doc.customer?.name || "the customer";
  const addr      = doc.branch_address || doc.biz_address;

  async function act(name, path, body = {}) {
    setBusy(name); setActionErr("");
    try {
      setDoc(await apiPost(`invoices/doc/${id}/${path}`, body));
      return true;
    } catch (e) {
      setActionErr(e.message);
      return false;
    } finally {
      setBusy("");
    }
  }

  function deliver() {
    if (!window.confirm(partDelivered
      ? "Mark the rest as delivered? Whatever hasn't gone out on a waybill yet will be taken out of stock."
      : "Mark as delivered? The items on this invoice will be taken out of stock.")) return;
    act("deliver", "deliver");
  }

  function cancel() {
    if (!window.confirm(`Cancel this ${docName}? It stays in the list, marked cancelled.`)) return;
    act("cancel", "cancel");
  }

  function accept() {
    if (!window.confirm("The customer agreed? This quotation becomes an invoice with its own INV number.")) return;
    act("accept", "accept");
  }

  function openPay() {
    // Starts empty: saving without an amount puts it all on the customer's
    // debt, never quietly records a full payment. "All of it" fills the total.
    setAmount("");
    setPaying(true);
    setActionErr("");
  }

  async function recordPayment(e) {
    e.preventDefault();
    if (await act("pay", "pay", { amount: Math.round(parseAmt(amount)) })) setPaying(false);
  }

  const payNum = Math.round(parseAmt(amount));
  const toDebt = Math.max(0, doc.total - payNum);

  function shareText() {
    const L = [(isQuote ? "QUOTATION — " : "INVOICE — ") + (doc.biz_name || "")];
    if (addr) L.push(addr);
    L.push(doc.ref);
    L.push(dateStr(doc.created_at));
    if (doc.customer?.name) L.push(`Bill to: ${doc.customer.name}`);
    L.push("--------------------");
    doc.items.forEach(it => L.push(`${it.name}${it.unit ? ` (${it.unit})` : ""}  x${qtyStr(it.qty)} = ${nairaFull(it.total)}`));
    L.push("--------------------");
    if (doc.discount > 0) {
      L.push(`Subtotal: ${nairaFull(doc.subtotal)}`);
      L.push(`Discount: -${nairaFull(doc.discount)}`);
    }
    if (doc.other_debt > 0) {
      L.push(`This invoice: ${nairaFull(doc.total)}`);
      L.push(`Previous balance: ${nairaFull(doc.other_debt)}`);
      L.push(`Total due now: ${nairaFull(doc.total_due_now)}`);
    } else {
      L.push(`${isQuote ? "Quoted total" : "Amount due"}: ${nairaFull(doc.total)}`);
    }
    if (hasDeposit) {
      L.push(`Deposit before work starts (${doc.deposit_percent}%): ${nairaFull(doc.deposit_amount)}`);
      L.push(`Balance on completion: ${nairaFull(doc.balance_on_completion)}`);
    }
    if (doc.due_date) L.push(`${hasDeposit ? "Completion / balance due" : "Due by"}: ${dateStr(doc.due_date)}`);
    if (doc.note) L.push(doc.note);
    L.push("--------------------");
    L.push(doc.footer);
    return L.join("\n");
  }

  async function share() {
    const text = shareText();
    try {
      if (navigator.share) {
        await navigator.share({ title: `${isQuote ? "Quotation" : "Invoice"} ${doc.ref}`, text });
      } else {
        await navigator.clipboard.writeText(text);
        setShareMsg("Copied — paste it into WhatsApp or anywhere.");
        setTimeout(() => setShareMsg(""), 3000);
      }
    } catch { /* share cancelled */ }
  }

  return (
    <div className="receipt-shell">
      <div className="receipt-actions no-print" style={{ flexWrap: "wrap" }}>
        <button className="btn btn-ghost" onClick={() => navigate("/invoices")}>
          <ArrowLeft size={15} /> Invoices
        </button>
        {(waiting || isQuote) && !delivered && !partDelivered && (
          <button className="btn btn-ghost" onClick={() => navigate(`/invoices/${id}/edit`)}>
            <Pencil size={15} /> Edit
          </button>
        )}
        {!cancelled && phone && (
          <button className="btn btn-ghost" onClick={() => act("send", "send")} disabled={!!busy}>
            <Send size={15} /> {busy === "send" ? "Sending…" : doc.sent_at ? "Resend" : "Send to customer"}
          </button>
        )}
        {!cancelled && (
          <button className="btn btn-ghost" onClick={share}><Share2 size={15} /> Share</button>
        )}
        <button className="btn btn-ghost" onClick={() => window.print()}>
          <Printer size={15} /> Download / Print
        </button>
      </div>

      {/* Where it stands, and what can happen next. */}
      <div className="invoice-state no-print">
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <InvoiceStatusBadge status={doc.status} />
          {delivered
            ? <span className="invoice-flag invoice-flag--done"><PackageCheck size={13} /> Delivered {dateStr(doc.delivered_at)}</span>
            : partDelivered ? <span className="invoice-flag"><PackageCheck size={13} /> Part delivered</span>
            : !cancelled && <span className="invoice-flag">Not delivered yet</span>}
          {doc.sent_at && <span className="td-muted" style={{ fontSize: 12 }}>Sent {dateStr(doc.sent_at)}</span>}
        </div>

        <p className="invoice-state__text">
          {cancelled && `This ${docName} was cancelled. Nothing was owed and no stock moved.`}
          {isQuote && `A quotation: nothing is owed yet. When ${custName} agrees, tap "Customer accepted" — it becomes an invoice${hasDeposit ? ` asking for the ${doc.deposit_percent}% deposit before work starts` : ""}.`}
          {waiting && hasDeposit && `Ask for the deposit of ${nairaFull(doc.deposit_amount)} (${doc.deposit_percent}%) before work starts; the balance of ${nairaFull(doc.balance_on_completion)} is paid on completion. `}
          {waiting && !delivered && !partDelivered && "Nothing is owed yet and no stock has moved. Record the payment when the customer pays; make a waybill or mark it delivered when the goods go out."}
          {waiting && partDelivered && "Some goods have gone out on waybills. Record the payment when the customer pays; make another waybill when the rest goes."}
          {waiting && delivered && "The goods are out of stock. Record the payment when the customer pays — anything unpaid becomes their debt."}
          {doc.status === "paid" && `Paid ${nairaFull(doc.amount_paid)} on ${dateStr(doc.paid_at)}.`}
          {doc.status === "deposit_paid" && `Deposit of ${nairaFull(doc.amount_paid)} paid on ${dateStr(doc.paid_at)} — work can start. The balance of ${nairaFull(doc.moved_to_debt)} is due on completion${doc.due_date ? ` (${dateStr(doc.due_date)})` : ""}; it is on ${custName}'s debts, collect it from Debts.`}
          {doc.status === "part_paid" && (doc.amount_paid > 0
            ? `${nairaFull(doc.amount_paid)} paid on ${dateStr(doc.paid_at)}. The other ${nairaFull(doc.moved_to_debt)} is now ${custName}'s debt — collect it from Debts.`
            : `Taken on credit on ${dateStr(doc.paid_at)}: the full ${nairaFull(doc.moved_to_debt)} is now ${custName}'s debt.`)}
          {(doc.status === "paid" || someOwed) && !delivered && " Mark it delivered when the goods go out."}
        </p>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {isQuote && (
            <button className="btn btn-primary" onClick={accept} disabled={!!busy}>
              <Banknote size={15} /> {busy === "accept" ? "Saving…" : "Customer accepted"}
            </button>
          )}
          {waiting && !paying && (
            <button className="btn btn-primary" onClick={openPay} disabled={!!busy}>
              <Banknote size={15} /> {hasDeposit ? "Record deposit / payment" : "Record payment"}
            </button>
          )}
          {!cancelled && !isQuote && (
            <button className="btn btn-ghost" onClick={() => setWaybill(true)} disabled={!!busy}>
              <Truck size={15} /> Waybill
            </button>
          )}
          {!cancelled && !delivered && !isQuote && (
            <button className="btn btn-ghost" onClick={deliver} disabled={!!busy}>
              <PackageCheck size={15} /> {busy === "deliver" ? "Saving…" : partDelivered ? "Mark the rest delivered" : "Mark delivered"}
            </button>
          )}
          {doc.transaction_id && (
            <button className="btn btn-ghost" onClick={() => navigate(`/pos/receipt/${doc.transaction_id}`)}>
              <ReceiptIcon size={15} /> View receipt
            </button>
          )}
          {(waiting || isQuote) && !delivered && !partDelivered && (
            <button className="btn btn-ghost" onClick={cancel} disabled={!!busy} style={{ color: "#b91c1c" }}>
              <Ban size={15} /> {busy === "cancel" ? "Cancelling…" : `Cancel ${docName}`}
            </button>
          )}
        </div>

        {paying && (
          <form className="invoice-pay" onSubmit={recordPayment}>
            <label className="form-label" htmlFor="inv-pay">Amount paid now</label>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <input id="inv-pay" inputMode="numeric" autoFocus value={amount}
                onChange={e => setAmount(fmtAmt(e.target.value))} style={{ width: 160 }} />
              {hasDeposit && (
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAmount(fmtAmt(doc.deposit_amount))}>
                  Deposit ({doc.deposit_percent}%)
                </button>
              )}
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAmount(fmtAmt(doc.total))}>All of it</button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAmount("0")}>Nothing yet</button>
            </div>
            <div className="invoice-pay__result">
              {payNum > doc.total
                ? <span style={{ color: "#b91c1c" }}>That is more than the invoice total of {nairaFull(doc.total)}.</span>
                : toDebt === 0
                  ? <span style={{ color: "#166534" }}>Paid in full — it becomes a cash sale with a receipt.</span>
                  : <span className="owe-line--due">
                      {nairaFull(toDebt)} will be added to {custName}'s debt
                      {doc.due_date ? `, due ${dateStr(doc.due_date)}` : ""}.
                    </span>}
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button type="submit" className="btn btn-primary" disabled={!!busy || payNum > doc.total}>
                {busy === "pay" ? "Saving…" : "Save payment"}
              </button>
              <button type="button" className="btn btn-ghost" onClick={() => setPaying(false)} disabled={!!busy}>Cancel</button>
            </div>
          </form>
        )}

        {actionErr && <div className="pos-error" style={{ margin: "10px 0 0" }}>{actionErr}</div>}
        {!phone && !cancelled && (
          <div className="td-muted" style={{ fontSize: 12, marginTop: 8 }}>
            No phone on file for this customer — print or share to send the invoice.
          </div>
        )}
        {shareMsg && <div style={{ fontSize: 13, color: "#166534", marginTop: 8 }}>{shareMsg}</div>}
      </div>

      <div className="receipt-paper">
        <div className="receipt-header">
          {doc.biz_logo && (
            <img src={doc.biz_logo} alt="" style={{ maxHeight: 64, maxWidth: 160, objectFit: "contain", margin: "0 auto 6px", display: "block" }} />
          )}
          <div className="receipt-brand">{doc.biz_name}</div>
          {doc.biz_phone && <div className="receipt-muted" style={{ fontSize: 12 }}>Tel: {doc.biz_phone}</div>}
          {addr && <div className="receipt-muted" style={{ fontSize: 12, whiteSpace: "pre-line" }}>{addr}</div>}
          {doc.branch_name && <div className="receipt-muted" style={{ fontSize: 12 }}>{doc.branch_name} branch</div>}
          <div className="receipt-sub">{isQuote ? "QUOTATION" : "INVOICE"}</div>
          <div className="receipt-date">{dateStr(doc.created_at)}</div>
          <div className="receipt-ref">{doc.ref}</div>
          {!isQuote && doc.quote_ref && <div className="receipt-muted" style={{ fontSize: 12 }}>From quotation {doc.quote_ref}</div>}
          {(cancelled || doc.status === "paid") && (
            <div className={`invoice-stamp${cancelled ? " invoice-stamp--void" : ""}`}>
              {cancelled ? "CANCELLED" : "PAID"}
            </div>
          )}
        </div>

        {doc.customer && (
          <div className="receipt-customer">
            <span className="receipt-label">{isQuote ? "Prepared for" : "Bill to"}</span>
            <span>{doc.customer.name}</span>
            {doc.customer.phone && <span className="receipt-muted">{doc.customer.phone}</span>}
          </div>
        )}

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
            {doc.items.map((it, i) => (
              <tr key={i}>
                <td>{it.name}{it.unit ? ` (${it.unit})` : ""}</td>
                <td className="receipt-right">{qtyStr(it.qty)}</td>
                <td className="receipt-right">{fmtAmt(it.unit_price)}</td>
                <td className="receipt-right">{fmtAmt(it.total)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            {doc.discount > 0 && (
              <>
                <tr>
                  <td colSpan={3}>Subtotal</td>
                  <td className="receipt-right">{nairaFull(doc.subtotal)}</td>
                </tr>
                <tr>
                  <td colSpan={3}>Discount</td>
                  <td className="receipt-right">−{nairaFull(doc.discount)}</td>
                </tr>
              </>
            )}
            <tr className="receipt-total-row">
              <td colSpan={3}>{isQuote ? "Quoted total" : waiting ? "Amount due" : "Total"}</td>
              <td className="receipt-right">{nairaFull(doc.total)}</td>
            </tr>
            {hasDeposit && (
              <>
                <tr style={{ fontWeight: 700 }}>
                  <td colSpan={3}>Deposit before work starts ({doc.deposit_percent}%)</td>
                  <td className="receipt-right">{nairaFull(doc.deposit_amount)}</td>
                </tr>
                <tr>
                  <td colSpan={3}>Balance on completion</td>
                  <td className="receipt-right">{nairaFull(doc.balance_on_completion)}</td>
                </tr>
              </>
            )}
            {waiting && doc.other_debt > 0 && (
              <>
                <tr>
                  <td colSpan={3}>Previous balance</td>
                  <td className="receipt-right">{nairaFull(doc.other_debt)}</td>
                </tr>
                <tr className="receipt-total-row" style={{ color: "#b91c1c" }}>
                  <td colSpan={3}>Total due now</td>
                  <td className="receipt-right">{nairaFull(doc.total_due_now)}</td>
                </tr>
              </>
            )}
            {(doc.status === "paid" || someOwed) && (
              <tr>
                <td colSpan={3}>{doc.status === "deposit_paid" ? "Deposit paid" : "Paid"}</td>
                <td className="receipt-right">{nairaFull(doc.amount_paid)}</td>
              </tr>
            )}
            {someOwed && (
              <tr style={{ fontWeight: 700, color: "#b91c1c" }}>
                <td colSpan={3}>{doc.status === "deposit_paid" ? "Balance due on completion" : "Balance owed"}</td>
                <td className="receipt-right">{nairaFull(doc.moved_to_debt)}</td>
              </tr>
            )}
          </tfoot>
        </table>

        <div className="receipt-footer">
          {(waiting || isQuote || doc.status === "deposit_paid") && doc.due_date && (
            <div style={{ fontWeight: 700 }}>
              {hasDeposit ? `Completion / balance due: ${dateStr(doc.due_date)}` : `Please pay by ${dateStr(doc.due_date)}`}
            </div>
          )}
          {isQuote && <div className="receipt-muted" style={{ marginTop: 6 }}>This is a quotation, not a bill. Work starts once it is accepted{hasDeposit ? " and the deposit is paid" : ""}.</div>}
          {doc.note && <div className="receipt-muted" style={{ marginTop: 6, whiteSpace: "pre-line" }}>{doc.note}</div>}
          {doc.created_by && <div className="receipt-muted" style={{ marginTop: 6 }}>Prepared by: {doc.created_by}</div>}
          <div className="receipt-muted" style={{ marginTop: 12 }}>{doc.footer}</div>
        </div>
      </div>
      {!isQuote && <WaybillList query={`invoice_id=${doc.id}`} />}
      {waybill && <WaybillModal source={{ invoice_id: doc.id }} onClose={() => setWaybill(false)} />}
    </div>
  );
}
