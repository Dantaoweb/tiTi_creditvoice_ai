import { useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { BarChart, COLORS, HBars, LineChart, naira } from "./Charts";

/* The Insights graphs: how the business moves over the chosen period, in its
   own words (Fees, Rent, Jobs…). Profit and expenses only for the owner and
   authorised staff — the server leaves them out for everyone else. */

const PERIOD_WORD = { TODAY: "today", WEEK: "this week", MONTH: "the last 30 days", YEAR: "the last 12 months" };

function GraphCard({ title, sub, children }) {
  return (
    <div className="card">
      <div className="card-header" style={{ flexWrap: "wrap", gap: 6 }}>
        <span className="card-title">{title}</span>
        {sub && <span className="td-muted" style={{ fontSize: 12.5 }}>{sub}</span>}
      </div>
      <div className="card-body" style={{ paddingTop: 6 }}>{children}</div>
    </div>
  );
}

export default function BusinessGraphs({ period }) {
  const [c, setC] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    setC(null); setErr("");
    apiFetch("reports/charts", period ? { period } : {}).then(setC).catch(e => setErr(e.message));
  }, [period]);

  if (err) return <div className="card card-body" style={{ color: "var(--rose)" }}>{err}</div>;
  if (!c) return <div className="card card-body td-muted">Drawing your graphs…</div>;

  const L = c.labels, t = c.totals;
  const when = PERIOD_WORD[period] || "all time";
  const nothing = !t.sales && !t.collected;
  if (nothing) {
    return (
      <div className="card card-body td-muted">
        No sales or payments recorded {when} yet — your graphs will appear as soon as you record some.
      </div>
    );
  }
  const busiestDay = [...c.busy_days].sort((a, b) => b.amount - a.amount)[0];
  const busiestHour = [...c.busy_hours].sort((a, b) => b.amount - a.amount)[0];

  return (
    <div style={{ display: "grid", gap: 14, gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 420px), 1fr))" }}>
      <GraphCard title={`${L.sales} over time`} sub={`${naira(t.sales)} ${when}`}>
        <BarChart data={c.series} stacked keys={[
          { key: "cash", label: L.cash, color: COLORS.brand },
          { key: "credit", label: L.credit, color: COLORS.amber },
        ]} />
      </GraphCard>

      <GraphCard title="Money in vs new debt"
        sub={t.collected >= t.new_debt ? "You're collecting more than you're giving on credit ✓"
                                       : "More credit given than money collected"}>
        <LineChart data={c.series} keys={[
          { key: "collected", label: L.collected, color: COLORS.green },
          { key: "new_debt", label: "New debt", color: COLORS.rose },
        ]} />
      </GraphCard>

      <GraphCard title="What customers owe you" sub={`${naira(t.owed_now)} now`}>
        <LineChart data={c.series} area keys={[{ key: "owed", label: "Owed to you", color: COLORS.rose }]} />
      </GraphCard>

      {c.profit_hidden ? null : (
        <GraphCard title="Profit and expenses"
          sub={t.expenses ? `${naira(t.profit - t.expenses)} after expenses` : `${naira(t.profit)} gross profit`}>
          <BarChart data={c.series} keys={[
            { key: "profit", label: "Gross profit", color: COLORS.green },
            { key: "expenses", label: "Expenses", color: COLORS.rose },
          ]} />
          <div className="td-muted" style={{ fontSize: 12, marginTop: 4 }}>
            Profit counts sales whose cost price is known. Record expenses on the Expenses page to see what you keep.
          </div>
        </GraphCard>
      )}

      <GraphCard title="What brings in the money" sub={`Top ${c.top.length} ${when}`}>
        {c.top.length ? <HBars items={c.top} valueKey="revenue" /> : <span className="td-muted">No sales yet.</span>}
      </GraphCard>

      <GraphCard title="Busiest days and hours"
        sub={busiestDay?.amount ? `Busiest: ${busiestDay.label}${busiestHour?.amount ? `, around ${busiestHour.label}` : ""}` : undefined}>
        <HBars items={c.busy_days} color={COLORS.blue} />
        {period !== "TODAY" && <div style={{ height: 14 }} />}
        <BarChart data={c.busy_hours.map(h => ({ label: h.label, amount: h.amount }))} height={150}
          keys={[{ key: "amount", label: "Sales by hour", color: COLORS.blue }]} />
      </GraphCard>
    </div>
  );
}
