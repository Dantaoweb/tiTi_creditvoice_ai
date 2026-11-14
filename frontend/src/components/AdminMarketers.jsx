import { useState, useEffect } from "react";
import { apiFetch, apiPost, apiPut } from "../lib/api";
import { nairaFull, dateStr } from "../lib/format";

/* Admin → Marketers (marketers.py): people recruited to sell CreditVoice.
   Not referrers. A % of every plan payment their businesses make, renewals
   too; paid outside the app and marked here. */
export default function AdminMarketers() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [form, setForm] = useState({ name: "", phone: "", percent: "", code: "" });
  const [busy, setBusy] = useState(false);
  const [pct, setPct] = useState("");
  const [open, setOpen] = useState(null);
  function load() {
    apiFetch("admin/marketers").then(d => { setData(d); setPct(String(d.default_percent)); }).catch(e => setErr(e.message));
  }
  useEffect(() => { load(); }, []);

  async function add(e) {
    e.preventDefault(); setBusy(true); setErr("");
    try {
      await apiPost("admin/marketers", { name: form.name, phone: form.phone, code: form.code || null,
        percent: form.percent === "" ? null : Number(form.percent) });
      setForm({ name: "", phone: "", percent: "", code: "" }); load();
    } catch (x) { setErr(x.message); }
    finally { setBusy(false); }
  }
  async function saveDefault() {
    try { await apiPut("admin/marketer-settings", { default_percent: Number(pct) }); load(); }
    catch (x) { setErr(x.message); }
  }

  if (!data) return <div className="td-muted">{err || "Loading…"}</div>;
  const t = data.totals;
  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {[["Marketers", `${t.active} active of ${t.marketers}`], ["Businesses brought", t.businesses], ["Paying now", t.paying],
          ["Bonus earned", nairaFull(t.bonus_total)], ["Bonus owed", nairaFull(t.bonus_owed)], ["Bonus paid", nairaFull(t.bonus_paid)]].map(([l, v]) => (
          <div key={l} className="card" style={{ padding: "8px 12px", minWidth: 120 }}>
            <div className="td-muted" style={{ fontSize: 12 }}>{l}</div><strong>{v}</strong>
          </div>
        ))}
      </div>

      <div className="card" style={{ padding: 14, display: "grid", gap: 10 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <strong>Default bonus</strong>
          <input type="number" min="0" max="50" step="0.5" value={pct} onChange={e => setPct(e.target.value)} style={{ width: 80 }} />
          <span>% of every plan payment, renewals too</span>
          <button className="btn btn-ghost btn-sm" onClick={saveDefault}>Save</button>
        </div>
        <form onSubmit={add} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <strong style={{ width: "100%" }}>Add a marketer</strong>
          <input required placeholder="Name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} style={{ flex: "2 1 160px" }} />
          <input required placeholder="Phone" inputMode="tel" value={form.phone} onChange={e => setForm({ ...form, phone: e.target.value })} style={{ flex: "2 1 140px" }} />
          <input placeholder={`% (default ${data.default_percent})`} type="number" min="0" max="50" step="0.5" value={form.percent}
            onChange={e => setForm({ ...form, percent: e.target.value })} style={{ flex: "1 1 100px" }} />
          <input placeholder="Code (optional)" value={form.code} onChange={e => setForm({ ...form, code: e.target.value })} style={{ flex: "1 1 120px" }} />
          <button className="btn btn-primary" disabled={busy}>{busy ? "Adding…" : "Add"}</button>
        </form>
        <span className="form-hint">They log in with a normal CreditVoice account on the same phone to see their own numbers. A business brought by a marketer gets the free GO trial and earns no referral cashback.</span>
        {err && <div className="modal-error">{err}</div>}
      </div>

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        {data.marketers.length === 0 ? <div className="td-muted" style={{ padding: 14 }}>No marketers yet.</div> : (
          <table className="data-table" style={{ width: "100%" }}>
            <thead><tr><th>Marketer</th><th>Code</th><th style={{ textAlign: "right" }}>Businesses</th><th style={{ textAlign: "right" }}>Paying</th>
              <th style={{ textAlign: "right" }}>This month</th><th style={{ textAlign: "right" }}>Earned</th><th style={{ textAlign: "right" }}>Owed</th><th></th></tr></thead>
            <tbody>
              {data.marketers.map(m => (
                <tr key={m.id} style={{ opacity: m.status === "active" ? 1 : 0.55 }}>
                  <td>{m.name}<div className="td-muted" style={{ fontSize: 12 }}>{m.phone} · {m.percent}%{m.status !== "active" ? " · inactive" : ""}</div></td>
                  <td><code>{m.code}</code></td>
                  <td style={{ textAlign: "right" }}>{m.businesses}{m.joined_this_month ? <div className="td-muted" style={{ fontSize: 12 }}>+{m.joined_this_month} this month</div> : null}</td>
                  <td style={{ textAlign: "right" }}>{m.paying}</td>
                  <td style={{ textAlign: "right" }}>{nairaFull(m.bonus_this_month)}</td>
                  <td style={{ textAlign: "right" }}>{nairaFull(m.bonus_total)}</td>
                  <td style={{ textAlign: "right", fontWeight: 700, color: m.bonus_owed ? "#b45309" : undefined }}>{nairaFull(m.bonus_owed)}</td>
                  <td><button className="btn btn-ghost btn-sm" onClick={() => setOpen(m.id)}>Open</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {open && <MarketerModal id={open} onClose={() => { setOpen(null); load(); }} />}
    </div>
  );
}

function MarketerModal({ id, onClose }) {
  const [m, setM] = useState(null);
  const [err, setErr] = useState("");
  const [ref, setRef] = useState("");
  const [pct, setPct] = useState("");
  const [msg, setMsg] = useState("");
  function load() { apiFetch(`admin/marketers/${id}`).then(d => { setM(d); setPct(d.own_percent ?? ""); }).catch(e => setErr(e.message)); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [id]);
  if (!m) return null;

  async function update(body) {
    setErr(""); setMsg("");
    try { await apiPut(`admin/marketers/${id}`, body); load(); setMsg("Saved."); } catch (x) { setErr(x.message); }
  }
  async function pay() {
    if (!window.confirm(`Mark ${nairaFull(m.bonus_owed)} as paid to ${m.name}? Pay them first (bank transfer), then mark it here.`)) return;
    setErr("");
    try { const r = await apiPost(`admin/marketers/${id}/pay`, { reference: ref.trim() || null }); setMsg(`Marked ${nairaFull(r.paid)} paid.`); setRef(""); load(); }
    catch (x) { setErr(x.message); }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal modal-wide">
        <div className="modal-header">
          <span className="modal-title">{m.name} · {m.code}</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body" style={{ display: "grid", gap: 12, fontSize: 14 }}>
          <div className="td-muted" style={{ wordBreak: "break-all" }}>Sign-up link: {m.link} · or on WhatsApp: <strong>join {m.code}</strong></div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <span>Bonus</span>
            <input type="number" min="0" max="50" step="0.5" value={pct} placeholder={`${m.percent} (default)`} onChange={e => setPct(e.target.value)} style={{ width: 110 }} />
            <span>%</span>
            <button className="btn btn-ghost btn-sm" onClick={() => update(pct === "" ? { use_default_percent: true } : { percent: Number(pct) })}>Save %</button>
            <button className="btn btn-ghost btn-sm" onClick={() => update({ status: m.status === "active" ? "inactive" : "active" })}>
              {m.status === "active" ? "Make inactive" : "Make active"}</button>
          </div>
          <span className="form-hint">A new % applies to payments from now on. An inactive marketer's code stops working; what they earned stays.</span>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {[["Businesses", m.businesses], ["Paying", m.paying], ["Earned", nairaFull(m.bonus_total)], ["Paid", nairaFull(m.bonus_paid)], ["Owed", nairaFull(m.bonus_owed)]].map(([l, v]) => (
              <div key={l} className="card" style={{ padding: "6px 10px" }}><div className="td-muted" style={{ fontSize: 12 }}>{l}</div><strong>{v}</strong></div>
            ))}
          </div>
          {m.bonus_owed > 0 && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <input placeholder="Payment reference (optional)" value={ref} onChange={e => setRef(e.target.value)} style={{ flex: "1 1 200px" }} />
              <button className="btn btn-primary btn-sm" onClick={pay}>Mark {nairaFull(m.bonus_owed)} paid</button>
            </div>
          )}
          {err && <div className="modal-error">{err}</div>}
          {msg && <div className="pos-change">{msg}</div>}

          <strong>Businesses they brought ({m.business_list.length})</strong>
          {m.business_list.length === 0 ? <div className="td-muted">None yet.</div> : (
            <div style={{ overflowX: "auto" }}>
              <table className="data-table" style={{ width: "100%" }}>
                <thead><tr><th>Business</th><th>Joined</th><th>Plan</th><th style={{ textAlign: "right" }}>Paid us</th><th style={{ textAlign: "right" }}>Bonus</th></tr></thead>
                <tbody>{m.business_list.map(b => (
                  <tr key={b.id}><td>{b.name}<div className="td-muted" style={{ fontSize: 12 }}>{b.business_type || ""} · {b.phone}</div></td>
                    <td className="td-muted">{dateStr(b.joined)}</td><td>{b.plan}{b.paying ? "" : <span className="td-muted"> (not paying)</span>}</td>
                    <td style={{ textAlign: "right" }}>{nairaFull(b.paid_total)}</td><td style={{ textAlign: "right" }}>{nairaFull(b.bonus)}</td></tr>
                ))}</tbody>
              </table>
            </div>
          )}
          <strong>Bonus on each payment</strong>
          {m.earnings.length === 0 ? <div className="td-muted">No payments yet.</div> : (
            <div style={{ overflowX: "auto" }}>
              <table className="data-table" style={{ width: "100%" }}>
                <thead><tr><th>Date</th><th>Business</th><th style={{ textAlign: "right" }}>Payment</th><th style={{ textAlign: "right" }}>Bonus</th><th>Status</th></tr></thead>
                <tbody>{m.earnings.map(e => (
                  <tr key={e.id}><td className="td-muted">{dateStr(e.created_at)}</td>
                    <td>{e.business}<div className="td-muted" style={{ fontSize: 12 }}>{e.plan} {e.billing_period === "YEARLY" ? "yearly" : "monthly"}{e.renewal ? " · renewal" : " · first"}</div></td>
                    <td style={{ textAlign: "right" }}>{nairaFull(e.amount)}</td>
                    <td style={{ textAlign: "right" }}>{nairaFull(e.bonus)}<div className="td-muted" style={{ fontSize: 12 }}>{e.percent}%</div></td>
                    <td>{e.status === "paid" ? <span style={{ color: "#166534" }}>Paid {dateStr(e.paid_at)}{e.pay_reference ? ` · ${e.pay_reference}` : ""}</span> : <span style={{ color: "#b45309" }}>Owed</span>}</td></tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </div>
        <div className="modal-footer"><button className="btn btn-ghost" onClick={onClose}>Close</button></div>
      </div>
    </div>
  );
}
