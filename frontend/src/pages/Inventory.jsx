import { useEffect, useState } from "react";
import { Plus, PlusCircle, MinusCircle, ChevronRight } from "lucide-react";
import { useApp } from "../context/AppContext";
import { useAuth } from "../context/AuthContext";
import { getBizLabels } from "../lib/bizLabels";
import { apiFetch, apiPost, apiPut } from "../lib/api";
import { nairaFull, dateStr, dateTimeStr, parseAmt } from "../lib/format";
import MoneyInput from "../components/MoneyInput";
import DataTable from "../components/DataTable";
import MetricCard from "../components/MetricCard";
import { StockBadge } from "../components/Badge";
import StaleDataBanner from "../components/StaleDataBanner";
import { LimitBar } from "../components/UpgradeGate";
import { usePlan } from "../lib/usePlan";

// ── Modal wrapper ────────────────────────────────────────────────────────────
function Modal({ title, onClose, children }) {
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">{title}</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

// ── Catalog picker modal ─────────────────────────────────────────────────────
function CatalogPickerModal({ ownerPhone, onClose, onSaved }) {
  const [catalog, setCatalog] = useState({});
  const [services, setServices] = useState([]);
  const [kind, setKind] = useState("product");
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(new Set());
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState(null);

  useEffect(() => {
    apiFetch("inventory/catalog")
      .then(d => {
        setKind(d.kind || "product");
        setCatalog(d.catalog || {});
        setServices(d.services || []);
      })
      .catch(() => setErr("Could not load catalog."))
      .finally(() => setLoading(false));
  }, []);

  function toggle(name) {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(name) ? next.delete(name) : next.add(name);
      return next;
    });
  }

  function toggleAll(names) {
    setSelected(prev => {
      const next = new Set(prev);
      const allOn = names.every(n => next.has(n));
      names.forEach(n => allOn ? next.delete(n) : next.add(n));
      return next;
    });
  }

  async function save() {
    if (selected.size === 0) { setErr("Select at least one item."); return; }
    setSaving(true); setErr("");
    try {
      let res;
      if (kind === "service") {
        const items = services
          .filter(s => selected.has(s.name))
          .map(s => ({ name: s.name, selling_price: s.price, is_service: true }));
        res = await apiPost("inventory/bulk", { owner_phone: ownerPhone, items });
      } else {
        res = await apiPost("inventory/bulk", { owner_phone: ownerPhone, names: [...selected] });
      }
      setResult(res);
      onSaved();
    } catch (e) { setErr(e.message); }
    finally { setSaving(false); }
  }

  const allNames = kind === "service"
    ? services.map(s => s.name)
    : Object.values(catalog).flat();

  return (
    <Modal title={kind === "service" ? "Add from Price List" : "Add from Product Catalog"} onClose={onClose}>
      <div className="modal-body" style={{ maxHeight: "60vh", overflowY: "auto" }}>
        {loading ? (
          <div style={{ padding: 20, textAlign: "center", color: "var(--text-muted)" }}>Loading catalog…</div>
        ) : result ? (
          <div>
            <div style={{ color: "var(--brand)", fontWeight: 600, marginBottom: 8 }}>
              ✓ {result.saved} {kind === "service" ? "service" : "product"}{result.saved !== 1 ? "s" : ""} added{kind === "service" ? " with suggested prices" : " as drafts"}
            </div>
            {result.already_existed > 0 && (
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                {result.already_existed} already existed and were skipped.
              </div>
            )}
            <p style={{ fontSize: 13, marginTop: 10 }}>
              {kind === "service"
                ? "Adjust any prices from the list below."
                : "Set prices from the inventory table."}
            </p>
          </div>
        ) : (
          <>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <span style={{ fontSize: 13, color: "var(--text-muted)" }}>{selected.size} selected</span>
              <button className="btn btn-ghost" style={{ fontSize: 12 }}
                onClick={() => setSelected(selected.size === allNames.length ? new Set() : new Set(allNames))}>
                {selected.size === allNames.length ? "Deselect all" : "Select all"}
              </button>
            </div>
            {kind === "service" ? (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {services.map(s => (
                  <button key={s.name}
                    className={`btn ${selected.has(s.name) ? "btn-primary" : "btn-secondary"}`}
                    style={{ fontSize: 12, padding: "4px 10px" }}
                    onClick={() => toggle(s.name)}>
                    {s.name.charAt(0).toUpperCase() + s.name.slice(1)} · ₦{s.price.toLocaleString()}
                  </button>
                ))}
              </div>
            ) : (
              Object.entries(catalog).map(([cat, names]) => (
                <div key={cat} style={{ marginBottom: 14 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                    <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", color: "var(--text-muted)", letterSpacing: 1 }}>{cat}</span>
                    <button className="btn btn-ghost" style={{ fontSize: 11, padding: "2px 6px" }}
                      onClick={() => toggleAll(names)}>
                      {names.every(n => selected.has(n)) ? "Deselect" : "Select all"}
                    </button>
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {names.map(name => (
                      <button key={name}
                        className={`btn ${selected.has(name) ? "btn-primary" : "btn-secondary"}`}
                        style={{ fontSize: 12, padding: "4px 10px" }}
                        onClick={() => toggle(name)}>
                        {name.charAt(0).toUpperCase() + name.slice(1)}
                      </button>
                    ))}
                  </div>
                </div>
              ))
            )}
            {err && <div className="modal-error">{err}</div>}
          </>
        )}
      </div>
      <div className="modal-footer">
        <button className="btn btn-ghost" onClick={onClose}>{result ? "Close" : "Cancel"}</button>
        {!result && !loading && (
          <button className="btn btn-primary" onClick={save} disabled={saving || selected.size === 0}>
            {saving ? "Adding…" : `Add ${selected.size || ""} Selected`}
          </button>
        )}
      </div>
    </Modal>
  );
}

// ── Bulk name add modal ──────────────────────────────────────────────────────
function BulkAddModal({ ownerPhone, onClose, onSaved }) {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState(null);

  async function save() {
    setErr(""); setSaving(true);
    const names = text
      .split(/[\n,;]+/)
      .map(s => s.trim().toLowerCase())
      .filter(s => s.length > 0);
    if (names.length === 0) { setErr("Enter at least one product name."); setSaving(false); return; }
    try {
      const res = await apiPost("inventory/bulk", { owner_phone: ownerPhone, names });
      setResult(res);
      onSaved();
    } catch (e) { setErr(e.message); }
    finally { setSaving(false); }
  }

  return (
    <Modal title="Quick Add Product Names" onClose={onClose}>
      <div className="modal-body">
        {result ? (
          <div>
            <div style={{ color: "var(--brand)", fontWeight: 600, marginBottom: 8 }}>
              ✓ {result.saved} product{result.saved !== 1 ? "s" : ""} added as drafts
            </div>
            {result.already_existed > 0 && (
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                {result.already_existed} already existed and were skipped.
              </div>
            )}
            <p style={{ fontSize: 13, marginTop: 10 }}>
              Open each product from the inventory table to set its price and quantity.
            </p>
          </div>
        ) : (
          <>
            <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 10 }}>
              Type or paste your product names — one per line, or separated by commas. Prices and quantities can be set later.
            </p>
            <div className="form-group">
              <label className="form-label">Product names</label>
              <textarea
                value={text}
                onChange={e => setText(e.target.value)}
                placeholder={"Paracetamol\nAmoxicillin\nMalaria drugs\nTissue paper"}
                rows={8}
                autoFocus
                style={{ resize: "vertical", fontFamily: "inherit" }}
              />
            </div>
            {err && <div className="modal-error">{err}</div>}
          </>
        )}
      </div>
      <div className="modal-footer">
        <button className="btn btn-ghost" onClick={onClose}>{result ? "Close" : "Cancel"}</button>
        {!result && (
          <button className="btn btn-primary" onClick={save} disabled={saving}>
            {saving ? "Adding…" : "Add All"}
          </button>
        )}
      </div>
    </Modal>
  );
}

