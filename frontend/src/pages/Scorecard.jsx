import { useEffect, useState } from "react";
import { ShieldCheck, TrendingUp, Info, CheckCircle2, XCircle, ExternalLink } from "lucide-react";
import { apiFetch } from "../lib/api";
import { nairaFull, dateStr } from "../lib/format";
import MetricCard from "../components/MetricCard";

// The business's own evidence file: what CreditVoice can show a finance partner
// about its trading record. CreditVoice lends nothing and approves nothing —
// partners underwrite — so the wording here never promises anyone anything.

function Bar({ value, tone = "brand" }) {
  return (
    <div style={{ height: 6, background: "rgba(127,127,127,0.15)", borderRadius: 3, overflow: "hidden" }}>
      <div style={{
        height: "100%", width: `${Math.max(0, Math.min(100, value))}%`,
        background: tone === "amber" ? "var(--amber)" : "var(--brand)", borderRadius: 3,
        transition: "width .3s",
      }} />
    </div>
  );
}

function TierBadge({ tier, score }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <ShieldCheck size={22} color="var(--brand)" />
      <div>
        <div style={{ fontSize: 20, fontWeight: 800 }}>{tier}</div>
        <div className="text-subtle text-sm">
          {score === null ? "Not enough records yet" : `Score ${score} of 100`}
        </div>
      </div>
    </div>
  );
}

