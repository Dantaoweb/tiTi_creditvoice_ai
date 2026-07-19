import { useEffect, useState } from "react";
import { Download, MapPin, Lock } from "lucide-react";
import { useApp } from "../context/AppContext";
import { useAuth } from "../context/AuthContext";
import { apiFetch, apiDownload, apiPost } from "../lib/api";
import { nairaFull, dateTimeStr, qty } from "../lib/format";
import DataTable from "../components/DataTable";
import { TxTypeBadge } from "../components/Badge";
import { getBizLabels } from "../lib/bizLabels";
import StaleDataBanner from "../components/StaleDataBanner";
import { usePlan } from "../lib/usePlan";
import { useToast } from "../components/Toast";

export default function Transactions() {
  const { ownerPhone, period } = useApp();
  const { user } = useAuth();
  const { allows } = usePlan();
  const canExport = allows("EXPORT");
  const L = getBizLabels(user?.menu_group);
  const toast = useToast();
  const [rows, setRows]           = useState([]);
  const [branches, setBranches]   = useState([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState(null);
  const [isStale, setIsStale]     = useState(false);
  const [filter, setFilter]       = useState("all");
  const [branchFilter, setBranchFilter] = useState("");
  const [exporting, setExporting] = useState(false);

  async function handleExport(exportType) {
    setExporting(true);
    try {
      await apiDownload("export", { export_type: exportType, owner_phone: ownerPhone, period });
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setExporting(false);
    }
  }

  useEffect(() => {
    apiFetch("branches").then(d => setBranches(d.branches || [])).catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    const params = { period };
    if (branchFilter) params.branch_id = branchFilter;
    apiFetch("transactions", params)
      .then((d) => { setRows(d.transactions); setIsStale(!navigator.onLine); })
      .catch((e) => { setError(e.message); setIsStale(true); })
      .finally(() => setLoading(false));
  }, [ownerPhone, period, branchFilter]);

  async function voidTx(row) {
    const reason = window.prompt(
      `Void transaction #${row.id} (${nairaFull(row.amount)})?\n\n` +
      "It will stop counting in balances and reports. Enter a reason:",
      ""
    );
    if (reason === null) return;   // cancelled
    try {
      await apiPost(`transactions/${row.id}/void`, { reason });
      setRows(rs => rs.map(r =>
        r.id === row.id ? { ...r, is_voided: true, void_reason: reason.trim() || "No reason given" } : r
      ));
      toast("Transaction voided.", "success");
    } catch (e) {
      toast(e.message, "error");
    }
  }

  const types = ["all", ...Array.from(new Set(rows.map((r) => r.type))).sort()];
  const filtered = filter === "all" ? rows : rows.filter((r) => r.type === filter);

  return (
    <>
      <StaleDataBanner isStale={isStale} />
      {error && <div style={{ color: "var(--rose)" }}>{error}</div>}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Transactions <span className="text-subtle text-sm">({filtered.length})</span></span>
          <div className="gap-2" style={{ flexWrap: "wrap" }}>
            {branches.length > 0 && (
              <select
                className="branch-filter-select"
                value={branchFilter}
                onChange={e => setBranchFilter(e.target.value)}
              >
                <option value="">All branches</option>
                {branches.map(b => (
                  <option key={b.id} value={b.id}>{b.name}</option>
                ))}
              </select>
            )}
            {types.map((t) => (
              <button
                key={t}
                className={`btn btn-sm btn-pill ${filter === t ? "btn-primary" : "btn-ghost"}`}
                onClick={() => setFilter(t)}
              >
                {t === "all" ? "All" : t}
              </button>
            ))}
            {canExport ? (
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
            ) : (
              <button
                className="btn btn-sm btn-ghost"
                style={{ opacity: 0.6, cursor: "not-allowed" }}
                title="Export is available on the Go plan. Upgrade to download your records."
                onClick={() => window.location.href = "/app/upgrade"}
              >
                <Lock size={11} style={{ color: "#a78bfa" }} />
                <Download size={13} /> Export
              </button>
            )}
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
            { key: "branch",     label: "Branch",    render: (r) => r.branch_name
                ? <span className="branch-chip"><MapPin size={11} />{r.branch_name}</span>
                : <span className="text-subtle">—</span> },
            { key: "recorded_by",label: "By",        render: (r) => <span className="td-muted">{r.recorded_by || "—"}</span> },
            { key: "void_reason",label: "Void note", render: (r) => r.void_reason
                ? <span className="text-rose text-sm">{r.void_reason}</span>
                : <span className="text-subtle">—</span> },
            { key: "created_at", label: "Date",      render: (r) => <span className="td-muted">{dateTimeStr(r.created_at)}</span>, sortKey: "created_at" },
            { key: "actions",    label: "",          render: (r) => r.is_voided
                ? <span className="text-subtle text-sm">Voided</span>
                : <button className="btn btn-ghost btn-xs text-rose" onClick={() => voidTx(r)}>Void</button> },
          ]}
        />
      </div>
    </>
  );
}
