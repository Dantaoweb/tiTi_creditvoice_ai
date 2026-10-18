import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../lib/api";
import { BarChart, COLORS, naira } from "./Charts";

/* "Sales this week" at a glance on the Dashboard; the full graphs live on
   Insights. Hidden until there is something to draw. */
export default function WeekSalesMini() {
  const [c, setC] = useState(null);
  useEffect(() => { apiFetch("reports/charts", { period: "WEEK" }).then(setC).catch(() => {}); }, []);
  if (!c || !c.totals.sales) return null;
  return (
    <div className="card">
      <div className="card-header" style={{ flexWrap: "wrap", gap: 6 }}>
        <span className="card-title">{c.labels.sales} this week · {naira(c.totals.sales)}</span>
        <Link to="/insights" style={{ fontSize: 13 }}>More graphs →</Link>
      </div>
      <div className="card-body" style={{ paddingTop: 6 }}>
        <BarChart data={c.series} stacked height={150} keys={[
          { key: "cash", label: c.labels.cash, color: COLORS.brand },
          { key: "credit", label: c.labels.credit, color: COLORS.amber },
        ]} />
      </div>
    </div>
  );
}
