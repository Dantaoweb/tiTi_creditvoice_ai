import { useState, useEffect } from "react";
import { apiFetch, apiPost, apiPut } from "../lib/api";
import { dateStr } from "../lib/format";

function fmtWhen(iso) {
  if (!iso) return { label: "—", tone: "muted" };
  const d = new Date(iso); d.setHours(0, 0, 0, 0);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const days = Math.round((d - today) / 86400000);
  if (days < 0) return { label: `Overdue · ${dateStr(iso)}`, tone: "rose" };
  if (days === 0) return { label: "Due today", tone: "amber" };
  if (days === 1) return { label: "Due tomorrow", tone: "amber" };
  return { label: dateStr(iso), tone: "muted" };
}

function NotifyModal({ delivery, onClose, onSent }) {
  const suggested =
    `Hello ${delivery.customer || ""}, your order (Receipt #${delivery.id}) ` +
    `will be ready by ${dateStr(delivery.service_date)}. Thank you.`;
  const [msg, setMsg] = useState(suggested);
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState("");

  async function send() {
    setSending(true); setErr("");
    try {
      await apiPost(`deliveries/${delivery.id}/notify`, { message: msg });
      onSent();
      onClose();
    } catch (e) { setErr(e.message); }
    finally { setSending(false); }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">Message {delivery.customer || "customer"}</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          {!delivery.customer_phone && (
            <div className="modal-error">No phone number saved for this customer.</div>
          )}
          <textarea rows={4} value={msg} onChange={e => setMsg(e.target.value)} style={{ width: "100%" }} />
          <span className="form-hint">Sent to the customer's WhatsApp — edit before sending.</span>
          {err && <div className="modal-error">{err}</div>}
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={send} disabled={sending || !delivery.customer_phone}>
            {sending ? "Sending…" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Deliveries() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [notify, setNotify] = useState(null);
  const [toast, setToast] = useState("");

  function load() {
    setLoading(true);
    apiFetch("deliveries")
      .then(d => setRows(d.deliveries || []))
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  async function saveDate(id, val) {
    try {
      await apiPut(`transactions/${id}/service-date`, { service_date: val || null });
      setRows(prev => prev.map(r =>
        r.id === id ? { ...r, service_date: val ? new Date(val).toISOString() : null } : r
      ));
    } catch (e) { setErr(e.message); }
  }

  if (loading) return <div className="page-loading">Loading deliveries…</div>;

  return (
    <div className="card" style={{ maxWidth: 720 }}>
      <div className="card-header"><span className="card-title">Deliveries</span></div>
      {err && <div className="pos-error" style={{ margin: 12 }}>{err}</div>}
      {toast && <div style={{ color: "var(--brand)", padding: "8px 16px", fontSize: 13 }}>✓ {toast}</div>}
      {rows.length === 0 ? (
        <div className="td-muted" style={{ padding: 16 }}>
          No deliveries scheduled. Set a "Deliver / ready by" date when recording a sale.
        </div>
      ) : (
        <div>
          {rows.map(r => {
            const w = fmtWhen(r.service_date);
            const tone = w.tone === "rose" ? "#b91c1c" : w.tone === "amber" ? "#b45309" : "var(--muted)";
            return (
              <div key={r.id} style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                gap: 10, flexWrap: "wrap", padding: "12px 16px", borderBottom: "1px solid var(--border)",
              }}>
                <div style={{ minWidth: 0 }}>
                  <strong>{r.customer || "—"}</strong>
                  <div className="td-muted" style={{ fontSize: 12 }}>#{r.id} · {r.product}</div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: tone }}>{w.label}</span>
                  <input
                    type="date"
                    defaultValue={r.service_date ? r.service_date.slice(0, 10) : ""}
                    onChange={e => saveDate(r.id, e.target.value)}
                    style={{ fontSize: 12 }}
                  />
                  <button className="btn btn-secondary btn-sm" onClick={() => setNotify(r)}>Message</button>
                </div>
              </div>
            );
          })}
        </div>
      )}
      {notify && (
        <NotifyModal delivery={notify} onClose={() => setNotify(null)} onSent={() => setToast("Message sent")} />
      )}
    </div>
  );
}
