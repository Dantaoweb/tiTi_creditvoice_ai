import { useState } from "react";
import EmptyState from "./EmptyState";
import Skeleton from "./Skeleton";

export default function DataTable({ columns, rows, loading, emptyText, rowClass }) {
  const [sortCol, setSortCol] = useState(null);
  const [sortDir, setSortDir] = useState("asc");

  function handleSort(col) {
    if (!col.sortKey) return;
    if (sortCol === col.sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(col.sortKey);
      setSortDir("asc");
    }
  }

  let sorted = rows || [];
  if (sortCol) {
    sorted = [...sorted].sort((a, b) => {
      const av = a[sortCol];
      const bv = b[sortCol];
      const cmp = typeof av === "number" ? av - bv : String(av ?? "").localeCompare(String(bv ?? ""));
      return sortDir === "asc" ? cmp : -cmp;
    });
  }

  if (loading) return <Skeleton rows={6} />;

  if (!sorted.length) return <EmptyState text={emptyText} />;

  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                onClick={() => handleSort(col)}
                style={{ cursor: col.sortKey ? "pointer" : "default", userSelect: "none" }}
              >
                {col.label}
                {col.sortKey && sortCol === col.sortKey && (
                  <span style={{ marginLeft: 4 }}>{sortDir === "asc" ? "↑" : "↓"}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr key={row.id ?? i} className={rowClass ? rowClass(row) : ""}>
              {columns.map((col) => (
                <td key={col.key} className={col.tdClass || ""}>
                  {col.render ? col.render(row) : row[col.key] ?? "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
