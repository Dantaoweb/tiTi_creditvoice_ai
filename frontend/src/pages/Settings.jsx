import { useEffect, useState } from "react";
import { ArrowUp, ArrowDown, Pencil, Check, X } from "lucide-react";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull } from "../lib/format";
import { saveBusiness, saveDisplay, useSettings } from "../lib/settings";
import { useAuth } from "../context/AuthContext";
import PrintHeader, { PrintBank } from "../components/PrintHeader";
import { paperClass } from "../lib/print";

/* Settings people choose for themselves. "My display" is each person's own;
   the business sections are for the owner and authorised staff. Every default
   is how the app worked before, so nothing changes until someone chooses. */

function Seg({ value, options, onChange }) {
  return (
    <div className="seg" role="radiogroup">
      {options.map(([v, label]) => (
        <button key={String(v)} type="button" role="radio" aria-checked={value === v}
          className={value === v ? "on" : ""} onClick={() => onChange(v)}>{label}</button>
      ))}
    </div>
  );
}

function Row({ title, hint, children }) {
  return (
    <div className="settings-row">
      <div className="settings-row-text"><strong>{title}</strong>{hint && <span>{hint}</span>}</div>
      <div>{children}</div>
    </div>
  );
}

function useSaver(fn) {
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  async function save(changes) {
    setErr("");
    try { await fn(changes); setMsg("Saved ✓"); setTimeout(() => setMsg(""), 1500); }
    catch (e) { setErr(e.message); }
  }
  return { save, msg, err };
}

function DisplaySection({ display }) {
  const d = { text_size: "normal", theme: "light", density: "comfortable", scan_mode: "keep", ...(display || {}) };
  const { save, msg, err } = useSaver(saveDisplay);
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">My display</span>
        <span className="td-muted" style={{ fontSize: 12 }}>{msg || "Just for you, on every device you use"}</span>
      </div>
      <div className="card-body" style={{ paddingTop: 4, paddingBottom: 4 }}>
        {err && <div className="modal-error">{err}</div>}
        <Row title="Text size" hint="Makes everything bigger or smaller — text, buttons and icons.">
          <Seg value={d.text_size} onChange={v => save({ text_size: v })}
            options={[["small", "Small"], ["normal", "Normal"], ["large", "Large"], ["xlarge", "Extra large"]]} />
        </Row>
        <Row title="Theme" hint="Dark is easier on the eyes at night and saves battery on many phones.">
          <Seg value={d.theme} onChange={v => save({ theme: v })}
            options={[["light", "Light"], ["dark", "Dark"], ["system", "Follow my phone"]]} />
        </Row>
        <Row title="List style" hint="Compact fits more rows on the screen; comfortable gives bigger rows to tap.">
          <Seg value={d.density} onChange={v => save({ density: v })}
            options={[["compact", "Compact"], ["comfortable", "Comfortable"]]} />
        </Row>
        <Row title="Phone camera scanning"
          hint="Tap to scan reads one barcode and closes the camera. From a photo uses your phone's own Camera app — safest for phones that switch off or get hot. A USB or Bluetooth scanner is not affected.">
          <Seg value={d.scan_mode} onChange={v => save({ scan_mode: v })}
            options={[["tap", "Tap to scan"], ["keep", "Keep scanning"], ["photo", "From a photo"]]} />
        </Row>
      </div>
    </div>
  );
}

