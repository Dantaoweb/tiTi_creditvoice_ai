import { useEffect, useState } from "react";
import { Plus, Trash2, Lock, Users, Eye } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull } from "../lib/format";
import EmptyState from "../components/EmptyState";
import Skeleton from "../components/Skeleton";

const CATEGORIES = ["memo", "expense", "income", "decision", "goal", "other"];

const VISIBILITY_OPTS = [
  { value: "owner_only", label: "Only me", icon: Lock },
  { value: "partners", label: "Partners", icon: Users },
  { value: "investors", label: "Investors", icon: Eye },
  { value: "all", label: "Everyone", icon: Eye },
];

const CAT_COLORS = {
  memo: "badge-blue",
  expense: "badge-rose",
  income: "badge-green",
  decision: "badge-amber",
  goal: "badge-brand",
  other: "badge-gray",
};

function NoteCard({ note, onDelete }) {
  const [removing, setRemoving] = useState(false);
  const vis = VISIBILITY_OPTS.find(v => v.value === note.visibility) || VISIBILITY_OPTS[0];
  const VisIcon = vis.icon;

  async function del() {
    if (!window.confirm("Delete this note?")) return;
    setRemoving(true);
    try {
      await fetch(`/app/api/notes/${note.id}`, { method: "DELETE", credentials: "include" });
      onDelete(note.id);
    } catch (_) { setRemoving(false); }
  }

  return (
    <div className="card">
      <div className="card-header" style={{ alignItems: "flex-start" }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
            <span className={`badge ${CAT_COLORS[note.category] || "badge-gray"}`} style={{ textTransform: "capitalize" }}>
              {note.category}
            </span>
            <span className="badge badge-gray" style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <VisIcon size={10} /> {vis.label}
            </span>
          </div>
          <div style={{ fontSize: 14, lineHeight: 1.5 }}>{note.body}</div>
          {note.amount != null && (
            <div style={{ marginTop: 6, fontWeight: 700, color: note.category === "expense" ? "var(--rose)" : "var(--brand)" }}>
              {note.category === "expense" ? "−" : "+"}{nairaFull(note.amount)}
            </div>
          )}
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8, flexShrink: 0 }}>
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
            {new Date(note.created_at).toLocaleDateString("en-NG", { day: "numeric", month: "short", year: "numeric" })}
          </span>
          <button className="btn btn-secondary" style={{ fontSize: 11, color: "var(--rose)" }}
            disabled={removing} onClick={del}>
            <Trash2 size={11} /> {removing ? "…" : "Delete"}
          </button>
        </div>
      </div>
    </div>
  );
}

