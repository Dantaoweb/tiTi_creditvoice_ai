import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus } from "lucide-react";
import { apiFetch } from "../lib/api";
import { dateStr, nairaFull } from "../lib/format";

const TONE = { draft: "var(--muted)", sent: "#1d4ed8", part_received: "#b45309", received: "#166534",
               closed: "var(--muted)", cancelled: "var(--muted)" };

/* Purchase orders: what you've ordered from suppliers, and what's still
   expected. Low-stock products are grouped by their usual supplier so an
   order can be started in one tap. */
export default function PurchaseOrders() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [groups, setGroups] = useState([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    apiFetch("purchase-orders").then(d => setRows(d.orders || [])).catch(e => setErr(e.message));
    apiFetch("purchase-orders/suggestions").then(d => setGroups(d.groups || [])).catch(() => {});
  }, []);

  function orderFrom(g) {
    navigate("/purchase-orders/new", { state: {
      supplier_name: g.supplier || "",
      lines: g.items.map(i => ({ inventory_item_id: i.inventory_item_id, product: i.product, unit: i.unit || "",
                                 quantity: String(i.suggest), unit_cost: i.unit_cost ? String(i.unit_cost) : "" })),
    } });
  }

  return (
    <div style={{ display: "grid", gap: 14, maxWidth: 760 }}>
      <div className="card">
        <div className="card-header">
          <span className="card-title">Purchase orders</span>
          <Link to="/purchase-orders/new" className="btn btn-primary btn-sm"><Plus size={14} /> New order</Link>
        </div>
        <div className="td-muted" style={{ padding: "0 16px 12px", fontSize: 13 }}>
          Order from your suppliers before goods come. Nothing is owed and no stock moves until you receive
          what arrives against the order.
        </div>
        {err && <div className="modal-error" style={{ margin: 12 }}>{err}</div>}
      </div>

      {groups.length > 0 && (
        <div className="card">
          <div className="card-header"><span className="card-title">Running low</span></div>
          {groups.map(g => (
            <div key={g.supplier || "none"} style={{ padding: "10px 16px", borderBottom: "1px solid var(--border)", fontSize: 13 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                <strong>{g.supplier || "No usual supplier"}</strong>
                <button className="btn btn-secondary btn-sm" onClick={() => orderFrom(g)}>
                  Order {g.supplier ? `from ${g.supplier}` : "these"}
                </button>
              </div>
              <div className="td-muted">
                {g.items.map(i => `${i.product} (${i.in_stock} left)`).join(" · ")}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <div className="card-header"><span className="card-title">Orders</span></div>
        {rows === null ? <div className="td-muted" style={{ padding: 16 }}>Loading…</div>
          : rows.length === 0 ? <div className="td-muted" style={{ padding: 16 }}>No orders yet.</div>
          : rows.map(r => (
            <Link key={r.id} to={`/purchase-orders/${r.id}`} style={{
              display: "flex", justifyContent: "space-between", gap: 10, padding: "12px 16px",
              borderBottom: "1px solid var(--border)", color: "inherit", textDecoration: "none", flexWrap: "wrap",
            }}>
              <span><strong>{r.number}</strong> · {r.supplier || "—"}
                <span className="td-muted"> · {r.items} item{r.items === 1 ? "" : "s"} · {nairaFull(r.total)}
                  {r.expected_date ? ` · by ${dateStr(r.expected_date)}` : ""}</span></span>
              <span style={{ fontSize: 12, fontWeight: 700, color: TONE[r.status] }}>{r.status_label}</span>
            </Link>
          ))}
      </div>
    </div>
  );
}