function StockSection({ business }) {
  const { save, msg, err } = useSaver(saveBusiness);
  const [warnDays, setWarnDays] = useState(business.expiry_warn_days ?? 30);
  const [low, setLow] = useState(business.default_low_stock ?? "");
  useEffect(() => { setLow(business.default_low_stock ?? ""); }, [business.default_low_stock]);
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Stock</span>
        <span className="td-muted" style={{ fontSize: 12 }}>{msg || "For everyone in your business"}</span>
      </div>
      <div className="card-body" style={{ paddingTop: 4, paddingBottom: 4 }}>
        {err && <div className="modal-error">{err}</div>}
        <Row title="Group stock by category" hint="Shows your products in groups (Drinks, Provisions…) instead of one long list.">
          <Seg value={business.group_by_category} onChange={v => save({ group_by_category: v })}
            options={[[false, "Off"], [true, "On"]]} />
        </Row>
        {business.group_by_category && (
          <Row title="Where grouping shows" hint="At the till, tap a category, then the product — faster with many products.">
            <Seg value={business.group_on_pos} onChange={v => save({ group_on_pos: v })}
              options={[[false, "Inventory only"], [true, "Inventory and POS"]]} />
          </Row>
        )}
        <Row title="New categories come from" hint="tiTi can pick one from the product's name when it's added; you can always change it.">
          <Seg value={business.category_source} onChange={v => save({ category_source: v })}
            options={[["manual", "I type them"], ["suggest", "tiTi suggests"]]} />
        </Row>
        <Row title="Low-stock alert for new products" hint="New products warn you when they fall to this number. Leave empty for none.">
          <div style={{ display: "flex", gap: 6 }}>
            <input type="number" min={0} value={low} onChange={e => setLow(e.target.value)}
              placeholder="none" style={{ width: 90 }} />
            <button type="button" className="btn btn-secondary btn-sm"
              onClick={() => save({ default_low_stock: low === "" ? null : Number(low) })}>Save</button>
          </div>
        </Row>
        <Row title="Allow selling more than you have in store"
          hint={business.allow_negative_stock
            ? "On: a sale can go past what's in store — for a named customer the rest is kept as still to deliver; a walk-in sale just sells. Only changes new sales."
            : "Off (the default): you can't sell more than you have — out-of-stock products can't be tapped at the till. Turn on only if you sell goods you'll deliver later."}>
          <Seg value={business.allow_negative_stock} onChange={v => save({ allow_negative_stock: v })}
            options={[[true, "Yes"], [false, "No"]]} />
        </Row>
        <Row title="Keep goods aside for customers who have not collected"
          hint="Yes: goods a customer bought but left in the store are kept aside — no one else can buy them. No: they stay free to sell until you keep them aside yourself (Deliveries or Add stock).">
          <Seg value={business.keep_aside} onChange={v => save({ keep_aside: v })}
            options={[[true, "Yes"], [false, "No"]]} />
        </Row>
        <Row title="Warn me before goods expire"
          hint={`tiTi tells you about goods that expire within ${business.expiry_warn_days} days, and marks them in Inventory. Food sellers often use 7.`}>
          <div style={{ display: "flex", gap: 6 }}>
            <input type="number" min={1} max={365} value={warnDays} onChange={e => setWarnDays(e.target.value)} style={{ width: 80 }} />
            <span style={{ alignSelf: "center", fontSize: 13 }}>days</span>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => save({ expiry_warn_days: Number(warnDays) })}>Save</button>
          </div>
        </Row>
        <Row title="Stock count: hide the app's numbers while counting"
          hint={business.count_blind ? "Counters see only empty boxes, so they count what's really there instead of copying." : "Counters see what the app says next to each box."}>
          <Seg value={business.count_blind} onChange={v => save({ count_blind: v })}
            options={[[true, "Hide (blind)"], [false, "Show"]]} />
        </Row>
        <Row title='Show "Not all goods delivered now" when selling' hint="For goods a customer pays for but collects in parts.">
          <Seg value={business.show_part_delivery} onChange={v => save({ show_part_delivery: v })}
            options={[[true, "Yes"], [false, "No"]]} />
        </Row>
      </div>
    </div>
  );
}

