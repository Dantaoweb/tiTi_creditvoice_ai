import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ClipboardCheck } from "lucide-react";
import { apiFetch, apiPost } from "../lib/api";
import { dateStr, nairaFull } from "../lib/format";
import { useAuth } from "../context/AuthContext";

const STATUS = {
  counting: ["Counting", "#b45309"],
  submitted: ["Waiting for approval", "#1d4ed8"],
  approved: ["Approved", "#166534"],
  cancelled: ["Cancelled", "var(--muted)"],
};

/* Stock counts: start one, carry on with one, and (owner) see what counts
   found missing. */
export default function StockCounts() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const canSeeLosses = !!user?.full_access;
  const [rows, setRows] = useState(null);
  const [cats, setCats] = useState([]);
  const [category, setCategory] = useState("");
  const [loss, setLoss] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiFetch("stock-counts").then(d => setRows(d.counts || [])).catch(e => setErr(e.message));
    apiFetch("categories").then(d => setCats((d.categories || []).filter(c => c.name && c.name !== "service"))).catch(() => {});
    if (canSeeLosses) apiFetch("stock-counts/losses", { days: 30 }).then(setLoss).catch(() => {});
  }, [canSeeLosses]);

  async function start() {
    setBusy(true); setErr("");
    try {
      const sc = await apiPost("stock-counts", { category: category || null });
      navigate(`/stock-counts/${sc.id}`);
    } catch (e) { setErr(e.message); setBusy(false); }
  }

  const open = (rows || []).find(r => r.status === "counting");
  return (
    <div style={{ display: "grid", gap: 14, maxWidth: 720 }}>
      <div className="card">
        <div className="card-header"><span className="card-title">Stock count</span></div>
        <div className="card-body" style={{ fontSize: 13 }}>
          <p style={{ marginTop: 0 }}>
            Walk your shelves and type what is really there. When you're done, send it for approval —
            stock only changes when the owner approves, and every difference gets a reason
            (damaged, expired, missing…), so you can see what you're losing.
          </p>
          {open && (
            <div style={{ marginBottom: 10 }}>
              <Link to={`/stock-counts/${open.id}`} className="btn btn-secondary btn-sm">
                Carry on with {open.number} ({open.counted} counted)
              </Link>
            </div>
          )}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <select value={category} onChange={e => setCategory(e.target.value)} style={{ minWidth: 180 }}>
              <option value="">All products</option>
              {cats.map(c => <option key={c.name} value={c.name}>Only {c.name.replace(/\b\w/g, x => x.toUpperCase())}</option>)}
            </select>
            <button className="btn btn-primary" onClick={start} disabled={busy}>
              <ClipboardCheck size={15} /> {busy ? "Starting…" : "Start a count"}
            </button>
          </div>
          {err && <div className="modal-error">{err}</div>}
        </div>
      </div>

      {canSeeLosses && loss && (loss.lost > 0 || loss.found > 0) && (
        <div className="card">
          <div className="card-header"><span className="card-title">Last 30 days</span></div>
          <div className="card-body" style={{ fontSize: 13 }}>
            <div><strong style={{ color: "var(--rose)" }}>{nairaFull(loss.lost)}</strong> of stock lost (at cost)
              {loss.found > 0 && <> · {nairaFull(loss.found)} found extra</>}</div>
            {loss.by_reason.map(r => (
              <div key={r.reason} className="td-muted">{r.reason}: {r.value < 0 ? "−" : "+"}{nairaFull(Math.abs(r.value))}</div>
            ))}
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-header"><span className="card-title">Counts</span></div>
        {rows === null ? <div className="td-muted" style={{ padding: 16 }}>Loading…</div>
          : rows.length === 0 ? <div className="td-muted" style={{ padding: 16 }}>No counts yet.</div>
          : rows.map(r => (
            <Link key={r.id} to={`/stock-counts/${r.id}`} style={{
              display: "flex", justifyContent: "space-between", gap: 10, padding: "12px 16px",
              borderBottom: "1px solid var(--border)", color: "inherit", textDecoration: "none",
            }}>
              <span><strong>{r.number}</strong> · {r.scope} · {dateStr(r.created_at)}
                <span className="td-muted"> · {r.counted} counted</span></span>
              <span style={{ fontSize: 12, fontWeight: 700, color: STATUS[r.status]?.[1] }}>{STATUS[r.status]?.[0]}</span>
            </Link>
          ))}
      </div>
    </div>
  );
}
