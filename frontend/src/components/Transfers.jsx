import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Trash2 } from "lucide-react";
import { apiFetch, apiPost } from "../lib/api";
import { dateStr } from "../lib/format";

function Shell({ title, onClose, children, footer }) {
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal modal-wide">
        <div className="modal-header">
          <span className="modal-title">{title}</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body" style={{ display: "grid", gap: 10 }}>{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  );
}

const titled = s => (s || "").replace(/\b\w/g, c => c.toUpperCase());
const qtyStr = (n, unit) => `${Number(n ?? 0).toLocaleString()}${unit ? ` ${unit}` : ""}`;

/* Send stock from one branch to another (stock_transfers.py). `lockedFrom` =
   the only branch this person may send from (an admin kept to their branch). */
export function TransferModal({ branches, lockedFrom = null, preset = null, confirm = false, onClose }) {
  const navigate = useNavigate();
  const def = branches.find(b => b.is_default) || branches[0];
  const [from, setFrom] = useState(lockedFrom || preset?.branch_id || def?.id);
  const [to, setTo] = useState(() => (branches.find(b => b.id !== (lockedFrom || preset?.branch_id || def?.id)) || {}).id);
  const [items, setItems] = useState(null);
  const [lines, setLines] = useState(preset ? [{ item_id: preset.id, qty: "" }] : [{ item_id: null, qty: "" }]);
  const [carrier, setCarrier] = useState("");
  const [carrierPhone, setCarrierPhone] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    setItems(null);
    apiFetch("inventory", { branch_id: from, limit: 500 })
      .then(d => setItems((d.items || []).filter(i => !i.is_service && (i.quantity ?? 0) > 0)))
      .catch(e => setErr(e.message));
  }, [from]);

  function pickFrom(id) {
    setFrom(id);
    setLines([{ item_id: null, qty: "" }]);
    if (id === to) setTo((branches.find(b => b.id !== id) || {}).id);
  }
  const setLine = (ix, patch) => setLines(ls => ls.map((l, i) => (i === ix ? { ...l, ...patch } : l)));
  const byId = Object.fromEntries((items || []).map(i => [i.id, i]));

  async function send() {
    const chosen = lines.filter(l => l.item_id && Number(l.qty) > 0);
    if (!chosen.length) { setErr("Pick a product and how many to send."); return; }
    const over = chosen.find(l => Number(l.qty) > (byId[l.item_id]?.quantity ?? 0));
    if (over) { setErr(`Only ${qtyStr(byId[over.item_id].quantity, byId[over.item_id].unit)} of ${titled(byId[over.item_id].name)} here.`); return; }
    setBusy(true); setErr("");
    try {
      const tr = await apiPost("transfers", {
        from_branch_id: from, to_branch_id: to,
        lines: chosen.map(l => ({ item_id: l.item_id, quantity: Number(l.qty) })),
        carried_by: carrier.trim() || null, carrier_phone: carrierPhone.trim() || null, note: note.trim() || null,
      });
      navigate(`/transfers/${tr.id}`);
    } catch (e) { setErr(e.message); setBusy(false); }
  }

  return (
    <Shell title="Transfer stock" onClose={onClose} footer={<>
      <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
      <button className="btn btn-primary" disabled={busy || !items} onClick={send}>{busy ? "Sending…" : "Send"}</button>
    </>}>
      <div className="form-row" style={{ flexWrap: "wrap" }}>
        <div className="form-group" style={{ flex: "1 1 160px" }}>
          <label className="form-label">From</label>
          <select value={from ?? ""} disabled={!!lockedFrom} onChange={e => pickFrom(Number(e.target.value))}>
            {branches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </div>
        <div className="form-group" style={{ flex: "1 1 160px" }}>
          <label className="form-label">To</label>
          <select value={to ?? ""} onChange={e => setTo(Number(e.target.value))}>
            {branches.filter(b => b.id !== from).map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </div>
      </div>

      <label className="form-label" style={{ margin: 0 }}>What's going</label>
      {!items ? <div className="td-muted">Loading {branches.find(b => b.id === from)?.name}'s stock…</div>
        : items.length === 0 ? <div className="td-muted">No stock in {branches.find(b => b.id === from)?.name} to send.</div>
        : lines.map((l, ix) => (
          <div key={ix} style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <select style={{ flex: 1, minWidth: 0 }} value={l.item_id ?? ""} onChange={e => setLine(ix, { item_id: Number(e.target.value) || null })}>
              <option value="">— Product —</option>
              {items.map(i => <option key={i.id} value={i.id}>{titled(i.name)} ({qtyStr(i.quantity, i.unit)})</option>)}
            </select>
            <input type="number" min="0" step="any" inputMode="decimal" value={l.qty} placeholder="How many"
              onChange={e => setLine(ix, { qty: e.target.value })} style={{ width: 100 }} />
            {lines.length > 1 && (
              <button className="pos-remove" aria-label="Remove" onClick={() => setLines(ls => ls.filter((_, i) => i !== ix))}>
                <Trash2 size={13} />
              </button>
            )}
          </div>
        ))}
      {items && items.length > 0 && (
        <div><button className="btn btn-ghost btn-sm" onClick={() => setLines(ls => [...ls, { item_id: null, qty: "" }])}>
          <Plus size={13} /> Add product
        </button></div>
      )}

      <div className="form-row" style={{ flexWrap: "wrap" }}>
        <div className="form-group" style={{ flex: "1 1 160px" }}>
          <label className="form-label">Carried by <span className="text-subtle">(optional)</span></label>
          <input value={carrier} maxLength={80} onChange={e => setCarrier(e.target.value)} placeholder="Driver or staff name" />
        </div>
        <div className="form-group" style={{ flex: "1 1 140px" }}>
          <label className="form-label">Their phone <span className="text-subtle">(optional)</span></label>
          <input value={carrierPhone} maxLength={30} inputMode="tel" onChange={e => setCarrierPhone(e.target.value)} />
        </div>
      </div>
      <input value={note} maxLength={300} onChange={e => setNote(e.target.value)} placeholder="Note (optional)" />
      <span className="form-hint">
        {confirm
          ? "The goods leave now and show as on the way. The other branch taps Received and says what arrived."
          : "The goods leave now and are in the other branch's stock straight away. A product it doesn't have yet is added there."}
        {" "}You get a transfer note to print — no prices on it.
      </span>
      {err && <div className="modal-error">{err}</div>}
    </Shell>
  );
}

const LABEL = { on_the_way: "On the way", received: "Received", cancelled: "Cancelled" };

/* Every transfer, newest first; on-the-way ones to receive first. */
export function TransfersModal({ onClose, onNew }) {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { apiFetch("transfers").then(setData).catch(e => setErr(e.message)); }, []);
  const rows = data ? [...data.transfers].sort((a, b) => (a.status === "on_the_way") === (b.status === "on_the_way") ? 0
    : a.status === "on_the_way" ? -1 : 1) : [];
  return (
    <Shell title="Transfers between branches" onClose={onClose} footer={<>
      <button className="btn btn-ghost" onClick={onClose}>Close</button>
      {onNew && <button className="btn btn-primary" onClick={onNew}><Plus size={14} /> Transfer stock</button>}
    </>}>
      {err && <div className="modal-error">{err}</div>}
      {!data && !err && <div className="td-muted">Loading…</div>}
      {data && data.to_receive > 0 && (
        <div className="pos-credit-warn">{data.to_receive} on the way to confirm — open it and tap Received when it arrives.</div>
      )}
      {data && rows.length === 0 && <div className="td-muted">No transfers yet.</div>}
      {rows.map(t => (
        <button key={t.id} type="button" className="name-chip" onClick={() => navigate(`/transfers/${t.id}`)}
          style={{ display: "flex", justifyContent: "space-between", width: "100%", textAlign: "left", gap: 8, flexWrap: "wrap" }}>
          <span><strong>{t.number}</strong> · {t.from_branch} → {t.to_branch} · {t.items} product{t.items === 1 ? "" : "s"}</span>
          <span className="td-muted" style={{ whiteSpace: "nowrap" }}>
            {dateStr(t.created_at)} · <span style={{ color: t.status === "on_the_way" ? "#b45309" : t.short ? "#b91c1c" : undefined }}>
              {LABEL[t.status] || t.status}{t.short ? " — some missing" : ""}</span>
          </span>
        </button>
      ))}
    </Shell>
  );
}