function CategoriesSection({ business }) {
  const [cats, setCats] = useState(null);
  const [err, setErr] = useState("");
  const [editing, setEditing] = useState(null);
  const [newName, setNewName] = useState("");
  const [assignTo, setAssignTo] = useState("");
  const [q, setQ] = useState("");
  const [found, setFound] = useState([]);
  const [picked, setPicked] = useState(new Set());
  const [suggest, setSuggest] = useState(null);
  const [msg, setMsg] = useState("");
  const [adding, setAdding] = useState("");

  const load = () => apiFetch("categories").then(d => setCats(d.categories || [])).catch(e => setErr(e.message));
  useEffect(() => { load(); }, []);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) { setFound([]); return; }
    const t = setTimeout(() => {
      apiFetch("inventory", { q: term, limit: 40 }).then(d => setFound(d.items || [])).catch(() => {});
    }, 300);
    return () => clearTimeout(t);
  }, [q]);

  const named = (cats || []).filter(c => c.name && !c.is_service);
  const note = text => { setMsg(text); setTimeout(() => setMsg(""), 2500); };

  async function move(i, dir) {
    const order = named.map(c => c.name);
    const j = i + dir;
    if (j < 0 || j >= order.length) return;
    [order[i], order[j]] = [order[j], order[i]];
    try { await saveBusiness({ category_order: order }); load(); } catch (e) { setErr(e.message); }
  }
  async function addCats() {
    try {
      const r = await apiPost("categories/add", { names: [adding] });
      setCats(r.categories); setAdding(""); note(r.added ? `${r.added} categor${r.added > 1 ? "ies" : "y"} added.` : "Already on your list.");
    } catch (e) { setErr(e.message); }
  }
  async function remove(name) {
    try { const r = await apiPost("categories/delete", { name }); setCats(r.categories); note("Category removed."); }
    catch (e) { setErr(e.message); }
  }
  async function onlyList(v) {
    try { await saveBusiness({ category_only_list: v }); } catch (e) { setErr(e.message); }
  }
  async function rename(old) {
    try {
      const r = await apiPost("categories/rename", { old, new: newName });
      setCats(r.categories); setEditing(null); note(`Renamed — ${r.renamed} product(s) moved.`);
    } catch (e) { setErr(e.message); }
  }
  async function assign() {
    if (!picked.size) { setErr("Tick the products to move."); return; }
    try {
      const r = await apiPost("categories/assign", { item_ids: [...picked], category: assignTo.trim() || null });
      setCats(r.categories); setPicked(new Set()); setQ(""); note(`${r.assigned} product(s) moved.`);
    } catch (e) { setErr(e.message); }
  }
  async function loadSuggestions() {
    try {
      const r = await apiFetch("categories/auto");
      setSuggest({ ...r, keep: new Set(r.suggestions.map(s => s.id)) });
    } catch (e) { setErr(e.message); }
  }
  async function applySuggestions() {
    const items = suggest.suggestions.filter(s => suggest.keep.has(s.id)).map(s => ({ id: s.id, category: s.category }));
    try {
      const r = await apiPost("categories/auto", { items });
      setCats(r.categories); setSuggest(null); note(`${r.applied} product(s) given a category.`);
    } catch (e) { setErr(e.message); }
  }

  const uncategorised = (cats || []).find(c => !c.name);
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Manage categories</span>
        <span className="td-muted" style={{ fontSize: 12 }}>{msg || (business.group_by_category ? "" : "Turn on grouping above to see them on Inventory")}</span>
      </div>
      <div className="card-body">
        {err && <div className="modal-error" onClick={() => setErr("")}>{err}</div>}
        {!cats && <p className="td-muted">Loading…</p>}
        {cats && named.length === 0 && <p className="td-muted">No categories yet — add some below, then pick them when you add a product.</p>}
        {named.map((c, i) => (
          <div key={c.name} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
            <div style={{ display: "flex", flexDirection: "column" }}>
              <button type="button" className="link-btn" aria-label="Move up" onClick={() => move(i, -1)} disabled={i === 0}><ArrowUp size={13} /></button>
              <button type="button" className="link-btn" aria-label="Move down" onClick={() => move(i, 1)} disabled={i === named.length - 1}><ArrowDown size={13} /></button>
            </div>
            {editing === c.name ? (
              <>
                <input value={newName} onChange={e => setNewName(e.target.value)} autoFocus style={{ flex: 1 }} />
                <button type="button" className="btn btn-primary btn-xs" onClick={() => rename(c.name)}><Check size={13} /></button>
                <button type="button" className="btn btn-ghost btn-xs" onClick={() => setEditing(null)}><X size={13} /></button>
              </>
            ) : (
              <>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <strong>{c.label}</strong>
                  <span className="td-muted" style={{ fontSize: 12 }}> · {c.count} product{c.count !== 1 ? "s" : ""}{c.value ? ` · ${nairaFull(c.value)} in stock` : ""}</span>
                </span>
                <button type="button" className="btn btn-ghost btn-xs" onClick={() => { setEditing(c.name); setNewName(c.label); }}>
                  <Pencil size={12} /> Rename
                </button>
                {c.count === 0 && (
                  <button type="button" className="btn btn-ghost btn-xs" style={{ color: "#b91c1c" }} aria-label="Delete"
                    onClick={() => remove(c.name)}><X size={12} /></button>
                )}
              </>
            )}
          </div>
        ))}
        <div style={{ display: "flex", gap: 6, padding: "10px 0 4px" }}>
          <input value={adding} onChange={e => setAdding(e.target.value)} placeholder="Add categories, e.g. Drinks, Provisions, Toiletries"
            onKeyDown={e => { if (e.key === "Enter" && adding.trim()) { e.preventDefault(); addCats(); } }} style={{ flex: 1, minWidth: 0 }} />
          <button type="button" className="btn btn-secondary btn-sm" onClick={addCats} disabled={!adding.trim()}>+ Add</button>
        </div>
        <span className="form-hint">Separate several with commas. They show on Add product even before any product is in them.</span>
        <Row title="Only categories from my list"
          hint={business.category_only_list
            ? "On: staff pick a category from this list when they add a product. Only you can make a new one there."
            : "Off: anyone adding a product can pick from the list or type a new category (it joins the list)."}>
          <Seg value={!!business.category_only_list} onChange={onlyList} options={[[true, "On"], [false, "Off"]]} />
        </Row>

        {uncategorised && (
          <div className="td-muted" style={{ fontSize: 13, padding: "8px 0" }}>
            {uncategorised.count} product{uncategorised.count !== 1 ? "s have" : " has"} no category yet.{" "}
            <button type="button" className="link-btn" onClick={loadSuggestions}>Let tiTi suggest categories</button>
          </div>
        )}

        {suggest && (
          <div style={{ border: "1px dashed var(--line)", borderRadius: 8, padding: 10, marginTop: 8 }}>
            {suggest.suggestions.length === 0 ? (
              <p className="td-muted" style={{ fontSize: 13 }}>tiTi has no suggestion for these product names — put them into categories yourself below.</p>
            ) : (
              <>
                <p style={{ fontSize: 13, margin: "0 0 6px" }}>tiTi suggests a category for {suggest.suggestions.length} product(s). Untick any that are wrong:</p>
                <div style={{ maxHeight: 260, overflowY: "auto" }}>
                  {suggest.suggestions.map(s => (
                    <label key={s.id} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, padding: "3px 0" }}>
                      <input type="checkbox" style={{ width: "auto" }} checked={suggest.keep.has(s.id)}
                        onChange={e => setSuggest(p => { const k = new Set(p.keep); e.target.checked ? k.add(s.id) : k.delete(s.id); return { ...p, keep: k }; })} />
                      {s.name} → <strong>{s.category.replace(/\b\w/g, c => c.toUpperCase())}</strong>
                    </label>
                  ))}
                </div>
                <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                  <button type="button" className="btn btn-primary btn-sm" onClick={applySuggestions}>Apply {suggest.keep.size}</button>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSuggest(null)}>Cancel</button>
                </div>
              </>
            )}
          </div>
        )}

        <div style={{ marginTop: 16 }}>
          <label className="form-label">Put products into a category</label>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
            <input placeholder="Find products…" value={q} onChange={e => setQ(e.target.value)} style={{ flex: "1 1 180px" }} />
            <input list="cv-cats" placeholder="Category (new or existing)" value={assignTo}
              onChange={e => setAssignTo(e.target.value)} style={{ flex: "1 1 180px" }} />
            <datalist id="cv-cats">{named.map(c => <option key={c.name} value={c.label} />)}</datalist>
            <button type="button" className="btn btn-primary btn-sm" onClick={assign} disabled={!picked.size}>
              Move {picked.size || ""}
            </button>
          </div>
          {found.length > 0 && (
            <div style={{ maxHeight: 240, overflowY: "auto", marginTop: 8 }}>
              {found.map(it => (
                <label key={it.id} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, padding: "3px 0" }}>
                  <input type="checkbox" style={{ width: "auto" }} checked={picked.has(it.id)}
                    onChange={e => setPicked(p => { const n = new Set(p); e.target.checked ? n.add(it.id) : n.delete(it.id); return n; })} />
                  <span style={{ textTransform: "capitalize" }}>{it.name}</span>
                  <span className="td-muted" style={{ fontSize: 12 }}>{it.category ? `· ${it.category}` : "· no category"}</span>
                </label>
              ))}
            </div>
          )}
          <span className="form-hint">Leave the category empty to take products out of their category.</span>
        </div>
      </div>
    </div>
  );
}