// ── Add item modal ───────────────────────────────────────────────────────────
function AddItemModal({ ownerPhone, isServiceBiz, fields = [], onClose, onSaved }) {
  const [itemType, setItemType] = useState(isServiceBiz ? "service" : "stock");
  const [form, setForm] = useState({
    name: "", unit: "", quantity: "",
    cost_price: "", selling_price: "", low_stock_alert: "",
    retail_unit: "", retail_per_base: "", retail_price: "",
  });
  const [attrs, setAttrs] = useState({});
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  function set(k, v) { setForm(p => ({ ...p, [k]: v })); }
  function setAttr(k, v) { setAttrs(p => ({ ...p, [k]: v })); }

  const isService = itemType === "service";

  async function save() {
    if (!form.name.trim()) { setErr("Name is required."); return; }
    if (!form.selling_price) { setErr("Price is required."); return; }
    setSaving(true); setErr("");
    try {
      const item = await apiPost("inventory", {
        owner_phone: ownerPhone,
        name: form.name.trim(),
        unit: form.unit.trim() || null,
        quantity: isService ? null : (parseAmt(form.quantity) || 0),
        cost_price: isService ? null : (form.cost_price ? parseAmt(form.cost_price) : null),
        selling_price: form.selling_price ? parseAmt(form.selling_price) : null,
        low_stock_alert: isService ? null : (form.low_stock_alert ? parseAmt(form.low_stock_alert) : null),
        is_service: isService,
        retail_unit: !isService ? (form.retail_unit.trim() || null) : null,
        retail_per_base: (!isService && form.retail_per_base !== "") ? parseAmt(form.retail_per_base) : null,
        retail_price: (!isService && form.retail_price !== "") ? parseAmt(form.retail_price) : null,
        attributes: isService ? {} : attrs,
      });
      onSaved(item);
      onClose();
    } catch (e) { setErr(e.message); }
    finally { setSaving(false); }
  }

  return (
    <Modal title={isService ? "Add Service / Price" : "Add Product"} onClose={onClose}>
      <div className="modal-body">
        <div className="item-type-toggle">
          <button
            className={`btn btn-sm ${itemType === "service" ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setItemType("service")}
          >
            Service / Price
          </button>
          <button
            className={`btn btn-sm ${itemType === "stock" ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setItemType("stock")}
          >
            Physical Stock
          </button>
        </div>

        <div className="form-row">
          <div className="form-group">
            <label className="form-label">{isService ? "Service name *" : "Product name *"}</label>
            <input
              value={form.name}
              onChange={e => set("name", e.target.value)}
              placeholder={isService ? "e.g. Haircut, Full wash, Repair" : "e.g. Indomie Noodles"}
            />
          </div>
          <div className="form-group" style={{ width: 120 }}>
            <label className="form-label">{isService ? "Tier / Size" : "Unit"}</label>
            <input
              value={form.unit}
              onChange={e => set("unit", e.target.value)}
              placeholder={isService ? "e.g. kids, adult" : "e.g. carton"}
            />
          </div>
        </div>

        {!isService && fields.length > 0 && (
          <div className="form-row" style={{ flexWrap: "wrap" }}>
            {fields.map(f => (
              <div className="form-group" key={f.key} style={{ flex: "1 1 45%", minWidth: 0 }}>
                <label className="form-label">{f.label}</label>
                <input value={attrs[f.key] || ""} onChange={e => setAttr(f.key, e.target.value)} />
              </div>
            ))}
          </div>
        )}

        <div className="form-row">
          <div className="form-group">
            <label className="form-label">{isService ? "Price (₦) *" : "Selling price (₦) *"}</label>
            <MoneyInput
              value={form.selling_price}
              onChange={v => set("selling_price", v)}
              placeholder="0"
            />
          </div>
          {!isService && (
            <div className="form-group">
              <label className="form-label">Cost price (₦)</label>
              <MoneyInput value={form.cost_price} onChange={v => set("cost_price", v)} placeholder="0" />
            </div>
          )}
        </div>

        {!isService && form.selling_price !== "" && form.cost_price !== "" &&
         parseAmt(form.selling_price) < parseAmt(form.cost_price) && (
          <div className="inv-below-cost-warning">
            ⚠️ Selling price is below your cost price — you'll be selling at a loss.
          </div>
        )}

        {!isService && (
          <div className="form-row">
            <div className="form-group">
              <label className="form-label">Opening stock</label>
              <MoneyInput value={form.quantity} onChange={v => set("quantity", v)} placeholder="0" />
            </div>
            <div className="form-group">
              <label className="form-label">Low-stock alert</label>
              <MoneyInput value={form.low_stock_alert} onChange={v => set("low_stock_alert", v)} placeholder="optional" />
            </div>
          </div>
        )}

        {!isService && (
          <div style={{ borderTop: "1px solid var(--border)", paddingTop: 12, marginTop: 4 }}>
            <div className="form-label" style={{ marginBottom: 8, color: "var(--text-muted)", fontSize: 12 }}>
              Retail Breakdown (optional) — e.g. sell sachets from a pack
            </div>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label">Sub-unit name</label>
                <input value={form.retail_unit} onChange={e => set("retail_unit", e.target.value)}
                  placeholder="e.g. sachet" />
              </div>
              <div className="form-group" style={{ width: 110 }}>
                <label className="form-label">Per {form.unit || "unit"}</label>
                <MoneyInput value={form.retail_per_base}
                  onChange={v => set("retail_per_base", v)} placeholder="e.g. 15" />
              </div>
              <div className="form-group">
                <label className="form-label">Sub-unit price (₦)</label>
                <MoneyInput value={form.retail_price}
                  onChange={v => set("retail_price", v)} placeholder="e.g. 34" />
              </div>
            </div>
          </div>
        )}

        {err && <div className="modal-error">{err}</div>}
      </div>
      <div className="modal-footer">
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={saving}>
          {saving ? "Saving…" : isService ? "Add Service" : "Add Product"}
        </button>
      </div>
    </Modal>
  );
}

// ── Edit item modal ──────────────────────────────────────────────────────────
function EditItemModal({ item, fields = [], onClose, onSaved }) {
  const isService = item.is_service;
  const [form, setForm] = useState({
    name: item.name,
    unit: item.unit || "",
    cost_price: item.cost_price || "",
    selling_price: item.selling_price || "",
    low_stock_alert: item.low_stock_alert ?? "",
    is_available: item.is_available,
    retail_unit: item.retail_unit || "",
    retail_per_base: item.retail_per_base || "",
    retail_price: item.retail_price || "",
  });
  const [attrs, setAttrs] = useState(item.attributes || {});
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  function set(k, v) { setForm(p => ({ ...p, [k]: v })); }
  function setAttr(k, v) { setAttrs(p => ({ ...p, [k]: v })); }

  async function save() {
    setSaving(true); setErr("");
    try {
      await apiPut(`inventory/${item.id}`, {
        name: form.name.trim() || null,
        unit: form.unit.trim() || null,
        cost_price: (!isService && form.cost_price !== "") ? parseAmt(form.cost_price) : null,
        selling_price: form.selling_price !== "" ? parseAmt(form.selling_price) : null,
        low_stock_alert: (!isService && form.low_stock_alert !== "") ? parseAmt(form.low_stock_alert) : null,
        is_available: form.is_available,
        retail_unit: form.retail_unit.trim() || null,
        retail_per_base: form.retail_per_base !== "" ? parseAmt(form.retail_per_base) : null,
        retail_price: form.retail_price !== "" ? parseAmt(form.retail_price) : null,
        ...(fields.length > 0 && !isService ? { attributes: attrs } : {}),
      });
      onSaved();
      onClose();
    } catch (e) { setErr(e.message); }
    finally { setSaving(false); }
  }

  return (
    <Modal title={`Edit: ${item.name}`} onClose={onClose}>
      <div className="modal-body">
        <div className="form-row">
          <div className="form-group">
            <label className="form-label">{isService ? "Service name" : "Product name"}</label>
            <input value={form.name} onChange={e => set("name", e.target.value)} />
          </div>
          <div className="form-group" style={{ width: 120 }}>
            <label className="form-label">{isService ? "Tier / Size" : "Unit"}</label>
            <input value={form.unit} onChange={e => set("unit", e.target.value)} />
          </div>
        </div>
        {!isService && fields.length > 0 && (
          <div className="form-row" style={{ flexWrap: "wrap" }}>
            {fields.map(f => (
              <div className="form-group" key={f.key} style={{ flex: "1 1 45%", minWidth: 0 }}>
                <label className="form-label">{f.label}</label>
                <input value={attrs[f.key] || ""} onChange={e => setAttr(f.key, e.target.value)} />
              </div>
            ))}
          </div>
        )}
        <div className="form-row">
          <div className="form-group">
            <label className="form-label">{isService ? "Price (₦)" : "Selling price (₦)"}</label>
            <MoneyInput value={form.selling_price} onChange={v => set("selling_price", v)} />
          </div>
          {!isService && (
            <div className="form-group">
              <label className="form-label">Cost price (₦)</label>
              <MoneyInput value={form.cost_price} onChange={v => set("cost_price", v)} />
            </div>
          )}
        </div>
        {!isService && form.selling_price !== "" && form.cost_price !== "" &&
         parseAmt(form.selling_price) < parseAmt(form.cost_price) && (
          <div className="inv-below-cost-warning">
            ⚠️ Selling price is below your cost price — you'll be selling at a loss.
          </div>
        )}
        {!isService && (
          <div className="form-row">
            <div className="form-group">
              <label className="form-label">Low-stock alert</label>
              <MoneyInput value={form.low_stock_alert} onChange={v => set("low_stock_alert", v)} />
            </div>
            <div className="form-group" style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingTop: 20 }}>
              <input type="checkbox" id="is_avail" checked={form.is_available} onChange={e => set("is_available", e.target.checked)} />
              <label htmlFor="is_avail" className="form-label" style={{ margin: 0 }}>Available for sale</label>
            </div>
          </div>
        )}
        {isService && (
          <div className="form-group" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <input type="checkbox" id="is_avail" checked={form.is_available} onChange={e => set("is_available", e.target.checked)} />
            <label htmlFor="is_avail" className="form-label" style={{ margin: 0 }}>Active / Available</label>
          </div>
        )}
        {!isService && (
          <div style={{ borderTop: "1px solid var(--border)", paddingTop: 12, marginTop: 4 }}>
            <div className="form-label" style={{ marginBottom: 8, color: "var(--text-muted)", fontSize: 12 }}>
              Retail Breakdown (optional) — e.g. sell sachets from a pack
            </div>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label">Sub-unit name</label>
                <input value={form.retail_unit} onChange={e => set("retail_unit", e.target.value)}
                  placeholder="e.g. sachet" />
              </div>
              <div className="form-group" style={{ width: 110 }}>
                <label className="form-label">Per {form.unit || "unit"}</label>
                <MoneyInput value={form.retail_per_base}
                  onChange={v => set("retail_per_base", v)} placeholder="e.g. 15" />
              </div>
              <div className="form-group">
                <label className="form-label">Sub-unit price (₦)</label>
                <MoneyInput value={form.retail_price}
                  onChange={v => set("retail_price", v)} placeholder="e.g. 34" />
              </div>
            </div>
          </div>
        )}
        {err && <div className="modal-error">{err}</div>}
      </div>
      <div className="modal-footer">
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save Changes"}
        </button>
      </div>
    </Modal>
  );
}

