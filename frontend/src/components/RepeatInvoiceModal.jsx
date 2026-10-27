import { useState } from "react";
import { apiPost, apiPut } from "../lib/api";
import { nairaFull, fmtAmt, parseAmt } from "../lib/format";

const EVERY = [["week", "Every week"], ["month", "Every month"], ["quarter", "Every 3 months"], ["year", "Every year"]];
const MONTHS = { month: 1, quarter: 3, year: 12 };

// Today in Nigeria, as YYYY-MM-DD
function lagosToday() {
  return new Date(Date.now() + 3600 * 1000).toISOString().slice(0, 10);
}

// One period after the invoice date — the usual first repeat
function nextAfter(iso, every) {
  const d = new Date(iso + "T12:00:00Z");
  if (every === "week") d.setUTCDate(d.getUTCDate() + 7);
  else {
    const day = d.getUTCDate();
    d.setUTCDate(1); d.setUTCMonth(d.getUTCMonth() + MONTHS[every]);
    const last = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0)).getUTCDate();
    d.setUTCDate(Math.min(day, last));
  }
  const out = d.toISOString().slice(0, 10);
  return out < lagosToday() ? lagosToday() : out;
}

/* Make an invoice repeat (invoiceId), or change a repeat (repeat).
   Sending choice: "Send it for me" (the default) or "Let me check first". */
export default function RepeatInvoiceModal({ invoiceId, invoiceDate, repeat, onClose, onSaved }) {
  const base = (invoiceDate || lagosToday()).slice(0, 10);
  const [every, setEvery] = useState(repeat?.every || "month");
  const [start, setStart] = useState(repeat?.next_date || nextAfter(base, "month"));
  const [touched, setTouched] = useState(!!repeat);
  const [stop, setStop] = useState(repeat?.stop_after ? "count" : repeat?.stop_on ? "date" : "never");
  const [count, setCount] = useState(String(repeat?.stop_after || 12));
  const [stopOn, setStopOn] = useState(repeat?.stop_on || "");
  const [autoSend, setAutoSend] = useState(repeat ? repeat.auto_send : true);
  const [items, setItems] = useState(repeat?.items || null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  function pickEvery(v) {
    setEvery(v);
    if (!touched) setStart(nextAfter(base, v));
  }

  async function save() {
    setBusy(true); setErr("");
    const body = { every, start, auto_send: autoSend,
      stop_after: stop === "count" ? Number(count) || null : null, stop_on: stop === "date" ? stopOn || null : null };
    try {
      const r = repeat
        ? await apiPut(`recurring-invoices/${repeat.id}`, { ...body, items })
        : await apiPost(`invoices/doc/${invoiceId}/repeat`, body);
      onSaved(r);
    } catch (e) { setErr(e.message); setBusy(false); }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 480 }}>
        <div className="modal-header">
          <span className="modal-title">{repeat ? `Repeat invoice — ${repeat.customer}` : "Make it repeat"}</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body" style={{ display: "grid", gap: 12, fontSize: 14 }}>
          {!repeat && <div className="td-muted">On each date a new invoice is made with the same items and prices, for the same customer.</div>}
          <div>
            <label className="form-label">How often</label>
            <select value={every} onChange={e => pickEvery(e.target.value)} style={{ width: "100%" }}>
              {EVERY.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <label className="form-label">{repeat ? "Next one on" : "First repeat on"}</label>
            <input type="date" value={start} min={lagosToday()} onChange={e => { setStart(e.target.value); setTouched(true); }} style={{ width: "100%" }} />
          </div>
          <div>
            <label className="form-label">Stop</label>
            <select value={stop} onChange={e => setStop(e.target.value)} style={{ width: "100%" }}>
              <option value="never">Never — until I stop it</option>
              <option value="count">After a number of invoices</option>
              <option value="date">On a date</option>
            </select>
            {stop === "count" && (
              <div style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 6 }}>
                <input inputMode="numeric" value={count} onChange={e => setCount(e.target.value.replace(/\D/g, ""))} style={{ width: 80 }} />
                <span>more invoice(s){repeat?.made_count ? `, counting the ${repeat.made_count} already made` : ""}</span>
              </div>
            )}
            {stop === "date" && <input type="date" value={stopOn} min={start} onChange={e => setStopOn(e.target.value)} style={{ width: "100%", marginTop: 6 }} />}
          </div>
          <div>
            <label className="form-label">When it's made</label>
            <div className="seg" role="radiogroup">
              <button type="button" role="radio" aria-checked={autoSend} className={autoSend ? "on" : ""} onClick={() => setAutoSend(true)}>Send it for me</button>
              <button type="button" role="radio" aria-checked={!autoSend} className={!autoSend ? "on" : ""} onClick={() => setAutoSend(false)}>Let me check first</button>
            </div>
            <span className="form-hint">
              {autoSend
                ? "It goes to the customer's WhatsApp with the pay link, and you get a note. No phone on file? You're told to send or print it."
                : "It's made but not sent. You get a note to check it, then tap Send to customer."}
            </span>
          </div>
          {repeat && items && (
            <div>
              <label className="form-label">Items and prices (for the next ones)</label>
              {items.map((it, i) => (
                <div key={i} style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 4 }}>
                  <span style={{ flex: 1 }}>{it.qty} × {it.name}</span>
                  <input inputMode="numeric" value={fmtAmt(String(it.unit_price))} style={{ width: 110 }}
                    onChange={e => setItems(items.map((x, j) => (j === i ? { ...x, unit_price: parseAmt(e.target.value) } : x)))} />
                </div>
              ))}
              <div style={{ textAlign: "right", fontSize: 13 }}>
                Total <strong>{nairaFull(items.reduce((t, x) => t + Math.round(Number(x.qty) * Number(x.unit_price || 0)), 0) - (repeat.discount || 0))}</strong>
                {repeat.discount ? <span className="td-muted"> (after {nairaFull(repeat.discount)} off)</span> : null}
              </div>
            </div>
          )}
          {err && <div className="modal-error">{err}</div>}
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={save} disabled={busy}>{busy ? "Saving…" : repeat ? "Save" : "Make it repeat"}</button>
        </div>
      </div>
    </div>
  );
}
