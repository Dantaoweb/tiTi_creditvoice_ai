import { useState } from "react";
import EmptyState from "./EmptyState";
import Skeleton from "./Skeleton";

// Pass `sort` ({ col, dir }) + `onSort` to sort on the server (paged data);
// otherwise rows are sorted in the browser.
export default function DataTable({ columns, rows, loading, emptyText, rowClass, sort, onSort }) {
  const [localCol, setLocalCol] = useState(null);
  const [localDir, setLocalDir] = useState("asc");
  const sortCol = onSort ? sort?.col ?? null : localCol;
  const sortDir = onSort ? sort?.dir ?? "asc" : localDir;

  function handleSort(col) {
    if (!col.sortKey) return;
    const dir = sortCol === col.sortKey && sortDir === "asc" ? "desc" : "asc";
    if (onSort) return onSort({ col: col.sortKey, dir });
    setLocalCol(col.sortKey);
    setLocalDir(dir);
  }

  let sorted = rows || [];
  if (sortCol && !onSort) {
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
