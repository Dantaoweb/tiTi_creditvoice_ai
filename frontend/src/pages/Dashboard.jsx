import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { TrendingUp, AlertCircle, MessageCircle, X, Download, FileText, MapPin } from "lucide-react";
import { useApp } from "../context/AppContext";
import { useAuth } from "../context/AuthContext";
import { apiFetch, apiDownload } from "../lib/api";
import { naira, nairaFull, relativeDate } from "../lib/format";
import MetricCard from "../components/MetricCard";
import DataTable from "../components/DataTable";
import { TxTypeBadge } from "../components/Badge";
import { getBizLabels } from "../lib/bizLabels";
import StaleDataBanner from "../components/StaleDataBanner";

const WA_NUDGE_KEY = "cv_wa_nudge_dismissed";

function WhatsAppNudge({ titiNumber }) {
  const [dismissed, setDismissed] = useState(
    () => localStorage.getItem(WA_NUDGE_KEY) === "1"
  );
  if (dismissed || !titiNumber) return null;
  const waLink = `https://wa.me/${titiNumber}?text=Hello`;
  return (
    <div className="wa-nudge">
      <MessageCircle size={18} className="wa-nudge-icon" />
      <div className="wa-nudge-text">
        <strong>Link WhatsApp to unlock more</strong>
        <span>Send reminders to customers, use voice capture, and access tiTi from your phone — send <em>Hello</em> to tiTi on WhatsApp.</span>
      </div>
      <a href={waLink} target="_blank" rel="noreferrer" className="btn btn-whatsapp btn-sm">
        Open WhatsApp
      </a>
      <button className="wa-nudge-close" onClick={() => { setDismissed(true); localStorage.setItem(WA_NUDGE_KEY, "1"); }}>
        <X size={14} />
      </button>
    </div>
  );
}

