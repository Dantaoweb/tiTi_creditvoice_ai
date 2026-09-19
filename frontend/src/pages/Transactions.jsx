import { useEffect, useRef, useState } from "react";
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

const PAGE_SIZE = 50;

export default function Transactions() {
  const { ownerPhone, period } = useApp();
  const { user } = useAuth();
  const { allows } = usePlan();
  const canExport = allows("EXPORT");
  const L = getBizLabels(user?.menu_group);
  const toast = useToast();
  const [rows, setRows]           = useState([]);
  const [total, setTotal]         = useState(0);
  const [hasMore, setHasMore]     = useState(false);
  const [byType, setByType]       = useState({});   // server counts per type, whole period
  const [branches, setBranches]   = useState([]);
  const [loading, setLoading]     = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError]         = useState(null);
  const [isStale, setIsStale]     = useState(false);
  const [filter, setFilter]       = useState("all");
  const [branchFilter, setBranchFilter] = useState("");
  const [search, setSearch]       = useState("");
  const [query, setQuery]         = useState("");   // debounced search sent to the server
  const [sort, setSort]           = useState(null); // { col, dir } — null = newest first
  const [exporting, setExporting] = useState(false);
  const reqId = useRef(0);

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

  // Paged, filtered and searched on the server so the whole period is
  // reachable — the list used to stop at the latest 200.
  function pageParams(offset, limit) {
    return {
      period, branch_id: branchFilter, q: query,
      type: filter === "all" ? "" : filter,
      sort: sort ? (sort.col === "amount" ? "amount" : "date") : "", dir: sort?.dir || "",
      offset, limit,
    };
  }

  useEffect(() => {
    const t = setTimeout(() => setQuery(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Type counts ignore the type filter itself, so every pill keeps its count.
  useEffect(() => {
    apiFetch("transactions/summary", { period, branch_id: branchFilter, q: query })
      .then(d => setByType(d.by_type || {}))
      .catch(() => {});
  }, [ownerPhone, period, branchFilter, query]);

  useEffect(() => {
    const id = ++reqId.current;
    setLoading(true);
    setRows([]);
    apiFetch("transactions", pageParams(0, PAGE_SIZE))
      .then((d) => {
        if (id !== reqId.current) return;
        setRows(d.transactions); setTotal(d.total); setHasMore(d.has_more);
        setError(null); setIsStale(!navigator.onLine);
      })
      .catch((e) => { if (id === reqId.current) { setError(e.message); setIsStale(true); } })
      .finally(() => { if (id === reqId.current) setLoading(false); });
  }, [ownerPhone, period, branchFilter, filter, query, sort]);

  function loadMore() {
    const id = reqId.current;
    setLoadingMore(true);
    apiFetch("transactions", pageParams(rows.length, PAGE_SIZE))
      .then((d) => {
        if (id !== reqId.current) return;
        setRows(prev => {
          const seen = new Set(prev.map(r => r.id));
          return [...prev, ...d.transactions.filter(r => !seen.has(r.id))];
        });
        setTotal(d.total); setHasMore(d.has_more);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoadingMore(false));
  }

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

  // Keep the selected pill visible even if a search leaves it with no matches.
  const types = ["all", ...Array.from(new Set([...Object.keys(byType), ...(filter !== "all" ? [filter] : [])])).sort()];
  const typeCount = t => t === "all"
    ? Object.values(byType).reduce((s, n) => s + n, 0)
    : byType[t] || 0;

  return (
    <>
      <StaleDataBanner isStale={isStale} />
      {error && <div style={{ color: "var(--rose)" }}>{error}</div>}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Transactions <span className="text-subtle text-sm">({total.toLocaleString()})</span></span>
          <div className="gap-2" style={{ flexWrap: "wrap" }}>
            <input
              placeholder="Search customer or product…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{ width: 190, minWidth: 120 }}
            />
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
                <span style={{ opacity: 0.7, marginLeft: 4 }}>({typeCount(t).toLocaleString()})</span>
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
                <Lock size={11} style={{ color: "#3b82f6" }} />
                <Download size={13} /> Export
              </button>
            )}
          </div>
        </div>
        <DataTable
          loading={loading && rows.length === 0}
          rows={rows}
          sort={sort}
          onSort={setSort}
          emptyText={query || filter !== "all" ? "No transactions match." : "No transactions for this period."}
          rowClass={(r) => r.is_voided ? "voided" : ""}
          columns={[
            { key: "id",         label: "#",         render: (r) => <span className="td-mono td-muted">#{r.id}</span> },
            { key: "type",       label: "Type",      render: (r) => <TxTypeBadge type={r.type} voided={r.is_voided} /> },
            { key: "customer",   label: L.customer,  render: (r) => r.customer
                ? <span style={{ color: "#2563eb", fontWeight: 600 }}>{r.customer}</span>
                : <span className="text-subtle">{L.directSale}</span> },
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
        {rows.length > 0 && (
          <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 12, padding: 12, flexWrap: "wrap" }}>
            <span className="text-subtle text-sm">
              Showing {rows.length.toLocaleString()} of {total.toLocaleString()}
            </span>
            {hasMore && (
              <button type="button" className="btn btn-secondary btn-sm" onClick={loadMore} disabled={loadingMore}>
                {loadingMore ? "Loading…" : "Load more"}
              </button>
            )}
          </div>
        )}
      </div>
    </>
  );
}
