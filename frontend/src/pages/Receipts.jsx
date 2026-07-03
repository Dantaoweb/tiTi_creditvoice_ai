import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../lib/api";
import { nairaFull, dateStr } from "../lib/format";

export default function Receipts() {
  const [receipts, setReceipts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    apiFetch("pos/receipts")
      .then(d => setReceipts(d.receipts || []))
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="page-loading">Loading receipts…</div>;

  return (
    <div className="card" style={{ maxWidth: 640 }}>
      <div className="card-header">
        <span className="card-title">Receipts</span>
      </div>
      {err && <div className="pos-error" style={{ margin: 12 }}>{err}</div>}
      {receipts.length === 0 ? (
        <div className="td-muted" style={{ padding: 16 }}>
          No receipts yet. Record a sale to create one.
        </div>
      ) : (
        <div>
          {receipts.map(r => (
            <button
              key={r.id}
              onClick={() => navigate(`/pos/receipt/${r.id}`)}
              style={{
                display: "flex", justifyContent: "space-between", alignItems: "center",
                width: "100%", padding: "12px 16px", background: "none",
                border: "none", borderBottom: "1px solid var(--border)",
                cursor: "pointer", textAlign: "left",
              }}
            >
              <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
                <strong>#{r.id} · {r.customer || "Cash sale"}</strong>
                <span className="td-muted" style={{ fontSize: 12 }}>
                  {dateStr(r.created_at)}{r.type === "BUY" ? " · Credit" : ""}
                </span>
              </div>
              <strong style={{ color: r.type === "BUY" ? "#b45309" : "var(--ink)" }}>
                {nairaFull(r.total)}
              </strong>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
