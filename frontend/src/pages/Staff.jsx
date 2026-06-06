import { useEffect, useState } from "react";
import { useApp } from "../context/AppContext";
import { apiFetch } from "../lib/api";
import { nairaFull } from "../lib/format";
import MetricCard from "../components/MetricCard";
import EmptyState from "../components/EmptyState";
import Skeleton from "../components/Skeleton";

export default function Staff() {
  const { ownerPhone, period } = useApp();
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  useEffect(() => {
    setLoading(true);
    apiFetch("staff", { owner_phone: ownerPhone, period })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [ownerPhone, period]);

  const staff = data?.staff || [];
  const totalSales    = staff.reduce((s, m) => s + m.sales,    0);
  const totalPayments = staff.reduce((s, m) => s + m.payments, 0);
  const totalTx       = staff.reduce((s, m) => s + m.transactions, 0);

  return (
    <>
      {error && <div style={{ color: "var(--rose)" }}>{error}</div>}

      <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(3, minmax(160px, 1fr))" }}>
        <MetricCard loading={loading} label="Total staff sales"    value={nairaFull(totalSales)}    color="green" />
        <MetricCard loading={loading} label="Total payments taken" value={nairaFull(totalPayments)} color="blue"  />
        <MetricCard loading={loading} label="Total transactions"   value={totalTx.toLocaleString()} color="amber" />
      </div>

      {loading ? (
        <div className="card"><Skeleton rows={4} /></div>
      ) : staff.length === 0 ? (
        <div className="card"><EmptyState text="No staff found. Add staff from WhatsApp: 'add staff'." /></div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 16 }}>
          {staff.map((member) => (
            <div key={member.id} className="card">
              <div className="card-header">
                <div>
                  <div className="card-title">{(member.name || "Staff").replace(/\b\w/g, c => c.toUpperCase())}</div>
                  <div className="card-subtitle">{member.phone}</div>
                </div>
                <div className="badge badge-blue">{member.role}</div>
              </div>
              <div className="card-body" style={{ display: "grid", gap: 14 }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                  <div className="parsed-cell">
                    <span>Sales</span>
                    <strong>{nairaFull(member.sales)}</strong>
                  </div>
                  <div className="parsed-cell">
                    <span>Payments</span>
                    <strong>{nairaFull(member.payments)}</strong>
                  </div>
                  <div className="parsed-cell">
                    <span>Transactions</span>
                    <strong>{member.transactions.toLocaleString()}</strong>
                  </div>
                  <div className="parsed-cell">
                    <span>Customers served</span>
                    <strong>{member.customers_served.toLocaleString()}</strong>
                  </div>
                </div>

                {member.top_products?.length > 0 && (
                  <div>
                    <div className="form-label" style={{ marginBottom: 8 }}>Top products</div>
                    <div style={{ display: "grid", gap: 6 }}>
                      {member.top_products.map((p, i) => (
                        <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                          <span>{(p.product || "—").replace(/\b\w/g, c => c.toUpperCase())}</span>
                          <span className="text-muted">{p.qty} unit(s) · {nairaFull(p.total)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