// ── Adjust stock modal (only for physical stock items) ───────────────────────
function AdjustModal({ item, onClose, onSaved }) {
  const [delta, setDelta] = useState("");
  const [supplier, setSupplier] = useState("");
  const [cost, setCost] = useState("");
  const [paidNow, setPaidNow] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  async function save(direction) {
    const qty = parseAmt(delta);
    if (!qty || qty <= 0) { setErr("Enter a quantity greater than 0."); return; }
    setSaving(true); setErr("");
    try {
      if (direction === "in") {
        // Adding stock is receiving goods: record against a supplier (defaults
        // to "Others" server-side) so it shows in the supplier ledger, and add
        // to physical stock — the same path as Quick Record → Stock Received.
        await apiPost("inventory/stock-received", {
          item_id: item.id,
          quantity: qty,
          cost_per_unit: cost ? parseAmt(cost) : null,
          supplier: supplier.trim() || null,
          paid_now: paidNow !== "" ? parseAmt(paidNow) : null,   // blank → fully paid
          due_date: dueDate || null,
          note: note.trim() || null,
        });
      } else {
        await apiPost(`inventory/${item.id}/adjust`, {
          qty_delta: -qty,
          note: note.trim() || null,
        });
      }
      onSaved();
      onClose();
    } catch (e) { setErr(e.message); }
    finally { setSaving(false); }
  }

  const _qty  = parseAmt(delta) || 0;
  const _cost = parseAmt(cost) || 0;
  const totalCost = Math.round(_qty * _cost);
  const _paid = paidNow === "" ? totalCost : (parseAmt(paidNow) || 0);
  const oweBal = Math.max(0, totalCost - _paid);

  return (
    <Modal title={`Adjust Stock: ${item.name}`} onClose={onClose}>
      <div className="modal-body">
        <div className="adjust-current">
          Current stock: <strong>{(item.quantity ?? 0).toLocaleString()}{item.unit ? ` ${item.unit}` : ""}</strong>
        </div>
        <div className="form-group">
          <label className="form-label">Quantity</label>
          <MoneyInput
            value={delta}
            onChange={v => setDelta(v)}
            placeholder="How many?"
          />
        </div>
        <div className="form-group">
          <label className="form-label">Supplier <span className="text-subtle">(when adding)</span></label>
          <input value={supplier} onChange={e => setSupplier(e.target.value)} placeholder="Others (default)" />
        </div>
        <div className="form-group">
          <label className="form-label">Cost per unit (₦) <span className="text-subtle">(when adding)</span></label>
          <input inputMode="numeric" value={cost} onChange={e => setCost(e.target.value)} placeholder="0" />
        </div>
        <div className="form-group">
          <label className="form-label">Paid now (₦) <span className="text-subtle">(when adding)</span></label>
          <input inputMode="numeric" value={paidNow} onChange={e => setPaidNow(e.target.value)} placeholder="full amount" />
          {totalCost > 0 && (
            <span className="form-hint">
              {oweBal > 0
                ? `Total ₦${totalCost.toLocaleString()} — you'll owe ${supplier.trim() || "the supplier"} ₦${oweBal.toLocaleString()}`
                : `Total ₦${totalCost.toLocaleString()} — paid in full`}
            </span>
          )}
        </div>
        {oweBal > 0 && (
          <div className="form-group">
            <label className="form-label">Payment due <span className="text-subtle">(if owing)</span></label>
            <input type="date" value={dueDate} onChange={e => setDueDate(e.target.value)} />
          </div>
        )}
        <div className="form-group">
          <label className="form-label">Note (optional)</label>
          <input value={note} onChange={e => setNote(e.target.value)} placeholder="e.g. New delivery, damage, etc." />
        </div>
        {err && <div className="modal-error">{err}</div>}
      </div>
      <div className="modal-footer">
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-secondary" onClick={() => save("out")} disabled={saving}>
          <MinusCircle size={14} /> Remove Stock
        </button>
        <button className="btn btn-primary" onClick={() => save("in")} disabled={saving}>
          <PlusCircle size={14} /> Add Stock
        </button>
      </div>
    </Modal>
  );
}

