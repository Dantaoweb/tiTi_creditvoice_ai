import { useEffect, useState } from "react";
import { UserPlus, Copy, Check, Clock, CheckCircle } from "lucide-react";
import { useApp } from "../context/AppContext";
import { useAuth } from "../context/AuthContext";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull } from "../lib/format";
import MetricCard from "../components/MetricCard";
import EmptyState from "../components/EmptyState";
import Skeleton from "../components/Skeleton";

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  function copy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }
  return (
    <button onClick={copy} className="btn btn-secondary" style={{ padding: "4px 10px", fontSize: 12 }}>
      {copied ? <><Check size={12} /> Copied</> : <><Copy size={12} /> Copy code</>}
    </button>
  );
}

export default function Staff() {
  const { ownerPhone, period } = useApp();
  const { user } = useAuth();
  const isOwner = user?.role === "user" && !user?.parent_id;

  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [members, setMembers] = useState([]);

  // Invite form
  const [showInvite, setShowInvite] = useState(false);
  const [invName, setInvName]   = useState("");
  const [invPhone, setInvPhone] = useState("");
  const [invEmail, setInvEmail] = useState("");
  const [invBusy, setInvBusy]   = useState(false);
  const [invErr, setInvErr]     = useState("");
  const [invResult, setInvResult] = useState(null); // { invite_code, emailed, email_hint }

  useEffect(() => {
    setLoading(true);
    apiFetch("staff", { owner_phone: ownerPhone, period })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [ownerPhone, period]);

  useEffect(() => {
    if (!isOwner) return;
    apiFetch("staff/members")
      .then(d => setMembers(d.members || []))
      .catch(() => {});
  }, [isOwner, invResult]);

  const staff = data?.staff || [];
  const totalSales    = staff.reduce((s, m) => s + m.sales,    0);
  const totalPayments = staff.reduce((s, m) => s + m.payments, 0);
  const totalTx       = staff.reduce((s, m) => s + m.transactions, 0);

  const pending = members.filter(m => m.pending);
  const active  = members.filter(m => !m.pending);

  async function handleInvite(e) {
    e.preventDefault();
    setInvErr("");
    if (!invName.trim())  { setInvErr("Enter the staff member's name."); return; }
    if (!invPhone.trim()) { setInvErr("Enter their phone number."); return; }
    setInvBusy(true);
    try {
      const res = await apiPost("staff/invite", {
        name: invName.trim(),
        phone: invPhone.trim(),
        email: invEmail.trim() || null,
      });
      setInvResult(res);
      setInvName(""); setInvPhone(""); setInvEmail("");
      setShowInvite(false);
    } catch (e) { setInvErr(e.message); }
    finally { setInvBusy(false); }
  }

  return (
    <>
      {error && <div style={{ color: "var(--rose)" }}>{error}</div>}

      <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(3, minmax(160px, 1fr))" }}>
        <MetricCard loading={loading} label="Total staff sales"    value={nairaFull(totalSales)}    color="green" />
        <MetricCard loading={loading} label="Total payments taken" value={nairaFull(totalPayments)} color="blue"  />
        <MetricCard loading={loading} label="Total transactions"   value={totalTx.toLocaleString()} color="amber" />
      </div>

      {/* ── Invite result ── */}
      {invResult && (
        <div className="card" style={{ borderLeft: "3px solid var(--brand)" }}>
          <div className="card-header">
            <div>
              <div className="card-title">Invitation sent</div>
              <div className="card-subtitle">
                {invResult.emailed
                  ? `Notification emailed to ${invResult.email_hint}.`
                  : "Share the accept code below with your staff member directly."}
              </div>
            </div>
            <button className="btn btn-secondary" style={{ fontSize: 12 }} onClick={() => setInvResult(null)}>Dismiss</button>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "12px 0 4px" }}>
            <div style={{ letterSpacing: 6, fontSize: 28, fontWeight: 800, fontFamily: "monospace" }}>
              {invResult.invite_code}
            </div>
            <CopyButton text={invResult.invite_code} />
          </div>
          <p className="login-hint-muted" style={{ margin: "8px 0 0" }}>
            Staff member goes to <strong>CreditVoice → Accept staff invitation</strong> on the login page and enters this code. Expires in 24 hours.
          </p>
        </div>
      )}

      {/* ── Invite form ── */}
      {isOwner && (
        <div className="card">
          {!showInvite ? (
            <button className="btn btn-primary" onClick={() => { setShowInvite(true); setInvErr(""); setInvResult(null); }}>
              <UserPlus size={15} /> Invite Staff Member
            </button>
          ) : (
            <form onSubmit={handleInvite} style={{ display: "grid", gap: 14 }}>
              <div className="card-title" style={{ marginBottom: 4 }}>Invite a staff member</div>

              <div className="form-group">
                <label className="form-label">Full Name *</label>
                <input value={invName} onChange={e => setInvName(e.target.value)} placeholder="e.g. Chidi Okafor" autoFocus disabled={invBusy} />
              </div>

              <div className="form-group">
                <label className="form-label">Phone Number *</label>
                <input type="tel" value={invPhone} onChange={e => setInvPhone(e.target.value)} placeholder="e.g. 2348012345678" disabled={invBusy} />
                <span className="form-hint">Include country code, no +</span>
              </div>

              <div className="form-group">
                <label className="form-label">Email Address (optional)</label>
                <input type="email" value={invEmail} onChange={e => setInvEmail(e.target.value)} placeholder="chidi@email.com" disabled={invBusy} />
                <span className="form-hint">If provided, staff will receive an email notification</span>
              </div>

              {invErr && <div className="login-error">{invErr}</div>}

              <div style={{ display: "flex", gap: 10 }}>
                <button type="submit" className="btn btn-primary" disabled={invBusy}>
                  {invBusy ? "Sending…" : "Send Invitation"}
                </button>
                <button type="button" className="btn btn-secondary" onClick={() => { setShowInvite(false); setInvErr(""); }} disabled={invBusy}>
                  Cancel
                </button>
              </div>
            </form>
          )}
        </div>
      )}

      {/* ── Pending invitations ── */}
      {pending.length > 0 && (
        <div className="card">
          <div className="card-title" style={{ marginBottom: 12 }}>Pending Invitations</div>
          <div style={{ display: "grid", gap: 10 }}>
            {pending.map(m => (
              <div key={m.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 0", borderBottom: "1px solid var(--border)" }}>
                <Clock size={16} style={{ color: "var(--amber)", flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{m.name}</div>
                  <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{m.phone}{m.email ? ` · ${m.email}` : ""}</div>
                </div>
                <span className="badge badge-amber">Pending</span>
              </div>
            ))}
          </div>
          <p className="login-hint-muted" style={{ marginTop: 10 }}>
            Share the accept code with your staff. They can accept at <strong>CreditVoice → Accept staff invitation</strong>.
          </p>
        </div>
      )}

      {/* ── Active staff ── */}
      {loading ? (
        <div className="card"><Skeleton rows={4} /></div>
      ) : staff.length === 0 ? (
        <div className="card"><EmptyState text="No active staff yet. Use the invite form above to add your first staff member." /></div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 16 }}>
          {staff.map((member) => (
            <div key={member.id} className="card">
              <div className="card-header">
                <div>
                  <div className="card-title">{(member.name || "Staff").replace(/\b\w/g, c => c.toUpperCase())}</div>
                  <div className="card-subtitle">{member.phone}</div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <CheckCircle size={14} style={{ color: "var(--brand)" }} />
                  <span className="badge badge-blue">{member.role}</span>
                </div>
              </div>
              <div className="card-body" style={{ display: "grid", gap: 14 }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                  <div className="parsed-cell">
                    <span>Sales</span>
                    <strong>{nairaFull(member.sales)}</strong>
                  </div>
                  <div className="parsed-cell">
                    <span>Payments</span>
                    <strong>{nairaFull(member.payments)}</strong>
                  </div>
                  <div className="parsed-cell">
                    <span>Transactions</span>
                    <strong>{member.transactions.toLocaleString()}</strong>
                  </div>
                  <div className="parsed-cell">
                    <span>Customers served</span>
                    <strong>{member.customers_served.toLocaleString()}</strong>
                  </div>
                </div>

                {member.top_products?.length > 0 && (
                  <div>
                    <div className="form-label" style={{ marginBottom: 8 }}>Top products</div>
                    <div style={{ display: "grid", gap: 6 }}>
                      {member.top_products.map((p, i) => (
                        <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                          <span>{(p.product || "—").replace(/\b\w/g, c => c.toUpperCase())}</span>
                          <span className="text-muted">{p.qty} unit(s) · {nairaFull(p.total)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
