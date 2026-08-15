import { useEffect, useState } from "react";
import { AlertCircle, TrendingUp, TrendingDown } from "lucide-react";
import { useApp } from "../context/AppContext";
import { apiFetch } from "../lib/api";
import { nairaFull, dateTimeStr } from "../lib/format";
import MetricCard from "../components/MetricCard";

const PERIODS = [
  { value: "TODAY", label: "Today" },
  { value: "WEEK",  label: "This Week" },
  { value: "MONTH", label: "This Month" },
  { value: "YEAR",  label: "This Year" },
  { value: "",      label: "All Time" },
];
const PERIOD_LABEL = { TODAY: "today", WEEK: "this week", MONTH: "this month", YEAR: "this year" };

const cap = s => (s || "—").replace(/\b\w/g, c => c.toUpperCase());

function FlagBadge({ flag }) {
  if (!flag) return null;
  const map = {
    loss:    { text: "Loss",    color: "var(--rose)" },
    thin:    { text: "Thin",    color: "var(--amber)" },
    no_cost: { text: "No cost", color: "var(--muted)" },
  };
  const f = map[flag];
  if (!f) return null;
  return (
    <span className="badge" style={{ background: f.color + "1a", color: f.color, marginLeft: 6 }}>
      {f.text}
    </span>
  );
}

function pctDelta(oldP, newP) {
  if (!oldP || newP == null) return null;
  return Math.round((newP - oldP) / oldP * 100);
}

export default function Insights() {
  const { period, setPeriod } = useApp();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    apiFetch("reports/inventory-insights", { period })
      .then(d => { setData(d); setError(""); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [period]);

  const periodLabel = PERIOD_LABEL[period] || "all time";
  const margin = data?.margin || [];
  const changes = data?.price_changes || [];
  const received = data?.stock_received || [];

  return (
    <>
      <div className="card-body" style={{ padding: "0 0 4px" }}>
        <h2 style={{ margin: "0 0 2px" }}>Inventory Insights</h2>
        <p className="text-subtle text-sm" style={{ margin: 0 }}>
          Margin, price changes and stock received — tracked over time.
        </p>
      </div>

      {error && (
        <div className="card card-body" style={{ color: "var(--rose)", display: "flex", gap: 8 }}>
          <AlertCircle size={16} /> {error}
        </div>
      )}

      {/* Period picker */}
      <div className="dash-period-strip">
        {PERIODS.map(({ value, label }) => (
          <button
            key={value}
            className={`btn btn-sm btn-pill${period === value ? " btn-primary" : " btn-ghost"}`}
            onClick={() => setPeriod(value)}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Summary strip */}
      <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))" }}>
        <MetricCard loading={loading} label={`Purchasing spend ${periodLabel}`}
          value={nairaFull(data?.purchasing_spend)} color="amber" />
        <MetricCard loading={loading} label={`Price changes ${periodLabel}`}
          value={Number(data?.price_edits || 0).toLocaleString()} color="blue"
          sub={data ? `${data.price_up} up · ${data.price_down} down` : undefined} />
        <MetricCard loading={loading} label="Products priced"
          value={Number(margin.length).toLocaleString()} color="brand" />
      </div>

      {/* A. Margin snapshot */}
      <div className="card">
        <div className="card-header"><span className="card-title">Margin snapshot</span></div>
        {loading ? (
          <p className="td-muted card-body">Loading…</p>
        ) : margin.length === 0 ? (
          <p className="td-muted card-body">No priced products yet. Add a selling price to a product to see its margin.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="history-table">
              <thead>
                <tr><th>Product</th><th>Cost</th><th>Selling</th><th>Margin</th><th>%</th></tr>
              </thead>
              <tbody>
                {margin.map(r => (
                  <tr key={r.id} className={r.flag === "loss" ? "low-stock" : ""}>
                    <td>{cap(r.name)}{r.is_service && <span className="svc-chip" style={{ marginLeft: 6 }}>service</span>}<FlagBadge flag={r.flag} /></td>
                    <td className="td-muted">{r.cost_price ? nairaFull(r.cost_price) : "—"}</td>
                    <td>{nairaFull(r.selling_price)}</td>
                    <td className={r.margin != null && r.margin < 0 ? "" : "td-muted"}
                        style={r.margin != null && r.margin < 0 ? { color: "var(--rose)" } : undefined}>
                      {r.margin != null ? nairaFull(r.margin) : "—"}
                    </td>
                    <td><strong>{r.margin_pct != null ? `${r.margin_pct}%` : "—"}</strong></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* B. Price changes */}
      <div className="card">
        <div className="card-header"><span className="card-title">Price changes {periodLabel}</span></div>
        {loading ? (
          <p className="td-muted card-body">Loading…</p>
        ) : changes.length === 0 ? (
          <p className="td-muted card-body">No price changes {periodLabel}. Edits to a product's cost or selling price show up here.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="history-table">
              <thead>
                <tr><th>Date</th><th>Product</th><th>What</th><th>From → To</th><th>By</th></tr>
              </thead>
              <tbody>
                {changes.map(c => {
                  const d = pctDelta(c.old_price, c.new_price);
                  return (
                    <tr key={c.id}>
                      <td className="td-muted">{dateTimeStr(c.created_at)}</td>
                      <td>{cap(c.name)}</td>
                      <td>{c.field === "cost_price" ? "Cost" : "Selling"}</td>
                      <td>
                        <span className="td-muted">{c.old_price ? nairaFull(c.old_price) : "—"}</span>
                        {" → "}
                        <strong>{c.new_price ? nairaFull(c.new_price) : "—"}</strong>
                        {d != null && d !== 0 && (
                          <span style={{ marginLeft: 6, color: d > 0 ? "var(--brand)" : "var(--rose)" }}>
                            {d > 0 ? `+${d}%` : `${d}%`}
                          </span>
                        )}
                      </td>
                      <td className="td-muted">{c.changed_by || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* C. Stock received */}
      <div className="card">
        <div className="card-header"><span className="card-title">Stock received {periodLabel}</span></div>
        {loading ? (
          <p className="td-muted card-body">Loading…</p>
        ) : received.length === 0 ? (
          <p className="td-muted card-body">No stock received {periodLabel}. Record stock via Quick Record → Stock Received.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="history-table">
              <thead>
                <tr><th>Product</th><th>Qty</th><th>Spent</th><th>Avg cost</th><th>Trend</th></tr>
              </thead>
              <tbody>
                {received.map(r => (
                  <tr key={r.item_id}>
                    <td>{cap(r.name)}</td>
                    <td><strong>{(r.qty ?? 0).toLocaleString()}</strong></td>
                    <td>{nairaFull(r.spent)}</td>
                    <td className="td-muted">{r.avg_cost ? nairaFull(r.avg_cost) : "—"}</td>
                    <td>
                      {r.trend === "up" ? (
                        <span style={{ color: "var(--rose)", display: "inline-flex", alignItems: "center", gap: 3 }}>
                          <TrendingUp size={14} /> {r.first_cost ? nairaFull(r.first_cost) : ""}→{r.last_cost ? nairaFull(r.last_cost) : ""}
                        </span>
                      ) : r.trend === "down" ? (
                        <span style={{ color: "var(--brand)", display: "inline-flex", alignItems: "center", gap: 3 }}>
                          <TrendingDown size={14} /> {r.first_cost ? nairaFull(r.first_cost) : ""}→{r.last_cost ? nairaFull(r.last_cost) : ""}
                        </span>
                      ) : (
                        <span className="td-muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
