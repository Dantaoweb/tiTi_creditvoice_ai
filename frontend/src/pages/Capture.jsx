import { useState, useEffect, useRef } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Mic, MicOff, Play, Send, X, CheckCircle, ShoppingCart, CreditCard, Package } from "lucide-react";
import { useApp } from "../context/AppContext";
import { useAuth } from "../context/AuthContext";
import { apiFetch, apiPost } from "../lib/api";
import { enqueue, isNetworkError } from "../lib/offlineQueue";
import { nairaFull, qty } from "../lib/format";
import MoneyInput from "../components/MoneyInput";
import { useToast } from "../components/Toast";
import { getBizLabels } from "../lib/bizLabels";

function fmtAmt(s) {
  const raw = String(s || "").replace(/[^0-9]/g, "");
  return raw ? Number(raw).toLocaleString("en-NG") : "";
}
function parseAmt(s) { return Number(String(s || "").replace(/,/g, "")); }

async function blobToBase64(blob) {
  const buffer = await blob.arrayBuffer();
  let binary = "";
  new Uint8Array(buffer).forEach((b) => (binary += String.fromCharCode(b)));
  return btoa(binary);
}

// ── Shared search inputs ─────────────────────────────────────────────────────

export function CustomerSearch({ ownerPhone, placeholder, filterDebtors = false, allowNew = false, onSelect, value, onQueryChange }) {
  const [customers, setCustomers] = useState([]);
  const [search, setSearch]       = useState("");
  const [open, setOpen]           = useState(false);

  useEffect(() => {
    if (!ownerPhone) return;
    apiFetch("customers", { owner_phone: ownerPhone })
      .then(d => {
        let list = d.customers || [];
        if (filterDebtors) list = list.filter(c => c.balance > 0);
        setCustomers(list);
      })
      .catch(() => {});
  }, [ownerPhone, filterDebtors]);

  function setQuery(q) {
    setSearch(q);
    onQueryChange && onQueryChange(q);
  }

  const filtered = search.trim()
    ? customers.filter(c => c.name.toLowerCase().includes(search.toLowerCase()))
    : filterDebtors ? customers.slice(0, 8) : [];

  const exactMatch = filtered.some(c => c.name.toLowerCase() === search.trim().toLowerCase());
  const showAddNew = allowNew && search.trim().length >= 2 && !exactMatch;

  if (value) {
    return (
      <>
        <div className="qf-pill">
          <span>
            {value.name}{value.isNew ? " · new" : ""}
            {value.balance > 0 && <span className="text-rose"> — owes {nairaFull(value.balance)}</span>}
          </span>
          <button type="button" onClick={() => onSelect(null)}>×</button>
        </div>
        {value.isNew && (
          <input
            style={{ marginTop: 6 }}
            value={value.phone || ""}
            onChange={e => onSelect({ ...value, phone: e.target.value })}
            placeholder="Phone (optional)…"
            inputMode="tel"
          />
        )}
      </>
    );
  }

  return (
    <div className="qf-search-wrap">
      <input
        value={search}
        onChange={e => { setQuery(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder={placeholder}
      />
      {open && (filtered.length > 0 || showAddNew) && (
        <div className="qf-dropdown">
          {filtered.map(c => (
            <button key={c.id} type="button" onMouseDown={() => { onSelect(c); setQuery(""); setOpen(false); }}>
              <span>{c.name}</span>
              {c.balance > 0 && <span className="text-rose text-sm">{nairaFull(c.balance)}</span>}
            </button>
          ))}
          {showAddNew && (
            <button type="button" onMouseDown={() => {
              onSelect({ id: null, name: search.trim(), phone: null, isNew: true });
              setQuery(""); setOpen(false);
            }}>
              <span>➕ Add "{search.trim()}" as new customer</span>
            </button>
          )}
        </div>
      )}
      {open && filterDebtors && customers.length === 0 && (
        <div className="qf-dropdown">
          <div style={{ padding: "10px 14px", color: "var(--muted)", fontSize: 13 }}>No debtors found.</div>
        </div>
      )}
    </div>
  );
}

export function InventorySearch({ ownerPhone, onSelect, value, allowNew = false }) {
  const [items, setItems]   = useState([]);
  const [search, setSearch] = useState("");
  const [open, setOpen]     = useState(false);

  useEffect(() => {
    if (!ownerPhone) return;
    apiFetch("inventory", { owner_phone: ownerPhone })
      .then(d => setItems(d.items || []))
      .catch(() => {});
  }, [ownerPhone]);

  const q = search.trim();
  const filtered = q
    ? items.filter(i => i.name.toLowerCase().includes(q.toLowerCase()))
    : [];
  const exact = q && items.some(i => i.name.toLowerCase() === q.toLowerCase());
  const showNew = allowNew && q && !exact;

  if (value) {
    return (
      <div className="qf-pill">
        <span>
          {value.name}{" "}
          <span className="text-subtle">
            {value.isNew ? "— new product" : `— ${qty(value.quantity, value.unit || "units")} in stock`}
          </span>
        </span>
        <button type="button" onClick={() => onSelect(null)}>×</button>
      </div>
    );
  }

  return (
    <div className="qf-search-wrap">
      <input
        value={search}
        onChange={e => { setSearch(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder={allowNew ? "Search or type a new product…" : "Search product name…"}
      />
      {open && (filtered.length > 0 || showNew) && (
        <div className="qf-dropdown">
          {filtered.map(i => (
            <button key={i.id} type="button" onMouseDown={() => { onSelect(i); setSearch(""); setOpen(false); }}>
              <span>{i.name}</span>
              <span className="text-subtle text-sm">{qty(i.quantity, i.unit || "units")}</span>
            </button>
          ))}
          {showNew && (
            <button type="button" onMouseDown={() => { onSelect({ id: null, name: q, isNew: true }); setSearch(""); setOpen(false); }}>
              <span>+ Add new: <strong>{q}</strong></span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Branch selector ───────────────────────────────────────────────────────────

function BranchSelector({ ownerPhone, value, onChange }) {
  const [branches, setBranches] = useState([]);

  useEffect(() => {
    if (!ownerPhone) return;
    apiFetch("branches")
      .then(d => {
        const list = d.branches || [];
        setBranches(list);
        if (!value && list.length > 0) {
          const def = list.find(b => b.is_default) || list[0];
          onChange(def.id);
        }
      })
      .catch(() => {});
  }, [ownerPhone]);

  if (branches.length === 0) return null;

  return (
    <div className="form-group">
      <label className="form-label">Branch / Location</label>
      <select value={value || ""} onChange={e => onChange(e.target.value ? Number(e.target.value) : null)}>
        <option value="">— No branch tag —</option>
        {branches.map(b => (
          <option key={b.id} value={b.id}>{b.name}{b.is_default ? " (default)" : ""}</option>
        ))}
      </select>
    </div>
  );
}

// ── Form panels ──────────────────────────────────────────────────────────────

function SaleForm({ ownerPhone, onSuccess }) {
  const { user }                = useAuth();
  const L                       = getBizLabels(user?.menu_group);
  const [product, setProduct]   = useState("");
  const [qty, setQty]           = useState("1");
  const [unit, setUnit]         = useState("");
  const [amount, setAmount]     = useState("");
  const [paid, setPaid]         = useState("");
  const [customer, setCustomer] = useState(null);
  const [custQuery, setCustQuery] = useState("");   // typed-but-unselected search text
  const [settleDebt, setSettleDebt] = useState(true);   // fold prior debt into this sale
  const [branchId, setBranchId] = useState(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState(null);

  const prevDebt = (customer && customer.balance > 0) ? customer.balance : 0;
  const debtDue  = settleDebt ? prevDebt : 0;

  async function handleSubmit(e) {
    e.preventDefault();
    if (!product.trim() || !amount) return;
    setLoading(true); setError(null);
    // Typed a name but never tapped a result: without this guard the sale
    // silently saves as cash and any part payment is lost (no debt tracked).
    if (!customer && custQuery.trim()) {
      setError(
        `"${custQuery.trim()}" is not attached — tap them in the list, or tap ` +
        `"Add as new customer". To record a cash sale instead, clear the customer box.`
      );
      setLoading(false);
      return;
    }
    try {
      const qtyNum = Math.max(1, parseAmt(qty) || 1);
      const total  = parseAmt(amount);
      const paidNum = customer ? Math.min(parseAmt(paid) || 0, total) : total;
      // Surplus beyond the sale clears the customer's prior debt (up to what's owed).
      const debtPaid = customer ? Math.min(Math.max(0, (parseAmt(paid) || 0) - total), debtDue) : 0;
      const body   = {
        owner_phone:    ownerPhone,
        customer_id:    customer?.id || null,
        customer_name:  (customer && !customer.id) ? customer.name : null,
        customer_phone: (customer && !customer.id) ? (customer.phone?.trim() || null) : null,
        items:          [{ name: product.trim(), qty: qtyNum, unit: unit || null, unit_price: Math.round(total / qtyNum) }],
        payment_amount: paidNum,
        debt_payment:   debtPaid,
        branch_id:      branchId || null,
      };
      const result = await apiPost("pos/save", body);
      const bal = total - paidNum;
      onSuccess(
        customer
          ? `Sale of ${nairaFull(total)} to ${customer.name} — paid ${nairaFull(paidNum)}${bal > 0 ? `, balance ${nairaFull(bal)}` : " (fully paid)"}${debtPaid > 0 ? ` · cleared ${nairaFull(debtPaid)} old debt` : ""}.`
          : `Cash sale of ${nairaFull(total)} recorded.`,
        result?.receipt_id ? `/pos/receipt/${result.receipt_id}` : null,
      );
      setProduct(""); setQty("1"); setUnit(""); setAmount(""); setPaid(""); setCustomer(null); setCustQuery("");
    } catch (e) {
      if (isNetworkError(e)) {
        const qtyNum2 = Math.max(1, parseAmt(qty) || 1);
        const total2  = parseAmt(amount);
        const paidNum2 = customer ? Math.min(parseAmt(paid) || 0, total2) : total2;
        const debtPaid2 = customer ? Math.min(Math.max(0, (parseAmt(paid) || 0) - total2), debtDue) : 0;
        enqueue("pos/save", {
          owner_phone: ownerPhone, customer_id: customer?.id || null,
          customer_name: (customer && !customer.id) ? customer.name : null,
          customer_phone: (customer && !customer.id) ? (customer.phone?.trim() || null) : null,
          items: [{ name: product.trim(), qty: qtyNum2, unit: unit || null, unit_price: Math.round(total2 / qtyNum2) }],
          payment_amount: paidNum2,
          debt_payment: debtPaid2,
          branch_id: branchId || null,
        }, `Sale ${nairaFull(total2)}${customer ? ` — ${customer.name}` : " (cash)"}`);
        onSuccess(`No internet — sale saved offline. Will sync automatically when you reconnect.`);
        setProduct(""); setQty("1"); setUnit(""); setAmount(""); setPaid(""); setCustomer(null); setCustQuery("");
      } else {
        setError(e.message);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="qf-form">
      <div className="qf-row qf-row--lg-sm">
        <div className="form-group">
          <label className="form-label">Product / Service *</label>
          <input value={product} onChange={e => setProduct(e.target.value)} placeholder="Rice, Cement, Haircut…" required />
        </div>
        <div className="form-group">
          <label className="form-label">Qty</label>
          <MoneyInput value={qty} onChange={v => setQty(v)} placeholder="1" />
        </div>
      </div>
      <div className="qf-row qf-row--sm-lg">
        <div className="form-group">
          <label className="form-label">Unit</label>
          <input value={unit} onChange={e => setUnit(e.target.value)} placeholder="bags, pcs…" />
        </div>
        <div className="form-group">
          <label className="form-label">Amount (₦) *</label>
          <input inputMode="numeric" value={amount} onChange={e => setAmount(fmtAmt(e.target.value))} placeholder="0" required />
        </div>
      </div>
      <div className="form-group">
        <label className="form-label">{L.customer} <span className="text-subtle">— leave blank for cash sale</span></label>
        <CustomerSearch
          ownerPhone={ownerPhone}
          placeholder={`Search ${L.customerName.toLowerCase()}…`}
          allowNew
          onSelect={c => { setCustomer(c); setSettleDebt(true); }}
          value={customer}
          onQueryChange={setCustQuery}
        />
      </div>
      {customer && (
        <div className="form-group">
          <label className="form-label">Amount paid (₦) <span className="text-subtle">— leave blank for full credit</span></label>
          <MoneyInput value={paid} onChange={v => setPaid(v)} placeholder="0" />
        </div>
      )}
      {prevDebt > 0 && (
        <label className="form-group" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, cursor: "pointer", marginBottom: 8 }}>
          <span style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
            <input type="checkbox" checked={settleDebt} onChange={e => setSettleDebt(e.target.checked)} style={{ width: "auto" }} />
            Settle previous debt
          </span>
          <span style={{ fontWeight: 600, color: settleDebt ? "var(--rose)" : "var(--muted)" }}>+{nairaFull(prevDebt)}</span>
        </label>
      )}
      <BranchSelector ownerPhone={ownerPhone} value={branchId} onChange={setBranchId} />
      <div className="qf-type-hint">
        {customer
          ? (() => {
              const t = parseAmt(amount), p = Math.min(parseAmt(paid) || 0, t), b = t - p;
              const dPaid = Math.min(Math.max(0, (parseAmt(paid) || 0) - t), debtDue);
              const base = b > 0
                ? `${p > 0 ? "Part-paid" : "Credit"} sale → ${customer.name} will owe ${nairaFull(b)}`
                : `Paid in full → no new debt`;
              if (debtDue > 0) {
                return dPaid >= debtDue
                  ? `${base} · clears ${nairaFull(debtDue)} old debt (due ${nairaFull(t + debtDue)})`
                  : `${base} · amount due ${nairaFull(t + debtDue)} incl. ${nairaFull(debtDue)} old debt`;
              }
              return base;
            })()
          : "Cash sale → no customer debt"}
      </div>
      {error && <div className="modal-error">{error}</div>}
      <button type="submit" className="btn btn-primary qf-btn" disabled={loading}>
        {loading ? "Saving…" : "Record Sale"}
      </button>
    </form>
  );
}

function PaymentForm({ ownerPhone, onSuccess }) {
  const { user }                = useAuth();
  const L                       = getBizLabels(user?.menu_group);
  const [customer, setCustomer] = useState(null);
  const [amount, setAmount]     = useState("");
  const [note, setNote]         = useState("");
  const [branchId, setBranchId] = useState(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!customer || !amount) return;
    setLoading(true); setError(null);
    try {
      const result = await apiPost(`customers/${customer.id}/pay`, { amount: parseAmt(amount), note: note || null, branch_id: branchId || null });
      onSuccess(
        `Payment of ${nairaFull(parseAmt(amount))} from ${customer.name} recorded.`,
        result?.id ? `/pos/receipt/${result.id}` : null,
      );
      setCustomer(null); setAmount(""); setNote("");
    } catch (e) {
      if (isNetworkError(e)) {
        enqueue(
          `customers/${customer.id}/pay`,
          { amount: parseAmt(amount), note: note || null, branch_id: branchId || null },
          `Payment ${nairaFull(parseAmt(amount))} from ${customer.name}`,
        );
        onSuccess(`No internet — payment saved offline. Will sync automatically when you reconnect.`);
        setCustomer(null); setAmount(""); setNote("");
      } else {
        setError(e.message);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="qf-form">
      <div className="form-group">
        <label className="form-label">{L.customer} who paid *</label>
        <CustomerSearch ownerPhone={ownerPhone} placeholder={`Search ${L.customerName.toLowerCase()}…`} filterDebtors onSelect={setCustomer} value={customer} />
        <div className="form-hint">Shows {L.customers.toLowerCase()} with outstanding balance.</div>
      </div>
      <div className="qf-row qf-row--sm-xl">
        <div className="form-group">
          <label className="form-label">Amount paid (₦) *</label>
          <input
            inputMode="numeric"
            value={amount}
            onChange={e => setAmount(fmtAmt(e.target.value))}
            placeholder={customer?.balance > 0 ? fmtAmt(String(customer.balance)) : "0"}
            required
          />
        </div>
        <div className="form-group">
          <label className="form-label">Note <span className="text-subtle">(optional)</span></label>
          <input value={note} onChange={e => setNote(e.target.value)} placeholder="Bank transfer, cash…" />
        </div>
      </div>
      <BranchSelector ownerPhone={ownerPhone} value={branchId} onChange={setBranchId} />
      {error && <div className="modal-error">{error}</div>}
      <button type="submit" className="btn btn-primary qf-btn" disabled={loading || !customer}>
        {loading ? "Saving…" : "Record Payment"}
      </button>
    </form>
  );
}

function StockForm({ ownerPhone, onSuccess }) {
  const [item, setItem]         = useState(null);
  const [qty, setQty]           = useState("");
  const [cost, setCost]         = useState("");
  const [paidNow, setPaidNow]   = useState("");
  const [paidTouched, setPaidTouched] = useState(false);   // stop auto-fill once edited
  const [supplier, setSupplier] = useState("");
  const [supplierNames, setSupplierNames] = useState([]);   // existing suppliers, for autocomplete
  const [dueDate, setDueDate]   = useState("");
  const [note, setNote]         = useState("");
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    apiFetch("suppliers")
      .then(d => setSupplierNames((d.suppliers || []).map(s => s.name)))
      .catch(() => {});
  }, []);

  // Pre-fill "Amount paid now" with the running total so traders see the figure
  // and can reduce it for a part payment (defaults to paying in full). Stops
  // auto-filling the moment they type their own amount.
  const stockTotal = Math.round((parseAmt(qty) || 0) * (cost ? parseAmt(cost) : 0));
  useEffect(() => {
    if (!paidTouched) setPaidNow(stockTotal > 0 ? fmtAmt(String(stockTotal)) : "");
  }, [stockTotal, paidTouched]);

  function _body() {
    return {
      item_id:       item?.id || null,
      product:       item?.name || null,
      unit:          item?.unit || null,
      quantity:      parseAmt(qty),
      cost_per_unit: cost ? parseAmt(cost) : null,
      paid_now:      parseAmt(paidNow),   // pre-filled with the total; reduce for part payment
      supplier:      supplier.trim() || null,   // blank → "Others" server-side
      due_date:      dueDate || null,           // when the balance owed is due
      note:          note.trim() || null,
    };
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!item || !qty) return;
    setLoading(true); setError(null);
    const who = supplier.trim() ? ` from ${supplier.trim()}` : "";
    try {
      const r = await apiPost("inventory/stock-received", _body());
      onSuccess(`${qty} ${item.unit || "units"} of ${item.name} added to stock${who}.`);
      setItem(null); setQty(""); setCost(""); setPaidNow(""); setPaidTouched(false); setSupplier(""); setDueDate(""); setNote("");
      if (r?.purchase_id) { navigate(`/suppliers/receipt/purchase/${r.purchase_id}`); return; }
    } catch (e) {
      if (isNetworkError(e)) {
        enqueue("inventory/stock-received", _body(),
          `Stock +${qty} ${item.unit || "units"} of ${item.name}${who}`);
        onSuccess("No internet — stock entry saved offline. Will sync automatically when you reconnect.");
        setItem(null); setQty(""); setCost(""); setPaidNow(""); setPaidTouched(false); setSupplier(""); setDueDate(""); setNote("");
      } else {
        setError(e.message);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="qf-form">
      <div className="form-group">
        <label className="form-label">Product *</label>
        <InventorySearch ownerPhone={ownerPhone} onSelect={setItem} value={item} allowNew />
      </div>
      <div className="qf-row qf-row--sm-lg">
        <div className="form-group">
          <label className="form-label">Qty received *</label>
          <MoneyInput value={qty} onChange={v => setQty(v)} placeholder="10" required />
        </div>
        <div className="form-group">
          <label className="form-label">Cost per unit (₦)</label>
          <input inputMode="numeric" value={cost} onChange={e => setCost(fmtAmt(e.target.value))} placeholder="0" />
        </div>
      </div>
      <div className="qf-row qf-row--sm-lg">
        <div className="form-group">
          <label className="form-label">Supplier</label>
          <input value={supplier} onChange={e => setSupplier(e.target.value)} placeholder="Search or type a supplier…"
            list="stock-supplier-list" autoComplete="off" />
          <datalist id="stock-supplier-list">
            {supplierNames.map(n => (
              <option key={n} value={n.replace(/\b\w/g, c => c.toUpperCase())} />
            ))}
          </datalist>
        </div>
        <div className="form-group">
          <label className="form-label">Amount paid now (₦)</label>
          <input inputMode="numeric" value={paidNow}
            onChange={e => { setPaidNow(fmtAmt(e.target.value)); setPaidTouched(true); }} placeholder="0" />
          <span className="form-hint">Filled in as the full amount — reduce it if you only paid part now.</span>
        </div>
      </div>
      <div className="qf-row qf-row--sm-lg">
        <div className="form-group">
          <label className="form-label">Payment due <span className="text-subtle">(if owing)</span></label>
          <input type="date" value={dueDate} onChange={e => setDueDate(e.target.value)} />
        </div>
        <div className="form-group">
          <label className="form-label">Note <span className="text-subtle">(optional)</span></label>
          <input value={note} onChange={e => setNote(e.target.value)} placeholder="Delivery ref, batch…" />
        </div>
      </div>
      {error && <div className="modal-error">{error}</div>}
      <button type="submit" className="btn btn-primary qf-btn" disabled={loading || !item}>
        {loading ? "Saving…" : "Add to Stock"}
      </button>
    </form>
  );
}

// ── Quick Form panel ──────────────────────────────────────────────────────────

const FORM_TABS = [
  { key: "sale",    label: "Record Sale",    icon: ShoppingCart },
  { key: "payment", label: "Record Payment", icon: CreditCard   },
  { key: "stock",   label: "Stock Received", icon: Package      },
];

function QuickFormPanel({ ownerPhone }) {
  const [formTab, setFormTab] = useState("sale");
  const [success, setSuccess] = useState(null);  // { msg, link }

  function handleSuccess(msg, link = null) {
    setSuccess({ msg, link });
    setTimeout(() => setSuccess(null), 8000);
  }

  return (
    <div className="card" style={{ maxWidth: 560, overflow: "visible" }}>
      <div style={{ paddingBottom: 0 }}>
        <span className="card-title">Quick Record</span>
        <div className="card-subtitle" style={{ marginTop: 2 }}>Fill in the fields — no command syntax needed</div>
      </div>
      <div className="qf-sub-tabs">
        {FORM_TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            className={`qf-sub-tab${formTab === key ? " active" : ""}`}
            onClick={() => { setFormTab(key); setSuccess(null); }}
          >
            <span className="qf-tab-icon" style={{ display: "inline-flex" }}><Icon size={14} /></span>
            {label}
          </button>
        ))}
      </div>
      {success && (
        <div className="qf-success">
          <CheckCircle size={15} />
          <span>{success.msg}</span>
          {success.link && (
            <Link to={success.link} style={{ marginLeft: 8, fontWeight: 600, textDecoration: "underline" }}>
              View receipt →
            </Link>
          )}
        </div>
      )}
      <div style={{ padding: "4px 20px 20px" }}>
        {formTab === "sale"    && <SaleForm    ownerPhone={ownerPhone} onSuccess={handleSuccess} />}
        {formTab === "payment" && <PaymentForm ownerPhone={ownerPhone} onSuccess={handleSuccess} />}
        {formTab === "stock"   && <StockForm   ownerPhone={ownerPhone} onSuccess={handleSuccess} />}
      </div>
    </div>
  );
}

// ── Text / Voice panel (original Capture logic) ───────────────────────────────

function TextVoicePanel({ ownerPhone }) {
  const { user }  = useAuth();
  const L         = getBizLabels(user?.menu_group);
  // Prefer the user's business-type-specific prompts (from the server, mirroring
  // WhatsApp); fall back to the menu-group examples when none are provided.
  const exampleItems = (user?.examples?.length
    ? user.examples.map(t => ({ text: t, label: t.length > 26 ? t.slice(0, 24) + "…" : t }))
    : L.examples);
  const toast     = useToast();

  const [phone, setPhone]         = useState(ownerPhone || "");
  const [text, setText]           = useState("");
  const [preview, setPreview]     = useState(null);
  const [previewState, setPS]     = useState("empty");
  const [saving, setSaving]       = useState(false);
  const [saved, setSaved]         = useState(false);

  const [recording, setRecording] = useState(false);
  const [hasAudio, setHasAudio]   = useState(false);
  const [voiceStatus, setVS]      = useState("Ready to record");
  const recorderRef               = useRef(null);
  const chunksRef                 = useRef([]);
  const audioBlobRef              = useRef(null);
  const audioRef                  = useRef(null);

  useEffect(() => { if (ownerPhone) setPhone(ownerPhone); }, [ownerPhone]);

  async function handlePreview(e) {
    e.preventDefault();
    if (!phone || !text.trim()) return;
    setPS("loading"); setSaved(false); setPreview(null);
    try {
      const data = await apiPost("capture/preview", { phone, text: text.trim() });
      setPreview(data); setPS("ready");
    } catch (err) {
      setPS("error"); setPreview({ message: err.message });
    }
  }

  async function handleConfirm() {
    if (!preview?.pending) return;
    setSaving(true);
    try {
      const data = await apiPost("capture/confirm", { phone });
      setSaved(true); setPreview(data);
      toast(data.messages?.[0] || "Transaction saved.", "success");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setSaving(false);
    }
  }

  function handleClear() {
    setText(""); setPreview(null); setPS("empty"); setSaved(false);
    setHasAudio(false); setVS("Ready to record");
    audioBlobRef.current = null;
    if (audioRef.current) { audioRef.current.src = ""; audioRef.current.hidden = true; }
  }

  async function startRecording() {
    if (!navigator.mediaDevices) { toast("Microphone not available", "error"); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunksRef.current = [];
      const mimeType = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
      recorderRef.current = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorderRef.current.addEventListener("dataavailable", (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      });
      recorderRef.current.addEventListener("stop", () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: mimeType || "audio/webm" });
        audioBlobRef.current = blob;
        if (audioRef.current) {
          audioRef.current.src = URL.createObjectURL(blob);
          audioRef.current.hidden = false;
        }
        setHasAudio(true); setVS("Recording ready — transcribe to fill text"); setRecording(false);
      });
      recorderRef.current.start();
      setRecording(true); setVS("Recording…");
    } catch { toast("Microphone permission denied", "error"); }
  }

  function stopRecording() {
    if (recorderRef.current?.state !== "inactive") recorderRef.current.stop();
  }

  async function handleTranscribe() {
    if (!audioBlobRef.current) return;
    setVS("Transcribing…");
    try {
      const b64  = await blobToBase64(audioBlobRef.current);
      const data = await apiPost("capture/voice", {
        phone, audio_base64: b64, mime_type: audioBlobRef.current.type || "audio/webm",
      });
      if (data.transcript) setText(data.transcript);
      setPreview(data); setPS("ready"); setVS("Transcription done");
    } catch (err) {
      const isUpgrade = /go plan/i.test(err.message || "");
      toast(err.message, isUpgrade ? "info" : "error", isUpgrade ? { persist: true } : undefined);
      setVS(isUpgrade ? "" : "Transcription failed");
    }
  }

  const pending = preview?.pending;

  const SUMMARY_FIELDS = [
    ["Action",      pending?.action],
    [L.customer,    pending?.customer_name || L.directSale],
    ["Product",     pending?.product],
    ["Quantity",    pending?.quantity ? qty(pending.quantity, pending.unit) : null],
    ["Sale amount", pending?.buy_amount  ? nairaFull(pending.buy_amount)  : null],
    ["Payment",     pending?.paid_amount ? nairaFull(pending.paid_amount) : null],
    ["Due date",    pending?.due_date    ? new Date(pending.due_date).toLocaleDateString("en-NG") : null],
  ].filter(([, v]) => v);

  return (
    <div className="capture-grid">
      <div className="card">
        <div className="card-header">
          <span className="card-title">Record transaction</span>
          <span className="card-subtitle">Same style as WhatsApp</span>
        </div>
        <form onSubmit={handlePreview} style={{ display: "grid", gap: 16, padding: 18 }}>
          <div className="form-group">
            <label className="form-label">Registered phone</label>
            <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="234..." className="form-full" />
          </div>
          <div className="voice-box">
            <div>
              <div className="voice-label">Voice capture</div>
              <div className="voice-status">{voiceStatus}</div>
            </div>
            <audio ref={audioRef} controls hidden style={{ width: "100%", height: 36 }} />
            <div className="gap-2">
              <button type="button" className="btn btn-secondary btn-sm"
                onClick={recording ? stopRecording : startRecording}
              >
                {recording ? <><MicOff size={14} /> Stop</> : <><Mic size={14} /> Record</>}
              </button>
              <button type="button" className="btn btn-secondary btn-sm"
                disabled={!hasAudio || recording}
                onClick={handleTranscribe}
              >
                <Play size={14} /> Transcribe
              </button>
            </div>
          </div>
          <div className="form-group">
            <label className="form-label">Transaction text</label>
            <textarea rows={5} className="form-full" placeholder={exampleItems[0]?.text || ""}
              value={text} onChange={(e) => setText(e.target.value)} />
          </div>
          <div className="example-chips">
            {exampleItems.map((ex, i) => (
              <button key={(ex.label || ex.text) + i} type="button" className="example-chip" onClick={() => setText(ex.text)}>
                {ex.label}
              </button>
            ))}
          </div>
          <div className="gap-2">
            <button type="submit" className="btn btn-primary" disabled={previewState === "loading"}>
              <Send size={14} />
              {previewState === "loading" ? "Reading…" : "Preview"}
            </button>
            <button type="button" className="btn btn-ghost" onClick={handleClear}>
              <X size={14} /> Clear
            </button>
          </div>
        </form>
      </div>
      <div className="card">
        <div className="card-header">
          <span className="card-title">Preview</span>
          <span className="card-subtitle">Confirm before saving</span>
        </div>
        <div style={{ padding: 18 }}>
          {previewState === "empty" && (
            <div className="capture-result empty">Enter a transaction and click Preview.</div>
          )}
          {previewState === "loading" && (
            <div className="capture-result empty">Reading transaction…</div>
          )}
          {previewState === "error" && (
            <div className="capture-result">
              <div style={{ color: "var(--rose)", fontSize: 13.5 }}>{preview?.message}</div>
            </div>
          )}
          {previewState === "ready" && preview && (
            <div className="capture-result">
              {preview.transcript && (
                <div style={{ background: "#f0f7f3", borderLeft: "3px solid var(--brand)", borderRadius: "0 6px 6px 0", padding: "10px 14px" }}>
                  <div className="form-label" style={{ marginBottom: 4 }}>Transcript</div>
                  <div style={{ fontSize: 13.5 }}>{preview.transcript}</div>
                </div>
              )}
              {preview.messages?.map((m, i) => (
                <div key={i} className="message-bubble">{m}</div>
              ))}
              {pending && !saved && (
                <>
                  <div className="form-label">Parsed details</div>
                  <div className="parsed-preview">
                    {SUMMARY_FIELDS.map(([label, value]) => (
                      <div key={label} className="parsed-cell">
                        <span>{label}</span>
                        <strong>{value}</strong>
                      </div>
                    ))}
                  </div>
                  <button className="btn btn-primary" disabled={saving} onClick={handleConfirm}>
                    <CheckCircle size={15} />
                    {saving ? "Saving…" : "Confirm & save"}
                  </button>
                </>
              )}
              {saved && (
                <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--brand)", fontWeight: 600 }}>
                  <CheckCircle size={18} /> Transaction saved. Check Dashboard for updated totals.
                </div>
              )}
              {preview.message && !pending && (
                <div style={{ color: "var(--muted)", fontSize: 13.5 }}>{preview.message}</div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Root Capture page ─────────────────────────────────────────────────────────

export default function Capture() {
  const { ownerPhone } = useApp();
  const [mode, setMode] = useState("form");

  return (
    <>
      <div className="capture-mode-bar">
        <button
          className={`capture-mode-btn${mode === "form" ? " active" : ""}`}
          onClick={() => setMode("form")}
        >
          Quick Form
        </button>
        <button
          className={`capture-mode-btn${mode === "text" ? " active" : ""}`}
          onClick={() => setMode("text")}
        >
          Text / Voice
        </button>
      </div>

      {mode === "form" && <QuickFormPanel ownerPhone={ownerPhone} />}
      {mode === "text" && <TextVoicePanel ownerPhone={ownerPhone} />}
    </>
  );
}
