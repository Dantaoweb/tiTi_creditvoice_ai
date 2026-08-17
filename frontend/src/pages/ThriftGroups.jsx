import { useEffect, useState } from "react";
import {
  Users, Plus, Copy, Check, ArrowLeft, Crown, ShieldCheck, Trash2,
  UserPlus, Coins, ArrowUpCircle, Loader2, CircleDollarSign, Lock, Unlock,
} from "lucide-react";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull, parseAmt } from "../lib/format";
import MoneyInput from "../components/MoneyInput";
import MetricCard from "../components/MetricCard";
import EmptyState from "../components/EmptyState";
import Skeleton from "../components/Skeleton";

const cap = s => (s || "—").replace(/\b\w/g, c => c.toUpperCase());
const ROLE_BADGE = { admin: "badge-blue", approver: "badge-amber", member: "badge-gray" };
const ROLE_LABEL = { admin: "Admin", approver: "Approver", member: "Member" };

// ── Create-group form ──────────────────────────────────────────────────────────
function CreateGroup({ onDone, onCancel }) {
  const [form, setForm] = useState({ name: "", amount: "", frequency: "weekly", require_approval: true, max_members: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  async function submit(e) {
    e.preventDefault();
    const amount = parseAmt(form.amount);
    if (!form.name.trim()) { setErr("Give the group a name."); return; }
    if (!amount || amount <= 0) { setErr("Enter a contribution amount."); return; }
    setBusy(true); setErr("");
    try {
      const cap = parseInt(form.max_members, 10);
      const g = await apiPost("thrift/groups", {
        name: form.name.trim(), contribution_amount: amount,
        frequency: form.frequency, require_approval: form.require_approval,
        max_members: form.max_members && cap >= 2 ? cap : null,
      });
      onDone(g);
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="card">
      <div className="card-title" style={{ marginBottom: 10 }}>New Ajo / Thrift group</div>
      <form onSubmit={submit} style={{ display: "grid", gap: 12 }}>
        <div className="form-group">
          <label className="form-label">Group name *</label>
          <input value={form.name} onChange={e => set("name", e.target.value)}
            placeholder="e.g. Market Women Ajo" disabled={busy} autoFocus />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div className="form-group">
            <label className="form-label">Contribution per round *</label>
            <MoneyInput value={form.amount} onChange={v => set("amount", v)} placeholder="e.g. 5,000" disabled={busy} />
          </div>
          <div className="form-group">
            <label className="form-label">Frequency</label>
            <select value={form.frequency} onChange={e => set("frequency", e.target.value)} disabled={busy}>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
            </select>
          </div>
        </div>
        <div className="form-group">
          <label className="form-label">Member limit (optional)</label>
          <input type="number" min="2" value={form.max_members}
            onChange={e => set("max_members", e.target.value)} placeholder="e.g. 10" disabled={busy} />
          <span className="form-hint">Leave blank for no limit. You can also lock the group later.</span>
        </div>
        <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13.5 }}>
          <input type="checkbox" checked={form.require_approval}
            onChange={e => set("require_approval", e.target.checked)} style={{ width: "auto" }} />
          People who join via the link need approval first
        </label>
        {err && <div className="login-error">{err}</div>}
        <div style={{ display: "flex", gap: 10 }}>
          <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? "Creating…" : "Create group"}</button>
          <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={busy}>Cancel</button>
        </div>
      </form>
    </div>
  );
}

