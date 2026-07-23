import { useEffect, useState } from "react";
import { UserPlus, Copy, Check, Clock, CheckCircle, Pencil, Save, X, Trash2, GraduationCap, Users, Lock, TrendingUp, Award } from "lucide-react";
import { useApp } from "../context/AppContext";
import { useAuth } from "../context/AuthContext";
import { apiFetch, apiPost, apiPut, apiDelete } from "../lib/api";
import { nairaFull } from "../lib/format";
import MetricCard from "../components/MetricCard";
import EmptyState from "../components/EmptyState";
import Skeleton from "../components/Skeleton";
import { usePlan } from "../lib/usePlan";
import { LimitBar } from "../components/UpgradeGate";
import { useToast } from "../components/Toast";

function CopyButton({ text, label = "Copy code" }) {
  const [copied, setCopied] = useState(false);
  function copy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }
  return (
    <button onClick={copy} className="btn btn-secondary" style={{ padding: "4px 10px", fontSize: 12 }}>
      {copied ? <><Check size={12} /> Copied</> : <><Copy size={12} /> {label}</>}
    </button>
  );
}

// Renders an invite code with copy + a shareable link + WhatsApp share.
function InviteShare({ code, phone }) {
  const link = `${window.location.origin}/app/login?invite=${encodeURIComponent(code)}`
    + (phone ? `&phone=${encodeURIComponent(phone)}` : "");
  const msg = `You've been invited to join as staff on CreditVoice. Tap to accept (expires in 24h):\n${link}`;
  const waDigits = (phone || "").replace(/\D/g, "");
  const waUrl = waDigits
    ? `https://wa.me/${waDigits}?text=${encodeURIComponent(msg)}`
    : `https://api.whatsapp.com/send?text=${encodeURIComponent(msg)}`;
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "4px 0" }}>
        <div style={{ letterSpacing: 4, fontSize: 22, fontWeight: 800, fontFamily: "monospace" }}>{code}</div>
        <CopyButton text={code} />
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 6 }}>
        <input readOnly value={link} onFocus={e => e.target.select()}
          style={{ flex: 1, minWidth: 200, fontSize: 12, fontFamily: "monospace" }} />
        <CopyButton text={link} label="Copy link" />
        <a className="btn btn-primary" style={{ padding: "4px 10px", fontSize: 12 }}
          href={waUrl} target="_blank" rel="noopener noreferrer">Send on WhatsApp</a>
      </div>
    </div>
  );
}

