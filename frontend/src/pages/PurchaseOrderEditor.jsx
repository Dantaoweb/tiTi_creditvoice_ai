import { useState, useEffect } from "react";
import { useNavigate, useParams, useLocation } from "react-router-dom";
import { Plus, Trash2 } from "lucide-react";
import { apiFetch, apiPost, apiPut } from "../lib/api";
import { nairaFull, fmtAmt, parseAmt } from "../lib/format";

const blank = () => ({ key: Math.random(), inventory_item_id: null, product: "", unit: "", quantity: "", unit_cost: "" });

// One order line: type a product (your stock list is suggested) or a new one
function LineRow({ line, onChange, onRemove }) {
  const [found, setFound] = useState([]);
  useEffect(() => {
    const term = line.product.trim();
    if (line.inventory_item_id || term.length < 2) return undefined;
    const t = setTimeout(() => {
      apiFetch("inventory", { q: term, limit: 6 }).then(d => setFound(d.items || [])).catch(() => setFound([]));
    }, 250);
    return () => clearTimeout(t);
  }, [line.product, line.inventory_item_id]);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr auto", gap: 6, alignItems: "start", marginBottom: 8 }}>
      <div style={{ position: "relative" }}>
        <input value={line.product} placeholder="Product" maxLength={120}
          onChange={e => onChange({ product: e.target.value, inventory_item_id: null })} style={{ width: "100%" }} />
        {found.length > 0 && !line.inventory_item_id && (
          <div className="card" style={{ position: "absolute", zIndex: 5, left: 0, right: 0, top: "100%", padding: 4 }}>
            {found.map(p => (
              <button key={p.id} type="button" className="btn btn-ghost btn-sm" style={{ display: "block", width: "100%", textAlign: "left" }}
                onMouseDown={e => e.preventDefault()}
                onClick={() => { setFound([]); onChange({ product: p.name, inventory_item_id: p.id, unit: p.unit || "",
                  unit_cost: p.cost_price ? fmtAmt(String(p.cost_price)) : line.unit_cost }); }}>
                {p.name} <span className="td-muted">· {p.quantity ?? 0} in stock</span>
              </button>
            ))}
          </div>
        )}
        {line.unit && <div className="td-muted" style={{ fontSize: 11 }}>{line.unit}</div>}
      </div>
      <input inputMode="numeric" value={line.quantity} placeholder="Qty" onChange={e => onChange({ quantity: e.target.value.replace(/\D/g, "") })} />
      <input inputMode="numeric" value={line.unit_cost} placeholder="Cost each ₦" onChange={e => onChange({ unit_cost: fmtAmt(e.target.value) })} />
      <button type="button" className="btn btn-ghost btn-sm" onClick={onRemove} aria-label="Remove"><Trash2 size={14} /></button>
    </div>
  );
}

/* Write or change a purchase order. Opening it from "Running low" fills in
   the products and the supplier. */
export default function PurchaseOrderEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const prefill = useLocation().state;
  const [suppliers, setSuppliers] = useState([]);
  const [supplier, setSupplier] = useState(prefill?.supplier_name || "");
  const [expected, setExpected] = useState("");
  const [note, setNote] = useState("");
  const [lines, setLines] = useState(() => prefill?.lines?.length
    ? prefill.lines.map(l => ({ ...blank(), ...l, unit_cost: l.unit_cost ? fmtAmt(l.unit_cost) : "" })) : [blank()]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    apiFetch("suppliers").then(d => setSuppliers((d.suppliers || []).map(s => s.name))).catch(() => {});
    if (id) {
      apiFetch(`purchase-orders/${id}`).then(po => {
        setSupplier(po.supplier?.name || ""); setExpected(po.expected_date || ""); setNote(po.note || "");
        setLines(po.lines.map(l => ({ ...blank(), inventory_item_id: l.inventory_item_id, product: l.product,
          unit: l.unit || "", quantity: String(l.quantity), unit_cost: l.unit_cost ? fmtAmt(String(l.unit_cost)) : "" })));
      }).catch(e => setErr(e.message));
    }
  }, [id]);

  const set = (i, patch) => setLines(ls => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const filled = lines.filter(l => l.product.trim() && Number(l.quantity) > 0);
  const total = filled.reduce((s, l) => s + Number(l.quantity) * (parseAmt(l.unit_cost) || 0), 0);

  async function save(e) {
    e.preventDefault();
    if (!supplier.trim()) { setErr("Choose or type the supplier."); return; }
    if (!filled.length) { setErr("Add at least one product with how many to order."); return; }
    setBusy(true); setErr("");
    const body = {
      supplier_name: supplier.trim(), expected_date: expected || null, note: note.trim() || null,
      lines: filled.map(l => ({ inventory_item_id: l.inventory_item_id, product: l.product.trim(), unit: l.unit || null,
                                quantity: Number(l.quantity), unit_cost: l.unit_cost ? parseAmt(l.unit_cost) : null })),
    };
    try {
      const po = id ? await apiPut(`purchase-orders/${id}`, body) : await apiPost("purchase-orders", body);
      navigate(`/purchase-orders/${po.id}`, { replace: true });
    } catch (e2) { setErr(e2.message); setBusy(false); }
  }

  return (
    <form className="card" style={{ maxWidth: 720, padding: 16, display: "grid", gap: 12 }} onSubmit={save}>
      <span className="card-title">{id ? "Change purchase order" : "New purchase order"}</span>
      <div>
        <label className="form-label">Supplier</label>
        <input value={supplier} onChange={e => setSupplier(e.target.value)} list="po-suppliers" maxLength={120}
          placeholder="Search or type a supplier…" style={{ width: "100%" }} />
        <datalist id="po-suppliers">{suppliers.map(n => <option key={n} value={n.replace(/\b\w/g, c => c.toUpperCase())} />)}</datalist>
      </div>
      <div>
        <label className="form-label">What you're ordering</label>
        {lines.map((l, i) => (
          <LineRow key={l.key} line={l} onChange={p => set(i, p)}
            onRemove={() => setLines(ls => (ls.length > 1 ? ls.filter((_, j) => j !== i) : [blank()]))} />
        ))}
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setLines(ls => [...ls, blank()])}>
          <Plus size={14} /> Add product
        </button>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <div>
          <label className="form-label">Deliver by <span className="text-subtle">(optional)</span></label>
          <input type="date" value={expected} onChange={e => setExpected(e.target.value)} style={{ width: "100%" }} />
        </div>
        <div>
          <label className="form-label">Note <span className="text-subtle">(optional)</span></label>
          <input value={note} maxLength={300} onChange={e => setNote(e.target.value)} placeholder="e.g. Deliver to the back gate" style={{ width: "100%" }} />
        </div>
      </div>
      {err && <div className="modal-error">{err}</div>}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span>Total: <strong>{nairaFull(total)}</strong> <span className="td-muted" style={{ fontSize: 12 }}>— nothing is owed until goods arrive</span></span>
        <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : id ? "Save changes" : "Create order"}</button>
      </div>
    </form>
  );
}
