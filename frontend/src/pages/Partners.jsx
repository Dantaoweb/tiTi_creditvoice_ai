import { useEffect, useState } from "react";
import { UserPlus, Trash2, Eye, TrendingUp, Users, Briefcase, Lock, Copy, Check, X, Loader2 } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { apiFetch, apiPost } from "../lib/api";
import { usePlan } from "../lib/usePlan";
import { nairaFull, parseAmt } from "../lib/format";
import MoneyInput from "../components/MoneyInput";
import MetricCard from "../components/MetricCard";
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
        investment_amount: form.investment_amount ? parseAmt(form.investment_amount) : null,
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
            <MoneyInput
              value={form.investment_amount} onChange={v => set("investment_amount", v)}
              placeholder="e.g. 500,000" disabled={busy} />
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
  // Any top-level account is a business owner (web owners have role "owner").
  const isOwner = !user?.parent_id && user?.role !== "delegate" && user?.role !== "delegate_pending";
  const canUsePartners = allows("PARTNERS");

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showInvite, setShowInvite] = useState(false);
  const [removing, setRemoving] = useState(null);
  const [tab, setTab] = useState("my_partners");
  const [copiedId, setCopiedId] = useState(null);
  const [overview, setOverview] = useState(null);   // scoped business view (partner)
  const [ovLoading, setOvLoading] = useState(false);

  function inviteLink(p) {
    return `${window.location.origin}/app/partners/join/${p.invite_token}`;
  }
  function copyInviteLink(p) {
    navigator.clipboard.writeText(inviteLink(p)).then(() => {
      setCopiedId(p.id);
      setTimeout(() => setCopiedId(null), 2000);
    });
  }
  function viewBusiness(p) {
    setOvLoading(true); setOverview(null);
    apiFetch(`partners/overview/${p.id}`)
      .then(d => setOverview(d))
      .catch(() => {})
      .finally(() => setOvLoading(false));
  }

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

  async function respondToInvite(id, action) {
    try {
      await fetch(`/app/api/partners/${id}/${action}`, { method: "POST", credentials: "include" });
      load();
    } catch (_) {}
  }

  const myPartners = data?.partners || [];
  const myRoles = data?.as_partner || [];
  const pending = myPartners.filter(p => p.status === "pending");
  const pendingInvites = myRoles.filter(p => p.status === "pending");
  const active = myPartners.filter(p => p.status === "active");

  function statusBadge(status) {
    if (status === "active") return <span className="badge badge-green">Active</span>;
    if (status === "pending") return <span className="badge badge-amber">Pending</span>;
    return <span className="badge badge-gray">{status}</span>;
  }

  if (!canUsePartners) {
    return (
      <div className="card" style={{ textAlign: "center", padding: "48px 24px" }}>
        <Lock size={36} color="#3b82f6" style={{ margin: "0 auto 16px" }} />
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
            {pendingInvites.length > 0 && (
              <span style={{
                background: "var(--amber)", color: "#000", borderRadius: "99px",
                padding: "0 6px", fontSize: 11, fontWeight: 700, marginLeft: 4,
              }}>{pendingInvites.length}</span>
            )}
          </button>
        )}
      </div>

      {/* ── My Partners tab ── */}
      {tab === "my_partners" && isOwner && (
        <>
          {/* Summary cards */}
          {!loading && myPartners.length > 0 && (
            <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(110px, 1fr))", marginBottom: 16 }}>
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

                  {p.status === "pending" && p.invite_token && (
                    <div style={{ marginTop: 12, borderTop: "1px solid var(--border)", paddingTop: 10 }}>
                      <div className="form-label" style={{ marginBottom: 6 }}>Invite link — share it to let them join</div>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                        <input readOnly value={inviteLink(p)} onFocus={e => e.target.select()}
                          style={{ flex: 1, minWidth: 200, fontSize: 12 }} />
                        <button className="btn btn-primary" style={{ fontSize: 12 }} onClick={() => copyInviteLink(p)}>
                          {copiedId === p.id ? <><Check size={13} /> Copied</> : <><Copy size={13} /> Copy link</>}
                        </button>
                      </div>
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
                    <div style={{ display: "flex", gap: 6 }}>
                      <span className={`badge ${ROLE_COLORS[p.role] || "badge-gray"}`}>
                        {ROLE_LABELS[p.role] || p.role}
                      </span>
                      {statusBadge(p.status)}
                    </div>
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
                  {p.status === "pending" ? (
                    <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                      <button className="btn btn-primary" style={{ fontSize: 12 }}
                        onClick={() => respondToInvite(p.id, "accept")}>
                        Accept Invitation
                      </button>
                      <button className="btn btn-secondary" style={{ fontSize: 12, color: "var(--rose)" }}
                        onClick={() => respondToInvite(p.id, "decline")}>
                        Decline
                      </button>
                    </div>
                  ) : (
                    <div style={{ marginTop: 12 }}>
                      <button className="btn btn-secondary" style={{ fontSize: 12 }}
                        onClick={() => viewBusiness(p)}>
                        <Eye size={13} /> View business
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {(overview || ovLoading) && (
        <OverviewModal data={overview} loading={ovLoading} onClose={() => { setOverview(null); setOvLoading(false); }} />
      )}
    </>
  );
}

function OverviewModal({ data, loading, onClose }) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 460 }}>
        <div className="modal-header">
          <span className="card-title">{loading ? "Loading…" : data?.business_name}</span>
          <button className="btn-icon" onClick={onClose}><X size={18} /></button>
        </div>
        {loading || !data ? (
          <div className="card-body" style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <Loader2 size={16} className="spin" /> Loading business overview…
          </div>
        ) : (
          <div className="card-body" style={{ display: "grid", gap: 12 }}>
            <div className="text-subtle text-sm">
              {data.role_label} · {data.access_label}
              <br />Owner: {data.owner_name}
            </div>

            {data.show_sales && (
              <div className="metrics-grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
                <MetricCard label="Sales (30 days)" value={nairaFull(data.sales_30d)} color="green" small />
                <MetricCard label="Payments (30 days)" value={nairaFull(data.payments_30d)} color="blue" small />
              </div>
            )}

            {data.show_investment && (data.investment_amount != null || data.equity_percent != null) && (
              <div className="metrics-grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
                {data.investment_amount != null && (
                  <MetricCard label="Your capital" value={nairaFull(data.investment_amount)} color="brand" small />
                )}
                {data.equity_percent != null && (
                  <MetricCard label="Your equity" value={`${data.equity_percent}%`} color="amber" small />
                )}
              </div>
            )}

            {data.show_customers && (
              <MetricCard label="Customers" value={Number(data.customers || 0).toLocaleString()} color="rose" small />
            )}

            {data.notes?.length > 0 && (
              <div>
                <div className="form-label" style={{ marginBottom: 6 }}>Shared notes</div>
                <div style={{ display: "grid", gap: 6 }}>
                  {data.notes.map((n, i) => (
                    <div key={i} className="parsed-cell" style={{ textAlign: "left" }}>
                      <span style={{ textTransform: "capitalize" }}>{n.category}{n.amount != null ? ` · ${nairaFull(n.amount)}` : ""}</span>
                      <strong style={{ fontWeight: 500, fontSize: 13 }}>{n.title ? `${n.title}: ` : ""}{n.body}</strong>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
