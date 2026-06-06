import { useEffect, useState } from "react";
import { Plus, Pencil, PlusCircle, MinusCircle } from "lucide-react";
import { useApp } from "../context/AppContext";
import { apiFetch, apiPost, apiPut } from "../lib/api";
import { nairaFull, dateStr } from "../lib/format";
import DataTable from "../components/DataTable";
import { StockBadge } from "../components/Badge";

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

// ── Add item modal ───────────────────────────────────────────────────────────
function AddItemModal({ ownerPhone, onClose, onSaved }) {
  const [form, setForm] = useState({
    name: "", unit: "", quantity: 0,
    cost_price: "", selling_price: "", low_stock_alert: "",
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  function set(k, v) { setForm(p => ({ ...p, [k]: v })); }

  async function save() {
    if (!form.name.trim()) { setErr("Product name is required."); return; }
    setSaving(true); setErr("");
    try {
      const item = await apiPost("inventory", {
        owner_phone: ownerPhone,
        name: form.name.trim(),
        unit: form.unit.trim() || null,
        quantity: parseInt(form.quantity) || 0,
        cost_price: form.cost_price ? parseInt(form.cost_price) : null,
        selling_price: form.selling_price ? parseInt(form.selling_price) : null,
        low_stock_alert: form.low_stock_alert ? parseInt(form.low_stock_alert) : null,
      });
      onSaved(item);
      onClose();
    } catch (e) { setErr(e.message); }
    finally { setSaving(false); }
  }

  return (
    <Modal title="Add Product" onClose={onClose}>
      <div className="modal-body">
        <div className="form-row">
          <div className="form-group">
            <label className="form-label">Product name *</label>
            <input value={form.name} onChange={e => set("name", e.target.value)} placeholder="e.g. Indomie Noodles" />
          </div>
          <div className="form-group" style={{ width: 120 }}>
            <label className="form-label">Unit</label>
            <input value={form.unit} onChange={e => set("unit", e.target.value)} placeholder="e.g. carton" />
          </div>
        </div>
        <div className="form-row">
          <div className="form-group">
            <label className="form-label">Opening stock</label>
            <input type="number" min={0} value={form.quantity} onChange={e => set("quantity", e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">Low-stock alert</label>
            <input type="number" min={0} value={form.low_stock_alert} onChange={e => set("low_stock_alert", e.target.value)} placeholder="optional" />
          </div>
        </div>
        <div className="form-row">
          <div className="form-group">
            <label className="form-label">Cost price (₦)</label>
            <input type="number" min={0} value={form.cost_price} onChange={e => set("cost_price", e.target.value)} placeholder="0" />
          </div>
          <div className="form-group">
            <label className="form-label">Selling price (₦)</label>
            <input type="number" min={0} value={form.selling_price} onChange={e => set("selling_price", e.target.value)} placeholder="0" />
          </div>
        </div>
        {err && <div className="modal-error">{err}</div>}
      </div>
      <div className="modal-footer">
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Add Product"}
        </button>
      </div>
    </Modal>
  );
}

// ── Edit item modal ──────────────────────────────────────────────────────────
function EditItemModal({ item, onClose, onSaved }) {
  const [form, setForm] = useState({
    name: item.name,
    unit: item.unit || "",
    cost_price: item.cost_price || "",
    selling_price: item.selling_price || "",
    low_stock_alert: item.low_stock_alert ?? "",
    is_available: item.is_available,
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  function set(k, v) { setForm(p => ({ ...p, [k]: v })); }

  async function save() {
    setSaving(true); setErr("");
    try {
      await apiPut(`inventory/${item.id}`, {
        name: form.name.trim() || null,
        unit: form.unit.trim() || null,
        cost_price: form.cost_price !== "" ? parseInt(form.cost_price) : null,
        selling_price: form.selling_price !== "" ? parseInt(form.selling_price) : null,
        low_stock_alert: form.low_stock_alert !== "" ? parseInt(form.low_stock_alert) : null,
        is_available: form.is_available,
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
            <label className="form-label">Product name</label>
            <input value={form.name} onChange={e => set("name", e.target.value)} />
          </div>
          <div className="form-group" style={{ width: 120 }}>
            <label className="form-label">Unit</label>
            <input value={form.unit} onChange={e => set("unit", e.target.value)} />
          </div>
        </div>
        <div className="form-row">
          <div className="form-group">
            <label className="form-label">Cost price (₦)</label>
            <input type="number" min={0} value={form.cost_price} onChange={e => set("cost_price", e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">Selling price (₦)</label>
            <input type="number" min={0} value={form.selling_price} onChange={e => set("selling_price", e.target.value)} />
          </div>
        </div>
        <div className="form-row">
          <div className="form-group">
            <label className="form-label">Low-stock alert</label>
            <input type="number" min={0} value={form.low_stock_alert} onChange={e => set("low_stock_alert", e.target.value)} />
          </div>
          <div className="form-group" style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingTop: 20 }}>
            <input type="checkbox" id="is_avail" checked={form.is_available} onChange={e => set("is_available", e.target.checked)} />
            <label htmlFor="is_avail" className="form-label" style={{ margin: 0 }}>Available for sale</label>
          </div>
        </div>
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

// ── Adjust stock modal ───────────────────────────────────────────────────────
function AdjustModal({ item, onClose, onSaved }) {
  const [delta, setDelta] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  async function save(direction) {
    const qty = parseInt(delta);
    if (!qty || qty <= 0) { setErr("Enter a quantity greater than 0."); return; }
    setSaving(true); setErr("");
    try {
      await apiPost(`inventory/${item.id}/adjust`, {
        qty_delta: direction === "in" ? qty : -qty,
        note: note.trim() || null,
      });
      onSaved();
      onClose();
    } catch (e) { setErr(e.message); }
    finally { setSaving(false); }
  }

  return (
    <Modal title={`Adjust Stock: ${item.name}`} onClose={onClose}>
      <div className="modal-body">
        <div className="adjust-current">
          Current stock: <strong>{item.quantity}{item.unit ? ` ${item.unit}` : ""}</strong>
        </div>
        <div className="form-group">
          <label className="form-label">Quantity</label>
          <input
            type="number" min={1}
            value={delta}
            onChange={e => setDelta(e.target.value)}
            placeholder="How many?"
          />
        </div>
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

// ── Main page ────────────────────────────────────────────────────────────────
export default function Inventory() {
  const { ownerPhone } = useApp();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [editItem, setEditItem] = useState(null);
  const [adjustItem, setAdjustItem] = useState(null);

  function load() {
    setLoading(true);
    apiFetch("inventory", { owner_phone: ownerPhone })
      .then(d => setRows(d.items))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(load, [ownerPhone]);

  const filtered = search
    ? rows.filter(r => (r.name || "").toLowerCase().includes(search.toLowerCase()))
    : rows;

  const lowCount = rows.filter(
    r => r.is_available && r.low_stock_alert !== null && r.quantity <= r.low_stock_alert
  ).length;

  return (
    <>
      {error && <div style={{ color: "var(--rose)" }}>{error}</div>}

      {lowCount > 0 && (
        <div className="card card-body" style={{ display: "flex", gap: 8, color: "var(--amber)", fontSize: 13.5 }}>
          ⚠️ <strong>{lowCount}</strong> product{lowCount !== 1 ? "s" : ""} below the low-stock alert level.
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <span className="card-title">Inventory <span className="text-subtle text-sm">({filtered.length})</span></span>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              placeholder="Search product…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{ width: 200 }}
            />
            <button className="btn btn-primary btn-sm" onClick={() => setShowAdd(true)}>
              <Plus size={14} /> Add Product
            </button>
          </div>
        </div>
        <DataTable
          loading={loading}
          rows={filtered}
          emptyText="No inventory items yet. Click Add Product to get started."
          rowClass={r =>
            r.is_available && r.low_stock_alert !== null && r.quantity <= r.low_stock_alert
              ? "low-stock"
              : ""
          }
          columns={[
            {
              key: "name", label: "Product", sortKey: "name",
              render: r => <strong className="td-strong">{(r.name || "—").replace(/\b\w/g, c => c.toUpperCase())}</strong>,
            },
            {
              key: "quantity", label: "Qty in stock", sortKey: "quantity",
              render: r => <span>{Number(r.quantity).toLocaleString()}{r.unit ? ` ${r.unit}` : ""}</span>,
            },
            { key: "selling_price", label: "Selling price", sortKey: "selling_price", render: r => nairaFull(r.selling_price) },
            { key: "cost_price",    label: "Cost price",    render: r => r.cost_price ? nairaFull(r.cost_price) : <span className="text-subtle">—</span> },
            { key: "alert",         label: "Alert at",      render: r => r.low_stock_alert !== null ? r.low_stock_alert : <span className="text-subtle">—</span> },
            { key: "status",        label: "Status",        render: r => <StockBadge available={r.is_available} quantity={r.quantity} alert={r.low_stock_alert} /> },
            { key: "updated_at",    label: "Updated",       render: r => <span className="td-muted">{dateStr(r.updated_at)}</span> },
            {
              key: "actions", label: "",
              render: r => (
                <div style={{ display: "flex", gap: 6 }}>
                  <button className="btn btn-ghost btn-xs" onClick={() => setAdjustItem(r)} title="Adjust stock">
                    ±
                  </button>
                  <button className="btn btn-ghost btn-xs" onClick={() => setEditItem(r)} title="Edit">
                    <Pencil size={12} />
                  </button>
                </div>
              ),
            },
          ]}
        />
      </div>

      {showAdd && (
        <AddItemModal
          ownerPhone={ownerPhone}
          onClose={() => setShowAdd(false)}
          onSaved={item => { setRows(prev => [{ ...item, is_available: true }, ...prev]); }}
        />
      )}

      {editItem && (
        <EditItemModal
          item={editItem}
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
    </>
  );
}