// ── Group detail ────────────────────────────────────────────────────────────────
function GroupDetail({ groupId, onBack }) {
  const [g, setG] = useState(null);
  const [err, setErr] = useState("");
  const [copied, setCopied] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    apiFetch(`thrift/groups/${groupId}`).then(setG).catch(e => setErr(e.message));
  }
  useEffect(load, [groupId]);

  async function act(path, body) {
    setBusy(true); setErr("");
    try { const r = await apiPost(path, body || {}); setG(r); }
    catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }
  async function removeMember(id) {
    if (!window.confirm("Remove this member?")) return;
    setBusy(true);
    try {
      const r = await fetch(`/app/api/thrift/members/${id}`, { method: "DELETE", credentials: "include" });
      setG(await r.json());
    } catch (_) {} finally { setBusy(false); }
  }
  function copyLink() {
    const link = `${window.location.origin}/app/thrift/join/${g.invite_token}`;
    navigator.clipboard.writeText(link).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000); });
  }
  async function addMember(e) {
    e.preventDefault();
    if (!newName.trim()) return;
    await act(`thrift/groups/${groupId}/members`, { name: newName.trim() });
    setNewName(""); setShowAdd(false);
  }

  if (err && !g) return <div className="card card-body" style={{ color: "var(--rose)" }}>{err}</div>;
  if (!g) return <div className="card card-body" style={{ display: "flex", gap: 8 }}><Loader2 size={16} className="spin" /> Loading…</div>;

  const members = g.members || [];
  const pending = members.filter(m => m.status === "pending");
  const active = members.filter(m => m.status === "active");
  const canApprove = g.can_approve;
  const isAdmin = g.is_admin;
  const completed = g.status === "completed";

  return (
    <>
      <button className="btn btn-secondary btn-sm" onClick={onBack} style={{ marginBottom: 12 }}>
        <ArrowLeft size={13} /> All groups
      </button>

      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>{g.name}</h2>
        <span className="text-subtle text-sm">
          {nairaFull(g.contribution_amount)} · {cap(g.frequency)} · {completed ? "Completed" : `Round ${g.current_round} of ${g.total_rounds}`}
        </span>
      </div>

      {err && <div className="card card-body" style={{ color: "var(--rose)", marginBottom: 8 }}>{err}</div>}

      <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))" }}>
        <MetricCard label="Pot per round" value={nairaFull(g.pot)} color="green" />
        <MetricCard label="Members" value={g.max_members ? `${g.active_count}/${g.max_members}` : g.active_count} color="blue" />
        <MetricCard label="Paid this round" value={`${g.paid_count || 0}/${g.active_count}`} color="brand" />
        <MetricCard label="Collected" value={nairaFull(g.collected_this_round)} color="amber" small />
      </div>

      {/* Whose turn */}
      {!completed && g.current_turn && (
        <div className="card" style={{ borderLeft: "3px solid var(--brand)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <CircleDollarSign size={18} color="var(--brand)" />
            <div style={{ flex: 1 }}>
              <strong>{g.current_turn.name}</strong> collects the pot this round
              <div className="text-subtle text-sm">Round {g.current_round} · {nairaFull(g.pot)}</div>
            </div>
            {canApprove && (
              <button className="btn btn-primary btn-sm" disabled={busy}
                onClick={() => act(`thrift/groups/${groupId}/payout`)}>
                <ArrowUpCircle size={13} /> Record payout
              </button>
            )}
          </div>
        </div>
      )}

      {/* Admin: lock / membership status */}
      {isAdmin && (
        <div className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <div>
            <strong>{g.locked ? "Group is locked" : (completed ? "Group is completed" : (!g.accepting ? "Group is full" : "Group is open"))}</strong>
            <div className="text-subtle text-sm">
              {g.slots_taken}{g.max_members ? ` of ${g.max_members}` : ""} members{g.max_members ? "" : " · no limit"}
            </div>
          </div>
          <button className="btn btn-secondary btn-sm" disabled={busy}
            onClick={() => act(`thrift/groups/${groupId}/settings`, { locked: !g.locked })}>
            {g.locked ? <><Unlock size={13} /> Unlock</> : <><Lock size={13} /> Lock group</>}
          </button>
        </div>
      )}

      {/* Invite link */}
      {canApprove && g.invite_token && (
        <div className="card">
          <div className="form-label" style={{ marginBottom: 6 }}>Invite link — share it so people can join</div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <input readOnly value={`${window.location.origin}/app/thrift/join/${g.invite_token}`}
              onFocus={e => e.target.select()} style={{ flex: 1, minWidth: 200, fontSize: 12 }} />
            <button className="btn btn-primary btn-sm" onClick={copyLink}>
              {copied ? <><Check size={13} /> Copied</> : <><Copy size={13} /> Copy</>}
            </button>
          </div>
          {!g.accepting && (
            <div className="text-subtle text-sm" style={{ marginTop: 6 }}>
              New members can't join right now — the group is {g.locked ? "locked" : (completed ? "completed" : "full")}.
            </div>
          )}
        </div>
      )}

      {/* Pending approvals */}
      {canApprove && pending.length > 0 && (
        <div className="card">
          <div className="card-title" style={{ marginBottom: 8 }}>Pending approvals ({pending.length})</div>
          <div style={{ display: "grid", gap: 8 }}>
            {pending.map(m => (
              <div key={m.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <span>{m.name}</span>
                <div style={{ display: "flex", gap: 6 }}>
                  <button className="btn btn-primary btn-sm" disabled={busy}
                    onClick={() => act(`thrift/members/${m.id}/approve`)}>Approve</button>
                  <button className="btn btn-secondary btn-sm" style={{ color: "var(--rose)" }} disabled={busy}
                    onClick={() => act(`thrift/members/${m.id}/decline`)}>Decline</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Members */}
      <div className="card">
        <div className="card-header" style={{ flexWrap: "wrap", gap: 8 }}>
          <span className="card-title"><Users size={15} /> Members</span>
          {canApprove && !completed && g.accepting && (
            <button className="btn btn-secondary btn-sm" onClick={() => setShowAdd(s => !s)}>
              <UserPlus size={13} /> Add participant
            </button>
          )}
        </div>
        {showAdd && (
          <form onSubmit={addMember} style={{ display: "flex", gap: 8, margin: "8px 0", flexWrap: "wrap" }}>
            <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="Participant name"
              style={{ flex: 1, minWidth: 160 }} autoFocus />
            <button className="btn btn-primary btn-sm" disabled={busy}>Add</button>
          </form>
        )}
        <div style={{ overflowX: "auto" }}>
          <table className="history-table">
            <thead><tr><th>#</th><th>Member</th><th>Contributed</th><th>This round</th><th></th></tr></thead>
            <tbody>
              {active.map(m => (
                <tr key={m.id} style={m.turn_order === g.current_round && !completed ? { background: "rgba(26,86,219,0.06)" } : undefined}>
                  <td className="td-muted">{m.turn_order ?? "—"}</td>
                  <td>
                    {m.name}{m.is_me ? " (you)" : ""}
                    {m.role === "admin" && <Crown size={12} color="var(--brand)" style={{ marginLeft: 6 }} />}
                    {m.role === "approver" && <span className="badge badge-amber" style={{ marginLeft: 6 }}>Approver</span>}
                  </td>
                  <td>{nairaFull(m.total_contributed)}</td>
                  <td>
                    {m.paid_current_round
                      ? <span className="badge badge-green"><Check size={11} /> Paid</span>
                      : canApprove && !completed
                        ? <button className="btn btn-secondary btn-sm" disabled={busy}
                            onClick={() => act(`thrift/groups/${groupId}/contributions`, { member_id: m.id })}>
                            <Coins size={12} /> Record
                          </button>
                        : <span className="td-muted">—</span>}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    {isAdmin && m.role !== "admin" && (
                      <span style={{ display: "inline-flex", gap: 6 }}>
                        {m.role === "member"
                          ? <button className="btn btn-secondary btn-sm" title="Give approval power" disabled={busy}
                              onClick={() => act(`thrift/members/${m.id}/promote`)}><ShieldCheck size={12} /></button>
                          : <button className="btn btn-secondary btn-sm" title="Remove approval power" disabled={busy}
                              onClick={() => act(`thrift/members/${m.id}/demote`)}>Demote</button>}
                        <button className="btn btn-secondary btn-sm" style={{ color: "var(--rose)" }} title="Remove"
                          disabled={busy} onClick={() => removeMember(m.id)}><Trash2 size={12} /></button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Payout history */}
      {g.payouts?.length > 0 && (
        <div className="card">
          <div className="card-title" style={{ marginBottom: 8 }}>Payout history</div>
          <div style={{ overflowX: "auto" }}>
            <table className="history-table">
              <thead><tr><th>Round</th><th>Collected by</th><th>Amount</th></tr></thead>
              <tbody>
                {g.payouts.map((p, i) => (
                  <tr key={i}>
                    <td className="td-muted">{p.round_number}</td>
                    <td>{p.member_name}</td>
                    <td><strong>{nairaFull(p.amount)}</strong></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

// ── Groups list + entry ─────────────────────────────────────────────────────────
export default function ThriftGroups() {
  const [groups, setGroups] = useState(null);
  const [selected, setSelected] = useState(null);
  const [showCreate, setShowCreate] = useState(false);

  function load() {
    apiFetch("thrift/groups").then(d => setGroups(d.groups || [])).catch(() => setGroups([]));
  }
  useEffect(load, []);

  if (selected) {
    return <GroupDetail groupId={selected} onBack={() => { setSelected(null); load(); }} />;
  }

  return (
    <>
      {!showCreate ? (
        <div className="card" style={{ marginBottom: 0 }}>
          <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
            <Plus size={15} /> Create Ajo / Thrift group
          </button>
        </div>
      ) : (
        <CreateGroup onDone={g => { setShowCreate(false); load(); setSelected(g.id); }}
          onCancel={() => setShowCreate(false)} />
      )}

      {groups === null ? (
        <div className="card"><Skeleton rows={3} /></div>
      ) : groups.length === 0 ? (
        <div className="card"><EmptyState text={"No groups yet.\nCreate an ajo/thrift group, set the contribution amount, then share the invite link so members can join."} /></div>
      ) : (
        <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))" }}>
          {groups.map(g => (
            <button key={g.id} className="card" style={{ textAlign: "left", cursor: "pointer" }}
              onClick={() => setSelected(g.id)}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", gap: 8 }}>
                <span className="card-title">{g.name}</span>
                <span className={`badge ${ROLE_BADGE[g.my_role] || "badge-gray"}`}>{ROLE_LABEL[g.my_role] || g.my_role}</span>
              </div>
              <div className="text-subtle text-sm" style={{ marginTop: 6 }}>
                {nairaFull(g.contribution_amount)} · {cap(g.frequency)}
              </div>
              <div style={{ display: "flex", gap: 12, marginTop: 10, fontSize: 13 }}>
                <span><strong>{g.active_count}</strong> members</span>
                <span className="text-subtle">{g.status === "completed" ? "Completed" : `Round ${g.current_round}`}</span>
                {g.pending_count > 0 && <span className="badge badge-amber">{g.pending_count} pending</span>}
              </div>
            </button>
          ))}
        </div>
      )}
    </>
  );
}
