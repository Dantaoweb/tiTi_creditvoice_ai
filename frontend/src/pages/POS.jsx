import { useState, useEffect, useRef } from "react";
import { useNavigate, Link } from "react-router-dom";
import { Search, Plus, Minus, Trash2, ShoppingCart, User, X } from "lucide-react";
import { useApp } from "../context/AppContext";
import { useAuth } from "../context/AuthContext";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull, nairaInWords, qty } from "../lib/format";
import { enqueue, isNetworkError } from "../lib/offlineQueue";
import { usePlan } from "../lib/usePlan";

// ── Product picker (paged list, qty stepper beside each row) ────────────────

const PAGE_SIZE = 20;   // products shown at once; slide/arrow to reveal more

function ProductGrid({ ownerPhone, branchId, qtyFor, onSetQty }) {
  const [products, setProducts] = useState([]);
  const [usage, setUsage] = useState(null);   // { count, limit, remaining }
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const touchX = useRef(null);

  useEffect(() => {
    if (!ownerPhone) return;
    setLoading(true);
    apiFetch("pos/products", { owner_phone: ownerPhone, ...(branchId ? { branch_id: branchId } : {}) })
      .then(d => { setProducts(d.products || []); setUsage(d.monthly_transactions || null); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [ownerPhone, branchId]);

  // Basic monthly-transaction cap warning (only when a limit applies and it's close).
  const capBanner = (usage && usage.limit != null && usage.remaining != null && usage.remaining <= 10) ? (
    <div className="pos-cap-banner" style={{
      margin: "0 0 10px", padding: "8px 12px", borderRadius: 8, fontSize: 12.5, fontWeight: 600,
      background: usage.remaining === 0 ? "#fee2e2" : "#fef3c7",
      border: `1px solid ${usage.remaining === 0 ? "#fca5a5" : "#fcd34d"}`,
      color: usage.remaining === 0 ? "#991b1b" : "#92400e",
    }}>
      {usage.remaining === 0
        ? `You've reached the Basic limit of ${usage.limit} sales this month. Upgrade to Go for unlimited.`
        : `${usage.remaining} of ${usage.limit} monthly sales left on Basic. Upgrade to Go for unlimited.`}
      {" "}<Link to="/upgrade" style={{ color: "inherit", textDecoration: "underline" }}>Upgrade</Link>
    </div>
  ) : null;

  const filtered = q.trim()
    ? products.filter(p => p.name.toLowerCase().includes(q.toLowerCase()))
    : products;

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pages - 1);
  const pageItems = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);

  // Reset to first page whenever the search changes.
  useEffect(() => { setPage(0); }, [q]);

  const go = (d) => setPage(p => Math.min(pages - 1, Math.max(0, p + d)));

  // Swipe left/right on the list to move between pages of 20.
  function onTouchStart(e) { touchX.current = e.touches[0].clientX; }
  function onTouchEnd(e) {
    if (touchX.current == null) return;
    const dx = e.changedTouches[0].clientX - touchX.current;
    if (Math.abs(dx) > 50) go(dx < 0 ? 1 : -1);
    touchX.current = null;
  }

  return (
    <div className="pos-products-panel">
      {capBanner}
      <div className="pos-pgrid-search">
        <Search size={15} className="pos-search-icon" />
        <input
          className="pos-search-input"
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="Search product…"
        />
        {q && (
          <button className="pos-search-clear" onClick={() => setQ("")}>
            <X size={13} />
          </button>
        )}
      </div>

      <div className="pos-grid-scroll" onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}>
        {loading ? (
          <div className="pos-grid-msg">Loading products…</div>
        ) : filtered.length === 0 ? (
          <div className="pos-grid-msg">
            {q ? "No products match your search." : "Add products in Inventory to see them here."}
          </div>
        ) : (
          <div className="pos-pick-list">
            {pageItems.map(p => {
              const oos = !p.is_service && p.quantity <= 0;
              const n = qtyFor(p);
              const stockLabel = p.is_service
                ? "Service"
                : oos ? "Out of stock"
                : p.unit ? qty(p.quantity, p.unit) : `${qty(p.quantity)} in stock`;
              return (
                <div key={p.id} className={`pos-pick-row${n > 0 ? " pos-pick-row--active" : ""}`}
                  style={n > 0
                    ? { borderColor: "#2563eb", background: "rgba(37,99,235,0.10)", boxShadow: "inset 0 0 0 1px #2563eb" }
                    : undefined}>
                  {/* Tapping anywhere on the placard adds one — not just the +/− */}
                  <div className="pos-pick-info"
                    onClick={() => !oos && onSetQty(p, n + 1)}
                    style={{ cursor: oos ? "default" : "pointer", flex: 1 }}>
                    <span className="pos-pick-name" style={n > 0 ? { color: "#2563eb" } : undefined}>{p.name}</span>
                    <span className="pos-pick-meta">
                      {nairaFull(p.selling_price)}<span className="pos-pick-dot">·</span>
                      <span className={oos ? "pos-pick-oos" : ""}>{stockLabel}</span>
                    </span>
                  </div>
                  {/* Qty stepper sits BESIDE the product, always reachable */}
                  <div className="pos-qty pos-pick-qty">
                    <button onClick={() => onSetQty(p, n - 1)} disabled={n <= 0} aria-label="decrease">
                      <Minus size={13} />
                    </button>
                    <input
                      type="number" min={0} inputMode="numeric"
                      value={n}
                      onChange={e => onSetQty(p, Math.max(0, parseInt(e.target.value) || 0))}
                    />
                    <button onClick={() => onSetQty(p, n + 1)} disabled={oos} aria-label="increase">
                      <Plus size={13} />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {pages > 1 && (
        <div className="pos-pager">
          <button onClick={() => go(-1)} disabled={safePage === 0} aria-label="previous">‹</button>
          <span>{safePage + 1} / {pages} · 20 per page</span>
          <button onClick={() => go(1)} disabled={safePage >= pages - 1} aria-label="next">›</button>
        </div>
      )}
    </div>
  );
}

// ── Customer search ─────────────────────────────────────────────────────────

function CustomerSearch({ ownerPhone, customer, onSelect, onClear, onQueryChange }) {
  const [q, _setQ] = useState("");
  const setQ = (v) => { _setQ(v); onQueryChange && onQueryChange(v); };
  const [results, setResults] = useState([]);
  const timeout = useRef(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    clearTimeout(timeout.current);
    if (!q.trim()) { setResults([]); return; }
    timeout.current = setTimeout(async () => {
      try {
        const data = await apiFetch("customers", { owner_phone: ownerPhone });
        const lower = q.toLowerCase();
        setResults((data.customers || []).filter(c =>
          c.name.toLowerCase().includes(lower) ||
          (c.phone || "").includes(lower)
        ).slice(0, 8));
      } catch { setResults([]); }
    }, 250);
  }, [q, ownerPhone]);

  if (customer) {
    return (
      <>
        <div className="pos-customer-pill">
          <User size={13} />
          <span>{customer.name}{customer.isNew ? " · new" : ""}</span>
          {customer.balance > 0 && (
            <span className="pos-customer-debt">owes {nairaFull(customer.balance)}</span>
          )}
          <button onClick={onClear}><X size={13} /></button>
        </div>
        {customer.isNew && (
          <div className="pos-search-row" style={{ marginTop: 6 }}>
            <User size={15} className="pos-search-icon" />
            <input
              className="pos-search-input"
              value={customer.phone || ""}
              onChange={e => onSelect({ ...customer, phone: e.target.value })}
              placeholder="Phone (optional)…"
              inputMode="tel"
            />
          </div>
        )}
      </>
    );
  }

  return (
    <div className="pos-search-wrap">
      <div className="pos-search-row">
        <User size={15} className="pos-search-icon" />
        <input
          className="pos-search-input"
          value={q}
          onChange={e => { setQ(e.target.value); setOpen(true); }}
          placeholder="Search customer (optional)…"
        />
      </div>
      {open && q.trim() && (
        <div className="pos-search-results">
          {results.map(c => (
            <button key={c.id} className="pos-product-row"
              onClick={() => { onSelect(c); setQ(""); setOpen(false); }}>
              <span className="pos-product-name">{c.name}</span>
              <span className="pos-product-meta">
                {c.phone || "no phone"}
                {c.balance > 0 && <span className="pos-stock">owes {nairaFull(c.balance)}</span>}
              </span>
            </button>
          ))}
          {!results.some(c => c.name.toLowerCase() === q.trim().toLowerCase()) && (
            <button
              className="pos-product-row"
              onClick={() => {
                onSelect({ id: null, name: q.trim(), phone: null, isNew: true });
                setQ(""); setOpen(false);
              }}>
              <span className="pos-product-name">➕ Add "{q.trim()}" as new customer</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function fmtAmt(s) {
  const raw = String(s || "").replace(/[^0-9]/g, "");
  return raw ? Number(raw).toLocaleString("en-US") : "";
}
function parseAmt(s) { return Number(String(s || "").replace(/,/g, "")); }

// ── Main POS page ───────────────────────────────────────────────────────────

export default function POS() {
  const { ownerPhone } = useApp();
  const { user } = useAuth();
  const { plan, limit: planLimit } = usePlan();
  // Delivery/ready-by date: shown by default for service businesses, available to all
  const serviceDefault = !!user?.menu_group && user.menu_group !== "stock";
  const inventoryLim = planLimit("active_inventory_items");
  const navigate = useNavigate();

  const [cart, setCart] = useState([]);
  const [customer, setCustomer] = useState(null);
  const [custQuery, setCustQuery] = useState("");   // typed-but-unselected search text
  const [payment, setPayment] = useState("");
  const [settleDebt, setSettleDebt] = useState(true);   // fold prior debt into checkout
  const [dueDate, setDueDate] = useState("");
  const [serviceDate, setServiceDate] = useState("");
  const [showDelivery, setShowDelivery] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState("");
  const creditRef = useRef(null);
  const creditVisible = useRef(false);

  // Branch the sale is made from. Only owners choose it; branch staff are locked
  // to their own branch by the backend, so we never show them a switcher.
  const isOwner = !user?.parent_id;
  const [branches, setBranches] = useState([]);
  const [branchId, setBranchId] = useState(null);

  useEffect(() => {
    if (!isOwner) return;
    apiFetch("branches")
      .then(d => {
        const list = d.branches || [];
        setBranches(list);
        if (list.length) {
          const def = list.find(b => b.is_default) || list[0];
          setBranchId(def.id);
        }
      })
      .catch(() => {});
  }, [isOwner]);

  const total    = cart.reduce((s, it) => s + it.qty * it.unit_price, 0);
  const prevDebt = (customer && customer.balance > 0) ? customer.balance : 0;
  const debtDue  = settleDebt ? prevDebt : 0;      // debt folded into this checkout
  const amountDue = total + debtDue;
  const payNum   = parseAmt(payment);
  const paid     = Math.min(payNum, total);                             // sale portion
  const debtPaid = Math.min(Math.max(0, payNum - total), debtDue);      // toward prior debt
  const change   = Math.max(0, payNum - amountDue);
  const owed     = customer ? total - paid : 0;                         // new credit on this sale
  const showCredit = customer && owed > 0;

  // Scroll the credit section into view the first time it appears
  useEffect(() => {
    if (showCredit && !creditVisible.current) {
      creditVisible.current = true;
      setTimeout(() => creditRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 80);
    }
    if (!showCredit) creditVisible.current = false;
  }, [showCredit]);

  // Current cart qty for a picker product (matched by inventory item id).
  function qtyFor(p) {
    const it = cart.find(c => c.inventory_item_id === p.id);
    return it ? it.qty : 0;
  }

  // Effective unit price for a line at a given qty. Auto-applies the wholesale
  // (bulk) price when qty reaches the threshold, unless the cashier has hand-
  // edited the price or is selling a retail sub-unit — never forced.
  function effUnitPrice(line, q) {
    if (line.priceEdited || line.sold_unit) return line.unit_price;
    if (line.wholesale_price && line.wholesale_min_qty && q >= line.wholesale_min_qty) {
      return line.wholesale_price;
    }
    return line.base_price ?? line.unit_price;
  }

  // Set the qty straight from the picker's stepper: add / update / remove.
  function setProductQty(p, newQty) {
    setCart(prev => {
      const idx = prev.findIndex(it => it.inventory_item_id === p.id && it.name === p.name);
      if (newQty <= 0) return idx >= 0 ? prev.filter((_, i) => i !== idx) : prev;
      if (idx >= 0) {
        const u = [...prev];
        const line = { ...u[idx], qty: newQty };
        line.unit_price = effUnitPrice(line, newQty);
        u[idx] = line;
        return u;
      }
      const line = {
        inventory_item_id: p.id,
        name: p.name,
        unit: p.unit,
        base_price: p.selling_price,             // retail (single-unit) price
        wholesale_price: p.wholesale_price || null,
        wholesale_min_qty: p.wholesale_min_qty || null,
        priceEdited: false,
        unit_price: p.selling_price,
        qty: newQty,
        stock: p.quantity,
        is_service: p.is_service,
        retail_unit: p.retail_unit || null,
        retail_per_base: p.retail_per_base || null,
        retail_price: p.retail_price || null,
        sold_unit: null,
        fraction: 1.0,
      };
      line.unit_price = effUnitPrice(line, newQty);
      return [...prev, line];
    });
  }

  function addCustomItem() {
    setCart(prev => [...prev, {
      inventory_item_id: null,
      name: "",
      unit: "",
      unit_price: 0,
      qty: 1,
    }]);
  }

  function updateItem(idx, field, value) {
    setCart(prev => {
      const updated = [...prev];
      const line = { ...updated[idx], [field]: value };
      // A hand-typed price wins from then on; a qty change re-checks the
      // wholesale threshold.
      if (field === "unit_price") line.priceEdited = true;
      else if (field === "qty") line.unit_price = effUnitPrice(line, value);
      updated[idx] = line;
      return updated;
    });
  }

  function removeItem(idx) {
    setCart(prev => prev.filter((_, i) => i !== idx));
  }

  async function handleSave() {
    if (cart.length === 0)               { setSaveErr("Add at least one item to the order."); return; }
    if (cart.some(it => !it.name.trim())) { setSaveErr("All items need a name."); return; }
    if (cart.some(it => it.unit_price <= 0)) { setSaveErr("All items need a price greater than zero."); return; }
    // Typed a name but never tapped a result — without this the sale silently
    // saves as cash and any part payment / balance is not tracked.
    if (!customer && custQuery.trim()) {
      setSaveErr(
        `"${custQuery.trim()}" is not attached — tap them in the list, or tap ` +
        `"Add as new customer". To record a cash sale instead, clear the customer box.`
      );
      return;
    }
    setSaveErr("");
    setSaving(true);
    const payload = {
      owner_phone:    ownerPhone,
      customer_id:    customer?.id || null,
      customer_name:  (customer && !customer.id) ? customer.name : null,
      customer_phone: (customer && !customer.id) ? (customer.phone?.trim() || null) : null,
      items: cart.map(it => ({
        inventory_item_id: it.inventory_item_id || null,
        name:       it.name,
        qty:        it.qty,
        unit:       it.unit || null,
        unit_price: it.unit_price,
        sold_unit:  it.sold_unit || null,
        fraction:   it.fraction || 1.0,
      })),
      payment_amount: paid,
      debt_payment: debtPaid,
      branch_id: branchId,
      due_date: (customer && owed > 0 && dueDate) ? dueDate : null,
      service_date: serviceDate || null,
    };
    try {
      const result = await apiPost("pos/save", payload);
      navigate(`/pos/receipt/${result.receipt_id}`);
    } catch (e) {
      if (isNetworkError(e)) {
        const label = `POS sale — ${cart.length} item(s), ${nairaFull(paid)}`;
        enqueue("pos/save", payload, label);
        setCart([]); setCustomer(null); setPayment(""); setDueDate(""); setServiceDate(""); setSaveErr("");
        setSaving(false);
        navigate("/capture", {
          state: { offlineMsg: "No internet — POS sale saved offline. It will sync when you reconnect." },
        });
        return;
      }
      setSaveErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="pos-shell">

      {/* ── Left: Product picker ─────────────────────────────────────── */}
      <div className="pos-products-col">
        {inventoryLim !== null && (
          <div className="pos-plan-hint">
            Basic plan: up to {inventoryLim} active products ·{" "}
            <span onClick={() => window.location.href = "/app/upgrade"}>Upgrade to Go →</span>
          </div>
        )}
        {isOwner && branches.length > 1 && (
          <div className="pos-branch-bar">
            <span className="pos-branch-label">Selling from:</span>
            <select
              className="pos-branch-select"
              value={branchId ?? ""}
              onChange={e => setBranchId(Number(e.target.value))}
            >
              {branches.map(b => (
                <option key={b.id} value={b.id}>{b.name}{b.is_default ? " (default)" : ""}</option>
              ))}
            </select>
          </div>
        )}
        <ProductGrid ownerPhone={ownerPhone} branchId={branchId} qtyFor={qtyFor} onSetQty={setProductQty} />
      </div>

      {/* ── Right: Order (cart + payment) ───────────────────────────── */}
      <div className="pos-order-col">

        {/* Cart items */}
        <div className="pos-cart-box">
          <div className="pos-cart-header">
            <ShoppingCart size={16} />
            <span>Order</span>
            <span className="pos-cart-count">{cart.length} item{cart.length !== 1 ? "s" : ""}</span>
          </div>

          {cart.length === 0 ? (
            <div className="pos-empty">Tap a product on the left to add it here.</div>
          ) : (
            <div className="pos-items">
              {cart.map((it, idx) => (
                <div key={idx} className="pos-item">
                  <div className="pos-item-row">
                    <input
                      className="pos-item-name"
                      value={it.name}
                      onChange={e => updateItem(idx, "name", e.target.value)}
                      placeholder="Item name"
                    />
                    <button className="pos-remove" onClick={() => removeItem(idx)}>
                      <Trash2 size={13} />
                    </button>
                  </div>

                  {/* Retail unit toggle */}
                  {it.retail_unit && (
                    <div className="pos-unit-toggle">
                      <button
                        className={`pos-unit-btn${!it.sold_unit ? " pos-unit-btn--active" : ""}`}
                        onClick={() => {
                          updateItem(idx, "sold_unit", null);
                          updateItem(idx, "fraction", 1.0);
                          updateItem(idx, "unit_price", it._base_price || it.unit_price);
                        }}
                      >
                        Per {it.unit || "unit"}
                      </button>
                      <button
                        className={`pos-unit-btn${it.sold_unit === it.retail_unit ? " pos-unit-btn--active" : ""}`}
                        onClick={() => {
                          updateItem(idx, "_base_price", it.unit_price);
                          updateItem(idx, "sold_unit", it.retail_unit);
                          updateItem(idx, "fraction", 1.0);
                          if (it.retail_price) updateItem(idx, "unit_price", it.retail_price);
                        }}
                      >
                        Per {it.retail_unit}
                        {it.retail_price ? ` (${nairaFull(it.retail_price)})` : ""}
                      </button>
                    </div>
                  )}

                  <div className="pos-item-controls">
                    <div className="pos-qty">
                      <button onClick={() => updateItem(idx, "qty", Math.max(1, it.qty - 1))}>
                        <Minus size={12} />
                      </button>
                      <input
                        type="number" min={1}
                        value={it.qty}
                        onChange={e => updateItem(idx, "qty", Math.max(1, parseInt(e.target.value) || 1))}
                      />
                      <button onClick={() => updateItem(idx, "qty", it.qty + 1)}>
                        <Plus size={12} />
                      </button>
                    </div>
                    <span className="pos-x">×</span>
                    <div className="pos-price-wrap">
                      <span className="pos-currency">₦</span>
                      <input
                        type="text"
                        inputMode="numeric"
                        value={fmtAmt(String(it.unit_price || ""))}
                        onChange={e => updateItem(idx, "unit_price", parseAmt(e.target.value))}
                        placeholder="0"
                      />
                    </div>
                    <span className="pos-line-total">{nairaFull(it.qty * it.unit_price)}</span>
                  </div>
                  {(!it.priceEdited && !it.sold_unit && it.wholesale_price && it.wholesale_min_qty && it.qty >= it.wholesale_min_qty) && (
                    <div style={{ fontSize: 11, color: "var(--brand)", fontWeight: 600, marginTop: 2 }}>
                      🏷 wholesale price (from {it.wholesale_min_qty})
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          <button className="pos-add-custom" onClick={addCustomItem}>
            <Plus size={13} /> Add custom item
          </button>
        </div>

        {/* Payment summary */}
        <div className="pos-summary">

          <div className="pos-summary-section">
            <div className="pos-summary-label">Customer</div>
            <CustomerSearch
              ownerPhone={ownerPhone}
              customer={customer}
              onSelect={c => { setCustomer(c); setSettleDebt(true); }}
              onClear={() => setCustomer(null)}
              onQueryChange={setCustQuery}
            />
            {!customer && (
              <span className="form-hint">Leave blank for walk-in / cash sale</span>
            )}
          </div>

          <div className="pos-summary-section">
            <div className="pos-total-row">
              <span>Total</span>
              <span>{nairaFull(total)}</span>
            </div>
            {total > 0 && (
              <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4, fontStyle: "italic" }}>
                {nairaInWords(total)}
              </div>
            )}
            {prevDebt > 0 && (
              <>
                <label style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginTop: 10, fontSize: 13, cursor: "pointer" }}>
                  <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <input type="checkbox" checked={settleDebt}
                      onChange={e => setSettleDebt(e.target.checked)} style={{ width: "auto" }} />
                    Settle previous debt
                  </span>
                  <span style={{ fontWeight: 600, color: settleDebt ? "var(--rose)" : "var(--muted)" }}>
                    +{nairaFull(prevDebt)}
                  </span>
                </label>
                {settleDebt && (
                  <div className="pos-total-row" style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid var(--line)" }}>
                    <span>Amount due</span>
                    <span>{nairaFull(amountDue)}</span>
                  </div>
                )}
              </>
            )}
          </div>

          <div className="pos-summary-section">
            <label className="pos-summary-label">Payment Received</label>
            <div className="pos-price-wrap" style={{ marginTop: 6 }}>
              <span className="pos-currency">₦</span>
              <input
                type="text"
                inputMode="numeric"
                value={payment}
                onChange={e => setPayment(fmtAmt(e.target.value))}
                placeholder="0"
                style={{ flex: 1, fontSize: "1.1rem", fontWeight: 600 }}
              />
            </div>
            {change > 0 && (
              <div className="pos-change">Change: {nairaFull(change)}</div>
            )}
            {/* Warning: partial payment with no customer — debt won't be tracked */}
            {!customer && total > 0 && parseAmt(payment) > 0 && parseAmt(payment) < total && (
              <div className="pos-credit-warn">
                ⚠ Select a customer above to record the {nairaFull(total - parseAmt(payment))} balance as credit debt
              </div>
            )}
          </div>

          {/* Credit section — prominent card, auto-scrolls into view */}
          {showCredit && (
            <div className="pos-credit-card" ref={creditRef}>
              <div className="pos-credit-card-header">
                <span className="pos-credit-label">Credit balance</span>
                <span className="pos-credit-amount">{nairaFull(owed)}</span>
              </div>
              <div className="pos-credit-card-body">
                <label className="pos-summary-label">
                  Payment due date <span style={{ opacity: 0.55, fontWeight: 400 }}>(optional)</span>
                </label>
                <input
                  type="date"
                  value={dueDate}
                  onChange={e => setDueDate(e.target.value)}
                  style={{ width: "100%", marginTop: 6 }}
                  min={new Date().toISOString().slice(0, 10)}
                />
                {!dueDate && (
                  <span className="form-hint">Set a due date to enable WhatsApp reminders</span>
                )}
              </div>
            </div>
          )}

          {/* Delivery / ready-by date — shown by default for service businesses */}
          {(serviceDefault || showDelivery) ? (
            <div className="pos-summary-section">
              <label className="pos-summary-label">
                Deliver / ready by <span style={{ opacity: 0.55, fontWeight: 400 }}>(optional)</span>
              </label>
              <input
                type="date"
                value={serviceDate}
                onChange={e => setServiceDate(e.target.value)}
                min={new Date().toISOString().slice(0, 10)}
                style={{ width: "100%", marginTop: 6 }}
              />
              <span className="form-hint">When the job/order will be ready — you'll be reminded before the date.</span>
            </div>
          ) : (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setShowDelivery(true)}
              style={{ margin: "0 16px 4px", alignSelf: "flex-start" }}
            >
              + Add delivery / ready date
            </button>
          )}

          {saveErr && <div className="pos-error">{saveErr}</div>}

          <button
            className="btn btn-primary"
            style={{ width: "calc(100% - 32px)", margin: "0 16px 16px", justifyContent: "center" }}
            onClick={handleSave}
            disabled={saving || cart.length === 0}
          >
            {saving ? "Saving…" : `Save Sale · ${nairaFull(amountDue)}`}
          </button>
        </div>
      </div>
    </div>
  );
}
