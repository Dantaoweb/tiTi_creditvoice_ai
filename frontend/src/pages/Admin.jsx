import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { apiFetch, apiPost, apiPut, apiPatch, apiDelete } from "../lib/api";
import { nairaFull, parseAmt } from "../lib/format";
import MoneyInput from "../components/MoneyInput";
import { Download, RefreshCw, Search, Ticket, Trash2, RotateCcw } from "lucide-react";

// ── tiny bar chart ──────────────────────────────────────────────────────────

function BarChart({ data, valueKey, color = "var(--brand)" }) {
  if (!data?.length) return null;
  const max = Math.max(...data.map(d => d[valueKey]), 1);
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 60 }}>
      {data.map((d, i) => (
        <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", flex: 1, gap: 2 }}>
          <div style={{ flex: 1, display: "flex", alignItems: "flex-end", width: "100%" }}>
            <div
              title={`${d.date}: ${d[valueKey]}`}
              style={{
                width: "100%",
                height: `${Math.max(2, (d[valueKey] / max) * 54)}px`,
                background: color, borderRadius: 3, opacity: 0.85,
                transition: "height 0.3s",
              }}
            />
          </div>
          {data.length <= 7 && (
            <span style={{ fontSize: 9, color: "var(--text-muted)", whiteSpace: "nowrap" }}>
              {d.date.split(" ")[1]}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

// ── stat card ───────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, color }) {
  // Numbers get thousands separators; strings (already formatted) pass through.
  const display = typeof value === "number" ? value.toLocaleString() : (value ?? "—");
  return (
    <div className="metric-card" style={{ borderTop: `3px solid ${color || "var(--brand)"}` }}>
      <div className="metric-value" style={{ color: color || "var(--brand)" }}>{display}</div>
      <div className="metric-label">{label}</div>
      {sub && <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

// ── failed parses tab ────────────────────────────────────────────────────────

// What to teach tiTi next, read off what people actually asked and it missed.
// Grouped by what was being asked, ranked by how many businesses hit it — one
// person sending the same thing twenty times is a support conversation, twenty
// people sending it once is a feature.
function ParseGaps() {
  const [data, setData] = useState(null);
  const [days, setDays] = useState(90);
  const [err, setErr] = useState("");

  useEffect(() => {
    setData(null);
    apiFetch("admin/parse-gaps", { days, limit: 40 })
      .then(setData).catch(e => setErr(e.message));
  }, [days]);

  if (err) return <div style={{ color: "var(--rose)" }}>{err}</div>;
  if (!data) return <div className="text-subtle text-sm">Reading what people asked…</div>;

  const s = data.summary || {};
  const SHAPES = {
    question: ["badge-blue", "question"],
    transaction: ["badge-amber", "recording"],
    unclear: ["badge-gray", "unclear"],
  };

  return (
    <div style={{ display: "grid", gap: 16, marginBottom: 20 }}>
      <div className="card">
        <div className="card-header" style={{ flexWrap: "wrap", gap: 8 }}>
          <span className="card-title">What tiTi could not answer</span>
          <div style={{ display: "flex", gap: 6 }}>
            {[7, 30, 90].map(d => (
              <button key={d} className={`btn btn-xs ${days === d ? "btn-primary" : "btn-ghost"}`}
                onClick={() => setDays(d)}>{d}d</button>
            ))}
          </div>
        </div>
        <div className="card-body">
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap", fontSize: 13 }}>
            <span><strong>{s.messages || 0}</strong> messages missed</span>
            <span><strong>{s.distinct_questions || 0}</strong> distinct things asked</span>
            <span><strong>{s.businesses_affected || 0}</strong> businesses affected</span>
            <span className="text-subtle">
              {s.questions || 0} questions · {s.transactions || 0} recordings · {s.unclear || 0} unclear
            </span>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">
            Asked most, answered least
            <span className="text-subtle text-sm"> — fix the top of this list first</span>
          </span>
        </div>
        <div className="card-body" style={{ display: "grid", gap: 10 }}>
          {(data.unanswered || []).length === 0 ? (
            <div className="text-subtle text-sm">Nothing missed in this period.</div>
          ) : data.unanswered.map(g => (
            <div key={g.signature} style={{
              border: "1px solid var(--border)", borderRadius: 10, padding: 10,
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                <span className={`badge ${(SHAPES[g.shape] || SHAPES.unclear)[0]}`}>
                  {(SHAPES[g.shape] || SHAPES.unclear)[1]}
                </span>
                <span className="text-subtle text-sm">
                  {g.businesses} business(es) · {g.count} time(s)
                </span>
              </div>
              <div style={{ marginTop: 6, display: "grid", gap: 3 }}>
                {g.examples.map((ex, i) => (
                  <div key={i} style={{ fontSize: 13, fontStyle: "italic" }}>“{ex}”</div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {(data.misreadings || []).length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">
              Read wrong, then corrected
              <span className="text-subtle text-sm"> — the right answer is in the second line</span>
            </span>
          </div>
          <div className="card-body" style={{ display: "grid", gap: 10 }}>
            {data.misreadings.map(g => (
              <div key={g.signature} style={{
                border: "1px solid var(--border)", borderRadius: 10, padding: 10,
              }}>
                <div className="text-subtle text-sm" style={{ marginBottom: 4 }}>
                  {g.businesses} business(es) · {g.count} time(s)
                  {g.parsed_type ? ` · read as ${g.parsed_type}` : ""}
                </div>
                {g.pairs.map((p, i) => (
                  <div key={i} style={{ fontSize: 13 }}>
                    <div>they said: <em>“{p.said}”</em></div>
                    <div style={{ color: "var(--brand)" }}>they meant: <em>“{p.meant}”</em></div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function FailedParsesTab() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch("admin/failed-parses?limit=200")
      .then(d => setRows(d.rows || []))
      .finally(() => setLoading(false));
  }, []);

  function exportCsv() {
    window.open("/app/api/admin/failed-parses/export", "_blank");
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
        <button className="btn btn-secondary" onClick={exportCsv} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <Download size={14} /> Export CSV
        </button>
      </div>
      <ParseGaps />
      {loading ? (
        <p style={{ color: "var(--text-muted)" }}>Loading…</p>
      ) : rows.length === 0 ? (
        <p style={{ color: "var(--text-muted)" }}>No failed parses yet.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "var(--surface-2, #f9fafb)", textAlign: "left" }}>
                {["Phone", "Message", "Resolved By", "LLM Reply", "Time"].map(h => (
                  <th key={h} style={{ padding: "8px 10px", borderBottom: "1px solid var(--border)", fontWeight: 600 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.id} style={{ borderBottom: "1px solid var(--border)" }}>
                  <td style={{ padding: "7px 10px", whiteSpace: "nowrap" }}>{r.phone}</td>
                  <td style={{ padding: "7px 10px", maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.text}</td>
                  <td style={{ padding: "7px 10px" }}>
                    {r.resolved_by
                      ? <span style={{ background: "var(--green-50,#f0fdf4)", color: "var(--green,#16a34a)", borderRadius: 4, padding: "1px 6px", fontSize: 11, fontWeight: 600 }}>LLM</span>
                      : <span style={{ color: "var(--text-muted)", fontSize: 11 }}>—</span>}
                  </td>
                  <td style={{ padding: "7px 10px", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text-muted)", fontSize: 12 }}>
                    {r.llm_reply || "—"}
                  </td>
                  <td style={{ padding: "7px 10px", whiteSpace: "nowrap", color: "var(--text-muted)", fontSize: 11 }}>
                    {r.created_at ? new Date(r.created_at).toLocaleString() : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── users tab ───────────────────────────────────────────────────────────────

function UsersTab() {
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("recent");   // recent | active | name
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null);

  function load(pg = page, search = q, srt = sort) {
    setLoading(true);
    apiFetch(`admin/users?page=${pg}&per_page=50&sort=${srt}&q=${encodeURIComponent(search)}`)
      .then(d => setData(d))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  async function removeUser(u) {
    if (!window.confirm(`Remove ${u.name || u.phone}? They (and their staff) will be signed out and blocked from logging in. You can restore them later.`)) return;
    setBusyId(u.id);
    try { await apiDelete(`admin/users/${u.id}`); load(); }
    catch (e) { alert(e.message || "Could not remove user."); }
    finally { setBusyId(null); }
  }

  async function restoreUser(u) {
    setBusyId(u.id);
    try { await apiPost(`admin/users/${u.id}/restore`, {}); load(); }
    catch (e) { alert(e.message || "Could not restore user."); }
    finally { setBusyId(null); }
  }

  function handleSearch(e) {
    e.preventDefault();
    setPage(1);
    load(1, q);
  }

  function changeSort(srt) {
    setSort(srt);
    setPage(1);
    load(1, q, srt);
  }

  function fmtLastActive(iso) {
    if (!iso) return "never";
    const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
    if (days <= 0) return "today";
    if (days === 1) return "yesterday";
    if (days < 30) return `${days}d ago`;
    return new Date(iso).toLocaleDateString();
  }

  const PLAN_COLOR = { BASIC: "#6b7280", GO: "#1a56db", PRO: "#d97706", PREMIUM: "#0f766e", ENTERPRISE: "#1a56db" };
  const STATUS_COLOR = { ACTIVE: "var(--green,#16a34a)", EXPIRED: "#dc2626", TRIAL: "#d97706" };

  return (
    <div>
      <form onSubmit={handleSearch} style={{ display: "flex", gap: 8, marginBottom: 14 }}>
        <input
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="Search name, phone, email…"
          style={{ flex: 1, padding: "7px 10px", borderRadius: 8, border: "1px solid var(--border)", fontSize: 13 }}
        />
        <button type="submit" className="btn btn-primary" style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <Search size={14} /> Search
        </button>
      </form>

      <div style={{ display: "flex", gap: 6, marginBottom: 12, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Sort:</span>
        {[["active", "Most active"], ["recent", "Newest"], ["name", "Name"]].map(([val, lbl]) => (
          <button
            key={val}
            onClick={() => changeSort(val)}
            className="btn btn-sm"
            style={{
              padding: "4px 12px", borderRadius: 999, fontSize: 12, fontWeight: 600,
              border: "1px solid var(--border)",
              background: sort === val ? "var(--brand)" : "transparent",
              color: sort === val ? "#fff" : "var(--text-muted)",
            }}
          >{lbl}</button>
        ))}
      </div>

      {loading ? (
        <p style={{ color: "var(--text-muted)" }}>Loading…</p>
      ) : !data ? null : (
        <>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 10 }}>
            Showing {data.users.length.toLocaleString()} of {(data.total ?? 0).toLocaleString()} businesses
            {sort === "active" && " · ranked by transactions recorded"}
          </p>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "var(--surface-2, #f9fafb)", textAlign: "left" }}>
                  {["Name", "Phone", "Business Type", "Plan", "Status", "Txns", "30d", "Customers", "Stock", "Last active", "Joined", ""].map((h, i) => (
                    <th key={i} style={{ padding: "8px 10px", borderBottom: "1px solid var(--border)", fontWeight: 600, whiteSpace: "nowrap" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.users.map(u => (
                  <tr key={u.id} style={{ borderBottom: "1px solid var(--border)", opacity: u.deleted_at ? 0.55 : 1 }}>
                    <td style={{ padding: "7px 10px", fontWeight: 500 }}>
                      {u.name || "—"}
                      {u.deleted_at && (
                        <span style={{ marginLeft: 6, background: "#dc262618", color: "#dc2626", borderRadius: 4, padding: "1px 6px", fontSize: 10, fontWeight: 700 }}>
                          REMOVED
                        </span>
                      )}
                    </td>
                    <td style={{ padding: "7px 10px" }}>{u.phone}</td>
                    <td style={{ padding: "7px 10px", color: "var(--text-muted)" }}>{u.business_type_label || "—"}</td>
                    <td style={{ padding: "7px 10px" }}>
                      <span style={{
                        background: `${PLAN_COLOR[u.subscription_plan] || "#6b7280"}18`,
                        color: PLAN_COLOR[u.subscription_plan] || "#6b7280",
                        borderRadius: 4, padding: "1px 7px", fontSize: 11, fontWeight: 700,
                      }}>
                        {u.subscription_plan || "BASIC"}
                      </span>
                    </td>
                    <td style={{ padding: "7px 10px" }}>
                      <span style={{
                        color: STATUS_COLOR[u.subscription_status] || "#6b7280",
                        fontSize: 12, fontWeight: 600,
                      }}>
                        {u.subscription_status || "ACTIVE"}
                      </span>
                    </td>
                    <td style={{ padding: "7px 10px", fontWeight: 700, textAlign: "right" }}>{(u.transactions_total ?? 0).toLocaleString()}</td>
                    <td style={{ padding: "7px 10px", color: "var(--text-muted)", textAlign: "right" }}>{(u.transactions_30d ?? 0).toLocaleString()}</td>
                    <td style={{ padding: "7px 10px", color: "var(--text-muted)", textAlign: "right" }}>{(u.customers ?? 0).toLocaleString()}</td>
                    <td style={{ padding: "7px 10px", color: "var(--text-muted)", textAlign: "right" }}>{(u.stock_items ?? 0).toLocaleString()}</td>
                    <td style={{ padding: "7px 10px", color: "var(--text-muted)", fontSize: 11, whiteSpace: "nowrap" }}>{fmtLastActive(u.last_active)}</td>
                    <td style={{ padding: "7px 10px", color: "var(--text-muted)", fontSize: 11, whiteSpace: "nowrap" }}>
                      {u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}
                    </td>
                    <td style={{ padding: "7px 10px", whiteSpace: "nowrap" }}>
                      {u.deleted_at ? (
                        <button
                          className="btn btn-sm" disabled={busyId === u.id}
                          onClick={() => restoreUser(u)}
                          title="Restore this business"
                          style={{ padding: "4px 8px", borderRadius: 6, fontSize: 11, fontWeight: 600, border: "1px solid var(--border)", background: "transparent", color: "#16a34a", display: "inline-flex", alignItems: "center", gap: 4 }}
                        ><RotateCcw size={12} /> Restore</button>
                      ) : (
                        <button
                          className="btn btn-sm" disabled={busyId === u.id}
                          onClick={() => removeUser(u)}
                          title="Remove this business"
                          style={{ padding: "4px 8px", borderRadius: 6, fontSize: 11, fontWeight: 600, border: "1px solid #fca5a5", background: "transparent", color: "#dc2626", display: "inline-flex", alignItems: "center", gap: 4 }}
                        ><Trash2 size={12} /> Remove</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {data.total > 50 && (
            <div style={{ display: "flex", gap: 8, marginTop: 14, justifyContent: "center" }}>
              <button
                className="btn btn-secondary"
                disabled={page <= 1}
                onClick={() => { setPage(p => p - 1); load(page - 1, q); }}
              >← Prev</button>
              <span style={{ padding: "6px 12px", fontSize: 13 }}>Page {page}</span>
              <button
                className="btn btn-secondary"
                disabled={page * 50 >= data.total}
                onClick={() => { setPage(p => p + 1); load(page + 1, q); }}
              >Next →</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── main admin page ──────────────────────────────────────────────────────────

// ── token codes tab ──────────────────────────────────────────────────────────

function TokenCodesTab() {
  const [plan, setPlan]           = useState("GO");
  const [days, setDays]           = useState("30");
  const [count, setCount]         = useState("10");
  const [batch, setBatch]         = useState("");
  const [expDays, setExpDays]     = useState("");
  const [generating, setGenerating] = useState(false);
  const [genErr, setGenErr]       = useState("");

  const [rows, setRows]           = useState([]);
  const [total, setTotal]         = useState(0);
  const [page, setPage]           = useState(1);
  const [loading, setLoading]     = useState(true);
  const [filterBatch, setFilterBatch] = useState("");

  function loadCodes(p = page, b = filterBatch) {
    setLoading(true);
    apiFetch(`admin/token-codes?page=${p}&per_page=50${b ? `&batch=${encodeURIComponent(b)}` : ""}`)
      .then(d => { setRows(d.rows || []); setTotal(d.total || 0); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }

  useEffect(() => { loadCodes(1, ""); }, []);

  async function generate(e) {
    e.preventDefault();
    setGenErr("");
    const n = parseInt(count);
    const d = parseInt(days);
    if (!n || n < 1 || n > 1000) { setGenErr("Count must be 1–1000."); return; }
    if (!d || d < 1) { setGenErr("Enter a valid number of days."); return; }
    setGenerating(true);
    try {
      const res = await fetch("/app/api/admin/token-codes/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          plan,
          duration_days: d,
          count: n,
          batch_label: batch.trim() || "",
          expires_in_days: expDays ? parseInt(expDays) : null,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to generate");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `tokens_${plan}_${batch || "batch"}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      loadCodes(1, "");
    } catch (e) { setGenErr(e.message); }
    finally { setGenerating(false); }
  }

  function search(e) {
    e.preventDefault();
    setPage(1);
    loadCodes(1, filterBatch);
  }

  const redeemed = rows.filter(r => r.redeemed).length;

  return (
    <div style={{ display: "grid", gap: 24 }}>
      {/* Generate form */}
      <div className="card">
        <div className="card-header">
          <span className="card-title"><Ticket size={15} /> Generate Token Codes</span>
        </div>
        <form onSubmit={generate} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 12, marginTop: 12 }}>
          <div className="form-group">
            <label className="form-label">Plan</label>
            <select value={plan} onChange={e => setPlan(e.target.value)}>
              <option value="GO">GO</option>
              <option value="PRO">PRO</option>
              <option value="PREMIUM">PREMIUM</option>
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">Duration (days)</label>
            <input type="number" min="1" value={days} onChange={e => setDays(e.target.value)} placeholder="e.g. 90" />
          </div>
          <div className="form-group">
            <label className="form-label">Number of codes</label>
            <input type="number" min="1" max="1000" value={count} onChange={e => setCount(e.target.value)} placeholder="e.g. 50" />
          </div>
          <div className="form-group">
            <label className="form-label">Batch label</label>
            <input value={batch} onChange={e => setBatch(e.target.value)} placeholder="e.g. NIRSAL-June-2026" />
          </div>
          <div className="form-group">
            <label className="form-label">Code expires in (days, optional)</label>
            <input type="number" min="1" value={expDays} onChange={e => setExpDays(e.target.value)} placeholder="e.g. 365" />
          </div>
          <div className="form-group" style={{ display: "flex", alignItems: "flex-end" }}>
            <button className="btn btn-primary" type="submit" disabled={generating} style={{ width: "100%" }}>
              <Download size={14} /> {generating ? "Generating…" : "Generate & Download CSV"}
            </button>
          </div>
        </form>
        {genErr && <div className="login-error" style={{ marginTop: 8 }}>{genErr}</div>}
      </div>

      {/* Issued codes list */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Issued Codes</span>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{total} total · {redeemed} redeemed</span>
        </div>
        <form onSubmit={search} style={{ display: "flex", gap: 8, margin: "12px 0" }}>
          <input value={filterBatch} onChange={e => setFilterBatch(e.target.value)} placeholder="Filter by batch label…" style={{ flex: 1 }} />
          <button className="btn btn-secondary" type="submit"><Search size={13} /></button>
          <button className="btn btn-secondary" type="button" onClick={() => { setFilterBatch(""); loadCodes(1, ""); }}>
            <RefreshCw size={13} />
          </button>
        </form>
        {loading ? (
          <p style={{ color: "var(--text-muted)" }}>Loading…</p>
        ) : rows.length === 0 ? (
          <p style={{ color: "var(--text-muted)" }}>No codes yet.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
              <thead>
                <tr style={{ textAlign: "left", color: "var(--text-muted)", borderBottom: "1px solid var(--border)" }}>
                  {["Code", "Plan", "Days", "Batch", "Expires", "Status", "Redeemed by", "Redeemed at"].map(h => (
                    <th key={h} style={{ padding: "8px 10px", fontWeight: 600 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.id} style={{ borderBottom: "1px solid var(--border)", opacity: r.redeemed ? 0.6 : 1 }}>
                    <td style={{ padding: "8px 10px", fontFamily: "monospace", fontWeight: 700 }}>{r.code}</td>
                    <td style={{ padding: "8px 10px" }}>
                      <span style={{ color: r.plan === "PRO" ? "#f59e0b" : "var(--brand)", fontWeight: 700 }}>{r.plan}</span>
                    </td>
                    <td style={{ padding: "8px 10px" }}>{r.duration_days}d</td>
                    <td style={{ padding: "8px 10px", color: "var(--text-muted)" }}>{r.batch_label || "—"}</td>
                    <td style={{ padding: "8px 10px", color: "var(--text-muted)" }}>{r.expires_at ? new Date(r.expires_at).toLocaleDateString() : "—"}</td>
                    <td style={{ padding: "8px 10px" }}>
                      {r.redeemed
                        ? <span style={{ color: "var(--text-muted)", fontSize: 11 }}>Used</span>
                        : <span style={{ color: "#16a34a", fontWeight: 600, fontSize: 11 }}>Available</span>}
                    </td>
                    <td style={{ padding: "8px 10px", color: "var(--text-muted)" }}>{r.redeemed_by || "—"}</td>
                    <td style={{ padding: "8px 10px", color: "var(--text-muted)" }}>{r.redeemed_at ? new Date(r.redeemed_at).toLocaleDateString() : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {total > 50 && (
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 12 }}>
            <button className="btn btn-secondary btn-sm" disabled={page <= 1} onClick={() => { setPage(p => p - 1); loadCodes(page - 1, filterBatch); }}>Prev</button>
            <span style={{ fontSize: 12, color: "var(--text-muted)", alignSelf: "center" }}>Page {page}</span>
            <button className="btn btn-secondary btn-sm" disabled={page * 50 >= total} onClick={() => { setPage(p => p + 1); loadCodes(page + 1, filterBatch); }}>Next</button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── application settings tab ────────────────────────────────────────────────────

function ReferralSettingsTab() {
  const [amount, setAmount] = useState("");
  const [current, setCurrent] = useState(null);
  const [busy, setBusy]     = useState(false);
  const [msg, setMsg]       = useState("");
  const [err, setErr]       = useState("");
  const [refData, setRefData] = useState(null);   // { referrers, total_bonus, total_referrals }
  const [refLoading, setRefLoading] = useState(true);

  useEffect(() => {
    apiFetch("admin/application-settings")
      .then(d => { setCurrent(d.cashback_amount); setAmount(String(d.cashback_amount)); })
      .catch(() => {});
    apiFetch("admin/applications")
      .then(setRefData)
      .catch(() => {})
      .finally(() => setRefLoading(false));
  }, []);

  async function save(e) {
    e.preventDefault();
    const n = parseAmt(amount);
    if (isNaN(n) || n < 0) { setErr("Enter a valid amount (₦0 or more)."); return; }
    setBusy(true); setErr(""); setMsg("");
    try {
      await apiPost("admin/application-settings", { cashback_amount: n });
      setCurrent(n);
      setMsg(`Cashback set to ${nairaFull(n)} per successful application.`);
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  const referrers = refData?.referrers || [];

  return (
    <div style={{ display: "grid", gap: 20 }}>
      <div className="card" style={{ maxWidth: 480 }}>
        <div className="card-header">
          <span className="card-title">Referral Cashback Rate</span>
        </div>
        <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 16, marginTop: 8 }}>
          Amount credited to a GO/PRO referrer's wallet when their invited user upgrades to GO plan.
          {current !== null && <><br /><strong style={{ color: "var(--ink)" }}>Current: {nairaFull(current)}</strong></>}
        </p>
        <form onSubmit={save} style={{ display: "flex", gap: 8 }}>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label">Cashback amount (₦)</label>
            <MoneyInput value={amount} onChange={v => setAmount(v)} placeholder="e.g. 500" disabled={busy} />
          </div>
          <div className="form-group" style={{ display: "flex", alignItems: "flex-end" }}>
            <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
          </div>
        </form>
        {msg && <div style={{ color: "#16a34a", fontSize: 13, marginTop: 8 }}>{msg}</div>}
        {err && <div className="login-error" style={{ marginTop: 8 }}>{err}</div>}
      </div>

      <div className="card">
        <div className="card-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span className="card-title">Referrers & Bonuses</span>
          {refData && (
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
              {refData.total_referrals} referral(s) · total bonus <strong style={{ color: "#16a34a" }}>{nairaFull(refData.total_bonus)}</strong>
            </span>
          )}
        </div>
        {refLoading ? (
          <div className="td-muted" style={{ padding: 12 }}>Loading…</div>
        ) : referrers.length === 0 ? (
          <div className="td-muted" style={{ padding: 12 }}>No applications yet.</div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ textAlign: "left", color: "var(--text-muted)" }}>
                  {["Referrer", "Code", "Plan", "Invited", "Active GO/PRO", "Bonus"].map(h => (
                    <th key={h} style={{ padding: "8px 10px", borderBottom: "1px solid var(--border)" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {referrers.map(r => (
                  <tr key={r.application_code} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: "8px 10px" }}>
                      <div style={{ fontWeight: 600 }}>{r.referrer_name || "—"}</div>
                      <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{r.referrer_phone || ""}</div>
                    </td>
                    <td style={{ padding: "8px 10px", fontFamily: "monospace" }}>{r.application_code}</td>
                    <td style={{ padding: "8px 10px" }}>{r.referrer_plan}</td>
                    <td style={{ padding: "8px 10px" }}>{r.total_invited}</td>
                    <td style={{ padding: "8px 10px" }}>{r.active_go}</td>
                    <td style={{ padding: "8px 10px", fontWeight: 700, color: r.bonus > 0 ? "#16a34a" : "var(--text-muted)" }}>
                      {nairaFull(r.bonus)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// ── supplier applications tab ────────────────────────────────────────────────
function ConnectionRequests() {
  const [conns, setConns]   = useState([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy]     = useState(null);

  function load(s) {
    setLoading(true);
    apiFetch(`admin/supplier-connections${s ? `?status=${s}` : ""}`)
      .then(d => setConns(d.connections || []))
      .catch(() => setConns([]))
      .finally(() => setLoading(false));
  }
  useEffect(() => { load(filter); }, [filter]);

  async function block(id) {
    setBusy(id);
    try {
      await fetch(`/app/api/admin/supplier-connections/${id}/block`, { method: "POST", credentials: "include" });
      load(filter);
    } finally { setBusy(null); }
  }

  const CS = { forwarded: "#d97706", accepted: "#059669", declined: "#6b7280", blocked: "#dc2626" };

  return (
    <div style={{ background: "#fff", border: "1px solid var(--border)", borderRadius: 10, padding: 16, marginBottom: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        <div style={{ fontWeight: 700, fontSize: 13 }}>Connection requests (auto-forwarded — block a bad actor)</div>
        <div style={{ display: "flex", gap: 6 }}>
          {["", "forwarded", "accepted", "declined", "blocked"].map(s => (
            <button key={s || "all"} onClick={() => setFilter(s)} style={{
              padding: "3px 10px", borderRadius: 99, border: "1px solid", cursor: "pointer", fontSize: 12,
              background: filter === s ? "var(--brand)" : "transparent",
              color: filter === s ? "#fff" : "var(--text-muted)",
              borderColor: filter === s ? "var(--brand)" : "var(--border)",
            }}>{s ? s.charAt(0).toUpperCase() + s.slice(1) : "All"}</button>
          ))}
        </div>
      </div>
      {loading ? <p style={{ color: "var(--text-muted)", fontSize: 13 }}>Loading…</p> : conns.length === 0 ? (
        <p style={{ color: "var(--text-muted)", fontSize: 13 }}>No {filter || ""} requests.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)", color: "var(--text-muted)", fontSize: 12 }}>
                <th style={{ textAlign: "left", padding: "4px 8px" }}>From</th>
                <th style={{ textAlign: "left", padding: "4px 8px" }}>To supplier</th>
                <th style={{ textAlign: "left", padding: "4px 8px" }}>Interest</th>
                <th style={{ textAlign: "left", padding: "4px 8px" }}>Status</th>
                <th style={{ padding: "4px 8px" }}></th>
              </tr>
            </thead>
            <tbody>
              {conns.map(c => (
                <tr key={c.id} style={{ borderBottom: "1px solid var(--border)" }}>
                  <td style={{ padding: "6px 8px" }}>{c.from_business_name}<br /><span style={{ color: "var(--text-muted)", fontSize: 11 }}>{c.from_phone}</span></td>
                  <td style={{ padding: "6px 8px" }}>{c.supplier_name}</td>
                  <td style={{ padding: "6px 8px", color: "var(--text-muted)" }}>{c.product_interest || "—"}</td>
                  <td style={{ padding: "6px 8px", fontWeight: 700, color: CS[c.connection_status] || "#666" }}>{c.connection_status}</td>
                  <td style={{ padding: "6px 8px", textAlign: "right" }}>
                    {c.connection_status !== "blocked" && (
                      <button onClick={() => block(c.id)} disabled={busy === c.id} style={{
                        padding: "3px 10px", borderRadius: 6, border: "1px solid #dc2626", background: "#fff",
                        color: "#dc2626", cursor: "pointer", fontSize: 12,
                      }}>{busy === c.id ? "…" : "Block"}</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function SuppliersTab() {
  const [apps, setApps]       = useState([]);
  const [stats, setStats]     = useState(null);
  const [filter, setFilter]   = useState("pending");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy]       = useState(null);
  const [rejectId, setRejectId]     = useState(null);
  const [rejectReason, setRejectReason] = useState("");

  function load(s) {
    setLoading(true);
    apiFetch(`admin/supplier-applications?status=${s}`)
      .then(d => setApps(d.applications || []))
      .catch(() => setApps([]))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load(filter);
    apiFetch("admin/supplier-stats").then(setStats).catch(() => {});
  }, [filter]);

  async function approve(id) {
    setBusy(id);
    try {
      await fetch(`/app/api/admin/supplier-applications/${id}/approve`, { method: "POST", credentials: "include" });
      load(filter);
      announcePendingChanged();
    } finally { setBusy(null); }
  }

  async function reject(id) {
    setBusy(id);
    try {
      await fetch(`/app/api/admin/supplier-applications/${id}/reject`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: rejectReason }),
      });
      setRejectId(null); setRejectReason("");
      load(filter);
      announcePendingChanged();
    } finally { setBusy(null); }
  }

  const STATUS_COLORS = { pending: "#d97706", approved: "#059669", rejected: "#dc2626" };

  return (
    <div>
      {/* Connection stats */}
      {stats && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px,1fr))", gap: 12, marginBottom: 24 }}>
          {[
            { label: "Contacts sent",         value: stats.total_contacts,     color: "#2563eb" },
            { label: "Confirmed connections",  value: stats.total_connections,  color: "#059669" },
            { label: "Overall avg rating",     value: stats.overall_avg_rating ? `${stats.overall_avg_rating} ★` : "—", color: "#d97706" },
            { label: "Approved suppliers",     value: stats.approved_suppliers, color: "#1a56db" },
          ].map(s => (
            <div key={s.label} style={{ background: "#fff", border: "1px solid var(--border)", borderRadius: 10, padding: "14px 16px" }}>
              <div style={{ fontSize: 22, fontWeight: 800, color: s.color }}>{s.value ?? "—"}</div>
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{s.label}</div>
            </div>
          ))}
        </div>
      )}
      {stats?.per_supplier?.length > 0 && (
        <div style={{ background: "#fff", border: "1px solid var(--border)", borderRadius: 10, padding: 16, marginBottom: 24 }}>
          <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 10 }}>Per-supplier connections</div>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)", color: "var(--text-muted)", fontSize: 12 }}>
                <th style={{ textAlign: "left", padding: "4px 8px" }}>Supplier</th>
                <th style={{ textAlign: "right", padding: "4px 8px" }}>Contacts</th>
                <th style={{ textAlign: "right", padding: "4px 8px" }}>Ratings</th>
                <th style={{ textAlign: "right", padding: "4px 8px" }}>Avg rating</th>
              </tr>
            </thead>
            <tbody>
              {stats.per_supplier.map(s => (
                <tr key={s.supplier_id} style={{ borderBottom: "1px solid var(--border)" }}>
                  <td style={{ padding: "6px 8px" }}>{s.business_name}</td>
                  <td style={{ padding: "6px 8px", textAlign: "right" }}>{s.contacts}</td>
                  <td style={{ padding: "6px 8px", textAlign: "right" }}>{s.ratings}</td>
                  <td style={{ padding: "6px 8px", textAlign: "right", color: s.avg_rating ? "#d97706" : "var(--text-muted)" }}>
                    {s.avg_rating ? `${s.avg_rating} ★` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ConnectionRequests />

      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {["pending","approved","rejected","all"].map(s => (
          <button key={s} onClick={() => setFilter(s)} style={{
            padding: "5px 14px", borderRadius: 99, border: "1px solid", cursor: "pointer", fontSize: 13,
            background: filter === s ? "var(--brand)" : "transparent",
            color: filter === s ? "#fff" : "var(--text-muted)",
            borderColor: filter === s ? "var(--brand)" : "var(--border)",
          }}>{s.charAt(0).toUpperCase() + s.slice(1)}</button>
        ))}
      </div>
      {loading ? <p style={{ color: "var(--text-muted)" }}>Loading…</p> : apps.length === 0 ? (
        <p style={{ color: "var(--text-muted)" }}>No {filter} applications.</p>
      ) : apps.map(a => (
        <div key={a.id} style={{ background: "#fff", border: "1px solid var(--border)", borderRadius: 10, padding: 16, marginBottom: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
            <strong style={{ fontSize: 15 }}>
              {a.business_name}
              {a.reapplied_at && a.verification_status === "pending" && (
                <span style={{ marginLeft: 8, fontSize: 11, fontWeight: 700, color: "#b45309",
                  background: "rgba(245,158,11,0.14)", borderRadius: 99, padding: "2px 8px" }}>
                  Re-applied
                </span>
              )}
            </strong>
            <span style={{ fontSize: 12, fontWeight: 700, color: STATUS_COLORS[a.verification_status] || "#666",
              background: "#f9fafb", borderRadius: 99, padding: "3px 10px", border: "1px solid var(--border)" }}>
              {a.verification_status}
            </span>
          </div>
          <div style={{ fontSize: 13, color: "var(--text-muted)", display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 8 }}>
            <span>Type: <strong>{a.supplier_type_label}</strong></span>
            <span>Phone: {a.owner_phone}</span>
            {a.cac_number && <span>CAC: {a.cac_number}</span>}
            {a.states_covered?.length > 0 && <span>States: {a.states_covered.join(", ")}</span>}
          </div>
          {a.reapplied_at && a.verification_status === "pending" && (
            <p style={{ fontSize: 12, color: "#b45309", marginBottom: 8 }}>
              Rejected before{a.previous_rejection_reason ? <> — reason: <em>{a.previous_rejection_reason}</em></> : ""}. Check it was fixed.
            </p>
          )}
          {a.bio && <p style={{ fontSize: 13, marginBottom: 8, color: "var(--text-secondary)" }}>{a.bio}</p>}
          {a.products?.length > 0 && (
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 10 }}>
              <strong>Products:</strong> {a.products.map(p => `${p.product_name}${p.min_order_qty ? ` (min ${p.min_order_qty} ${p.min_order_unit || ""})` : ""}`).join(" · ")}
            </div>
          )}
          {a.verification_status === "pending" && (
            rejectId === a.id ? (
              <div style={{ display: "flex", gap: 8, alignItems: "flex-start", flexWrap: "wrap" }}>
                <input value={rejectReason} onChange={e => setRejectReason(e.target.value)}
                  placeholder="Reason for rejection (optional)" style={{ flex: 1, minWidth: 200 }} />
                <button onClick={() => reject(a.id)} disabled={busy === a.id}
                  style={{ background: "var(--rose)", color: "#fff", border: "none", borderRadius: 6, padding: "6px 14px", cursor: "pointer", fontSize: 13 }}>
                  Confirm Reject
                </button>
                <button onClick={() => { setRejectId(null); setRejectReason(""); }}
                  style={{ background: "none", border: "1px solid var(--border)", borderRadius: 6, padding: "6px 14px", cursor: "pointer", fontSize: 13 }}>
                  Cancel
                </button>
              </div>
            ) : (
              <div style={{ display: "flex", gap: 8 }}>
                <button onClick={() => approve(a.id)} disabled={busy === a.id}
                  style={{ background: "#059669", color: "#fff", border: "none", borderRadius: 6, padding: "6px 16px", cursor: "pointer", fontSize: 13, fontWeight: 600 }}>
                  Approve
                </button>
                <button onClick={() => setRejectId(a.id)}
                  style={{ background: "none", border: "1px solid var(--rose)", color: "var(--rose)", borderRadius: 6, padding: "6px 16px", cursor: "pointer", fontSize: 13 }}>
                  Reject
                </button>
              </div>
            )
          )}
          {a.rejection_reason && (
            <p style={{ fontSize: 12, color: "var(--rose)", marginTop: 8 }}>Reason: {a.rejection_reason}</p>
          )}
        </div>
      ))}
    </div>
  );
}

// ── opportunities admin tab ──────────────────────────────────────────────────
const EMPTY_FIELD = { label: "", type: "text", placeholder: "", required: false, options: "" };

function FieldEditor({ fields, onChange }) {
  function update(i, val) { onChange(fields.map((f, j) => j === i ? val : f)); }
  function remove(i)      { onChange(fields.filter((_, j) => j !== i)); }
  function add()          { onChange([...fields, { ...EMPTY_FIELD }]); }

  return (
    <div>
      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8 }}>Application form fields</div>
      {fields.map((f, i) => (
        <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8, flexWrap: "wrap" }}>
          <input value={f.label} onChange={e => update(i, { ...f, label: e.target.value })}
            placeholder="Field label" style={{ flex: "1 1 140px" }} />
          <select value={f.type} onChange={e => update(i, { ...f, type: e.target.value })} style={{ flex: "0 0 100px" }}>
            <option value="text">Text</option>
            <option value="number">Number</option>
            <option value="textarea">Long text</option>
            <option value="select">Dropdown</option>
          </select>
          {f.type === "select" && (
            <input value={f.options} onChange={e => update(i, { ...f, options: e.target.value })}
              placeholder="opt1,opt2,opt3" style={{ flex: "1 1 140px" }} title="Comma-separated options" />
          )}
          <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, cursor: "pointer", whiteSpace: "nowrap" }}>
            <input type="checkbox" checked={f.required} onChange={e => update(i, { ...f, required: e.target.checked })} />
            Required
          </label>
          <button type="button" onClick={() => remove(i)}
            style={{ background: "none", border: "none", color: "var(--rose)", cursor: "pointer", fontSize: 16 }}>×</button>
        </div>
      ))}
      <button type="button" onClick={add} style={{ fontSize: 12, color: "var(--brand)", background: "none",
        border: "1px dashed var(--brand)", borderRadius: 6, padding: "4px 12px", cursor: "pointer" }}>
        + Add field
      </button>
    </div>
  );
}

function OpportunitiesTab() {
  const [opps, setOpps]           = useState([]);
  const [loading, setLoading]     = useState(true);
  const [showForm, setShowForm]   = useState(false);
  const [editing, setEditing]     = useState(null);
  const [busy, setBusy]           = useState(false);
  const [err, setErr]             = useState("");
  const [viewApps, setViewApps]   = useState(null);   // opportunity being viewed for applications
  const [oppApps, setOppApps]     = useState([]);
  const [appFilter, setAppFilter] = useState("all");
  const [updatingApp, setUpdatingApp] = useState(null);
  const [appNote, setAppNote]     = useState("");

  const empty = { title: "", partner_name: "", category: "general", description: "", link_url: "", is_active: true, application_fields: [], finance_partner_id: "" };
  const [financiers, setFinanciers] = useState([]);
  useEffect(() => {
    apiFetch("admin/finance-partners").then(d => setFinanciers(d.partners || [])).catch(() => {});
  }, []);
  const [form, setForm]           = useState({ ...empty });

  const CATS = ["finance","equipment","trade","products","general"];

  function load() {
    setLoading(true);
    apiFetch("admin/opportunities")
      .then(d => setOpps(d.opportunities || []))
      .catch(() => setOpps([]))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  function startEdit(o) {
    setEditing(o.id);
    setForm({ ...o, application_fields: JSON.parse(o.application_fields || "[]") });
    setShowForm(true);
  }
  function startNew() { setEditing(null); setForm({ ...empty }); setShowForm(true); }

  async function save(e) {
    e.preventDefault(); setErr(""); setBusy(true);
    try {
      const body = {
        ...form,
        application_fields: JSON.stringify(
          (form.application_fields || []).map(f => ({
            ...f,
            options: f.type === "select" ? f.options.split(",").map(s => s.trim()).filter(Boolean) : [],
          }))
        ),
      };
      if (editing) {
        await fetch(`/app/api/admin/opportunities/${editing}`, {
          method: "PUT", credentials: "include",
          headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
      } else {
        await fetch("/app/api/admin/opportunities", {
          method: "POST", credentials: "include",
          headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
      }
      setShowForm(false); setEditing(null); load();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function del(id) {
    if (!confirm("Delete this opportunity?")) return;
    await fetch(`/app/api/admin/opportunities/${id}`, { method: "DELETE", credentials: "include" });
    load();
  }

  function viewApplications(opp) {
    setViewApps(opp);
    apiFetch(`admin/opportunity-applications?opportunity_id=${opp.id}`)
      .then(d => setOppApps(d.applications || []))
      .catch(() => setOppApps([]));
  }

  async function updateAppStatus(appId, status, notes) {
    setUpdatingApp(appId);
    try {
      await fetch(`/app/api/admin/opportunity-applications/${appId}/status`, {
        method: "PATCH", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, admin_notes: notes }),
      });
      setOppApps(prev => prev.map(a => a.id === appId ? { ...a, status, admin_notes: notes } : a));
      load();                       // the "new" count on each opportunity
      announcePendingChanged();
    } finally { setUpdatingApp(null); }
  }

  const APP_STATUSES = ["submitted","reviewing","approved","declined"];
  const filteredOppApps = appFilter === "all" ? oppApps : oppApps.filter(a => a.status === appFilter);
  const dateStr = s => s ? new Date(s).toLocaleDateString("en-NG", { day: "numeric", month: "short", year: "numeric" }) : "—";

  // Applications view
  if (viewApps) {
    return (
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
          <button onClick={() => setViewApps(null)} style={{ background: "none", border: "1px solid var(--border)", borderRadius: 6, padding: "5px 12px", cursor: "pointer", fontSize: 13 }}>← Back</button>
          <strong style={{ fontSize: 15 }}>Applications: {viewApps.title}</strong>
          <span style={{ fontSize: 13, color: "var(--text-muted)" }}>{oppApps.length} total</span>
        </div>
        <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
          {["all", ...APP_STATUSES].map(s => (
            <button key={s} onClick={() => setAppFilter(s)} style={{
              padding: "5px 12px", borderRadius: 99, border: "1px solid", cursor: "pointer", fontSize: 12,
              background: appFilter === s ? "var(--brand)" : "transparent",
              color: appFilter === s ? "#fff" : "var(--text-muted)",
              borderColor: appFilter === s ? "var(--brand)" : "var(--border)",
            }}>{s.charAt(0).toUpperCase() + s.slice(1)}</button>
          ))}
        </div>
        {filteredOppApps.length === 0 ? (
          <p style={{ color: "var(--text-muted)" }}>No {appFilter === "all" ? "" : appFilter} applications.</p>
        ) : filteredOppApps.map(a => (
          <div key={a.id} style={{ background: "#fff", border: "1px solid var(--border)", borderRadius: 10, padding: 16, marginBottom: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
              <div>
                <strong style={{ fontSize: 14 }}>{a.applicant_name}</strong>
                <span style={{ fontSize: 12, color: "var(--text-muted)", marginLeft: 8 }}>{a.applicant_phone}</span>
                {a.applicant_email && <span style={{ fontSize: 12, color: "var(--text-muted)", marginLeft: 8 }}>{a.applicant_email}</span>}
              </div>
              <span style={{ fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 99, border: "1px solid var(--border)" }}>{a.status}</span>
            </div>
            {Object.keys(a.answers).length > 0 && (
              <div style={{ fontSize: 13, marginBottom: 10, color: "var(--text-secondary)", lineHeight: 1.8 }}>
                {Object.entries(a.answers).map(([k, v]) => v ? (
                  <div key={k}><strong>{k}:</strong> {v}</div>
                ) : null)}
              </div>
            )}
            {a.admin_notes && (
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>
                <strong>Your note to user:</strong> {a.admin_notes}
              </div>
            )}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <select defaultValue={a.status} onChange={e => {
                const newStatus = e.target.value;
                const note = prompt("Optional message to applicant:", a.admin_notes || "") ?? a.admin_notes ?? "";
                updateAppStatus(a.id, newStatus, note);
              }} style={{ fontSize: 13, padding: "4px 8px", borderRadius: 6, border: "1px solid var(--border)" }}
                disabled={updatingApp === a.id}>
                {APP_STATUSES.map(s => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
              </select>
              {updatingApp === a.id && <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Saving…</span>}
              <span style={{ fontSize: 11, color: "var(--text-muted)", marginLeft: "auto" }}>Applied {dateStr(a.created_at)}</span>
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <strong style={{ fontSize: 15 }}>Opportunities</strong>
        <button onClick={startNew} style={{ background: "var(--brand)", color: "#fff", border: "none",
          borderRadius: 8, padding: "7px 16px", cursor: "pointer", fontSize: 13, fontWeight: 600 }}>
          + New opportunity
        </button>
      </div>

      {showForm && (
        <form onSubmit={save} style={{ background: "#fff", border: "1px solid var(--border)", borderRadius: 10,
          padding: 20, marginBottom: 20, display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">Title *</label>
              <input value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))} required />
            </div>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">Partner name</label>
              <input value={form.partner_name} onChange={e => setForm(f => ({ ...f, partner_name: e.target.value }))} />
            </div>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">Category</label>
              <select value={form.category} onChange={e => setForm(f => ({ ...f, category: e.target.value }))}>
                {CATS.map(c => <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>)}
              </select>
            </div>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">Link URL</label>
              <input type="url" value={form.link_url} onChange={e => setForm(f => ({ ...f, link_url: e.target.value }))} placeholder="https://…" />
            </div>
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label">Description *</label>
            <textarea rows={3} value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} required />
          </div>
          {/* Link a financier and this card becomes their offer: it shows their
              requirements and applying runs consent + a frozen snapshot, so a
              business never has to look in two places for an offer. */}
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label">Financing offer from</label>
            <select value={form.finance_partner_id || ""}
              onChange={e => setForm(f => ({ ...f, finance_partner_id: e.target.value }))}>
              <option value="">Not a financing offer</option>
              {financiers.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <span className="form-hint">
              {form.finance_partner_id
                ? "Applicants go through consent and the scorecard snapshot — the intake questions below are ignored."
                : "Leave as is for an ordinary notice with your own intake questions."}
            </span>
          </div>
          {!form.finance_partner_id && (
            <FieldEditor
              fields={form.application_fields || []}
              onChange={fields => setForm(f => ({ ...f, application_fields: fields }))}
            />
          )}
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, cursor: "pointer" }}>
            <input type="checkbox" checked={form.is_active} onChange={e => setForm(f => ({ ...f, is_active: e.target.checked }))} />
            Active (visible to users)
          </label>
          {err && <div className="login-error">{err}</div>}
          <div style={{ display: "flex", gap: 8 }}>
            <button type="submit" disabled={busy} style={{ background: "var(--brand)", color: "#fff", border: "none",
              borderRadius: 8, padding: "7px 16px", cursor: "pointer", fontSize: 13 }}>
              {busy ? "Saving…" : editing ? "Save changes" : "Create"}
            </button>
            <button type="button" onClick={() => { setShowForm(false); setErr(""); }} style={{
              background: "none", border: "1px solid var(--border)", borderRadius: 8, padding: "7px 16px", cursor: "pointer", fontSize: 13 }}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {loading ? <p style={{ color: "var(--text-muted)" }}>Loading…</p> : opps.length === 0 ? (
        <p style={{ color: "var(--text-muted)" }}>No opportunities yet. Click "+ New opportunity" to add one.</p>
      ) : opps.map(o => (
        <div key={o.id} style={{ background: "#fff", border: "1px solid var(--border)", borderRadius: 10, padding: 14, marginBottom: 10,
          display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, opacity: o.is_active ? 1 : 0.55 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
              <strong style={{ fontSize: 14 }}>{o.title}</strong>
              <span style={{ fontSize: 11, color: "var(--text-muted)", background: "var(--surface)",
                borderRadius: 99, padding: "2px 8px", border: "1px solid var(--border)" }}>
                {o.category}
              </span>
              {!o.is_active && <span style={{ fontSize: 11, color: "var(--rose)", fontWeight: 600 }}>hidden</span>}
            </div>
            {o.partner_name && <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{o.partner_name}</div>}
            <p style={{ fontSize: 13, color: "var(--text-secondary)", margin: "4px 0 0" }}>{o.description.slice(0, 120)}{o.description.length > 120 ? "…" : ""}</p>
          </div>
          <div style={{ display: "flex", gap: 6, flexShrink: 0, flexWrap: "wrap" }}>
            <button onClick={() => viewApplications(o)} style={{
              background: o.application_count > 0 ? "var(--brand)" : "none",
              border: "1px solid var(--brand)",
              color: o.application_count > 0 ? "#fff" : "var(--brand)",
              borderRadius: 6, padding: "5px 12px", cursor: "pointer", fontSize: 12, fontWeight: 600 }}>
              Applications{o.application_count > 0 ? ` (${o.application_count})` : ""}
              {o.new_count > 0 && (
                <span className="nav-badge nav-badge-alert" style={{ marginLeft: 6 }}
                  title="Submitted and not looked at yet">
                  {o.new_count} new
                </span>
              )}
            </button>
            <button onClick={() => startEdit(o)} style={{ background: "none", border: "1px solid var(--border)",
              borderRadius: 6, padding: "5px 12px", cursor: "pointer", fontSize: 12 }}>Edit</button>
            <button onClick={() => del(o.id)} style={{ background: "none", border: "1px solid var(--rose)",
              color: "var(--rose)", borderRadius: 6, padding: "5px 12px", cursor: "pointer", fontSize: 12 }}>Delete</button>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── notify users tab ─────────────────────────────────────────────────────────
function NotifyTab() {
  const [title, setTitle] = useState("");
  const [body, setBody]   = useState("");
  const [target, setTarget] = useState("all");
  const [phone, setPhone] = useState("");
  const [alsoWa, setAlsoWa] = useState(false);
  const [busy, setBusy]   = useState(false);
  const [msg, setMsg]     = useState("");
  const [err, setErr]     = useState("");

  async function send(e) {
    e.preventDefault();
    setErr(""); setMsg("");
    if (!title.trim() || !body.trim()) { setErr("Enter a title and message."); return; }
    if (target === "phone" && !phone.trim()) { setErr("Enter the user's phone number."); return; }
    setBusy(true);
    try {
      const res = await apiPost("admin/notifications", {
        title: title.trim(), body: body.trim(), target,
        phone: target === "phone" ? phone.trim() : null, also_whatsapp: alsoWa,
      });
      setMsg(`Sent to ${res.recipients} user(s)${alsoWa ? ` · WhatsApp: ${res.whatsapp_sent}` : ""}.`);
      setTitle(""); setBody(""); setPhone("");
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="card" style={{ maxWidth: 560 }}>
      <div className="card-header"><span className="card-title">Send notification to users</span></div>
      <form onSubmit={send} style={{ display: "grid", gap: 12, marginTop: 12 }}>
        <div className="form-group">
          <label className="form-label">Send to</label>
          <select value={target} onChange={e => setTarget(e.target.value)} disabled={busy}>
            <option value="all">All business owners</option>
            <option value="phone">One user (by phone)</option>
          </select>
        </div>
        {target === "phone" && (
          <div className="form-group">
            <label className="form-label">User phone</label>
            <input value={phone} onChange={e => setPhone(e.target.value)} placeholder="e.g. 2348012345678" disabled={busy} />
          </div>
        )}
        <div className="form-group">
          <label className="form-label">Title</label>
          <input value={title} onChange={e => setTitle(e.target.value)} maxLength={120} placeholder="e.g. New feature: Invoices" disabled={busy} />
        </div>
        <div className="form-group">
          <label className="form-label">Message</label>
          <textarea value={body} onChange={e => setBody(e.target.value)} rows={4} maxLength={1000}
            placeholder="What do you want users to know?" disabled={busy} style={{ resize: "vertical" }} />
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
          <input type="checkbox" checked={alsoWa} onChange={e => setAlsoWa(e.target.checked)} style={{ width: "auto" }} disabled={busy} />
          Also send via WhatsApp
        </label>
        {msg && <div style={{ color: "#16a34a", fontSize: 13 }}>{msg}</div>}
        {err && <div className="login-error">{err}</div>}
        <div>
          <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? "Sending…" : "Send notification"}</button>
        </div>
      </form>
    </div>
  );
}

// ── Subscription payments: approve/reject bank transfers ──────────────────────
function PaymentsTab() {
  const [payments, setPayments] = useState(null);
  const [busyId, setBusyId]     = useState(null);
  const [msg, setMsg]           = useState("");
  const [err, setErr]           = useState("");

  function load() {
    setErr("");
    apiFetch("admin/subscription-payments?status=PENDING")
      .then(d => setPayments(d.payments || []))
      .catch(e => { setErr(e.message); setPayments([]); });
  }
  useEffect(() => { load(); }, []);

  async function act(id, kind) {
    setBusyId(id); setMsg(""); setErr("");
    try {
      const r = await apiPost(`admin/subscription-payments/${id}/${kind}`, {});
      setMsg(kind === "approve" ? `Approved — ${r.plan} plan is now active.` : "Payment rejected.");
      load();
    } catch (e) { setErr(e.message); }
    finally { setBusyId(null); }
  }

  if (payments === null) return <p style={{ color: "var(--text-muted)" }}>Loading…</p>;

  return (
    <section>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <h3 style={{ margin: 0 }}>Pending payments</h3>
        <button onClick={load} title="Refresh" style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)" }}>
          <RefreshCw size={15} />
        </button>
      </div>
      {msg && <div style={{ color: "#16a34a", marginBottom: 10 }}>{msg}</div>}
      {err && <div style={{ color: "var(--rose)", marginBottom: 10 }}>{err}</div>}
      {payments.length === 0 ? (
        <p style={{ color: "var(--text-muted)" }}>No pending payments. Bank transfers a user reports paying appear here for you to confirm.</p>
      ) : (
        <div style={{ display: "grid", gap: 10 }}>
          {payments.map(p => (
            <div key={p.id} className="card" style={{ padding: 12, display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center", justifyContent: "space-between" }}>
              <div>
                <div style={{ fontWeight: 700 }}>
                  {p.owner_name || "—"} <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>· {p.phone}</span>
                </div>
                <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
                  {p.plan} · {p.period === "YEARLY" ? "Yearly" : "Monthly"} · {nairaFull(p.amount)} · {p.method === "BANK_TRANSFER" ? "Bank transfer" : p.method}
                </div>
                {p.evidence_ref && <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>Ref: {p.evidence_ref}</div>}
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn btn-primary btn-sm" disabled={busyId === p.id}
                        style={{ background: "#16a34a", borderColor: "#16a34a" }}
                        onClick={() => act(p.id, "approve")}>
                  {busyId === p.id ? "…" : "Approve"}
                </button>
                <button className="btn btn-secondary btn-sm" disabled={busyId === p.id}
                        onClick={() => { if (window.confirm("Reject this payment?")) act(p.id, "reject"); }}>
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

// ── Finance partners + scorecard rules ──────────────────────────────────────
// Everything a partner deal depends on is editable here: their minimums, the
// commission, and how businesses are scored. No code change per partner.

const COMMISSION_TYPES = [
  ["PERCENT_OF_ASSET", "% of asset value"],
  ["FLAT_PER_DEAL", "Flat amount per deal"],
  ["PERCENT_OF_REPAYMENTS", "% of repayments"],
];
const COMMISSION_DUE = [
  ["ON_DELIVERY", "When the asset is delivered"],
  ["ON_FIRST_REPAYMENT", "On first repayment"],
  ["ON_COMPLETION", "When fully repaid"],
];
// The minimums a partner can demand. Keys match the backend's eligibility rules.
const ELIGIBILITY_FIELDS = [
  ["min_months_recorded", "Months of records"],
  ["min_months_on_platform", "Months on CreditVoice"],
  ["min_avg_monthly_sales", "Average monthly sales (₦)"],
  ["min_monthly_sales_floor", "Lowest monthly sales (₦)"],
  ["min_repeat_customer_pct", "% customers who return"],
  ["min_collection_rate_pct", "% of credit collected"],
  ["min_supplier_paid_pct", "% of suppliers paid"],
  ["min_score", "Scorecard score"],
  ["min_confidence", "Evidence confidence"],
];

const BLANK_PARTNER = {
  name: "", contact_name: "", contact_phone: "", contact_email: "", logo_url: "",
  asset_types: [], asset_value_min: null, asset_value_max: null, eligibility: {},
  nationwide: true, states_covered: [],
  scorecard_overrides: {},
  commission_type: "PERCENT_OF_ASSET", commission_value: 0,
  commission_due_on: "ON_DELIVERY", notes: "", is_active: true,
};

// The states a partner actually serves, so a business in Kano is never shown a
// Lagos-only financier.
function StatePicker({ selected, onChange }) {
  const [states, setStates] = useState([]);
  useEffect(() => {
    apiFetch("finance-meta").then(d => setStates(d.states || [])).catch(() => {});
  }, []);
  const toggle = st => onChange(
    selected.includes(st) ? selected.filter(x => x !== st) : [...selected, st]
  );
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, maxHeight: 160, overflowY: "auto" }}>
      {states.map(st => (
        <button key={st} type="button"
          className={`btn btn-xs btn-pill ${selected.includes(st) ? "btn-primary" : "btn-ghost"}`}
          onClick={() => toggle(st)}>
          {st}
        </button>
      ))}
    </div>
  );
}

// This partner's own scoring rules, on top of the global ones: ignore what they
// don't care about, re-weight what they do. Blank weight = use the global one.
function PartnerRules({ overrides, onChange }) {
  const [global, setGlobal] = useState(null);
  useEffect(() => {
    apiFetch("admin/scorecard-config").then(d => setGlobal(d.config)).catch(() => {});
  }, []);
  if (!global) return <p className="td-muted">Loading scoring rules…</p>;

  const comps = overrides?.components || {};
  const setComp = (key, patch) => {
    const next = { ...comps, [key]: { ...(comps[key] || {}), ...patch } };
    // Drop an entry that says nothing, so "no overrides" stays truly empty.
    Object.keys(next).forEach(k => {
      const v = next[k] || {};
      if (v.enabled !== false && (v.weight === undefined || v.weight === "")) delete next[k];
    });
    onChange(Object.keys(next).length ? { ...overrides, components: next } : {});
  };

  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr><th>Counts?</th><th>What it measures</th><th>Global weight</th><th>Their weight</th></tr>
        </thead>
        <tbody>
          {Object.entries(global.components || {}).map(([key, c]) => {
            const o = comps[key] || {};
            const counted = o.enabled !== false;
            return (
              <tr key={key}>
                <td>
                  <input type="checkbox" checked={counted}
                    onChange={e => setComp(key, e.target.checked ? { enabled: undefined } : { enabled: false })} />
                </td>
                <td>{c.label || key}<div className="td-muted" style={{ fontSize: 11 }}>{c.metric}</div></td>
                <td className="td-muted">{c.weight}</td>
                <td>
                  <input style={{ width: 70 }} inputMode="numeric" disabled={!counted}
                    value={o.weight ?? ""} placeholder={String(c.weight)}
                    onChange={e => setComp(key, {
                      weight: e.target.value === "" ? undefined : Number(e.target.value),
                    })} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="text-subtle text-sm" style={{ padding: "8px 0" }}>
        Leave everything as it is and this partner scores applicants the standard way.
      </div>
    </div>
  );
}

function PartnerForm({ initial, onSaved, onCancel }) {
  const [p, setP] = useState({ ...BLANK_PARTNER, ...(initial || {}) });
  const [assets, setAssets] = useState((initial?.asset_types || []).join(", "));
  const [showRules, setShowRules] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const set = (k, v) => setP(prev => ({ ...prev, [k]: v }));
  const setElig = (k, v) => setP(prev => ({
    ...prev,
    eligibility: { ...prev.eligibility, ...(v === "" ? { [k]: undefined } : { [k]: Number(v) }) },
  }));

  async function save() {
    if (!p.name.trim()) { setErr("Partner name is required."); return; }
    setBusy(true); setErr("");
    const body = {
      ...p,
      scorecard_overrides: p.scorecard_overrides || {},
      nationwide: p.nationwide !== false,
      states_covered: p.nationwide === false ? (p.states_covered || []) : [],
      asset_types: assets.split(",").map(s => s.trim()).filter(Boolean),
      eligibility: Object.fromEntries(
        Object.entries(p.eligibility || {}).filter(([, v]) => v !== undefined && v !== null && v !== "")
      ),
    };
    try {
      if (initial?.id) await apiPut(`admin/finance-partners/${initial.id}`, body);
      else await apiPost("admin/finance-partners", body);
      onSaved();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-header">
        <span className="card-title">{initial?.id ? `Edit ${initial.name}` : "New financier"}</span>
      </div>
      <div className="card-body" style={{ display: "grid", gap: 10 }}>
        {err && <div className="modal-error">{err}</div>}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <div className="form-group" style={{ flex: "1 1 220px", margin: 0 }}>
            <label className="form-label">Financier name *</label>
            <input value={p.name} onChange={e => set("name", e.target.value)} />
          </div>
          <div className="form-group" style={{ flex: "1 1 220px", margin: 0 }}>
            <label className="form-label">What they finance (comma separated)</label>
            <input value={assets} onChange={e => setAssets(e.target.value)} placeholder="motorcycle, freezer" />
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <div className="form-group" style={{ flex: "1 1 160px", margin: 0 }}>
            <label className="form-label">Contact name</label>
            <input value={p.contact_name || ""} onChange={e => set("contact_name", e.target.value)} />
          </div>
          <div className="form-group" style={{ flex: "1 1 160px", margin: 0 }}>
            <label className="form-label">Contact phone</label>
            <input value={p.contact_phone || ""} onChange={e => set("contact_phone", e.target.value)} />
          </div>
          <div className="form-group" style={{ flex: "1 1 160px", margin: 0 }}>
            <label className="form-label">Contact email</label>
            <input value={p.contact_email || ""} onChange={e => set("contact_email", e.target.value)} />
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <div className="form-group" style={{ flex: "1 1 140px", margin: 0 }}>
            <label className="form-label">Asset value from (₦)</label>
            <input inputMode="numeric" value={p.asset_value_min ?? ""}
              onChange={e => set("asset_value_min", e.target.value === "" ? null : parseAmt(e.target.value))} />
          </div>
          <div className="form-group" style={{ flex: "1 1 140px", margin: 0 }}>
            <label className="form-label">Asset value to (₦)</label>
            <input inputMode="numeric" value={p.asset_value_max ?? ""}
              onChange={e => set("asset_value_max", e.target.value === "" ? null : parseAmt(e.target.value))} />
          </div>
        </div>

        <div className="form-label" style={{ marginTop: 6 }}>Our commission</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <div className="form-group" style={{ flex: "1 1 180px", margin: 0 }}>
            <label className="form-label">Type</label>
            <select value={p.commission_type} onChange={e => set("commission_type", e.target.value)}>
              {COMMISSION_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div className="form-group" style={{ flex: "1 1 140px", margin: 0 }}>
            <label className="form-label">
              {p.commission_type === "FLAT_PER_DEAL" ? "Amount (₦)" : "Basis points (500 = 5%)"}
            </label>
            <input inputMode="numeric" value={p.commission_value ?? 0}
              onChange={e => set("commission_value", parseAmt(e.target.value) || 0)} />
          </div>
          <div className="form-group" style={{ flex: "1 1 200px", margin: 0 }}>
            <label className="form-label">Payable</label>
            <select value={p.commission_due_on} onChange={e => set("commission_due_on", e.target.value)}>
              {COMMISSION_DUE.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
        </div>

        <div className="form-label" style={{ marginTop: 6 }}>
          Their minimums <span className="text-subtle">— leave blank for no requirement</span>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {ELIGIBILITY_FIELDS.map(([key, label]) => (
            <div className="form-group" key={key} style={{ flex: "1 1 170px", margin: 0 }}>
              <label className="form-label" style={{ fontSize: 11 }}>{label}</label>
              <input inputMode="numeric" value={p.eligibility?.[key] ?? ""}
                onChange={e => setElig(key, e.target.value)} />
            </div>
          ))}
        </div>

        <div style={{ marginTop: 6 }}>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowRules(v => !v)}>
            {showRules ? "Hide" : "Set"} this partner's scoring rules
            {Object.keys(p.scorecard_overrides || {}).length > 0 ? " (customised)" : " (standard)"}
          </button>
          {showRules && (
            <PartnerRules overrides={p.scorecard_overrides || {}}
              onChange={v => set("scorecard_overrides", v)} />
          )}
        </div>

        <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, marginTop: 6 }}>
          <input type="checkbox"
            checked={!!(p.eligibility || {}).requires_registered_business}
            onChange={e => setElig("requires_registered_business", e.target.checked ? 1 : "")} />
          Only finances CAC-registered businesses
        </label>

        <div className="form-label" style={{ marginTop: 6 }}>Where they operate</div>
        <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
          <input type="checkbox" checked={p.nationwide !== false}
            onChange={e => set("nationwide", e.target.checked)} />
          Nationwide
        </label>
        {p.nationwide === false && (
          <StatePicker selected={p.states_covered || []} onChange={v => set("states_covered", v)} />
        )}

        <div className="form-group" style={{ margin: 0 }}>
          <label className="form-label">Internal notes</label>
          <textarea rows={2} value={p.notes || ""} onChange={e => set("notes", e.target.value)} />
        </div>
        <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
          <input type="checkbox" checked={!!p.is_active} onChange={e => set("is_active", e.target.checked)} />
          Active — businesses can see this partner
        </label>
      </div>
      <div className="modal-footer">
        <button className="btn btn-ghost" onClick={onCancel}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={busy}>
          {busy ? "Saving…" : "Save partner"}
        </button>
      </div>
    </div>
  );
}

function FinancePartnersPanel() {
  const [partners, setPartners] = useState([]);
  const [editing, setEditing] = useState(null);   // partner object, or "new"
  const [err, setErr] = useState("");

  function load() {
    apiFetch("admin/finance-partners")
      .then(d => setPartners(d.partners || []))
      .catch(e => setErr(e.message));
  }
  useEffect(load, []);

  async function remove(p) {
    if (!window.confirm(`Delete ${p.name}? Businesses will no longer see this partner.`)) return;
    try { await apiDelete(`admin/finance-partners/${p.id}`); load(); }
    catch (e) { setErr(e.message); }
  }

  const money = v => (v ? nairaFull(v) : "—");

  return (
    <div>
      {err && <div style={{ color: "var(--rose)", marginBottom: 10 }}>{err}</div>}
      {editing ? (
        <PartnerForm
          initial={editing === "new" ? null : editing}
          onCancel={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      ) : (
        <button className="btn btn-primary btn-sm" style={{ marginBottom: 12 }} onClick={() => setEditing("new")}>
          + Add financier
        </button>
      )}

      <div className="card">
        <div className="card-header">
          <span className="card-title">Financiers <span className="text-subtle text-sm">({partners.length})</span></span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>Financier</th><th>Finances</th><th>Asset value</th><th>Commission</th><th>Minimums</th><th>Status</th><th></th></tr>
            </thead>
            <tbody>
              {partners.length === 0 ? (
                <tr><td colSpan={7} className="td-muted">No partners yet.</td></tr>
              ) : partners.map(p => (
                <tr key={p.id}>
                  <td>
                    <strong>{p.name}</strong>
                    {p.contact_phone && <div className="td-muted" style={{ fontSize: 11 }}>{p.contact_phone}</div>}
                  </td>
                  <td>
                    {(p.asset_types || []).join(", ") || "—"}
                    <div className="td-muted" style={{ fontSize: 11 }}>
                      {p.nationwide === false
                        ? ((p.states_covered || []).join(", ") || "no states set")
                        : "Nationwide"}
                    </div>
                  </td>
                  <td className="td-muted">{money(p.asset_value_min)} – {money(p.asset_value_max)}</td>
                  <td>
                    {p.commission_type === "FLAT_PER_DEAL"
                      ? nairaFull(p.commission_value)
                      : `${(p.commission_value / 100).toFixed(2)}%`}
                    <div className="td-muted" style={{ fontSize: 11 }}>
                      {(COMMISSION_DUE.find(([v]) => v === p.commission_due_on) || [])[1]}
                    </div>
                  </td>
                  <td className="td-muted" style={{ fontSize: 11 }}>
                    {Object.keys(p.eligibility || {}).length === 0 ? "none" :
                      Object.entries(p.eligibility).map(([k, v]) => (
                        <div key={k}>{(ELIGIBILITY_FIELDS.find(([f]) => f === k) || [k, k])[1]}: {Number(v).toLocaleString()}</div>
                      ))}
                  </td>
                  <td>
                    <span className={`badge ${p.is_active ? "badge-green" : "badge-gray"}`}>
                      {p.is_active ? "Active" : "Paused"}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button className="btn btn-ghost btn-xs" onClick={() => setEditing(p)}>Edit</button>
                      <button className="btn btn-ghost btn-xs text-rose" onClick={() => remove(p)}>
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function ScorecardRulesPanel() {
  const [data, setData] = useState(null);
  const [cfg, setCfg] = useState(null);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  function load() {
    apiFetch("admin/scorecard-config")
      .then(d => { setData(d); setCfg(JSON.parse(JSON.stringify(d.config))); })
      .catch(e => setErr(e.message));
  }
  useEffect(load, []);

  if (err) return <div style={{ color: "var(--rose)" }}>{err}</div>;
  if (!cfg) return <p className="td-muted">Loading rules…</p>;

  const setComp = (key, field, value) => setCfg(prev => ({
    ...prev,
    components: { ...prev.components, [key]: { ...prev.components[key], [field]: Number(value) } },
  }));
  const setTier = (i, field, value) => setCfg(prev => {
    const tiers = prev.tiers.map((t, idx) => idx === i ? { ...t, [field]: field === "min_score" ? Number(value) : value } : t);
    return { ...prev, tiers };
  });

  const totalWeight = Object.values(cfg.components || {}).reduce((s, c) => s + Number(c.weight || 0), 0);

  async function runPreview() {
    setBusy(true); setErr(""); setMsg("");
    try { setPreview(await apiPost("admin/scorecard-preview", { config: cfg })); }
    catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function save() {
    setBusy(true); setErr(""); setMsg("");
    try {
      const r = await apiPost("admin/scorecard-config", { config: cfg, note: note.trim() || null });
      setMsg(`Saved as version ${r.version}. Previous versions are kept.`);
      setNote(""); load();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {msg && <div className="card card-body" style={{ color: "#166534" }}>{msg}</div>}

      <div className="card">
        <div className="card-header" style={{ flexWrap: "wrap", gap: 8 }}>
          <span className="card-title">Scoring rules <span className="text-subtle text-sm">v{data.version}</span></span>
          <span className="text-subtle text-sm">
            Weights total {totalWeight}{totalWeight !== 100 ? " — they don't have to add to 100, scores are scaled" : ""}
          </span>
        </div>
        <div className="card-body" style={{ display: "grid", gap: 10 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <div className="form-group" style={{ flex: "1 1 160px", margin: 0 }}>
              <label className="form-label">Window (months of history to read)</label>
              <input inputMode="numeric" value={cfg.window_months}
                onChange={e => setCfg({ ...cfg, window_months: Number(e.target.value) || 1 })} />
            </div>
            <div className="form-group" style={{ flex: "1 1 200px", margin: 0 }}>
              <label className="form-label">Minimum months before scoring</label>
              <input inputMode="numeric" value={cfg.min_months_recorded}
                onChange={e => setCfg({ ...cfg, min_months_recorded: Number(e.target.value) || 0 })} />
            </div>
          </div>

          <div className="table-scroll">
            <table>
              <thead>
                <tr><th>Component</th><th>Weight</th><th>Scores 0 at</th><th>Scores 100 at</th></tr>
              </thead>
              <tbody>
                {Object.entries(cfg.components || {}).map(([key, c]) => (
                  <tr key={key}>
                    <td>{c.label || key}<div className="td-muted" style={{ fontSize: 11 }}>{c.metric}</div></td>
                    <td><input style={{ width: 70 }} inputMode="numeric" value={c.weight}
                      onChange={e => setComp(key, "weight", e.target.value)} /></td>
                    <td><input style={{ width: 110 }} inputMode="numeric" value={c.zero}
                      onChange={e => setComp(key, "zero", e.target.value)} /></td>
                    <td><input style={{ width: 110 }} inputMode="numeric" value={c.full}
                      onChange={e => setComp(key, "full", e.target.value)} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="form-label">Tiers</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {(cfg.tiers || []).map((t, i) => (
              <div key={i} style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <input style={{ width: 130 }} value={t.name} onChange={e => setTier(i, "name", e.target.value)} />
                <span className="text-subtle text-sm">from</span>
                <input style={{ width: 70 }} inputMode="numeric" value={t.min_score}
                  onChange={e => setTier(i, "min_score", e.target.value)} />
              </div>
            ))}
          </div>
        </div>
        <div className="modal-footer" style={{ flexWrap: "wrap", gap: 8 }}>
          <input placeholder="Why this change? (kept in history)" value={note}
            onChange={e => setNote(e.target.value)} style={{ flex: "1 1 220px" }} />
          <button className="btn btn-secondary" onClick={runPreview} disabled={busy}>
            {busy ? "Working…" : "Preview effect"}
          </button>
          <button className="btn btn-primary" onClick={save} disabled={busy}>Save as new version</button>
          <button className="btn btn-ghost" onClick={() => setCfg(JSON.parse(JSON.stringify(data.defaults)))}>
            <RotateCcw size={13} /> Reset to defaults
          </button>
        </div>
      </div>

      {preview && (
        <div className="card">
          <div className="card-header"><span className="card-title">Effect on your businesses</span></div>
          <div className="table-scroll">
            <table>
              <thead><tr><th></th><th>Live rules</th><th>Proposed</th></tr></thead>
              <tbody>
                <tr><td>Businesses checked</td><td>{preview.live.businesses}</td><td>{preview.proposed.businesses}</td></tr>
                <tr><td>Scored</td><td>{preview.live.scored}</td><td>{preview.proposed.scored}</td></tr>
                <tr><td>Not enough records</td><td>{preview.live.unscored}</td><td>{preview.proposed.unscored}</td></tr>
                <tr><td>Average score</td><td>{preview.live.avg_score}</td><td><strong>{preview.proposed.avg_score}</strong></td></tr>
                {Array.from(new Set([...Object.keys(preview.live.tiers), ...Object.keys(preview.proposed.tiers)])).map(tier => (
                  <tr key={tier}>
                    <td>{tier}</td>
                    <td>{preview.live.tiers[tier] || 0}</td>
                    <td>{preview.proposed.tiers[tier] || 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-header"><span className="card-title">Change history</span></div>
        <div className="table-scroll">
          <table>
            <thead><tr><th>Version</th><th>Note</th><th>By</th><th>When</th><th></th></tr></thead>
            <tbody>
              {(data.history || []).map(h => (
                <tr key={h.version}>
                  <td>v{h.version}</td>
                  <td>{h.note || "—"}</td>
                  <td className="td-muted">{h.updated_by || "—"}</td>
                  <td className="td-muted">{h.created_at ? new Date(h.created_at).toLocaleString() : "—"}</td>
                  <td>{h.is_active ? <span className="badge badge-green">Live</span> : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── Application pipeline + commission ledger ───────────────────────────────────
// A deal moves SUBMITTED → SHARED → IN_REVIEW → APPROVED → DELIVERED. Reaching
// the partner's trigger raises the fee, so the ledger follows the deal.

const APP_STATUS_COLORS = {
  SUBMITTED: ["#92400e", "rgba(180,83,9,0.10)"],
  SHARED:    ["#1d4ed8", "rgba(29,78,216,0.10)"],
  IN_REVIEW: ["#1d4ed8", "rgba(29,78,216,0.10)"],
  APPROVED:  ["#166534", "rgba(22,101,52,0.10)"],
  DELIVERED: ["#166534", "rgba(22,101,52,0.16)"],
  DECLINED:  ["#b91c1c", "rgba(185,28,28,0.10)"],
  WITHDRAWN: ["#6b7280", "rgba(107,114,128,0.12)"],
};
const COMMISSION_NEXT = { PENDING: "DUE", DUE: "INVOICED", INVOICED: "PAID", PAID: null };

function AppStatus({ status }) {
  const [color, background] = APP_STATUS_COLORS[status] || ["#6b7280", "rgba(107,114,128,0.12)"];
  return <span className="badge" style={{ color, background, fontWeight: 700 }}>{status.replace("_", " ")}</span>;
}

function ApplicationRow({ r, onChanged, onOpen }) {
  const [assetValue, setAssetValue] = useState(r.asset_value ?? "");
  const [partnerRef, setPartnerRef] = useState(r.partner_ref ?? "");
  const [reason, setReason] = useState(r.decline_reason ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function patch(body) {
    setBusy(true); setErr("");
    try { await apiFetch(`admin/finance-applications/${r.id}`, {}, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }); onChanged(); }
    catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function commission(status) {
    setBusy(true); setErr("");
    try { await apiPost(`admin/finance-applications/${r.id}/commission`, { status }); onChanged(); }
    catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  const nextFee = COMMISSION_NEXT[r.commission_status];

  return (
    <tr>
      <td>
        <button type="button" className="name-chip" onClick={() => onOpen(r)} title="View the frozen record">
          <span>{r.business_name || r.owner_name || "—"}</span>
        </button>
        <div className="td-muted" style={{ fontSize: 11 }}>{r.owner_phone}</div>
        <div className="td-mono td-muted" style={{ fontSize: 11 }}>{r.application_code}</div>
      </td>
      <td>
        {r.partner_name || "—"}
        <div className="td-muted" style={{ fontSize: 11 }}>{r.asset_requested || "—"}</div>
      </td>
      <td>
        {r.tier || "Unrated"}
        <div className="td-muted" style={{ fontSize: 11 }}>
          {r.score ?? "—"} · {r.confidence}% evidence · rules v{r.config_version ?? "—"}
        </div>
      </td>
      <td>
        <input style={{ width: 110 }} inputMode="numeric" value={assetValue}
          placeholder="asset ₦"
          onChange={e => setAssetValue(e.target.value)}
          onBlur={() => {
            const v = assetValue === "" ? null : parseAmt(assetValue);
            if (v !== (r.asset_value ?? null)) patch({ asset_value: v });
          }} />
        <input style={{ width: 110, marginTop: 4 }} value={partnerRef} placeholder="their ref"
          onChange={e => setPartnerRef(e.target.value)}
          onBlur={() => { if (partnerRef !== (r.partner_ref || "")) patch({ partner_ref: partnerRef }); }} />
      </td>
      <td>
        <AppStatus status={r.status} />
        {err && <div style={{ color: "var(--rose)", fontSize: 11 }}>{err}</div>}
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 6 }}>
          {(r.next_statuses || []).filter(s => s !== "WITHDRAWN").map(s => (
            <button key={s} className="btn btn-ghost btn-xs" disabled={busy}
              onClick={() => s === "DECLINED"
                ? patch({ status: s, decline_reason: reason || window.prompt("Reason for declining?") || "" })
                : patch({ status: s })}>
              → {s.replace("_", " ")}
            </button>
          ))}
        </div>
        {r.decline_reason && <div className="td-muted" style={{ fontSize: 11 }}>{r.decline_reason}</div>}
      </td>
      <td>
        {r.commission_amount ? <strong>{nairaFull(r.commission_amount)}</strong> : <span className="td-muted">—</span>}
        <div className="td-muted" style={{ fontSize: 11 }}>{r.commission_status}</div>
        {r.commission_reason && !r.commission_amount && (
          <div className="td-muted" style={{ fontSize: 11 }}>{r.commission_reason}</div>
        )}
        {nextFee && (
          <button className="btn btn-ghost btn-xs" disabled={busy} onClick={() => commission(nextFee)}>
            mark {nextFee.toLowerCase()}
          </button>
        )}
      </td>
    </tr>
  );
}

// Once an asset is delivered, the repayment plan is entered here and becomes
// one supplier bill per installment on the business's own Suppliers page.
function RepaymentPanel({ application, onChanged }) {
  const [schedule, setSchedule] = useState(null);
  const [form, setForm] = useState({ installments: "", amount_each: "", every: "WEEKLY", first_due: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  function load() {
    apiFetch(`admin/finance-applications/${application.id}/schedule`)
      .then(d => setSchedule(d.schedule)).catch(e => setErr(e.message));
  }
  useEffect(load, [application.id]);

  async function create() {
    setBusy(true); setErr("");
    try {
      const r = await apiPost(`admin/finance-applications/${application.id}/schedule`, {
        installments: Number(form.installments) || 0,
        amount_each: parseAmt(form.amount_each) || 0,
        every: form.every,
        first_due: form.first_due || null,
      });
      setSchedule(r.schedule); onChanged && onChanged();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function act(path, body) {
    setBusy(true); setErr("");
    try {
      const r = await apiPost(`admin/finance-applications/${application.id}/${path}`, body);
      setSchedule(r.schedule); onChanged && onChanged();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
      <div className="form-label" style={{ marginBottom: 8 }}>Repayment plan</div>
      {err && <div className="modal-error">{err}</div>}

      {!schedule ? (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div className="form-group" style={{ margin: 0, flex: "0 1 120px" }}>
            <label className="form-label" style={{ fontSize: 11 }}>Installments</label>
            <input inputMode="numeric" value={form.installments}
              onChange={e => setForm({ ...form, installments: e.target.value })} placeholder="12" />
          </div>
          <div className="form-group" style={{ margin: 0, flex: "0 1 140px" }}>
            <label className="form-label" style={{ fontSize: 11 }}>Each (₦)</label>
            <input inputMode="numeric" value={form.amount_each}
              onChange={e => setForm({ ...form, amount_each: e.target.value })} placeholder="100,000" />
          </div>
          <div className="form-group" style={{ margin: 0, flex: "0 1 120px" }}>
            <label className="form-label" style={{ fontSize: 11 }}>Every</label>
            <select value={form.every} onChange={e => setForm({ ...form, every: e.target.value })}>
              <option value="WEEKLY">Week</option>
              <option value="MONTHLY">Month</option>
            </select>
          </div>
          <div className="form-group" style={{ margin: 0, flex: "0 1 150px" }}>
            <label className="form-label" style={{ fontSize: 11 }}>First due (optional)</label>
            <input type="date" value={form.first_due}
              onChange={e => setForm({ ...form, first_due: e.target.value })} />
          </div>
          <button className="btn btn-primary btn-sm" disabled={busy} onClick={create}>
            {busy ? "Creating…" : "Create plan"}
          </button>
        </div>
      ) : (
        <>
          <div className="text-subtle text-sm" style={{ marginBottom: 8 }}>
            {schedule.settled_count} of {schedule.count} paid · {nairaFull(schedule.confirmed_paid)} confirmed ·
            {" "}{nairaFull(schedule.outstanding)} outstanding
            {schedule.overdue_count > 0 && <span style={{ color: "var(--rose)" }}> · {schedule.overdue_count} overdue</span>}
            {schedule.settled_count > 0 && ` · ${schedule.on_time_pct}% on time`}
          </div>
          <div className="table-scroll">
            <table>
              <thead><tr><th>#</th><th>Due</th><th>Amount</th><th>Status</th><th></th></tr></thead>
              <tbody>
                {schedule.installments.map(i => (
                  <tr key={i.installment_no}>
                    <td>{i.installment_no}</td>
                    <td className="td-muted">{i.due_date ? new Date(i.due_date).toLocaleDateString() : "—"}</td>
                    <td>{nairaFull(i.amount)}</td>
                    <td>
                      {i.settled
                        ? (i.confirmed >= i.amount
                            ? <span className="badge badge-green">confirmed</span>
                            : <span className="badge" style={{ color: "#92400e", background: "rgba(180,83,9,0.10)" }}>claimed</span>)
                        : i.overdue ? <span className="badge" style={{ color: "#b91c1c", background: "rgba(185,28,28,0.10)" }}>overdue</span>
                        : <span className="td-muted">due</span>}
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 4 }}>
                        {i.settled && i.confirmed < i.amount && (
                          <button className="btn btn-ghost btn-xs" disabled={busy}
                            onClick={() => act("repayments/confirm", { installment_no: i.installment_no })}>
                            confirm
                          </button>
                        )}
                        {!i.settled && (
                          <button className="btn btn-ghost btn-xs" disabled={busy}
                            onClick={() => act("repayments", { installment_no: i.installment_no, amount: i.outstanding })}>
                            mark paid
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function SnapshotModal({ application, onClose, onChanged }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    apiFetch(`admin/finance-applications/${application.id}`).then(setData).catch(e => setErr(e.message));
  }, [application.id]);

  const m = data?.snapshot?.metrics;
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal modal-wide">
        <div className="modal-header">
          <span className="modal-title">
            {application.business_name || application.owner_phone} — {application.application_code}
          </span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          {err && <div className="modal-error">{err}</div>}
          {!data ? <p className="td-muted">Loading…</p> : !m ? (
            <p className="td-muted">No snapshot stored for this application.</p>
          ) : (
            <>
              <p className="text-subtle text-sm">
                The record exactly as it stood when they applied
                {data.consent_given_at ? ` (consent given ${new Date(data.consent_given_at).toLocaleDateString()})` : ""}
                — scored on rules v{data.config_version}. This is what a partner is shown.
              </p>
              <table className="history-table">
                <tbody>
                  <tr><td>Tier / score / evidence</td><td className="receipt-right">{data.tier} · {data.score ?? "—"} · {data.confidence}%</td></tr>
                  <tr><td>Average monthly sales</td><td className="receipt-right">{nairaFull(m.avg_monthly_sales)}</td></tr>
                  <tr><td>Lowest month</td><td className="receipt-right">{nairaFull(m.min_monthly_sales)}</td></tr>
                  <tr><td>Months of records · recording days/month</td><td className="receipt-right">{m.months_recorded} · {m.avg_active_days_per_month}</td></tr>
                  <tr><td>Gross margin (coverage)</td><td className="receipt-right">{m.gross_margin_pct}% ({m.margin_coverage_pct}%)</td></tr>
                  <tr><td>Customers · returning</td><td className="receipt-right">{m.total_customers} · {m.repeat_customer_pct}%</td></tr>
                  <tr><td>Credit given · collected</td><td className="receipt-right">{nairaFull(m.credit_sales)} · {m.collection_rate_pct}%</td></tr>
                  <tr><td>Owed to them · due in 30 days</td><td className="receipt-right">{nairaFull(m.receivables)} · {nairaFull(m.expected_next_30_days)}</td></tr>
                  <tr><td>Suppliers paid · overdue</td><td className="receipt-right">{m.supplier_paid_pct}% · {nairaFull(m.overdue_payables)}</td></tr>
                  <tr><td>Sales tied to a named customer</td><td className="receipt-right">{m.corroborated_revenue_pct}%</td></tr>
                  {(data.snapshot?.not_applicable || []).length > 0 && (
                    <tr>
                      <td>Not counted (no records)</td>
                      <td className="receipt-right td-muted">
                        {data.snapshot.not_applicable.map(s => s.label).join(", ")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
              {application.note && (
                <p style={{ marginTop: 10, fontSize: 13 }}><strong>They said:</strong> {application.note}</p>
              )}
              {application.status === "DELIVERED" && (
                <RepaymentPanel application={application} onChanged={onChanged} />
              )}
            </>
          )}
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

function ApplicationsPanel() {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState(null);
  const [err, setErr] = useState("");

  function load() {
    apiFetch("admin/finance-applications", status ? { status } : {})
      .then(setData).catch(e => setErr(e.message));
  }
  useEffect(load, [status]);

  if (err) return <div style={{ color: "var(--rose)" }}>{err}</div>;
  if (!data) return <p className="td-muted">Loading applications…</p>;

  const t = data.commission_totals || {};
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="metrics-grid">
        <MetricCardLite label="Fees due" value={nairaFull(t.DUE || 0)} />
        <MetricCardLite label="Invoiced" value={nairaFull(t.INVOICED || 0)} />
        <MetricCardLite label="Paid to us" value={nairaFull(t.PAID || 0)} />
        <MetricCardLite label="Delivered deals" value={data.counts?.DELIVERED || 0} />
      </div>

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {["", "SUBMITTED", "SHARED", "IN_REVIEW", "APPROVED", "DELIVERED", "DECLINED", "WITHDRAWN"].map(s => (
          <button key={s || "all"} className={`btn btn-sm btn-pill ${status === s ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setStatus(s)}>
            {s ? `${s.replace("_", " ")} (${data.counts?.[s] ?? 0})` : "All"}
          </button>
        ))}
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">Applications <span className="text-subtle text-sm">({data.applications.length})</span></span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>Business</th><th>Partner</th><th>Scorecard</th><th>Deal</th><th>Stage</th><th>Our fee</th></tr>
            </thead>
            <tbody>
              {data.applications.length === 0 ? (
                <tr><td colSpan={6} className="td-muted">No applications{status ? " at this stage" : " yet"}.</td></tr>
              ) : data.applications.map(r => (
                <ApplicationRow key={r.id} r={r} onChanged={load} onOpen={setOpen} />
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {open && <SnapshotModal application={open} onClose={() => setOpen(null)} onChanged={load} />}
    </div>
  );
}

function MetricCardLite({ label, value }) {
  return (
    <div className="card card-body">
      <div className="text-subtle text-sm">{label}</div>
      <div style={{ fontSize: 18, fontWeight: 800 }}>{value}</div>
    </div>
  );
}

// Logins for a financier's own staff, who work at /financier. Distinct from a
// user's business partners — different people, different app, different cookie.
function FinancierLoginsPanel() {
  const [users, setUsers] = useState([]);
  const [partners, setPartners] = useState([]);
  const [form, setForm] = useState({ finance_partner_id: "", name: "", phone: "", email: "" });
  const [issued, setIssued] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  function load() {
    apiFetch("admin/financier-users").then(d => setUsers(d.users || [])).catch(e => setErr(e.message));
    apiFetch("admin/finance-partners").then(d => setPartners(d.partners || [])).catch(() => {});
  }
  useEffect(load, []);

  async function create() {
    setBusy(true); setErr(""); setIssued(null);
    try {
      const r = await apiPost("admin/financier-users", form);
      setIssued(r);
      setForm({ finance_partner_id: form.finance_partner_id, name: "", phone: "", email: "" });
      load();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function act(id, what) {
    if (what === "deactivate" && !window.confirm("Deactivate this login? They are signed out immediately.")) return;
    setBusy(true); setErr("");
    try {
      const r = await apiPost(`admin/financier-users/${id}/${what}`, {});
      if (what === "reinvite") setIssued(r);
      load();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {err && <div style={{ color: "var(--rose)" }}>{err}</div>}
      {issued && issued.invite_code && (
        <div className="card card-body" style={{ color: "#166534" }}>
          Invite code for <strong>{issued.name}</strong>: <strong>{issued.invite_code}</strong>
          <div className="text-subtle text-sm">
            They open <strong>/financier</strong>, choose "I have an invite code", and set their own PIN.
            The code expires in 7 days.
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-header"><span className="card-title">Invite a financier's staff</span></div>
        <div className="card-body" style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div className="form-group" style={{ margin: 0, flex: "1 1 180px" }}>
            <label className="form-label">Financier</label>
            <select value={form.finance_partner_id}
              onChange={e => setForm({ ...form, finance_partner_id: e.target.value })}>
              <option value="">Select…</option>
              {partners.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <div className="form-group" style={{ margin: 0, flex: "1 1 150px" }}>
            <label className="form-label">Their name</label>
            <input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} />
          </div>
          <div className="form-group" style={{ margin: 0, flex: "1 1 150px" }}>
            <label className="form-label">Their phone</label>
            <input inputMode="tel" value={form.phone}
              onChange={e => setForm({ ...form, phone: e.target.value })} />
          </div>
          <div className="form-group" style={{ margin: 0, flex: "1 1 170px" }}>
            <label className="form-label">Email (optional)</label>
            <input value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} />
          </div>
          <button className="btn btn-primary btn-sm" disabled={busy || !form.finance_partner_id || !form.name || !form.phone}
            onClick={create}>
            {busy ? "Working…" : "Create login"}
          </button>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">Financier logins <span className="text-subtle text-sm">({users.length})</span></span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>Person</th><th>Financier</th><th>Status</th><th>Last sign-in</th><th></th></tr>
            </thead>
            <tbody>
              {users.length === 0 ? (
                <tr><td colSpan={5} className="td-muted">No financier logins yet.</td></tr>
              ) : users.map(u => (
                <tr key={u.id}>
                  <td>
                    <strong>{u.name}</strong>
                    <div className="td-muted" style={{ fontSize: 11 }}>{u.phone}{u.email ? ` · ${u.email}` : ""}</div>
                  </td>
                  <td>{u.financier_name || "—"}</td>
                  <td>
                    {!u.is_active ? <span className="badge badge-gray">Deactivated</span>
                      : u.accepted ? <span className="badge badge-green">Active</span>
                      : <span className="badge" style={{ color: "#92400e", background: "rgba(180,83,9,0.10)" }}>
                          Invited{u.invite_code ? ` · ${u.invite_code}` : ""}
                        </span>}
                  </td>
                  <td className="td-muted">
                    {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "never"}
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button className="btn btn-ghost btn-xs" disabled={busy}
                        onClick={() => act(u.id, "reinvite")}>new code</button>
                      {u.is_active && (
                        <button className="btn btn-ghost btn-xs text-rose" disabled={busy}
                          onClick={() => act(u.id, "deactivate")}>deactivate</button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function FinanceTab() {
  const [panel, setPanel] = useState("applications");
  const PANELS = [["applications", "Applications"], ["partners", "Financiers"],
                  ["logins", "Financier logins"], ["rules", "Scorecard rules"]];
  return (
    <div>
      <div className="page-tabs" style={{ marginBottom: 14 }}>
        {PANELS.map(([key, label]) => (
          <button key={key} className={`page-tab${panel === key ? " active" : ""}`} onClick={() => setPanel(key)}>
            {label}
          </button>
        ))}
      </div>
      {panel === "applications" ? <ApplicationsPanel />
        : panel === "partners" ? <FinancePartnersPanel />
        : panel === "logins" ? <FinancierLoginsPanel />
        : <ScorecardRulesPanel />}
    </div>
  );
}

// What appears on the public /resources and /events pages. Those are rendered
// as plain HTML on the server so search engines can read them — a link inside
// the app would be invisible, since the app sits behind a login.
const LINK_RELS = [
  ["EDITORIAL", "We recommend it (normal link)"],
  ["SPONSORED", "Paid or exchanged (marked sponsored)"],
  ["NOFOLLOW", "Listed only (no endorsement)"],
];
const BLANK_LISTING = {
  page: "resources", section: "", title: "", url: "", blurb: "",
  link_rel: "EDITORIAL", event_date: "", event_venue: "", sort_order: 0, is_active: true,
};

function PublicPagesTab() {
  const [listings, setListings] = useState([]);
  const [form, setForm] = useState(BLANK_LISTING);
  const [editingId, setEditingId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const set = (k, v) => setForm(prev => ({ ...prev, [k]: v }));

  function load() {
    apiFetch("admin/public-listings").then(d => setListings(d.listings || []))
      .catch(e => setErr(e.message));
  }
  useEffect(load, []);

  async function save() {
    setBusy(true); setErr("");
    try {
      const body = { ...form, sort_order: Number(form.sort_order) || 0 };
      if (editingId) await apiPut(`admin/public-listings/${editingId}`, body);
      else await apiPost("admin/public-listings", body);
      setForm(BLANK_LISTING); setEditingId(null); load();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function remove(row) {
    if (!window.confirm(`Remove "${row.title}" from the public page?`)) return;
    try { await apiDelete(`admin/public-listings/${row.id}`); load(); }
    catch (e) { setErr(e.message); }
  }

  function edit(row) {
    setEditingId(row.id);
    setForm({ ...BLANK_LISTING, ...row, section: row.section || "",
              url: row.url || "", blurb: row.blurb || "",
              event_date: row.event_date || "", event_venue: row.event_venue || "" });
  }

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {err && <div style={{ color: "var(--rose)" }}>{err}</div>}
      <div className="card card-body text-subtle text-sm">
        These entries appear on <a href="/resources" target="_blank" rel="noopener">/resources</a> and
        {" "}<a href="/events" target="_blank" rel="noopener">/events</a>, which are public pages search
        engines can read. Mark anything paid for or exchanged as sponsored.
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">{editingId ? "Edit entry" : "Add an entry"}</span>
          {editingId && (
            <button className="btn btn-ghost btn-sm"
              onClick={() => { setEditingId(null); setForm(BLANK_LISTING); }}>Cancel</button>
          )}
        </div>
        <div className="card-body" style={{ display: "grid", gap: 10 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <div className="form-group" style={{ margin: 0, flex: "0 1 140px" }}>
              <label className="form-label">Page</label>
              <select value={form.page} onChange={e => set("page", e.target.value)}>
                <option value="resources">Resources</option>
                <option value="events">Events</option>
              </select>
            </div>
            <div className="form-group" style={{ margin: 0, flex: "1 1 170px" }}>
              <label className="form-label">Section heading</label>
              <input value={form.section} onChange={e => set("section", e.target.value)}
                placeholder={form.page === "events" ? "(events group themselves)" : "Sponsors"} />
            </div>
            <div className="form-group" style={{ margin: 0, flex: "0 1 110px" }}>
              <label className="form-label">Order</label>
              <input inputMode="numeric" value={form.sort_order}
                onChange={e => set("sort_order", e.target.value)} />
            </div>
          </div>
          <div className="form-group" style={{ margin: 0 }}>
            <label className="form-label">Title *</label>
            <input value={form.title} onChange={e => set("title", e.target.value)} />
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <div className="form-group" style={{ margin: 0, flex: "1 1 240px" }}>
              <label className="form-label">Link (optional)</label>
              <input value={form.url} onChange={e => set("url", e.target.value)}
                placeholder="https://…" />
            </div>
            <div className="form-group" style={{ margin: 0, flex: "1 1 220px" }}>
              <label className="form-label">How to mark the link</label>
              <select value={form.link_rel} onChange={e => set("link_rel", e.target.value)}>
                {LINK_RELS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
          </div>
          <div className="form-group" style={{ margin: 0 }}>
            <label className="form-label">Short write-up</label>
            <textarea rows={2} value={form.blurb} onChange={e => set("blurb", e.target.value)} />
          </div>
          {form.page === "events" && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <div className="form-group" style={{ margin: 0, flex: "0 1 170px" }}>
                <label className="form-label">Event date</label>
                <input type="date" value={form.event_date}
                  onChange={e => set("event_date", e.target.value)} />
              </div>
              <div className="form-group" style={{ margin: 0, flex: "1 1 200px" }}>
                <label className="form-label">Venue</label>
                <input value={form.event_venue} onChange={e => set("event_venue", e.target.value)} />
              </div>
            </div>
          )}
          <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
            <input type="checkbox" checked={!!form.is_active}
              onChange={e => set("is_active", e.target.checked)} />
            Visible on the page
          </label>
        </div>
        <div className="modal-footer">
          <button className="btn btn-primary" disabled={busy || !form.title.trim()} onClick={save}>
            {busy ? "Saving…" : editingId ? "Save changes" : "Add to page"}
          </button>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">On the public pages <span className="text-subtle text-sm">({listings.length})</span></span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>Page</th><th>Entry</th><th>Link</th><th>Order</th><th>Status</th><th></th></tr>
            </thead>
            <tbody>
              {listings.length === 0 ? (
                <tr><td colSpan={6} className="td-muted">Nothing listed yet.</td></tr>
              ) : listings.map(l => (
                <tr key={l.id}>
                  <td>{l.page}<div className="td-muted" style={{ fontSize: 11 }}>{l.section || "—"}</div></td>
                  <td>
                    <strong>{l.title}</strong>
                    {l.event_date && (
                      <div className="td-muted" style={{ fontSize: 11 }}>
                        {l.event_date}{l.event_venue ? ` · ${l.event_venue}` : ""}
                      </div>
                    )}
                  </td>
                  <td className="td-muted" style={{ fontSize: 11, maxWidth: 200, overflow: "hidden" }}>
                    {l.url || "—"}
                    <div>{(LINK_RELS.find(([v]) => v === l.link_rel) || ["", l.link_rel])[1]}</div>
                  </td>
                  <td>{l.sort_order}</td>
                  <td>
                    <span className={`badge ${l.is_active ? "badge-green" : "badge-gray"}`}>
                      {l.is_active ? "Visible" : "Hidden"}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button className="btn btn-ghost btn-xs" onClick={() => edit(l)}>Edit</button>
                      <button className="btn btn-ghost btn-xs text-rose" onClick={() => remove(l)}>
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── Reviews on the landing page, and the public-site settings ───────────────
// Reviews are written by the businesses themselves and carry their phone
// number, so nothing here goes live until it is approved AND featured.

const SETTING_FIELDS = [
  ["facebook_url", "Facebook page", "https://facebook.com/…"],
  ["instagram_url", "Instagram profile", "https://instagram.com/…"],
  ["tiktok_url", "TikTok profile", "https://tiktok.com/@…"],
  ["whatsapp_url", "WhatsApp link", "https://wa.me/234…"],
  ["featured_reviews", "Reviews to show on the homepage", "3"],
];

// Not a URL like the rest: this one decides what the whole site is allowed to
// claim, so it gets its own control and its own explanation.
const WA_LIVE_KEY = "whatsapp_live";
const WA_ON = new Set(["1", "true", "yes", "on", "live"]);

function SiteTab() {
  const [reviews, setReviews] = useState([]);
  const [counts, setCounts] = useState({});
  const [filter, setFilter] = useState("PENDING");
  const [settings, setSettings] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [saved, setSaved] = useState("");

  function loadReviews() {
    apiFetch("admin/reviews", filter ? { status: filter } : {})
      .then(d => { setReviews(d.reviews || []); setCounts(d.counts || {}); })
      .catch(e => setErr(e.message));
  }
  useEffect(loadReviews, [filter]);
  useEffect(() => {
    apiFetch("admin/site-settings").then(d => setSettings(d.settings || {}))
      .catch(e => setErr(e.message));
  }, []);

  async function patch(row, body) {
    setErr("");
    try { await apiPatch(`admin/reviews/${row.id}`, body); loadReviews(); announcePendingChanged(); }
    catch (e) { setErr(e.message); }
  }

  async function saveSettings() {
    setBusy(true); setErr(""); setSaved("");
    try {
      const d = await apiPost("admin/site-settings", { settings });
      setSettings(d.settings || settings);
      setSaved("Saved. The homepage updates within a minute.");
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  const featuredCount = reviews.filter(r => r.is_featured).length;

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {err && <div style={{ color: "var(--rose)" }}>{err}</div>}

      <div className="card">
        <div className="card-header">
          <span className="card-title">Social links &amp; homepage settings</span>
        </div>
        <div className="card-body" style={{ display: "grid", gap: 10 }}>
          <div className="text-subtle text-sm">
            These feed the <a href="/" target="_blank" rel="noopener">homepage</a> directly —
            no deploy needed. Leave a link blank to hide that icon.
          </div>
          {settings === null ? <div className="text-subtle text-sm">Loading…</div> : <>
            {SETTING_FIELDS.map(([key, label, ph]) => (
              <div className="form-group" style={{ margin: 0 }} key={key}>
                <label className="form-label">{label}</label>
                <input value={settings[key] || ""} placeholder={ph}
                  onChange={e => setSettings(s => ({ ...s, [key]: e.target.value }))} />
              </div>
            ))}

            <div style={{
              border: "1px solid var(--border)", borderRadius: 10, padding: 12,
              display: "grid", gap: 6,
            }}>
              <label style={{ display: "flex", gap: 8, alignItems: "center", fontWeight: 600 }}>
                <input type="checkbox"
                  checked={WA_ON.has(String(settings[WA_LIVE_KEY] || "").toLowerCase())}
                  onChange={e => setSettings(s => ({ ...s, [WA_LIVE_KEY]: e.target.checked ? "yes" : "no" }))} />
                WhatsApp is approved by Meta and working
              </label>
              <span className="text-subtle text-sm">
                Leave this off until approval lands. While it is off, the homepage says
                “tiTi on WhatsApp — coming soon” instead of promising it, the WhatsApp
                buttons and footer icon are hidden, and login codes go by email only —
                so nobody waits for a message that cannot be sent. Turn it on and all of
                that comes back at once, with no deploy.
              </span>
            </div>
          </>}
        </div>
        <div className="modal-footer" style={{ gap: 10, alignItems: "center" }}>
          {saved && <span className="text-subtle text-sm">{saved}</span>}
          <button className="btn btn-primary" disabled={busy || settings === null}
            onClick={saveSettings}>{busy ? "Saving…" : "Save settings"}</button>
        </div>
      </div>

      <div className="card">
        <div className="card-header" style={{ flexWrap: "wrap", gap: 8 }}>
          <span className="card-title">
            Reviews <span className="text-subtle text-sm">({featuredCount} featured on this list)</span>
          </span>
          <div style={{ display: "flex", gap: 6 }}>
            {[["PENDING", "Pending"], ["APPROVED", "Approved"], ["REJECTED", "Rejected"], ["", "All"]]
              .map(([v, l]) => (
                <button key={l} className={`btn btn-xs ${filter === v ? "btn-primary" : "btn-ghost"}`}
                  onClick={() => setFilter(v)}>
                  {l}{counts[v] ? ` (${counts[v]})` : ""}
                </button>
              ))}
          </div>
        </div>
        <div className="card-body" style={{ display: "grid", gap: 12 }}>
          {reviews.length === 0 ? (
            <div className="text-subtle text-sm">Nothing here.</div>
          ) : reviews.map(r => (
            <div key={r.id} style={{
              border: "1px solid var(--border)", borderRadius: 10, padding: 12,
              display: "grid", gap: 8,
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                <div>
                  <strong>{r.business_name}</strong>
                  <div className="text-subtle text-sm">
                    {[r.business_type, r.location].filter(Boolean).join(" · ") || "—"}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <span className={`badge ${r.status === "APPROVED" ? "badge-green"
                    : r.status === "REJECTED" ? "badge-rose" : "badge-amber"}`}>{r.status}</span>
                  {r.is_featured && <span className="badge badge-blue">On homepage</span>}
                </div>
              </div>
              <div style={{ fontStyle: "italic" }}>“{r.quote}”</div>
              <div className="text-subtle text-sm">
                Shown contact: {r.contact_phone || "none"}
                {r.contact_link ? ` · ${r.contact_link}` : ""}
                {" · "}account {r.owner_phone}
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {r.status !== "APPROVED" && (
                  <button className="btn btn-xs btn-primary"
                    onClick={() => patch(r, { status: "APPROVED" })}>Approve</button>
                )}
                {r.status === "APPROVED" && (
                  <button className="btn btn-xs btn-ghost"
                    onClick={() => patch(r, { is_featured: !r.is_featured })}>
                    {r.is_featured ? "Take off homepage" : "Show on homepage"}
                  </button>
                )}
                {r.status !== "REJECTED" && (
                  <button className="btn btn-xs btn-ghost text-rose"
                    onClick={() => patch(r, { status: "REJECTED" })}>Reject</button>
                )}
                <input style={{ width: 90, padding: "4px 8px", fontSize: 12 }} placeholder="Order"
                  defaultValue={r.sort_order}
                  onBlur={e => {
                    const v = Number(e.target.value) || 0;
                    if (v !== r.sort_order) patch(r, { sort_order: v });
                  }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── In-app campaign cards ───────────────────────────────────────────────────
// The pop-up over the dashboard. Targeting matters more than the artwork: a
// card shown to the wrong person, or too often, costs more than it earns.

const BLANK_CAMPAIGN = {
  key: "", title: "", body: "", image_url: "", theme: "navy",
  cta_label: "", cta_link: "", goal: "", owners_only: true, plans: "",
  min_transactions: 0, min_days_active: 0, starts_at: "", ends_at: "",
  is_active: false, max_shows: 3, snooze_days: 14, priority: 0,
  also_notify: true, also_whatsapp: false,
};

// Ready-made starting points. The review one is the reason this exists: it asks
// people who have actually used the app, and stops the moment they write one.
const CAMPAIGN_TEMPLATES = {
  "Ask for a review": {
    key: "review-ask", theme: "navy", goal: "review",
    title: "Your shop, on our homepage",
    body: "Tell other business owners what CreditVoice does for you. If we feature it, your business name, town and phone number go on our homepage — a free advert.",
    cta_label: "Write my review", cta_link: "/profile",
    owners_only: true, min_transactions: 30, min_days_active: 14,
    max_shows: 3, snooze_days: 14, priority: 10,
  },
  "Upgrade nudge": {
    key: "upgrade-nudge", theme: "amber", goal: "upgrade",
    title: "You have outgrown the free plan",
    body: "Unlimited records, stock alerts and reports. Pay yearly and get two months free.",
    cta_label: "See the plans", cta_link: "/upgrade",
    owners_only: true, plans: "BASIC", min_transactions: 50, min_days_active: 21,
    max_shows: 4, snooze_days: 21, priority: 5,
  },
  "Plain announcement": {
    key: "", theme: "green", goal: "",
    title: "", body: "", cta_label: "Open", cta_link: "/",
    owners_only: true, min_transactions: 0, min_days_active: 1,
    max_shows: 2, snooze_days: 30, priority: 0,
  },
};

function CampaignsTab() {
  const [rows, setRows] = useState([]);
  const [form, setForm] = useState(BLANK_CAMPAIGN);
  const [editingId, setEditingId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  function load() {
    apiFetch("admin/campaigns").then(d => setRows(d.campaigns || []))
      .catch(e => setErr(e.message));
  }
  useEffect(load, []);

  async function save() {
    setBusy(true); setErr("");
    try {
      const body = {
        ...form,
        min_transactions: Number(form.min_transactions) || 0,
        min_days_active: Number(form.min_days_active) || 0,
        max_shows: Number(form.max_shows) || 0,
        snooze_days: Number(form.snooze_days) || 0,
        priority: Number(form.priority) || 0,
      };
      if (editingId) await apiPut(`admin/campaigns/${editingId}`, body);
      else await apiPost("admin/campaigns", body);
      setForm(BLANK_CAMPAIGN); setEditingId(null); load();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function remove(row) {
    if (!window.confirm(`Delete "${row.title}"? Its results are deleted too.`)) return;
    try { await apiDelete(`admin/campaigns/${row.id}`); load(); }
    catch (e) { setErr(e.message); }
  }

  async function toggle(row) {
    try { await apiPut(`admin/campaigns/${row.id}`, { ...row, is_active: !row.is_active }); load(); }
    catch (e) { setErr(e.message); }
  }

  function edit(row) {
    setEditingId(row.id);
    setForm({ ...BLANK_CAMPAIGN, ...row, image_url: row.image_url || "",
              cta_label: row.cta_label || "", cta_link: row.cta_link || "",
              goal: row.goal || "", plans: row.plans || "" });
  }

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {err && <div style={{ color: "var(--rose)" }}>{err}</div>}
      <div className="card card-body text-subtle text-sm">
        These cards appear over the dashboard. Only one is ever shown at a time, it can always
        be closed, and a card with a goal stops by itself once the person does what it asked.
      </div>

      <div className="card">
        <div className="card-header" style={{ flexWrap: "wrap", gap: 8 }}>
          <span className="card-title">{editingId ? "Edit card" : "New card"}</span>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {!editingId && Object.keys(CAMPAIGN_TEMPLATES).map(name => (
              <button key={name} className="btn btn-ghost btn-xs"
                onClick={() => setForm({ ...BLANK_CAMPAIGN, ...CAMPAIGN_TEMPLATES[name] })}>
                {name}
              </button>
            ))}
            {editingId && (
              <button className="btn btn-ghost btn-sm"
                onClick={() => { setEditingId(null); setForm(BLANK_CAMPAIGN); }}>Cancel</button>
            )}
          </div>
        </div>
        <div className="card-body" style={{ display: "grid", gap: 10 }}>
          <div className="form-group" style={{ margin: 0 }}>
            <label className="form-label">Title *</label>
            <input value={form.title} onChange={e => set("title", e.target.value)}
              placeholder="Your shop, on our homepage" />
          </div>
          <div className="form-group" style={{ margin: 0 }}>
            <label className="form-label">Text *</label>
            <textarea rows={3} value={form.body} onChange={e => set("body", e.target.value)} />
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <div className="form-group" style={{ margin: 0, flex: "1 1 160px" }}>
              <label className="form-label">Button text</label>
              <input value={form.cta_label} onChange={e => set("cta_label", e.target.value)}
                placeholder="Write my review" />
            </div>
            <div className="form-group" style={{ margin: 0, flex: "1 1 160px" }}>
              <label className="form-label">Button goes to</label>
              <input value={form.cta_link} onChange={e => set("cta_link", e.target.value)}
                placeholder="/profile" />
              <span className="form-hint">An in-app path like /profile, or a full https:// link.</span>
            </div>
            <div className="form-group" style={{ margin: 0, flex: "0 1 130px" }}>
              <label className="form-label">Colour</label>
              <select value={form.theme} onChange={e => set("theme", e.target.value)}>
                <option value="navy">Navy</option>
                <option value="amber">Amber</option>
                <option value="green">Green</option>
              </select>
            </div>
          </div>
          <div className="form-group" style={{ margin: 0 }}>
            <label className="form-label">Picture (optional)</label>
            <input value={form.image_url} onChange={e => set("image_url", e.target.value)}
              placeholder="https://… (leave blank for a plain coloured card)" />
          </div>

          <div className="text-subtle text-sm" style={{ fontWeight: 700, marginTop: 4 }}>Who sees it</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <div className="form-group" style={{ margin: 0, flex: "1 1 150px" }}>
              <label className="form-label">Recorded at least</label>
              <input inputMode="numeric" value={form.min_transactions}
                onChange={e => set("min_transactions", e.target.value)} />
              <span className="form-hint">entries. Keeps it away from brand-new accounts.</span>
            </div>
            <div className="form-group" style={{ margin: 0, flex: "1 1 150px" }}>
              <label className="form-label">Signed up at least</label>
              <input inputMode="numeric" value={form.min_days_active}
                onChange={e => set("min_days_active", e.target.value)} />
              <span className="form-hint">days ago.</span>
            </div>
            <div className="form-group" style={{ margin: 0, flex: "1 1 150px" }}>
              <label className="form-label">Plans (blank = all)</label>
              <input value={form.plans} onChange={e => set("plans", e.target.value)}
                placeholder="BASIC,GO" />
            </div>
            <div className="form-group" style={{ margin: 0, flex: "1 1 150px" }}>
              <label className="form-label">Stops when</label>
              <select value={form.goal} onChange={e => set("goal", e.target.value)}>
                <option value="">Never (plain announcement)</option>
                <option value="review">They write a review</option>
                <option value="upgrade">They leave the free plan</option>
              </select>
            </div>
          </div>
          <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
            <input type="checkbox" checked={!!form.owners_only}
              onChange={e => set("owners_only", e.target.checked)} />
            Owners only (never staff)
          </label>

          <div className="text-subtle text-sm" style={{ fontWeight: 700, marginTop: 4 }}>How often, and when</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <div className="form-group" style={{ margin: 0, flex: "1 1 120px" }}>
              <label className="form-label">Show at most</label>
              <input inputMode="numeric" value={form.max_shows}
                onChange={e => set("max_shows", e.target.value)} />
              <span className="form-hint">times per person.</span>
            </div>
            <div className="form-group" style={{ margin: 0, flex: "1 1 120px" }}>
              <label className="form-label">Quiet for</label>
              <input inputMode="numeric" value={form.snooze_days}
                onChange={e => set("snooze_days", e.target.value)} />
              <span className="form-hint">days after they close it.</span>
            </div>
            <div className="form-group" style={{ margin: 0, flex: "1 1 120px" }}>
              <label className="form-label">Priority</label>
              <input inputMode="numeric" value={form.priority}
                onChange={e => set("priority", e.target.value)} />
            </div>
            <div className="form-group" style={{ margin: 0, flex: "1 1 150px" }}>
              <label className="form-label">Start (optional)</label>
              <input type="date" value={(form.starts_at || "").slice(0, 10)}
                onChange={e => set("starts_at", e.target.value)} />
            </div>
            <div className="form-group" style={{ margin: 0, flex: "1 1 150px" }}>
              <label className="form-label">End (optional)</label>
              <input type="date" value={(form.ends_at || "").slice(0, 10)}
                onChange={e => set("ends_at", e.target.value)} />
            </div>
          </div>
          <div className="text-subtle text-sm" style={{ fontWeight: 700, marginTop: 4 }}>Where else it goes</div>
          <label style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13 }}>
            <input type="checkbox" checked={!!form.also_notify}
              onChange={e => set("also_notify", e.target.checked)} />
            <span>
              Also put it in the bell (and send a push). The card only reaches people who open
              the dashboard — this reaches the rest, once each, and stays after they close it.
            </span>
          </label>
          <label style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13 }}>
            <input type="checkbox" checked={!!form.also_whatsapp}
              onChange={e => set("also_whatsapp", e.target.checked)} />
            <span>
              Also send on WhatsApp — skipped automatically until Meta approves the number.
            </span>
          </label>

          <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
            <input type="checkbox" checked={!!form.is_active}
              onChange={e => set("is_active", e.target.checked)} />
            Live — start showing it
          </label>
        </div>
        <div className="modal-footer">
          <button className="btn btn-primary" disabled={busy || !form.title.trim() || !form.body.trim()}
            onClick={save}>{busy ? "Saving…" : editingId ? "Save changes" : "Create card"}</button>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">Cards <span className="text-subtle text-sm">({rows.length})</span></span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>Card</th><th>Who</th><th>Seen</th><th>Clicked</th><th>Closed</th><th>Done</th><th>Status</th><th></th></tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr><td colSpan={8} className="td-muted">No cards yet.</td></tr>
              ) : rows.map(c => (
                <tr key={c.id}>
                  <td>
                    <strong>{c.title}</strong>
                    <div className="td-muted" style={{ fontSize: 11 }}>{c.key}</div>
                  </td>
                  <td className="td-muted" style={{ fontSize: 11 }}>
                    {c.min_transactions > 0 ? `${c.min_transactions}+ entries` : "anyone"}
                    {c.min_days_active > 0 ? `, ${c.min_days_active}d+` : ""}
                    {c.plans ? `, ${c.plans}` : ""}
                  </td>
                  <td>{c.stats?.shows || 0}<div className="td-muted" style={{ fontSize: 11 }}>{c.stats?.people || 0} people</div></td>
                  <td>{c.stats?.clicked || 0}</td>
                  <td>{c.stats?.dismissed || 0}</td>
                  <td>{c.stats?.completed || 0}</td>
                  <td>
                    <span className={`badge ${c.is_active ? "badge-green" : "badge-gray"}`}>
                      {c.is_active ? "Live" : "Off"}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button className="btn btn-ghost btn-xs" onClick={() => toggle(c)}>
                        {c.is_active ? "Pause" : "Start"}
                      </button>
                      <button className="btn btn-ghost btn-xs" onClick={() => edit(c)}>Edit</button>
                      <button className="btn btn-ghost btn-xs text-rose" onClick={() => remove(c)}>
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// Admin tabs that hold a queue, and the pending-counts key for each.
const TAB_PENDING = { Suppliers: "suppliers", Opportunities: "opportunities", Site: "reviews" };

// Something waiting for an admin was decided: the menu badge and the tab
// counts listen for this and ask again.
function announcePendingChanged() {
  window.dispatchEvent(new Event("cv-admin-pending"));
}

const TABS = ["Overview", "Users", "Payments", "Suppliers", "Opportunities", "Finance", "Token Codes", "Public Pages", "Site", "Campaigns", "Referrals", "Notify", "Failed Messages"];

export default function Admin() {
  const [stats, setStats] = useState(null);
  const [statsLoading, setStatsLoading] = useState(true);
  // The tab lives in the URL, so an alert can open the queue it is about
  // (/admin?tab=Suppliers).
  const [params, setParams] = useSearchParams();
  const tab = TABS.includes(params.get("tab")) ? params.get("tab") : "Overview";
  const setTab = t => setParams(t === "Overview" ? {} : { tab: t }, { replace: true });
  const [pending, setPending] = useState({});

  useEffect(() => {
    const load = () => apiFetch("admin/pending-counts").then(setPending).catch(() => {});
    load();
    window.addEventListener("cv-admin-pending", load);
    return () => window.removeEventListener("cv-admin-pending", load);
  }, [tab]);

  function loadStats() {
    setStatsLoading(true);
    apiFetch("admin/stats")
      .then(d => setStats(d))
      .catch(() => setStats(null))
      .finally(() => setStatsLoading(false));
  }

  useEffect(() => { loadStats(); }, []);

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto" }}>

      {/* Tab nav */}
      <div style={{ display: "flex", gap: 4, marginBottom: 24, borderBottom: "1px solid var(--border)", paddingBottom: 0, overflowX: "auto" }}>
        {TABS.map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              background: "none", border: "none", cursor: "pointer",
              padding: "8px 16px", fontWeight: tab === t ? 700 : 500,
              color: tab === t ? "var(--brand)" : "var(--text-muted)",
              borderBottom: tab === t ? "2px solid var(--brand)" : "2px solid transparent",
              marginBottom: -1, fontSize: 14, whiteSpace: "nowrap",
            }}
          >
            {t}
            {pending[TAB_PENDING[t]] > 0 && (
              <span className="nav-badge nav-badge-alert" style={{ marginLeft: 6 }}
                title={`${pending[TAB_PENDING[t]]} waiting for you`}>
                {pending[TAB_PENDING[t]]}
              </span>
            )}
          </button>
        ))}
        <button
          onClick={loadStats}
          title="Refresh stats"
          style={{
            marginLeft: "auto", background: "none", border: "none",
            cursor: "pointer", color: "var(--text-muted)", padding: "8px 12px",
          }}
        >
          <RefreshCw size={15} />
        </button>
      </div>

      {/* Overview tab */}
      {tab === "Overview" && (
        statsLoading ? (
          <p style={{ color: "var(--text-muted)" }}>Loading stats…</p>
        ) : !stats ? (
          <p style={{ color: "var(--rose)" }}>Failed to load stats. Make sure you are an admin.</p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>

            {/* Users section */}
            <section>
              <h2 style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>Businesses / Signups</h2>
              <div className="metrics-grid">
                <StatCard label="Total Businesses" value={stats.users.total} color="var(--brand)" />
                <StatCard label="New Today" value={stats.users.new_today} color="#0ea5e9" />
                <StatCard label="New This Week" value={stats.users.new_this_week} color="#3b82f6" />
                <StatCard label="New This Month" value={stats.users.new_this_month} color="#f59e0b" />
              </div>
              <div style={{ marginTop: 16, padding: "14px 16px", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted)", marginBottom: 8 }}>SIGNUPS — LAST 14 DAYS</div>
                <BarChart data={stats.users.signup_trend} valueKey="signups" color="var(--brand)" />
              </div>
            </section>

            {/* Transactions section */}
            <section>
              <h2 style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>Transactions Recorded</h2>
              <div className="metrics-grid">
                <StatCard label="Total Transactions" value={stats.transactions.total} color="#16a34a" />
                <StatCard label="Today" value={stats.transactions.today} color="#0ea5e9" />
                <StatCard label="This Week" value={stats.transactions.this_week} color="#3b82f6" />
              </div>
              <div style={{ marginTop: 16, padding: "14px 16px", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted)", marginBottom: 8 }}>TRANSACTIONS — LAST 14 DAYS</div>
                <BarChart data={stats.transactions.tx_trend} valueKey="transactions" color="#16a34a" />
              </div>
            </section>

            {/* Failed parses section */}
            <section>
              <h2 style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>Failed Messages</h2>
              <div className="metrics-grid">
                <StatCard label="Total Failed" value={stats.failed_parses.total} color="#dc2626" />
                <StatCard label="Today" value={stats.failed_parses.today} color="#f59e0b" />
                <StatCard
                  label="LLM Resolved"
                  value={stats.failed_parses.llm_resolved}
                  sub={stats.failed_parses.total > 0
                    ? `${Math.round((stats.failed_parses.llm_resolved / stats.failed_parses.total) * 100)}% recovery rate`
                    : null}
                  color="#16a34a"
                />
              </div>
            </section>

            {/* Business type breakdown */}
            {stats.business_breakdown?.length > 0 && (
              <section>
                <h2 style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>Business Types</h2>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {stats.business_breakdown.map((b, i) => {
                    const max = stats.business_breakdown[0].count;
                    return (
                      <div key={i} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div style={{ width: 140, fontSize: 12, color: "var(--ink)" }}>{b.label}</div>
                        <div style={{ flex: 1, background: "var(--border)", borderRadius: 4, height: 8, overflow: "hidden" }}>
                          <div style={{
                            width: `${(b.count / max) * 100}%`,
                            height: "100%", background: "var(--brand)", borderRadius: 4,
                          }} />
                        </div>
                        <div style={{ width: 32, fontSize: 12, fontWeight: 600, textAlign: "right" }}>{b.count}</div>
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

          </div>
        )
      )}

      {tab === "Users"          && <UsersTab />}
      {tab === "Payments"       && <PaymentsTab />}
      {tab === "Suppliers"      && <SuppliersTab />}
      {tab === "Opportunities"  && <OpportunitiesTab />}
      {tab === "Finance"        && <FinanceTab />}
      {tab === "Public Pages"   && <PublicPagesTab />}
      {tab === "Site"           && <SiteTab />}
      {tab === "Campaigns"      && <CampaignsTab />}
      {tab === "Token Codes"    && <TokenCodesTab />}
      {tab === "Referrals"        && <ReferralSettingsTab />}
      {tab === "Notify"         && <NotifyTab />}
      {tab === "Failed Messages"&& <FailedParsesTab />}
    </div>
  );
}
