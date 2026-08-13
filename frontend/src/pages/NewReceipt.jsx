import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { Plus, Trash2, ArrowLeft } from "lucide-react";
import { useApp } from "../context/AppContext";
import { apiPost } from "../lib/api";
import { nairaFull, parseAmt } from "../lib/format";
import MoneyInput from "../components/MoneyInput";
import { InventorySearch, CustomerSearch } from "./Capture";

// A blank receipt you fill in and record. Each line is either a listed stock
// item (deducts stock on save) or a custom one-off (acknowledged, no stock),
// with an optional "save to my products". Records through the same pos/save
// engine as the POS, so the finished receipt lands in the Receipts menu.
let _rowKey = 1;
const newRow = () => ({ key: _rowKey++, item: null, price: "", qtyVal: "1", save: false });

export default function NewReceipt() {
  const { ownerPhone } = useApp();
  const navigate = useNavigate();
  const [rows, setRows]           = useState([newRow()]);
  const [customer, setCustomer]   = useState(null);
  const [custQuery, setCustQuery] = useState("");
  const [settleDebt, setSettleDebt] = useState(true);
  const [paid, setPaid]           = useState("");
  const [saving, setSaving]       = useState(false);
  const [err, setErr]             = useState("");

  const setRow = (key, patch) => setRows(rs => rs.map(r => r.key === key ? { ...r, ...patch } : r));
  const addRow = () => setRows(rs => [...rs, newRow()]);
  const removeRow = key => setRows(rs => rs.length > 1 ? rs.filter(r => r.key !== key) : rs);

  // Picking a listed item prefills its price; a typed custom item leaves it blank.
  function pickItem(key, item) {
    if (item && !item.isNew && item.selling_price != null) setRow(key, { item, price: String(item.selling_price) });
    else setRow(key, { item });
  }

  const valid = rows.filter(r => r.item && r.item.name && parseAmt(r.price) > 0 && parseAmt(r.qtyVal) > 0);
  const total     = valid.reduce((s, r) => s + parseAmt(r.price) * parseAmt(r.qtyVal), 0);
  const prevDebt  = (customer && customer.balance > 0) ? customer.balance : 0;
  const debtDue   = settleDebt ? prevDebt : 0;
  const amountDue = total + debtDue;
  const payNum    = parseAmt(paid);
  const salePaid  = customer ? Math.min(payNum, total) : total;
  const debtPaid  = customer ? Math.min(Math.max(0, payNum - total), debtDue) : 0;
  const change    = Math.max(0, payNum - amountDue);
  const owed      = customer ? total - salePaid : 0;

  async function save() {
    if (valid.length === 0) { setErr("Add at least one item with a price."); return; }
    if (!customer && custQuery.trim()) {
      setErr(`"${custQuery.trim()}" isn't attached — tap them in the list or Add as new, or clear the box for a cash receipt.`);
      return;
    }
    setSaving(true); setErr("");
    try {
      const items = valid.map(r => ({
        inventory_item_id: (r.item && !r.item.isNew) ? r.item.id : null,
        name: r.item.name,
        qty: parseAmt(r.qtyVal),
        unit: r.item.unit || null,
        unit_price: parseAmt(r.price),
      }));
      const res = await apiPost("pos/save", {
        owner_phone:    ownerPhone,
        customer_id:    customer?.id || null,
        customer_name:  (customer && !customer.id) ? customer.name : null,
        customer_phone: (customer && !customer.id) ? (customer.phone?.trim() || null) : null,
        items,
        payment_amount: salePaid,
        debt_payment:   debtPaid,
        branch_id:      null,
      });
      // Best-effort: add ticked custom lines to the product list for next time.
      for (const r of valid) {
        if (r.save && r.item.isNew) {
          try { await apiPost("inventory", { owner_phone: ownerPhone, name: r.item.name, selling_price: parseAmt(r.price) }); }
          catch { /* at the plan cap or a duplicate — ignore; the receipt is already saved */ }
        }
      }
      navigate(res?.receipt_id ? `/pos/receipt/${res.receipt_id}` : "/receipts");
    } catch (e) { setErr(e.message); }
    finally { setSaving(false); }
  }

  return (
    <div className="card" style={{ maxWidth: 640 }}>
      <div className="card-header">
        <span className="card-title">New Receipt</span>
        <Link to="/receipts" className="btn btn-ghost btn-sm"><ArrowLeft size={14} /> Receipts</Link>
      </div>

      <div style={{ padding: 16, display: "grid", gap: 14 }}>
        <div style={{ display: "grid", gap: 10 }}>
          {rows.map((r, i) => (
            <div key={r.key} style={{ border: "1px solid var(--line)", borderRadius: 8, padding: 10, display: "grid", gap: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span className="td-muted" style={{ fontSize: 12 }}>Item {i + 1}</span>
                {rows.length > 1 && (
                  <button type="button" className="link-btn" style={{ color: "var(--rose)" }} onClick={() => removeRow(r.key)}>
                    <Trash2 size={13} />
                  </button>
                )}
              </div>
              <InventorySearch ownerPhone={ownerPhone} value={r.item} allowNew onSelect={item => pickItem(r.key, item)} />
              <div style={{ display: "flex", gap: 8 }}>
                <div className="form-group" style={{ margin: 0, flex: 1 }}>
                  <label className="form-label">Qty</label>
                  <MoneyInput value={r.qtyVal} onChange={v => setRow(r.key, { qtyVal: v })} placeholder="1" />
                </div>
                <div className="form-group" style={{ margin: 0, flex: 1 }}>
                  <label className="form-label">Unit price (₦)</label>
                  <MoneyInput value={r.price} onChange={v => setRow(r.key, { price: v })} placeholder="0" />
                </div>
                <div className="form-group" style={{ margin: 0, flex: 1 }}>
                  <label className="form-label">Line total</label>
                  <div style={{ paddingTop: 8, fontWeight: 700 }}>{nairaFull(parseAmt(r.price) * parseAmt(r.qtyVal))}</div>
                </div>
              </div>
              {r.item && r.item.isNew && (
                <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, cursor: "pointer" }}>
                  <input type="checkbox" checked={r.save} onChange={e => setRow(r.key, { save: e.target.checked })} style={{ width: "auto" }} />
                  Save “{r.item.name}” to my products for next time
                </label>
              )}
            </div>
          ))}
          <button type="button" className="btn btn-secondary btn-sm" onClick={addRow} style={{ justifySelf: "start" }}>
            <Plus size={14} /> Add item
          </button>
        </div>

        <div className="form-group">
          <label className="form-label">Customer <span className="text-subtle">— leave blank for a cash receipt</span></label>
          <CustomerSearch ownerPhone={ownerPhone} placeholder="Search customer…" allowNew value={customer}
            onSelect={c => { setCustomer(c); setSettleDebt(true); }} onQueryChange={setCustQuery} />
        </div>

        <div style={{ borderTop: "1px solid var(--line)", paddingTop: 10, display: "grid", gap: 6 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 700 }}>
            <span>Total</span><span>{nairaFull(total)}</span>
          </div>
          {prevDebt > 0 && (
            <>
              <label style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, fontSize: 13, cursor: "pointer" }}>
                <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input type="checkbox" checked={settleDebt} onChange={e => setSettleDebt(e.target.checked)} style={{ width: "auto" }} />
                  Settle previous debt
                </span>
                <span style={{ fontWeight: 600, color: settleDebt ? "var(--rose)" : "var(--muted)" }}>+{nairaFull(prevDebt)}</span>
              </label>
              {settleDebt && (
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span>Amount due</span><span>{nairaFull(amountDue)}</span>
                </div>
              )}
            </>
          )}
        </div>

        {customer && (
          <div className="form-group">
            <label className="form-label">Amount paid (₦) <span className="text-subtle">— blank = full credit</span></label>
            <MoneyInput value={paid} onChange={v => setPaid(v)} placeholder="0" />
            {payNum > 0 && change > 0 && <span className="form-hint">Change: {nairaFull(change)}</span>}
            {owed > 0 && <span className="form-hint">{customer.name} will owe {nairaFull(owed)}</span>}
          </div>
        )}

        {err && <div className="modal-error">{err}</div>}
        <button className="btn btn-primary" onClick={save} disabled={saving || valid.length === 0}>
          {saving ? "Saving…" : `Save & Generate Receipt · ${nairaFull(amountDue)}`}
        </button>
      </div>
    </div>
  );
}