// ── Item detail modal ────────────────────────────────────────────────────────
// One surface per item: stock/price metrics, movement history, and Edit /
// Adjust actions (delegated to the existing modals). Mirrors Suppliers/Customers.
function ItemDetailModal({ item, fields, canManage, onClose, onEdit, onAdjust }) {
  const [movs, setMovs] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    apiFetch(`inventory/${item.id}/movements`)
      .then(d => setMovs(d.movements || []))
      .catch(e => setErr(e.message));
  }, [item.id]);

  const title = (item.name || "Item").replace(/\b\w/g, c => c.toUpperCase());
  const attrLine = (fields || [])
    .map(f => (item.attributes || {})[f.key]).filter(Boolean).join(" · ");

  return (
    <Modal title={title} onClose={onClose}>
      <div className="modal-body">
        {err && <div className="modal-error">{err}</div>}
        {item.is_service && <div style={{ marginBottom: 10 }}><span className="svc-chip">service</span></div>}
        {attrLine && <div className="td-attr-line" style={{ marginBottom: 10 }}>{attrLine}</div>}

        <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(3, 1fr)", marginBottom: 14 }}>
          {!item.is_service && (
            <MetricCard label="In stock" value={`${(item.quantity ?? 0).toLocaleString()}${item.unit ? ` ${item.unit}` : ""}`}
              color={item.low_stock_alert !== null && (item.quantity ?? 0) <= item.low_stock_alert ? "amber" : undefined} />
          )}
          <MetricCard label="Selling price" value={nairaFull(item.selling_price)} />
          {!item.is_service && <MetricCard label="Cost price" value={item.cost_price ? nairaFull(item.cost_price) : "—"} />}
        </div>

        {canManage && (
          <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
            {!item.is_service && (
              <button className="btn btn-primary" style={{ flex: 1 }} onClick={() => onAdjust(item)}>Adjust stock</button>
            )}
            <button className="btn btn-secondary" style={{ flex: 1 }} onClick={() => onEdit(item)}>Edit details</button>
          </div>
        )}

        {!item.is_service && (
          <>
            <div className="card-title" style={{ marginBottom: 6 }}>Stock movements</div>
            {!movs ? (
              <p className="td-muted">Loading…</p>
            ) : movs.length === 0 ? (
              <p className="td-muted">No stock movements yet.</p>
            ) : (
              <table className="history-table">
                <thead>
                  <tr><th>Date</th><th>Type</th><th>Qty</th><th>Note</th></tr>
                </thead>
                <tbody>
                  {movs.map(m => (
                    <tr key={m.id}>
                      <td className="td-muted">{dateTimeStr(m.created_at)}</td>
                      <td>
                        <span className="badge" style={{
                          background: (m.type === "IN" ? "var(--brand)" : "var(--rose)") + "1a",
                          color: m.type === "IN" ? "var(--brand)" : "var(--rose)",
                        }}>{m.type === "IN" ? "+ In" : "− Out"}</span>
                      </td>
                      <td><strong>{(m.quantity ?? 0).toLocaleString()}</strong></td>
                      <td className="td-muted">{m.note || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>
      <div className="modal-footer">
        <button className="btn btn-ghost" onClick={onClose}>Close</button>
      </div>
    </Modal>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────
export default function Inventory() {
  const { ownerPhone } = useApp();
  const { user } = useAuth();
  const { plan, limit: planLimit, withinLimit } = usePlan();
  const L = getBizLabels(user?.menu_group);
  const isServiceBiz = user?.menu_group === "service";
  // Only the owner or a branch admin manages stock. Regular staff view only.
  const canManageStock = user?.full_access ?? !user?.parent_id;

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isStale, setIsStale] = useState(false);
  const [search, setSearch] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [showBulk, setShowBulk] = useState(false);
  const [showCatalog, setShowCatalog] = useState(false);
  const [editItem, setEditItem] = useState(null);
  const [adjustItem, setAdjustItem] = useState(null);
  const [detailItem, setDetailItem] = useState(null);
  const [fields, setFields] = useState([]);   // per-business custom stock fields

  function load() {
    setLoading(true);
    apiFetch("inventory", { owner_phone: ownerPhone })
      .then(d => { setRows(d.items); setIsStale(!navigator.onLine); })
      .catch(e => { setError(e.message); setIsStale(true); })
      .finally(() => setLoading(false));
  }

  useEffect(load, [ownerPhone]);

  useEffect(() => {
    apiFetch("inventory/fields").then(d => setFields(d.fields || [])).catch(() => {});
  }, []);

  const filtered = search
    ? rows.filter(r => (r.name || "").toLowerCase().includes(search.toLowerCase()))
    : rows;

  const lowCount = rows.filter(
    r => !r.is_service && r.is_available && r.low_stock_alert !== null && (r.quantity ?? 0) <= r.low_stock_alert
  ).length;

  const pageTitle = isServiceBiz ? L.stock : "Inventory";
  const addLabel = isServiceBiz ? "Add Service / Product" : "Add Product";

  // Active = items with a selling price set (drafts don't count toward limit)
  const activeCount  = rows.filter(r => r.selling_price != null).length;
  const inventoryLim = planLimit("active_inventory_items");
  const canAddActive = withinLimit("active_inventory_items", activeCount);

  return (
    <>
      <StaleDataBanner isStale={isStale} />
      {error && <div style={{ color: "var(--rose)" }}>{error}</div>}

      {lowCount > 0 && (
        <div className="card card-body" style={{ display: "flex", gap: 8, color: "var(--amber)", fontSize: 13.5 }}>
          ⚠️ <strong>{lowCount}</strong> product{lowCount !== 1 ? "s" : ""} below the low-stock alert level.
        </div>
      )}

      <div className="card">
        <div className="card-header" style={{ flexWrap: "wrap", gap: 8 }}>
          <span className="card-title">{pageTitle} <span className="text-subtle text-sm">({filtered.length})</span></span>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <input
              placeholder="Search…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{ width: 140, minWidth: 100 }}
            />
            {canManageStock && (
              <button className="btn btn-secondary btn-sm" onClick={() => setShowCatalog(true)} title="Pick from suggested product list">
                <Plus size={14} /> Catalog
              </button>
            )}
            {canManageStock && (
              <button className="btn btn-secondary btn-sm" onClick={() => setShowBulk(true)} title="Add many product names at once">
                <Plus size={14} /> Quick Add
              </button>
            )}
            {canManageStock && (
              <button
                className="btn btn-primary btn-sm"
                onClick={() => canAddActive ? setShowAdd(true) : null}
                title={canAddActive ? undefined : `Basic plan: ${inventoryLim} active products. Upgrade to Go for unlimited.`}
                style={canAddActive ? {} : { opacity: 0.5, cursor: "not-allowed" }}
              >
                <Plus size={14} /> {addLabel}
              </button>
            )}
          </div>
        </div>
        {inventoryLim !== null && (
          <div style={{ padding: "8px 16px 0" }}>
            <LimitBar
              used={activeCount}
              limit={inventoryLim}
              label="active products"
              upgradePlan="Go"
            />
          </div>
        )}
        <DataTable
          loading={loading}
          rows={filtered}
          emptyText={isServiceBiz
            ? "No services yet. Click 'Add Service / Product' to build your price list."
            : "No inventory items yet. Click Add Product to get started."
          }
          rowClass={r =>
            !r.is_service && r.is_available && r.low_stock_alert !== null && (r.quantity ?? 0) <= r.low_stock_alert
              ? "low-stock"
              : ""
          }
          columns={[
            {
              key: "name", label: "Name", sortKey: "name",
              render: r => {
                const attrLine = fields
                  .map(f => (r.attributes || {})[f.key])
                  .filter(Boolean)
                  .join(" · ");
                return (
                  <span>
                    <button type="button" className="name-chip" onClick={() => setDetailItem(r)}
                      title="Click to view, edit & adjust">
                      <span>{(r.name || "—").replace(/\b\w/g, c => c.toUpperCase())}</span>
                      <ChevronRight size={14} className="name-chip__chev" />
                    </button>
                    {r.is_service && <span className="svc-chip">service</span>}
                    {attrLine && <div className="td-attr-line">{attrLine}</div>}
                  </span>
                );
              },
            },
            {
              key: "qty_or_avail", label: "Stock / Status",
              render: r => r.is_service
                ? <span className="text-subtle">—</span>
                : <span>{(r.quantity ?? 0).toLocaleString()}{r.unit ? ` ${r.unit}` : ""}</span>,
            },
            { key: "selling_price", label: "Price", sortKey: "selling_price", render: r => nairaFull(r.selling_price) },
            {
              key: "cost_price", label: "Cost price",
              render: r => r.is_service
                ? <span className="text-subtle">—</span>
                : (r.cost_price ? nairaFull(r.cost_price) : <span className="text-subtle">—</span>),
            },
            {
              key: "alert", label: "Alert at",
              render: r => r.is_service
                ? <span className="text-subtle">—</span>
                : (r.low_stock_alert !== null ? r.low_stock_alert.toLocaleString() : <span className="text-subtle">—</span>),
            },
            {
              key: "status", label: "Status",
              render: r => r.is_service
                ? <span className={`badge ${r.is_available ? "badge-green" : "badge-gray"}`}>{r.is_available ? "Active" : "Inactive"}</span>
                : <StockBadge available={r.is_available} quantity={r.quantity ?? 0} alert={r.low_stock_alert} />,
            },
            { key: "updated_at", label: "Updated", render: r => <span className="td-muted">{dateStr(r.updated_at)}</span> },
            {
              key: "actions", label: "",
              render: r => (!canManageStock || r.is_service) ? null : (
                <button className="btn btn-ghost btn-xs" onClick={() => setAdjustItem(r)} title="Adjust stock">±</button>
              ),
            },
          ]}
        />
      </div>

      {showCatalog && (
        <CatalogPickerModal
          ownerPhone={ownerPhone}
          onClose={() => setShowCatalog(false)}
          onSaved={load}
        />
      )}

      {showBulk && (
        <BulkAddModal
          ownerPhone={ownerPhone}
          onClose={() => setShowBulk(false)}
          onSaved={load}
        />
      )}

      {showAdd && (
        <AddItemModal
          ownerPhone={ownerPhone}
          isServiceBiz={isServiceBiz}
          fields={fields}
          onClose={() => setShowAdd(false)}
          onSaved={item => {
            setRows(prev => [{ ...item, is_available: true, is_service: item.is_service ?? false }, ...prev]);
          }}
        />
      )}

      {editItem && (
        <EditItemModal
          item={editItem}
          fields={fields}
          onClose={() => setEditItem(null)}
          onSaved={load}
        />
      )}

      {adjustItem && (
        <AdjustModal
          item={adjustItem}
          onClose={() => setAdjustItem(null)}
          onSaved={load}
        />
      )}

      {detailItem && (
        <ItemDetailModal
          item={detailItem}
          fields={fields}
          canManage={canManageStock}
          onClose={() => setDetailItem(null)}
          onEdit={it => { setDetailItem(null); setEditItem(it); }}
          onAdjust={it => { setDetailItem(null); setAdjustItem(it); }}
        />
      )}
    </>
  );
}
