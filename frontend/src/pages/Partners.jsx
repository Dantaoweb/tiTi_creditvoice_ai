import { useEffect, useState } from "react";
import { UserPlus, Trash2, Eye, TrendingUp, Users, Briefcase, Lock } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { apiFetch, apiPost } from "../lib/api";
import { usePlan } from "../lib/usePlan";
import { nairaFull } from "../lib/format";
import EmptyState from "../components/EmptyState";
import Skeleton from "../components/Skeleton";

const ROLE_LABELS = {
  co_founder: "Co-Founder",
  partner: "Business Partner",
  investor: "Investor",
  silent: "Silent Partner",
};

const ROLE_COLORS = {
  co_founder: "badge-blue",
  partner: "badge-amber",
  investor: "badge-green",
  silent: "badge-gray",
};

function InviteForm({ onDone, onCancel }) {
  const [form, setForm] = useState({
    partner_phone: "",
    role: "partner",
    equity_percent: "",
    investment_amount: "",
    notes: "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  function set(k, v) { setForm(f => ({ ...f, [k]: v })); }

  async function submit(e) {
    e.preventDefault();
    setErr("");
    if (!form.partner_phone.trim()) { setErr("Phone number is required."); return; }
    setBusy(true);
    try {
      await apiPost("partners/invite", {
        partner_phone: form.partner_phone.trim(),
        role: form.role,
        equity_percent: form.equity_percent ? parseFloat(form.equity_percent) : null,
        investment_amount: form.investment_amount ? parseInt(form.investment_amount) : null,
        notes: form.notes.trim() || null,
      });
      onDone();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="card">
      <div className="card-title" style={{ marginBottom: 4 }}>Invite a Partner or Investor</div>
      <form onSubmit={submit} style={{ display: "grid", gap: 14, marginTop: 12 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div className="form-group">
            <label className="form-label">Phone Number *</label>
            <input type="tel" value={form.partner_phone}
              onChange={e => set("partner_phone", e.target.value)}
              placeholder="e.g. 2348012345678" disabled={busy} />
            <span className="form-hint">Include country code, no +</span>
          </div>
          <div className="form-group">
            <label className="form-label">Role *</label>
            <select value={form.role} onChange={e => set("role", e.target.value)} disabled={busy}>
              <option value="co_founder">Co-Founder</option>
              <option value="partner">Business Partner</option>
              <option value="investor">Investor</option>
              <option value="silent">Silent Partner</option>
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">Equity % (optional)</label>
            <input type="number" min="0" max="100" step="0.1"
              value={form.equity_percent} onChange={e => set("equity_percent", e.target.value)}
              placeholder="e.g. 25" disabled={busy} />
          </div>
          <div className="form-group">
            <label className="form-label">Investment Amount (optional)</label>
            <input type="number" min="0"
              value={form.investment_amount} onChange={e => set("investment_amount", e.target.value)}
              placeholder="e.g. 500000" disabled={busy} />
          </div>
        </div>
        <div className="form-group">
          <label className="form-label">Notes (optional)</label>
          <textarea value={form.notes} onChange={e => set("notes", e.target.value)}
            placeholder="e.g. Responsible for daily operations, joined Jan 2025"
            rows={2} disabled={busy} style={{ resize: "vertical" }} />
        </div>
        {err && <div className="login-error">{err}</div>}
        <div style={{ display: "flex", gap: 10 }}>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Sending…" : "Send Invitation"}
          </button>
          <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={busy}>Cancel</button>
        </div>
      </form>
    </div>
  );
}

export default function Partners() {
  const { user } = useAuth();
  const { allows } = usePlan();
  const isOwner = user?.role === "user" && !user?.parent_id;
  const canUsePartners = allows("PARTNERS");

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showInvite, setShowInvite] = useState(false);
  const [removing, setRemoving] = useState(null);
  const [tab, setTab] = useState("my_partners");

  function load() {
    setLoading(true);
    apiFetch("partners").then(setData).catch(() => {}).finally(() => setLoading(false));
  }
  useEffect(load, []);

  async function remove(id) {
    setRemoving(id);
    try {
      await fetch(`/app/api/partners/${id}`, { method: "DELETE", credentials: "include" });
      load();
    } catch (_) {}
    finally { setRemoving(null); }
  }

  const myPartners = data?.partners || [];
  const myRoles = data?.as_partner || [];
  const pending = myPartners.filter(p => p.status === "pending");
  const active = myPartners.filter(p => p.status === "active");

  function statusBadge(status) {
    if (status === "active") return <span className="badge badge-green">Active</span>;
    if (status === "pending") return <span className="badge badge-amber">Pending</span>;
    return <span className="badge badge-gray">{status}</span>;
  }

  if (!canUsePartners) {
    return (
      <div className="card" style={{ textAlign: "center", padding: "48px 24px" }}>
        <Lock size={36} color="#a78bfa" style={{ margin: "0 auto 16px" }} />
        <div style={{ fontSize: 18, fontWeight: 700, color: "#fff", marginBottom: 8 }}>
          Partners & Investors requires Pro
        </div>
        <div style={{ color: "rgba(255,255,255,0.55)", fontSize: 14, maxWidth: 420, margin: "0 auto 20px" }}>
          Track equity, investment amounts, and partner roles for co-founders, investors, and silent partners.
          Available on the Pro plan.
        </div>
        <button className="btn btn-primary" onClick={() => window.location.href = "/app/upgrade"}>
          Upgrade to Pro
        </button>
      </div>
    );
  }

  return (
    <>
      {/* Tab switcher */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {isOwner && (
          <button className={`btn ${tab === "my_partners" ? "btn-primary" : "btn-secondary"}`}
            style={{ fontSize: 13 }} onClick={() => setTab("my_partners")}>
            <Users size={13} /> My Partners
          </button>
        )}
        {myRoles.length > 0 && (
          <button className={`btn ${tab === "my_roles" ? "btn-primary" : "btn-secondary"}`}
            style={{ fontSize: 13 }} onClick={() => setTab("my_roles")}>
            <Briefcase size={13} /> Businesses I'm In
          </button>
        )}
      </div>

      {/* ── My Partners tab ── */}
      {tab === "my_partners" && isOwner && (
        <>
          {/* Summary cards */}
          {!loading && myPartners.length > 0 && (
            <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(3, minmax(140px, 1fr))", marginBottom: 16 }}>
              <div className="card" style={{ gap: 4, padding: "14px 16px" }}>
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Total Partners</div>
                <div style={{ fontSize: 22, fontWeight: 700 }}>{active.length}</div>
              </div>
              <div className="card" style={{ gap: 4, padding: "14px 16px" }}>
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Pending Invites</div>
                <div style={{ fontSize: 22, fontWeight: 700, color: "var(--amber)" }}>{pending.length}</div>
              </div>
              <div className="card" style={{ gap: 4, padding: "14px 16px" }}>
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Total Investment</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: "var(--brand)" }}>
                  {nairaFull(myPartners.reduce((s, p) => s + (p.investment_amount || 0), 0))}
                </div>
              </div>
            </div>
          )}

          {/* Invite form or button */}
          {!showInvite ? (
            <div className="card" style={{ marginBottom: 0 }}>
              <button className="btn btn-primary" onClick={() => setShowInvite(true)}>
                <UserPlus size={15} /> Invite Partner / Investor
              </button>
            </div>
          ) : (
            <InviteForm onDone={() => { setShowInvite(false); load(); }} onCancel={() => setShowInvite(false)} />
          )}

          {/* Partner list */}
          {loading ? (
            <div className="card"><Skeleton rows={4} /></div>
          ) : myPartners.length === 0 ? (
            <div className="card">
              <EmptyState text="No partners yet. Invite a co-founder, business partner, or investor to give them visibility into your business." />
            </div>
          ) : (
            <div style={{ display: "grid", gap: 12 }}>
              {myPartners.map(p => (
                <div key={p.id} className="card">
                  <div className="card-header">
                    <div>
                      <div className="card-title">{p.partner_name || p.partner_phone}</div>
                      <div className="card-subtitle">{p.partner_phone}</div>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span className={`badge ${ROLE_COLORS[p.role] || "badge-gray"}`}>
                        {ROLE_LABELS[p.role] || p.role}
                      </span>
                      {statusBadge(p.status)}
                    </div>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 8, marginTop: 12 }}>
                    {p.equity_percent != null && (
                      <div className="parsed-cell">
                        <span>Equity</span>
                        <strong>{p.equity_percent}%</strong>
                      </div>
                    )}
                    {p.investment_amount != null && (
                      <div className="parsed-cell">
                        <span>Investment</span>
                        <strong>{nairaFull(p.investment_amount)}</strong>
                      </div>
                    )}
                    <div className="parsed-cell">
                      <span>Access</span>
                      <strong style={{ fontSize: 12 }}>{p.access_level?.replace("_", " ")}</strong>
                    </div>
                    <div className="parsed-cell">
                      <span>Invited</span>
                      <strong style={{ fontSize: 12 }}>{p.invited_at ? new Date(p.invited_at).toLocaleDateString() : "—"}</strong>
                    </div>
                  </div>

                  {p.notes && (
                    <div style={{ marginTop: 10, fontSize: 13, color: "var(--text-muted)", borderTop: "1px solid var(--border)", paddingTop: 8 }}>
                      {p.notes}
                    </div>
                  )}

                  <div style={{ marginTop: 10 }}>
                    <button className="btn btn-secondary"
                      style={{ fontSize: 12, color: "var(--rose)" }}
                      disabled={removing === p.id}
                      onClick={() => {
                        if (window.confirm(`Remove ${p.partner_name || p.partner_phone} from your business?`)) remove(p.id);
                      }}>
                      <Trash2 size={12} /> {removing === p.id ? "Removing…" : "Remove"}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* ── Businesses I'm In tab ── */}
      {tab === "my_roles" && (
        <>
          {myRoles.length === 0 ? (
            <div className="card"><EmptyState text="You haven't been added as a partner in any other business yet." /></div>
          ) : (
            <div style={{ display: "grid", gap: 12 }}>
              {myRoles.map(p => (
                <div key={p.id} className="card">
                  <div className="card-header">
                    <div>
                      <div className="card-title">{p.business_name}</div>
                      <div className="card-subtitle">Owner: {p.owner_name} · {p.owner_phone}</div>
                    </div>
                    <span className={`badge ${ROLE_COLORS[p.role] || "badge-gray"}`}>
                      {ROLE_LABELS[p.role] || p.role}
                    </span>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 8, marginTop: 12 }}>
                    {p.equity_percent != null && (
                      <div className="parsed-cell"><span>Equity</span><strong>{p.equity_percent}%</strong></div>
                    )}
                    {p.investment_amount != null && (
                      <div className="parsed-cell"><span>Investment</span><strong>{nairaFull(p.investment_amount)}</strong></div>
                    )}
                    <div className="parsed-cell">
                      <span>Access level</span>
                      <strong style={{ fontSize: 12 }}>{p.access_level?.replace("_", " ")}</strong>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </>
  );
}
