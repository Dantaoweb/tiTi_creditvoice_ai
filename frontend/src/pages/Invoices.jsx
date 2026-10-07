import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, PackageCheck } from "lucide-react";
import { apiFetch } from "../lib/api";
import { nairaFull, dateStr } from "../lib/format";
import { InvoiceStatusBadge } from "./InvoiceView";

export default function Invoices() {
  const [invoices, setInvoices] = useState([]);
  const [summary, setSummary] = useState({ open: 0, overdue: 0, part_paid: 0, paid: 0, total_due: 0 });
  const [filter, setFilter] = useState("");   // "", open, overdue, part_paid, paid, cancelled
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    setLoading(true);
    apiFetch("invoices", filter ? { status: filter } : {})
      .then(d => { setInvoices(d.invoices || []); if (d.summary) setSummary(d.summary); })
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false));
  }, [filter]);

  const tiles = [
    { key: "",          label: "All" },
    { key: "open",      label: `Waiting (${summary.open})` },
    { key: "overdue",   label: `Overdue (${summary.overdue})` },
    { key: "part_paid", label: `Part paid (${summary.part_paid})` },
    { key: "paid",      label: `Paid (${summary.paid})` },
    ...(summary.cancelled ? [{ key: "cancelled", label: `Cancelled (${summary.cancelled})` }] : []),
  ];

  const open = inv => navigate(inv.kind === "sale"
    ? `/pos/receipt/${inv.id}?doc=invoice`
    : `/invoices/${inv.id}`);

  return (
    <div className="card" style={{ maxWidth: 760 }}>
      <div className="card-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span className="card-title">Invoices</span>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
            Awaiting payment: <strong style={{ color: "#b45309" }}>{nairaFull(summary.total_due)}</strong>
          </span>
        </div>
        <button className="btn btn-primary" onClick={() => navigate("/invoices/new")}>
          <Plus size={15} /> New invoice
        </button>
      </div>

      <div style={{ display: "flex", gap: 8, padding: "10px 16px", flexWrap: "wrap" }}>
        {tiles.map(t => (
          <button
            key={t.key || "all"}
            onClick={() => setFilter(t.key)}
            className={`btn btn-sm ${filter === t.key ? "btn-primary" : "btn-ghost"}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {err && <div className="pos-error" style={{ margin: 12 }}>{err}</div>}
      {loading ? (
        <div className="td-muted" style={{ padding: 16 }}>Loading invoices…</div>
      ) : invoices.length === 0 ? (
        <div className="td-muted" style={{ padding: 16 }}>
          {filter
            ? "No invoices here."
            : "No invoices yet. Tap “New invoice” to ask a customer to pay — it isn't a debt until they take the goods on credit."}
        </div>
      ) : (
        <div>
          {invoices.map(inv => (
            <button
              key={`${inv.kind}-${inv.id}`}
              onClick={() => open(inv)}
              style={{
                display: "flex", justifyContent: "space-between", alignItems: "center",
                width: "100%", padding: "12px 16px", background: "none",
                border: "none", borderBottom: "1px solid var(--border)",
                cursor: "pointer", textAlign: "left", gap: 12,
              }}
            >
              <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 2, minWidth: 0 }}>
                <strong>{inv.invoice_ref} · {inv.customer_name}</strong>
                <span className="td-muted" style={{ fontSize: 12 }}>
                  {dateStr(inv.issued_at)}
                  {inv.due_date ? ` · due ${dateStr(inv.due_date)}` : ""}
                  {inv.sent_at ? ` · sent ${dateStr(inv.sent_at)}` : ""}
                  {inv.kind === "sale" ? " · from a sale" : ""}
                </span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
                <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  {inv.kind === "invoice" && inv.delivered && (
                    <PackageCheck size={14} color="#166534" aria-label="Delivered" />
                  )}
                  <InvoiceStatusBadge status={inv.status} />
                </span>
                <span style={{ fontSize: 13, fontWeight: 700, color: inv.outstanding > 0 ? "#b45309" : "var(--text-muted)" }}>
                  {inv.outstanding > 0 ? `${nairaFull(inv.outstanding)} due` : nairaFull(inv.total)}
                </span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