// VAT: off unless the business turns it on, then they choose how prices work
function VatSection({ business }) {
  const { save, msg, err } = useSaver(saveBusiness);
  const [rate, setRate] = useState(business.vat_rate ?? 7.5);
  const [number, setNumber] = useState(business.vat_number || "");
  const [collected, setCollected] = useState(null);
  useEffect(() => {
    if (business.vat_enabled) apiFetch("reports/vat").then(setCollected).catch(() => setCollected(null));
  }, [business.vat_enabled]);
  const on = !!business.vat_enabled;
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">VAT</span>
        <span className="td-muted" style={{ fontSize: 12 }}>{msg}</span>
      </div>
      <div className="card-body" style={{ paddingTop: 4, paddingBottom: 4 }}>
        {err && <div className="modal-error">{err}</div>}
        <Row title="I charge VAT"
          hint={on ? "VAT shows on sales, receipts, invoices and quotations." : "Off: no VAT anywhere. Turn on only if your business is registered to charge VAT."}>
          <Seg value={on} onChange={v => save({ vat_enabled: v })} options={[[false, "No"], [true, "Yes"]]} />
        </Row>
        {on && (
          <>
            <Row title="My prices"
              hint={business.vat_mode === "inclusive"
                ? `Already include VAT: a ₦10,750 price stays ₦10,750 — the receipt shows the VAT inside it (₦750).`
                : `Are before VAT: a ₦10,000 price becomes ₦10,000 + VAT ${business.vat_rate}% = ₦${(10000 * (1 + business.vat_rate / 100)).toLocaleString()} at the till.`}>
              <Seg value={business.vat_mode} onChange={v => save({ vat_mode: v })}
                options={[["add", "Add VAT on top"], ["inclusive", "Already include VAT"]]} />
            </Row>
            <Row title="VAT rate" hint="Nigeria's VAT is 7.5%. Products marked “No VAT” (Inventory → edit) are left out.">
              <div style={{ display: "flex", gap: 6 }}>
                <input type="number" min={0.1} max={50} step="0.1" value={rate} onChange={e => setRate(e.target.value)} style={{ width: 80 }} />
                <span style={{ alignSelf: "center", fontSize: 13 }}>%</span>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => save({ vat_rate: Number(rate) })}>Save</button>
              </div>
            </Row>
            <Row title="TIN / VAT number" hint="Printed on receipts, invoices and quotations.">
              <div style={{ display: "flex", gap: 6 }}>
                <input value={number} maxLength={40} onChange={e => setNumber(e.target.value)} placeholder="e.g. 12345678-0001" style={{ width: 170 }} />
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => save({ vat_number: number })}>Save</button>
              </div>
            </Row>
            {collected && (
              <Row title="VAT collected" hint="From sales and paid invoices — what you'll file.">
                <div style={{ fontSize: 13, textAlign: "right" }}>
                  <div>{collected.month}: <strong>{nairaFull(collected.this_month)}</strong></div>
                  <div className="td-muted">{collected.last_month_name}: {nairaFull(collected.last_month)}</div>
                </div>
              </Row>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function SummarySection({ business }) {
  const { save, msg, err } = useSaver(saveBusiness);
  const [time, setTime] = useState(business.daily_summary_time || "20:00");
  useEffect(() => { setTime(business.daily_summary_time || "20:00"); }, [business.daily_summary_time]);
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Notifications & WhatsApp</span>
        <span className="td-muted" style={{ fontSize: 12 }}>{msg}</span>
      </div>
      <div className="card-body" style={{ paddingTop: 4, paddingBottom: 4 }}>
        {err && <div className="modal-error">{err}</div>}
        <Row title="Phone notifications on the lock screen"
          hint={business.push_hide_details
            ? "Hidden: the lock screen only says e.g. \"You have a payment to confirm\". Names and amounts show once the app is opened."
            : "Shown: alerts say who and how much, e.g. \"Ade says he paid ₦45,000\" — anyone who sees the phone can read it."}>
          <Seg value={business.push_hide_details} onChange={v => save({ push_hide_details: v })}
            options={[[false, "Show details"], [true, "Hide amounts & names"]]} />
        </Row>
        <Row title="Daily summary" hint="tiTi sends the owner today's sales, payments and what's owed, every day.">
          <Seg value={business.daily_summary} onChange={v => save({ daily_summary: v })}
            options={[[false, "Off"], [true, "On"]]} />
        </Row>
        {business.daily_summary && (
          <Row title="Send it at" hint="Nigeria time. It arrives within 10 minutes of this time.">
            <div style={{ display: "flex", gap: 6 }}>
              <input type="time" value={time} onChange={e => setTime(e.target.value)} style={{ width: 120 }} />
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => save({ daily_summary_time: time })}>Save</button>
            </div>
          </Row>
        )}
      </div>
    </div>
  );
}

// What each choice does to the printout — shown under the buttons
const PAPER_OUTCOME = {
  "80mm": "Narrow receipt for the small thermal printer most shops use (80mm roll).",
  "58mm": "Extra-narrow receipt for the smallest handheld printers (58mm roll). Long names wrap.",
  a4: "Full page for an office printer or to save as PDF and send. Wider, with more space.",
};
const LOGO_OUTCOME = {
  top: "Logo sits above your business name, in the middle.",
  left: "Logo sits on the left, your name and details beside it.",
  right: "Logo sits on the right, your name and details beside it.",
  none: "No logo is printed (saves ink on thermal printers).",
};

// Quotations: "auto" (null) = businesses that do jobs; Show / Hide = the owner's choice
function InvoicesSection({ business }) {
  const { save, msg, err } = useSaver(saveBusiness);
  const { refreshUser } = useAuth();
  const v = business.quotes ?? "auto";
  const hints = {
    auto: "Automatic: businesses that do jobs (tailor, mechanic, builder, printer…) can write quotations; shops can't.",
    true: "Shown: Invoices has \"New quotation\" — a price for the customer to agree to (with a deposit if you like) before it becomes an invoice.",
    false: "Hidden: no quotations, only invoices. Quotations already written are kept.",
  };
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Invoices</span>
        <span className="td-muted" style={{ fontSize: 12 }}>{msg}</span>
      </div>
      <div className="card-body" style={{ paddingTop: 4, paddingBottom: 4 }}>
        {err && <div className="modal-error">{err}</div>}
        <Row title="Quotations" hint={hints[String(v)]}>
          <Seg value={v} onChange={async x => { await save({ quotes: x === "auto" ? null : x }); refreshUser?.(); }}
            options={[["auto", "Automatic"], [true, "Show"], [false, "Hide"]]} />
        </Row>
      </div>
    </div>
  );
}

