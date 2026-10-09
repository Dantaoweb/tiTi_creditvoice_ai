import { useState, useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Plus, Trash2, User, X, Camera } from "lucide-react";
import { apiFetch, apiPost, apiPut } from "../lib/api";
import { nairaFull, fmtAmt, parseAmt } from "../lib/format";
import DiscountInput from "../components/DiscountInput";
import CameraScanner from "../components/CameraScanner";
import { discountAmount, NO_DISCOUNT } from "../lib/discount";

// Writing an invoice is asking to be paid — nothing is owed and nothing leaves
// stock until the money or the goods actually move (see InvoiceView).

const blankLine = () => ({ key: Math.random(), inventory_item_id: null, name: "", unit: "", qty: "1", unit_price: "" });

function CustomerPicker({ customer, onPick, onClear }) {
  const [q, setQ] = useState("");
  const [found, setFound] = useState({ q: "", items: [] });
  const term = q.trim();

  useEffect(() => {
    if (!term) return;
    let live = true;
    const t = setTimeout(() => {
      apiFetch("customers", { q: term, limit: 8 })
        .then(d => { if (live) setFound({ q: term, items: d.customers || [] }); })
        .catch(() => { if (live) setFound({ q: term, items: [] }); });
    }, 250);
    return () => { live = false; clearTimeout(t); };
  }, [term]);

  if (customer) {
    return (
      <div className="pos-customer-pill">
        <User size={13} />
        <span>{customer.name}{customer.isNew ? " · new" : ""}</span>
        {customer.balance > 0 && <span className="pos-customer-debt">owes {nairaFull(customer.balance)}</span>}
        <button type="button" onClick={onClear}><X size={13} /></button>
      </div>
    );
  }

  const results = term && found.q === term ? found.items : [];
  const exact = results.some(c => c.name.toLowerCase() === term.toLowerCase());
  return (
    <div style={{ position: "relative" }}>
      <input placeholder="Search a customer, or type a new name"
        value={q} onChange={e => setQ(e.target.value)} />
      {term && (
        <div className="invoice-suggest">
          {results.map(c => (
            <button type="button" key={c.id} onClick={() => onPick(c)}>
              <strong>{c.name}</strong>
              {c.phone && <span className="td-muted"> · {c.phone}</span>}
            </button>
          ))}
          {!exact && (
            <button type="button" onClick={() => onPick({ name: term, isNew: true })}>
              <Plus size={13} /> Add “{term}” as a new customer
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function ProductInput({ line, onChange }) {
  const [found, setFound] = useState({ q: "", items: [] });
  const [focus, setFocus] = useState(false);
  const term = line.name.trim();

  useEffect(() => {
    if (!term || line.inventory_item_id) return;
    let live = true;
    const t = setTimeout(() => {
      apiFetch("pos/products", { q: term, limit: 8 })
        .then(d => { if (live) setFound({ q: term, items: d.products || [] }); })
        .catch(() => { if (live) setFound({ q: term, items: [] }); });
    }, 250);
    return () => { live = false; clearTimeout(t); };
  }, [term, line.inventory_item_id]);

  const results = focus && term && found.q === term && !line.inventory_item_id ? found.items : [];
  return (
    <div style={{ position: "relative", flex: "2 1 180px" }}>
      <input placeholder="Item or service"
        value={line.name}
        onFocus={() => setFocus(true)}
        onBlur={() => setTimeout(() => setFocus(false), 150)}
        // Typing again unlinks it from the stock item it was picked from.
        onChange={e => onChange({ name: e.target.value, inventory_item_id: null })} />
      {results.length > 0 && (
        <div className="invoice-suggest">
          {results.map(p => (
            <button type="button" key={p.id} onMouseDown={e => e.preventDefault()}
              onClick={() => onChange({
                name: p.name, inventory_item_id: p.id, unit: p.unit || "",
                unit_price: fmtAmt(p.selling_price),
              })}>
              <strong>{p.name}</strong>
              <span className="td-muted">
                {" "}· {nairaFull(p.selling_price)}{!p.is_service && ` · ${p.quantity} in stock`}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function InvoiceEditor() {
  const { id } = useParams();            // set when editing
  const navigate = useNavigate();
  const [customer, setCustomer] = useState(null);
  const [newPhone, setNewPhone] = useState("");
  const [lines, setLines] = useState([blankLine()]);
  const [dueDate, setDueDate] = useState("");
  const [note, setNote] = useState("");
  const [discountValue, setDiscountValue] = useState(NO_DISCOUNT);
  const [camera, setCamera] = useState(false);

  // A scanned product becomes a line; scanning it again adds one more.
  async function addScanned(code) {
    try {
      const res = await apiFetch("pos/scan", { code });
      if (!res.found) return { label: `Not recognised: ${code}`, ok: false };
      const p = res.product;
      setLines(ls => {
        const kept = ls.filter(l => l.name.trim());
        const same = kept.find(l => l.inventory_item_id === p.id);
        if (same) {
          return kept.map(l => l === same ? { ...l, qty: String(parseAmt(l.qty) + 1) } : l);
        }
        return [...kept, {
          ...blankLine(), inventory_item_id: p.id, name: p.name, unit: p.unit || "",
          unit_price: p.selling_price ? fmtAmt(p.selling_price) : "",
        }];
      });
      return { label: `Added ${p.name}` };
    } catch {
      return { label: "Could not look that up — check your connection", ok: false };
    }
  }
  const [loading, setLoading] = useState(!!id);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!id) return;
    apiFetch(`invoices/doc/${id}`)
      .then(doc => {
        setCustomer(doc.customer);
        setLines(doc.items.map(it => ({
          key: Math.random(), inventory_item_id: it.inventory_item_id, name: it.name,
          unit: it.unit || "", qty: String(it.qty), unit_price: fmtAmt(it.unit_price),
          sold_unit: it.sold_unit, fraction: it.fraction,
        })));
        setDueDate(doc.due_date ? doc.due_date.slice(0, 10) : "");
        setNote(doc.note || "");
        if (doc.discount) setDiscountValue({ input: Number(doc.discount).toLocaleString("en-NG"), pct: false });
      })
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  const setLine = (key, patch) => setLines(ls => ls.map(l => (l.key === key ? { ...l, ...patch } : l)));
  const lineTotal = l => Math.round(parseAmt(l.qty) * parseAmt(l.unit_price));
  const filled = lines.filter(l => l.name.trim());
  const subtotal = filled.reduce((s, l) => s + lineTotal(l), 0);
  const discount = discountAmount(subtotal, discountValue);   // off the whole invoice
  const total = subtotal - discount;

  async function save(e) {
    e.preventDefault();
    setErr("");
    if (!customer) return setErr("Choose who the invoice is for.");
    if (!filled.length) return setErr("Add at least one item.");
    const items = filled.map(l => ({
      inventory_item_id: l.inventory_item_id, name: l.name.trim(), unit: l.unit || null,
      qty: parseAmt(l.qty), unit_price: Math.round(parseAmt(l.unit_price)),
      sold_unit: l.sold_unit || null, fraction: l.fraction ?? 1,
    }));
    const body = { items, due_date: dueDate || null, note: note.trim() || null, discount };
    setBusy(true);
    try {
      const doc = id
        ? await apiPut(`invoices/doc/${id}`, body)
        : await apiPost("invoices/new", {
            ...body,
            ...(customer.isNew
              ? { customer_name: customer.name, customer_phone: newPhone.trim() || null }
              : { customer_id: customer.id }),
          });
      navigate(`/invoices/${doc.id}`, { replace: true });
    } catch (e2) {
      setErr(e2.message);
      setBusy(false);
    }
  }

  if (loading) return <div className="page-loading">Loading invoice…</div>;

  return (
    <form className="card invoice-form" style={{ maxWidth: 760 }} onSubmit={save}>
      <div className="card-header" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => navigate(id ? `/invoices/${id}` : "/invoices")}>
          <ArrowLeft size={15} />
        </button>
        <span className="card-title">{id ? "Edit invoice" : "New invoice"}</span>
      </div>

      <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 16 }}>
        <div className="invoice-hint">
          An invoice asks the customer to pay. It is <strong>not a debt</strong> and takes nothing
          out of stock. Stock goes out when you mark it delivered, and any unpaid part becomes
          debt when you record the payment.
        </div>

        <div>
          <label className="form-label">Bill to</label>
          {id ? (
            <div className="pos-customer-pill"><User size={13} /><span>{customer?.name}</span></div>
          ) : (
            <CustomerPicker customer={customer} onPick={setCustomer} onClear={() => setCustomer(null)} />
          )}
          {customer?.isNew && (
            <input style={{ marginTop: 8 }} inputMode="tel"
              placeholder="Their WhatsApp number (optional, to send the invoice)"
              value={newPhone} onChange={e => setNewPhone(e.target.value)} />
          )}
        </div>

        <div>
          <label className="form-label">Items</label>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {lines.map(l => (
              <div key={l.key} className="invoice-line">
                <ProductInput line={l} onChange={patch => setLine(l.key, patch)} />
                <input style={{ flex: "0 1 80px" }} inputMode="decimal"
                  aria-label="Quantity" placeholder="Qty" value={l.qty}
                  onChange={e => setLine(l.key, { qty: e.target.value })} />
                <input style={{ flex: "1 1 110px" }} inputMode="numeric"
                  aria-label="Price" placeholder="Price ₦" value={l.unit_price}
                  onChange={e => setLine(l.key, { unit_price: fmtAmt(e.target.value) })} />
                <span className="invoice-line-total">{nairaFull(lineTotal(l))}</span>
                <button type="button" className="btn btn-ghost btn-sm" aria-label="Remove item"
                  disabled={lines.length === 1}
                  onClick={() => setLines(ls => ls.filter(x => x.key !== l.key))}>
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
            <button type="button" className="btn btn-ghost btn-sm"
              onClick={() => setLines(ls => [...ls, blankLine()])}>
              <Plus size={14} /> Add item
            </button>
            <button type="button" className="cam-scan-btn" onClick={() => setCamera(true)}>
              <Camera size={15} /> Scan items
            </button>
          </div>
          {camera && (
            <CameraScanner continuous title="Scan items onto the invoice"
              onCode={addScanned} onClose={() => setCamera(false)} />
          )}
        </div>

        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 180px" }}>
            <label className="form-label">Pay by (optional)</label>
            <input type="date" value={dueDate} onChange={e => setDueDate(e.target.value)} />
          </div>
          <div style={{ flex: "2 1 240px" }}>
            <label className="form-label">Note (optional)</label>
            <input maxLength={500} placeholder="e.g. Bank details, delivery terms"
              value={note} onChange={e => setNote(e.target.value)} />
          </div>
        </div>

        {err && <div className="pos-error" style={{ margin: 0 }}>{err}</div>}

        {subtotal > 0 && (
          <div style={{ maxWidth: 360, marginLeft: "auto", width: "100%" }}>
            <DiscountInput value={discountValue} onChange={setDiscountValue} />
            {discount > 0 && (
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, color: "var(--muted)" }}>
                <span>Subtotal {nairaFull(subtotal)}</span><span>−{nairaFull(discount)}</span>
              </div>
            )}
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <span style={{ fontSize: 15 }}>Total: <strong>{nairaFull(total)}</strong></span>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Saving…" : id ? "Save changes" : "Create invoice"}
          </button>
        </div>
      </div>
    </form>
  );
}
