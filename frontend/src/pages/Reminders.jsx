import { useEffect, useState } from "react";
import { useApp } from "../context/AppContext";
import { useAuth } from "../context/AuthContext";
import { apiFetch } from "../lib/api";
import { nairaFull, dateStr, dateTimeStr } from "../lib/format";
import DataTable from "../components/DataTable";
import { StatusBadge } from "../components/Badge";
import { getBizLabels } from "../lib/bizLabels";

export default function Reminders() {
  const { ownerPhone } = useApp();
  const { user } = useAuth();
  const L = getBizLabels(user?.menu_group);
  const [rows, setRows]     = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState(null);

  useEffect(() => {
    setLoading(true);
    apiFetch("reminders", { owner_phone: ownerPhone })
      .then((d) => setRows(d.reminders))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [ownerPhone]);

  const counts = rows.reduce((acc, r) => {
    acc[r.status] = (acc[r.status] || 0) + 1;
    return acc;
  }, {});

  return (
    <>
      {error && <div style={{ color: "var(--rose)" }}>{error}</div>}

      {!!rows.length && (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {Object.entries(counts).map(([status, count]) => (
            <div key={status} className="card card-body text-sm" style={{ padding: "10px 16px" }}>
              <StatusBadge status={status} /> <strong style={{ marginLeft: 6 }}>{count}</strong>
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <span className="card-title">Reminders <span className="text-subtle text-sm">({rows.length})</span></span>
        </div>
        <DataTable
          loading={loading}
          rows={rows}
          emptyText="No reminders queued."
          columns={[
            { key: "customer_name", label: L.customer,  render: (r) => <strong className="td-strong">{(r.customer_name || "—").replace(/\b\w/g, c => c.toUpperCase())}</strong> },
            { key: "balance",       label: "Balance",   render: (r) => <span className="text-rose font-bold">{nairaFull(r.balance)}</span>, sortKey: "balance" },
            { key: "due_date",      label: "Due",       render: (r) => <span className={r.due_date && new Date(r.due_date) < new Date() ? "text-rose" : ""}>{dateStr(r.due_date)}</span> },
            { key: "type",          label: "Type",      render: (r) => <span className="td-muted">{r.type || "—"}</span> },
            { key: "status",        label: "Status",    render: (r) => <StatusBadge status={r.status} /> },
            { key: "message_text",  label: "Message",   render: (r) => <span className="text-sm td-muted" style={{ maxWidth: 260, display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.message_text || "—"}</span> },
            { key: "created_at",    label: "Queued",    render: (r) => <span className="td-muted">{dateTimeStr(r.created_at)}</span> },
          ]}
        />
      </div>
    </>
  );
}