// Appointments in the menu: "auto" (null) = service businesses only
function AppointmentsSection({ business }) {
  const { save, msg, err } = useSaver(saveBusiness);
  const v = business.show_appointments ?? "auto";
  const hints = {
    auto: "Automatic: shown for service businesses (salon, barber, clinic, mechanic, tailor, professionals) and hidden for shops.",
    true: "Shown: Appointments is in your menu. Book customers for a time; they get a WhatsApp reminder the evening before.",
    false: "Hidden: Appointments is not in your menu. Bookings already made are kept.",
  };
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Appointments</span>
        <span className="td-muted" style={{ fontSize: 12 }}>{msg}</span>
      </div>
      <div className="card-body" style={{ paddingTop: 4, paddingBottom: 4 }}>
        {err && <div className="modal-error">{err}</div>}
        <Row title="Show Appointments in the menu" hint={hints[String(v)]}>
          <Seg value={v} onChange={x => save({ show_appointments: x === "auto" ? null : x })}
            options={[["auto", "Automatic"], [true, "Show"], [false, "Hide"]]} />
        </Row>
        <Row title="Customers can book from a link"
          hint={business.booking_link
            ? "On: share your link (Appointments → Booking link). Customers pick a service, a day and a free time."
            : "Off: only you and your staff book appointments."}>
          <Seg value={business.booking_link} onChange={x => save({ booking_link: x })}
            options={[[true, "On"], [false, "Off"]]} />
        </Row>
        {business.booking_link && (
          <>
            <Row title="When a customer books from the link"
              hint={business.booking_auto_confirm
                ? "Booked straight away: the time is theirs and they get a WhatsApp at once. Faster, but anyone with the link can take a time."
                : "You confirm each one: it waits in Appointments as \"Asking to book\". You tap Confirm or Decline and they hear back on WhatsApp."}>
              <Seg value={business.booking_auto_confirm} onChange={x => save({ booking_auto_confirm: x })}
                options={[[false, "I confirm"], [true, "Book straight away"]]} />
            </Row>
            <Row title="Customers choose who does it"
              hint={business.booking_pick_staff ? "They see your staff names and can pick one (or anyone free)." : "They don't choose — you decide who does it."}>
              <Seg value={business.booking_pick_staff} onChange={x => save({ booking_pick_staff: x })}
                options={[[true, "Yes"], [false, "No"]]} />
            </Row>
            <Row title="Time for each booking"
              hint={`Customers see free times every ${business.booking_slot_min} minutes, and each booking takes that long. You can change any booking afterwards.`}>
              <select value={business.booking_slot_min} onChange={e => save({ booking_slot_min: Number(e.target.value) })}>
                {[15, 20, 30, 45, 60, 90, 120].map(m => <option key={m} value={m}>{m < 60 ? `${m} min` : `${m / 60} hour${m > 60 ? "s" : ""}`}</option>)}
              </select>
            </Row>
            <Row title="How far ahead customers can book" hint={`Up to ${business.booking_days_ahead} days from today.`}>
              <select value={business.booking_days_ahead} onChange={e => save({ booking_days_ahead: Number(e.target.value) })}>
                {[3, 7, 14, 30, 60, 90].map(d => <option key={d} value={d}>{d} days</option>)}
              </select>
            </Row>
            <HoursRow key={JSON.stringify(business.booking_hours)} hours={business.booking_hours} onSave={h => save({ booking_hours: h })} />
          </>
        )}
      </div>
    </div>
  );
}

