import { useEffect, useState } from "react";
import {
  GraduationCap, Users, Wallet, Settings, AlertCircle, Check, Plus, BookOpen, Bell, Trash2,
} from "lucide-react";
import { apiDelete, apiFetch, apiPost, apiPut } from "../lib/api";
import { nairaFull } from "../lib/format";
import MetricCard from "../components/MetricCard";

/**
 * The school's own screen: take fees, register pupils, and set up what each
 * class owes.
 *
 * Ordered the way a bursar's day runs — collecting first, because that is what
 * happens two hundred times before lunch, and setup last, because it happens
 * once a term.
 */

const TABS = [
  { key: "collect", label: "Collect fees", icon: Wallet },
  { key: "pupils", label: "Pupils", icon: Users },
  { key: "fees", label: "This term", icon: GraduationCap },
  { key: "setup", label: "Setup", icon: Settings },
];

const toInt = v => {
  const n = parseInt(String(v).replace(/[^\d]/g, ""), 10);
  return isNaN(n) ? 0 : n;
};

export default function School() {
  const [tab, setTab] = useState("collect");
  const [setup, setSetup] = useState(null);
  const [pupils, setPupils] = useState([]);
  const [err, setErr] = useState("");
  const [flash, setFlash] = useState("");

  function loadSetup() {
    apiFetch("school/setup").then(setSetup).catch(e => setErr(e.message));
  }
  function loadPupils() {
    apiFetch("school/pupils").then(d => setPupils(d.pupils || [])).catch(() => {});
  }
  useEffect(() => { loadSetup(); loadPupils(); }, []);

  function announce(message) {
    setFlash(message);
    setTimeout(() => setFlash(""), 4000);
  }

  const hasTerm = !!setup?.current_term_id;

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {err && (
        <div className="card card-body" style={{ color: "var(--rose)", display: "flex", gap: 8 }}>
          <AlertCircle size={16} /> {err}
        </div>
      )}
      {flash && (
        <div className="card card-body" style={{ color: "#16a34a", display: "flex", gap: 8 }}>
          <Check size={16} /> {flash}
        </div>
      )}

      {setup && !hasTerm && (
        <div className="card card-body" style={{ display: "grid", gap: 8 }}>
          <strong>Start your school year</strong>
          <span className="text-subtle text-sm">
            Fees are owed per term, so nothing can be charged until a session is open.
            Go to <b>Setup</b> to create one — it takes a minute.
          </span>
        </div>
      )}

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {TABS.map(({ key, label, icon: Icon }) => (
          <button key={key} onClick={() => setTab(key)}
            className={`btn btn-sm ${tab === key ? "btn-primary" : "btn-ghost"}`}
            style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>

      {tab === "collect" && (
        <Collect setup={setup} pupils={pupils} onDone={() => { loadPupils(); }}
          announce={announce} setErr={setErr} />
      )}
      {tab === "pupils" && (
        <Pupils setup={setup} pupils={pupils} reload={loadPupils}
          announce={announce} setErr={setErr} />
      )}
      {tab === "fees" && <ThisTerm setup={setup} announce={announce} setErr={setErr} />}
      {tab === "setup" && (
        <Setup setup={setup} reload={loadSetup} announce={announce} setErr={setErr} />
      )}
    </div>
  );
}

// ── Collecting ──────────────────────────────────────────────────────────────
// The bursar's two hundred times a day: find the pupil, see what they owe,
// take the money. Charging a textbook sits here too, because it happens at the
// same desk.

function Collect({ setup, pupils, onDone, announce, setErr }) {
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState(null);
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [statement, setStatement] = useState(null);

  const books = (setup?.fee_items || []).filter(i => i.is_optional && i.is_active);
  const matches = search.trim()
    ? pupils.filter(p =>
        p.name.toLowerCase().includes(search.trim().toLowerCase()) ||
        (p.admission_no || "").toLowerCase().includes(search.trim().toLowerCase()))
      .slice(0, 8)
    : [];

  function pick(pupil) {
    setPicked(pupil);
    setSearch("");
    setStatement(null);
    apiFetch(`school/pupils/${pupil.customer_id}/statement`)
      .then(setStatement).catch(() => {});
  }

  async function takePayment() {
    const value = toInt(amount);
    if (!picked || value <= 0) return;
    setBusy(true);
    try {
      const res = await apiPost("school/payments", {
        customer_id: picked.customer_id, amount: value,
      });
      announce(`${picked.name}: ${nairaFull(value)} received. Balance ${nairaFull(res.balance)}.`);
      setAmount("");
      setPicked({ ...picked, balance: res.balance });
      onDone();
      apiFetch(`school/pupils/${picked.customer_id}/statement`).then(setStatement).catch(() => {});
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function giveBook(item) {
    if (!picked) return;
    try {
      await apiPost("school/charge", {
        customer_id: picked.customer_id,
        items: [{ fee_item_id: item.id, quantity: 1 }],
      });
      announce(`${item.name} charged to ${picked.name}.`);
      onDone();
      apiFetch(`school/pupils/${picked.customer_id}/statement`).then(setStatement).catch(() => {});
    } catch (e) { setErr(e.message); }
  }

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="card">
        <div className="card-header"><span className="card-title">Find a pupil</span></div>
        <div className="card-body" style={{ display: "grid", gap: 10 }}>
          <input value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Name or admission number" autoFocus />
          {matches.map(p => (
            <button key={p.customer_id} className="btn btn-ghost"
              style={{ justifyContent: "space-between", display: "flex" }}
              onClick={() => pick(p)}>
              <span>{p.name} <span className="text-subtle text-sm">· {p.class_name}</span></span>
              <span className={p.balance > 0 ? "text-rose" : "text-subtle"}>
                {p.balance > 0 ? nairaFull(p.balance) : "paid up"}
              </span>
            </button>
          ))}
          {search.trim() && matches.length === 0 && (
            <span className="text-subtle text-sm">No pupil by that name.</span>
          )}
        </div>
      </div>

      {picked && (
        <div className="card">
          <div className="card-header" style={{ flexWrap: "wrap", gap: 8 }}>
            <span className="card-title">
              {picked.name}
              <span className="text-subtle text-sm"> · {picked.class_name}
                {picked.admission_no ? ` · ${picked.admission_no}` : ""}</span>
            </span>
            <span className={picked.balance > 0 ? "badge badge-rose" : "badge badge-green"}>
              {picked.balance > 0 ? `Owes ${nairaFull(picked.balance)}` : "Paid up"}
            </span>
          </div>
          <div className="card-body" style={{ display: "grid", gap: 12 }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <input inputMode="numeric" value={amount} style={{ flex: "1 1 160px" }}
                onChange={e => setAmount(e.target.value)} placeholder="Amount paid" />
              <button className="btn btn-primary" disabled={busy || toInt(amount) <= 0}
                onClick={takePayment}>
                {busy ? "Saving…" : "Record payment"}
              </button>
              {picked.balance > 0 && (
                <button className="btn btn-ghost" onClick={() => setAmount(String(picked.balance))}>
                  Pay all
                </button>
              )}
            </div>

            {books.length > 0 && (
              <div>
                <div className="text-subtle text-sm" style={{ marginBottom: 6 }}>
                  Books and extras — charged only when the pupil takes one:
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {books.map(item => (
                    <button key={item.id} className="btn btn-ghost btn-sm"
                      onClick={() => giveBook(item)}
                      style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <BookOpen size={13} /> {item.name}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {statement && (
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Date</th><th>Entry</th><th>Amount</th></tr></thead>
                  <tbody>
                    {statement.entries.slice(0, 8).map(e => (
                      <tr key={e.id}>
                        <td className="td-muted" style={{ fontSize: 11 }}>
                          {e.date ? e.date.slice(0, 10) : "—"}
                        </td>
                        <td>
                          {e.description}
                          {e.items.length > 0 && (
                            <div className="td-muted" style={{ fontSize: 11 }}>
                              {e.items.map(i => i.name).join(", ")}
                            </div>
                          )}
                        </td>
                        <td className={e.kind === "payment" ? "text-green" : ""}>
                          {e.kind === "payment" ? "−" : "+"}{nairaFull(e.amount)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Pupils ──────────────────────────────────────────────────────────────────
// Registration draws itself from the fields this school decided to keep, so
// nothing here knows what "best colour" is.

function Pupils({ setup, pupils, reload, announce, setErr }) {
  const [fields, setFields] = useState([]);
  const [form, setForm] = useState({ name: "", class_id: "", parent_name: "", parent_phone: "" });
  const [details, setDetails] = useState({});
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [feesFor, setFeesFor] = useState(null);
  const [classFilter, setClassFilter] = useState("");

  useEffect(() => {
    apiFetch("school/pupil-fields").then(d => setFields(d.fields || [])).catch(() => {});
  }, []);

  const shown = classFilter ? pupils.filter(p => p.class_id === classFilter) : pupils;

  function startNew() {
    setEditingId(null);
    setForm({ name: "", class_id: classFilter || "", parent_name: "", parent_phone: "" });
    setDetails({});
    setOpen(true);
  }

  async function startEdit(pupil) {
    setEditingId(pupil.customer_id);
    setForm({
      name: pupil.name, class_id: pupil.class_id || "",
      parent_name: pupil.parent_name || "", parent_phone: pupil.parent_phone || "",
      admission_no: pupil.admission_no || "",
    });
    setOpen(true);
    // The pupil's own answers come from their statement, so the form opens
    // filled in rather than asking for everything again.
    try {
      const statement = await apiFetch(`school/pupils/${pupil.customer_id}/statement`);
      const filled = {};
      (statement.details || []).forEach(d => { filled[d.key] = d.value; });
      setDetails(filled);
    } catch { /* an edit with blank details is still better than no edit */ }
  }

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    try {
      if (editingId) {
        const res = await apiPut(`school/pupils/${editingId}`, { ...form, details });
        announce(`${res.name} updated.`);
      } else {
        const res = await apiPost("school/pupils", { ...form, details });
        announce(`${res.name} registered — admission number ${res.admission_no}.`);
      }
      setForm({ name: "", class_id: form.class_id, parent_name: "", parent_phone: "" });
      setDetails({});
      setOpen(false);
      setEditingId(null);
      reload();
    } catch (e2) { setErr(e2.message); }
    finally { setBusy(false); }
  }

  async function remove(pupil) {
    if (!window.confirm(`Remove ${pupil.name} from the register?`)) return;
    try {
      const res = await apiDelete(`school/pupils/${pupil.customer_id}`);
      announce(res.deleted ? `${pupil.name} removed.`
                           : `${pupil.name} marked as left. ${res.reason}`);
      reload();
    } catch (e) { setErr(e.message); }
  }

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="card">
        <div className="card-header" style={{ flexWrap: "wrap", gap: 8 }}>
          <span className="card-title">Pupils <span className="text-subtle text-sm">({shown.length})</span></span>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <select value={classFilter} onChange={e => setClassFilter(e.target.value)}>
              <option value="">All classes</option>
              {(setup?.classes || []).map(c => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
            <button className="btn btn-primary btn-sm" onClick={startNew}
              style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <Plus size={14} /> Register pupil
            </button>
          </div>
        </div>

        {open && (
          <form onSubmit={save} className="card-body" style={{ display: "grid", gap: 10 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
              <strong>{editingId ? "Edit pupil" : "New pupil"}</strong>
              <button type="button" className="btn btn-ghost btn-xs"
                onClick={() => { setOpen(false); setEditingId(null); }}>Cancel</button>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <div className="form-group" style={{ margin: 0, flex: "1 1 200px" }}>
                <label className="form-label">Pupil's name *</label>
                <input value={form.name} required
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
              </div>
              <div className="form-group" style={{ margin: 0, flex: "1 1 160px" }}>
                <label className="form-label">Class</label>
                <select value={form.class_id}
                  onChange={e => setForm(f => ({ ...f, class_id: e.target.value }))}>
                  <option value="">Choose a class</option>
                  {(setup?.classes || []).map(c => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <div className="form-group" style={{ margin: 0, flex: "1 1 180px" }}>
                <label className="form-label">Parent / guardian</label>
                <input value={form.parent_name}
                  onChange={e => setForm(f => ({ ...f, parent_name: e.target.value }))} />
              </div>
              <div className="form-group" style={{ margin: 0, flex: "1 1 180px" }}>
                <label className="form-label">Parent's phone</label>
                <input value={form.parent_phone}
                  onChange={e => setForm(f => ({ ...f, parent_phone: e.target.value }))} />
              </div>
            </div>

            {/* This school's own questions — see Setup to change them. */}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {fields.map(field => (
                <div className="form-group" key={field.key}
                  style={{ margin: 0, flex: "1 1 160px" }}>
                  <label className="form-label">
                    {field.label}{field.is_required ? " *" : ""}
                  </label>
                  {field.field_type === "choice" ? (
                    <select value={details[field.key] || ""}
                      onChange={e => setDetails(d => ({ ...d, [field.key]: e.target.value }))}>
                      <option value="">—</option>
                      {field.options.map(o => <option key={o} value={o}>{o}</option>)}
                    </select>
                  ) : (
                    <input
                      type={field.field_type === "date" ? "date" : "text"}
                      inputMode={field.field_type === "number" ? "numeric" : undefined}
                      value={details[field.key] || ""}
                      onChange={e => setDetails(d => ({ ...d, [field.key]: e.target.value }))} />
                  )}
                </div>
              ))}
            </div>

            <div>
              <button className="btn btn-primary" disabled={busy || !form.name.trim()}>
                {busy ? "Saving…" : editingId ? "Save changes" : "Register"}
              </button>
            </div>
          </form>
        )}

        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>Pupil</th><th>Class</th><th>Admission no.</th><th>Parent</th><th>Balance</th><th></th></tr>
            </thead>
            <tbody>
              {shown.length === 0 ? (
                <tr><td colSpan={6} className="td-muted">No pupils yet.</td></tr>
              ) : shown.map(p => (
                <tr key={p.customer_id}>
                  <td><strong>{p.name}</strong></td>
                  <td>{p.class_name}</td>
                  <td className="td-muted" style={{ fontSize: 12 }}>{p.admission_no || "—"}</td>
                  <td className="td-muted" style={{ fontSize: 12 }}>
                    {p.parent_name || "—"}
                    {p.parent_phone ? <div>{p.parent_phone}</div> : null}
                  </td>
                  <td className={p.balance > 0 ? "text-rose" : ""}>
                    {p.balance > 0 ? nairaFull(p.balance) : "—"}
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button className="btn btn-ghost btn-xs"
                        onClick={() => setFeesFor(feesFor === p.customer_id ? null : p)}>
                        Fees
                      </button>
                      <button className="btn btn-ghost btn-xs" onClick={() => startEdit(p)}>
                        Edit
                      </button>
                      <button className="btn btn-ghost btn-xs text-rose"
                        onClick={() => remove(p)}>
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {feesFor && (
        <PupilFees pupil={feesFor} setup={setup} onClose={() => setFeesFor(null)}
          announce={announce} setErr={setErr} />
      )}
    </div>
  );
}

// ── What one child actually pays ────────────────────────────────────────────
// The class fee is a default, not a rule. Staff children, scholarship pupils,
// siblings on a discount and families having a hard term all stay on the
// register and are billed what was agreed.

function PupilFees({ pupil, setup, onClose, announce, setErr }) {
  const [preview, setPreview] = useState(null);
  const [form, setForm] = useState({ kind: "EXEMPT", value: "", fee_item_id: "",
                                     term_id: "", reason: "" });
  const [busy, setBusy] = useState(false);

  function load() {
    apiFetch(`school/pupils/${pupil.customer_id}/fees`)
      .then(d => setPreview(d.preview)).catch(e => setErr(e.message));
  }
  useEffect(load, [pupil.customer_id]);

  async function save() {
    setBusy(true);
    try {
      await apiPost("school/exemptions", {
        customer_id: pupil.customer_id,
        kind: form.kind,
        value: toInt(form.value),
        fee_item_id: form.fee_item_id || null,
        term_id: form.term_id || null,
        reason: form.reason || null,
      });
      announce(`${pupil.name}'s fees updated.`);
      setForm({ kind: "EXEMPT", value: "", fee_item_id: "", term_id: "", reason: "" });
      load();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function drop(id) {
    try {
      await apiDelete(`school/exemptions/${id}`);
      announce("Arrangement removed — back to the class fee.");
      load();
    } catch (e) { setErr(e.message); }
  }

  const needsValue = form.kind !== "EXEMPT";

  return (
    <div className="card">
      <div className="card-header" style={{ flexWrap: "wrap", gap: 8 }}>
        <span className="card-title">{pupil.name} — fees this term</span>
        <button className="btn btn-ghost btn-xs" onClick={onClose}>Close</button>
      </div>
      <div className="card-body" style={{ display: "grid", gap: 12 }}>
        {!preview ? (
          <span className="text-subtle text-sm">No term is open yet.</span>
        ) : (
          <>
            <div className="table-scroll">
              <table>
                <thead><tr><th>Item</th><th>Class fee</th><th>This pupil</th><th>Why</th></tr></thead>
                <tbody>
                  {preview.lines.map(l => (
                    <tr key={l.fee_item_id}>
                      <td>{l.name}</td>
                      <td className="td-muted">{nairaFull(l.class_amount)}</td>
                      <td className={l.amount < l.class_amount ? "text-green" : ""}>
                        {nairaFull(l.amount)}
                      </td>
                      <td className="td-muted" style={{ fontSize: 12 }}>
                        {l.exempt_reason || "—"}
                      </td>
                    </tr>
                  ))}
                  <tr>
                    <td><strong>Total</strong></td>
                    <td className="td-muted">{nairaFull(preview.class_total)}</td>
                    <td><strong>{nairaFull(preview.pupil_total)}</strong></td>
                    <td className="td-muted" style={{ fontSize: 12 }}>
                      {preview.excused > 0 ? `${nairaFull(preview.excused)} excused` : ""}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            {preview.exemptions.length > 0 && (
              <div style={{ display: "grid", gap: 6 }}>
                {preview.exemptions.map(x => (
                  <div key={x.id} style={{ display: "flex", gap: 8, alignItems: "center",
                                           fontSize: 13 }}>
                    <span style={{ flex: 1 }}>
                      {x.kind === "EXEMPT" ? "Pays nothing"
                        : x.kind === "PERCENT" ? `${x.value}% off`
                        : x.kind === "AMOUNT" ? `${nairaFull(x.value)} off the bill`
                        : `Pays ${nairaFull(x.value)}`}
                      {x.fee_item_id ? " · one item only" : " · all fees"}
                      {x.term_id ? " · this term" : " · every term"}
                      {x.reason ? ` — ${x.reason}` : ""}
                    </span>
                    <button className="btn btn-ghost btn-xs text-rose" onClick={() => drop(x.id)}>
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
              <div className="form-group" style={{ margin: 0, flex: "1 1 150px" }}>
                <label className="form-label">Arrangement</label>
                <select value={form.kind}
                  onChange={e => setForm(f => ({ ...f, kind: e.target.value }))}>
                  <option value="EXEMPT">Pays nothing</option>
                  <option value="PERCENT">Percentage off</option>
                  <option value="AMOUNT">Amount off the bill</option>
                  <option value="FIXED">Pays an agreed amount</option>
                </select>
              </div>
              {needsValue && (
                <div className="form-group" style={{ margin: 0, flex: "0 1 110px" }}>
                  <label className="form-label">
                    {form.kind === "PERCENT" ? "Percent" : "Amount"}
                  </label>
                  <input inputMode="numeric" value={form.value}
                    onChange={e => setForm(f => ({ ...f, value: e.target.value }))} />
                </div>
              )}
              <div className="form-group" style={{ margin: 0, flex: "1 1 150px" }}>
                <label className="form-label">Applies to</label>
                <select value={form.fee_item_id}
                  onChange={e => setForm(f => ({ ...f, fee_item_id: e.target.value }))}>
                  <option value="">All fees</option>
                  {(setup?.fee_items || []).map(i => (
                    <option key={i.id} value={i.id}>{i.name} only</option>
                  ))}
                </select>
              </div>
              <div className="form-group" style={{ margin: 0, flex: "1 1 150px" }}>
                <label className="form-label">For how long</label>
                <select value={form.term_id}
                  onChange={e => setForm(f => ({ ...f, term_id: e.target.value }))}>
                  <option value="">Every term</option>
                  <option value={setup?.current_term_id || ""}>This term only</option>
                </select>
              </div>
              <div className="form-group" style={{ margin: 0, flex: "1 1 170px" }}>
                <label className="form-label">Reason</label>
                <input value={form.reason} placeholder="Staff child, scholarship…"
                  onChange={e => setForm(f => ({ ...f, reason: e.target.value }))} />
              </div>
              <button className="btn btn-primary" disabled={busy} onClick={save}>
                {busy ? "Saving…" : "Save"}
              </button>
            </div>
            <span className="form-hint">
              Changes apply the next time this term is charged. Fees already billed stay
              as they are — correct those with a payment or a fresh charge.
            </span>
          </>
        )}
      </div>
    </div>
  );
}

// ── This term ───────────────────────────────────────────────────────────────

function ThisTerm({ setup, announce, setErr }) {
  const [summary, setSummary] = useState(null);
  const [owing, setOwing] = useState([]);
  const [busy, setBusy] = useState(false);

  function load() {
    apiFetch("school/term-summary").then(d => setSummary(d.summary)).catch(() => {});
    apiFetch("school/defaulters").then(d => setOwing(d.defaulters || [])).catch(() => {});
  }
  useEffect(load, [setup?.current_term_id]);

  async function remindParents() {
    setBusy(true);
    try {
      const res = await apiPost("school/fee-reminders", {});
      const parts = [];
      if (res.queued) parts.push(`${res.queued} reminder(s) ready to review on Reminders`);
      if (res.already_queued) parts.push(`${res.already_queued} already waiting`);
      if (res.no_phone) parts.push(`${res.no_phone} parent(s) have no phone number saved`);
      announce(parts.join(" · ") || "Nothing to send — everyone has paid.");
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function openTerm() {
    if (!setup?.current_term_id) return;
    if (!window.confirm("Charge every pupil what their class owes this term?")) return;
    setBusy(true);
    try {
      const res = await apiPost(`school/terms/${setup.current_term_id}/open`, {});
      announce(res.charged
        ? `${res.charged} pupil(s) charged — ${nairaFull(res.total)} invoiced.`
        : "Everyone has already been charged for this term.");
      load();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  if (!summary) {
    return (
      <div className="card card-body" style={{ display: "grid", gap: 10 }}>
        <strong>No fees raised yet this term</strong>
        <span className="text-subtle text-sm">
          Set what each class owes under Setup, then charge the term.
        </span>
        <div>
          <button className="btn btn-primary" disabled={busy || !setup?.current_term_id}
            onClick={openTerm}>Charge this term</button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit,minmax(160px,1fr))" }}>
        <MetricCard label="Expected" value={nairaFull(summary.expected)} />
        <MetricCard label="Collected" value={nairaFull(summary.collected)} />
        <MetricCard label="Outstanding" value={nairaFull(summary.outstanding)} />
        <MetricCard label="Collection rate" value={`${summary.collection_rate}%`} />
      </div>

      <div className="card">
        <div className="card-header" style={{ flexWrap: "wrap", gap: 8 }}>
          <span className="card-title">{summary.term} — by class</span>
          <button className="btn btn-ghost btn-sm" disabled={busy} onClick={openTerm}>
            Charge any new pupils
          </button>
        </div>
        <div className="table-scroll">
          <table>
            <thead><tr><th>Class</th><th>Pupils</th><th>Expected</th><th>Outstanding</th></tr></thead>
            <tbody>
              {summary.classes.map(c => (
                <tr key={c.class_id}>
                  <td>{c.class_name}</td>
                  <td>{c.pupils}</td>
                  <td>{nairaFull(c.expected)}</td>
                  <td className={c.outstanding > 0 ? "text-rose" : ""}>
                    {nairaFull(c.outstanding)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="card-header" style={{ flexWrap: "wrap", gap: 8 }}>
          <span className="card-title">
            Still owing <span className="text-subtle text-sm">({owing.length})</span>
          </span>
          {owing.length > 0 && (
            <button className="btn btn-ghost btn-sm" disabled={busy}
              onClick={remindParents}
              style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <Bell size={14} /> Remind parents
            </button>
          )}
        </div>
        <div className="table-scroll">
          <table>
            <thead><tr><th>Pupil</th><th>Class</th><th>Billed</th><th>Owing</th><th>Parent</th></tr></thead>
            <tbody>
              {owing.length === 0 ? (
                <tr><td colSpan={5} className="td-muted">Everyone has paid ✓</td></tr>
              ) : owing.map(d => (
                <tr key={d.customer_id}>
                  <td><strong>{d.name}</strong></td>
                  <td>{d.class_name}</td>
                  <td>{nairaFull(d.billed)}</td>
                  <td className="text-rose">{nairaFull(d.outstanding)}</td>
                  <td className="td-muted" style={{ fontSize: 12 }}>{d.phone || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── Setup ───────────────────────────────────────────────────────────────────

function Setup({ setup, reload, announce, setErr }) {
  const [sessionName, setSessionName] = useState("");
  const [className, setClassName] = useState("");
  const [item, setItem] = useState({ name: "", kind: "FEE", is_optional: false, default_amount: "" });
  const [scheduleClass, setScheduleClass] = useState("");
  const [amounts, setAmounts] = useState({});
  const [fields, setFields] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [newField, setNewField] = useState("");

  const termId = setup?.current_term_id;

  function loadFields() {
    apiFetch("school/pupil-fields").then(d => {
      setFields(d.fields || []);
      setSuggestions(d.suggestions || []);
    }).catch(() => {});
  }
  useEffect(loadFields, []);

  useEffect(() => {
    if (!scheduleClass || !termId) return;
    apiFetch("school/schedule", { term_id: termId, class_id: scheduleClass })
      .then(d => {
        const next = {};
        (d.schedule || []).forEach(r => { next[r.fee_item_id] = String(r.amount); });
        setAmounts(next);
      }).catch(() => {});
  }, [scheduleClass, termId]);

  async function call(fn, message) {
    try { await fn(); announce(message); reload(); }
    catch (e) { setErr(e.message); }
  }

  async function removeThing(path, confirmText) {
    if (!window.confirm(confirmText)) return;
    try {
      const res = await apiDelete(path);
      // Records money depends on are closed rather than deleted, and the
      // server says why — pass that straight on instead of inventing wording.
      announce(res.deleted ? "Removed." : res.reason || "Closed.");
      reload();
    } catch (e) { setErr(e.message); }
  }

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="card">
        <div className="card-header"><span className="card-title">School year</span></div>
        <div className="card-body" style={{ display: "grid", gap: 10 }}>
          <div className="text-subtle text-sm">
            Fees are owed per term, so every charge belongs to one. The current term is
            marked below.
          </div>
          {(setup?.terms || []).map(t => (
            <div key={t.id} style={{ display: "flex", justifyContent: "space-between",
                                     alignItems: "center", gap: 8 }}>
              <span>
                {t.name}
                {t.invoiced_at && <span className="text-subtle text-sm"> · fees raised</span>}
              </span>
              {t.is_current ? <span className="badge badge-green">Current</span> : (
                <button className="btn btn-ghost btn-xs"
                  onClick={() => call(() => apiPost(`school/terms/${t.id}/current`, {}),
                                      `${t.name} is now the current term.`)}>
                  Make current
                </button>
              )}
            </div>
          ))}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input value={sessionName} onChange={e => setSessionName(e.target.value)}
              placeholder="2025/2026" style={{ flex: "1 1 160px" }} />
            <button className="btn btn-primary" disabled={!sessionName.trim()}
              onClick={() => call(() => apiPost("school/sessions", { name: sessionName }),
                                  "Session created with three terms.")
                            .then(() => setSessionName(""))}>
              Start session
            </button>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header"><span className="card-title">Classes</span></div>
        <div className="card-body" style={{ display: "grid", gap: 10 }}>
          <div style={{ display: "grid", gap: 6 }}>
            {(setup?.classes || []).map(c => (
              <div key={c.id} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input defaultValue={c.name} style={{ flex: 1 }}
                  onBlur={e => {
                    const name = e.target.value.trim();
                    if (name && name !== c.name) {
                      call(() => apiPut(`school/classes/${c.id}`,
                                        { name, level_order: c.level_order,
                                          teacher_id: c.teacher_id, is_active: c.is_active }),
                           `Renamed to ${name}.`);
                    }
                  }} />
                {!c.is_active && <span className="badge badge-gray">Closed</span>}
                <button className="btn btn-ghost btn-xs text-rose"
                  onClick={() => removeThing(`school/classes/${c.id}`,
                                             `Remove ${c.name}?`)}>
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
            {(setup?.classes || []).length === 0 && (
              <span className="text-subtle text-sm">No classes yet.</span>
            )}
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input value={className} onChange={e => setClassName(e.target.value)}
              placeholder="JSS 2A" style={{ flex: "1 1 160px" }} />
            <button className="btn btn-primary" disabled={!className.trim()}
              onClick={() => call(() => apiPost("school/classes", { name: className }),
                                  `${className} added.`).then(() => setClassName(""))}>
              Add class
            </button>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header"><span className="card-title">What you charge for</span></div>
        <div className="card-body" style={{ display: "grid", gap: 10 }}>
          <div className="text-subtle text-sm">
            Mark books and extras as optional — a pupil owes those only when they take one.
          </div>
          <div style={{ display: "grid", gap: 6 }}>
            {(setup?.fee_items || []).map(i => (
              <div key={i.id} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input defaultValue={i.name} style={{ flex: 1 }}
                  onBlur={e => {
                    const name = e.target.value.trim();
                    if (name && name !== i.name) {
                      call(() => apiPut(`school/fee-items/${i.id}`, { name }),
                           `Renamed to ${name}.`);
                    }
                  }} />
                <label style={{ display: "flex", gap: 5, alignItems: "center", fontSize: 12 }}>
                  <input type="checkbox" checked={i.is_optional}
                    onChange={e => call(
                      () => apiPut(`school/fee-items/${i.id}`,
                                   { is_optional: e.target.checked }),
                      e.target.checked
                        ? `${i.name} is now charged only when taken.`
                        : `${i.name} is now charged to everyone when the term opens.`)} />
                  optional
                </label>
                {!i.is_active && <span className="badge badge-gray">Retired</span>}
                <button className="btn btn-ghost btn-xs text-rose"
                  onClick={() => removeThing(`school/fee-items/${i.id}`, `Remove ${i.name}?`)}>
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
            {(setup?.fee_items || []).length === 0 && (
              <span className="text-subtle text-sm">Nothing set up yet.</span>
            )}
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
            <input value={item.name} style={{ flex: "1 1 160px" }}
              onChange={e => setItem(s => ({ ...s, name: e.target.value }))}
              placeholder="Tuition, PTA levy, Maths textbook…" />
            <select value={item.kind} onChange={e => setItem(s => ({ ...s, kind: e.target.value }))}>
              <option value="FEE">Fee</option>
              <option value="LEVY">Levy</option>
              <option value="BOOK">Book</option>
              <option value="UNIFORM">Uniform</option>
              <option value="OTHER">Other</option>
            </select>
            <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}>
              <input type="checkbox" checked={item.is_optional}
                onChange={e => setItem(s => ({ ...s, is_optional: e.target.checked }))} />
              Optional
            </label>
            <button className="btn btn-primary" disabled={!item.name.trim()}
              onClick={() => call(() => apiPost("school/fee-items", {
                ...item, default_amount: toInt(item.default_amount) || null,
              }), `${item.name} added.`).then(() =>
                setItem({ name: "", kind: "FEE", is_optional: false, default_amount: "" }))}>
              Add
            </button>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header"><span className="card-title">What each class owes this term</span></div>
        <div className="card-body" style={{ display: "grid", gap: 10 }}>
          <select value={scheduleClass} onChange={e => setScheduleClass(e.target.value)}>
            <option value="">Choose a class</option>
            {(setup?.classes || []).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          {scheduleClass && (setup?.fee_items || []).map(i => (
            <div key={i.id} style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ flex: 1 }}>
                {i.name}
                {i.is_optional && <span className="text-subtle text-sm"> (optional)</span>}
              </span>
              <input inputMode="numeric" style={{ width: 120 }}
                value={amounts[i.id] || ""} placeholder="0"
                onChange={e => setAmounts(a => ({ ...a, [i.id]: e.target.value }))} />
            </div>
          ))}
          {scheduleClass && (
            <div>
              <button className="btn btn-primary"
                onClick={() => call(() => apiPost("school/schedule", {
                  term_id: termId, class_id: scheduleClass,
                  amounts: Object.fromEntries(Object.entries(amounts)
                    .map(([k, v]) => [k, toInt(v)]).filter(([, v]) => v > 0)),
                }), "Fees saved for this class.")}>
                Save fees
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">What you keep about a pupil</span>
        </div>
        <div className="card-body" style={{ display: "grid", gap: 10 }}>
          <div className="text-subtle text-sm">
            These are the questions on your registration form. Add the ones your school cares
            about — switch off any you do not use.
          </div>
          <div style={{ display: "grid", gap: 6 }}>
            {fields.map(f => (
              <div key={f.id} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input type="checkbox" checked={f.is_active} title="Ask this question"
                  onChange={e => {
                    apiPut(`school/pupil-fields/${f.id}`, { is_active: e.target.checked })
                      .then(loadFields).catch(err => setErr(err.message));
                  }} />
                <input defaultValue={f.label} style={{ flex: 1 }}
                  onBlur={e => {
                    const label = e.target.value.trim();
                    if (label && label !== f.label) {
                      apiPut(`school/pupil-fields/${f.id}`, { label })
                        .then(loadFields).catch(err => setErr(err.message));
                    }
                  }} />
                <label style={{ display: "flex", gap: 5, alignItems: "center", fontSize: 12 }}>
                  <input type="checkbox" checked={f.is_required}
                    onChange={e => {
                      apiPut(`school/pupil-fields/${f.id}`, { is_required: e.target.checked })
                        .then(loadFields).catch(err => setErr(err.message));
                    }} />
                  required
                </label>
                <span className="text-subtle text-sm">{f.field_type}</span>
                <button className="btn btn-ghost btn-xs text-rose"
                  onClick={() => {
                    if (!window.confirm(`Stop asking "${f.label}"?`)) return;
                    apiDelete(`school/pupil-fields/${f.id}`)
                      .then(loadFields).catch(err => setErr(err.message));
                  }}>
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>

          {suggestions.length > 0 && (
            <div>
              <div className="text-subtle text-sm" style={{ marginBottom: 6 }}>
                Common ones you have not added:
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {suggestions.map(s => (
                  <button key={s.key} className="btn btn-ghost btn-xs"
                    onClick={() => apiPost("school/pupil-fields", {
                      label: s.label, field_type: s.field_type,
                      options: s.options || null, key: s.key,
                    }).then(loadFields).catch(err => setErr(err.message))}>
                    + {s.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input value={newField} onChange={e => setNewField(e.target.value)}
              placeholder="Anything else you keep" style={{ flex: "1 1 180px" }} />
            <button className="btn btn-primary" disabled={!newField.trim()}
              onClick={() => apiPost("school/pupil-fields", { label: newField })
                .then(() => { setNewField(""); loadFields(); })
                .catch(err => setErr(err.message))}>
              Add question
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
