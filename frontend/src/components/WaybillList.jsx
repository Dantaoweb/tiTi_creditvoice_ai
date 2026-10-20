import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../lib/api";
import { dateStr } from "../lib/format";

/* The waybills made for a receipt, an invoice or a customer — each opens to
   reprint. `query` is e.g. "tx_id=12"; `refresh` reloads it when it changes. */
export default function WaybillList({ query, refresh, title = "Waybills" }) {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    apiFetch(`waybills?${query}`).then(d => setRows(d.waybills || [])).catch(() => setRows([]));
  }, [query, refresh]);
  if (!rows.length) return null;
  return (
    <div className="no-print" style={{ maxWidth: 480, margin: "10px auto", fontSize: 13 }}>
      <div className="td-muted" style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4 }}>
        {title}
      </div>
      {rows.map(w => (
        <Link key={w.id} to={`/waybills/${w.id}`} style={{
          display: "block", padding: "6px 0", borderBottom: "1px solid var(--border)",
          textDecoration: w.cancelled ? "line-through" : "none", color: "inherit",
        }}>
          <strong>{w.number}</strong> · {dateStr(w.created_at)} · {w.what}
          {w.driver_name || w.vehicle ? ` · ${[w.driver_name, w.vehicle].filter(Boolean).join(", ")}` : ""}
          {w.cancelled ? " (cancelled)" : ""}
        </Link>
      ))}
    </div>
  );
}
