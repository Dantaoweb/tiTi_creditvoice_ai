import { useEffect, useState } from "react";
import { apiFetch, apiPost } from "../lib/api";
import { Download, RefreshCw, Search, Ticket } from "lucide-react";

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
  return (
    <div className="metric-card" style={{ borderTop: `3px solid ${color || "var(--brand)"}` }}>
      <div className="metric-value" style={{ color: color || "var(--brand)" }}>{value ?? "—"}</div>
      <div className="metric-label">{label}</div>
      {sub && <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

// ── failed parses tab ────────────────────────────────────────────────────────

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
  const [loading, setLoading] = useState(true);

  function load(pg = page, search = q) {
    setLoading(true);
    apiFetch(`admin/users?page=${pg}&per_page=50&q=${encodeURIComponent(search)}`)
      .then(d => setData(d))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  function handleSearch(e) {
    e.preventDefault();
    setPage(1);
    load(1, q);
  }

  const PLAN_COLOR = { BASIC: "#6b7280", PRO: "var(--brand)", ENTERPRISE: "#7c3aed" };
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

      {loading ? (
        <p style={{ color: "var(--text-muted)" }}>Loading…</p>
      ) : !data ? null : (
        <>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 10 }}>
            Showing {data.users.length} of {data.total} businesses
          </p>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "var(--surface-2, #f9fafb)", textAlign: "left" }}>
                  {["Name", "Phone", "Business Type", "Plan", "Status", "Joined"].map(h => (
                    <th key={h} style={{ padding: "8px 10px", borderBottom: "1px solid var(--border)", fontWeight: 600 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.users.map(u => (
                  <tr key={u.id} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: "7px 10px", fontWeight: 500 }}>{u.name || "—"}</td>
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
                    <td style={{ padding: "7px 10px", color: "var(--text-muted)", fontSize: 11, whiteSpace: "nowrap" }}>
                      {u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}
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

// ── referral settings tab ────────────────────────────────────────────────────

function ReferralSettingsTab() {
  const [amount, setAmount] = useState("");
  const [current, setCurrent] = useState(null);
  const [busy, setBusy]     = useState(false);
  const [msg, setMsg]       = useState("");
  const [err, setErr]       = useState("");

  useEffect(() => {
    apiFetch("admin/referral-settings")
      .then(d => { setCurrent(d.cashback_amount); setAmount(String(d.cashback_amount)); })
      .catch(() => {});
  }, []);

  async function save(e) {
    e.preventDefault();
    const n = parseInt(amount);
    if (isNaN(n) || n < 0) { setErr("Enter a valid amount (₦0 or more)."); return; }
    setBusy(true); setErr(""); setMsg("");
    try {
      await apiPost("admin/referral-settings", { cashback_amount: n });
      setCurrent(n);
      setMsg(`Cashback set to ₦${n.toLocaleString()} per successful referral.`);
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="card" style={{ maxWidth: 480 }}>
      <div className="card-header">
        <span className="card-title">Referral Cashback Rate</span>
      </div>
      <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 16, marginTop: 8 }}>
        Amount credited to a GO/PRO referrer's wallet when their invited user upgrades to GO plan.
        {current !== null && <><br /><strong style={{ color: "var(--ink)" }}>Current: ₦{current?.toLocaleString()}</strong></>}
      </p>
      <form onSubmit={save} style={{ display: "flex", gap: 8 }}>
        <div className="form-group" style={{ flex: 1 }}>
          <label className="form-label">Cashback amount (₦)</label>
          <input type="number" min="0" value={amount} onChange={e => setAmount(e.target.value)} placeholder="e.g. 500" disabled={busy} />
        </div>
        <div className="form-group" style={{ display: "flex", alignItems: "flex-end" }}>
          <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
        </div>
      </form>
      {msg && <div style={{ color: "#16a34a", fontSize: 13, marginTop: 8 }}>{msg}</div>}
      {err && <div className="login-error" style={{ marginTop: 8 }}>{err}</div>}
    </div>
  );
}

const TABS = ["Overview", "Users", "Token Codes", "Referrals", "Failed Messages"];

export default function Admin() {
  const [stats, setStats] = useState(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [tab, setTab] = useState("Overview");

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
      <div style={{ display: "flex", gap: 4, marginBottom: 24, borderBottom: "1px solid var(--border)", paddingBottom: 0 }}>
        {TABS.map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              background: "none", border: "none", cursor: "pointer",
              padding: "8px 16px", fontWeight: tab === t ? 700 : 500,
              color: tab === t ? "var(--brand)" : "var(--text-muted)",
              borderBottom: tab === t ? "2px solid var(--brand)" : "2px solid transparent",
              marginBottom: -1, fontSize: 14,
            }}
          >
            {t}
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
                <StatCard label="New This Week" value={stats.users.new_this_week} color="#8b5cf6" />
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
                <StatCard label="This Week" value={stats.transactions.this_week} color="#8b5cf6" />
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

      {tab === "Users" && <UsersTab />}
      {tab === "Token Codes" && <TokenCodesTab />}
      {tab === "Referrals" && <ReferralSettingsTab />}
      {tab === "Failed Messages" && <FailedParsesTab />}
    </div>
  );
}
