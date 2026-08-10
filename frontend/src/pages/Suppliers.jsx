import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull, dateStr, parseAmt } from "../lib/format";
import MoneyInput from "../components/MoneyInput";
import DataTable from "../components/DataTable";
import MetricCard from "../components/MetricCard";
import { Search, Send, CheckCircle, Clock, XCircle, Plus, Trash2, ChevronDown, ChevronUp, Star } from "lucide-react";

// ── Star rating component ─────────────────────────────────────────────────────
function StarRating({ value, onChange, size = 22 }) {
  const [hovered, setHovered] = useState(0);
  const active = hovered || value;
  return (
    <div style={{ display: "flex", gap: 4 }}>
      {[1, 2, 3, 4, 5].map(n => (
        <Star
          key={n}
          size={size}
          fill={n <= active ? "#f59e0b" : "none"}
          color={n <= active ? "#f59e0b" : "#d1d5db"}
          style={{ cursor: onChange ? "pointer" : "default", transition: "color 0.1s" }}
          onMouseEnter={() => onChange && setHovered(n)}
          onMouseLeave={() => onChange && setHovered(0)}
          onClick={() => onChange && onChange(n)}
        />
      ))}
    </div>
  );
}

function StarDisplay({ avg, count }) {
  if (!avg) return null;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12 }}>
      <Star size={12} fill="#f59e0b" color="#f59e0b" />
      <span style={{ fontWeight: 700, color: "#92400e" }}>{avg}</span>
      <span style={{ color: "var(--text-muted)" }}>({count})</span>
    </span>
  );
}

// ── Tab nav ───────────────────────────────────────────────────────────────────
function TabNav({ tabs, active, onChange }) {
  return (
    <div style={{ display: "flex", gap: 0, borderBottom: "1px solid var(--border)", marginBottom: 24 }}>
      {tabs.map(t => (
        <button key={t.key} onClick={() => onChange(t.key)} style={{
          background: "none", border: "none", cursor: "pointer",
          padding: "10px 18px", fontWeight: active === t.key ? 700 : 500,
          fontSize: 14, color: active === t.key ? "var(--brand)" : "var(--text-muted)",
          borderBottom: active === t.key ? "2px solid var(--brand)" : "2px solid transparent",
          marginBottom: -1, whiteSpace: "nowrap",
        }}>
          {t.label}{t.badge ? <span style={{
            marginLeft: 6, background: "var(--rose)", color: "#fff",
            borderRadius: 99, fontSize: 10, padding: "1px 6px", fontWeight: 700,
          }}>{t.badge}</span> : null}
        </button>
      ))}
    </div>
  );
}

// ── Status badge ─────────────────────────────────────────────────────────────
function StatusBadge({ status }) {
  const map = {
    pending:  { label: "Under Review", color: "#d97706", bg: "#fef3c7", icon: <Clock size={11} /> },
    approved: { label: "Approved",     color: "#059669", bg: "#d1fae5", icon: <CheckCircle size={11} /> },
    rejected: { label: "Rejected",     color: "#dc2626", bg: "#fee2e2", icon: <XCircle size={11} /> },
  };
  const s = map[status] || map.pending;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12,
      fontWeight: 600, color: s.color, background: s.bg, borderRadius: 99, padding: "3px 10px" }}>
      {s.icon} {s.label}
    </span>
  );
}

// ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ──
// TAB 1: My Supply Chain (existing functionality)
// ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ──
function MySupplyChain() {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [payFor, setPayFor]   = useState(null);   // supplier row to pay
  const [detailId, setDetailId] = useState(null); // supplier id to view

  function reload() {
    setLoading(true);
    apiFetch("suppliers")
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }
  useEffect(reload, []);

  const suppliers   = data?.suppliers || [];
  const totalOwed   = suppliers.reduce((s, r) => s + r.balance, 0);
  const totalPaid   = suppliers.reduce((s, r) => s + r.total_paid, 0);
  const dueCount    = suppliers.filter(r => r.has_overdue).length;

  return (
    <>
      {error && <div style={{ color: "var(--rose)" }}>{error}</div>}
      <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))" }}>
        <MetricCard loading={loading} label="Total owed to suppliers" value={nairaFull(totalOwed)}  color="rose"  />
        <MetricCard loading={loading} label="Total paid to suppliers" value={nairaFull(totalPaid)}  color="green" />
        <MetricCard loading={loading} label="Suppliers with overdue"  value={dueCount}              color="amber" />
      </div>
      <div className="card">
        <div className="card-header">
          <span className="card-title">Suppliers <span className="text-subtle text-sm">({suppliers.length})</span></span>
        </div>
        <DataTable
          loading={loading}
          rows={suppliers}
          emptyText="No supplier records yet. Record a purchase via Quick Record → Stock Received."
          rowClass={r => r.has_overdue ? "low-stock" : ""}
          columns={[
            { key: "name",         label: "Supplier",        render: r => (
              <button type="button" className="link-btn td-strong" style={{ textAlign: "left" }} onClick={() => setDetailId(r.id)}>
                {(r.name || "—").replace(/\b\w/g, c => c.toUpperCase())}
              </button>
            ), sortKey: "name" },
            { key: "purchases",    label: "Purchases",       render: r => r.purchases, sortKey: "purchases" },
            { key: "total_bought", label: "Total purchased", render: r => nairaFull(r.total_bought), sortKey: "total_bought" },
            { key: "total_paid",   label: "Total paid",      render: r => nairaFull(r.total_paid), sortKey: "total_paid" },
            { key: "balance",      label: "Balance owed",    render: r => r.balance > 0
              ? <span className="text-rose font-bold">{nairaFull(r.balance)}</span>
              : <span className="text-subtle">{nairaFull(r.balance)}</span>, sortKey: "balance" },
            { key: "actions",      label: "",                render: r => (
              <button className="btn btn-secondary btn-sm" onClick={() => setPayFor(r)}>Pay</button>
            ) },
          ]}
        />
      </div>

      {payFor && (
        <SupplierPayModal supplier={payFor} onClose={() => setPayFor(null)} onDone={() => { setPayFor(null); reload(); }} />
      )}
      {detailId && (
        <SupplierDetailModal
          supplierId={detailId}
          onClose={() => setDetailId(null)}
          onPay={(sup) => { setDetailId(null); setPayFor(sup); }}
        />
      )}
      {!!(data?.recent_purchases?.length) && (
        <div className="card">
          <div className="card-header"><span className="card-title">Recent supplier purchases</span></div>
          <DataTable
            loading={false} rows={data.recent_purchases} emptyText=""
            columns={[
              { key: "supplier",   label: "Supplier",  render: r => r.supplier || "—" },
              { key: "product",    label: "Product",   render: r => r.product || "—" },
              { key: "total",      label: "Total",     render: r => nairaFull(r.total) },
              { key: "paid",       label: "Paid",      render: r => nairaFull(r.paid_amount) },
              { key: "balance",    label: "Remaining", render: r => nairaFull(r.total - r.paid_amount) },
              { key: "due_date",   label: "Due",       render: r => <span className={r.due_date && new Date(r.due_date) < new Date() ? "text-rose" : ""}>{dateStr(r.due_date)}</span> },
              { key: "created_at", label: "Date",      render: r => <span className="td-muted">{dateStr(r.created_at)}</span> },
            ]}
          />
        </div>
      )}
    </>
  );
}

// Record a payment to a supplier (pays down what you owe them).
function SupplierPayModal({ supplier, onClose, onDone }) {
  const [amount, setAmount] = useState("");
  const [note, setNote]     = useState("");
  const [busy, setBusy]     = useState(false);
  const [err, setErr]       = useState("");

  async function submit(e) {
    e.preventDefault();
    const amt = parseAmt(amount);
    if (!amt || amt <= 0) { setErr("Enter an amount."); return; }
    setBusy(true); setErr("");
    try {
      await apiPost(`suppliers/${supplier.id}/pay`, { amount: amt, note: note.trim() });
      onDone();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <form className="modal" onSubmit={submit}>
        <div className="modal-header">
          <span className="modal-title">Pay {(supplier.name || "").replace(/\b\w/g, c => c.toUpperCase())}</span>
          <button type="button" className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          {supplier.balance > 0 && (
            <div className="td-muted" style={{ marginBottom: 10 }}>
              You currently owe <strong className="text-rose">{nairaFull(supplier.balance)}</strong>.
            </div>
          )}
          <div className="form-group">
            <label className="form-label">Amount (₦) *</label>
            <MoneyInput value={amount} onChange={setAmount} placeholder="0" />
          </div>
          <div className="form-group">
            <label className="form-label">Note <span className="text-subtle">(optional)</span></label>
            <input value={note} onChange={e => setNote(e.target.value)} placeholder="e.g. part payment, transfer ref…" />
          </div>
          {err && <div className="modal-error">{err}</div>}
        </div>
        <div className="modal-footer">
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : "Record payment"}</button>
        </div>
      </form>
    </div>
  );
}

