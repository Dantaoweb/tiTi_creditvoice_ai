import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Search, Plus, Minus, Trash2, ShoppingCart, User, X } from "lucide-react";
import { useApp } from "../context/AppContext";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull, nairaInWords } from "../lib/format";
import { enqueue, isNetworkError } from "../lib/offlineQueue";
import { usePlan } from "../lib/usePlan";

// ── Product grid (browse + search) ─────────────────────────────────────────

function ProductGrid({ ownerPhone, onAdd }) {
  const [products, setProducts] = useState([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!ownerPhone) return;
    apiFetch("pos/products", { owner_phone: ownerPhone })
      .then(d => setProducts(d.products || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [ownerPhone]);

  const filtered = q.trim()
    ? products.filter(p => p.name.toLowerCase().includes(q.toLowerCase()))
    : products;

  function pick(p) {
    onAdd({
      inventory_item_id: p.id,
      name: p.name,
      unit: p.unit,
      unit_price: p.selling_price,
      qty: 1,
      stock: p.quantity,
      is_service: p.is_service,
      retail_unit: p.retail_unit || null,
      retail_per_base: p.retail_per_base || null,
      retail_price: p.retail_price || null,
      sold_unit: null,
      fraction: 1.0,
    });
  }

  return (
    <div className="pos-products-panel">
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

      <div className="pos-grid-scroll">
        {loading ? (
          <div className="pos-grid-msg">Loading products…</div>
        ) : filtered.length === 0 ? (
          <div className="pos-grid-msg">
            {q ? "No products match your search." : "Add products in Inventory to see them here."}
          </div>
        ) : (
          <div className="pos-product-grid">
            {filtered.map(p => {
              const oos = !p.is_service && p.quantity <= 0;
              return (
                <button
                  key={p.id}
                  className={`pos-pgrid-card${oos ? " pos-pgrid-card--oos" : ""}`}
                  onClick={() => pick(p)}
                  title={oos ? `${p.name} — out of stock` : p.name}
                >
                  <span className="pos-pgrid-name">{p.name}</span>
                  <span className="pos-pgrid-price">{nairaFull(p.selling_price)}</span>
                  <span className="pos-pgrid-stock">
                    {p.is_service
                      ? "Service"
                      : oos
                        ? "Out of stock"
                        : p.unit
                          ? `${p.quantity} ${p.unit}`
                          : `${p.quantity} in stock`}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Customer search ─────────────────────────────────────────────────────────

function CustomerSearch({ ownerPhone, customer, onSelect, onClear }) {
  const [q, setQ] = useState("");
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
      <div className="pos-customer-pill">
        <User size={13} />
        <span>{customer.name}</span>
        {customer.balance > 0 && (
          <span className="pos-customer-debt">owes {nairaFull(customer.balance)}</span>
        )}
        <button onClick={onClear}><X size={13} /></button>
      </div>
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
      {open && results.length > 0 && (
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
  const { plan, limit: planLimit } = usePlan();
  const inventoryLim = planLimit("active_inventory_items");
  const navigate = useNavigate();

  const [cart, setCart] = useState([]);
  const [customer, setCustomer] = useState(null);
  const [payment, setPayment] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState("");
  const creditRef = useRef(null);
  const creditVisible = useRef(false);

  const total  = cart.reduce((s, it) => s + it.qty * it.unit_price, 0);
  const paid   = Math.min(parseAmt(payment), total);
  const change = Math.max(0, parseAmt(payment) - total);
  const owed   = customer ? total - paid : 0;
  const showCredit = customer && owed > 0;

  // Scroll the credit section into view the first time it appears
  useEffect(() => {
    if (showCredit && !creditVisible.current) {
      creditVisible.current = true;
      setTimeout(() => creditRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 80);
    }
    if (!showCredit) creditVisible.current = false;
  }, [showCredit]);

  function addToCart(product) {
    setCart(prev => {
      const idx = prev.findIndex(it =>
        it.inventory_item_id === product.inventory_item_id && it.name === product.name
      );
      if (idx >= 0) {
        const updated = [...prev];
        updated[idx] = { ...updated[idx], qty: updated[idx].qty + 1 };
        return updated;
      }
      return [...prev, { ...product }];
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
      updated[idx] = { ...updated[idx], [field]: value };
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
    setSaveErr("");
    setSaving(true);
    const payload = {
      owner_phone:    ownerPhone,
      customer_id:    customer?.id || null,
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
      due_date: (customer && owed > 0 && dueDate) ? dueDate : null,
    };
    try {
      const result = await apiPost("pos/save", payload);
      navigate(`/pos/receipt/${result.receipt_id}`);
    } catch (e) {
      if (isNetworkError(e)) {
        const label = `POS sale — ${cart.length} item(s), ${nairaFull(paid)}`;
        enqueue("pos/save", payload, label);
        setCart([]); setCustomer(null); setPayment(""); setDueDate(""); setSaveErr("");
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
        <ProductGrid ownerPhone={ownerPhone} onAdd={addToCart} />
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
              onSelect={setCustomer}
              onClear={() => setCustomer(null)}
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

          {saveErr && <div className="pos-error">{saveErr}</div>}

          <button
            className="btn btn-primary"
            style={{ width: "calc(100% - 32px)", margin: "0 16px 16px", justifyContent: "center" }}
            onClick={handleSave}
            disabled={saving || cart.length === 0}
          >
            {saving ? "Saving…" : `Save Sale · ${nairaFull(total)}`}
          </button>
        </div>
      </div>
    </div>
  );
}
