import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Printer, ShoppingCart, ArrowLeft } from "lucide-react";
import { apiFetch } from "../lib/api";
import { naira, dateTimeStr } from "../lib/format";

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

  const paid = receipt.total; // TODO: fetch pay amount from receipt when we store it
  const typeLabel = receipt.type === "BUY" ? "Credit Sale" : "Cash Sale";

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
          <div className="receipt-brand">CreditVoice</div>
          <div className="receipt-sub">Business Receipt</div>
          <div className="receipt-date">{dateTimeStr(receipt.created_at)}</div>
          <div className="receipt-ref">Receipt #{receipt.id}</div>
        </div>

        {receipt.customer && (
          <div className="receipt-customer">
            <span className="receipt-label">Customer</span>
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
                <td className="receipt-right">{naira(it.unit_price)}</td>
                <td className="receipt-right">{naira(it.total)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="receipt-total-row">
              <td colSpan={3}>Total</td>
              <td className="receipt-right">{naira(receipt.total)}</td>
            </tr>
          </tfoot>
        </table>

        <div className="receipt-footer">
          <div className="receipt-type-badge">{typeLabel}</div>
          {receipt.recorded_by && (
            <div className="receipt-muted">Served by: {receipt.recorded_by}</div>
          )}
          <div className="receipt-muted" style={{ marginTop: 12 }}>
            Thank you for your business
          </div>
        </div>
      </div>
    </div>
  );
}
