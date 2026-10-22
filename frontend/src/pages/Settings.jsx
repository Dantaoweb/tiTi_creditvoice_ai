import { useEffect, useState } from "react";
import { ArrowUp, ArrowDown, Pencil, Check, X } from "lucide-react";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull } from "../lib/format";
import { saveBusiness, saveDisplay, useSettings } from "../lib/settings";

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
          hint="Yes: the sale goes through and what isn't in store is kept as still to deliver for the customer. No: a sale can't take more than what's in store. Only changes new sales.">
          <Seg value={business.allow_negative_stock} onChange={v => save({ allow_negative_stock: v })}
            options={[[true, "Yes"], [false, "No"]]} />
        </Row>
        <Row title="Keep goods aside for customers who have not collected"
          hint="Yes: goods a customer bought but left in the store are kept aside — no one else can buy them. No: they stay free to sell until you keep them aside yourself (Deliveries or Add stock).">
          <Seg value={business.keep_aside} onChange={v => save({ keep_aside: v })}
            options={[[true, "Yes"], [false, "No"]]} />
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
        {cats && named.length === 0 && <p className="td-muted">No categories yet — put products into one below.</p>}
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
              </>
            )}
          </div>
        ))}
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

function SummarySection({ business }) {
  const { save, msg, err } = useSaver(saveBusiness);
  const [time, setTime] = useState(business.daily_summary_time || "20:00");
  useEffect(() => { setTime(business.daily_summary_time || "20:00"); }, [business.daily_summary_time]);
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">WhatsApp</span>
        <span className="td-muted" style={{ fontSize: 12 }}>{msg}</span>
      </div>
      <div className="card-body" style={{ paddingTop: 4, paddingBottom: 4 }}>
        {err && <div className="modal-error">{err}</div>}
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
        </>
      ) : (
        <div className="card card-body td-muted" style={{ fontSize: 13 }}>
          Business settings (stock, categories, daily summary) are set by the owner.
        </div>
      )}
    </div>
  );
}