// A supplier's purchases + payments history with running balance.
function SupplierDetailModal({ supplierId, onClose, onPay }) {
  const [d, setD]     = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    apiFetch(`suppliers/${supplierId}`).then(setD).catch(e => setErr(e.message));
  }, [supplierId]);

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">{d ? (d.name || "").replace(/\b\w/g, c => c.toUpperCase()) : "Supplier"}</span>
          <button type="button" className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          {err && <div className="modal-error">{err}</div>}
          {!d ? <p className="td-muted">Loading…</p> : (
            <>
              <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(3, 1fr)", marginBottom: 14 }}>
                <MetricCard label="Purchased" value={nairaFull(d.total_bought)} />
                <MetricCard label="Paid"      value={nairaFull(d.total_paid)} color="green" />
                <MetricCard label="Owed"      value={nairaFull(d.balance)} color={d.balance > 0 ? "rose" : "green"} />
              </div>
              <button className="btn btn-primary" style={{ width: "100%", marginBottom: 16 }}
                onClick={() => onPay({ id: d.id, name: d.name, balance: d.balance })}>
                Pay this supplier
              </button>

              <div className="card-title" style={{ marginBottom: 6 }}>Purchases</div>
              {d.purchases.length === 0 ? <p className="td-muted">None yet.</p> : (
                <div style={{ display: "grid", gap: 6, marginBottom: 14 }}>
                  {d.purchases.map(p => (
                    <div key={p.id} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, borderBottom: "1px solid var(--border)", paddingBottom: 5 }}>
                      <span>{(p.product || "—")}{p.quantity ? ` · ${p.quantity}${p.unit || ""}` : ""}<br /><span className="td-muted" style={{ fontSize: 11 }}>{dateStr(p.created_at)}</span></span>
                      <span style={{ textAlign: "right" }}>{nairaFull(p.total)}<br /><span className="td-muted" style={{ fontSize: 11 }}>paid {nairaFull(p.paid_amount)}</span></span>
                    </div>
                  ))}
                </div>
              )}

              <div className="card-title" style={{ marginBottom: 6 }}>Payments</div>
              {d.payments.length === 0 ? <p className="td-muted">None yet.</p> : (
                <div style={{ display: "grid", gap: 6 }}>
                  {d.payments.map(p => (
                    <div key={p.id} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, borderBottom: "1px solid var(--border)", paddingBottom: 5 }}>
                      <span className="td-muted">{dateStr(p.created_at)}{p.product ? ` · ${p.product}` : ""}</span>
                      <span className="text-green font-bold">{nairaFull(p.amount)}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ──
// TAB 2: Find Suppliers (directory)
// ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ──
function ContactModal({ supplier, onClose }) {
  const [product, setProduct]   = useState("");
  const [msg, setMsg]           = useState("");
  const [busy, setBusy]         = useState(false);
  const [done, setDone]         = useState(false);
  const [err, setErr]           = useState("");
  const [stars, setStars]       = useState(0);
  const [review, setReview]     = useState("");
  const [rated, setRated]       = useState(false);
  const [ratingBusy, setRatingBusy] = useState(false);

  async function send(e) {
    e.preventDefault();
    if (!msg.trim()) { setErr("Enter a message."); return; }
    setBusy(true); setErr("");
    try {
      await apiPost(`verified-suppliers/${supplier.id}/contact`, {
        product_interest: product,
        message: msg,
      });
      setDone(true);
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function submitRating() {
    if (!stars) return;
    setRatingBusy(true);
    try {
      await apiPost(`verified-suppliers/${supplier.id}/rate`, { rating: stars, review });
      setRated(true);
    } catch { /* non-blocking */ }
    finally { setRatingBusy(false); }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-title">Contact {supplier.business_name}</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        {done ? (
          <div style={{ padding: "24px 0", textAlign: "center" }}>
            <CheckCircle size={40} color="var(--green)" style={{ marginBottom: 12 }} />
            <p style={{ fontWeight: 600, marginBottom: 4 }}>Message sent!</p>
            <p style={{ color: "var(--text-muted)", fontSize: 13, marginBottom: 20 }}>
              {supplier.business_name} will see your enquiry in their inbox.
            </p>

            {!rated ? (
              <div style={{ borderTop: "1px solid var(--border)", paddingTop: 20 }}>
                <p style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
                  Have you worked with them before? Rate your experience.
                </p>
                <div style={{ display: "flex", justifyContent: "center", marginBottom: 12 }}>
                  <StarRating value={stars} onChange={setStars} size={28} />
                </div>
                {stars > 0 && (
                  <textarea value={review} onChange={e => setReview(e.target.value)}
                    rows={2} placeholder="Optional: share what went well or what to know…"
                    style={{ width: "100%", marginBottom: 10, resize: "none" }} />
                )}
                <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
                  {stars > 0 && (
                    <button className="btn btn-primary" onClick={submitRating} disabled={ratingBusy}>
                      {ratingBusy ? "Saving…" : "Submit rating"}
                    </button>
                  )}
                  <button className="btn btn-secondary" onClick={onClose}>
                    {stars > 0 ? "Skip" : "Close"}
                  </button>
                </div>
              </div>
            ) : (
              <>
                <p style={{ color: "var(--green)", fontSize: 13, fontWeight: 600 }}>Rating saved — thank you!</p>
                <button className="btn btn-primary" style={{ marginTop: 12 }} onClick={onClose}>Close</button>
              </>
            )}
          </div>
        ) : (
          <form onSubmit={send} style={{ display: "flex", flexDirection: "column", gap: 14, padding: "4px 0" }}>
            <div className="form-group">
              <label className="form-label">Product you're asking about</label>
              <input value={product} onChange={e => setProduct(e.target.value)}
                placeholder="e.g. 50kg rice bags" />
            </div>
            <div className="form-group">
              <label className="form-label">Your message *</label>
              <textarea value={msg} onChange={e => setMsg(e.target.value)} rows={4}
                placeholder={`Hi ${supplier.business_name.split(" ")[0]}, I'm interested in...`}
                style={{ resize: "vertical" }} />
            </div>
            {err && <div className="login-error">{err}</div>}
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
              <button type="submit" className="btn btn-primary" disabled={busy}>
                {busy ? "Sending…" : <><Send size={13} style={{ marginRight: 6 }} />Send Message</>}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

function SupplierCard({ s, onContact }) {
  const [expanded, setExpanded] = useState(false);
  const typeLabel = s.supplier_type_label || s.supplier_type;

  return (
    <div className="card" style={{ marginBottom: 12, padding: 0, overflow: "hidden" }}>
      <div style={{ padding: "16px 20px", display: "flex", alignItems: "flex-start", gap: 12 }}>
        <div style={{
          width: 44, height: 44, borderRadius: "50%", background: "var(--brand)",
          color: "#fff", display: "flex", alignItems: "center", justifyContent: "center",
          fontWeight: 800, fontSize: 17, flexShrink: 0,
        }}>
          {(s.business_name || "?")[0].toUpperCase()}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <strong style={{ fontSize: 15 }}>{s.business_name}</strong>
            <span style={{ fontSize: 11, background: "var(--surface)", color: "var(--text-muted)",
              borderRadius: 99, padding: "2px 8px", border: "1px solid var(--border)" }}>
              {typeLabel}
            </span>
          </div>
          {s.bio && <p style={{ fontSize: 13, color: "var(--text-muted)", margin: "4px 0 6px", lineHeight: 1.5 }}>{s.bio}</p>}
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: 12, color: "var(--text-muted)", alignItems: "center" }}>
            {s.states_covered?.length > 0 && (
              <span>📍 {s.states_covered.slice(0,3).join(", ")}{s.states_covered.length > 3 ? ` +${s.states_covered.length - 3} more` : ""}</span>
            )}
            {s.can_deliver && <span>🚚 Delivers</span>}
            {s.products?.length > 0 && <span>📦 {s.products.length} product{s.products.length > 1 ? "s" : ""}</span>}
            <StarDisplay avg={s.avg_rating} count={s.rating_count} />
          </div>
        </div>
        <button className="btn btn-primary" style={{ flexShrink: 0, fontSize: 13 }} onClick={() => onContact(s)}>
          Contact
        </button>
      </div>

      {s.products?.length > 0 && (
        <>
          <button onClick={() => setExpanded(!expanded)} style={{
            width: "100%", border: "none", borderTop: "1px solid var(--border)",
            background: "var(--surface)", padding: "8px 20px", cursor: "pointer",
            display: "flex", alignItems: "center", gap: 6, fontSize: 12,
            color: "var(--text-muted)", fontWeight: 500,
          }}>
            {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            {expanded ? "Hide products" : `View ${s.products.length} product${s.products.length > 1 ? "s" : ""}`}
          </button>
          {expanded && (
            <div style={{ borderTop: "1px solid var(--border)" }}>
              {s.products.map(p => (
                <div key={p.id} style={{
                  padding: "12px 20px", borderBottom: "1px solid var(--border)",
                  display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", fontSize: 13,
                }}>
                  <strong style={{ minWidth: 0 }}>{p.product_name}</strong>
                  {p.min_order_qty && (
                    <span style={{ color: "var(--text-muted)" }}>
                      Min: {p.min_order_qty} {p.min_order_unit || "units"}
                    </span>
                  )}
                  {p.available_sizes?.length > 0 && (
                    <span style={{ color: "var(--text-muted)" }}>
                      Sizes: {p.available_sizes.join(", ")}
                    </span>
                  )}
                  {p.price_range && (
                    <span style={{ color: "var(--green)", fontWeight: 600 }}>{p.price_range}</span>
                  )}
                  {p.quality_notes && (
                    <span style={{ color: "var(--text-muted)", fontStyle: "italic" }}>{p.quality_notes}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function FindSuppliers() {
  const [suppliers, setSuppliers] = useState([]);
  const [meta, setMeta]           = useState({ states: [], supplier_types: [] });
  const [loading, setLoading]     = useState(true);
  const [product, setProduct]     = useState("");
  const [state, setState]         = useState("");
  const [stype, setStype]         = useState("");
  const [contacting, setContacting] = useState(null);

  const load = useCallback((p = "", s = "", t = "") => {
    setLoading(true);
    apiFetch("verified-suppliers/directory", { product: p, state: s, supplier_type: t })
      .then(d => setSuppliers(d.suppliers || []))
      .catch(() => setSuppliers([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    apiFetch("verified-suppliers/meta").then(setMeta).catch(() => {});
    load();
  }, [load]);

  function search(e) { e.preventDefault(); load(product, state, stype); }

  return (
    <>
      <div className="card" style={{ marginBottom: 20 }}>
        <form onSubmit={search} style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div className="form-group" style={{ flex: "1 1 160px", marginBottom: 0 }}>
            <label className="form-label">Product</label>
            <input value={product} onChange={e => setProduct(e.target.value)} placeholder="e.g. rice, palm oil…" />
          </div>
          <div className="form-group" style={{ flex: "1 1 140px", marginBottom: 0 }}>
            <label className="form-label">State</label>
            <select value={state} onChange={e => setState(e.target.value)}>
              <option value="">All states</option>
              {meta.states.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div className="form-group" style={{ flex: "1 1 160px", marginBottom: 0 }}>
            <label className="form-label">Type</label>
            <select value={stype} onChange={e => setStype(e.target.value)}>
              <option value="">All types</option>
              {meta.supplier_types.map(t => <option key={t.key} value={t.key}>{t.label}</option>)}
            </select>
          </div>
          <button type="submit" className="btn btn-primary" style={{ height: 36 }}>
            <Search size={14} /> Search
          </button>
        </form>
      </div>

      {loading ? (
        <p style={{ color: "var(--text-muted)" }}>Searching suppliers…</p>
      ) : suppliers.length === 0 ? (
        <div style={{ textAlign: "center", padding: "40px 0", color: "var(--text-muted)" }}>
          <p style={{ fontSize: 15, fontWeight: 600 }}>No verified suppliers found</p>
          <p style={{ fontSize: 13 }}>Try a different product or region, or check back later as more suppliers join.</p>
        </div>
      ) : (
        <div>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 16 }}>
            {suppliers.length} verified supplier{suppliers.length > 1 ? "s" : ""} found
          </p>
          {suppliers.map(s => (
            <SupplierCard key={s.id} s={s} onContact={setContacting} />
          ))}
        </div>
      )}

      {contacting && (
        <ContactModal supplier={contacting} onClose={() => setContacting(null)} />
      )}
    </>
  );
}

// ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ──
// TAB 3: Supplier Profile (apply / view status / edit / inbox)
// ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ──

const EMPTY_PRODUCT = { product_name: "", category: "", available_sizes: [], min_order_qty: "", min_order_unit: "", price_range: "", quality_notes: "" };

function ProductRow({ p, onChange, onRemove, index }) {
  const [sizeInput, setSizeInput] = useState("");

  function addSize() {
    if (!sizeInput.trim()) return;
    onChange(index, { ...p, available_sizes: [...(p.available_sizes || []), sizeInput.trim()] });
    setSizeInput("");
  }

  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 14, marginBottom: 12, background: "var(--surface)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
        <strong style={{ fontSize: 13 }}>Product {index + 1}</strong>
        <button type="button" onClick={() => onRemove(index)} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--rose)" }}>
          <Trash2 size={14} />
        </button>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label className="form-label">Product name *</label>
          <input value={p.product_name} onChange={e => onChange(index, { ...p, product_name: e.target.value })} placeholder="e.g. Parboiled Rice" />
        </div>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label className="form-label">Category</label>
          <input value={p.category} onChange={e => onChange(index, { ...p, category: e.target.value })} placeholder="e.g. Grains" />
        </div>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label className="form-label">Min. order qty</label>
          <MoneyInput value={p.min_order_qty} onChange={v => onChange(index, { ...p, min_order_qty: v })} placeholder="e.g. 50" />
        </div>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label className="form-label">Unit</label>
          <input value={p.min_order_unit} onChange={e => onChange(index, { ...p, min_order_unit: e.target.value })} placeholder="e.g. bags, kg, cartons" />
        </div>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label className="form-label">Price range (optional)</label>
          <input value={p.price_range} onChange={e => onChange(index, { ...p, price_range: e.target.value })} placeholder="e.g. ₦45,000–₦48,000/bag" />
        </div>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label className="form-label">Quality notes (optional)</label>
          <input value={p.quality_notes} onChange={e => onChange(index, { ...p, quality_notes: e.target.value })} placeholder="e.g. Grade A, NAFDAC certified" />
        </div>
      </div>
      <div className="form-group" style={{ marginTop: 10, marginBottom: 0 }}>
        <label className="form-label">Available sizes / packs</label>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
          {(p.available_sizes || []).map((sz, i) => (
            <span key={i} style={{ background: "var(--brand)", color: "#fff", borderRadius: 99,
              fontSize: 12, padding: "2px 10px", display: "flex", alignItems: "center", gap: 6 }}>
              {sz}
              <button type="button" onClick={() => onChange(index, { ...p, available_sizes: p.available_sizes.filter((_, j) => j !== i) })}
                style={{ background: "none", border: "none", color: "#fff", cursor: "pointer", padding: 0, lineHeight: 1 }}>×</button>
            </span>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <input value={sizeInput} onChange={e => setSizeInput(e.target.value)} placeholder="e.g. 50kg bag" onKeyDown={e => e.key === "Enter" && (e.preventDefault(), addSize())} />
          <button type="button" className="btn btn-secondary" onClick={addSize} style={{ whiteSpace: "nowrap" }}>Add</button>
        </div>
      </div>
    </div>
  );
}

function SupplierProfileTab({ userPlan }) {
  const [profile, setProfile] = useState(null);
  const [inbox, setInbox]     = useState([]);
  const [unread, setUnread]   = useState(0);
  const [meta, setMeta]       = useState({ states: [], supplier_types: [] });
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy]       = useState(false);
  const [err, setErr]         = useState("");
  const [ok, setOk]           = useState("");
  const [inboxView, setInboxView] = useState(false);

  // Form state
  const [stype, setStype]         = useState("");
  const [bio, setBio]             = useState("");
  const [states, setStates]       = useState([]);
  const [canDeliver, setCanDeliver] = useState(false);
  const [deliveryNotes, setDeliveryNotes] = useState("");
  const [cac, setCac]             = useState("");
  const [products, setProducts]   = useState([{ ...EMPTY_PRODUCT }]);

  const isPro = ["PRO", "PREMIUM"].includes((userPlan || "").toUpperCase());

  useEffect(() => {
    Promise.all([
      apiFetch("verified-suppliers/profile"),
      apiFetch("verified-suppliers/meta"),
    ]).then(([pd, md]) => {
      setMeta(md);
      if (pd.profile) {
        const p = pd.profile;
        setProfile(p);
        setStype(p.supplier_type);
        setBio(p.bio);
        setStates(p.states_covered || []);
        setCanDeliver(p.can_deliver);
        setDeliveryNotes(p.delivery_notes);
        setCac(p.cac_number);
        setProducts(p.products?.length ? p.products.map(pr => ({
          product_name: pr.product_name, category: pr.category,
          available_sizes: pr.available_sizes, min_order_qty: pr.min_order_qty || "",
          min_order_unit: pr.min_order_unit, price_range: pr.price_range, quality_notes: pr.quality_notes,
        })) : [{ ...EMPTY_PRODUCT }]);
      }
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (profile?.verification_status === "approved") {
      apiFetch("verified-suppliers/inbox")
        .then(d => { setInbox(d.messages || []); setUnread(d.unread || 0); })
        .catch(() => {});
    }
  }, [profile]);

  function toggleState(s) {
    setStates(prev => prev.includes(s) ? prev.filter(x => x !== s) : [...prev, s]);
  }

  function updateProduct(i, val) { setProducts(prev => prev.map((p, j) => j === i ? val : p)); }
  function removeProduct(i)      { setProducts(prev => prev.filter((_, j) => j !== i)); }

  async function submit(e) {
    e.preventDefault();
    setErr(""); setOk("");
    if (!stype) { setErr("Select your supplier type."); return; }
    if (!products.some(p => p.product_name.trim())) { setErr("Add at least one product."); return; }
    setBusy(true);
    try {
      const body = {
        supplier_type: stype, bio, states_covered: states,
        can_deliver: canDeliver, delivery_notes: deliveryNotes, cac_number: cac,
        products: products.filter(p => p.product_name.trim()).map(p => ({
          ...p,
          min_order_qty: p.min_order_qty ? parseAmt(p.min_order_qty) : null,
          available_sizes: p.available_sizes || [],
        })),
      };
      const isEdit = profile?.verification_status === "approved" && editing;
      if (isEdit) {
        await apiFetch("verified-suppliers/profile", {}, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        setOk("Profile updated.");
        setEditing(false);
      } else {
        const res = await apiPost("verified-suppliers/apply", body);
        setOk(res.message || "Application submitted.");
      }
      const pd = await apiFetch("verified-suppliers/profile");
      setProfile(pd.profile);
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function markRead(id) {
    await apiFetch(`verified-suppliers/messages/${id}/read`, {}, { method: "PATCH" });
    setInbox(prev => prev.map(m => m.id === id ? { ...m, status: "read" } : m));
    setUnread(prev => Math.max(0, prev - 1));
  }

  if (loading) return <p style={{ color: "var(--text-muted)" }}>Loading…</p>;

  // ── Not PRO: show value prop + upgrade prompt ───────────────────────────
  if (!isPro && !profile) {
    return (
      <div className="card" style={{ maxWidth: 560, margin: "0 auto", padding: 32, textAlign: "center" }}>
        <div style={{ fontSize: 40, marginBottom: 12 }}>🏭</div>
        <h2 style={{ fontSize: 18, fontWeight: 800, marginBottom: 8 }}>List Your Business as a Verified Supplier</h2>
        <p style={{ color: "var(--text-muted)", fontSize: 14, lineHeight: 1.7, marginBottom: 20 }}>
          Get discovered by hundreds of CreditVoice retailers searching for your product.
          tiTi recommends you automatically when a retailer runs low on what you supply.
        </p>
        <div style={{ textAlign: "left", marginBottom: 24, display: "flex", flexDirection: "column", gap: 10 }}>
          {[
            "🔍 Free visibility — no ads, no middlemen",
            "📲 Retailers contact you directly through CreditVoice",
            "🤖 tiTi recommends you when retailers are low on your products",
            "✅ Verified badge that signals trust and legitimacy",
            "📦 List your products with sizes, MOQ, and price range",
          ].map((b, i) => (
            <div key={i} style={{ display: "flex", gap: 10, fontSize: 14 }}>{b}</div>
          ))}
        </div>
        <div style={{ background: "#fef3c7", border: "1px solid #fcd34d", borderRadius: 8, padding: "12px 16px", marginBottom: 20, fontSize: 13 }}>
          <Star size={13} style={{ color: "#d97706", marginRight: 6 }} />
          <strong>Pro plan feature.</strong> Upgrade to Pro or Premium to apply for Verified Supplier status.
        </div>
        <Link to="/upgrade" className="btn btn-primary" style={{ justifyContent: "center" }}>
          Upgrade to Pro
        </Link>
      </div>
    );
  }

  // ── Inbox view ─────────────────────────────────────────────────────────
  if (inboxView && profile?.verification_status === "approved") {
    return (
      <>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
          <button className="btn btn-secondary" onClick={() => setInboxView(false)}>← Back to profile</button>
          <strong style={{ fontSize: 15 }}>Enquiries Inbox</strong>
          {unread > 0 && <span style={{ background: "var(--rose)", color: "#fff", borderRadius: 99, fontSize: 11, padding: "2px 8px", fontWeight: 700 }}>{unread} unread</span>}
        </div>
        {inbox.length === 0 ? (
          <div style={{ textAlign: "center", padding: "40px 0", color: "var(--text-muted)" }}>
            <p>No messages yet. Once retailers find your listing and reach out, they'll appear here.</p>
          </div>
        ) : (
          inbox.map(m => (
            <div key={m.id} className="card" style={{
              marginBottom: 12, padding: 16,
              borderLeft: `4px solid ${m.status === "unread" ? "var(--brand)" : "var(--border)"}`,
            }} onClick={() => m.status === "unread" && markRead(m.id)}>
              <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
                <strong>{m.from_business_name}</strong>
                <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{dateStr(m.created_at)}</span>
              </div>
              {m.product_interest && (
                <p style={{ fontSize: 12, color: "var(--brand)", margin: "4px 0", fontWeight: 600 }}>
                  About: {m.product_interest}
                </p>
              )}
              <p style={{ fontSize: 14, color: "var(--text-secondary)", margin: "6px 0 0" }}>{m.message}</p>
              {m.status === "unread" && (
                <span style={{ fontSize: 11, color: "var(--brand)", fontWeight: 600 }}>Click to mark as read</span>
              )}
            </div>
          ))
        )}
      </>
    );
  }

  // ── Status view (pending / rejected) ───────────────────────────────────
  if (profile && profile.verification_status !== "approved" && !editing) {
    return (
      <div className="card" style={{ maxWidth: 560, margin: "0 auto", padding: 28 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
          <strong style={{ fontSize: 16 }}>Supplier Application</strong>
          <StatusBadge status={profile.verification_status} />
        </div>
        {profile.verification_status === "pending" && (
          <p style={{ color: "var(--text-muted)", fontSize: 14, lineHeight: 1.7 }}>
            Your application is under review. Our team will respond within 48 hours.
            You'll see a status update here once reviewed.
          </p>
        )}
        {profile.verification_status === "rejected" && (
          <>
            <p style={{ color: "var(--rose)", fontSize: 14, marginBottom: 12 }}>
              {profile.rejection_reason || "Your application was not approved at this time."}
            </p>
            <button className="btn btn-primary" onClick={() => setEditing(true)}>Re-apply</button>
          </>
        )}
        <div style={{ marginTop: 20, borderTop: "1px solid var(--border)", paddingTop: 16, fontSize: 13, color: "var(--text-muted)" }}>
          Applied: {dateStr(profile.created_at)}
        </div>
      </div>
    );
  }

  // ── Approved: show live profile + inbox link ────────────────────────────
  if (profile?.verification_status === "approved" && !editing) {
    return (
      <>
        <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
          <div className="card" style={{ flex: 1, minWidth: 0, padding: 20 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <StatusBadge status="approved" />
            </div>
            <p style={{ fontSize: 13, color: "var(--text-muted)" }}>Your business is listed in the CreditVoice supplier directory.</p>
            <button className="btn btn-secondary" style={{ marginTop: 12, fontSize: 13 }} onClick={() => setEditing(true)}>
              Edit Profile
            </button>
          </div>
          <div className="card" style={{ flex: 1, minWidth: 0, padding: 20, cursor: "pointer" }} onClick={() => setInboxView(true)}>
            <div style={{ fontSize: 22, fontWeight: 800, color: unread > 0 ? "var(--brand)" : "var(--text-secondary)" }}>
              {unread > 0 ? unread : inbox.length}
            </div>
            <div style={{ fontSize: 13, color: "var(--text-muted)" }}>{unread > 0 ? "unread enquiries" : "total enquiries"}</div>
            <button className="btn btn-secondary" style={{ marginTop: 12, fontSize: 13 }}>View Inbox →</button>
          </div>
        </div>

        <div className="card" style={{ padding: 20 }}>
          <div style={{ fontWeight: 700, marginBottom: 12 }}>Your listed products</div>
          {profile.products?.map((p, i) => (
            <div key={i} style={{ padding: "10px 0", borderBottom: "1px solid var(--border)", fontSize: 13 }}>
              <strong>{p.product_name}</strong>
              {p.min_order_qty && <span style={{ color: "var(--text-muted)", marginLeft: 8 }}>Min: {p.min_order_qty} {p.min_order_unit}</span>}
              {p.price_range && <span style={{ color: "var(--green)", marginLeft: 8 }}>{p.price_range}</span>}
            </div>
          ))}
        </div>
      </>
    );
  }

  // ── Application form ────────────────────────────────────────────────────
  return (
    <div style={{ maxWidth: 680 }}>
      {!profile && (
        <div className="card" style={{ padding: 20, marginBottom: 20, background: "linear-gradient(135deg,#e6efff,#f0f6ff)" }}>
          <strong style={{ fontSize: 15 }}>What you gain as a Verified Supplier</strong>
          <ul style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 2, marginTop: 8, paddingLeft: 16 }}>
            <li>Discovered by retailers searching for your product on CreditVoice</li>
            <li>tiTi recommends you when retailers run low on what you supply</li>
            <li>Retailers can message you directly from the platform</li>
            <li>A verified badge that signals trust and legitimacy</li>
            <li>Zero commission — you deal directly with buyers</li>
          </ul>
        </div>
      )}

      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div className="form-group">
          <label className="form-label">I am a *</label>
          <select value={stype} onChange={e => setStype(e.target.value)} required>
            <option value="">Select type…</option>
            {meta.supplier_types.map(t => <option key={t.key} value={t.key}>{t.label}</option>)}
          </select>
        </div>

        <div className="form-group">
          <label className="form-label">About your business</label>
          <textarea value={bio} onChange={e => setBio(e.target.value)} rows={3}
            placeholder="Briefly describe what you produce or supply, your experience, and what makes you reliable." />
        </div>

        <div className="form-group">
          <label className="form-label">States / regions you can supply *</label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 4 }}>
            {meta.states.map(s => (
              <button key={s} type="button" onClick={() => toggleState(s)} style={{
                fontSize: 12, padding: "4px 10px", borderRadius: 99, border: "1px solid",
                cursor: "pointer", fontWeight: states.includes(s) ? 700 : 400,
                borderColor: states.includes(s) ? "var(--brand)" : "var(--border)",
                background: states.includes(s) ? "var(--brand)" : "transparent",
                color: states.includes(s) ? "#fff" : "var(--text-secondary)",
              }}>{s}</button>
            ))}
          </div>
        </div>

        <div className="form-group">
          <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", fontSize: 14 }}>
            <input type="checkbox" checked={canDeliver} onChange={e => setCanDeliver(e.target.checked)} />
            I can arrange delivery / logistics
          </label>
          {canDeliver && (
            <input style={{ marginTop: 8 }} value={deliveryNotes} onChange={e => setDeliveryNotes(e.target.value)}
              placeholder="e.g. Free delivery within Lagos for orders above 10 bags" />
          )}
        </div>

        <div className="form-group">
          <label className="form-label">CAC number (optional but recommended)</label>
          <input value={cac} onChange={e => setCac(e.target.value)} placeholder="e.g. RC1234567" />
          <span className="form-hint">Increases trust with buyers and speeds up approval.</span>
        </div>

        <div>
          <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12 }}>Products you supply *</div>
          {products.map((p, i) => (
            <ProductRow key={i} p={p} index={i} onChange={updateProduct} onRemove={removeProduct} />
          ))}
          <button type="button" className="btn btn-secondary" onClick={() => setProducts(prev => [...prev, { ...EMPTY_PRODUCT }])}>
            <Plus size={13} /> Add another product
          </button>
        </div>

        {err && <div className="login-error">{err}</div>}
        {ok  && <div className="login-info">{ok}</div>}

        <div style={{ display: "flex", gap: 10 }}>
          {editing && <button type="button" className="btn btn-secondary" onClick={() => { setEditing(false); setErr(""); }}>Cancel</button>}
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Submitting…" : editing ? "Save changes" : "Submit application"}
          </button>
        </div>
      </form>
    </div>
  );
}

// ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ──
// Main export
// ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ── ──
export default function Suppliers() {
  // Plan gating needs the authenticated user (with subscription_plan), which
  // lives in AuthContext. AppContext only carries ownerPhone/period, so reading
  // user from it left userPlan undefined and gated even Pro/Premium users out.
  const { user } = useAuth();
  const [tab, setTab] = useState("chain");
  const [inboxCount, setInboxCount] = useState(0);

  useEffect(() => {
    apiFetch("verified-suppliers/inbox")
      .then(d => setInboxCount(d.unread || 0))
      .catch(() => {});
  }, []);

  const tabs = [
    { key: "chain",   label: "My Supply Chain" },
    { key: "find",    label: "Find Suppliers" },
    { key: "profile", label: "Supplier Profile", badge: inboxCount || null },
  ];

  return (
    <>
      <TabNav tabs={tabs} active={tab} onChange={setTab} />
      {tab === "chain"   && <MySupplyChain />}
      {tab === "find"    && <FindSuppliers />}
      {tab === "profile" && <SupplierProfileTab userPlan={user?.subscription_plan} />}
    </>
  );
}
