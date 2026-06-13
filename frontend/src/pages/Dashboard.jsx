import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { TrendingUp, AlertCircle, MessageCircle, X } from "lucide-react";
import { useApp } from "../context/AppContext";
import { useAuth } from "../context/AuthContext";
import { apiFetch } from "../lib/api";
import { naira, nairaFull, relativeDate } from "../lib/format";
import MetricCard from "../components/MetricCard";
import DataTable from "../components/DataTable";
import { TxTypeBadge } from "../components/Badge";
import { getBizLabels } from "../lib/bizLabels";

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
  }, []);
  const [data, setData]       = useState(null);
  const [txData, setTxData]   = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    const params = { owner_phone: ownerPhone, period };
    Promise.all([
      apiFetch("dashboard", params),
      apiFetch("transactions", { owner_phone: ownerPhone, period }),
    ])
      .then(([d, t]) => { setData(d); setTxData(t); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [ownerPhone, period]);

  const s = data?.summary || {};

  const PERIOD_LABEL = {
    TODAY: "today", WEEK: "this week", MONTH: "this month", YEAR: "this year",
  };
  const periodLabel = PERIOD_LABEL[period] || "all time";

  return (
    <>
      <WhatsAppNudge titiNumber={titiNumber} />

      {error && (
        <div className="card card-body gap-2" style={{ color: "var(--rose)", display: "flex", gap: 8 }}>
          <AlertCircle size={16} /> {error}
        </div>
      )}

      <div className="metrics-grid">
        <MetricCard loading={loading} label={`Sales ${periodLabel}`}    value={naira(s.total_sales_amount)} color="green" />
        <MetricCard loading={loading} label="Payments received"         value={naira(s.total_pay_amount)}   color="blue"  />
        <MetricCard loading={loading} label="Outstanding balance"       value={naira(s.total_outstanding)}  color="amber" />
        <MetricCard loading={loading} label={L.totalCustomers}          value={Number(s.total_customers || 0).toLocaleString()} color="rose" />
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
    </>
  );
}
