import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Plus, Trash2, Pencil, Check, X } from "lucide-react";
import { useApp } from "../context/AppContext";
import { apiFetch, apiPost, apiPut, apiDelete } from "../lib/api";
import { nairaFull, dateStr, parseAmt, fmtAmt } from "../lib/format";

// Expenses: money spent running the business, taken off gross profit to give
// net profit. Staff share what they spent as an expense Note; it waits here in
// "To review" until the boss approves it (or says it isn't an expense). Stock
// bought is not an expense — it's already the cost of goods.

// Same period keys as the Dashboard and Insights (AppContext).
const PERIODS = [["TODAY", "Today"], ["WEEK", "This week"], ["MONTH", "This month"],
                 ["YEAR", "This year"], ["", "All time"]];
const today = () => new Date().toISOString().slice(0, 10);

function ExpenseForm({ categories, initial, onSave, onCancel }) {
  const [f, setF] = useState(initial || { amount: "", category: "", spent_on: today(), note: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const set = (k, v) => setF(p => ({ ...p, [k]: v }));

  async function save() {
    if (!parseAmt(f.amount)) return setErr("Enter the amount spent.");
    if (!f.category) return setErr("Choose the type of expense.");
    setBusy(true); setErr("");
    try {
      await onSave({ amount: Math.round(parseAmt(f.amount)), category: f.category,
                     spent_on: f.spent_on || null, note: f.note.trim() || null });
    } catch (e) { setErr(e.message); setBusy(false); }
  }

  return (
    <div className="expense-form">
      <div className="form-row">
        <div className="form-group">
          <label className="form-label">Amount (₦)</label>
          <input inputMode="numeric" value={f.amount} placeholder="0"
            onChange={e => set("amount", fmtAmt(e.target.value))} />
        </div>
        <div className="form-group">
          <label className="form-label">Type</label>
          <select value={f.category} onChange={e => set("category", e.target.value)}>
            <option value="">Choose…</option>
            {categories.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
          </select>
        </div>
        <div className="form-group">
          <label className="form-label">Date spent</label>
          <input type="date" value={f.spent_on} max={today()} onChange={e => set("spent_on", e.target.value)} />
        </div>
      </div>
      <div className="form-group">
        <label className="form-label">Note (optional)</label>
        <input value={f.note} maxLength={300} placeholder="e.g. October shop rent"
          onChange={e => set("note", e.target.value)} />
      </div>
      <div className="form-hint">Buying stock isn't an expense — record it with Add or Adjust stock, so it counts as cost of goods.</div>
      {err && <div className="pos-error" style={{ margin: 0 }}>{err}</div>}
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn btn-primary" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save expense"}</button>
        <button className="btn btn-ghost" onClick={onCancel} disabled={busy}>Cancel</button>
      </div>
    </div>
  );
}

function ReviewRow({ item, categories, onDone }) {
  const [category, setCategory] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function approve() {
    if (!category) return setErr("Choose the type first.");
    setBusy(true); setErr("");
    try {
      await apiPost(`expenses/from-note/${item.note_id}`, { category, spent_on: item.created_at?.slice(0, 10) });
      onDone();
    } catch (e) { setErr(e.message); setBusy(false); }
  }
  async function dismiss() {
    if (!window.confirm("Not a business expense? It won't count, and whoever shared it will be told.")) return;
    setBusy(true);
    try { await apiPost(`expenses/notes/${item.note_id}/dismiss`, {}); onDone(); }
    catch (e) { setErr(e.message); setBusy(false); }
  }

  return (
    <div className="expense-review">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
        <strong>{nairaFull(item.amount)}</strong>
        <span className="text-subtle text-sm">{item.shared_by} · {dateStr(item.created_at)}</span>
      </div>
      <div className="text-sm">{item.body}</div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        <select value={category} onChange={e => setCategory(e.target.value)} style={{ maxWidth: 200 }}>
          <option value="">Type…</option>
          {categories.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
        </select>
        <button className="btn btn-sm btn-primary" onClick={approve} disabled={busy}><Check size={14} /> Approve</button>
        <button className="btn btn-sm btn-ghost" onClick={dismiss} disabled={busy}><X size={14} /> Not an expense</button>
      </div>
      {err && <div className="text-sm" style={{ color: "var(--rose)" }}>{err}</div>}
    </div>
  );
}

export default function Expenses() {
  const { period, setPeriod } = useApp();
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState(null);

  function load() {
    apiFetch("expenses", { period }).then(d => { setData(d); setErr(""); }).catch(e => setErr(e.message));
  }
  useEffect(load, [period]);   // eslint-disable-line react-hooks/exhaustive-deps

  async function remove(e) {
    if (!window.confirm(`Delete this ${nairaFull(e.amount)} expense?`)) return;
    try { await apiDelete(`expenses/${e.id}`); load(); } catch (x) { setErr(x.message); }
  }

  if (err && !data) return <div className="pos-error" style={{ margin: 24 }}>{err}</div>;
  if (!data) return <div className="page-loading">Loading expenses…</div>;
  const cats = data.categories || [];

  return (
    <div style={{ display: "grid", gap: 16, maxWidth: 820 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h2 style={{ margin: "0 0 2px" }}>Expenses</h2>
          <p className="text-subtle text-sm" style={{ margin: 0 }}>
            What it costs to run the business. Taken off gross profit to show your net profit on the{" "}
            <Link to="/dashboard">Dashboard</Link>.
          </p>
        </div>
        <select value={period || ""} onChange={e => setPeriod(e.target.value)} style={{ maxWidth: 180 }}>
          {PERIODS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </div>

      {data.to_review.length > 0 && (
        <div className="card card-body" style={{ display: "grid", gap: 10 }}>
          <div>
            <strong>To review ({data.to_review.length})</strong>
            <div className="text-subtle text-sm">Expenses shared in Notes. Only approved ones count towards net profit.</div>
          </div>
          {data.to_review.map(item => <ReviewRow key={item.note_id} item={item} categories={cats} onDone={load} />)}
        </div>
      )}

      <div className="card card-body" style={{ display: "grid", gap: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
          <div>
            <div className="text-subtle text-sm">Total spent</div>
            <div style={{ fontSize: 24, fontWeight: 800, color: "var(--rose)" }}>{nairaFull(data.total)}</div>
          </div>
          {!adding && (
            <button className="btn btn-primary" onClick={() => { setAdding(true); setEditing(null); }}>
              <Plus size={15} /> Add expense
            </button>
          )}
        </div>
        {adding && (
          <ExpenseForm categories={cats}
            onSave={async body => { await apiPost("expenses", body); setAdding(false); load(); }}
            onCancel={() => setAdding(false)} />
        )}
        {data.by_category.length > 0 && (
          <div className="expense-cats">
            {data.by_category.map(c => (
              <div key={c.category} className="expense-cat">
                <span>{c.label}</span>
                <div className="expense-cat__bar">
                  <div style={{ width: `${Math.max(4, Math.round(100 * c.amount / (data.total || 1)))}%` }} />
                </div>
                <strong>{nairaFull(c.amount)}</strong>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-header"><span className="card-title">All expenses</span></div>
        {data.expenses.length === 0 ? (
          <p className="td-muted card-body">No expenses recorded for this period.</p>
        ) : data.expenses.map(e => (
          editing === e.id ? (
            <div key={e.id} className="card-body">
              <ExpenseForm categories={cats}
                initial={{ amount: fmtAmt(String(e.amount)), category: e.category, spent_on: e.spent_on || today(), note: e.note || "" }}
                onSave={async body => { await apiPut(`expenses/${e.id}`, body); setEditing(null); load(); }}
                onCancel={() => setEditing(null)} />
            </div>
          ) : (
            <div key={e.id} className="expense-row">
              <div style={{ minWidth: 0 }}>
                <strong>{e.category_label}</strong>
                <div className="text-subtle text-sm">
                  {dateStr(e.spent_on)}{e.note ? ` · ${e.note}` : ""}
                  {e.from_note ? " · from a note" : ""}{e.recorded_by ? ` · ${e.recorded_by}` : ""}
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <strong>{nairaFull(e.amount)}</strong>
                <button className="btn btn-ghost btn-sm" aria-label="Edit" onClick={() => { setEditing(e.id); setAdding(false); }}><Pencil size={14} /></button>
                <button className="btn btn-ghost btn-sm" aria-label="Delete" onClick={() => remove(e)}><Trash2 size={14} /></button>
              </div>
            </div>
          )
        ))}
      </div>
    </div>
  );
}
