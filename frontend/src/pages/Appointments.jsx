import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronLeft, ChevronRight, Plus, Link2 } from "lucide-react";
import { apiFetch, apiPost, apiPut } from "../lib/api";
import { nairaFull, fmtAmt, parseAmt } from "../lib/format";

const TONE = { requested: "#7c3aed", declined: "var(--muted)", booked: "#1d4ed8", arrived: "#b45309", done: "#166534", no_show: "#b91c1c", cancelled: "var(--muted)" };
const shift = (iso, days) => { const d = new Date(iso + "T12:00:00"); d.setDate(d.getDate() + days); return d.toISOString().slice(0, 10); };
const nice = iso => new Date(iso + "T12:00:00").toLocaleDateString("en-NG", { weekday: "long", day: "numeric", month: "short" });

// Pick a customer (search) or type a new one
function CustomerPick({ value, onChange }) {
  const [q, setQ] = useState(value?.name || "");
  const [found, setFound] = useState([]);
  useEffect(() => {
    const t = q.trim();
    if (value?.id || t.length < 2) return undefined;
    const h = setTimeout(() => apiFetch("customers", { q: t, limit: 6 }).then(d => setFound(d.customers || [])).catch(() => {}), 250);
    return () => clearTimeout(h);
  }, [q, value?.id]);
  return (
    <div style={{ position: "relative" }}>
      <input value={q} placeholder="Customer name" maxLength={120} style={{ width: "100%" }}
        onChange={e => { setQ(e.target.value); onChange({ name: e.target.value }); }} />
      {found.length > 0 && !value?.id && (
        <div className="card" style={{ position: "absolute", zIndex: 5, left: 0, right: 0, top: "100%", padding: 4 }}>
          {found.map(c => (
            <button key={c.id} type="button" className="btn btn-ghost btn-sm" style={{ display: "block", width: "100%", textAlign: "left" }}
              onMouseDown={e => e.preventDefault()}
              onClick={() => { setFound([]); setQ(c.name); onChange({ id: c.id, name: c.name, phone: c.phone }); }}>
              {c.name}{c.phone ? <span className="td-muted"> · {c.phone}</span> : ""}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// Choose service(s) from the price list
function ServicePick({ services, onChange }) {
  const [q, setQ] = useState("");
  const [found, setFound] = useState([]);
  useEffect(() => {
    const t = q.trim();
    if (t.length < 2) return undefined;
    const h = setTimeout(() => apiFetch("pos/products", { q: t, limit: 6 }).then(d => setFound(d.products || [])).catch(() => {}), 250);
    return () => clearTimeout(h);
  }, [q]);
  return (
    <div>
      {services.map((s, i) => (
        <div key={i} style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 4 }}>
          <span style={{ flex: 1 }}>{s.name}</span>
          <input inputMode="numeric" value={fmtAmt(String(s.price ?? ""))} style={{ width: 100 }}
            onChange={e => onChange(services.map((x, j) => (j === i ? { ...x, price: parseAmt(e.target.value) } : x)))} />
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => onChange(services.filter((_, j) => j !== i))}>×</button>
        </div>
      ))}
      <div style={{ position: "relative" }}>
        <input value={q} placeholder="Add a service (e.g. haircut)…" onChange={e => { setQ(e.target.value); if (e.target.value.trim().length < 2) setFound([]); }} style={{ width: "100%" }} />
        {found.length > 0 && (
          <div className="card" style={{ position: "absolute", zIndex: 5, left: 0, right: 0, top: "100%", padding: 4 }}>
            {found.map(p => (
              <button key={p.id} type="button" className="btn btn-ghost btn-sm" style={{ display: "block", width: "100%", textAlign: "left" }}
                onMouseDown={e => e.preventDefault()}
                onClick={() => { setQ(""); setFound([]); onChange([...services, { inventory_item_id: p.id, name: p.name, price: p.selling_price }]); }}>
                {p.name} <span className="td-muted">· {nairaFull(p.selling_price)}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function BookModal({ day, staff, appt, onClose, onSaved }) {
  const [customer, setCustomer] = useState(appt?.customer || null);
  const [date, setDate] = useState(appt?.date || day);
  const [time, setTime] = useState(appt?.time || "09:00");
  const [duration, setDuration] = useState(String(appt?.duration_min || 30));
  const [services, setServices] = useState(appt?.services || []);
  const [staffId, setStaffId] = useState(appt?.staff_user_id || "");
  const [staffName, setStaffName] = useState(appt?.staff_user_id ? "" : (appt?.staff_name || ""));
  const [note, setNote] = useState(appt?.note || "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [warn, setWarn] = useState(null);

  async function save() {
    if (!customer?.id && !customer?.name?.trim()) { setErr("Who is the appointment for?"); return; }
    setBusy(true); setErr("");
    const body = { date, time, duration_min: Number(duration) || 30, services,
      customer_id: customer?.id || null, customer_name: customer?.id ? null : customer?.name?.trim(),
      customer_phone: customer?.id ? null : (customer?.phone || null),
      staff_user_id: staffId || null, staff_name: staffId ? null : (staffName.trim() || null), note: note.trim() || null };
    try {
      const r = appt ? await apiPut(`appointments/${appt.id}`, body) : await apiPost("appointments", body);
      if (r.clashes?.length) { setWarn(r); setBusy(false); return; }
      onSaved(r.date);
    } catch (e) { setErr(e.message); setBusy(false); }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 520 }}>
        <div className="modal-header">
          <span className="modal-title">{appt ? "Change appointment" : "Book an appointment"}</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        {warn ? (
          <>
            <div className="modal-body" style={{ fontSize: 14 }}>
              ⚠ Saved — but {warn.staff_name} already has {warn.clashes.map(c => `${c.customer} at ${c.time}`).join(", ")} at the same time.
              Change the time or staff if that's a mistake.
            </div>
            <div className="modal-footer"><button className="btn btn-primary" onClick={() => onSaved(warn.date)}>OK</button></div>
          </>
        ) : (
          <>
            <div className="modal-body" style={{ display: "grid", gap: 10 }}>
              <div><label className="form-label">Customer</label><CustomerPick value={customer} onChange={setCustomer} /></div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
                <div><label className="form-label">Date</label><input type="date" value={date} onChange={e => setDate(e.target.value)} style={{ width: "100%" }} /></div>
                <div><label className="form-label">Time</label><input type="time" value={time} onChange={e => setTime(e.target.value)} style={{ width: "100%" }} /></div>
                <div><label className="form-label">Minutes</label><input inputMode="numeric" value={duration} onChange={e => setDuration(e.target.value.replace(/\D/g, ""))} style={{ width: "100%" }} /></div>
              </div>
              <div><label className="form-label">Service(s)</label><ServicePick services={services} onChange={setServices} /></div>
              <div>
                <label className="form-label">With <span className="text-subtle">(optional)</span></label>
                <div style={{ display: "flex", gap: 6 }}>
                  <select value={staffId} onChange={e => setStaffId(e.target.value)} style={{ flex: 1 }}>
                    <option value="">— anyone / type a name —</option>
                    {staff.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                  {!staffId && <input value={staffName} maxLength={80} placeholder="Name" onChange={e => setStaffName(e.target.value)} style={{ flex: 1 }} />}
                </div>
              </div>
              <div><label className="form-label">Note <span className="text-subtle">(optional)</span></label>
                <input value={note} maxLength={300} onChange={e => setNote(e.target.value)} style={{ width: "100%" }} /></div>
              {err && <div className="modal-error">{err}</div>}
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
              <button className="btn btn-primary" onClick={save} disabled={busy}>{busy ? "Saving…" : appt ? "Save" : "Book"}</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function DoneModal({ appt, onClose, onDone }) {
  const [services, setServices] = useState(appt.services || []);
  const total = services.reduce((s, x) => s + (Number(x.price) || 0), 0);
  const [paid, setPaid] = useState(fmtAmt(String(total)));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function save() {
    setBusy(true); setErr("");
    try { onDone(await apiPost(`appointments/${appt.id}/done`, { paid: parseAmt(paid), services })); }
    catch (e) { setErr(e.message); setBusy(false); }
  }
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">Done — {appt.customer?.name}</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body" style={{ display: "grid", gap: 10 }}>
          <div><label className="form-label">What was done</label><ServicePick services={services} onChange={setServices} /></div>
          <div style={{ fontSize: 14 }}>Total: <strong>{nairaFull(total)}</strong></div>
          <div><label className="form-label">Paid now (₦)</label>
            <input inputMode="numeric" value={paid} onChange={e => setPaid(fmtAmt(e.target.value))} style={{ width: "100%" }} />
            <span className="form-hint">Less than the total becomes their debt. The receipt goes to them on WhatsApp.</span></div>
          {err && <div className="modal-error">{err}</div>}
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={save} disabled={busy}>{busy ? "Saving…" : "Record sale"}</button>
        </div>
      </div>
    </div>
  );
}

// The customer booking link: copy / send it, or how to switch it on
function LinkCard({ onClose }) {
  const [info, setInfo] = useState(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => { apiFetch("appointments/booking-link").then(setInfo).catch(() => setInfo({})); }, []);
  async function copy() {
    try { await navigator.clipboard.writeText(info.link); setCopied(true); setTimeout(() => setCopied(false), 1500); }
    catch { /* they can select it */ }
  }
  const share = info?.link && `https://wa.me/?text=${encodeURIComponent(`Book your appointment with ${info.biz_name}: ${info.link}`)}`;
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">Your booking link</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body" style={{ fontSize: 14, display: "grid", gap: 10 }}>
          {!info ? "Loading…" : !info.on ? (
            <>
              <div>Customers can book themselves from a link you share — on WhatsApp status, Instagram, anywhere.</div>
              <div>It's off. Switch it on in <strong>Settings → Appointments</strong>, set your opening hours, then come back here for the link.</div>
            </>
          ) : (
            <>
              <div>Share this link. Customers pick a service, a day and a free time; you'll see their request here to confirm.</div>
              <input readOnly value={info.link} onFocus={e => e.target.select()} style={{ width: "100%" }} />
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <button className="btn btn-secondary btn-sm" onClick={copy}>{copied ? "Copied ✓" : "Copy link"}</button>
                <a className="btn btn-primary btn-sm" href={share} target="_blank" rel="noreferrer">Send on WhatsApp</a>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// Booking requests from the link — confirm or decline (with a reason)
function Requests({ list, onChanged, setErr }) {
  async function act(a, what) {
    let body = {};
    if (what === "decline") {
      const reason = window.prompt("Decline — tell them why? (optional, e.g. \"We're full that day, try Friday\")", "");
      if (reason === null) return;
      body = { reason };
    }
    try { await apiPost(`appointments/${a.id}/${what}`, body); onChanged(); }
    catch (e) { setErr(e.message); }
  }
  return (
    <div className="card" style={{ borderLeft: "4px solid #7c3aed" }}>
      <div className="card-header"><span className="card-title">Asking to book ({list.length})</span></div>
      {list.map(a => (
        <div key={a.id} style={{ padding: "10px 16px", borderTop: "1px solid var(--border)" }}>
          <strong>{nice(a.date)}, {a.time}</strong> · {a.customer?.name}
          {a.customer?.phone && <span className="td-muted"> · {a.customer.phone}</span>}
          <div className="td-muted" style={{ fontSize: 12 }}>
            {a.services.map(s => s.name).join(", ")}{a.total ? ` · ${nairaFull(a.total)}` : ""}
            {a.staff_name ? ` · with ${a.staff_name}` : ""}{a.note ? ` · ${a.note}` : ""}
          </div>
          <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
            <button className="btn btn-primary btn-sm" onClick={() => act(a, "confirm")}>Confirm</button>
            <button className="btn btn-ghost btn-sm" style={{ color: "#b91c1c" }} onClick={() => act(a, "decline")}>Decline</button>
          </div>
        </div>
      ))}
    </div>
  );
}

/* The day's appointments: book, move, mark arrived / no-show, and Done
   (records the sale). Customers are reminded on WhatsApp the evening before. */
export default function Appointments() {
  const navigate = useNavigate();
  const [day, setDay] = useState(null);
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [booking, setBooking] = useState(null);     // {} new, or an appointment to change
  const [doing, setDoing] = useState(null);
  const [showLink, setShowLink] = useState(false);

  function load(d) {
    apiFetch("appointments", d ? { day: d } : {}).then(r => { setData(r); setDay(r.day); }).catch(e => setErr(e.message));
  }
  useEffect(() => { load(); }, []);

  async function status(a, s) {
    try { await apiPost(`appointments/${a.id}/status`, { status: s }); load(day); }
    catch (e) { setErr(e.message); }
  }

  if (!data) return <div className="page-loading">{err || "Loading appointments…"}</div>;
  const isToday = day === data.today;
  return (
    <div style={{ display: "grid", gap: 14, maxWidth: 720 }}>
      <div className="card">
        <div className="card-header" style={{ flexWrap: "wrap", gap: 8 }}>
          <span className="card-title">Appointments</span>
          <div style={{ display: "flex", gap: 6 }}>
            <button className="btn btn-secondary btn-sm" onClick={() => setShowLink(true)}><Link2 size={14} /> Booking link</button>
            <button className="btn btn-primary btn-sm" onClick={() => setBooking({})}><Plus size={14} /> Book</button>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 16px 12px" }}>
          <button className="btn btn-ghost btn-sm" onClick={() => load(shift(day, -1))} aria-label="Previous day"><ChevronLeft size={16} /></button>
          <div style={{ textAlign: "center" }}>
            <strong>{isToday ? "Today" : nice(day)}</strong>
            {!isToday && <div><button className="btn btn-ghost btn-sm" onClick={() => load()}>Back to today</button></div>}
            {isToday && <div className="td-muted" style={{ fontSize: 12 }}>{nice(day)}</div>}
          </div>
          <button className="btn btn-ghost btn-sm" onClick={() => load(shift(day, 1))} aria-label="Next day"><ChevronRight size={16} /></button>
        </div>
        {err && <div className="modal-error" style={{ margin: 12 }}>{err}</div>}
      </div>

      {data.requests?.length > 0 && <Requests list={data.requests} onChanged={() => load(day)} setErr={setErr} />}

      <div className="card">
        {data.appointments.length === 0 ? (
          <div className="td-muted" style={{ padding: 16 }}>No appointments {isToday ? "today" : "this day"}. Tap Book to add one.</div>
        ) : data.appointments.map(a => (
          <div key={a.id} style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)", opacity: ["cancelled", "declined"].includes(a.status) ? 0.55 : 1 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
              <div style={{ minWidth: 0 }}>
                <strong>{a.time}–{a.end}</strong> · {a.customer?.name}
                {a.no_shows > 0 && <span style={{ color: "#b91c1c", fontSize: 12 }}> · {a.no_shows} no-show{a.no_shows > 1 ? "s" : ""} before</span>}
                <div className="td-muted" style={{ fontSize: 12 }}>
                  {a.services.map(s => s.name).join(", ") || "No service chosen"}
                  {a.total ? ` · ${nairaFull(a.total)}` : ""}{a.staff_name ? ` · with ${a.staff_name}` : ""}
                  {a.note ? ` · ${a.note}` : ""}{a.reminded ? " · reminded ✓" : ""}
                </div>
              </div>
              <span style={{ fontSize: 12, fontWeight: 700, color: TONE[a.status] }}>{a.status_label}</span>
            </div>
            {["booked", "arrived"].includes(a.status) && (
              <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
                {a.status === "booked" && <button className="btn btn-secondary btn-sm" onClick={() => status(a, "arrived")}>Arrived</button>}
                <button className="btn btn-primary btn-sm" onClick={() => setDoing(a)}>Done</button>
                <button className="btn btn-ghost btn-sm" onClick={() => setBooking(a)}>Change</button>
                <button className="btn btn-ghost btn-sm" onClick={() => status(a, "no_show")}>No-show</button>
                <button className="btn btn-ghost btn-sm" style={{ color: "#b91c1c" }}
                  onClick={() => window.confirm("Cancel this appointment?") && status(a, "cancelled")}>Cancel</button>
              </div>
            )}
            {a.status === "done" && a.sale_tx_id && (
              <button className="btn btn-ghost btn-sm" style={{ marginTop: 4 }} onClick={() => navigate(`/pos/receipt/${a.sale_tx_id}`)}>View receipt</button>
            )}
          </div>
        ))}
      </div>

      {booking && (
        <BookModal day={day} staff={data.staff} appt={booking.id ? booking : null}
          onClose={() => setBooking(null)} onSaved={d => { setBooking(null); load(d); }} />
      )}
      {showLink && <LinkCard onClose={() => setShowLink(false)} />}
      {doing && <DoneModal appt={doing} onClose={() => setDoing(null)} onDone={() => { setDoing(null); load(day); }} />}
    </div>
  );
}