// Loyalty: off, stamp card or points — and the numbers behind it
function LoyaltySection({ business }) {
  const { save, msg, err } = useSaver(saveBusiness);
  const mode = business.loyalty_mode || "off";
  const [products, setProducts] = useState(null);
  const [q, setQ] = useState("");
  const chosen = business.loyalty_items || [];
  useEffect(() => {
    if (mode === "off") return undefined;
    let live = true;
    apiFetch("pos/products").then(d => { if (live) setProducts(d.products || []); }).catch(() => {});
    return () => { live = false; };
  }, [mode]);
  const nameOf = id => products?.find(p => p.id === id)?.name || `Product #${id}`;
  const matches = q.trim().length >= 2 && products
    ? products.filter(p => !chosen.includes(p.id) && p.name.toLowerCase().includes(q.trim().toLowerCase())).slice(0, 6) : [];
  const hints = {
    off: "Off: no stamps or points.",
    stamps: `Stamp card: every paid sale to a named customer is a stamp. At ${business.loyalty_stamps_needed} stamps the next one is free — tick "Use reward" at the till and the cheapest item that counts comes off.`,
    points: `Points: customers get ₦${business.loyalty_points_percent} back for every ₦100 they spend. Tick "Use points" at the till to take them off.`,
  };
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Loyalty</span>
        <span className="td-muted" style={{ fontSize: 12 }}>{msg}</span>
      </div>
      <div className="card-body" style={{ paddingTop: 4, paddingBottom: 4 }}>
        {err && <div className="modal-error">{err}</div>}
        <Row title="Reward customers who come back" hint={hints[mode]}>
          <Seg value={mode} onChange={v => save({ loyalty_mode: v })}
            options={[["off", "Off"], ["stamps", "Stamp card"], ["points", "Points"]]} />
        </Row>
        {mode !== "off" && (
          <>
            {mode === "stamps" ? (
              <Row title="Stamps for a free one" hint={`Buy ${business.loyalty_stamps_needed}, get the next one free.`}>
                <select value={business.loyalty_stamps_needed} onChange={e => save({ loyalty_stamps_needed: Number(e.target.value) })}>
                  {[3, 4, 5, 6, 8, 10, 12, 15, 20].map(n => <option key={n} value={n}>{n} stamps</option>)}
                </select>
              </Row>
            ) : (
              <Row title="Points for every ₦100 spent" hint={`Spend ₦10,000 → ₦${Math.floor(100 * business.loyalty_points_percent).toLocaleString()} in points.`}>
                <select value={business.loyalty_points_percent} onChange={e => save({ loyalty_points_percent: Number(e.target.value) })}>
                  {[0.5, 1, 2, 3, 5].map(n => <option key={n} value={n}>₦{n} back</option>)}
                </select>
              </Row>
            )}
            <Row title="Rewards expire"
              hint={business.loyalty_expiry_months ? `Unused ${mode === "stamps" ? "stamps" : "points"} are gone after ${business.loyalty_expiry_months} months.` : "Never: they keep them until they use them."}>
              <select value={business.loyalty_expiry_months} onChange={e => save({ loyalty_expiry_months: Number(e.target.value) })}>
                {[[0, "Never"], [3, "After 3 months"], [6, "After 6 months"], [12, "After 1 year"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </Row>
            <Row title="Products that count"
              hint={chosen.length ? "Only sales of these products earn (and only these can be the free one)." : "Everything you sell counts. Add products here to count only those."}>
              <div style={{ display: "grid", gap: 6 }}>
                <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                  {chosen.map(id => (
                    <span key={id} className="badge" style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
                      {nameOf(id)}
                      <button type="button" className="btn btn-ghost btn-sm" style={{ padding: 0 }} aria-label="Remove"
                        onClick={() => save({ loyalty_items: chosen.filter(x => x !== id) })}>×</button>
                    </span>
                  ))}
                </div>
                <input value={q} placeholder="Add a product…" onChange={e => setQ(e.target.value)} />
                {matches.map(p => (
                  <button key={p.id} type="button" className="btn btn-ghost btn-sm" style={{ justifyContent: "flex-start" }}
                    onClick={() => { setQ(""); save({ loyalty_items: [...chosen, p.id] }); }}>{p.name}</button>
                ))}
              </div>
            </Row>
            <div className="td-muted" style={{ fontSize: 12, padding: "6px 0 10px" }}>
              Only sales to a named customer earn, and only once paid — a credit sale earns when the debt is cleared.
              A voided sale takes its reward back. Customers see their stamps or points on their WhatsApp receipt.
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// Opening hours for the booking link — a day left unticked is closed
const WEEK = [["mon", "Monday"], ["tue", "Tuesday"], ["wed", "Wednesday"], ["thu", "Thursday"], ["fri", "Friday"], ["sat", "Saturday"], ["sun", "Sunday"]];
function HoursRow({ hours, onSave }) {
  const [h, setH] = useState(hours || {});
  const set = (d, v) => setH({ ...h, [d]: v });
  return (
    <Row title="Opening hours" hint="Customers only see free times inside these hours. Untick a day you're closed.">
      <div style={{ display: "grid", gap: 4 }}>
        {WEEK.map(([d, label]) => (
          <div key={d} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13, flexWrap: "wrap" }}>
            <label style={{ width: 110, display: "flex", gap: 6, alignItems: "center" }}>
              <input type="checkbox" checked={!!h[d]} onChange={e => set(d, e.target.checked ? ["08:00", "18:00"] : null)} />{label}
            </label>
            {h[d] ? (
              <>
                <input type="time" value={h[d][0]} onChange={e => set(d, [e.target.value, h[d][1]])} />
                <span>to</span>
                <input type="time" value={h[d][1]} onChange={e => set(d, [h[d][0], e.target.value])} />
              </>
            ) : <span className="td-muted">Closed</span>}
          </div>
        ))}
        <div><button type="button" className="btn btn-secondary btn-sm" onClick={() => onSave(h)}>Save hours</button></div>
      </div>
    </Row>
  );
}

function PrintSection({ business }) {
  const { save, msg, err } = useSaver(saveBusiness);
  // The business's real name, logo, address, email and bank accounts
  const [biz, setBiz] = useState(null);
  useEffect(() => { apiFetch("settings/print-preview").then(setBiz).catch(() => setBiz({})); }, []);
  const [title, setTitle] = useState(business.receipt_title || "");
  const [footer, setFooter] = useState(business.receipt_footer || "");
  const b = business;
  // A preview with the business's own details, as the choices stand
  const banks = biz?.all_bank_accounts || [];
  const sample = {
    ...(biz || {}),
    biz_name: biz?.biz_name || "Your business",
    biz_address: biz?.biz_address || "Your address",
    bank_accounts: b.print_bank_receipts ? banks : [],
    print: {
      paper: b.print_paper, logo: b.print_logo, align: b.print_align,
      show_phone: b.print_show_phone, show_address: b.print_show_address, show_email: b.print_show_email,
    },
  };
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Receipts & printables</span>
        <span className="td-muted" style={{ fontSize: 12 }}>{msg || "Receipts, invoices, quotations, waybills"}</span>
      </div>
      <div className="card-body" style={{ paddingTop: 4, paddingBottom: 4 }}>
        {err && <div className="modal-error">{err}</div>}
        <Row title="Paper size" hint={PAPER_OUTCOME[b.print_paper]}>
          <Seg value={b.print_paper} onChange={v => save({ print_paper: v })}
            options={[["80mm", "Thermal 80mm"], ["58mm", "Thermal 58mm"], ["a4", "A4 page"]]} />
        </Row>
        <Row title="Logo" hint={biz?.biz_logo ? LOGO_OUTCOME[b.print_logo] : "Add your logo on My Profile first. " + LOGO_OUTCOME[b.print_logo]}>
          <Seg value={b.print_logo} onChange={v => save({ print_logo: v })}
            options={[["top", "On top"], ["left", "Left"], ["right", "Right"], ["none", "Hide"]]} />
        </Row>
        <Row title="Business name and details"
          hint={b.print_align === "left" ? "Lined up on the left, like a letterhead." : "Centred, like a shop receipt."}>
          <Seg value={b.print_align} onChange={v => save({ print_align: v })}
            options={[["center", "Centre"], ["left", "Left"]]} />
        </Row>
        <Row title="Phone number" hint={b.print_show_phone ? "Your phone number prints under your name." : "Your phone number is left off."}>
          <Seg value={b.print_show_phone} onChange={v => save({ print_show_phone: v })} options={[[true, "Show"], [false, "Hide"]]} />
        </Row>
        <Row title="Address" hint={b.print_show_address ? "Your address (or the branch's) prints under your name." : "Your address is left off."}>
          <Seg value={b.print_show_address} onChange={v => save({ print_show_address: v })} options={[[true, "Show"], [false, "Hide"]]} />
        </Row>
        <Row title="Email" hint={!biz?.biz_email ? "Add your business email on My Profile first."
          : b.print_show_email ? "Your business email prints under your name." : "Your email is left off."}>
          <Seg value={b.print_show_email} onChange={v => save({ print_show_email: v })} options={[[true, "Show"], [false, "Hide"]]} />
        </Row>
        <Row title="Bank details on invoices & quotations"
          hint={!banks.length ? "Add your bank account on My Profile first."
            : b.print_bank_invoices ? "Customers see where to pay on every invoice and quotation." : "Bank details are left off invoices and quotations."}>
          <Seg value={b.print_bank_invoices} onChange={v => save({ print_bank_invoices: v })} options={[[true, "Show"], [false, "Hide"]]} />
        </Row>
        <Row title="Bank details on receipts"
          hint={b.print_bank_receipts ? "Receipts also show your bank account — handy when customers pay balances by transfer." : "Receipts don't show your bank account."}>
          <Seg value={b.print_bank_receipts} onChange={v => save({ print_bank_receipts: v })} options={[[false, "Hide"], [true, "Show"]]} />
        </Row>
        <Row title="Receipt title" hint="The word at the top of a receipt. Leave empty for your business type's own (e.g. Receipt).">
          <div style={{ display: "flex", gap: 6 }}>
            <input value={title} maxLength={40} onChange={e => setTitle(e.target.value)} placeholder="Receipt" style={{ width: 160 }} />
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => save({ receipt_title: title })}>Save</button>
          </div>
        </Row>
        <Row title="Closing line" hint="Printed at the bottom of every receipt, and on WhatsApp receipts.">
          <div style={{ display: "flex", gap: 6 }}>
            <input value={footer} maxLength={160} onChange={e => setFooter(e.target.value)}
              placeholder="Thank you for your business." style={{ width: 220 }} />
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => save({ receipt_footer: footer })}>Save</button>
          </div>
        </Row>
        <div style={{ padding: "12px 0" }}>
          <div className="td-muted" style={{ fontSize: 12, marginBottom: 6 }}>Preview</div>
          <div className={paperClass(sample)} style={{ margin: "0 auto", boxShadow: "none" }}>
            <PrintHeader doc={sample} title={(title || "Receipt").toUpperCase()} date="22 Oct 2026, 10:30" refText="Receipt #120" />
            <PrintBank doc={sample} />
            <div className="receipt-footer" style={{ marginTop: 8 }}>
              <div className="receipt-muted">{footer || "Thank you for your business."}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Settings() {
  const { loaded, display, business, canEditBusiness } = useSettings();
  if (!loaded) return <div className="page-loading">Loading settings…</div>;
  return (
    <div style={{ display: "grid", gap: 14, maxWidth: 760 }}>
      <DisplaySection display={display} />
      {canEditBusiness ? (
        <>
          <StockSection business={business} />
          <CategoriesSection business={business} />
          <SummarySection business={business} />
          <VatSection business={business} />
          <InvoicesSection business={business} />
          <AppointmentsSection business={business} />
          <LoyaltySection business={business} />
          <PrintSection business={business} />
        </>
      ) : (
        <div className="card card-body td-muted" style={{ fontSize: 13 }}>
          Business settings (stock, categories, daily summary, receipts) are set by the owner.
        </div>
      )}
    </div>
  );
}
