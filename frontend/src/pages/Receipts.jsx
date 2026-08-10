import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../lib/api";
import { nairaFull, dateStr } from "../lib/format";

export default function Receipts() {
  const [tab, setTab] = useState("sales");   // sales | supplier
  const [sales, setSales] = useState([]);
  const [supplier, setSupplier] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    setLoading(true);
    Promise.all([
      apiFetch("pos/receipts").then(d => setSales(d.receipts || [])).catch(() => {}),
      apiFetch("suppliers/receipts").then(d => setSupplier(d.receipts || [])).catch(() => {}),
    ]).catch(e => setErr(e.message)).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="page-loading">Loading receipts…</div>;

  const rows = tab === "sales" ? sales : supplier;

  return (
    <div className="card" style={{ maxWidth: 640 }}>
      <div className="card-header">
        <span className="card-title">Receipts</span>
      </div>

      {/* Sales | Supplier tabs */}
      <div style={{ display: "flex", gap: 4, padding: "0 12px", borderBottom: "1px solid var(--border)" }}>
        {[["sales", `Sales${sales.length ? ` (${sales.length})` : ""}`],
          ["supplier", `Supplier${supplier.length ? ` (${supplier.length})` : ""}`]].map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)}
            style={{
              background: "none", border: "none", cursor: "pointer", padding: "10px 14px",
              fontWeight: tab === key ? 700 : 500, fontSize: 14,
              color: tab === key ? "var(--brand)" : "var(--text-muted)",
              borderBottom: tab === key ? "2px solid var(--brand)" : "2px solid transparent", marginBottom: -1,
            }}>{label}</button>
        ))}
      </div>

      {err && <div className="pos-error" style={{ margin: 12 }}>{err}</div>}

      {rows.length === 0 ? (
        <div className="td-muted" style={{ padding: 16 }}>
          {tab === "sales"
            ? "No sale receipts yet. Record a sale to create one."
            : "No supplier receipts yet. Record stock received or pay a supplier."}
        </div>
      ) : tab === "sales" ? (
        <div>
          {sales.map(r => (
            <button key={r.id} onClick={() => navigate(`/pos/receipt/${r.id}`)} className="receipt-list-row">
              <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
                <strong>#{r.id} · {r.customer || "Cash sale"}</strong>
                <span className="td-muted" style={{ fontSize: 12 }}>
                  {dateStr(r.created_at)}{r.type === "BUY" ? " · Credit" : ""}
                </span>
              </div>
              <strong style={{ color: r.type === "BUY" ? "#b45309" : "var(--ink)" }}>{nairaFull(r.total)}</strong>
            </button>
          ))}
        </div>
      ) : (
        <div>
          {supplier.map(r => (
            <button key={`${r.kind}-${r.id}`} onClick={() => navigate(`/suppliers/receipt/${r.kind}/${r.id}`)} className="receipt-list-row">
              <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
                <strong>{r.supplier}{r.kind === "payment" ? " · Payment" : (r.label ? ` · ${r.label}` : "")}</strong>
                <span className="td-muted" style={{ fontSize: 12 }}>
                  {dateStr(r.created_at)} · {r.kind === "payment" ? "Payment" : "Stock received"}
                </span>
              </div>
              <strong style={{ color: r.kind === "payment" ? "#16a34a" : "#b45309" }}>{nairaFull(r.amount)}</strong>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
