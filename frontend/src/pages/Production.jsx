import { useState, useEffect, useMemo, useRef } from "react";
import { Plus, Trash2 } from "lucide-react";
import { apiFetch, apiPost, apiPut, apiDelete } from "../lib/api";
import { nairaFull, dateTimeStr } from "../lib/format";

/* Production (production.py): recipes, recording what was made — the product
   goes into stock, what it used comes out — and what one really cost. */
export default function Production() {
  const [tab, setTab] = useState("make");
  const [items, setItems] = useState([]);
  const [err, setErr] = useState("");
  function loadItems() {
    return apiFetch("production").then(d => setItems(d.items || [])).catch(e => setErr(e.message));
  }
  useEffect(() => { loadItems(); }, []);

  return (
    <div style={{ display: "grid", gap: 14, maxWidth: 820 }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {[["make", "Record production"], ["recipes", "Recipes"], ["distributors", "Distributors"], ["report", "Report"], ["history", "History"]].map(([k, l]) => (
          <button key={k} className={`btn btn-sm ${tab === k ? "btn-primary" : "btn-ghost"}`} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>
      {err && <div className="pos-error">{err}</div>}
      {tab === "make" && <MakeTab items={items} onDone={loadItems} goRecipes={() => setTab("recipes")} />}
      {tab === "recipes" && <RecipesTab items={items} onChange={loadItems} />}
      {tab === "distributors" && <DistributorsTab items={items} onChange={loadItems} />}
      {tab === "report" && <ReportTab />}
      {tab === "history" && <HistoryTab onChange={loadItems} />}
    </div>
  );
}

const qtyStr = n => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 3 });

function ItemSelect({ items, value, onChange, placeholder, exclude }) {
  return (
    <select value={value || ""} onChange={e => onChange(e.target.value ? Number(e.target.value) : null)}>
      <option value="">{placeholder}</option>
      {items.filter(i => i.id !== exclude).map(i => (
        <option key={i.id} value={i.id}>{i.name}{i.unit ? ` (${i.unit})` : ""}{i.has_recipe ? " ✓" : ""}</option>
      ))}
    </select>
  );
}

/* ── Record what was made ─────────────────────────────────────────────────── */
function MakeTab({ items, onDone, goRecipes }) {
  const [productId, setProductId] = useState(null);
  const [made, setMade] = useState("");
  const [lines, setLines] = useState(null);       // null = from the recipe; edited = what was really used
  const [extra, setExtra] = useState(null);       // null = from the recipe
  const [rawPlan, setPlan] = useState(null);
  const [expiry, setExpiry] = useState("");
  const [note, setNote] = useState("");
  const [anyway, setAnyway] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState("");
  const timer = useRef(null);
  const product = items.find(i => i.id === productId);
  // The plan only counts for what's picked now
  const plan = productId && Number(made) > 0 && rawPlan?.product_id === productId ? rawPlan : null;

  useEffect(() => {
    clearTimeout(timer.current);
    if (!productId || !(Number(made) > 0)) return undefined;
    timer.current = setTimeout(() => {
      apiPost("production/plan", { product_id: productId, made_qty: Number(made), lines, extra_cost: extra })
        .then(p => { setPlan(p); setErr(""); }).catch(e => setErr(e.message));
    }, 300);
    return () => clearTimeout(timer.current);
  }, [productId, made, lines, extra]);

  function pick(id) { setProductId(id); setLines(null); setExtra(null); setAnyway(false); setDone(""); }
  function editLine(itemId, qty) {
    const base = lines ?? (plan?.lines || []).map(l => ({ item_id: l.item_id, qty: l.qty }));
    setLines(base.map(l => l.item_id === itemId ? { ...l, qty: Number(qty) || 0 } : l));
  }

  async function record() {
    setBusy(true); setErr("");
    try {
      const r = await apiPost("production/runs", { product_id: productId, made_qty: Number(made), lines, extra_cost: extra,
        expiry_date: expiry || null, note: note.trim() || null, allow_short: anyway });
      setDone(`Recorded: ${qtyStr(r.made_qty)} ${r.product} in stock${r.cost_per_unit ? `, ${nairaFull(Math.round(r.cost_per_unit))} each to make` : ""}.`);
      setMade(""); setLines(null); setExtra(null); setExpiry(""); setNote(""); setAnyway(false); setPlan(null);
      onDone();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="card" style={{ padding: 16, display: "grid", gap: 12 }}>
      <div className="td-muted" style={{ fontSize: 13 }}>
        What you made goes into stock; what it used comes out of stock. No adjusting each one by hand.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10 }}>
        <div className="form-group">
          <label className="form-label">What did you make?</label>
          <ItemSelect items={items} value={productId} onChange={pick} placeholder="— Pick a product —" />
        </div>
        <div className="form-group">
          <label className="form-label">How many{product?.unit ? ` (${product.unit})` : ""}?</label>
          <input type="number" min="0" step="any" inputMode="decimal" value={made} onChange={e => { setMade(e.target.value); setLines(null); }} placeholder="e.g. 160" />
        </div>
      </div>

      {product && !product.has_recipe && (
        <div className="pos-credit-warn">
          No recipe for {product.name} yet, so nothing is taken out of stock and it has no cost.{" "}
          <button className="btn btn-ghost btn-sm" onClick={goRecipes}>Add its recipe</button>
        </div>
      )}

      {plan && (
        <>
          {plan.lines.length > 0 && (
            <div style={{ overflowX: "auto" }}>
              <table className="data-table" style={{ width: "100%" }}>
                <thead><tr><th>Used</th><th style={{ textAlign: "right" }}>Amount</th><th style={{ textAlign: "right" }}>In stock</th><th style={{ textAlign: "right" }}>Cost</th></tr></thead>
                <tbody>
                  {plan.lines.map(l => (
                    <tr key={l.item_id}>
                      <td>{l.name}</td>
                      <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                        <input type="number" min="0" step="any" value={l.qty} onChange={e => editLine(l.item_id, e.target.value)}
                          style={{ width: 80, textAlign: "right" }} /> {l.unit || ""}
                      </td>
                      <td style={{ textAlign: "right", color: l.short ? "#b91c1c" : undefined }}>{l.in_stock == null ? "—" : qtyStr(l.in_stock)}</td>
                      <td style={{ textAlign: "right" }}>{l.unit_cost ? nairaFull(l.cost) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {plan.batches && <span className="form-hint">{qtyStr(plan.batches)} batch{plan.batches === 1 ? "" : "es"} of the recipe. Change an amount if you used more or less.</span>}
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10 }}>
            <div className="form-group">
              <label className="form-label">Other costs (gas, labour…) ₦</label>
              <input type="number" min="0" step="1" value={extra ?? plan.extra_cost} onChange={e => setExtra(e.target.value === "" ? null : Number(e.target.value))} />
            </div>
            <div className="form-group">
              <label className="form-label">Best before <span className="text-subtle">(optional)</span></label>
              <input type="date" value={expiry} onChange={e => setExpiry(e.target.value)} />
            </div>
          </div>
          <div className="card" style={{ padding: "10px 12px", display: "flex", gap: 16, flexWrap: "wrap", alignItems: "baseline" }}>
            <span>Total cost <strong>{nairaFull(plan.total_cost)}</strong></span>
            {plan.cost_per_unit != null && plan.total_cost > 0 && (
              <span>Each {product?.unit || "one"} costs <strong>{nairaFull(Math.round(plan.cost_per_unit))}</strong> to make
                {product?.selling_price ? <span className="td-muted"> · sells at {nairaFull(product.selling_price)}</span> : null}</span>
            )}
          </div>
          {plan.no_cost_price.length > 0 && (
            <span className="form-hint">No cost price for {plan.no_cost_price.join(", ")} — set it in Inventory so the cost is complete.</span>
          )}
          {plan.short.length > 0 && (
            <div className="pos-credit-warn" style={{ display: "grid", gap: 6 }}>
              <span>Not enough in stock: {plan.short.map(l => `${l.name} (short by ${qtyStr(l.short)})`).join(", ")}. Record the purchase first, or record this anyway — those go to 0.</span>
              <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <input type="checkbox" style={{ width: "auto" }} checked={anyway} onChange={e => setAnyway(e.target.checked)} /> Record anyway
              </label>
            </div>
          )}
          <div className="form-group">
            <label className="form-label">Note <span className="text-subtle">(optional)</span></label>
            <input maxLength={300} value={note} onChange={e => setNote(e.target.value)} placeholder="e.g. Morning bake" />
          </div>
        </>
      )}
      {err && <div className="pos-error">{err}</div>}
      {done && <div className="pos-change">{done}</div>}
      <div>
        <button className="btn btn-primary" disabled={busy || !plan || (plan.short.length > 0 && !anyway)} onClick={record}>
          {busy ? "Recording…" : "Record production"}
        </button>
      </div>
    </div>
  );
}

/* ── Recipes ──────────────────────────────────────────────────────────────── */
function RecipesTab({ items, onChange }) {
  const [editing, setEditing] = useState(null);     // product id
  const withRecipe = items.filter(i => i.has_recipe);
  return (
    <div className="card" style={{ padding: 16, display: "grid", gap: 10 }}>
      <div className="td-muted" style={{ fontSize: 13 }}>
        A recipe says what one batch uses — e.g. 1 bag flour, 2 kg sugar, 0.5 kg yeast and ₦4,000 gas and labour make 80 loaves.
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 220px" }}>
          <ItemSelect items={items} value={null} onChange={id => id && setEditing(id)} placeholder="+ Add or change a recipe for…" />
        </div>
      </div>
      {withRecipe.length === 0 && <div className="td-muted">No recipes yet.</div>}
      {withRecipe.map(i => (
        <div key={i.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderTop: "1px solid var(--line)", paddingTop: 8 }}>
          <span>{i.name}{i.cost_price ? <span className="td-muted" style={{ fontSize: 13 }}> · costs {nairaFull(i.cost_price)} each</span> : null}</span>
          <button className="btn btn-ghost btn-sm" onClick={() => setEditing(i.id)}>Edit</button>
        </div>
      ))}
      {editing && <RecipeModal product={items.find(i => i.id === editing)} items={items}
        onClose={() => setEditing(null)} onSaved={() => { setEditing(null); onChange(); }} />}
    </div>
  );
}

function RecipeModal({ product, items, onClose, onSaved }) {
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => {
    apiFetch(`production/recipe/${product.id}`).then(d => {
      const r = d.recipe;
      setForm(r ? { yield_qty: r.yield_qty, extra_cost: r.extra_cost, note: r.note || "", lines: r.lines.map(l => ({ item_id: l.item_id, qty: l.qty })) }
        : { yield_qty: "", extra_cost: 0, note: "", lines: [{ item_id: null, qty: "" }] });
    }).catch(e => setErr(e.message));
  }, [product.id]);
  const byId = useMemo(() => Object.fromEntries(items.map(i => [i.id, i])), [items]);
  if (!form) return null;

  const setLine = (ix, patch) => setForm({ ...form, lines: form.lines.map((l, i) => i === ix ? { ...l, ...patch } : l) });
  const perBatch = form.lines.reduce((s, l) => s + (Number(l.qty) || 0) * (byId[l.item_id]?.cost_price || 0), 0) + (Number(form.extra_cost) || 0);

  async function save() {
    setBusy(true); setErr("");
    try {
      await apiPut(`production/recipe/${product.id}`, { yield_qty: Number(form.yield_qty), extra_cost: Number(form.extra_cost) || 0,
        note: form.note.trim() || null, lines: form.lines.filter(l => l.item_id).map(l => ({ item_id: l.item_id, qty: Number(l.qty) })) });
      onSaved();
    } catch (e) { setErr(e.message); setBusy(false); }
  }
  async function remove() {
    if (!window.confirm(`Delete the recipe for ${product.name}? Past production stays recorded.`)) return;
    try { await apiDelete(`production/recipe/${product.id}`); onSaved(); } catch (e) { setErr(e.message); }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal modal-wide">
        <div className="modal-header">
          <span className="modal-title">Recipe: {product.name}</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body" style={{ display: "grid", gap: 10 }}>
          <div className="form-group">
            <label className="form-label">One batch makes how many{product.unit ? ` (${product.unit})` : ""}?</label>
            <input type="number" min="0" step="any" value={form.yield_qty} onChange={e => setForm({ ...form, yield_qty: e.target.value })} placeholder="e.g. 80" />
          </div>
          <label className="form-label" style={{ margin: 0 }}>What one batch uses</label>
          {form.lines.map((l, ix) => (
            <div key={ix} style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <ItemSelect items={items} exclude={product.id} value={l.item_id} onChange={id => setLine(ix, { item_id: id })} placeholder="— Material —" />
              </div>
              <input type="number" min="0" step="any" value={l.qty} onChange={e => setLine(ix, { qty: e.target.value })} placeholder="Amount" style={{ width: 90 }} />
              <span className="td-muted" style={{ width: 48, fontSize: 12 }}>{byId[l.item_id]?.unit || ""}</span>
              <button className="pos-remove" onClick={() => setForm({ ...form, lines: form.lines.filter((_, i) => i !== ix) })} aria-label="Remove"><Trash2 size={13} /></button>
            </div>
          ))}
          <div>
            <button className="btn btn-ghost btn-sm" onClick={() => setForm({ ...form, lines: [...form.lines, { item_id: null, qty: "" }] })}><Plus size={13} /> Add material</button>
          </div>
          <span className="form-hint">Materials must be in your stock (add flour, sugar… in Inventory with their cost price).</span>
          <div className="form-group">
            <label className="form-label">Other costs per batch ₦ <span className="text-subtle">(gas, diesel, labour — optional)</span></label>
            <input type="number" min="0" step="1" value={form.extra_cost} onChange={e => setForm({ ...form, extra_cost: e.target.value })} />
          </div>
          {Number(form.yield_qty) > 0 && perBatch > 0 && (
            <div className="card" style={{ padding: "8px 12px" }}>
              One batch costs <strong>{nairaFull(Math.round(perBatch))}</strong> → <strong>{nairaFull(Math.round(perBatch / Number(form.yield_qty)))}</strong> each
              {product.selling_price ? <span className="td-muted"> · sells at {nairaFull(product.selling_price)}</span> : null}
            </div>
          )}
          {err && <div className="modal-error">{err}</div>}
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost" style={{ color: "#b91c1c", marginRight: "auto" }} onClick={remove}>Delete recipe</button>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save recipe"}</button>
        </div>
      </div>
    </div>
  );
}

/* ── Distributors / van sales ─────────────────────────────────────────────── */
const sellerPrice = i => i?.wholesale_price || i?.selling_price || 0;

function SellerPicker({ value, onChange }) {
  const [q, setQ] = useState("");
  const [found, setFound] = useState([]);
  const [newPhone, setNewPhone] = useState("");
  useEffect(() => {
    if (value || q.trim().length < 2) return undefined;
    let live = true;
    const t = setTimeout(() => apiFetch("customers", { q: q.trim() })
      .then(d => { if (live) setFound((d.customers || []).slice(0, 6)); }).catch(() => {}), 250);
    return () => { live = false; clearTimeout(t); };
  }, [q, value]);
  if (value) {
    return (
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <strong>{value.name}</strong>{value.phone && <span className="td-muted">{value.phone}</span>}
        <button className="btn btn-ghost btn-sm" onClick={() => { onChange(null); setQ(""); setFound([]); }}>Change</button>
      </div>
    );
  }
  const typed = q.trim();
  return (
    <div style={{ display: "grid", gap: 6 }}>
      <input value={q} onChange={e => setQ(e.target.value)} placeholder="Seller's name (search your customers)" />
      {typed.length >= 2 && found.map(c => (
        <button key={c.id} className="btn btn-ghost btn-sm" style={{ justifyContent: "flex-start" }}
          onClick={() => onChange({ id: c.id, name: c.name, phone: c.phone })}>
          {c.name}{c.balance > 0 ? ` · owes ${nairaFull(c.balance)}` : ""}
        </button>
      ))}
      {typed.length >= 2 && (
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          <input value={newPhone} onChange={e => setNewPhone(e.target.value)} placeholder="Phone (optional)" inputMode="tel" style={{ flex: "1 1 140px" }} />
          <button className="btn btn-secondary btn-sm" onClick={() => onChange({ id: null, name: typed, phone: newPhone.trim() })}>
            Add “{typed}” as a new seller</button>
        </div>
      )}
    </div>
  );
}

function DistributorsTab({ items, onChange }) {
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [seller, setSeller] = useState(null);
  const [lines, setLines] = useState([{ item_id: null, qty: "", unit_price: "" }]);
  const [settling, setSettling] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const byId = useMemo(() => Object.fromEntries(items.map(i => [i.id, i])), [items]);
  function load(d = days) { apiFetch("distributors", { days: d }).then(setData).catch(e => setErr(e.message)); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(days); }, [days]);

  const setLine = (ix, patch) => setLines(lines.map((l, i) => i === ix ? { ...l, ...patch } : l));
  const outValue = lines.reduce((s, l) => s + (Number(l.qty) || 0) * (l.unit_price === "" ? sellerPrice(byId[l.item_id]) : Number(l.unit_price) || 0), 0);

  async function sendOut() {
    setBusy(true); setErr(""); setMsg("");
    try {
      const r = await apiPost("distributors/send-out", {
        customer_id: seller?.id || null, customer_name: seller && !seller.id ? seller.name : null,
        customer_phone: seller && !seller.id ? (seller.phone || null) : null,
        lines: lines.filter(l => l.item_id && Number(l.qty) > 0).map(l => ({
          item_id: l.item_id, qty: Number(l.qty), unit_price: l.unit_price === "" ? null : Number(l.unit_price) })) });
      setMsg(`Sent out with ${r.seller?.name}: ${nairaFull(r.out_value)} of goods at their price.`);
      setSeller(null); setLines([{ item_id: null, qty: "", unit_price: "" }]);
      load(); onChange();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div className="card" style={{ padding: 16, display: "grid", gap: 10 }}>
        <h3 style={{ margin: 0 }}>Send goods out with a seller</h3>
        <span className="form-hint">The goods leave stock now. When the seller comes back, settle: what's unsold comes back, and they pay for what they sold — the rest is their debt.</span>
        <SellerPicker value={seller} onChange={setSeller} />
        {lines.map((l, ix) => (
          <div key={ix} style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ flex: "2 1 180px", minWidth: 0 }}>
              <ItemSelect items={items} value={l.item_id} onChange={id => setLine(ix, { item_id: id, unit_price: "" })} placeholder="— Product —" />
            </div>
            <input type="number" min="0" step="1" value={l.qty} onChange={e => setLine(ix, { qty: e.target.value })}
              placeholder={byId[l.item_id]?.quantity != null ? `of ${qtyStr(byId[l.item_id].quantity)}` : "How many"} style={{ flex: "1 1 80px" }} />
            <input type="number" min="0" step="1" value={l.unit_price} onChange={e => setLine(ix, { unit_price: e.target.value })}
              placeholder={l.item_id ? `₦${sellerPrice(byId[l.item_id]).toLocaleString()} each` : "Their price"} style={{ flex: "1 1 110px" }}
              title="The seller's price: a lower price for them, or retail less their commission" />
            {lines.length > 1 && <button className="pos-remove" onClick={() => setLines(lines.filter((_, i) => i !== ix))} aria-label="Remove"><Trash2 size={13} /></button>}
          </div>
        ))}
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <button className="btn btn-ghost btn-sm" onClick={() => setLines([...lines, { item_id: null, qty: "", unit_price: "" }])}><Plus size={13} /> Add product</button>
          <span className="form-hint">Their price: your wholesale price unless you type another (retail less their commission comes to the same).</span>
        </div>
        {outValue > 0 && <div>Goods worth <strong>{nairaFull(outValue)}</strong> at their price</div>}
        {err && <div className="pos-error">{err}</div>}
        {msg && <div className="pos-change">{msg}</div>}
        <div><button className="btn btn-primary" disabled={busy || !seller || !lines.some(l => l.item_id && Number(l.qty) > 0)} onClick={sendOut}>
          {busy ? "Sending…" : "Send out"}</button></div>
      </div>

      {!data ? <div className="td-muted">Loading…</div> : (
        <>
          <div className="card" style={{ padding: 16, display: "grid", gap: 8 }}>
            <h3 style={{ margin: 0 }}>Out with sellers now ({data.out.length})</h3>
            {data.out.length === 0 && <div className="td-muted">Nobody has goods out.</div>}
            {data.out.map(r => (
              <div key={r.id} style={{ borderTop: "1px solid var(--line)", paddingTop: 8, display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <div style={{ minWidth: 0 }}>
                  <strong>{r.seller?.name}</strong> <span className="td-muted" style={{ fontSize: 12 }}>since {dateTimeStr(r.created_at)}</span>
                  <div className="td-muted" style={{ fontSize: 13 }}>{r.lines.map(l => `${l.out} ${l.name} @ ${nairaFull(l.unit_price)}`).join(", ")} · {nairaFull(r.out_value)}</div>
                </div>
                <button className="btn btn-primary btn-sm" onClick={() => setSettling(r)}>Settle</button>
              </div>
            ))}
          </div>

          <div className="card" style={{ padding: 16, display: "grid", gap: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <h3 style={{ margin: 0 }}>Sellers</h3>
              <div style={{ display: "flex", gap: 6 }}>
                {[[7, "7 days"], [30, "30 days"], [90, "3 months"]].map(([d, l]) => (
                  <button key={d} className={`btn btn-sm ${days === d ? "btn-primary" : "btn-ghost"}`} onClick={() => { setData(null); setDays(d); }}>{l}</button>
                ))}
              </div>
            </div>
            {data.sellers.length === 0 ? <div className="td-muted">No settled runs in this time.</div> : (
              <div style={{ overflowX: "auto" }}>
                <table className="data-table" style={{ width: "100%" }}>
                  <thead><tr><th>Seller</th><th style={{ textAlign: "right" }}>Took</th><th style={{ textAlign: "right" }}>Back</th>
                    <th style={{ textAlign: "right" }}>Spoilt</th><th style={{ textAlign: "right" }}>Sold</th><th style={{ textAlign: "right" }}>Paid</th><th style={{ textAlign: "right" }}>Owes now</th></tr></thead>
                  <tbody>
                    {data.sellers.map(s => (
                      <tr key={s.seller.id}>
                        <td>{s.seller.name}<div className="td-muted" style={{ fontSize: 12 }}>{s.runs} run{s.runs === 1 ? "" : "s"}</div></td>
                        <td style={{ textAlign: "right" }}>{qtyStr(s.taken)}</td>
                        <td style={{ textAlign: "right" }}>{qtyStr(s.back)}</td>
                        <td style={{ textAlign: "right", color: s.spoilt ? "#b91c1c" : undefined }}>{qtyStr(s.spoilt)}</td>
                        <td style={{ textAlign: "right" }}>{qtyStr(s.sold)}{s.sold_pct != null && <div className="td-muted" style={{ fontSize: 12 }}>{s.sold_pct}% · {nairaFull(s.sold_value)}</div>}</td>
                        <td style={{ textAlign: "right" }}>{nairaFull(s.paid)}</td>
                        <td style={{ textAlign: "right", color: s.seller.owes ? "#b45309" : undefined, fontWeight: 600 }}>{nairaFull(s.seller.owes)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
      {settling && <SettleModal run={settling} onClose={() => setSettling(null)}
        onDone={() => { setSettling(null); load(); onChange(); }} />}
    </div>
  );
}

function SettleModal({ run, onClose, onDone }) {
  const [ret, setRet] = useState(() => Object.fromEntries(run.lines.map(l => [l.id, { back: "", spoilt: "" }])));
  const [reason, setReason] = useState("expired");
  const [paid, setPaid] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState(null);
  const sold = l => l.out - (Number(ret[l.id].back) || 0) - (Number(ret[l.id].spoilt) || 0);
  const value = run.lines.reduce((s, l) => s + Math.max(0, sold(l)) * l.unit_price, 0);
  const paidNum = paid === "" ? value : Number(paid) || 0;

  async function save() {
    setBusy(true); setErr("");
    try {
      const r = await apiPost(`distributors/runs/${run.id}/settle`, {
        returns: Object.fromEntries(Object.entries(ret).map(([k, v]) => [k, { back: Number(v.back) || 0, spoilt: Number(v.spoilt) || 0 }])),
        paid: paidNum, due_date: paidNum < value && due ? due : null, spoilt_reason: reason });
      setDone(r);
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && (done ? onDone() : onClose())}>
      <div className="modal modal-wide">
        <div className="modal-header">
          <span className="modal-title">Settle: {run.seller?.name}</span>
          <button className="modal-close" onClick={done ? onDone : onClose}>×</button>
        </div>
        {done ? (
          <>
            <div className="modal-body" style={{ display: "grid", gap: 8 }}>
              <div className="pos-change">Settled. Sold {nairaFull(done.sold_value)}, paid {nairaFull(done.paid)}.</div>
              {done.owed_now > 0 && <div>{done.seller?.name} owes {nairaFull(done.owed_now)} for this run — it's on their debts with reminders.</div>}
            </div>
            <div className="modal-footer">
              {done.receipt_id && <a className="btn btn-secondary" href={`/app/pos/receipt/${done.receipt_id}`}>Receipt</a>}
              <button className="btn btn-primary" onClick={onDone}>Done</button>
            </div>
          </>
        ) : (
          <>
            <div className="modal-body" style={{ display: "grid", gap: 10 }}>
              <div style={{ overflowX: "auto" }}>
                <table className="data-table" style={{ width: "100%" }}>
                  <thead><tr><th>Product</th><th style={{ textAlign: "right" }}>Took</th><th style={{ textAlign: "right" }}>Back, good</th>
                    <th style={{ textAlign: "right" }}>Back, spoilt</th><th style={{ textAlign: "right" }}>Sold</th></tr></thead>
                  <tbody>
                    {run.lines.map(l => (
                      <tr key={l.id}>
                        <td>{l.name}<div className="td-muted" style={{ fontSize: 12 }}>@ {nairaFull(l.unit_price)}</div></td>
                        <td style={{ textAlign: "right" }}>{l.out}</td>
                        <td style={{ textAlign: "right" }}><input type="number" min="0" step="1" value={ret[l.id].back} placeholder="0" style={{ width: 70, textAlign: "right" }}
                          onChange={e => setRet({ ...ret, [l.id]: { ...ret[l.id], back: e.target.value } })} /></td>
                        <td style={{ textAlign: "right" }}><input type="number" min="0" step="1" value={ret[l.id].spoilt} placeholder="0" style={{ width: 70, textAlign: "right" }}
                          onChange={e => setRet({ ...ret, [l.id]: { ...ret[l.id], spoilt: e.target.value } })} /></td>
                        <td style={{ textAlign: "right", fontWeight: 600, color: sold(l) < 0 ? "#b91c1c" : undefined }}>{sold(l)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {run.lines.some(l => Number(ret[l.id].spoilt) > 0) && (
                <div className="form-group">
                  <label className="form-label">Why can't the spoilt ones be sold?</label>
                  <select value={reason} onChange={e => setReason(e.target.value)}>
                    <option value="expired">Stale / expired</option>
                    <option value="damaged">Damaged</option>
                    <option value="stolen">Missing</option>
                    <option value="other">Other</option>
                  </select>
                </div>
              )}
              <div>Sold: <strong>{nairaFull(value)}</strong></div>
              <div className="form-group">
                <label className="form-label">Paid now ₦</label>
                <input type="number" min="0" step="1" value={paid} onChange={e => setPaid(e.target.value)} placeholder={String(value)} />
              </div>
              {paidNum < value && (
                <>
                  <div className="pos-credit-warn">{nairaFull(value - paidNum)} goes on {run.seller?.name}'s debts.</div>
                  <div className="form-group">
                    <label className="form-label">Pay by <span className="text-subtle">(optional, for reminders)</span></label>
                    <input type="date" value={due} onChange={e => setDue(e.target.value)} />
                  </div>
                </>
              )}
              {err && <div className="modal-error">{err}</div>}
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
              <button className="btn btn-primary" onClick={save} disabled={busy || run.lines.some(l => sold(l) < 0)}>{busy ? "Saving…" : "Settle"}</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* ── Report: made / sold / removed, and the materials check ─────────────── */
function ReportTab() {
  const [days, setDays] = useState(7);
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let live = true;
    apiFetch("production/report", { days }).then(d => { if (live) setData(d); }).catch(e => live && setErr(e.message));
    return () => { live = false; };
  }, [days]);
  const pick = d => { setData(null); setDays(d); };

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {[[1, "Today"], [7, "7 days"], [30, "30 days"], [90, "3 months"]].map(([d, l]) => (
          <button key={d} className={`btn btn-sm ${days === d ? "btn-primary" : "btn-ghost"}`} onClick={() => pick(d)}>{l}</button>
        ))}
      </div>
      {err && <div className="pos-error">{err}</div>}
      {!data ? <div className="td-muted">Loading…</div> : data.products.length === 0 ? (
        <div className="card td-muted" style={{ padding: 16 }}>Nothing made in this time.</div>
      ) : (
        <>
          <div className="card" style={{ padding: 16, display: "grid", gap: 8 }}>
            <h3 style={{ margin: 0 }}>Made, sold and removed</h3>
            <span className="form-hint">Sold and removed count everything in the period, including from stock made before it. Sold includes what sellers sold, once settled.</span>
            <div style={{ overflowX: "auto" }}>
              <table className="data-table" style={{ width: "100%" }}>
                <thead><tr><th>Product</th><th style={{ textAlign: "right" }}>Made</th><th style={{ textAlign: "right" }}>Sold</th>
                  <th style={{ textAlign: "right" }}>Removed</th><th style={{ textAlign: "right" }}>Left now</th></tr></thead>
                <tbody>
                  {data.products.map(p => (
                    <tr key={p.product_id}>
                      <td>{p.product}{p.cost_per_unit ? <div className="td-muted" style={{ fontSize: 12 }}>{nairaFull(Math.round(p.cost_per_unit))} each to make</div> : null}</td>
                      <td style={{ textAlign: "right" }}>{qtyStr(p.made)}</td>
                      <td style={{ textAlign: "right" }}>{qtyStr(p.sold)}{p.sold_pct != null && <div className="td-muted" style={{ fontSize: 12 }}>{p.sold_pct}%</div>}</td>
                      <td style={{ textAlign: "right", color: p.removed_pct >= 10 ? "#b91c1c" : undefined }}>
                        {qtyStr(p.removed)}{p.removed > 0 && <div className="td-muted" style={{ fontSize: 12 }}>
                          {p.removed_pct}% · {p.removed_why.map(w => w.label.toLowerCase()).join(", ")}{p.removed_value ? ` · ${nairaFull(p.removed_value)}` : ""}</div>}
                      </td>
                      <td style={{ textAlign: "right" }}>{p.in_stock == null ? "—" : qtyStr(p.in_stock)}{p.with_sellers > 0 && <div className="td-muted" style={{ fontSize: 12 }}>+{qtyStr(p.with_sellers)} with sellers</div>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {data.materials.length > 0 && (
            <div className="card" style={{ padding: 16, display: "grid", gap: 8 }}>
              <h3 style={{ margin: 0 }}>Materials: used vs the recipe</h3>
              <span className="form-hint">What production used against what your recipes say it should, for what came out. Using more than the recipe means waste, a wrong recipe, or material going missing.</span>
              <div style={{ overflowX: "auto" }}>
                <table className="data-table" style={{ width: "100%" }}>
                  <thead><tr><th>Material</th><th style={{ textAlign: "right" }}>Used</th><th style={{ textAlign: "right" }}>Recipe says</th>
                    <th style={{ textAlign: "right" }}>Difference</th><th style={{ textAlign: "right" }}>Removed</th></tr></thead>
                  <tbody>
                    {data.materials.map(m => {
                      const over = m.difference > 0;
                      return (
                        <tr key={m.item_id}>
                          <td>{m.name}{m.unit ? <span className="td-muted"> ({m.unit})</span> : null}</td>
                          <td style={{ textAlign: "right" }}>{qtyStr(m.used)}</td>
                          <td style={{ textAlign: "right" }}>{m.expected == null ? "—" : qtyStr(m.expected)}</td>
                          <td style={{ textAlign: "right", color: over ? "#b91c1c" : m.difference < 0 ? "#166534" : undefined, fontWeight: over ? 700 : undefined }}>
                            {m.difference == null ? "not in recipe" : m.difference === 0 ? "as recipe" : `${over ? "+" : ""}${qtyStr(m.difference)}`}
                            {m.difference ? <div style={{ fontSize: 12, fontWeight: 400 }}>{m.difference_pct > 0 ? "+" : ""}{m.difference_pct}%{m.difference_value ? ` · ${nairaFull(Math.abs(m.difference_value))}` : ""}</div> : null}
                          </td>
                          <td style={{ textAlign: "right" }}>{m.removed ? `${qtyStr(m.removed)}${m.removed_value ? ` · ${nairaFull(m.removed_value)}` : ""}` : "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {data.materials.some(m => m.difference > 0) && (
                <div className="pos-credit-warn">
                  {data.materials.filter(m => m.difference > 0).map(m =>
                    `${qtyStr(m.difference)} ${m.unit || ""} more ${m.name.toLowerCase()} than the recipe needs`.replace(/\s+/g, " ")).join("; ")}
                  {" "}— check the recipe, or where it went.
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* ── History ──────────────────────────────────────────────────────────────── */
function HistoryTab({ onChange }) {
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  function load(d = days) {
    apiFetch("production/runs", { days: d }).then(setData).catch(e => setErr(e.message));
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(days); }, [days]);

  async function undo(r) {
    if (!window.confirm(`Undo "${qtyStr(r.made_qty)} ${r.product}"? They come out of stock and the materials go back.`)) return;
    try { await apiPost(`production/runs/${r.id}/undo`, {}); load(); onChange(); } catch (e) { setErr(e.message); }
  }

  return (
    <div className="card" style={{ padding: 16, display: "grid", gap: 10 }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {[[7, "7 days"], [30, "30 days"], [90, "3 months"]].map(([d, l]) => (
          <button key={d} className={`btn btn-sm ${days === d ? "btn-primary" : "btn-ghost"}`} onClick={() => setDays(d)}>{l}</button>
        ))}
      </div>
      {err && <div className="pos-error">{err}</div>}
      {!data ? <div className="td-muted">Loading…</div> : (
        <>
          {data.totals.length > 0 && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {data.totals.map(t => (
                <div key={t.product} className="card" style={{ padding: "8px 12px" }}>
                  <div className="td-muted" style={{ fontSize: 12 }}>{t.product}</div>
                  <strong>{qtyStr(t.made)}{t.unit ? ` ${t.unit}` : ""}</strong>
                  {t.cost_per_unit ? <span className="td-muted" style={{ fontSize: 12 }}> · {nairaFull(Math.round(t.cost_per_unit))} each</span> : null}
                </div>
              ))}
            </div>
          )}
          {data.runs.length === 0 && <div className="td-muted">Nothing made in this time.</div>}
          {data.runs.map(r => (
            <div key={r.id} style={{ borderTop: "1px solid var(--line)", paddingTop: 8, display: "grid", gap: 2, opacity: r.undone ? 0.55 : 1 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                <strong>{qtyStr(r.made_qty)} {r.product}{r.undone && " · undone"}</strong>
                <span className="td-muted" style={{ fontSize: 12 }}>{dateTimeStr(r.created_at)}{r.by ? ` · ${r.by}` : ""}</span>
              </div>
              <div className="td-muted" style={{ fontSize: 13 }}>
                {r.lines.map(l => `${qtyStr(l.qty)} ${l.unit || ""} ${l.name}`.replace(/\s+/g, " ")).join(", ") || "No materials recorded"}
                {r.total_cost > 0 && ` · cost ${nairaFull(r.total_cost)}${r.cost_per_unit ? ` (${nairaFull(Math.round(r.cost_per_unit))} each)` : ""}`}
                {r.note && ` · ${r.note}`}
              </div>
              {!r.undone && <div><button className="btn btn-ghost btn-sm" onClick={() => undo(r)}>Undo</button></div>}
            </div>
          ))}
        </>
      )}
    </div>
  );
}
