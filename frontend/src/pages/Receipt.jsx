import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Printer, ArrowLeft } from "lucide-react";
import { apiFetch } from "../lib/api";
import { nairaFull, dateTimeStr } from "../lib/format";

export default function Receipt() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [receipt, setReceipt] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

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
  const paid      = receipt.paid ?? receipt.total;
  const owed      = receipt.balance_owed ?? 0;
  const typeLabel = isCredit ? "Credit Sale" : "Cash Sale";

  return (
    <div className="receipt-shell">
      <div className="receipt-actions no-print">
        <button className="btn btn-ghost" onClick={() => navigate("/pos")}>
          <ArrowLeft size={15} /> New Sale
        </button>
        <button className="btn btn-primary" onClick={() => window.print()}>
          <Printer size={15} /> Print
        </button>
      </div>

      <div className="receipt-paper">
        <div className="receipt-header">
          <div className="receipt-brand">{bizName}</div>
          <div className="receipt-sub">{title}</div>
          <div className="receipt-date">{dateTimeStr(receipt.created_at)}</div>
          <div className="receipt-ref">Receipt #{receipt.id}</div>
        </div>

        {receipt.customer && (
          <div className="receipt-customer">
            <span className="receipt-label">{custLabel}</span>
            <span>{receipt.customer.name}</span>
            {receipt.customer.phone && <span className="receipt-muted">{receipt.customer.phone}</span>}
          </div>
        )}

        <table className="receipt-table">
          <thead>
            <tr>
              <th>Item</th>
              <th className="receipt-right">Qty</th>
              <th className="receipt-right">Price</th>
              <th className="receipt-right">Total</th>
            </tr>
          </thead>
          <tbody>
            {receipt.items.map((it, i) => (
              <tr key={i}>
                <td>{it.product}{it.unit ? ` (${it.unit})` : ""}</td>
                <td className="receipt-right">{it.qty}</td>
                <td className="receipt-right">{nairaFull(it.unit_price)}</td>
                <td className="receipt-right">{nairaFull(it.total)}</td>
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

        <div className="receipt-footer">
          <div className="receipt-type-badge">{typeLabel}</div>
          {isCredit && receipt.due_date && (
            <div className="receipt-muted" style={{ marginTop: 4 }}>
              Payment due: {new Date(receipt.due_date).toLocaleDateString("en-NG", { day: "numeric", month: "short", year: "numeric" })}
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
