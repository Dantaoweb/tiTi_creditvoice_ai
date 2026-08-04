import { useEffect, useState } from "react";
import { apiFetch, apiPost, apiDelete } from "../lib/api";
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

  const PLAN_COLOR = { BASIC: "#6b7280", GO: "#863bff", PRO: "#d97706", PREMIUM: "#0f766e", ENTERPRISE: "#7c3aed" };
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

// ── referral settings tab ────────────────────────────────────────────────────

function ReferralSettingsTab() {
  const [amount, setAmount] = useState("");
  const [current, setCurrent] = useState(null);
  const [busy, setBusy]     = useState(false);
  const [msg, setMsg]       = useState("");
  const [err, setErr]       = useState("");
  const [refData, setRefData] = useState(null);   // { referrers, total_bonus, total_referrals }
  const [refLoading, setRefLoading] = useState(true);

  useEffect(() => {
    apiFetch("admin/referral-settings")
      .then(d => { setCurrent(d.cashback_amount); setAmount(String(d.cashback_amount)); })
      .catch(() => {});
    apiFetch("admin/referrals")
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
      await apiPost("admin/referral-settings", { cashback_amount: n });
      setCurrent(n);
      setMsg(`Cashback set to ${nairaFull(n)} per successful referral.`);
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
          <div className="td-muted" style={{ padding: 12 }}>No referrals yet.</div>
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
                  <tr key={r.referral_code} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: "8px 10px" }}>
                      <div style={{ fontWeight: 600 }}>{r.referrer_name || "—"}</div>
                      <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{r.referrer_phone || ""}</div>
                    </td>
                    <td style={{ padding: "8px 10px", fontFamily: "monospace" }}>{r.referral_code}</td>
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
            { label: "Approved suppliers",     value: stats.approved_suppliers, color: "#7c3aed" },
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
            <strong style={{ fontSize: 15 }}>{a.business_name}</strong>
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

  const empty = { title: "", partner_name: "", category: "general", description: "", link_url: "", is_active: true, application_fields: [] };
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
          <FieldEditor
            fields={form.application_fields || []}
            onChange={fields => setForm(f => ({ ...f, application_fields: fields }))}
          />
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

const TABS = ["Overview", "Users", "Suppliers", "Opportunities", "Token Codes", "Referrals", "Notify", "Failed Messages"];

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

      {tab === "Users"          && <UsersTab />}
      {tab === "Suppliers"      && <SuppliersTab />}
      {tab === "Opportunities"  && <OpportunitiesTab />}
      {tab === "Token Codes"    && <TokenCodesTab />}
      {tab === "Referrals"      && <ReferralSettingsTab />}
      {tab === "Notify"         && <NotifyTab />}
      {tab === "Failed Messages"&& <FailedParsesTab />}
    </div>
  );
}
