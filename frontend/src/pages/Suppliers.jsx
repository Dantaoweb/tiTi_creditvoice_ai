import { useEffect, useState } from "react";
import { useApp } from "../context/AppContext";
import { apiFetch } from "../lib/api";
import { nairaFull, dateStr } from "../lib/format";
import DataTable from "../components/DataTable";
import MetricCard from "../components/MetricCard";

export default function Suppliers() {
  const { ownerPhone } = useApp();
  const [data, setData]     = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState(null);

  useEffect(() => {
    setLoading(true);
    apiFetch("suppliers", { owner_phone: ownerPhone })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [ownerPhone]);

  const suppliers = data?.suppliers || [];
  const totalOwed = suppliers.reduce((s, r) => s + r.balance, 0);
  const totalPaid = suppliers.reduce((s, r) => s + r.total_paid, 0);
  const dueCount  = suppliers.filter((r) => r.has_overdue).length;

  return (
    <>
      {error && <div style={{ color: "var(--rose)" }}>{error}</div>}

      <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(3, minmax(160px, 1fr))" }}>
        <MetricCard loading={loading} label="Total owed to suppliers" value={nairaFull(totalOwed)}  color="rose"  />
        <MetricCard loading={loading} label="Total paid to suppliers" value={nairaFull(totalPaid)}  color="green" />
        <MetricCard loading={loading} label="Suppliers with overdue"  value={dueCount}              color="amber" />
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">Suppliers <span className="text-subtle text-sm">({suppliers.length})</span></span>
        </div>
        <DataTable
          loading={loading}
          rows={suppliers}
          emptyText="No supplier records. Record a purchase from a supplier via WhatsApp."
          rowClass={(r) => r.has_overdue ? "low-stock" : ""}
          columns={[
            { key: "name",        label: "Supplier",         render: (r) => <strong className="td-strong">{(r.name || "—").replace(/\b\w/g, c => c.toUpperCase())}</strong>, sortKey: "name" },
            { key: "purchases",   label: "Purchases",        render: (r) => r.purchases,        sortKey: "purchases" },
            { key: "total_bought",label: "Total purchased",  render: (r) => nairaFull(r.total_bought), sortKey: "total_bought" },
            { key: "total_paid",  label: "Total paid",       render: (r) => nairaFull(r.total_paid), sortKey: "total_paid" },
            { key: "balance",     label: "Balance owed",     render: (r) => r.balance > 0
                ? <span className="text-rose font-bold">{nairaFull(r.balance)}</span>
                : <span className="text-subtle">{nairaFull(r.balance)}</span>,
              sortKey: "balance" },
            { key: "next_due",    label: "Next due",         render: (r) => r.next_due
                ? <span className={new Date(r.next_due) < new Date() ? "text-rose" : ""}>{dateStr(r.next_due)}</span>
                : <span className="text-subtle">—</span> },
          ]}
        />
      </div>

      {!!(data?.recent_purchases?.length) && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">Recent supplier purchases</span>
          </div>
          <DataTable
            loading={false}
            rows={data.recent_purchases}
            emptyText=""
            columns={[
              { key: "supplier",   label: "Supplier",   render: (r) => r.supplier || "—" },
              { key: "product",    label: "Product",    render: (r) => r.product || "—" },
              { key: "total",      label: "Total",      render: (r) => nairaFull(r.total) },
              { key: "paid",       label: "Paid",       render: (r) => nairaFull(r.paid_amount) },
              { key: "balance",    label: "Remaining",  render: (r) => nairaFull(r.total - r.paid_amount) },
              { key: "due_date",   label: "Due",        render: (r) => <span className={r.due_date && new Date(r.due_date) < new Date() ? "text-rose" : ""}>{dateStr(r.due_date)}</span> },
              { key: "created_at", label: "Date",       render: (r) => <span className="td-muted">{dateStr(r.created_at)}</span> },
            ]}
          />
        </div>
      )}
    </>
  );
}