export default function Dashboard() {
  const { ownerPhone, period } = useApp();
  const { user } = useAuth();
  const L = getBizLabels(user?.menu_group);
  const [titiNumber, setTitiNumber] = useState("");

  useEffect(() => {
    apiFetch("auth/config").then(d => setTitiNumber(d.titi_whatsapp || "")).catch(() => {});
    apiFetch("branches").then(d => setBranches(d.branches || [])).catch(() => {});
  }, []);
  const [data, setData]       = useState(null);
  const [txData, setTxData]   = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [isStale, setIsStale] = useState(false);
  const [exportingType, setExportingType]   = useState(null);
  const [downloadingPDF, setDownloadingPDF] = useState(false);
  const [branches, setBranches]   = useState([]);
  const [branchId, setBranchId]   = useState("");

  async function handleExport(exportType) {
    setExportingType(exportType);
    try {
      await apiDownload("export", { export_type: exportType, owner_phone: ownerPhone, period });
    } catch (e) {
      alert(e.message);
    } finally {
      setExportingType(null);
    }
  }

  async function handleLoanStatement() {
    setDownloadingPDF(true);
    try {
      await apiDownload("loan-statement", { owner_phone: ownerPhone, period });
    } catch (e) {
      alert(e.message);
    } finally {
      setDownloadingPDF(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    setError(null);
    const params = { period };
    const txParams = { period };
    if (branchId) txParams.branch_id = branchId;
    Promise.all([
      apiFetch("dashboard", params),
      apiFetch("transactions", txParams),
    ])
      .then(([d, t]) => { setData(d); setTxData(t); setIsStale(!navigator.onLine); })
      .catch((e) => { setError(e.message); setIsStale(true); })
      .finally(() => setLoading(false));
  }, [ownerPhone, period, branchId]);

  const s = data?.summary || {};

  const PERIOD_LABEL = {
    TODAY: "today", WEEK: "this week", MONTH: "this month", YEAR: "this year",
  };
  const periodLabel = PERIOD_LABEL[period] || "all time";

  return (
    <>
      <WhatsAppNudge titiNumber={titiNumber} />
      <StaleDataBanner isStale={isStale} />

      {error && (
        <div className="card card-body gap-2" style={{ color: "var(--rose)", display: "flex", gap: 8 }}>
          <AlertCircle size={16} /> {error}
        </div>
      )}

      {branches.length > 0 && (
        <div className="branch-filter-bar">
          <MapPin size={14} className="branch-filter-icon" />
          <span className="branch-filter-label">Branch:</span>
          {[{ id: "", name: "All" }, ...branches].map(b => (
            <button
              key={b.id}
              className={`btn btn-sm btn-pill ${branchId === (b.id ? String(b.id) : "") ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setBranchId(b.id ? String(b.id) : "")}
            >
              {b.name}
            </button>
          ))}
        </div>
      )}

      <div className="metrics-grid">
        <MetricCard loading={loading} label={`${L.totalSales || "Sales"} ${periodLabel}`} value={naira(s.total_sales_amount)} color="green" />
        <MetricCard loading={loading} label={L.payments    || "Payments received"}       value={naira(s.total_pay_amount)}   color="blue"  />
        <MetricCard loading={loading} label={L.outstanding || "Outstanding balance"}     value={naira(s.total_outstanding)}  color="amber" />
        <MetricCard loading={loading} label={L.totalCustomers}                           value={Number(s.total_customers || 0).toLocaleString()} color="rose" />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 20 }}>
        <div className="card">
          <div className="card-header">
            <span className="card-title">{L.topDebtors}</span>
            <Link to="/customers" className="btn btn-ghost btn-sm">View all</Link>
          </div>
          <DataTable
            loading={loading}
            rows={data?.top_debtors || []}
            emptyText="No outstanding balances."
            columns={[
              { key: "name",    label: L.customer,  render: (r) => <strong>{r.name}</strong> },
              { key: "balance", label: "Balance",   render: (r) => <span className="text-rose font-bold">{nairaFull(r.balance)}</span>, sortKey: "balance" },
            ]}
          />
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title">Recent transactions</span>
            <Link to="/transactions" className="btn btn-ghost btn-sm">View all</Link>
          </div>
          <DataTable
            loading={loading}
            rows={(txData?.transactions || []).slice(0, 8)}
            emptyText="No transactions yet."
            columns={[
              { key: "type",       label: "Type",       render: (r) => <TxTypeBadge type={r.type} voided={r.is_voided} /> },
              { key: "customer",   label: L.customer,   render: (r) => r.customer || <span className="text-subtle">{L.directSale}</span> },
              { key: "amount",     label: "Amount",     render: (r) => nairaFull(r.amount) },
              { key: "created_at", label: "When",       render: (r) => <span className="td-muted">{relativeDate(r.created_at)}</span> },
            ]}
          />
        </div>
      </div>

      {!!data?.low_stock_count && (
        <div className="card card-body" style={{ display: "flex", alignItems: "center", gap: 10, color: "var(--amber)" }}>
          <TrendingUp size={16} />
          <strong>{data.low_stock_count}</strong> product{data.low_stock_count !== 1 ? "s" : ""} running low on stock.
          <Link to="/inventory" className="btn btn-ghost btn-sm" style={{ marginLeft: "auto" }}>View inventory</Link>
        </div>
      )}

      <div className="stmt-banner">
        <div className="stmt-banner-left">
          <FileText size={18} className="stmt-banner-icon" />
          <div>
            <div className="stmt-banner-title">Loan-Ready Statement</div>
            <div className="stmt-banner-sub">A professional PDF showing your revenue, receivables, and stock — ready to share with a bank or microfinance institution.</div>
          </div>
        </div>
        <button
          className="btn btn-primary btn-sm"
          onClick={handleLoanStatement}
          disabled={downloadingPDF}
        >
          <Download size={14} />
          {downloadingPDF ? "Generating PDF…" : "Download Statement PDF"}
        </button>
      </div>

      <div className="export-strip">
        <div className="export-strip-label">
          <Download size={13} />
          Export data
        </div>
        {[
          { key: "transactions", label: "Transactions" },
          { key: "debtors",      label: "Unpaid Debtors" },
          { key: "customers",    label: "Customers" },
          { key: "stock",        label: "Stock Inventory" },
        ].map(({ key, label }) => (
          <button
            key={key}
            className="btn btn-ghost btn-sm"
            onClick={() => handleExport(key)}
            disabled={exportingType === key}
          >
            {exportingType === key ? "Downloading…" : `${label} CSV`}
          </button>
        ))}
      </div>
    </>
  );
}
