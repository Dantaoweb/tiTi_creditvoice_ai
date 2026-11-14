import { useState, useEffect } from "react";
import { MonitorPlay } from "lucide-react";
import { apiFetch, apiPost } from "../lib/api";

/* Demo business (demo_business.py): show CreditVoice as any kind of business,
   with sample data, without touching a real one. For admins and marketers. */
export default function DemoStart() {
  const [st, setSt] = useState(null);
  const [type, setType] = useState("bakery");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => {
    apiFetch("demo").then(d => { setSt(d); if (d.demo?.business_type) setType(d.demo.business_type); }).catch(e => setErr(e.message));
  }, []);
  if (err && !st) return <div className="pos-error" style={{ margin: 24 }}>{err}</div>;
  if (!st) return <div className="page-loading">Loading…</div>;

  async function open(fresh) {
    setBusy(true); setErr("");
    try {
      await apiPost("demo/open", fresh ? { business_type: type } : {});
      window.location.href = "/app/home";
    } catch (e) { setErr(e.message); setBusy(false); }
  }

  const groups = {};
  st.types.forEach(t => { (groups[t.group] ||= []).push(t); });
  return (
    <div className="card" style={{ padding: 20, display: "grid", gap: 12, maxWidth: 640 }}>
      <h2 style={{ margin: 0, display: "flex", gap: 8, alignItems: "center" }}><MonitorPlay size={20} /> Demo business</h2>
      <p style={{ margin: 0 }}>
        Show CreditVoice as any kind of business — a bakery, a school, a pharmacy — with sample products, customers,
        sales and a debt. Use it to show a customer how it works, or to train staff.
      </p>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 14 }}>
        <li>It's separate from every real business. Nothing you do there touches anyone's records.</li>
        <li>Nothing is sent: sample customers are never messaged on WhatsApp.</li>
        <li>Switch type or reset any time from the blue bar at the top; <strong>Exit demo</strong> brings you back here.</li>
      </ul>
      <div className="form-group">
        <label className="form-label">Show it as</label>
        <select value={type} onChange={e => setType(e.target.value)}>
          {Object.entries(groups).map(([g, ts]) => (
            <optgroup key={g} label={g}>{ts.map(t => <option key={t.key} value={t.key}>{t.label}</option>)}</optgroup>
          ))}
        </select>
      </div>
      {err && <div className="pos-error">{err}</div>}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="btn btn-primary" disabled={busy} onClick={() => open(true)}>{busy ? "Opening…" : "Open a fresh demo"}</button>
        {st.demo && (
          <button className="btn btn-secondary" disabled={busy} onClick={() => open(false)}>
            Continue my demo ({st.demo.label})</button>
        )}
      </div>
    </div>
  );
}

/* The bar across the top while inside a demo business */
export function DemoBar({ label, businessType }) {
  const [types, setTypes] = useState([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => { apiFetch("demo").then(d => setTypes(d.types || [])).catch(() => {}); }, []);
  async function go(path, body) {
    setBusy(true);
    try { await apiPost(path, body); window.location.href = path === "demo/exit" ? "/app/demo" : "/app/home"; }
    catch (e) { alert(e.message); setBusy(false); }
  }
  return (
    <div className="demo-bar" role="status">
      <strong>DEMO</strong>
      <span className="demo-bar__label">{label} — sample data, nothing is sent</span>
      <select aria-label="Show me as" value={businessType || ""} disabled={busy}
        onChange={e => go("demo/switch", { business_type: e.target.value })}>
        {types.map(t => <option key={t.key} value={t.key}>Show me as: {t.label}</option>)}
      </select>
      <button className="btn btn-sm" disabled={busy} onClick={() => go("demo/switch", {})}>Reset</button>
      <button className="btn btn-sm" disabled={busy} onClick={() => go("demo/exit")}>Exit demo</button>
    </div>
  );
}
