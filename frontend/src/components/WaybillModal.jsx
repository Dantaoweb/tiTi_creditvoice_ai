import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch, apiPost } from "../lib/api";

const qtyLabel = (n, unit) => `${Number(n).toLocaleString()}${unit ? ` ${unit}` : ""}`;

/* Make a waybill / loading order for the loaders and the driver. `source` is
   { tx_id } (a receipt), { invoice_id } or { customer_id } (everything they
   are still waiting for). Each line is ticked with how many go on this trip —
   never more than is in the store for them. Goods still to deliver leave
   stock when the waybill is made; goods already handed over are only listed.
   Then it opens the waybill to print or share. */
export default function WaybillModal({ source, onClose }) {
  const navigate = useNavigate();
  const [form, setForm] = useState(null);
  const [lines, setLines] = useState([]);
  const [details, setDetails] = useState({
    driver_name: "", driver_phone: "", vehicle: "", loaders: "", address: "", note: "",
  });
  const [notify, setNotify] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    const q = new URLSearchParams(Object.entries(source).map(([k, v]) => [k, String(v)])).toString();
    apiFetch(`waybills/new?${q}`)
      .then(f => {
        setForm(f);
        // A receipt: what went out at the sale ("Delivered now") is what is
        // loaded — ticked; what is still to deliver is a later trip, unticked.
        // Deliveries / invoice: still to deliver is ticked with what can go now.
        const anyLeft = f.lines.some(l => !l.handed_over);
        const anyAtSale = f.lines.some(l => l.kind === "at_sale" && l.suggest > 0);
        setLines(f.lines.map(l => ({
          ...l,
          tick: l.kind === "at_sale" ? l.suggest > 0
            : l.kind === "to_deliver" ? (!anyAtSale && l.max > 0)
            : l.handed_over ? !anyLeft : l.max > 0,
          qty: String(l.kind === "at_sale" ? (l.suggest || l.max) : (l.max || 0)),
        })));
        const d = f.details || {};
        setDetails(prev => ({
          ...prev,
          driver_name: d.driver_name || "", driver_phone: d.driver_phone || "",
          vehicle: d.vehicle || "", loaders: d.loaders || "", address: d.address || "",
        }));
      })
      .catch(e => setErr(e.message));
  }, []);

  const set = (k, v) => setDetails(d => ({ ...d, [k]: v }));
  const setLine = (i, k, v) => setLines(ls => ls.map((l, j) => (j === i ? { ...l, [k]: v } : l)));

  async function save() {
    const picked = lines.filter(l => l.tick && Number(l.qty) > 0);
    if (!picked.length) { setErr("Tick at least one item and say how many go on this waybill."); return; }
    for (const l of picked) {
      if (Number(l.qty) > Number(l.max)) {
        setErr(l.handed_over
          ? `Only ${qtyLabel(l.max, l.unit)} of ${l.product} were bought.`
          : `Only ${qtyLabel(l.max, l.unit)} of ${l.product} can go out now — that's what is in the store for this customer.`);
        return;
      }
    }
    setSaving(true); setErr("");
    try {
      const wb = await apiPost("waybills", {
        ...source,
        lines: picked.map(l => (l.key ? { key: l.key, quantity: Number(l.qty) }
                                      : { line_id: l.line_id, quantity: Number(l.qty), kind: l.kind || null })),
        ...Object.fromEntries(Object.entries(details).map(([k, v]) => [k, v.trim() || null])),
        notify,
      });
      navigate(`/waybills/${wb.id}`, { state: { justMade: wb } });
    } catch (e) { setErr(e.message); setSaving(false); }
  }

  const cust = form?.customer;
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 560 }}>
        <div className="modal-header">
          <span className="modal-title">
            Waybill{cust ? ` for ${cust.name}` : ""}{form?.title ? ` · ${form.title}` : ""}
          </span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          {!form && !err && <div className="td-muted">Loading…</div>}
          {form && (
            <>
              <label className="form-label">What goes on this trip</label>
              {lines.length === 0 && <div className="td-muted">Nothing is waiting to be delivered.</div>}
              {lines.map((l, i) => (
                <div key={`${l.line_id ?? l.key}-${l.kind || ""}`} style={{
                  display: "flex", alignItems: "center", gap: 8, padding: "8px 0",
                  borderBottom: "1px solid var(--border)", fontSize: 13,
                }}>
                  <input type="checkbox" checked={l.tick} style={{ width: "auto" }}
                    disabled={!l.handed_over && !(l.max > 0)}
                    onChange={e => setLine(i, "tick", e.target.checked)} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <strong>{l.product}</strong>
                    <div className="td-muted" style={{ fontSize: 12 }}>
                      {l.kind === "at_sale"
                        ? `Delivered now: ${qtyLabel(l.max, l.unit)} of ${qtyLabel(l.bought, l.unit)} — already out of stock`
                          + (l.listed > 0 ? ` · ${qtyLabel(l.listed, l.unit)} already on a waybill` : "")
                        : l.kind === "to_deliver"
                        ? (l.max > 0
                          ? `Still to deliver: ${qtyLabel(l.to_deliver, l.unit)} · ${qtyLabel(l.max, l.unit)} in store for them — tick only if it goes on this trip`
                          : `Still to deliver: ${qtyLabel(l.to_deliver, l.unit)} · none in store yet — add stock first`)
                        : l.handed_over
                        ? `Bought ${qtyLabel(l.bought, l.unit)} · already handed over (listed only)`
                        : l.max > 0
                          ? `${qtyLabel(l.to_deliver, l.unit)} still to deliver · ${qtyLabel(l.max, l.unit)} in store for them`
                          : `${qtyLabel(l.to_deliver, l.unit)} still to deliver · none in store yet — add stock first`}
                    </div>
                  </div>
                  {l.tick && (
                    <input type="number" min={0} max={l.max} inputMode="decimal" value={l.qty}
                      onChange={e => setLine(i, "qty", e.target.value)} style={{ width: 76 }} />
                  )}
                </div>
              ))}

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 12 }}>
                <div>
                  <label className="form-label">Driver</label>
                  <input value={details.driver_name} maxLength={120} onChange={e => set("driver_name", e.target.value)}
                    placeholder="e.g. Musa" style={{ width: "100%" }} />
                </div>
                <div>
                  <label className="form-label">Driver's phone</label>
                  <input value={details.driver_phone} maxLength={40} inputMode="tel"
                    onChange={e => set("driver_phone", e.target.value)} style={{ width: "100%" }} />
                </div>
                <div>
                  <label className="form-label">Vehicle no.</label>
                  <input value={details.vehicle} maxLength={60} onChange={e => set("vehicle", e.target.value)}
                    placeholder="e.g. KJA 123 XY" style={{ width: "100%" }} />
                </div>
                <div>
                  <label className="form-label">Loaders</label>
                  <input value={details.loaders} maxLength={300} onChange={e => set("loaders", e.target.value)}
                    placeholder="e.g. Sule, Tunde" style={{ width: "100%" }} />
                </div>
              </div>
              <label className="form-label" style={{ marginTop: 10 }}>Deliver to (address)</label>
              <input value={details.address} maxLength={300} onChange={e => set("address", e.target.value)}
                style={{ width: "100%" }} />
              <label className="form-label" style={{ marginTop: 10 }}>
                Note <span style={{ opacity: 0.55, fontWeight: 400 }}>(optional)</span>
              </label>
              <input value={details.note} maxLength={300} onChange={e => set("note", e.target.value)}
                style={{ width: "100%" }} />
              {cust?.phone && (
                <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, marginTop: 10, cursor: "pointer" }}>
                  <input type="checkbox" checked={notify} style={{ width: "auto" }}
                    onChange={e => setNotify(e.target.checked)} />
                  Tell {cust.name} on WhatsApp what is on its way
                </label>
              )}
              <span className="form-hint">
                "Delivered now" goods already left stock at the sale. Goods still to deliver leave stock
                only if you tick them here. Printing or sharing again never takes them again. No prices.
              </span>
            </>
          )}
          {err && <div className="modal-error">{err}</div>}
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={save} disabled={saving || !form || !lines.length}>
            {saving ? "Making…" : "Make waybill"}
          </button>
        </div>
      </div>
    </div>
  );
}