function ProfileEditRow({ member, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    staff_position: member.staff_position || "",
    staff_level: member.staff_level || "",
    staff_salary: member.staff_salary || "",
    staff_matric: member.staff_matric || "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function save() {
    setBusy(true); setErr("");
    try {
      await apiPut(`staff/${member.id}/profile`, {
        staff_position: form.staff_position || null,
        staff_level: form.staff_level || null,
        staff_salary: form.staff_salary ? parseInt(form.staff_salary) : null,
        staff_matric: form.staff_matric || null,
      });
      setEditing(false);
      onSaved();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="card" style={{ gap: 0 }}>
      <div className="card-header">
        <div>
          <div className="card-title">{(member.name || "Staff").replace(/\b\w/g, c => c.toUpperCase())}</div>
          <div className="card-subtitle">{member.phone}</div>
        </div>
        {!editing ? (
          <button className="btn btn-secondary" style={{ fontSize: 12 }} onClick={() => setEditing(true)}>
            <Pencil size={12} /> Edit profile
          </button>
        ) : (
          <div style={{ display: "flex", gap: 6 }}>
            <button className="btn btn-primary" style={{ fontSize: 12 }} onClick={save} disabled={busy}>
              <Save size={12} /> {busy ? "Saving…" : "Save"}
            </button>
            <button className="btn btn-secondary" style={{ fontSize: 12 }} onClick={() => setEditing(false)} disabled={busy}>
              <X size={12} />
            </button>
          </div>
        )}
      </div>
      {err && <div className="login-error" style={{ margin: "8px 0 0" }}>{err}</div>}
      {!editing ? (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 12 }}>
          {[["Position", member.staff_position], ["Level", member.staff_level],
            ["Salary", member.staff_salary ? nairaFull(member.staff_salary) + "/mo" : null],
            ["Employee ID", member.staff_matric]].map(([label, val]) => (
            <div className="parsed-cell" key={label}>
              <span>{label}</span>
              <strong style={{ color: val ? undefined : "var(--text-muted)", fontWeight: val ? 600 : 400 }}>
                {val || "Not set"}
              </strong>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 12 }}>
          {[["Position", "staff_position", "e.g. Cashier"], ["Level", "staff_level", "e.g. Senior"],
            ["Monthly Salary (₦)", "staff_salary", "e.g. 50000"], ["Employee ID", "staff_matric", "e.g. EMP001"]
          ].map(([label, key, ph]) => (
            <div className="form-group" key={key}>
              <label className="form-label">{label}</label>
              <input value={form[key]} onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                placeholder={ph} disabled={busy} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── School Teacher Roster Tab ─────────────────────────────────────────────────

function TeachersTab({ plan, limit: teacherLimit, withinLimit }) {
  const toast = useToast();
  const [rows, setRows]       = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editRow, setEditRow] = useState(null);
  const [form, setForm]       = useState({ name: "", subject: "", class_name: "", phone: "", employee_id: "" });
  const [busy, setBusy]       = useState(false);
  const [err, setErr]         = useState("");

  function load() {
    setLoading(true);
    apiFetch("school/teachers")
      .then(d => setRows(d.teachers || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  function openAdd() {
    setForm({ name: "", subject: "", class_name: "", phone: "", employee_id: "" });
    setEditRow(null);
    setErr("");
    setShowAdd(true);
  }

  function openEdit(row) {
    setForm({ name: row.name, subject: row.subject || "", class_name: row.class_name || "", phone: row.phone || "", employee_id: row.employee_id || "" });
    setEditRow(row);
    setErr("");
    setShowAdd(true);
  }

  async function save() {
    if (!form.name.trim()) { setErr("Name is required."); return; }
    setBusy(true); setErr("");
    try {
      if (editRow) {
        await apiPut(`school/teachers/${editRow.id}`, form);
      } else {
        await apiPost("school/teachers", form);
      }
      setShowAdd(false);
      load();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function del(id) {
    if (!window.confirm("Remove this teacher?")) return;
    try {
      await apiDelete(`school/teachers/${id}`);
      load();
    } catch (e) { toast(e.message, "error"); }
  }

  const canAdd = withinLimit("school_teachers", rows.length);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {teacherLimit !== null && (
        <LimitBar used={rows.length} limit={teacherLimit} label="teacher records" upgradePlan="Go" />
      )}

      <div className="card">
        <div className="card-header">
          <span className="card-title"><GraduationCap size={16} /> Teacher Roster</span>
          <button
            className="btn btn-primary btn-sm"
            onClick={canAdd ? openAdd : undefined}
            style={canAdd ? {} : { opacity: 0.5, cursor: "not-allowed" }}
            title={canAdd ? undefined : `Basic plan: ${teacherLimit} teachers. Upgrade to Go for unlimited.`}
          >
            + Add Teacher
          </button>
        </div>

        {showAdd && (
          <div style={{ padding: "12px 0", borderTop: "1px solid var(--border)", display: "grid", gap: 12, marginTop: 12 }}>
            <div className="card-title" style={{ marginBottom: 0 }}>{editRow ? "Edit Teacher" : "Add Teacher"}</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              {[
                ["Full Name *", "name", "e.g. Musa Ibrahim"],
                ["Subject", "subject", "e.g. Mathematics"],
                ["Class", "class_name", "e.g. JSS 2B"],
                ["Phone", "phone", "e.g. 08012345678"],
                ["Employee ID", "employee_id", "e.g. TCH001"],
              ].map(([label, key, ph]) => (
                <div className="form-group" key={key}>
                  <label className="form-label">{label}</label>
                  <input value={form[key]} onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                    placeholder={ph} disabled={busy} />
                </div>
              ))}
            </div>
            {err && <div className="login-error">{err}</div>}
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn btn-primary" onClick={save} disabled={busy}>
                {busy ? "Saving…" : "Save"}
              </button>
              <button className="btn btn-secondary" onClick={() => setShowAdd(false)} disabled={busy}>Cancel</button>
            </div>
          </div>
        )}

        {loading ? <Skeleton rows={3} /> : rows.length === 0 ? (
          <EmptyState text="No teachers added yet. Click 'Add Teacher' to build your roster." />
        ) : (
          <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
            {rows.map(r => (
              <div key={r.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 0", borderBottom: "1px solid var(--border)" }}>
                <GraduationCap size={15} style={{ color: "var(--brand)", flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{r.name}</div>
                  <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                    {[r.subject, r.class_name, r.employee_id].filter(Boolean).join(" · ")}
                    {r.phone ? ` · ${r.phone}` : ""}
                  </div>
                </div>
                <button className="btn btn-secondary" style={{ padding: "4px 8px", fontSize: 12 }} onClick={() => openEdit(r)}>
                  <Pencil size={12} />
                </button>
                <button className="btn btn-secondary" style={{ padding: "4px 8px", fontSize: 12, color: "var(--rose)" }} onClick={() => del(r.id)}>
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}


export default function Staff() {
  const { ownerPhone, period } = useApp();
  const { user } = useAuth();
  const { plan, allows, limit: planLimit, withinLimit } = usePlan();
  // A business owner is any top-level account (no parent). Staff/sub-accounts
  // have parent_id set. (Web owners have role "owner", not "user".)
  const isOwner = !user?.parent_id && user?.role !== "delegate" && user?.role !== "delegate_pending";
  const isSchool = user?.menu_group === "school";
  const canUseAppStaff = isSchool ? allows("SCHOOL_APP_STAFF") : allows("STAFF");
  const teacherLimit = planLimit("school_teachers");

  // For schools the default tab is "teachers"; for other biz "performance"
  const [tab, setTab] = useState(isSchool ? "teachers" : "performance");
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [members, setMembers] = useState([]);
  const [profiles, setProfiles] = useState([]);

  // Invite form
  const [showInvite, setShowInvite] = useState(false);
  const [invName, setInvName]   = useState("");
  const [invPhone, setInvPhone] = useState("");
  const [invEmail, setInvEmail] = useState("");
  const [invBusy, setInvBusy]   = useState(false);
  const [invErr, setInvErr]     = useState("");
  const [invResult, setInvResult] = useState(null); // { invite_code, emailed, email_hint }
  const [accessBusy, setAccessBusy] = useState({});
  const [resendResult, setResendResult] = useState({}); // { [id]: { invite_code, phone } }
  const [resendBusy, setResendBusy] = useState({});
  const [branches, setBranches] = useState([]);
  const [branchBusy, setBranchBusy] = useState({});

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
    apiFetch("branches")
      .then(d => setBranches(d.branches || []))
      .catch(() => {});
  }, [isOwner, invResult]);

  async function setBranch(id, branchId) {
    setBranchBusy(p => ({ ...p, [id]: true }));
    try {
      await apiPost(`staff/${id}/branch`, { branch_id: branchId });
      const name = branches.find(b => b.id === branchId)?.name || null;
      setMembers(ms => ms.map(m => (m.id === id ? { ...m, branch_id: branchId, branch_name: name } : m)));
    } catch (e) {
      alert(e.message);
    } finally {
      setBranchBusy(p => ({ ...p, [id]: false }));
    }
  }

  async function resendInvite(m) {
    setResendBusy(p => ({ ...p, [m.id]: true }));
    try {
      const res = await apiPost(`staff/${m.id}/resend-invite`, {});
      setResendResult(p => ({ ...p, [m.id]: res }));
    } catch (e) {
      alert(e.message);
    } finally {
      setResendBusy(p => ({ ...p, [m.id]: false }));
    }
  }

  function loadProfiles() {
    if (!isOwner) return;
    apiFetch("staff/profiles").then(d => setProfiles(d.profiles || [])).catch(() => {});
  }
  useEffect(loadProfiles, [isOwner]);

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
      setInvResult({ ...res, phone: invPhone.trim(), name: invName.trim() });
      setInvName(""); setInvPhone(""); setInvEmail("");
      setShowInvite(false);
    } catch (e) { setInvErr(e.message); }
    finally { setInvBusy(false); }
  }

  async function toggleAccess(id, next) {
    setAccessBusy(p => ({ ...p, [id]: true }));
    try {
      await apiPost(`staff/${id}/access`, { full_access: next });
      setMembers(ms => ms.map(m => (m.id === id ? { ...m, full_access: next } : m)));
    } catch (e) {
      alert(e.message);
    } finally {
      setAccessBusy(p => ({ ...p, [id]: false }));
    }
  }

  return (
    <>
      {error && <div style={{ color: "var(--rose)" }}>{error}</div>}

      {/* Tab switcher */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        {isSchool && (
          <button className={`btn ${tab === "teachers" ? "btn-primary" : "btn-secondary"}`}
            style={{ fontSize: 13 }} onClick={() => setTab("teachers")}>
            <GraduationCap size={13} /> Teachers
          </button>
        )}
        {isSchool ? (
          <button className={`btn ${tab === "performance" ? "btn-primary" : "btn-secondary"}`}
            style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}
            onClick={() => setTab("performance")}>
            <Users size={13} />
            Admin Staff
            {!canUseAppStaff && <Lock size={11} style={{ color: "#a78bfa" }} />}
          </button>
        ) : (
          ["performance", "profiles"].map(t => (
            <button key={t} className={`btn ${tab === t ? "btn-primary" : "btn-secondary"}`}
              style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}
              onClick={() => setTab(t)}>
              {t === "performance" ? "Performance" : "HR Profiles"}
              {t === "performance" && !canUseAppStaff && <Lock size={11} style={{ color: "#a78bfa" }} />}
            </button>
          ))
        )}
      </div>

      {/* School teachers tab */}
      {tab === "teachers" && isSchool && (
        <TeachersTab plan={plan} limit={teacherLimit} withinLimit={withinLimit} />
      )}

      {/* Upgrade wall for non-Pro trying to access app-access staff */}
      {tab === "performance" && !canUseAppStaff && (
        <div className="card" style={{ textAlign: "center", padding: "48px 24px" }}>
          <Lock size={36} color="#a78bfa" style={{ margin: "0 auto 16px" }} />
          <div style={{ fontSize: 18, fontWeight: 700, color: "#fff", marginBottom: 8 }}>
            {isSchool ? "Admin Staff requires Pro" : "Staff requires Pro"}
          </div>
          <div style={{ color: "rgba(255,255,255,0.55)", fontSize: 14, maxWidth: 400, margin: "0 auto 20px" }}>
            {isSchool
              ? "Invite a bursar, accountant, or admin officer to record fees with your oversight. Available on the Pro plan."
              : "Let staff members record sales and payments while you keep full visibility. Available on the Pro plan."}
          </div>
          <button className="btn btn-primary" onClick={() => window.location.href = "/app/upgrade"}>
            Upgrade to Pro
          </button>
        </div>
      )}

      {tab === "profiles" && !canUseAppStaff && (
        <div className="card" style={{ textAlign: "center", padding: "48px 24px" }}>
          <Lock size={36} color="#a78bfa" style={{ margin: "0 auto 16px" }} />
          <div style={{ fontSize: 18, fontWeight: 700, color: "#fff", marginBottom: 8 }}>HR Profiles requires Pro</div>
          <div style={{ color: "rgba(255,255,255,0.55)", fontSize: 14, maxWidth: 400, margin: "0 auto 20px" }}>
            Set staff positions, salaries and employee IDs. Available on the Pro plan.
          </div>
          <button className="btn btn-primary" onClick={() => window.location.href = "/app/upgrade"}>
            Upgrade to Pro
          </button>
        </div>
      )}

      {/* ── Profiles tab ── */}
      {tab === "profiles" && canUseAppStaff && (
        <>
          {profiles.length === 0 ? (
            <div className="card"><EmptyState text="No active staff profiles yet. Invite staff first, then set their position and salary here." /></div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(min(340px, 100%), 1fr))", gap: 16 }}>
              {profiles.map(m => <ProfileEditRow key={m.id} member={m} onSaved={loadProfiles} />)}
            </div>
          )}
        </>
      )}

      {tab === "performance" && canUseAppStaff && <>

      <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))" }}>
        <MetricCard loading={loading} label="Total staff sales"    value={nairaFull(totalSales)}    color="green" />
        <MetricCard loading={loading} label="Total payments taken" value={nairaFull(totalPayments)} color="blue"  />
        <MetricCard loading={loading} label="Total transactions"   value={totalTx.toLocaleString()} color="amber" />
      </div>

      {/* ── Staff Leaderboard ── */}
      {!loading && staff.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title"><TrendingUp size={15} /> Staff Leaderboard</span>
            <span className="text-subtle text-sm">{period || "All time"}</span>
          </div>
          <div className="staff-leaderboard">
            {staff.map((m, i) => {
              const pct = totalSales > 0 ? Math.round((m.sales / totalSales) * 100) : 0;
              const avg = m.transactions > 0 ? Math.round(m.sales / m.transactions) : 0;
              const medal = i === 0 ? "🥇" : i === 1 ? "🥈" : i === 2 ? "🥉" : null;
              return (
                <div key={m.id || m.name} className="staff-lb-row">
                  <div className="staff-lb-rank">
                    {medal ? <span>{medal}</span> : <span className="staff-lb-num">#{i + 1}</span>}
                  </div>
                  <div className="staff-lb-info">
                    <div className="staff-lb-name">
                      {(m.name || "Staff").replace(/\b\w/g, c => c.toUpperCase())}
                      {m.staff_position && (
                        <span className="staff-lb-pos">{m.staff_position}</span>
                      )}
                    </div>
                    <div className="staff-lb-bar-wrap">
                      <div className="staff-lb-bar">
                        <div
                          className="staff-lb-bar-fill"
                          style={{ width: `${pct}%`, background: i === 0 ? "#16a34a" : i === 1 ? "#2563eb" : "var(--brand)" }}
                        />
                      </div>
                      <span className="staff-lb-pct">{pct}%</span>
                    </div>
                  </div>
                  <div className="staff-lb-stats">
                    <div className="staff-lb-sale">{nairaFull(m.sales)}</div>
                    <div className="staff-lb-meta">
                      {m.transactions.toLocaleString()} tx · avg {nairaFull(avg)}
                    </div>
                    {m.staff_salary > 0 && totalSales > 0 && (
                      <div className="staff-lb-salary">
                        Salary: {nairaFull(m.staff_salary)}/mo
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

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
          {(() => {
            const link = `${window.location.origin}/app/login?invite=${encodeURIComponent(invResult.invite_code)}`
              + (invResult.phone ? `&phone=${encodeURIComponent(invResult.phone)}` : "");
            const msg = `You've been invited to join as staff on CreditVoice. Tap to accept (expires in 24h):\n${link}`;
            const waDigits = (invResult.phone || "").replace(/\D/g, "");
            const waUrl = waDigits
              ? `https://wa.me/${waDigits}?text=${encodeURIComponent(msg)}`
              : `https://api.whatsapp.com/send?text=${encodeURIComponent(msg)}`;
            return (
              <div style={{ marginTop: 12 }}>
                <div className="login-hint-muted" style={{ marginBottom: 6 }}>
                  Or send them this invite link — it opens the accept form ready to confirm:
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <input readOnly value={link} onFocus={e => e.target.select()}
                    style={{ flex: 1, minWidth: 200, fontSize: 12, fontFamily: "monospace" }} />
                  <CopyButton text={link} label="Copy link" />
                  <a className="btn btn-primary" style={{ padding: "4px 10px", fontSize: 12 }}
                    href={waUrl} target="_blank" rel="noopener noreferrer">
                    Send on WhatsApp
                  </a>
                </div>
              </div>
            );
          })()}
          <p className="login-hint-muted" style={{ margin: "10px 0 0" }}>
            The link takes them straight to <strong>Accept staff invitation</strong> with the code filled in. Or they can enter the code manually. Expires in 24 hours.
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
              <div key={m.id} style={{ padding: "10px 0", borderBottom: "1px solid var(--border)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <Clock size={16} style={{ color: "var(--amber)", flexShrink: 0 }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, fontSize: 14 }}>{m.name}</div>
                    <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{m.phone}{m.email ? ` · ${m.email}` : ""}</div>
                  </div>
                  <button className="btn btn-secondary btn-sm" disabled={resendBusy[m.id]}
                    onClick={() => resendInvite(m)}>
                    {resendBusy[m.id] ? "Sending…" : "Resend invite"}
                  </button>
                  <span className="badge badge-amber">Pending</span>
                </div>
                {resendResult[m.id] && (
                  <InviteShare code={resendResult[m.id].invite_code} phone={resendResult[m.id].phone || m.phone} />
                )}
              </div>
            ))}
          </div>
          <p className="login-hint-muted" style={{ marginTop: 10 }}>
            If a code expired or was lost, tap <strong>Resend invite</strong> for a fresh 24-hour code and link. They accept at <strong>CreditVoice → Accept staff invitation</strong>.
          </p>
        </div>
      )}

      {/* ── Active staff ── */}
      {loading ? (
        <div className="card"><Skeleton rows={4} /></div>
      ) : staff.length === 0 ? (
        <div className="card"><EmptyState text="No active staff yet. Use the invite form above to add your first staff member." /></div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(min(300px, 100%), 1fr))", gap: 16 }}>
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

                {isOwner && (() => {
                  const mem = members.find(x => x.id === member.id);
                  if (!mem || mem.pending) return null;
                  const full = mem.full_access;
                  return (
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 600 }}>
                          {full ? "Branch admin" : "Own records only"}
                        </div>
                        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                          {full
                            ? (mem.branch_id ? "Sees all records in their branch." : "Assign a branch below to scope this.")
                            : "Sees only what they record."}
                        </div>
                      </div>
                      <button
                        className={`btn btn-sm ${full ? "btn-secondary" : "btn-primary"}`}
                        disabled={accessBusy[member.id]}
                        onClick={() => toggleAccess(member.id, !full)}
                      >
                        {accessBusy[member.id] ? "Saving…" : (full ? "Remove branch admin" : "Make branch admin")}
                      </button>
                    </div>
                  );
                })()}

                {isOwner && branches.length > 0 && (() => {
                  const mem = members.find(x => x.id === member.id);
                  if (!mem || mem.pending) return null;
                  return (
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 600 }}>Branch</div>
                        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                          Their sales are tagged to this branch.
                        </div>
                      </div>
                      <select
                        value={mem.branch_id ?? ""}
                        disabled={branchBusy[member.id]}
                        onChange={e => setBranch(member.id, e.target.value ? Number(e.target.value) : null)}
                        style={{ maxWidth: 160 }}
                      >
                        <option value="">No branch</option>
                        {branches.map(b => (
                          <option key={b.id} value={b.id}>{b.name}</option>
                        ))}
                      </select>
                    </div>
                  );
                })()}

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

      </>}
    </>
  );
}
