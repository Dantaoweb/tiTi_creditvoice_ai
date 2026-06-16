import { useEffect, useState } from "react";
import { Download } from "lucide-react";
import { useApp } from "../context/AppContext";
import { useAuth } from "../context/AuthContext";
import { apiFetch, apiDownload } from "../lib/api";
import { nairaFull, dateTimeStr, qty } from "../lib/format";
import DataTable from "../components/DataTable";
import { TxTypeBadge } from "../components/Badge";
import { getBizLabels } from "../lib/bizLabels";

export default function Transactions() {
  const { ownerPhone, period } = useApp();
  const { user } = useAuth();
  const L = getBizLabels(user?.menu_group);
  const [rows, setRows]       = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [filter, setFilter]   = useState("all");
  const [exporting, setExporting] = useState(false);

  async function handleExport(exportType) {
    setExporting(true);
    try {
      await apiDownload("export", { export_type: exportType, owner_phone: ownerPhone, period });
    } catch (e) {
      alert(e.message);
    } finally {
      setExporting(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    apiFetch("transactions", { owner_phone: ownerPhone, period })
      .then((d) => setRows(d.transactions))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [ownerPhone, period]);

  const types = ["all", ...Array.from(new Set(rows.map((r) => r.type))).sort()];

  const filtered =
    filter === "all" ? rows : rows.filter((r) => r.type === filter);

  return (
    <>
      {error && <div style={{ color: "var(--rose)" }}>{error}</div>}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Transactions <span className="text-subtle text-sm">({filtered.length})</span></span>
          <div className="gap-2" style={{ flexWrap: "wrap" }}>
            {types.map((t) => (
              <button
                key={t}
                className={`btn btn-sm btn-pill ${filter === t ? "btn-primary" : "btn-ghost"}`}
                onClick={() => setFilter(t)}
              >
                {t === "all" ? "All" : t}
              </button>
            ))}
            <div className="export-dropdown">
              <button className="btn btn-sm btn-ghost export-dropdown-trigger" disabled={exporting}>
                <Download size={13} />
                {exporting ? "Exporting…" : "Export"}
              </button>
              <div className="export-dropdown-menu">
                <button onClick={() => handleExport("transactions")}>Transactions CSV</button>
                <button onClick={() => handleExport("debtors")}>Unpaid Debtors CSV</button>
                <button onClick={() => handleExport("customers")}>Customer List CSV</button>
                <button onClick={() => handleExport("stock")}>Stock Inventory CSV</button>
              </div>
            </div>
          </div>
        </div>
        <DataTable
          loading={loading}
          rows={filtered}
          emptyText="No transactions for this period."
          rowClass={(r) => r.is_voided ? "voided" : ""}
          columns={[
            { key: "id",         label: "#",         render: (r) => <span className="td-mono td-muted">#{r.id}</span> },
            { key: "type",       label: "Type",      render: (r) => <TxTypeBadge type={r.type} voided={r.is_voided} /> },
            { key: "customer",   label: L.customer,  render: (r) => r.customer || <span className="text-subtle">{L.directSale}</span> },
            { key: "product",    label: "Product",   render: (r) => r.product || "—" },
            { key: "qty",        label: "Qty",       render: (r) => qty(r.quantity, r.unit) },
            { key: "amount",     label: "Amount",    render: (r) => <strong>{nairaFull(r.amount)}</strong>, sortKey: "amount" },
            { key: "recorded_by",label: "By",        render: (r) => <span className="td-muted">{r.recorded_by || "—"}</span> },
            { key: "void_reason",label: "Void note", render: (r) => r.void_reason
                ? <span className="text-rose text-sm">{r.void_reason}</span>
                : <span className="text-subtle">—</span> },
            { key: "created_at", label: "Date",      render: (r) => <span className="td-muted">{dateTimeStr(r.created_at)}</span>, sortKey: "created_at" },
          ]}
        />
      </div>
    </>
  );
}
