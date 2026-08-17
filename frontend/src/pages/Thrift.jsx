import { useEffect, useState } from "react";
import { Activity, Users, TrendingUp, Plus, Info, Landmark, ChevronDown, ChevronUp, UserPlus } from "lucide-react";
import { useApp } from "../context/AppContext";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull, dateTimeStr, dateStr, parseAmt } from "../lib/format";
import MoneyInput from "../components/MoneyInput";
import MetricCard from "../components/MetricCard";
import Skeleton from "../components/Skeleton";
import EmptyState from "../components/EmptyState";
import DataTable from "../components/DataTable";
import ThriftGroups from "./ThriftGroups";
import { useNavigate } from "react-router-dom";

// ── Collapsible explainer ──────────────────────────────────────────────────────

function ThriftExplainer({ mode }) {
  const [open, setOpen] = useState(false);
  const text = mode === "group"
    ? {
        title: "Group Thrift / Ajo — How it works",
        body: (
          <>
            <p>
              <strong style={{ color: "#6d28d9" }}>Ajo / esusu / thrift</strong> is a group savings scheme where members
              contribute money regularly and the pot rotates to each member in turn.
            </p>
            <p>Add participants below, then record their contributions on WhatsApp or here.</p>
            <p><strong style={{ color: "#6d28d9" }}>Record via WhatsApp:</strong></p>
            <ul style={{ paddingLeft: 18, margin: "4px 0" }}>
              <li>Amina contributed 5000</li>
              <li>Tunde paid ajo 2000</li>
            </ul>
            <p style={{ marginTop: 8 }}>
              💡 Connect your <strong style={{ color: "#6d28d9" }}>Wallet</strong> so participants
              can pay directly — contributions match automatically.
            </p>
          </>
        ),
      }
    : {
        title: "Personal Savings — How it works",
        body: (
          <>
            <p>
              Track your <strong style={{ color: "#6d28d9" }}>personal savings</strong> alongside
              your business records — no participants or group needed.
            </p>
            <p>
              Record each deposit with an amount and optional note. See your running total at a glance.
            </p>
            <p><strong style={{ color: "#6d28d9" }}>Record via WhatsApp:</strong></p>
            <ul style={{ paddingLeft: 18, margin: "4px 0" }}>
              <li>I saved 5000</li>
              <li>personal savings 10000</li>
            </ul>
          </>
        ),
      };

  return (
    <div className="card" style={{ borderLeft: "3px solid #1a56db", marginBottom: 0 }}>
      <div className="card-header" style={{ cursor: "pointer" }} onClick={() => setOpen(o => !o)}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Info size={14} color="#3b82f6" />
          <span className="card-title" style={{ color: "#3b82f6", fontSize: 13 }}>{text.title}</span>
        </div>
        {open ? <ChevronUp size={14} color="var(--muted)" /> : <ChevronDown size={14} color="var(--muted)" />}
      </div>
      {open && (
        <div style={{ fontSize: 13, color: "var(--ink)", lineHeight: 1.7, paddingTop: 4 }}>
          {text.body}
        </div>
      )}
    </div>
  );
}

// ── Add participant form ───────────────────────────────────────────────────────

function AddParticipantForm({ onAdded, onCancel }) {
  const [name, setName]   = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy]   = useState(false);
  const [err, setErr]     = useState("");

  async function save() {
    if (!name.trim()) { setErr("Name is required."); return; }
    setBusy(true); setErr("");
    try {
      const res = await apiPost("thrift/participants", { name: name.trim(), phone: phone.trim() || null });
      onAdded(res);
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div style={{ padding: "12px 0", borderTop: "1px solid var(--border)", marginTop: 12, display: "grid", gap: 10 }}>
      <div className="card-title" style={{ marginBottom: 0 }}>Add Participant</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <div className="form-group">
          <label className="form-label">Full Name *</label>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Amina Bello" autoFocus disabled={busy} />
        </div>
        <div className="form-group">
          <label className="form-label">Phone (optional)</label>
          <input value={phone} onChange={e => setPhone(e.target.value)} placeholder="e.g. 08012345678" disabled={busy} />
        </div>
      </div>
      {err && <div className="login-error">{err}</div>}
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn btn-primary btn-sm" onClick={save} disabled={busy}>{busy ? "Saving…" : "Add"}</button>
        <button className="btn btn-secondary btn-sm" onClick={onCancel} disabled={busy}>Cancel</button>
      </div>
    </div>
  );
}

