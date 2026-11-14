import { useState, useEffect } from "react";
import { Copy, Share2 } from "lucide-react";
import { apiFetch } from "../lib/api";
import { nairaFull, dateStr } from "../lib/format";

/* A CreditVoice marketer's own page (marketers.py): their code and link,
   the businesses they brought, and their bonus. */
export default function Marketer() {
  const [m, setM] = useState(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  useEffect(() => { apiFetch("marketer/me").then(setM).catch(e => setErr(e.message)); }, []);
  if (err) return <div className="pos-error" style={{ margin: 24 }}>{err}</div>;
  if (!m) return <div className="page-loading">Loading…</div>;

  async function copy() {
    try { await navigator.clipboard.writeText(m.link); setMsg("Link copied."); } catch { setMsg(m.link); }
  }
  const wa = encodeURIComponent(`Run your business on CreditVoice — sales, stock and debts in one place, with a free 14-day trial: ${m.link}`);

  return (
    <div style={{ display: "grid", gap: 14, maxWidth: 820 }}>
      <div className="card" style={{ padding: 16, display: "grid", gap: 8 }}>
        <div className="td-muted" style={{ fontSize: 12 }}>Your marketer code</div>
        <div style={{ fontSize: 26, fontWeight: 800, letterSpacing: "0.04em" }}>{m.code}</div>
        <div className="td-muted" style={{ fontSize: 13, wordBreak: "break-all" }}>{m.link}</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn btn-ghost btn-sm" onClick={copy}><Copy size={13} /> Copy link</button>
          <a className="btn btn-ghost btn-sm" href={`https://wa.me/?text=${wa}`} target="_blank" rel="noreferrer"><Share2 size={13} /> Share on WhatsApp</a>
          {msg && <span className="td-muted" style={{ fontSize: 13 }}>{msg}</span>}
        </div>
        <span className="form-hint">
          Businesses sign up with your link, or on WhatsApp by sending <strong>join {m.code}</strong>. They get 14 days on GO free.
          You earn <strong>{m.percent}%</strong> of every plan payment they make — the first and every renewal.
        </span>
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {[["Businesses", m.businesses], ["Joined this month", m.joined_this_month], ["Paying", m.paying],
          ["Bonus this month", nairaFull(m.bonus_this_month)], ["Owed to you", nairaFull(m.bonus_owed)], ["Paid to you", nairaFull(m.bonus_paid)]].map(([l, v]) => (
          <div key={l} className="card" style={{ padding: "8px 12px", minWidth: 120 }}><div className="td-muted" style={{ fontSize: 12 }}>{l}</div><strong>{v}</strong></div>
        ))}
      </div>

      <div className="card" style={{ padding: 16, display: "grid", gap: 8 }}>
        <h3 style={{ margin: 0 }}>Businesses you brought</h3>
        {m.business_list.length === 0 ? <div className="td-muted">None yet — share your link.</div> : (
          <div style={{ overflowX: "auto" }}>
            <table className="data-table" style={{ width: "100%" }}>
              <thead><tr><th>Business</th><th>Joined</th><th>Plan</th><th style={{ textAlign: "right" }}>Your bonus</th></tr></thead>
              <tbody>{m.business_list.map(b => (
                <tr key={b.id}><td>{b.name}<div className="td-muted" style={{ fontSize: 12 }}>{b.owner} · {b.phone}</div></td>
                  <td className="td-muted">{dateStr(b.joined)}</td>
                  <td>{b.plan}{!b.paying && <div className="td-muted" style={{ fontSize: 12 }}>not paying yet</div>}</td>
                  <td style={{ textAlign: "right" }}>{nairaFull(b.bonus)}</td></tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card" style={{ padding: 16, display: "grid", gap: 8 }}>
        <h3 style={{ margin: 0 }}>Your bonus on each payment</h3>
        {m.earnings.length === 0 ? <div className="td-muted">No payments yet.</div> : (
          <div style={{ overflowX: "auto" }}>
            <table className="data-table" style={{ width: "100%" }}>
              <thead><tr><th>Date</th><th>Business</th><th style={{ textAlign: "right" }}>Bonus</th><th>Status</th></tr></thead>
              <tbody>{m.earnings.map(e => (
                <tr key={e.id}><td className="td-muted">{dateStr(e.created_at)}</td>
                  <td>{e.business}<div className="td-muted" style={{ fontSize: 12 }}>{e.renewal ? "renewal" : "first payment"} · {nairaFull(e.amount)} at {e.percent}%</div></td>
                  <td style={{ textAlign: "right" }}>{nairaFull(e.bonus)}</td>
                  <td>{e.status === "paid" ? <span style={{ color: "#166534" }}>Paid {dateStr(e.paid_at)}</span> : <span style={{ color: "#b45309" }}>Owed</span>}</td></tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
