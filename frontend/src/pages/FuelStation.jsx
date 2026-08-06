import { useEffect, useState } from "react";
import { Fuel, Gauge, Droplet, Plus, X } from "lucide-react";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull } from "../lib/format";

const PRODUCTS = ["PMS", "AGO", "DPK", "LPG"];
const TABS = ["Overview", "Shifts", "Deliveries", "Dips"];

function Field({ label, children }) {
  return (
    <label className="form-group" style={{ display: "block" }}>
      <span className="form-label">{label}</span>
      {children}
    </label>
  );
}

function Modal({ title, onClose, children }) {
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header"><span className="modal-title">{title}</span>
          <button className="modal-close" onClick={onClose}>×</button></div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

export default function FuelStation() {
  const [tab, setTab] = useState("Overview");
  const [ov, setOv] = useState(null);
  const [err, setErr] = useState("");

  function loadOverview() {
    apiFetch("fuel/overview").then(setOv).catch(e => setErr(e.message));
  }
  useEffect(loadOverview, []);

  return (
    <div>
      <h1 className="page-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Fuel size={22} /> Fuel Station
      </h1>
      {err && <div className="login-error" style={{ marginBottom: 10 }}>{err}</div>}

      <div className="seg-tabs" style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 14 }}>
        {TABS.map(t => (
          <button key={t} className={`btn btn-sm ${tab === t ? "btn-primary" : "btn-secondary"}`}
                  onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>

      {tab === "Overview" && <Overview ov={ov} reload={loadOverview} />}
      {tab === "Shifts" && <Shifts ov={ov} reloadOverview={loadOverview} />}
      {tab === "Deliveries" && <Deliveries ov={ov} reloadOverview={loadOverview} />}
      {tab === "Dips" && <Dips ov={ov} reloadOverview={loadOverview} />}
    </div>
  );
}

// ── Overview: today, tanks, pumps, prices + setup ────────────────────────────
function Overview({ ov, reload }) {
  const [modal, setModal] = useState(null);  // "tank" | "pump" | "price"

  if (!ov) return <div className="td-muted">Loading…</div>;
  const t = ov.today || {};

  return (
    <>
      <div className="metric-row" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(140px,1fr))", gap: 10, marginBottom: 16 }}>
        <Stat label="Litres sold today" value={(t.litres_sold ?? 0).toLocaleString()} />
        <Stat label="Collected today" value={nairaFull(t.collected || 0)} />
        <Stat label="Shortfall today" value={nairaFull(t.shortfall || 0)} danger={t.shortfall > 0} />
        <Stat label="Open shifts" value={t.open_shifts || 0} />
      </div>

      {/* Prices */}
      <Section title="Pump prices (₦/litre)" action={<button className="btn btn-sm btn-secondary" onClick={() => setModal("price")}><Plus size={13} /> Set price</button>}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {Object.keys(ov.prices || {}).length === 0
            ? <span className="td-muted">No prices set yet.</span>
            : Object.entries(ov.prices).map(([p, v]) => (
              <span key={p} className="chip" style={{ padding: "6px 12px", border: "1px solid var(--border)", borderRadius: 8 }}>
                <strong>{p}</strong> · {nairaFull(v)}
              </span>
            ))}
        </div>
      </Section>

      {/* Tanks */}
      <Section title="Tanks" action={<button className="btn btn-sm btn-secondary" onClick={() => setModal("tank")}><Plus size={13} /> Add tank</button>}>
        {(ov.tanks || []).length === 0 ? <span className="td-muted">No tanks yet.</span> : (
          <div style={{ display: "grid", gap: 8 }}>
            {ov.tanks.map(tk => {
              const pct = tk.capacity_litres ? Math.min(100, Math.round(100 * tk.current_level_litres / tk.capacity_litres)) : 0;
              return (
                <div key={tk.id} className="card" style={{ padding: 12 }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <strong><Droplet size={13} /> {tk.name} · {tk.product}</strong>
                    <span>{(tk.current_level_litres ?? 0).toLocaleString()} L{tk.capacity_litres ? ` / ${tk.capacity_litres.toLocaleString()} L` : ""}</span>
                  </div>
                  {tk.capacity_litres > 0 && (
                    <div style={{ height: 8, background: "var(--surface,#eef)", borderRadius: 6, marginTop: 8 }}>
                      <div style={{ width: `${pct}%`, height: "100%", background: pct < 15 ? "#dc2626" : "#2563eb", borderRadius: 6 }} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Section>

      {/* Pumps */}
      <Section title="Pumps" action={<button className="btn btn-sm btn-secondary" onClick={() => setModal("pump")}><Plus size={13} /> Add pump</button>}>
        {(ov.pumps || []).length === 0 ? <span className="td-muted">No pumps yet.</span> : (
          <div style={{ display: "grid", gap: 6 }}>
            {ov.pumps.map(p => (
              <div key={p.id} style={{ display: "flex", justifyContent: "space-between", padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 8 }}>
                <span><Gauge size={13} /> {p.name} · {p.product}</span>
                <span className="td-muted">meter {(p.current_meter ?? 0).toLocaleString()}</span>
              </div>
            ))}
          </div>
        )}
      </Section>

      {modal === "tank" && <TankModal ov={ov} onClose={() => setModal(null)} onDone={() => { setModal(null); reload(); }} />}
      {modal === "pump" && <PumpModal ov={ov} onClose={() => setModal(null)} onDone={() => { setModal(null); reload(); }} />}
      {modal === "price" && <PriceModal onClose={() => setModal(null)} onDone={() => { setModal(null); reload(); }} />}
    </>
  );
}

function Stat({ label, value, danger }) {
  return (
    <div className="card" style={{ padding: 12 }}>
      <div className="td-muted" style={{ fontSize: 12 }}>{label}</div>
      <div style={{ fontWeight: 800, fontSize: 18, color: danger ? "#dc2626" : "var(--ink)" }}>{value}</div>
    </div>
  );
}
function Section({ title, action, children }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0, fontSize: 15 }}>{title}</h3>{action}
      </div>
      {children}
    </div>
  );
}

function TankModal({ onClose, onDone }) {
  const [f, setF] = useState({ name: "", product: "PMS", capacity_litres: "", current_level_litres: "" });
  const [err, setErr] = useState("");
  const s = (k, v) => setF(p => ({ ...p, [k]: v }));
  async function save() {
    try {
      await apiPost("fuel/tanks", {
        name: f.name, product: f.product,
        capacity_litres: f.capacity_litres ? Number(f.capacity_litres) : null,
        current_level_litres: f.current_level_litres ? Number(f.current_level_litres) : null,
      });
      onDone();
    } catch (e) { setErr(e.message); }
  }
  return (
    <Modal title="Add tank" onClose={onClose}>
      {err && <div className="login-error">{err}</div>}
      <Field label="Name"><input value={f.name} onChange={e => s("name", e.target.value)} placeholder="Tank 1" /></Field>
      <Field label="Product"><select value={f.product} onChange={e => s("product", e.target.value)}>{PRODUCTS.map(p => <option key={p}>{p}</option>)}</select></Field>
      <Field label="Capacity (litres)"><input type="number" value={f.capacity_litres} onChange={e => s("capacity_litres", e.target.value)} placeholder="33000" /></Field>
      <Field label="Current level (litres)"><input type="number" value={f.current_level_litres} onChange={e => s("current_level_litres", e.target.value)} placeholder="0" /></Field>
      <button className="btn btn-primary" style={{ marginTop: 8 }} disabled={!f.name} onClick={save}>Save tank</button>
    </Modal>
  );
}

function PumpModal({ ov, onClose, onDone }) {
  const [f, setF] = useState({ name: "", product: "PMS", tank_id: "", current_meter: "" });
  const [err, setErr] = useState("");
  const s = (k, v) => setF(p => ({ ...p, [k]: v }));
  async function save() {
    try {
      await apiPost("fuel/pumps", {
        name: f.name, product: f.product,
        tank_id: f.tank_id ? Number(f.tank_id) : null,
        current_meter: f.current_meter ? Number(f.current_meter) : null,
      });
      onDone();
    } catch (e) { setErr(e.message); }
  }
  return (
    <Modal title="Add pump" onClose={onClose}>
      {err && <div className="login-error">{err}</div>}
      <Field label="Name"><input value={f.name} onChange={e => s("name", e.target.value)} placeholder="Pump 1" /></Field>
      <Field label="Product"><select value={f.product} onChange={e => s("product", e.target.value)}>{PRODUCTS.map(p => <option key={p}>{p}</option>)}</select></Field>
      <Field label="Tank">
        <select value={f.tank_id} onChange={e => s("tank_id", e.target.value)}>
          <option value="">— none —</option>
          {(ov.tanks || []).map(t => <option key={t.id} value={t.id}>{t.name} ({t.product})</option>)}
        </select>
      </Field>
      <Field label="Opening meter reading"><input type="number" value={f.current_meter} onChange={e => s("current_meter", e.target.value)} placeholder="0" /></Field>
      <button className="btn btn-primary" style={{ marginTop: 8 }} disabled={!f.name} onClick={save}>Save pump</button>
    </Modal>
  );
}

function PriceModal({ onClose, onDone }) {
  const [f, setF] = useState({ product: "PMS", price_per_litre: "" });
  const [err, setErr] = useState("");
  async function save() {
    try { await apiPost("fuel/price", { product: f.product, price_per_litre: Number(f.price_per_litre || 0) }); onDone(); }
    catch (e) { setErr(e.message); }
  }
  return (
    <Modal title="Set pump price" onClose={onClose}>
      {err && <div className="login-error">{err}</div>}
      <Field label="Product"><select value={f.product} onChange={e => setF(p => ({ ...p, product: e.target.value }))}>{PRODUCTS.map(p => <option key={p}>{p}</option>)}</select></Field>
      <Field label="Price per litre (₦)"><input type="number" value={f.price_per_litre} onChange={e => setF(p => ({ ...p, price_per_litre: e.target.value }))} placeholder="750" /></Field>
      <button className="btn btn-primary" style={{ marginTop: 8 }} disabled={!f.price_per_litre} onClick={save}>Save price</button>
    </Modal>
  );
}

// ── Shifts ────────────────────────────────────────────────────────────────────
function Shifts({ ov, reloadOverview }) {
  const [rows, setRows] = useState([]);
  const [modal, setModal] = useState(null);   // "open" | shift(row for close)
  function load() { apiFetch("fuel/shifts").then(d => setRows(d.shifts || [])).catch(() => {}); }
  useEffect(load, []);

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
        <h3 style={{ margin: 0, fontSize: 15 }}>Attendant shifts</h3>
        <button className="btn btn-sm btn-primary" onClick={() => setModal("open")}><Plus size={13} /> Open shift</button>
      </div>
      {rows.length === 0 ? <div className="td-muted">No shifts yet.</div> : (
        <div style={{ display: "grid", gap: 8 }}>
          {rows.map(s => (
            <div key={s.id} className="card" style={{ padding: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <strong>{s.product} · {s.attendant_name || "—"} {s.shift_label ? `(${s.shift_label})` : ""}</strong>
                <span className={`badge ${s.status === "open" ? "" : ""}`} style={{ color: s.status === "open" ? "#d97706" : "var(--muted)" }}>{s.status}</span>
              </div>
              <div className="td-muted" style={{ fontSize: 12, marginTop: 4 }}>
                Meter {(s.opening_meter ?? 0).toLocaleString()}{s.closing_meter != null ? ` → ${s.closing_meter.toLocaleString()}` : ""} · ₦{s.price_per_litre}/L
              </div>
              {s.status === "closed" ? (
                <div style={{ marginTop: 6, fontSize: 13 }}>
                  {(s.litres_sold ?? 0).toLocaleString()} L · expected {nairaFull(s.expected_amount)} · collected {nairaFull((s.cash_amount||0)+(s.pos_amount||0)+(s.transfer_amount||0)+(s.credit_amount||0))}
                  {" · "}<strong style={{ color: s.shortfall > 0 ? "#dc2626" : "#16a34a" }}>
                    {s.shortfall > 0 ? `short ${nairaFull(s.shortfall)}` : s.shortfall < 0 ? `over ${nairaFull(-s.shortfall)}` : "balanced"}
                  </strong>
                </div>
              ) : (
                <button className="btn btn-sm btn-primary" style={{ marginTop: 8 }} onClick={() => setModal(s)}>Close shift</button>
              )}
            </div>
          ))}
        </div>
      )}
      {modal === "open" && <OpenShiftModal ov={ov} onClose={() => setModal(null)} onDone={() => { setModal(null); load(); reloadOverview(); }} />}
      {modal && modal !== "open" && <CloseShiftModal shift={modal} onClose={() => setModal(null)} onDone={() => { setModal(null); load(); reloadOverview(); }} />}
    </>
  );
}

function OpenShiftModal({ ov, onClose, onDone }) {
  const [f, setF] = useState({ pump_id: "", shift_label: "" });
  const [err, setErr] = useState("");
  async function save() {
    try { await apiPost("fuel/shifts/open", { pump_id: Number(f.pump_id), shift_label: f.shift_label || null }); onDone(); }
    catch (e) { setErr(e.message); }
  }
  return (
    <Modal title="Open shift" onClose={onClose}>
      {err && <div className="login-error">{err}</div>}
      <Field label="Pump">
        <select value={f.pump_id} onChange={e => setF(p => ({ ...p, pump_id: e.target.value }))}>
          <option value="">— choose pump —</option>
          {(ov?.pumps || []).map(p => <option key={p.id} value={p.id}>{p.name} ({p.product}) · meter {p.current_meter}</option>)}
        </select>
      </Field>
      <Field label="Shift (optional)"><input value={f.shift_label} onChange={e => setF(p => ({ ...p, shift_label: e.target.value }))} placeholder="day / night" /></Field>
      <div className="td-muted" style={{ fontSize: 12 }}>Opening meter and price are taken from the pump automatically.</div>
      <button className="btn btn-primary" style={{ marginTop: 8 }} disabled={!f.pump_id} onClick={save}>Open shift</button>
    </Modal>
  );
}

function CloseShiftModal({ shift, onClose, onDone }) {
  const [f, setF] = useState({ closing_meter: "", cash_amount: "", pos_amount: "", transfer_amount: "", credit_amount: "" });
  const [err, setErr] = useState("");
  const s = (k, v) => setF(p => ({ ...p, [k]: v }));
  const litres = f.closing_meter ? Math.max(0, Number(f.closing_meter) - (shift.opening_meter || 0)) : 0;
  const expected = Math.round(litres * (shift.price_per_litre || 0));
  const collected = ["cash_amount", "pos_amount", "transfer_amount", "credit_amount"].reduce((a, k) => a + Number(f[k] || 0), 0);
  async function save() {
    try {
      await apiPost(`fuel/shifts/${shift.id}/close`, {
        closing_meter: Number(f.closing_meter),
        cash_amount: Number(f.cash_amount || 0), pos_amount: Number(f.pos_amount || 0),
        transfer_amount: Number(f.transfer_amount || 0), credit_amount: Number(f.credit_amount || 0),
      });
      onDone();
    } catch (e) { setErr(e.message); }
  }
  return (
    <Modal title={`Close shift · ${shift.product}`} onClose={onClose}>
      {err && <div className="login-error">{err}</div>}
      <div className="td-muted" style={{ fontSize: 13, marginBottom: 6 }}>Opening meter {(shift.opening_meter ?? 0).toLocaleString()} · ₦{shift.price_per_litre}/L</div>
      <Field label="Closing meter"><input type="number" value={f.closing_meter} onChange={e => s("closing_meter", e.target.value)} /></Field>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <Field label="Cash (₦)"><input type="number" value={f.cash_amount} onChange={e => s("cash_amount", e.target.value)} /></Field>
        <Field label="POS (₦)"><input type="number" value={f.pos_amount} onChange={e => s("pos_amount", e.target.value)} /></Field>
        <Field label="Transfer (₦)"><input type="number" value={f.transfer_amount} onChange={e => s("transfer_amount", e.target.value)} /></Field>
        <Field label="Credit (₦)"><input type="number" value={f.credit_amount} onChange={e => s("credit_amount", e.target.value)} /></Field>
      </div>
      <div style={{ background: "var(--surface,#f8fafc)", borderRadius: 8, padding: 10, margin: "8px 0", fontSize: 13 }}>
        {litres.toLocaleString()} L · expected <strong>{nairaFull(expected)}</strong> · collected {nairaFull(collected)}{" · "}
        <strong style={{ color: expected - collected > 0 ? "#dc2626" : "#16a34a" }}>
          {expected - collected > 0 ? `short ${nairaFull(expected - collected)}` : expected - collected < 0 ? `over ${nairaFull(collected - expected)}` : "balanced"}
        </strong>
      </div>
      <button className="btn btn-primary" disabled={!f.closing_meter} onClick={save}>Close & reconcile</button>
    </Modal>
  );
}

// ── Deliveries ────────────────────────────────────────────────────────────────
function Deliveries({ ov, reloadOverview }) {
  const [rows, setRows] = useState([]);
  const [modal, setModal] = useState(false);
  function load() { apiFetch("fuel/deliveries").then(d => setRows(d.deliveries || [])).catch(() => {}); }
  useEffect(load, []);
  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
        <h3 style={{ margin: 0, fontSize: 15 }}>Tanker deliveries</h3>
        <button className="btn btn-sm btn-primary" onClick={() => setModal(true)}><Plus size={13} /> Record delivery</button>
      </div>
      {rows.length === 0 ? <div className="td-muted">No deliveries yet.</div> : (
        <div style={{ display: "grid", gap: 6 }}>
          {rows.map(d => (
            <div key={d.id} style={{ display: "flex", justifyContent: "space-between", padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 8 }}>
              <span>{d.product} · {(d.litres ?? 0).toLocaleString()} L{d.supplier ? ` · ${d.supplier}` : ""}</span>
              <span className="td-muted" style={{ fontSize: 12 }}>{d.delivered_at ? new Date(d.delivered_at).toLocaleDateString() : ""}</span>
            </div>
          ))}
        </div>
      )}
      {modal && <DeliveryModal ov={ov} onClose={() => setModal(false)} onDone={() => { setModal(false); load(); reloadOverview(); }} />}
    </>
  );
}

function DeliveryModal({ ov, onClose, onDone }) {
  const [f, setF] = useState({ tank_id: "", litres: "", cost_per_litre: "", supplier: "", waybill: "" });
  const [err, setErr] = useState("");
  const s = (k, v) => setF(p => ({ ...p, [k]: v }));
  async function save() {
    try {
      await apiPost("fuel/deliveries", {
        tank_id: Number(f.tank_id), litres: Number(f.litres),
        cost_per_litre: f.cost_per_litre ? Number(f.cost_per_litre) : null,
        supplier: f.supplier || null, waybill: f.waybill || null,
      });
      onDone();
    } catch (e) { setErr(e.message); }
  }
  return (
    <Modal title="Record delivery" onClose={onClose}>
      {err && <div className="login-error">{err}</div>}
      <Field label="Tank">
        <select value={f.tank_id} onChange={e => s("tank_id", e.target.value)}>
          <option value="">— choose tank —</option>
          {(ov?.tanks || []).map(t => <option key={t.id} value={t.id}>{t.name} ({t.product})</option>)}
        </select>
      </Field>
      <Field label="Litres delivered"><input type="number" value={f.litres} onChange={e => s("litres", e.target.value)} placeholder="33000" /></Field>
      <Field label="Cost per litre (₦, optional)"><input type="number" value={f.cost_per_litre} onChange={e => s("cost_per_litre", e.target.value)} /></Field>
      <Field label="Supplier / depot (optional)"><input value={f.supplier} onChange={e => s("supplier", e.target.value)} /></Field>
      <Field label="Waybill (optional)"><input value={f.waybill} onChange={e => s("waybill", e.target.value)} /></Field>
      <button className="btn btn-primary" style={{ marginTop: 8 }} disabled={!f.tank_id || !f.litres} onClick={save}>Save delivery</button>
    </Modal>
  );
}

// ── Dips ──────────────────────────────────────────────────────────────────────
function Dips({ ov, reloadOverview }) {
  const [rows, setRows] = useState([]);
  const [modal, setModal] = useState(false);
  function load() { apiFetch("fuel/dips").then(d => setRows(d.dips || [])).catch(() => {}); }
  useEffect(load, []);
  const tankName = id => (ov?.tanks || []).find(t => t.id === id)?.name || `Tank ${id}`;
  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
        <h3 style={{ margin: 0, fontSize: 15 }}>Tank dips (variance check)</h3>
        <button className="btn btn-sm btn-primary" onClick={() => setModal(true)}><Plus size={13} /> Record dip</button>
      </div>
      {rows.length === 0 ? <div className="td-muted">No dips yet.</div> : (
        <div style={{ display: "grid", gap: 6 }}>
          {rows.map(d => (
            <div key={d.id} style={{ display: "flex", justifyContent: "space-between", padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 8 }}>
              <span>{tankName(d.tank_id)} · dip {(d.dipped_litres ?? 0).toLocaleString()} L (book {(d.computed_litres ?? 0).toLocaleString()})</span>
              <strong style={{ color: Math.abs(d.variance_litres) > 50 ? "#dc2626" : "#16a34a" }}>
                {d.variance_litres > 0 ? "+" : ""}{(d.variance_litres ?? 0).toLocaleString()} L
              </strong>
            </div>
          ))}
        </div>
      )}
      {modal && <DipModal ov={ov} onClose={() => setModal(false)} onDone={() => { setModal(false); load(); reloadOverview(); }} />}
    </>
  );
}

function DipModal({ ov, onClose, onDone }) {
  const [f, setF] = useState({ tank_id: "", dipped_litres: "", note: "" });
  const [err, setErr] = useState("");
  const s = (k, v) => setF(p => ({ ...p, [k]: v }));
  async function save() {
    try { await apiPost("fuel/dips", { tank_id: Number(f.tank_id), dipped_litres: Number(f.dipped_litres), note: f.note || null }); onDone(); }
    catch (e) { setErr(e.message); }
  }
  return (
    <Modal title="Record tank dip" onClose={onClose}>
      {err && <div className="login-error">{err}</div>}
      <Field label="Tank">
        <select value={f.tank_id} onChange={e => s("tank_id", e.target.value)}>
          <option value="">— choose tank —</option>
          {(ov?.tanks || []).map(t => <option key={t.id} value={t.id}>{t.name} ({t.product}) · book {(t.current_level_litres ?? 0).toLocaleString()} L</option>)}
        </select>
      </Field>
      <Field label="Dipped litres (physical reading)"><input type="number" value={f.dipped_litres} onChange={e => s("dipped_litres", e.target.value)} /></Field>
      <Field label="Note (optional)"><input value={f.note} onChange={e => s("note", e.target.value)} placeholder="morning dip" /></Field>
      <button className="btn btn-primary" style={{ marginTop: 8 }} disabled={!f.tank_id || !f.dipped_litres} onClick={save}>Save dip</button>
    </Modal>
  );
}
