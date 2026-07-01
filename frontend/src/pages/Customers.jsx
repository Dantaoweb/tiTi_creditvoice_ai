import { useEffect, useState } from "react";
import { Plus, Wallet, History, X, Pencil, Check, Bell, Send, AlertTriangle, TrendingDown } from "lucide-react";
import { useApp } from "../context/AppContext";
import { useAuth } from "../context/AuthContext";
import { apiFetch, apiPost, apiPut } from "../lib/api";
import { nairaFull, dateStr, dateTimeStr } from "../lib/format";
import DataTable from "../components/DataTable";
import { getBizLabels } from "../lib/bizLabels";
import StaleDataBanner from "../components/StaleDataBanner";

// ── Modal wrapper ────────────────────────────────────────────────────────────
function Modal({ title, onClose, children, wide }) {
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className={`modal${wide ? " modal-wide" : ""}`}>
        <div className="modal-header">
          <span className="modal-title">{title}</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

// ── Add customer modal ───────────────────────────────────────────────────────
function AddCustomerModal({ ownerPhone, onClose, onSaved, L }) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  async function save() {
    if (!name.trim()) { setErr(`${L.customerName} is required.`); return; }
    setSaving(true); setErr("");
    try {
      const c = await apiPost("customers", {
        owner_phone: ownerPhone,
        name: name.trim(),
        phone: phone.trim() || null,
      });
      onSaved(c);
      onClose();
    } catch (e) { setErr(e.message); }
    finally { setSaving(false); }
  }

  return (
    <Modal title={L.addCustomer} onClose={onClose}>
      <div className="modal-body">
        <div className="form-group">
          <label className="form-label">{L.customerName} *</label>
          <input value={name} onChange={e => setName(e.target.value)} placeholder={L.customerPlaceholder} autoFocus />
        </div>
        <div className="form-group">
          <label className="form-label">Phone number</label>
          <input value={phone} onChange={e => setPhone(e.target.value)} placeholder="e.g. 2348012345678" />
          <span className="form-hint">Optional — used for WhatsApp reminders</span>
        </div>
        {err && <div className="modal-error">{err}</div>}
      </div>
      <div className="modal-footer">
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={saving}>
          {saving ? "Saving…" : L.addCustomer}
        </button>
      </div>
    </Modal>
  );
}

// ── Record payment modal ─────────────────────────────────────────────────────
function PaymentModal({ customer, onClose, onSaved }) {
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  async function save() {
    const amt = parseInt(amount);
    if (!amt || amt <= 0) { setErr("Enter a valid amount."); return; }
    setSaving(true); setErr("");
    try {
      const result = await apiPost(`customers/${customer.id}/pay`, {
        amount: amt,
        note: note.trim() || null,
      });
      onSaved(result.new_balance);
      onClose();
    } catch (e) { setErr(e.message); }
    finally { setSaving(false); }
  }

  return (
    <Modal title={`Record Payment — ${customer.name}`} onClose={onClose}>
      <div className="modal-body">
        <div className="adjust-current">
          Outstanding balance: <strong className="text-rose">{nairaFull(customer.balance)}</strong>
        </div>
        <div className="form-group">
          <label className="form-label">Payment amount (₦) *</label>
          <input
            type="number" min={1}
            value={amount}
            onChange={e => setAmount(e.target.value)}
            placeholder="0"
            autoFocus
          />
        </div>
        <div className="form-group">
          <label className="form-label">Note</label>
          <input value={note} onChange={e => setNote(e.target.value)} placeholder="e.g. Bank transfer, cash…" />
        </div>
        {err && <div className="modal-error">{err}</div>}
      </div>
      <div className="modal-footer">
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Record Payment"}
        </button>
      </div>
    </Modal>
  );
}