function AddNoteForm({ onDone, onCancel }) {
  const [form, setForm] = useState({
    body: "",
    category: "memo",
    amount: "",
    visibility: "owner_only",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  function set(k, v) { setForm(f => ({ ...f, [k]: v })); }

  async function submit(e) {
    e.preventDefault();
    setErr("");
    if (!form.body.trim()) { setErr("Write something in the note."); return; }
    setBusy(true);
    try {
      await apiPost("notes", {
        body: form.body.trim(),
        category: form.category,
        amount: form.amount ? parseInt(form.amount) : null,
        visibility: form.visibility,
      });
      onDone();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="card">
      <div className="card-title" style={{ marginBottom: 4 }}>Add Note</div>
      <form onSubmit={submit} style={{ display: "grid", gap: 12, marginTop: 12 }}>
        <div className="form-group">
          <label className="form-label">Note *</label>
          <textarea value={form.body} onChange={e => set("body", e.target.value)}
            placeholder="e.g. Paid Emeka ₦10,000 for transport this week"
            rows={3} disabled={busy} style={{ resize: "vertical" }} autoFocus />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div className="form-group">
            <label className="form-label">Category</label>
            <select value={form.category} onChange={e => set("category", e.target.value)} disabled={busy}>
              {CATEGORIES.map(c => (
                <option key={c} value={c} style={{ textTransform: "capitalize" }}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">Amount (optional)</label>
            <input type="number" min="0" value={form.amount}
              onChange={e => set("amount", e.target.value)}
              placeholder="e.g. 10000" disabled={busy} />
          </div>
        </div>

        <div className="form-group">
          <label className="form-label">Visibility</label>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {VISIBILITY_OPTS.map(opt => {
              const Icon = opt.icon;
              return (
                <button key={opt.value} type="button"
                  className={`btn ${form.visibility === opt.value ? "btn-primary" : "btn-secondary"}`}
                  style={{ fontSize: 12 }}
                  onClick={() => set("visibility", opt.value)} disabled={busy}>
                  <Icon size={12} /> {opt.label}
                </button>
              );
            })}
          </div>
          <span className="form-hint">
            {form.visibility === "owner_only" && "Only you can see this note."}
            {form.visibility === "partners" && "You and your co-founders/partners can see this."}
            {form.visibility === "investors" && "You, partners, and investors can see this."}
            {form.visibility === "all" && "All business members can see this."}
          </span>
        </div>

        {err && <div className="login-error">{err}</div>}

        <div style={{ display: "flex", gap: 10 }}>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Saving…" : "Save Note"}
          </button>
          <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={busy}>Cancel</button>
        </div>
      </form>
    </div>
  );
}

export default function Notes() {
  const { user } = useAuth();
  const [notes, setNotes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [filterCat, setFilterCat] = useState("all");

  function load() {
    setLoading(true);
    const params = filterCat !== "all" ? `?category=${filterCat}` : "";
    apiFetch(`notes${params}`).then(d => setNotes(d.notes || [])).catch(() => {}).finally(() => setLoading(false));
  }
  useEffect(load, [filterCat]);

  function removeLocal(id) { setNotes(ns => ns.filter(n => n.id !== id)); }

  const totalExpenses = notes.filter(n => n.category === "expense").reduce((s, n) => s + (n.amount || 0), 0);
  const totalIncome   = notes.filter(n => n.category === "income").reduce((s, n)  => s + (n.amount || 0), 0);

  return (
    <>
      {/* Summary */}
      {notes.length > 0 && (
        <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(3, minmax(130px, 1fr))", marginBottom: 16 }}>
          <div className="card" style={{ gap: 4, padding: "14px 16px" }}>
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Total Notes</div>
            <div style={{ fontSize: 22, fontWeight: 700 }}>{notes.length}</div>
          </div>
          <div className="card" style={{ gap: 4, padding: "14px 16px" }}>
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Recorded Expenses</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: "var(--rose)" }}>{nairaFull(totalExpenses)}</div>
          </div>
          <div className="card" style={{ gap: 4, padding: "14px 16px" }}>
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Recorded Income</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: "var(--brand)" }}>{nairaFull(totalIncome)}</div>
          </div>
        </div>
      )}

      {/* Add / filter row */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16, alignItems: "center" }}>
        {!showAdd && (
          <button className="btn btn-primary" style={{ fontSize: 13 }} onClick={() => setShowAdd(true)}>
            <Plus size={13} /> Add Note
          </button>
        )}
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {["all", ...CATEGORIES].map(c => (
            <button key={c} className={`btn ${filterCat === c ? "btn-primary" : "btn-secondary"}`}
              style={{ fontSize: 12, textTransform: "capitalize" }}
              onClick={() => setFilterCat(c)}>
              {c === "all" ? "All" : c.charAt(0).toUpperCase() + c.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Add form */}
      {showAdd && (
        <AddNoteForm
          onDone={() => { setShowAdd(false); load(); }}
          onCancel={() => setShowAdd(false)}
        />
      )}

      {/* Notes list */}
      {loading ? (
        <div className="card"><Skeleton rows={4} /></div>
      ) : notes.length === 0 ? (
        <div className="card">
          <EmptyState text={filterCat === "all"
            ? "No notes yet. Use the Add Note button to record memos, expenses, or decisions."
            : `No ${filterCat} notes yet.`} />
        </div>
      ) : (
        <div style={{ display: "grid", gap: 10 }}>
          {notes.map(n => <NoteCard key={n.id} note={n} onDelete={removeLocal} />)}
        </div>
      )}
    </>
  );
}
