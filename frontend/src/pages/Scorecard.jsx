import { useEffect, useState } from "react";
import { ShieldCheck, TrendingUp, Info, CheckCircle2, XCircle, ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull, dateStr, parseAmt } from "../lib/format";
import MetricCard from "../components/MetricCard";
import { StatusPill } from "../components/FinanceApply";

// The business's own evidence file: what CreditVoice can show a finance partner
// about its trading record. CreditVoice lends nothing and approves nothing —
// partners underwrite — so the wording here never promises anyone anything.

// Plain-language meaning for a component, from the advice endpoint.
function meaningFor(advice, key) {
  const found = (advice?.explanations || []).find(e => e.key === key);
  return found?.meaning || "";
}

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



// Identity details, asked at the point a financier needs them — never at
// Applying shares this business's trading record with one partner. Consent is
// explicit, and the scorecard is frozen at this moment so what the partner sees
// A financed asset's repayment plan. It also lives on the Suppliers page (each
// installment is a supplier bill), but the plan reads clearer in one place.
function RepaymentPlan({ application, onPaid }) {
  const [schedule, setSchedule] = useState(null);
  const [busy, setBusy] = useState(null);      // installment number being paid
  const [err, setErr] = useState("");

  function load() {
    apiFetch(`my-applications/${application.id}/schedule`)
      .then(d => setSchedule(d.schedule))
      .catch(e => setErr(e.message));
  }
  useEffect(load, [application.id]);

  async function pay(inst) {
    const typed = window.prompt(
      `How much did you pay towards installment ${inst.installment_no}?`,
      String(inst.outstanding));
    if (typed === null) return;
    const amount = parseAmt(typed);
    if (!amount || amount <= 0) return;
    setBusy(inst.installment_no); setErr("");
    try {
      const r = await apiPost(`my-applications/${application.id}/repayments`,
        { installment_no: inst.installment_no, amount });
      setSchedule(r.schedule);
      onPaid && onPaid();
    } catch (e) { setErr(e.message); }
    finally { setBusy(null); }
  }

  if (err) return <div style={{ color: "var(--rose)", fontSize: 12 }}>{err}</div>;
  if (!schedule) return null;

  return (
    <div className="card" style={{ marginTop: 12 }}>
      <div className="card-header" style={{ flexWrap: "wrap", gap: 8 }}>
        <span className="card-title">
          Repayments — {application.partner_name} · {application.asset_requested || "asset"}
        </span>
        <span className="text-subtle text-sm">
          {schedule.settled_count} of {schedule.count} paid · {nairaFull(schedule.outstanding)} left
          {schedule.overdue_count > 0 && <span style={{ color: "var(--rose)" }}> · {schedule.overdue_count} overdue</span>}
        </span>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr><th>#</th><th>Due</th><th>Amount</th><th>Status</th><th></th></tr>
          </thead>
          <tbody>
            {schedule.installments.map(i => (
              <tr key={i.installment_no} className={i.overdue ? "low-stock" : ""}>
                <td>{i.installment_no}</td>
                <td className="td-muted">{i.due_date ? dateStr(i.due_date) : "—"}</td>
                <td>{nairaFull(i.amount)}{i.paid > 0 && !i.settled ? ` · paid ${nairaFull(i.paid)}` : ""}</td>
                <td>
                  {i.settled ? (
                    i.confirmed >= i.amount
                      ? <span className="badge badge-green">Paid ✓ confirmed</span>
                      : <span className="badge" style={{ color: "#92400e", background: "rgba(180,83,9,0.10)" }}>
                          Paid · awaiting confirmation
                        </span>
                  ) : i.overdue ? (
                    <span className="badge" style={{ color: "#b91c1c", background: "rgba(185,28,28,0.10)" }}>Overdue</span>
                  ) : <span className="td-muted">Due</span>}
                </td>
                <td>
                  {!i.settled && (
                    <button className="btn btn-primary btn-xs" disabled={busy === i.installment_no}
                      onClick={() => pay(i)}>
                      {busy === i.installment_no ? "Saving…" : "I have paid"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card-body text-subtle text-sm">
        Each installment also appears under Suppliers, where you pay everyone else.
        A repayment counts towards your record once {application.partner_name} confirms it.
      </div>
    </div>
  );
}

function MyApplications({ applications, onWithdraw }) {
  if (!applications || applications.length === 0) return null;
  return (
    <div className="card">
      <div className="card-header"><span className="card-title">My financing applications</span></div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr><th>Partner</th><th>Item</th><th>Ref</th><th>Sent</th><th>Status</th><th></th></tr>
          </thead>
          <tbody>
            {applications.map(r => (
              <tr key={r.id}>
                <td><strong>{r.partner_name || "—"}</strong></td>
                <td>{r.asset_requested || "—"}{r.asset_value ? ` · ${nairaFull(r.asset_value)}` : ""}</td>
                <td className="td-mono td-muted">{r.application_code}</td>
                <td className="td-muted">{r.created_at ? dateStr(r.created_at) : "—"}</td>
                <td>
                  <StatusPill status={r.status} />
                  {r.decline_reason && (
                    <div className="td-muted" style={{ fontSize: 11 }}>{r.decline_reason}</div>
                  )}
                </td>
                <td>
                  {["SUBMITTED", "SHARED", "IN_REVIEW"].includes(r.status) && (
                    <button className="btn btn-ghost btn-xs text-rose" onClick={() => onWithdraw(r)}>
                      Withdraw
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}


// The score is useless if a trader can't see what moved it. Each action is the
// concrete next thing, with the business's own figures in it.
function HowToImprove({ advice }) {
  if (!advice || (advice.actions || []).length === 0) return null;
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">How to improve your score</span>
      </div>
      <div className="card-body" style={{ display: "grid", gap: 12 }}>
        {advice.actions.map((a, i) => (
          <div key={a.key} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
            <span style={{
              flexShrink: 0, width: 22, height: 22, borderRadius: 999, fontSize: 12,
              display: "grid", placeItems: "center", fontWeight: 800,
              background: "rgba(37,99,235,0.12)", color: "var(--brand)",
            }}>{i + 1}</span>
            <div>
              <div style={{ fontWeight: 600, fontSize: 13.5 }}>
                {a.label}
                {a.possible_gain > 0 && (
                  <span className="text-subtle text-sm"> · up to +{a.possible_gain} points</span>
                )}
              </div>
              <div className="text-subtle text-sm">{a.action}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Scorecard() {
  const [card, setCard] = useState(null);
  const [offers, setOffers] = useState(null);
  const [applications, setApplications] = useState([]);
  const [advice, setAdvice] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  function loadOffers() {
    return Promise.all([apiFetch("finance-offers"), apiFetch("my-applications")])
      .then(([o, r]) => { setOffers(o); setApplications(r.applications || []); });
  }

  useEffect(() => {
    Promise.all([
      apiFetch("scorecard").then(setCard),
      apiFetch("scorecard/advice").then(setAdvice).catch(() => {}),
      loadOffers(),
    ])
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  async function withdraw(r) {
    if (!window.confirm(`Withdraw your application to ${r.partner_name}? Your record will no longer be shared with them.`)) return;
    try { await apiPost(`my-applications/${r.id}/withdraw`, {}); await loadOffers(); }
    catch (e) { setError(e.message); }
  }

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
              {meaningFor(advice, c.key) && (
                <div className="text-subtle text-sm" style={{ marginTop: 3 }}>
                  {meaningFor(advice, c.key)}
                </div>
              )}
            </div>
          ))}
          {(card.not_applicable || []).length > 0 && (
            <div className="text-subtle text-sm" style={{ borderTop: "1px solid var(--border)", paddingTop: 10 }}>
              Not counted for your business:{" "}
              {card.not_applicable.map(s => s.label).join(", ")}. These need records
              you haven't kept, so they don't count against your score.
            </div>
          )}
        </div>
      </div>

      <HowToImprove advice={advice} />

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
          <span className="card-title"><TrendingUp size={15} /> Financing</span>
        </div>
        <div className="card-body">
          <p className="text-subtle text-sm" style={{ marginTop: 0 }}>
            Offers from financiers live with everything else on{" "}
            <Link to="/opportunities">Opportunities</Link> — one place to look. This page is
            your record: what you have built, and what to improve.
          </p>
          {offers && (offers.offers || []).length > 0 && (
            <Link className="btn btn-primary btn-sm" to="/opportunities">
              See {offers.offers.length} financing offer{offers.offers.length === 1 ? "" : "s"}
            </Link>
          )}
        </div>
      </div>

      <MyApplications applications={applications} onWithdraw={withdraw} />

      {applications.filter(a => a.status === "DELIVERED").map(a => (
        <RepaymentPlan key={a.id} application={a} onPaid={loadOffers} />
      ))}


    </>
  );
}