// ── History modal ────────────────────────────────────────────────────────────
function DueDateCell({ tx, onUpdated }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(tx.due_date ? tx.due_date.slice(0, 10) : "");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      const result = await apiPut(`transactions/${tx.id}/due-date`, { due_date: val || null });
      onUpdated(tx.id, result.due_date);
      setEditing(false);
    } catch { /* keep editing open on error */ }
    finally { setSaving(false); }
  }

  if (tx.type !== "BUY") return <td className="td-muted">—</td>;

  if (editing) {
    return (
      <td style={{ whiteSpace: "nowrap" }}>
        <input
          type="date"
          value={val}
          onChange={e => setVal(e.target.value)}
          style={{ fontSize: 12, padding: "2px 4px", width: 130 }}
        />
        <button
          className="btn btn-sm btn-primary"
          onClick={save}
          disabled={saving}
          style={{ marginLeft: 4, padding: "2px 8px", fontSize: 12 }}
        >
          <Check size={12} />
        </button>
        <button
          className="btn btn-sm btn-ghost"
          onClick={() => setEditing(false)}
          style={{ padding: "2px 6px", fontSize: 12 }}
        >
          <X size={12} />
        </button>
      </td>
    );
  }

  return (
    <td className="td-muted" style={{ whiteSpace: "nowrap" }}>
      {tx.due_date ? dateStr(tx.due_date) : "—"}
      <button
        onClick={() => setEditing(true)}
        title="Edit due date"
        style={{ background: "none", border: "none", cursor: "pointer", marginLeft: 4, opacity: 0.5, verticalAlign: "middle" }}
      >
        <Pencil size={11} />
      </button>
    </td>
  );
}