// ── Record personal saving form ────────────────────────────────────────────────

function RecordSavingForm({ onSaved, onCancel }) {
  const [amount, setAmount] = useState("");
  const [note, setNote]     = useState("");
  const [busy, setBusy]     = useState(false);
  const [err, setErr]       = useState("");

  async function save() {
    const amt = parseAmt(amount);
    if (!amt || amt <= 0) { setErr("Enter a valid amount."); return; }
    setBusy(true); setErr("");
    try {
      await apiPost("thrift/save", { amount: amt, note: note.trim() || null });
      onSaved();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div style={{ padding: "12px 0", borderTop: "1px solid var(--border)", marginTop: 12, display: "grid", gap: 10 }}>
      <div className="card-title" style={{ marginBottom: 0 }}>Record Saving</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <div className="form-group">
          <label className="form-label">Amount (₦) *</label>
          <MoneyInput value={amount} onChange={v => setAmount(v)}
            placeholder="e.g. 5,000" autoFocus disabled={busy} />
        </div>
        <div className="form-group">
          <label className="form-label">Note (optional)</label>
          <input value={note} onChange={e => setNote(e.target.value)} placeholder="e.g. weekly deposit" disabled={busy} />
        </div>
      </div>
      {err && <div className="login-error">{err}</div>}
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn btn-primary btn-sm" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</button>
        <button className="btn btn-secondary btn-sm" onClick={onCancel} disabled={busy}>Cancel</button>
      </div>
    </div>
  );
}

// ── Group Thrift tab ───────────────────────────────────────────────────────────

function GroupThrift({ data, loading, reload }) {
  const navigate = useNavigate();
  const [showAdd, setShowAdd]   = useState(false);
  const [innerTab, setInnerTab] = useState("participants");

  const participants = data?.participants || [];
  const transactions = data?.transactions || [];
  const total        = data?.total        || 0;
  const count        = data?.count        || 0;

  return (
    <>
      <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(110px, 1fr))" }}>
        <MetricCard loading={loading} label="Total collected" value={nairaFull(total)} color="green" />
        <MetricCard loading={loading} label="Contributions"   value={count.toLocaleString()} color="brand" />
        <MetricCard loading={loading} label="Participants"    value={participants.length.toLocaleString()} color="blue" />
      </div>

      <ThriftExplainer mode="group" />

      {/* Inner tabs */}
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        {["participants", "history"].map(t => (
          <button key={t} className={`btn btn-sm ${innerTab === t ? "btn-primary" : "btn-secondary"}`}
            onClick={() => setInnerTab(t)}>
            {t === "participants" ? <><Users size={12} /> Participants</> : <><Activity size={12} /> History</>}
          </button>
        ))}
      </div>

      {innerTab === "participants" && (
        <div className="card">
          <div className="card-header" style={{ flexWrap: "wrap", gap: 8 }}>
            <span className="card-title"><Users size={15} /> Participants</span>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button className="btn btn-secondary btn-sm" onClick={() => navigate("/capture")}
                title="Record a contribution on the capture page">
                <Plus size={13} /> Record Contribution
              </button>
              <button className="btn btn-primary btn-sm" onClick={() => setShowAdd(a => !a)}>
                <UserPlus size={13} /> Add Participant
              </button>
            </div>
          </div>

          {showAdd && (
            <AddParticipantForm
              onAdded={() => { setShowAdd(false); reload(); }}
              onCancel={() => setShowAdd(false)}
            />
          )}

          {loading ? <Skeleton rows={4} /> : participants.length === 0 ? (
            <EmptyState text={"No participants yet.\nAdd participants and record contributions via WhatsApp:\n→ Amina contributed 5000"} />
          ) : (
            <div style={{ overflowX: "auto", marginTop: 8 }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13.5 }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--border)", color: "var(--text-muted)" }}>
                    <th style={{ padding: "8px 12px", textAlign: "left" }}>Participant</th>
                    <th style={{ padding: "8px 12px", textAlign: "right" }}>Contributions</th>
                    <th style={{ padding: "8px 12px", textAlign: "right" }}>Total</th>
                  </tr>
                </thead>
                <tbody>
                  {participants.map((p, i) => (
                    <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
                      <td style={{ padding: "10px 12px", fontWeight: 600 }}>
                        {(p.name || "—").replace(/\b\w/g, c => c.toUpperCase())}
                      </td>
                      <td style={{ padding: "10px 12px", textAlign: "right", color: "var(--text-muted)" }}>
                        {p.count}
                      </td>
                      <td style={{ padding: "10px 12px", textAlign: "right", fontWeight: 700, color: "var(--brand)" }}>
                        {nairaFull(p.total)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {innerTab === "history" && (
        <DataTable
          loading={loading}
          rows={transactions}
          emptyText="No contributions recorded yet."
          columns={[
            { key: "customer_name", label: "Participant", render: v => (v || "—").replace(/\b\w/g, c => c.toUpperCase()) },
            { key: "amount",        label: "Amount",      render: v => <strong style={{ color: "var(--brand)" }}>{nairaFull(v)}</strong> },
            { key: "product",       label: "Note",        render: v => v || "—" },
            { key: "created_at",    label: "Date",        render: v => dateTimeStr(v) },
          ]}
        />
      )}
    </>
  );
}

// ── Savings plan (frequency + goal + reminders) ─────────────────────────────────

function SavingsPlanCard({ refreshKey }) {
  const [plan, setPlan]   = useState(null);
  const [editing, setEditing] = useState(false);
  const [freq, setFreq]   = useState("weekly");
  const [goal, setGoal]   = useState("");
  const [busy, setBusy]   = useState(false);

  function load() { apiFetch("savings/plan").then(setPlan).catch(() => {}); }
  useEffect(load, [refreshKey]);
  useEffect(() => {
    if (plan?.has_plan) { setFreq(plan.frequency); setGoal(plan.goal_amount ? String(plan.goal_amount) : ""); }
  }, [plan?.has_plan]);

  async function save() {
    setBusy(true);
    try {
      const p = await apiPost("savings/plan", { frequency: freq, goal_amount: goal ? parseAmt(goal) : null });
      setPlan(p); setEditing(false);
    } catch (_) {} finally { setBusy(false); }
  }

  if (!plan) return null;

  if (!plan.has_plan || editing) {
    return (
      <div className="card" style={{ borderLeft: "3px solid #6d28d9" }}>
        <div className="card-title" style={{ marginBottom: 8 }}>Your savings plan</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div className="form-group">
            <label className="form-label">How often do you save? *</label>
            <select value={freq} onChange={e => setFreq(e.target.value)} disabled={busy}>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">Goal amount (optional)</label>
            <MoneyInput value={goal} onChange={setGoal} placeholder="e.g. 100,000" disabled={busy} />
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <button className="btn btn-primary btn-sm" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save plan"}</button>
          {plan.has_plan && <button className="btn btn-secondary btn-sm" onClick={() => setEditing(false)}>Cancel</button>}
        </div>
        <div className="text-subtle text-sm" style={{ marginTop: 8 }}>tiTi will remind you to save on schedule.</div>
      </div>
    );
  }

  const pct = plan.goal_pct ?? 0;
  return (
    <div className="card" style={{ borderLeft: "3px solid #6d28d9" }}>
      <div className="card-header">
        <span className="card-title">Saving {plan.frequency}</span>
        <button className="btn btn-secondary btn-sm" onClick={() => setEditing(true)}>Edit plan</button>
      </div>
      {plan.goal_amount ? (
        <div style={{ marginTop: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
            <span>{nairaFull(plan.total_saved)} of {nairaFull(plan.goal_amount)}</span>
            <strong>{pct}%</strong>
          </div>
          <div style={{ height: 8, background: "var(--line)", borderRadius: 99, overflow: "hidden", marginTop: 4 }}>
            <div style={{ width: `${pct}%`, height: "100%", background: plan.goal_reached ? "#166534" : "#6d28d9" }} />
          </div>
          {plan.goal_reached && <div className="text-sm" style={{ color: "#166534", marginTop: 4 }}>🎉 Goal reached!</div>}
        </div>
      ) : (
        <div className="text-sm" style={{ marginTop: 6 }}>{nairaFull(plan.total_saved)} saved so far</div>
      )}
      <div className="text-sm" style={{ marginTop: 8, color: plan.due ? "var(--rose)" : "var(--muted)", fontWeight: plan.due ? 600 : 400 }}>
        {plan.due
          ? (plan.overdue_days > 0 ? `⏰ Save overdue by ${plan.overdue_days} day${plan.overdue_days === 1 ? "" : "s"}` : "⏰ Time to save today")
          : (plan.next_due_at ? `Next save due ${dateStr(plan.next_due_at)}` : "")}
      </div>
    </div>
  );
}

// ── Personal Savings tab ───────────────────────────────────────────────────────

function PersonalSavings({ data, loading, reload }) {
  const [showForm, setShowForm] = useState(false);

  const transactions = data?.transactions || [];
  const total        = data?.total        || 0;
  const count        = data?.count        || 0;

  return (
    <>
      <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))" }}>
        <MetricCard loading={loading} label="Total saved" value={nairaFull(total)} color="green" />
        <MetricCard loading={loading} label="Deposits"    value={count.toLocaleString()} color="brand" />
      </div>

      <SavingsPlanCard refreshKey={count} />

      <ThriftExplainer mode="personal" />

      <div className="card">
        <div className="card-header">
          <span className="card-title">My Savings</span>
          <button className="btn btn-primary btn-sm" onClick={() => setShowForm(f => !f)}>
            <Plus size={13} /> Record Saving
          </button>
        </div>

        {showForm && (
          <RecordSavingForm
            onSaved={() => { setShowForm(false); reload(); }}
            onCancel={() => setShowForm(false)}
          />
        )}

        {loading ? <Skeleton rows={4} /> : transactions.length === 0 ? (
          <EmptyState text={"No savings recorded yet.\nTap 'Record Saving' above, or send tiTi:\n→ I saved 5000\n→ personal savings 10000"} />
        ) : (
          <DataTable
            loading={false}
            rows={transactions}
            emptyText=""
            columns={[
              { key: "amount",     label: "Amount", render: v => <strong style={{ color: "var(--brand)" }}>{nairaFull(v)}</strong> },
              { key: "product",    label: "Note",   render: v => (v || "").replace("personal_savings", "").replace(/^:\s*/, "") || "—" },
              { key: "created_at", label: "Date",   render: v => dateTimeStr(v) },
            ]}
          />
        )}
      </div>
    </>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Thrift() {
  const { ownerPhone, period } = useApp();
  const navigate = useNavigate();

  const [data, setData]     = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState(null);
  const [mode, setMode]     = useState("group");

  function load() {
    setLoading(true);
    apiFetch("thrift/summary", { period })
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(load, [ownerPhone, period]);

  return (
    <>
      {error && <div style={{ color: "var(--rose)", marginBottom: 12 }}>{error}</div>}

      {/* Page header */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
        <Activity size={20} color="#3b82f6" />
        <span style={{ fontSize: 16, fontWeight: 700 }}>Thrift / Ajo & Savings</span>
      </div>

      {/* Mode toggle */}
      <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        <button
          className={`btn ${mode === "group" ? "btn-primary" : "btn-secondary"}`}
          onClick={() => setMode("group")}
          style={{ fontSize: 13 }}
        >
          <Users size={14} /> Group Thrift / Ajo
        </button>
        <button
          className={`btn ${mode === "personal" ? "btn-primary" : "btn-secondary"}`}
          onClick={() => setMode("personal")}
          style={{ fontSize: 13 }}
        >
          <Landmark size={14} /> Personal Savings
        </button>
      </div>

      {mode === "group" && <ThriftGroups />}
      {mode === "personal" && (
        <PersonalSavings data={data?.personal} loading={loading} reload={load} />
      )}

      {/* Wallet CTA */}
      <div className="card" style={{
        background: "linear-gradient(135deg, rgba(26,86,219,0.15), rgba(26,86,219,0.05))",
        border: "1px solid rgba(26,86,219,0.3)",
        marginTop: 8,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <div style={{ fontSize: 28 }}>💳</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>Receive contributions to your Wallet</div>
            <div style={{ fontSize: 13, color: "var(--muted)", lineHeight: 1.5 }}>
              Connect a CreditVoice virtual account so participants can pay directly —
              contributions match automatically, no cash handling needed.
            </div>
          </div>
          <button className="btn btn-primary btn-sm" style={{ flexShrink: 0 }} onClick={() => navigate("/wallet")}>
            Connect Wallet
          </button>
        </div>
      </div>
    </>
  );
}