function MonthlySales({ months }) {
  const entries = Object.entries(months || {});
  if (entries.length === 0) return null;
  const max = Math.max(...entries.map(([, v]) => v), 1);
  return (
    <div className="card">
      <div className="card-header"><span className="card-title">Sales by month</span></div>
      <div className="card-body" style={{ display: "grid", gap: 8 }}>
        {entries.map(([month, value]) => (
          <div key={month} style={{ display: "grid", gridTemplateColumns: "72px 1fr auto", gap: 10, alignItems: "center" }}>
            <span className="text-subtle text-sm">{month}</span>
            <Bar value={(value / max) * 100} />
            <strong style={{ fontSize: 13 }}>{nairaFull(value)}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function Offer({ offer }) {
  const assets = (offer.asset_types || []).join(", ");
  return (
    <div className="card" style={{ marginBottom: 12 }}>
      <div className="card-header" style={{ flexWrap: "wrap", gap: 8 }}>
        <span className="card-title">{offer.name}</span>
        <span className="badge" style={{
          background: offer.eligible ? "rgba(22,101,52,0.10)" : "rgba(180,83,9,0.10)",
          color: offer.eligible ? "#166534" : "#92400e", fontWeight: 700,
        }}>
          {offer.eligible ? "You meet their requirements" : "Not there yet"}
        </span>
      </div>
      <div className="card-body">
        {assets && <div className="text-subtle text-sm" style={{ marginBottom: 6 }}>Finances: {assets}</div>}
        {(offer.asset_value_min || offer.asset_value_max) && (
          <div className="text-subtle text-sm" style={{ marginBottom: 10 }}>
            Value range: {nairaFull(offer.asset_value_min || 0)} – {nairaFull(offer.asset_value_max || 0)}
          </div>
        )}
        {(offer.checks || []).length === 0 ? (
          <div className="text-subtle text-sm">No published requirements — apply and they will review.</div>
        ) : (
          <div style={{ display: "grid", gap: 6 }}>
            {offer.checks.map((c, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                {c.passed
                  ? <CheckCircle2 size={14} color="#166534" />
                  : <XCircle size={14} color="#b45309" />}
                <span style={{ flex: 1 }}>{c.requirement}</span>
                <span className="text-subtle">
                  needs {c.required.toLocaleString()} · you have {Number(c.actual).toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function Scorecard() {
  const [card, setCard] = useState(null);
  const [offers, setOffers] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([apiFetch("scorecard"), apiFetch("finance-offers")])
      .then(([c, o]) => { setCard(c); setOffers(o); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="page-loading">Loading your scorecard…</div>;
  if (error) return <div style={{ color: "var(--rose)" }}>{error}</div>;

  const m = card.metrics;

  return (
    <>
      <div className="card">
        <div className="card-header" style={{ flexWrap: "wrap", gap: 12 }}>
          <TierBadge tier={card.tier} score={card.score} />
          <div style={{ textAlign: "right" }}>
            <div className="text-subtle text-sm">Evidence strength</div>
            <div style={{ fontWeight: 700 }}>{card.confidence}%</div>
          </div>
        </div>
        <div className="card-body">
          {!card.scored && (
            <div className="card card-body" style={{ color: "var(--amber)", fontSize: 13.5, marginBottom: 12 }}>
              {card.not_scored_reason} Keep recording your sales and it will appear here.
            </div>
          )}
          <div style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13, color: "var(--text-muted)" }}>
            <Info size={15} style={{ flexShrink: 0, marginTop: 2 }} />
            <span>
              This is a record of what you have entered in CreditVoice. You choose when to share it
              with a finance partner. CreditVoice does not lend and does not approve anything — each
              partner decides for itself.
            </span>
          </div>
        </div>
      </div>

      <div className="metrics-grid">
        <MetricCard label="Average monthly sales" value={nairaFull(m.avg_monthly_sales)} color="brand" />
        <MetricCard label="Lowest month" value={nairaFull(m.min_monthly_sales)} />
        <MetricCard label="Months of records" value={m.months_recorded} />
        <MetricCard label="Due in next 30 days" value={nairaFull(m.expected_next_30_days)} color="blue" />
        <MetricCard label="Owed to you" value={nairaFull(m.receivables)} color={m.receivables > 0 ? "rose" : undefined} />
        <MetricCard label="Customers who return" value={`${m.repeat_customer_pct}%`} />
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">What builds your score</span>
          <span className="text-subtle text-sm">{card.scored ? `Score ${card.score}` : "Unrated"}</span>
        </div>
        <div className="card-body" style={{ display: "grid", gap: 12 }}>
          {card.components.map(c => (
            <div key={c.key}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
                <span>{c.label}</span>
                <span className="text-subtle">
                  {typeof c.value === "number" && c.value > 1000 ? nairaFull(c.value) : c.value} · {c.score}/100
                </span>
              </div>
              <Bar value={c.score} tone={c.score < 40 ? "amber" : "brand"} />
            </div>
          ))}
        </div>
      </div>

      <MonthlySales months={m.monthly_sales} />

      <div className="card">
        <div className="card-header"><span className="card-title">Your record in detail</span></div>
        <div className="card-body">
          <table className="history-table">
            <tbody>
              <tr><td>Recording days per month</td><td className="receipt-right">{m.avg_active_days_per_month}</td></tr>
              <tr><td>First record</td><td className="receipt-right">{m.first_record_at ? dateStr(m.first_record_at) : "—"}</td></tr>
              <tr><td>On CreditVoice</td><td className="receipt-right">{m.months_on_platform} month(s)</td></tr>
              <tr>
                <td>Gross margin</td>
                <td className="receipt-right">
                  {m.gross_margin_pct}%
                  <span className="text-subtle text-sm"> (based on {m.margin_coverage_pct}% of sales)</span>
                </td>
              </tr>
              <tr><td>Credit given to customers</td><td className="receipt-right">{nairaFull(m.credit_sales)}</td></tr>
              <tr><td>Credit collected back</td><td className="receipt-right">{m.collection_rate_pct}%</td></tr>
              <tr><td>Average days to collect</td><td className="receipt-right">{m.avg_days_to_collect}</td></tr>
              <tr><td>Suppliers paid</td><td className="receipt-right">{m.supplier_paid_pct}%</td></tr>
              <tr><td>Overdue to suppliers</td><td className="receipt-right">{nairaFull(m.overdue_payables)}</td></tr>
              <tr><td>Sales tied to a named customer</td><td className="receipt-right">{m.corroborated_revenue_pct}%</td></tr>
              <tr><td>Customers · staff · products</td><td className="receipt-right">{m.total_customers} · {m.staff_count} · {m.stock_items}</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title"><TrendingUp size={15} /> Financing partners</span>
        </div>
        <div className="card-body">
          {(offers?.offers || []).length === 0 ? (
            <p className="td-muted">No partners listed yet. They will appear here as they join.</p>
          ) : (
            offers.offers.map(o => <Offer key={o.id} offer={o} />)
          )}
          <div className="text-subtle text-sm" style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
            <ExternalLink size={13} style={{ flexShrink: 0, marginTop: 2 }} />
            <span>
              Partners finance tools and vehicles and let you spread the cost. They run their own
              checks; meeting the requirements here does not guarantee approval.
            </span>
          </div>
        </div>
      </div>
    </>
  );
}
