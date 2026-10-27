import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull } from "../lib/format";

/* The page a customer opens from a business's booking link — no app, no
   account. They pick what they want done, a day and a free time, and leave a
   name and WhatsApp number. The business confirms (or it's booked at once if
   they chose that), and the customer hears back on WhatsApp. */

const dayName = iso => new Date(iso + "T12:00:00").toLocaleDateString("en-NG", { weekday: "short" });
const dayNum = iso => new Date(iso + "T12:00:00").toLocaleDateString("en-NG", { day: "numeric", month: "short" });
const ampm = t => { const [h, m] = t.split(":").map(Number); return `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`; };

export default function BookPage() {
  const { token } = useParams();
  const [p, setP] = useState(null);
  const [err, setErr] = useState("");
  const [picked, setPicked] = useState([]);
  const [staff, setStaff] = useState("");
  const [day, setDay] = useState(null);
  const [times, setTimes] = useState(null);
  const [time, setTime] = useState(null);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);

  useEffect(() => {
    apiFetch(`public/book/${token}`).then(setP).catch(e => setErr(e.message));
  }, [token]);

  useEffect(() => {
    if (!day) return;
    let live = true;
    apiFetch(`public/book/${token}/times`, staff ? { date: day, staff } : { date: day })
      .then(d => { if (live) setTimes(d.times); }).catch(e => live && setErr(e.message));
    return () => { live = false; };
  }, [token, day, staff]);

  function pickDay(d) { setDay(d); setTimes(null); setTime(null); }

  async function send() {
    setBusy(true); setErr("");
    try {
      setDone(await apiPost(`public/book/${token}`, {
        date: day, time, service_ids: picked, name: name.trim(), phone: phone.trim(),
        staff_user_id: staff || null, note: note.trim() || null,
      }));
    } catch (e) {
      setErr(e.message);
      if (/taken/i.test(e.message)) { setTime(null); setTimes(null); apiFetch(`public/book/${token}/times`, staff ? { date: day, staff } : { date: day }).then(d => setTimes(d.times)).catch(() => {}); }
    } finally { setBusy(false); }
  }

  const wrap = children => (
    <div style={{ minHeight: "100vh", background: "var(--bg, #f4f6fb)", padding: "24px 16px" }}>
      <div className="card" style={{ maxWidth: 480, margin: "0 auto", padding: 20 }}>{children}</div>
    </div>
  );
  if (err && !p) return wrap(<div className="pos-error">{err}</div>);
  if (!p) return wrap(<div className="td-muted">Loading…</div>);

  const head = (
    <div style={{ textAlign: "center", marginBottom: 14 }}>
      {p.biz_logo && <img src={p.biz_logo} alt="" style={{ maxHeight: 56, maxWidth: 140, objectFit: "contain" }} />}
      <div style={{ fontSize: 19, fontWeight: 800 }}>{p.biz_name}</div>
      <div className="td-muted" style={{ fontSize: 13 }}>Book an appointment</div>
    </div>
  );
  if (done) {
    return wrap(<>
      {head}
      <div style={{ background: "#ecfdf5", color: "#166534", borderRadius: 10, padding: 14, fontSize: 15 }}>
        {done.status === "booked"
          ? <>✓ You're booked: <strong>{done.services}</strong> on <strong>{dayName(done.date)} {dayNum(done.date)} at {ampm(done.time)}</strong>. We've sent it to your WhatsApp.</>
          : <>✓ Request sent: <strong>{done.services}</strong> on <strong>{dayName(done.date)} {dayNum(done.date)} at {ampm(done.time)}</strong>. {p.biz_name} will confirm on WhatsApp.</>}
      </div>
    </>);
  }

  const total = p.services.filter(s => picked.includes(s.id)).reduce((t, s) => t + s.price, 0);
  const ready = picked.length && day && time && name.trim().length >= 2 && phone.replace(/\D/g, "").length >= 10;
  const chip = on => ({ border: `1px solid ${on ? "var(--primary, #2563eb)" : "var(--line, #e5e7eb)"}`, background: on ? "var(--primary, #2563eb)" : "transparent",
    color: on ? "#fff" : "inherit", borderRadius: 10, padding: "8px 10px", cursor: "pointer" });

  return wrap(
    <div style={{ display: "grid", gap: 14 }}>
      {head}
      <div>
        <div className="receipt-label">1. What would you like?</div>
        {p.services.length === 0 && <div className="td-muted">No services listed yet{p.biz_phone ? ` — call ${p.biz_phone}` : ""}.</div>}
        {p.services.map(s => (
          <label key={s.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0", borderBottom: "1px solid var(--line, #e5e7eb)" }}>
            <input type="checkbox" checked={picked.includes(s.id)}
              onChange={e => setPicked(e.target.checked ? [...picked, s.id] : picked.filter(x => x !== s.id))} />
            <span style={{ flex: 1 }}>{s.name}</span>
            <span className="td-muted">{nairaFull(s.price)}</span>
          </label>
        ))}
        {total > 0 && <div style={{ textAlign: "right", fontSize: 13, marginTop: 4 }}>Total about <strong>{nairaFull(total)}</strong></div>}
      </div>

      {p.staff.length > 0 && (
        <div>
          <div className="receipt-label">Who would you like? <span style={{ opacity: 0.6 }}>(optional)</span></div>
          <select value={staff} onChange={e => { setStaff(e.target.value); setTime(null); setTimes(null); }} style={{ width: "100%" }}>
            <option value="">Anyone free</option>
            {p.staff.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </div>
      )}

      <div>
        <div className="receipt-label">2. Pick a day</div>
        <div style={{ display: "flex", gap: 6, overflowX: "auto", paddingBottom: 4 }}>
          {p.days.map(d => (
            <button key={d.date} type="button" disabled={!d.open} onClick={() => pickDay(d.date)}
              style={{ ...chip(day === d.date), minWidth: 62, textAlign: "center", opacity: d.open ? 1 : 0.4 }}>
              <div style={{ fontSize: 12 }}>{dayName(d.date)}</div>
              <div style={{ fontWeight: 700, fontSize: 13 }}>{dayNum(d.date)}</div>
              {!d.open && <div style={{ fontSize: 10 }}>Closed</div>}
            </button>
          ))}
        </div>
      </div>

      {day && (
        <div>
          <div className="receipt-label">3. Pick a time</div>
          {times === null ? <div className="td-muted">Checking free times…</div>
            : times.length === 0 ? <div className="td-muted">No free times that day — try another day.</div>
            : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(84px, 1fr))", gap: 6 }}>
                {times.map(t => <button key={t} type="button" style={chip(time === t)} onClick={() => setTime(t)}>{ampm(t)}</button>)}
              </div>
            )}
        </div>
      )}

      {time && (
        <div style={{ display: "grid", gap: 8 }}>
          <div className="receipt-label">4. Your details</div>
          <input value={name} maxLength={80} placeholder="Your name" onChange={e => setName(e.target.value)} />
          <input value={phone} maxLength={20} inputMode="tel" placeholder="WhatsApp number e.g. 0803…" onChange={e => setPhone(e.target.value)} />
          <input value={note} maxLength={300} placeholder="Anything they should know? (optional)" onChange={e => setNote(e.target.value)} />
        </div>
      )}

      {err && <div className="pos-error">{err}</div>}
      <button className="btn btn-primary" onClick={send} disabled={!ready || busy} style={{ justifyContent: "center" }}>
        {busy ? "Sending…" : p.confirm ? "Ask to book" : "Book"}
      </button>
      {p.confirm && <div className="td-muted" style={{ fontSize: 12, textAlign: "center" }}>{p.biz_name} will confirm your time on WhatsApp.</div>}
    </div>
  );
}
