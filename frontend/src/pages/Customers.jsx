import { useEffect, useState } from "react";
import { Plus, Wallet, History, X, Pencil, Check } from "lucide-react";
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

  return (
    <>
      <StaleDataBanner isStale={isStale} />
      {error && <div style={{ color: "var(--rose)" }}>{error}</div>}
      <div className="card">
        <div className="card-header">
          <span className="card-title">{L.customers} <span className="text-subtle text-sm">({filtered.length})</span></span>
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
        </div>
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
