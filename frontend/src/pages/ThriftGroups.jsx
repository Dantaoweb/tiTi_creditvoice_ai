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
import { usePlan } from "../lib/usePlan";

const cap = s => (s || "—").replace(/\b\w/g, c => c.toUpperCase());
const ROLE_BADGE = { admin: "badge-blue", approver: "badge-amber", member: "badge-gray" };
const ROLE_LABEL = { admin: "Admin", approver: "Approver", member: "Member" };

// ── Create-group form ──────────────────────────────────────────────────────────
function CreateGroup({ onDone, onCancel }) {
  const { allows } = usePlan();
  const canTarget = allows("THRIFT_TARGET_GROUPS");
  const [form, setForm] = useState({ name: "", type: "rotating", amount: "", goal: "", target_date: "", frequency: "weekly", require_approval: true, max_members: "", spillover: false, payout_method: "order" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));
  const isTarget = form.type === "target";

  async function submit(e) {
    e.preventDefault();
    if (!form.name.trim()) { setErr("Give the group a name."); return; }
    const amount = parseAmt(form.amount);
    const goal = parseAmt(form.goal);
    const cap = parseInt(form.max_members, 10);
    if (!cap || cap < 2) { setErr("Set a member limit (at least 2) — every group must be capped."); return; }
    if (isTarget) { if (!goal || goal <= 0) { setErr("Set a goal amount."); return; } }
    else if (!amount || amount <= 0) { setErr("Enter a contribution amount."); return; }
    setBusy(true); setErr("");
    try {
      const g = await apiPost("thrift/groups", {
        name: form.name.trim(), group_type: form.type,
        contribution_amount: amount || 0,
        goal_amount: isTarget ? goal : null,
        target_date: isTarget && form.target_date ? form.target_date : null,
        frequency: form.frequency, require_approval: form.require_approval,
        max_members: cap,
        spillover: isTarget ? false : form.spillover,
        payout_method: form.payout_method,
      });
      onDone(g);
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="card">
      <div className="card-title" style={{ marginBottom: 10 }}>New savings group</div>
      <form onSubmit={submit} style={{ display: "grid", gap: 12 }}>
        <div className="form-group">
          <label className="form-label">Type</label>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" className={`btn btn-sm ${!isTarget ? "btn-primary" : "btn-secondary"}`}
              onClick={() => set("type", "rotating")} disabled={busy}>Rotating (ajo)</button>
            <button type="button" className={`btn btn-sm ${isTarget ? "btn-primary" : "btn-secondary"}`}
              onClick={() => canTarget && set("type", "target")} disabled={busy || !canTarget}
              title={canTarget ? "" : "Target/goal groups are a Pro feature"}>
              Target (shared goal){!canTarget && " 🔒"}
            </button>
          </div>
          <span className="form-hint">{!canTarget
            ? "Target/goal savings (e.g. Eid) is available on Pro. Rotating ajo works on your plan."
            : isTarget
              ? "Everyone saves flexible amounts, any time, toward one goal (e.g. Eid)."
              : "A fixed amount each round; the pot rotates to one member per round."}</span>
        </div>
        <div className="form-group">
          <label className="form-label">Group name *</label>
          <input value={form.name} onChange={e => set("name", e.target.value)}
            placeholder={isTarget ? "e.g. Eid Savings 2027" : "e.g. Market Women Ajo"} disabled={busy} autoFocus />
        </div>

        {isTarget ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12 }}>
            <div className="form-group">
              <label className="form-label">Goal amount *</label>
              <MoneyInput value={form.goal} onChange={v => set("goal", v)} placeholder="e.g. 500,000" disabled={busy} />
            </div>
            <div className="form-group">
              <label className="form-label">Target date (optional)</label>
              <input type="date" value={form.target_date} min={new Date().toISOString().slice(0, 10)}
                onChange={e => set("target_date", e.target.value)} disabled={busy} />
            </div>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12 }}>
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
        )}

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12 }}>
          <div className="form-group">
            <label className="form-label">Member limit *</label>
            <input type="number" min="2" value={form.max_members}
              onChange={e => set("max_members", e.target.value)} placeholder="e.g. 10" disabled={busy} />
            <span className="form-hint">Every group must be capped.</span>
          </div>
          {!isTarget && (
            <div className="form-group">
              <label className="form-label">Who collects the pot?</label>
              <select value={form.payout_method} onChange={e => set("payout_method", e.target.value)} disabled={busy}>
                <option value="order">In join order (rotate)</option>
                <option value="choice">Admin picks each round</option>
              </select>
            </div>
          )}
        </div>
        <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13.5 }}>
          <input type="checkbox" checked={form.require_approval}
            onChange={e => set("require_approval", e.target.checked)} style={{ width: "auto" }} />
          People who join via the link need approval first
        </label>
        {!isTarget && (
          <label style={{ display: "flex", gap: 8, alignItems: "start", fontSize: 13.5 }}>
            <input type="checkbox" checked={form.spillover}
              onChange={e => set("spillover", e.target.checked)} style={{ width: "auto", marginTop: 3 }} />
            <span>Auto-continue — when this group fills, the same invite link starts and fills the next group automatically.
              <span className="text-subtle"> One link serves many groups.</span></span>
          </label>
        )}
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
  const [payMember, setPayMember] = useState("");   // choice-payout picker
  const [recId, setRecId] = useState(null);         // member whose amount is being entered
  const [recAmt, setRecAmt] = useState("");

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
  const isTarget = g.group_type === "target";

  return (
    <>
      <button className="btn btn-secondary btn-sm" onClick={onBack} style={{ marginBottom: 12 }}>
        <ArrowLeft size={13} /> All groups
      </button>

      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>{g.name}</h2>
        <span className="text-subtle text-sm">
          {isTarget
            ? <>Target: {nairaFull(g.goal_amount)}{g.target_date ? ` · by ${dateStr(g.target_date)}` : ""}</>
            : <>{nairaFull(g.contribution_amount)} · {cap(g.frequency)} · {completed ? "Completed" : `Round ${g.current_round} of ${g.total_rounds}`}</>}
        </span>
      </div>

      {err && <div className="card card-body" style={{ color: "var(--rose)", marginBottom: 8 }}>{err}</div>}

      {isTarget ? (
        <>
          <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))" }}>
            <MetricCard label="Saved so far" value={nairaFull(g.total_saved)} color="green" />
            <MetricCard label="Goal" value={nairaFull(g.goal_amount)} color="brand" />
            <MetricCard label="Members" value={g.max_members ? `${g.active_count}/${g.max_members}` : g.active_count} color="blue" small />
            <MetricCard label={g.days_to_target != null ? "Days left" : "Progress"}
              value={g.days_to_target != null ? Math.max(0, g.days_to_target) : `${g.goal_pct ?? 0}%`} color="amber" small />
          </div>
          <div className="card">
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
              <span>{nairaFull(g.total_saved)} of {nairaFull(g.goal_amount)}</span>
              <strong>{g.goal_pct ?? 0}%</strong>
            </div>
            <div style={{ height: 10, background: "var(--line)", borderRadius: 99, overflow: "hidden" }}>
              <div style={{ width: `${g.goal_pct ?? 0}%`, height: "100%", background: g.goal_reached ? "#166534" : "var(--brand)" }} />
            </div>
            {g.goal_reached && <div className="text-sm" style={{ color: "#166534", marginTop: 6 }}>🎉 Goal reached!</div>}
          </div>
        </>
      ) : (
      <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))" }}>
        <MetricCard label="Pot per round" value={nairaFull(g.pot)} color="green" />
        <MetricCard label="Members" value={g.max_members ? `${g.active_count}/${g.max_members}` : g.active_count} color="blue" />
        <MetricCard label="Paid this round" value={`${g.paid_count || 0}/${g.active_count}`} color="brand" />
        <MetricCard label="Collected" value={nairaFull(g.collected_this_round)} color="amber" small />
      </div>
      )}

      {/* Pot this round — order rotates automatically, choice lets admin pick */}
      {!isTarget && !completed && (g.eligible_recipients || []).length > 0 && (
        <div className="card" style={{ borderLeft: "3px solid var(--brand)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <CircleDollarSign size={18} color="var(--brand)" />
            <div style={{ flex: 1 }}>
              {g.payout_method === "choice"
                ? <><strong>Admin picks</strong> who collects the pot this round</>
                : g.current_turn
                  ? <><strong>{g.current_turn.name}</strong> collects the pot this round</>
                  : <span className="text-subtle">Waiting…</span>}
              <div className="text-subtle text-sm">Round {g.current_round} · {nairaFull(g.pot)}</div>
            </div>
            {canApprove && g.payout_method === "choice" ? (
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <select value={payMember} onChange={e => setPayMember(e.target.value)} style={{ maxWidth: 150 }}>
                  <option value="">Choose member…</option>
                  {g.eligible_recipients.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
                </select>
                <button className="btn btn-primary btn-sm" disabled={busy || !payMember}
                  onClick={async () => { await act(`thrift/groups/${groupId}/payout`, { member_id: Number(payMember) }); setPayMember(""); }}>
                  <ArrowUpCircle size={13} /> Pay
                </button>
              </div>
            ) : canApprove && g.current_turn ? (
              <button className="btn btn-primary btn-sm" disabled={busy}
                onClick={() => act(`thrift/groups/${groupId}/payout`)}>
                <ArrowUpCircle size={13} /> Record payout
              </button>
            ) : null}
          </div>
        </div>
      )}

      {/* Admin: lock / membership status / pot method */}
      {isAdmin && (
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
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
          {!isTarget && (
            <div style={{ marginTop: 10, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }} className="text-sm">
              <span className="text-subtle">Pot collector:</span>
              <select value={g.payout_method} disabled={busy}
                onChange={e => act(`thrift/groups/${groupId}/settings`, { payout_method: e.target.value })}>
                <option value="order">In join order (rotate)</option>
                <option value="choice">Admin picks each round</option>
              </select>
            </div>
          )}
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
          {g.spillover && !g.locked && !completed && (
            <div className="text-subtle text-sm" style={{ marginTop: 6 }}>
              ♻ Auto-continue is on — when this group fills, this link starts and fills the next group automatically.
            </div>
          )}
          {!g.accepting && !(g.spillover && !g.locked && !completed) && (
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
            <thead><tr><th>#</th><th>Member</th><th>{isTarget ? "Saved" : "Contributed"}</th><th>{isTarget ? "" : "This round"}</th><th></th></tr></thead>
            <tbody>
              {active.map(m => (
                <tr key={m.id} style={!isTarget && m.turn_order === g.current_round && !completed ? { background: "rgba(26,86,219,0.06)" } : undefined}>
                  <td className="td-muted">{isTarget ? "•" : (m.turn_order ?? "—")}</td>
                  <td>
                    {m.name}{m.is_me ? " (you)" : ""}
                    {m.role === "admin" && <Crown size={12} color="var(--brand)" style={{ marginLeft: 6 }} />}
                    {m.role === "approver" && <span className="badge badge-amber" style={{ marginLeft: 6 }}>Approver</span>}
                  </td>
                  <td>{nairaFull(m.total_contributed)}</td>
                  <td>
                    {(() => {
                      const mayRecord = (canApprove || (isTarget && m.is_me)) && !completed;
                      if (!isTarget && m.paid_current_round)
                        return <span className="badge badge-green"><Check size={11} /> Paid</span>;
                      if (!mayRecord) return <span className="td-muted">—</span>;
                      if (recId === m.id)
                        return <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
                          <input inputMode="numeric" value={recAmt} onChange={e => setRecAmt(e.target.value)}
                            placeholder={isTarget ? "amount" : ""} style={{ width: 84 }} autoFocus />
                          <button className="btn btn-primary btn-sm" disabled={busy}
                            onClick={async () => { const amt = parseAmt(recAmt) || (isTarget ? 0 : g.contribution_amount); if (!amt) return; await act(`thrift/groups/${groupId}/contributions`, { member_id: m.id, amount: amt }); setRecId(null); }}>Save</button>
                          <button className="btn btn-secondary btn-sm" onClick={() => setRecId(null)}>✕</button>
                        </span>;
                      return <button className="btn btn-secondary btn-sm" disabled={busy}
                        onClick={() => { setRecId(m.id); setRecAmt(isTarget ? "" : String(g.contribution_amount || "")); }}>
                        <Coins size={12} /> {isTarget ? (m.is_me ? "Add saving" : "Record") : "Record"}
                      </button>;
                    })()}
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
      {!isTarget && g.payouts?.length > 0 && (
        <div className="card">
          <div className="card-title" style={{ marginBottom: 8 }}>Payout history</div>
          <div style={{ overflowX: "auto" }}>
            <table className="history-table">
              <thead><tr><th>Round</th><th>Collected by</th><th>Amount</th><th>Confirmed</th></tr></thead>
              <tbody>
                {g.payouts.map(p => (
                  <tr key={p.id}>
                    <td className="td-muted">{p.round_number}</td>
                    <td>{p.member_name}</td>
                    <td><strong>{nairaFull(p.amount)}</strong></td>
                    <td>
                      {p.confirmed
                        ? <span className="badge badge-green"><Check size={11} /> Confirmed by recipient</span>
                        : p.can_confirm
                          ? <button className="btn btn-primary btn-sm" disabled={busy}
                              onClick={() => act(`thrift/payouts/${p.id}/confirm`)}>I received it</button>
                          : <span className="badge badge-amber">Awaiting recipient</span>}
                    </td>
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
                {g.group_type === "target"
                  ? <>🎯 Goal {nairaFull(g.goal_amount)}</>
                  : <>{nairaFull(g.contribution_amount)} · {cap(g.frequency)}</>}
              </div>
              {g.group_type === "target" && (
                <div style={{ height: 6, background: "var(--line)", borderRadius: 99, overflow: "hidden", marginTop: 8 }}>
                  <div style={{ width: `${g.goal_pct ?? 0}%`, height: "100%", background: g.goal_reached ? "#166534" : "var(--brand)" }} />
                </div>
              )}
              <div style={{ display: "flex", gap: 12, marginTop: 10, fontSize: 13 }}>
                <span><strong>{g.active_count}</strong> members</span>
                <span className="text-subtle">
                  {g.group_type === "target"
                    ? `${nairaFull(g.total_saved)} saved (${g.goal_pct ?? 0}%)`
                    : (g.status === "completed" ? "Completed" : `Round ${g.current_round}`)}
                </span>
                {g.pending_count > 0 && <span className="badge badge-amber">{g.pending_count} pending</span>}
              </div>
            </button>
          ))}
        </div>
      )}
    </>
  );
}
