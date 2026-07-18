import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../lib/api";
import { nairaFull, dateStr } from "../lib/format";

const STATUS_STYLES = {
  open:    { label: "Open",    bg: "rgba(59,130,246,0.12)",  fg: "#2563eb" },
  overdue: { label: "Overdue", bg: "rgba(239,68,68,0.12)",   fg: "#b91c1c" },
  paid:    { label: "Paid",    bg: "rgba(22,163,74,0.12)",   fg: "#166534" },
};

function StatusBadge({ status }) {
  const s = STATUS_STYLES[status] || STATUS_STYLES.open;
  return (
    <span style={{
      fontSize: 12, fontWeight: 700, padding: "2px 10px", borderRadius: 999,
      background: s.bg, color: s.fg, whiteSpace: "nowrap",
    }}>
      {s.label}
    </span>
  );
}

export default function Invoices() {
  const [invoices, setInvoices] = useState([]);
  const [summary, setSummary] = useState({ open: 0, overdue: 0, paid: 0, total_due: 0 });
  const [filter, setFilter] = useState("");   // "", open, overdue, paid
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    setLoading(true);
    apiFetch("invoices", filter ? { status: filter } : {})
      .then(d => { setInvoices(d.invoices || []); setSummary(d.summary || summary); })
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const tiles = [
    { key: "",        label: "All" },
    { key: "open",    label: `Open (${summary.open})` },
    { key: "overdue", label: `Overdue (${summary.overdue})` },
    { key: "paid",    label: `Paid (${summary.paid})` },
  ];

  return (
    <div className="card" style={{ maxWidth: 760 }}>
      <div className="card-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span className="card-title">Invoices</span>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
          Outstanding: <strong style={{ color: "#b45309" }}>{nairaFull(summary.total_due)}</strong>
        </span>
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
          {filter ? `No ${filter} invoices.` : "No invoices yet. Open a credit sale's receipt and tap “View as Invoice”."}
        </div>
      ) : (
        <div>
          {invoices.map(inv => (
            <button
              key={inv.id}
              onClick={() => navigate(`/pos/receipt/${inv.id}?doc=invoice`)}
              style={{
                display: "flex", justifyContent: "space-between", alignItems: "center",
                width: "100%", padding: "12px 16px", background: "none",
                border: "none", borderBottom: "1px solid var(--border)",
                cursor: "pointer", textAlign: "left", gap: 12,
              }}
            >
              <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 2 }}>
                <strong>{inv.invoice_ref} · {inv.customer_name}</strong>
                <span className="td-muted" style={{ fontSize: 12 }}>
                  {dateStr(inv.issued_at)}
                  {inv.due_date ? ` · due ${dateStr(inv.due_date)}` : ""}
                </span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
                <StatusBadge status={inv.status} />
                <span style={{ fontSize: 13, fontWeight: 700, color: inv.outstanding > 0 ? "#b45309" : "#166534" }}>
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