function HistoryModal({ customer, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    apiFetch(`customers/${customer.id}/history`)
      .then(setData)
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false));
  }, [customer.id]);

  function handleDueDateUpdated(txId, newDueDate) {
    setData(prev => ({
      ...prev,
      transactions: prev.transactions.map(tx =>
        tx.id === txId ? { ...tx, due_date: newDueDate } : tx
      ),
    }));
  }

  const TX_COLORS = { BUY: "var(--rose)", PAY: "var(--brand)", SALE: "var(--blue)" };

  return (
    <Modal title={`${customer.name} — Transaction History`} onClose={onClose} wide>
      <div className="modal-body">
        {loading && <div className="td-muted">Loading…</div>}
        {err && <div className="modal-error">{err}</div>}
        {data && (
          <>
            <div className="history-balance">
              Balance: <strong className={data.customer.balance > 0 ? "text-rose" : "text-brand"}>
                {nairaFull(data.customer.balance)}
              </strong>
            </div>
            {data.transactions.length === 0 ? (
              <div className="td-muted" style={{ textAlign: "center", padding: "24px 0" }}>No transactions yet.</div>
            ) : (
              <table className="history-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Type</th>
                    <th>Amount</th>
                    <th>Description</th>
                    <th>Due Date</th>
                    <th>Staff</th>
                  </tr>
                </thead>
                <tbody>
                  {data.transactions.map(tx => (
                    <tr key={tx.id}>
                      <td className="td-muted">{dateTimeStr(tx.created_at)}</td>
                      <td>
                        <span className="badge" style={{ background: TX_COLORS[tx.type] + "1a", color: TX_COLORS[tx.type] }}>
                          {tx.type}
                        </span>
                      </td>
                      <td><strong>{nairaFull(tx.amount)}</strong></td>
                      <td>{tx.product || "—"}</td>
                      <DueDateCell tx={tx} onUpdated={handleDueDateUpdated} />
                      <td className="td-muted">{tx.recorded_by || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>
      <div className="modal-footer">
        <button className="btn btn-ghost" onClick={onClose}>Close</button>
      </div>
    </Modal>
  );
}

// ── Reminder preview modal ───────────────────────────────────────────────────
function ReminderPreviewModal({ reminders, onClose, onSent }) {
  const [sending, setSending] = useState({});
  const [sent, setSent] = useState({});
  const [err, setErr] = useState({});

  async function sendOne(id) {
    setSending(p => ({ ...p, [id]: true }));
    setErr(p => ({ ...p, [id]: null }));
    try {
      await apiPost(`reminders/${id}/send`, {});
      setSent(p => ({ ...p, [id]: true }));
      onSent(id);
    } catch (e) {
      setErr(p => ({ ...p, [id]: e.message }));
    } finally {
      setSending(p => ({ ...p, [id]: false }));
    }
  }

  const pending = reminders.filter(r => r.status !== "SENT");
  const alreadySent = reminders.filter(r => r.status === "SENT");

  return (
    <Modal title="Review Reminders" onClose={onClose} wide>
      <div className="modal-body">
        {pending.length === 0 && alreadySent.length === 0 && (
          <div className="td-muted" style={{ textAlign: "center", padding: "24px 0" }}>
            No reminders in queue. Click "Generate Reminders" to create them.
          </div>
        )}
        {pending.length > 0 && (
          <>
            <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8 }}>
              Pending ({pending.length}) — Review each message before sending
            </div>
            {pending.map(r => (
              <div key={r.id} className="reminder-card">
                <div className="reminder-card-header">
                  <div>
                    <strong>{r.customer_name}</strong>
                    <span className="td-muted" style={{ marginLeft: 8 }}>{r.customer_phone || "no phone"}</span>
                  </div>
                  <span className="text-rose" style={{ fontWeight: 600 }}>{nairaFull(r.balance)}</span>
                </div>
                <div className="reminder-card-msg">{r.message_text}</div>
                {err[r.id] && <div className="modal-error" style={{ marginBottom: 6 }}>{err[r.id]}</div>}
                {sent[r.id] ? (
                  <div style={{ color: "var(--brand)", fontSize: 13, fontWeight: 600 }}>✓ Sent</div>
                ) : (
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={() => sendOne(r.id)}
                    disabled={sending[r.id] || !r.customer_phone}
                    title={!r.customer_phone ? "No phone number for this customer" : ""}
                  >
                    <Send size={13} /> {sending[r.id] ? "Sending…" : "Send"}
                  </button>
                )}
              </div>
            ))}
          </>
        )}
        {alreadySent.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <div style={{ fontWeight: 600, fontSize: 13, color: "var(--muted)", marginBottom: 8 }}>
              Already sent ({alreadySent.length})
            </div>
            {alreadySent.map(r => (
              <div key={r.id} className="reminder-card reminder-card-sent">
                <div className="reminder-card-header">
                  <span>{r.customer_name}</span>
                  <span className="text-subtle">{nairaFull(r.balance)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="modal-footer">
        <button className="btn btn-ghost" onClick={onClose}>Close</button>
      </div>
    </Modal>
  );
}

// ── Debtors tab ──────────────────────────────────────────────────────────────
function DebtorsTab({ debtors, onPay, onHistory, onBalanceUpdate }) {
  const [mode, setMode] = useState(null);   // "review" | "auto" | null (loading)
  const [reminders, setReminders] = useState([]);
  const [showPreview, setShowPreview] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genMsg, setGenMsg] = useState("");
  const [savingMode, setSavingMode] = useState(false);

  const now = new Date();

  useEffect(() => {
    apiFetch("automation")
      .then(d => {
        const rem = d.reminder || {};
        if (rem.auto_send_enabled) setMode("auto");
        else setMode("review");
      })
      .catch(() => setMode("review"));
  }, []);

  async function saveMode(newMode) {
    setSavingMode(true);
    try {
      await apiPost("automation", {
        reminder_auto_send_enabled: newMode === "auto",
        reminder_preview_enabled: newMode === "review",
      });
      setMode(newMode);
    } catch { /* keep current */ }
    finally { setSavingMode(false); }
  }

  async function loadReminders() {
    const data = await apiFetch("reminders");
    setReminders(data.reminders || []);
    return data.reminders || [];
  }

  async function handleGenerate() {
    setGenerating(true);
    setGenMsg("");
    try {
      const result = await apiPost("reminders/run", {});
      const loaded = await loadReminders();
      if (mode === "auto") {
        const sent = loaded.filter(r => r.status === "SENT").length;
        setGenMsg(`${result.sent || sent} reminder${(result.sent || sent) !== 1 ? "s" : ""} sent automatically.`);
      } else {
        const pending = loaded.filter(r => r.status !== "SENT").length;
        setGenMsg(pending > 0 ? `${pending} reminder${pending !== 1 ? "s" : ""} queued. Review and send below.` : "No new reminders generated.");
        if (pending > 0) setShowPreview(true);
      }
    } catch (e) {
      setGenMsg(`Error: ${e.message}`);
    } finally {
      setGenerating(false);
    }
  }

  async function openReview() {
    await loadReminders();
    setShowPreview(true);
  }

  function daysOverdue(nextDue) {
    if (!nextDue) return null;
    const due = new Date(nextDue);
    const diff = Math.floor((now - due) / 86400000);
    return diff > 0 ? diff : null;
  }

  const totalOwed = debtors.reduce((s, d) => s + (d.balance || 0), 0);
  const numOverdue = debtors.filter(d => d.has_overdue).length;
  const pendingCount = reminders.filter(r => r.status !== "SENT").length;

  return (
    <div className="debtors-tab">
      {/* Summary strip */}
      <div className="debtors-summary">
        <div className="debtors-stat">
          <div className="debtors-stat-value text-rose">{nairaFull(totalOwed)}</div>
          <div className="debtors-stat-label">Total Outstanding</div>
        </div>
        <div className="debtors-stat">
          <div className="debtors-stat-value">{debtors.length}</div>
          <div className="debtors-stat-label">Debtors</div>
        </div>
        <div className="debtors-stat">
          <div className="debtors-stat-value" style={{ color: numOverdue > 0 ? "var(--rose)" : "var(--muted)" }}>
            {numOverdue}
          </div>
          <div className="debtors-stat-label">Overdue</div>
        </div>
      </div>

      {/* Reminder controls */}
      <div className="debtors-reminder-bar">
        <div className="debtors-mode-wrap">
          <span style={{ fontSize: 13, color: "var(--muted)", marginRight: 8 }}>Reminder mode:</span>
          <div className="debtors-mode-pills">
            <button
              className={`debtors-mode-pill${mode === "review" ? " active" : ""}`}
              onClick={() => mode !== "review" && saveMode("review")}
              disabled={savingMode || mode === null}
            >
              Review
            </button>
            <button
              className={`debtors-mode-pill${mode === "auto" ? " active" : ""}`}
              onClick={() => mode !== "auto" && saveMode("auto")}
              disabled={savingMode || mode === null}
            >
              Automatic
            </button>
          </div>
          {mode === "review" && (
            <span className="form-hint" style={{ marginLeft: 8 }}>
              You review before sending
            </span>
          )}
          {mode === "auto" && (
            <span className="form-hint" style={{ marginLeft: 8 }}>
              Sends immediately
            </span>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
          {mode === "review" && pendingCount > 0 && (
            <button className="btn btn-ghost btn-sm" onClick={openReview}>
              <Bell size={13} /> Review ({pendingCount})
            </button>
          )}
          <button
            className="btn btn-primary btn-sm"
            onClick={handleGenerate}
            disabled={generating || debtors.length === 0}
          >
            <Bell size={13} />
            {generating ? "Generating…" : mode === "auto" ? "Send Reminders" : "Generate Reminders"}
          </button>
        </div>
      </div>

      {genMsg && (
        <div
          style={{
            padding: "8px 12px",
            background: genMsg.startsWith("Error") ? "var(--rose-bg, #fff5f5)" : "var(--brand-bg, #f0fff4)",
            color: genMsg.startsWith("Error") ? "var(--rose)" : "var(--brand)",
            borderRadius: 8,
            fontSize: 13,
            marginBottom: 12,
          }}
        >
          {genMsg}
        </div>
      )}

      {/* Debtor table */}
      {debtors.length === 0 ? (
        <div className="td-muted" style={{ textAlign: "center", padding: "48px 0" }}>
          No customers with outstanding balance.
        </div>
      ) : (
        <div className="debtors-table-wrap">
          <table className="history-table debtors-table">
            <thead>
              <tr>
                <th style={{ width: 36 }}>#</th>
                <th>Name</th>
                <th>Balance Owed</th>
                <th>Next Due</th>
                <th>Days Overdue</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {debtors.map((d, i) => {
                const overdueDays = daysOverdue(d.next_due);
                const isOverdue = d.has_overdue;
                return (
                  <tr key={d.id} className={isOverdue ? "row-overdue" : ""}>
                    <td className="td-muted" style={{ fontWeight: 700 }}>{i + 1}</td>
                    <td>
                      <strong className="td-strong">{(d.name || "—").replace(/\b\w/g, c => c.toUpperCase())}</strong>
                      {d.phone && <div className="td-muted" style={{ fontSize: 11 }}>{d.phone}</div>}
                    </td>
                    <td>
                      <span className="text-rose" style={{ fontWeight: 700 }}>{nairaFull(d.balance)}</span>
                    </td>
                    <td className="td-muted" style={{ whiteSpace: "nowrap" }}>
                      {d.next_due ? (
                        <span style={isOverdue ? { color: "var(--rose)", fontWeight: 600 } : {}}>
                          {dateStr(d.next_due)}
                        </span>
                      ) : "—"}
                    </td>
                    <td>
                      {overdueDays !== null ? (
                        <span className="badge" style={{ background: "var(--rose)1a", color: "var(--rose)", fontWeight: 600 }}>
                          <AlertTriangle size={11} style={{ marginRight: 3 }} />
                          {overdueDays}d
                        </span>
                      ) : isOverdue ? (
                        <span className="badge" style={{ background: "var(--rose)1a", color: "var(--rose)" }}>Overdue</span>
                      ) : (
                        <span className="td-muted">—</span>
                      )}
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }}>
                        <button
                          className="btn btn-ghost btn-xs"
                          title="View history"
                          onClick={() => onHistory(d)}
                        >
                          <History size={13} />
                        </button>
                        <button
                          className="btn btn-primary btn-xs"
                          title="Record payment"
                          onClick={() => onPay(d)}
                        >
                          <Wallet size={13} /> Pay
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {showPreview && (
        <ReminderPreviewModal
          reminders={reminders}
          onClose={() => setShowPreview(false)}
          onSent={id => setReminders(prev =>
            prev.map(r => r.id === id ? { ...r, status: "SENT" } : r)
          )}
        />
      )}
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────
export default function Customers() {
  const { ownerPhone } = useApp();
  const { user } = useAuth();
  const L = getBizLabels(user?.menu_group);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isStale, setIsStale] = useState(false);
  const [search, setSearch] = useState("");
  const [activeTab, setActiveTab] = useState("all");
  const [showAdd, setShowAdd] = useState(false);
  const [payCustomer, setPayCustomer] = useState(null);
  const [histCustomer, setHistCustomer] = useState(null);

  function load() {
    setLoading(true);
    apiFetch("customers", { owner_phone: ownerPhone })
      .then(d => { setRows(d.customers); setIsStale(!navigator.onLine); })
      .catch(e => { setError(e.message); setIsStale(true); })
      .finally(() => setLoading(false));
  }

  useEffect(load, [ownerPhone]);

  function updateBalance(customerId, newBalance) {
    setRows(prev => prev.map(r => r.id === customerId ? { ...r, balance: newBalance } : r));
  }

  const filtered = search
    ? rows.filter(r =>
        (r.name || "").toLowerCase().includes(search.toLowerCase()) ||
        (r.phone || "").includes(search)
      )
    : rows;

  const debtors = [...rows]
    .filter(r => r.balance > 0)
    .sort((a, b) => b.balance - a.balance);

  const debtorCount = debtors.length;

  return (
    <>
      <StaleDataBanner isStale={isStale} />
      {error && <div style={{ color: "var(--rose)" }}>{error}</div>}
      <div className="card">
        {/* Tab bar + header */}
        <div className="card-header" style={{ flexDirection: "column", gap: 0, padding: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "14px 16px 0" }}>
            <span className="card-title" style={{ flex: 1 }}>
              {activeTab === "all"
                ? <>{L.customers} <span className="text-subtle text-sm">({filtered.length})</span></>
                : <>Debtors <span className="text-subtle text-sm">({debtorCount})</span></>
              }
            </span>
            {activeTab === "all" && (
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 1, minWidth: 0 }}>
                <input
                  placeholder="Search name or phone…"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  style={{ flex: 1, minWidth: 0 }}
                />
                <button className="btn btn-primary btn-sm" onClick={() => setShowAdd(true)}>
                  <Plus size={14} /> {L.addCustomer}
                </button>
              </div>
            )}
          </div>

          {/* Tabs */}
          <div className="page-tabs" style={{ marginTop: 10 }}>
            <button
              className={`page-tab${activeTab === "all" ? " active" : ""}`}
              onClick={() => setActiveTab("all")}
            >
              All Customers
            </button>
            <button
              className={`page-tab${activeTab === "debtors" ? " active" : ""}`}
              onClick={() => setActiveTab("debtors")}
            >
              <TrendingDown size={13} style={{ marginRight: 4 }} />
              Debtors
              {debtorCount > 0 && (
                <span className="tab-badge">{debtorCount}</span>
              )}
            </button>
          </div>
        </div>

        {/* Tab content */}
        {activeTab === "all" ? (
          <DataTable
            loading={loading}
            rows={filtered}
            emptyText={L.noCustomers}
            rowClass={r => r.balance > 0 ? "has-balance" : ""}
            columns={[
              {
                key: "name", label: "Name", sortKey: "name",
                render: r => <strong className="td-strong">{(r.name || "—").replace(/\b\w/g, c => c.toUpperCase())}</strong>,
              },
              { key: "phone", label: "Phone", render: r => <span className="td-mono">{r.phone || "—"}</span> },
              {
                key: "balance", label: "Balance", sortKey: "balance",
                render: r => r.balance > 0
                  ? <span className="text-rose font-bold">{nairaFull(r.balance)}</span>
                  : <span className="text-subtle">{nairaFull(r.balance)}</span>,
              },
              { key: "created_at", label: "Joined", render: r => <span className="td-muted">{dateStr(r.created_at)}</span> },
              {
                key: "actions", label: "",
                render: r => (
                  <div style={{ display: "flex", gap: 6 }}>
                    <button
                      className="btn btn-ghost btn-xs"
                      title="View history"
                      onClick={() => setHistCustomer(r)}
                    >
                      <History size={13} />
                    </button>
                    {r.balance > 0 && (
                      <button
                        className="btn btn-primary btn-xs"
                        title="Record payment"
                        onClick={() => setPayCustomer(r)}
                      >
                        <Wallet size={13} /> Pay
                      </button>
                    )}
                  </div>
                ),
              },
            ]}
          />
        ) : (
          <div style={{ padding: "16px" }}>
            <DebtorsTab
              debtors={debtors}
              onPay={c => setPayCustomer(c)}
              onHistory={c => setHistCustomer(c)}
              onBalanceUpdate={updateBalance}
            />
          </div>
        )}
      </div>

      {showAdd && (
        <AddCustomerModal
          ownerPhone={ownerPhone}
          onClose={() => setShowAdd(false)}
          onSaved={c => setRows(prev => [{ ...c, created_at: new Date().toISOString() }, ...prev])}
          L={L}
        />
      )}

      {payCustomer && (
        <PaymentModal
          customer={payCustomer}
          onClose={() => setPayCustomer(null)}
          onSaved={newBalance => updateBalance(payCustomer.id, newBalance)}
        />
      )}

      {histCustomer && (
        <HistoryModal
          customer={histCustomer}
          onClose={() => setHistCustomer(null)}
        />
      )}
    </>
  );
}
