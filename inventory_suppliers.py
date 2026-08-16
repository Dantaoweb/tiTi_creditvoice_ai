import re

from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from item_normalizer import normalize_item

# ── Retail breakdown helpers ───────────────────────────────────────────────────

# Maps fraction prefix words → decimal multiplier.
# "half bag" → 0.5 of one bag; "1/8 bag" → 0.125 of one bag.
_FRACTION_MULTIPLIERS = {
    "half": 0.5,
    "quarter": 0.25,
    "three quarter": 0.75,
    "three quarters": 0.75,
    "3/4": 0.75,
    "eighth": 0.125,
    "one eighth": 0.125,
    "1/8": 0.125,
    "one quarter": 0.25,
    "one half": 0.5,
}


def _parse_fraction_unit(unit_str):
    """Split "half bag" → (0.5, "bag"). Returns (1.0, original) if no prefix."""
    if not unit_str:
        return 1.0, unit_str
    s = unit_str.lower().strip()
    for prefix, mult in sorted(_FRACTION_MULTIPLIERS.items(), key=lambda x: -len(x[0])):
        if s == prefix or s.startswith(prefix + " "):
            base = s[len(prefix):].strip()
            return mult, base or unit_str
    return 1.0, unit_str


def _find_by_retail_unit(db, owner_phone, product, sale_unit):
    """Find an InventoryItem whose retail_unit matches sale_unit and whose name matches product."""
    from models import InventoryItem
    candidates = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        InventoryItem.retail_unit.isnot(None),
        func.lower(InventoryItem.retail_unit) == sale_unit.lower(),
    ).all()
    if not candidates:
        return None
    pl = product.lower()
    exact = [c for c in candidates if c.name.lower() == pl]
    if exact:
        return exact[0]
    fuzzy = [c for c in candidates if pl in c.name.lower() or c.name.lower() in pl]
    return fuzzy[0] if len(fuzzy) == 1 else None


def _format_stock_remaining(qty, base_unit, retail_unit=None, retail_per_base=None):
    """Format a float quantity into a human-readable string.
    9.90625 bags (retail_unit=congo, per_base=32) → '9 bags 29 congos'
    4.833 crates (retail_unit=egg, per_base=30) → '4 crates 25 eggs'
    """
    if qty is None:
        return "0"
    qty = float(qty)
    if retail_unit and retail_per_base and retail_per_base > 0:
        whole = int(qty)
        remainder = round((qty - whole) * retail_per_base)
        parts = []
        if whole > 0:
            parts.append(f"{whole:,} {base_unit or ''}".strip())
        if remainder > 0:
            parts.append(f"{remainder} {retail_unit}")
        return " ".join(parts) if parts else f"0 {base_unit or ''}".strip()
    if qty == int(qty):
        label = f" {base_unit}" if base_unit else ""
        return f"{int(qty):,}{label}"
    label = f" {base_unit}" if base_unit else ""
    return f"{qty:.3g}{label}"


def _resolve_deduction(db, owner_phone, product, quantity, unit):
    """Return (item, deduct_amount) where deduct_amount is in the item's base unit (float).
    Returns (None, None) if no matching inventory item found.
    """
    # 1. Fraction prefix check: "half bag" → 0.5 × (match on "bag")
    fraction, base_unit = _parse_fraction_unit(unit or "")
    item = find_matching_inventory_item(db, owner_phone, product, base_unit or unit)
    if item:
        return item, quantity * fraction

    # 2. Retail sub-unit: "3 congo" → match rice whose retail_unit="congo"
    if unit:
        item = _find_by_retail_unit(db, owner_phone, product, unit)
        if item and item.retail_per_base:
            return item, quantity / item.retail_per_base

    # 3. Legacy purchase-history conversion (existing behaviour)
    item, converted = find_converted_inventory_for_sale(db, owner_phone, product, unit, quantity)
    if item:
        return item, float(converted)

    return None, None


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)
from models import (
    CustomerConversation,
    InventoryItem,
    InventoryMovement,
    ProductAlias,
    SalesOrderItem,
    Supplier,
    SupplierPayment,
    SupplierPurchase,
)


def find_or_create_supplier(db, owner_phone, supplier_name):
    supplier_name = supplier_name.strip().lower()
    supplier = db.query(Supplier).filter(
        Supplier.owner_phone == owner_phone,
        func.lower(Supplier.name) == supplier_name
    ).first()
    if supplier:
        return supplier
    supplier = Supplier(name=supplier_name, owner_phone=owner_phone)
    db.add(supplier)
    db.flush()
    return supplier


def find_inventory_item(db, owner_phone, product, unit=None):
    product, unit = normalize_item(product, unit)
    query = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        func.lower(InventoryItem.name) == product.lower()
    )
    if unit:
        query = query.filter(InventoryItem.unit == unit)
    else:
        query = query.filter(InventoryItem.unit.is_(None))
    return query.first()


def resolve_product_alias(db, owner_phone, product):
    """Return the canonical product name from the per-business alias table, or product unchanged."""
    if not product:
        return product
    alias_row = db.query(ProductAlias).filter(
        ProductAlias.owner_phone == owner_phone,
        func.lower(ProductAlias.alias) == product.lower().strip(),
    ).first()
    return alias_row.canonical if alias_row else product


def save_product_alias(db, owner_phone, alias, canonical):
    """Upsert a per-business product alias."""
    alias = alias.lower().strip()
    canonical = canonical.lower().strip()
    existing = db.query(ProductAlias).filter(
        ProductAlias.owner_phone == owner_phone,
        func.lower(ProductAlias.alias) == alias,
    ).first()
    if existing:
        existing.canonical = canonical
    else:
        db.add(ProductAlias(owner_phone=owner_phone, alias=alias, canonical=canonical))
    db.commit()


def find_matching_inventory_item(db, owner_phone, product, unit=None):
    product, unit = normalize_item(product, unit)

    # 1. Exact match
    item = find_inventory_item(db, owner_phone, product, unit)
    if item:
        return item

    # 2. Per-business alias (e.g. "eba" → "garri")
    resolved = resolve_product_alias(db, owner_phone, product)
    if resolved != product:
        item = find_inventory_item(db, owner_phone, resolved, unit)
        if item:
            return item
        # Also try without unit constraint after alias
        if unit:
            item = find_inventory_item(db, owner_phone, resolved, None)
            if item:
                return item

    # 3. Single item with this name, regardless of unit. Runs even when a unit is
    #    given so a stock-in doesn't create a DUPLICATE when the received unit
    #    normalises differently from how the item was stored (e.g. "bottles" vs
    #    "bottle") — the cause of one row holding the price and a twin holding the
    #    quantity. Guarded on exactly one match, so deliberate multi-unit variants
    #    of the same name still require an exact unit match.
    product_matches = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        func.lower(InventoryItem.name) == product.lower()
    ).all()
    if len(product_matches) == 1:
        return product_matches[0]

    # 4. Legacy "unit of product" composite name
    if unit:
        legacy_name = f"{unit} of {product}".lower()
        item = find_inventory_item(db, owner_phone, legacy_name, None)
        if item:
            return item

    # 5. Strip embedded unit prefix from product string
    unit_match = re.match(r"^(?P<unit>[a-z]+)\s+of\s+(?P<product>.+)$", product.lower())
    if unit_match:
        item = find_inventory_item(
            db,
            owner_phone,
            unit_match.group("product"),
            unit_match.group("unit"),
        )
        if item:
            return item

    # 6. Fuzzy word match: strip prepositions then check every query word is
    #    a prefix/substring of some word in the item name. Only return when
    #    exactly one item matches to avoid false positives.
    #    e.g. "basket of mangoes" → ["basket","mangoes"] matches "Baskets Mangoes"
    #    Unit is respected: "vitamin c sachet" won't match "vitamin c carton".
    def _deplural(w):
        if len(w) > 4 and w.endswith("ies"):
            return w[:-3] + "y"
        if len(w) > 3 and w.endswith("es"):
            return w[:-2]
        if len(w) > 2 and w.endswith("s"):
            return w[:-1]
        return w

    def _word_matches(qw, iwords):
        dq = _deplural(qw)
        return any(
            qw in iw or iw.startswith(qw) or qw.startswith(iw)
            or dq == iw or iw == _deplural(iw) and qw == _deplural(iw)
            for iw in iwords
        )

    _stop = {"of", "the", "and", "in", "a", "an"}
    _qwords = [w for w in re.split(r"\W+", product.lower()) if w and w not in _stop]
    if len(_qwords) >= 2:
        _candidates = []
        for _inv in db.query(InventoryItem).filter(
            InventoryItem.owner_phone == owner_phone
        ).all():
            # Skip items with a different unit when caller specified a unit
            if unit and _inv.unit and _inv.unit.lower() != unit.lower():
                continue
            # Drop empty tokens: a name like "egg (sorted)" splits to
            # {"egg","sorted",""}, and qw.startswith("") is always true — which
            # would fuzzily match ANY query word against the empty token and
            # merge unrelated products (e.g. "layer mash" into "egg (sorted)").
            _iwords = set(w for w in re.split(r"\W+", _inv.name.lower()) if w)
            if all(_word_matches(qw, _iwords) for qw in _qwords):
                _candidates.append(_inv)
        if len(_candidates) == 1:
            return _candidates[0]

    return None


def find_converted_inventory_for_sale(db, owner_phone, product, sale_unit, sale_quantity):
    product, sale_unit = normalize_item(product, sale_unit)
    if not product or not sale_unit:
        return None, None

    purchases = db.query(SupplierPurchase).filter(
        SupplierPurchase.owner_phone == owner_phone,
        func.lower(SupplierPurchase.product) == product.lower(),
        SupplierPurchase.unit == sale_unit,
        SupplierPurchase.quantity != None,
        SupplierPurchase.quantity > 0,
    ).order_by(
        SupplierPurchase.created_at.desc()
    ).all()

    for purchase in purchases:
        movement = db.query(InventoryMovement).join(
            InventoryItem,
            InventoryMovement.item_id == InventoryItem.id
        ).filter(
            InventoryMovement.owner_phone == owner_phone,
            InventoryMovement.source_type == "SUPPLIER_PURCHASE",
            InventoryMovement.source_id == purchase.id,
            InventoryMovement.movement_type == "IN",
            func.lower(InventoryItem.name) == product.lower(),
        ).order_by(
            InventoryMovement.created_at.desc()
        ).first()
        if not movement or not movement.quantity:
            continue

        item = db.query(InventoryItem).filter(
            InventoryItem.id == movement.item_id
        ).first()
        if not item or item.unit == sale_unit:
            continue

        conversion_ratio = movement.quantity / purchase.quantity
        if conversion_ratio <= 0:
            continue

        return item, int(round((sale_quantity or 1) * conversion_ratio))

    return None, None


def _auto_category(db, owner_phone, product):
    """Look up a suggested category for a product based on the owner's business template."""
    from models import User
    from business_templates import template_key_for_user, get_product_category_suggestion
    owner = db.query(User).filter(User.phone == owner_phone).first()
    if not owner:
        return None
    return get_product_category_suggestion(
        template_key_for_user(owner), product, getattr(owner, "business_type", None)
    )


def add_inventory_movement(db, owner_phone, product, quantity, unit, unit_price, movement_type, source_type, source_id, recorded_by_id=None, note=None, created_at=None):
    if not product or not quantity:
        return None
    product, unit = normalize_item(product, unit)
    item = find_matching_inventory_item(db, owner_phone, product, unit)
    if not item:
        item = InventoryItem(
            owner_phone=owner_phone,
            name=product.lower(),
            unit=unit,
            quantity=0,
            cost_price=unit_price,
            category=_auto_category(db, owner_phone, product),
        )
        db.add(item)
        db.flush()

    if movement_type == "IN":
        item.quantity = (item.quantity or 0) + quantity
        if unit_price:
            item.cost_price = unit_price
    elif movement_type == "OUT":
        item.quantity = max(0.0, (item.quantity or 0.0) - quantity)
    else:
        item.quantity = (item.quantity or 0) + quantity
    item.updated_at = _utcnow()

    mv_kwargs = dict(
        owner_phone=owner_phone,
        item_id=item.id,
        movement_type=movement_type,
        quantity=quantity,
        unit_price=unit_price,
        source_type=source_type,
        source_id=source_id,
        recorded_by_id=recorded_by_id,
        note=note,
    )
    # Let callers backdate a movement (e.g. logging yesterday's egg collection);
    # when omitted, the column default (utcnow) applies.
    if created_at is not None:
        mv_kwargs["created_at"] = created_at
    movement = InventoryMovement(**mv_kwargs)
    db.add(movement)
    return item


def deduct_inventory_for_items(db, owner_phone, items, source_type, source_id, recorded_by_id=None):
    updates = []
    missing = []
    low_stock_alerts = []
    for item_data in items or []:
        product = (item_data.get("product") or "").lower().strip()
        quantity = item_data.get("quantity") or 1
        unit = item_data.get("unit")
        product, unit = normalize_item(product, unit)
        if not product:
            continue
        item, deduct_qty = _resolve_deduction(db, owner_phone, product, quantity, unit)
        if not item:
            missing.append(product.title())
            continue
        pre_qty = float(item.quantity or 0)
        add_inventory_movement(
            db, owner_phone, item.name, deduct_qty, item.unit,
            item_data.get("unit_price"), "OUT", source_type, source_id,
            recorded_by_id, "Sold",
        )
        post_qty = float(item.quantity or 0)
        remaining_label = _format_stock_remaining(
            post_qty, item.unit, item.retail_unit, item.retail_per_base
        )
        updates.append(f"{product.title()}: {remaining_label} left")
        name = item.name.title()
        if pre_qty == 0:
            low_stock_alerts.append(
                f"⚠️ *{name}* was already OUT OF STOCK when this sale was recorded"
            )
        elif post_qty == 0:
            low_stock_alerts.append(
                f"⚠️ *{name}* is now OUT OF STOCK — please restock"
            )
        elif item.low_stock_alert is not None and post_qty <= item.low_stock_alert:
            low_stock_alerts.append(
                f"⚠️ *{name}*: only {remaining_label} left — running low"
            )
    return updates, missing, low_stock_alerts


def get_supplier_balance(db, supplier_id):
    total_purchase = db.query(func.coalesce(func.sum(SupplierPurchase.total), 0)).filter(
        SupplierPurchase.supplier_id == supplier_id
    ).scalar()
    paid_on_purchase = db.query(func.coalesce(func.sum(SupplierPurchase.paid_amount), 0)).filter(
        SupplierPurchase.supplier_id == supplier_id
    ).scalar()
    payments = db.query(func.coalesce(func.sum(SupplierPayment.amount), 0)).filter(
        SupplierPayment.supplier_id == supplier_id
    ).scalar()
    return total_purchase - paid_on_purchase - payments


def get_supplier_products(db, owner_phone, supplier_name):
    """
    All products a supplier has ever supplied.
    Returns (supplier_obj, list of product dicts) or (None, []) if not found.
    Each dict: {product, count, last_date, last_unit_price, last_unit}
    """
    from collections import defaultdict

    supplier = db.query(Supplier).filter(
        Supplier.owner_phone == owner_phone,
        func.lower(Supplier.name) == supplier_name.lower().strip(),
    ).first()
    if not supplier:
        supplier = db.query(Supplier).filter(
            Supplier.owner_phone == owner_phone,
            func.lower(Supplier.name).contains(supplier_name.lower().strip()),
        ).first()
    if not supplier:
        return None, []

    purchases = db.query(SupplierPurchase).filter(
        SupplierPurchase.supplier_id == supplier.id,
    ).order_by(SupplierPurchase.created_at.desc()).all()

    seen = defaultdict(lambda: {"count": 0, "last_date": None, "last_unit_price": None, "last_unit": None, "display": None})
    for p in purchases:
        if not p.product:
            continue
        key = p.product.lower()
        entry = seen[key]
        entry["count"] += 1
        if entry["last_date"] is None:
            entry["last_date"] = p.created_at
            entry["last_unit_price"] = p.unit_price
            entry["last_unit"] = p.unit
            entry["display"] = p.product

    result = sorted(
        [{"product": v["display"] or k, **{x: v[x] for x in ("count", "last_date", "last_unit_price", "last_unit")}}
         for k, v in seen.items()],
        key=lambda x: -x["count"],
    )
    return supplier, result


def get_product_suppliers(db, owner_phone, product_name):
    """
    All suppliers who have supplied a given product.
    Each dict: {supplier_id, name, count, last_date, last_unit_price, last_unit}
    Sorted by supply count descending.
    """
    from collections import defaultdict

    purchases = db.query(SupplierPurchase).filter(
        SupplierPurchase.owner_phone == owner_phone,
        func.lower(SupplierPurchase.product) == product_name.lower().strip(),
    ).order_by(SupplierPurchase.created_at.desc()).all()

    seen = defaultdict(lambda: {"count": 0, "last_date": None, "last_unit_price": None, "last_unit": None, "name": None})
    for p in purchases:
        entry = seen[p.supplier_id]
        entry["count"] += 1
        if entry["last_date"] is None:
            entry["last_date"] = p.created_at
            entry["last_unit_price"] = p.unit_price
            entry["last_unit"] = p.unit
        if not entry["name"]:
            sup = db.query(Supplier).filter(Supplier.id == p.supplier_id).first()
            entry["name"] = sup.name if sup else "unknown"

    return sorted(
        [{"supplier_id": sid, **{k: v[k] for k in ("name", "count", "last_date", "last_unit_price", "last_unit")}}
         for sid, v in seen.items()],
        key=lambda x: (-x["count"], x["name"] or ""),
    )


_STOCK_PAGE_SIZE = 20


def build_inventory_list_message(db, owner_phone, product=None, return_ids=False, page=0):
    from collections import defaultdict

    query = db.query(InventoryItem).filter(InventoryItem.owner_phone == owner_phone)
    if product:
        query = query.filter(func.lower(InventoryItem.name).like(f"%{product.lower()}%"))
    items = query.order_by(InventoryItem.name.asc(), InventoryItem.unit.asc()).all()

    if not items:
        empty = "No stock found yet.\n\nTo add stock:\nadd stock rice cost 3000 sell 4000"
        return (empty, []) if return_ids else empty

    # Group variants (same product, different units) together
    grouped = defaultdict(list)
    for item in items:
        grouped[item.name.lower()].append(item)

    # Build full ordered list before slicing for the page
    all_ids = []
    all_entries = []  # (display_name, variant, category, is_multi_variant)

    for name_key in sorted(grouped.keys()):
        variants = sorted(grouped[name_key], key=lambda x: (x.unit or ""))
        display_name = variants[0].name.title()
        category = (variants[0].category or "").strip().lower()
        is_multi = len(variants) > 1
        for v in variants:
            all_ids.append(v.id)
            all_entries.append((display_name, v, category, is_multi))

    total = len(all_ids)
    start = page * _STOCK_PAGE_SIZE
    if start >= total:
        start = 0
    end = min(start + _STOCK_PAGE_SIZE, total)
    page_entries = all_entries[start:end]

    # Total value across ALL items (not just this page)
    total_value = sum((v.quantity or 0) * (v.cost_price or 0) for _, v, _, _ in all_entries)

    title = "Stock" if not product else f"Stock: {product.title()}"
    msg = f"*{title}*\n\n"
    prev_category = None

    for i, (display_name, v, category, is_multi) in enumerate(page_entries):
        idx = start + i + 1  # 1-based absolute index
        qty = v.quantity or 0
        unit_label = f" {v.unit}" if v.unit else ""

        if category and category != prev_category:
            msg += f"— {category.title()} —\n"
            prev_category = category

        from datetime import datetime as _dtl
        _now_dt = _dtl.utcnow()

        if qty == 0:
            indicator = "🔴 "
        elif v.low_stock_alert is not None and qty <= v.low_stock_alert:
            indicator = "⚠️ "
        else:
            indicator = ""

        # Expiry warning overrides other indicators when expired/near
        _exp_suffix = ""
        if v.expiry_date:
            _days_left = (v.expiry_date - _now_dt).days
            if _days_left < 0:
                indicator = "☠ "
                _exp_suffix = f" [EXPIRED {v.expiry_date.strftime('%m/%Y')}]"
            elif _days_left <= 30:
                indicator = "⚠️ "
                _exp_suffix = f" [Exp {v.expiry_date.strftime('%m/%Y')} — {_days_left}d]"

        name_display = f"{display_name} ({v.unit})" if (is_multi and v.unit) else display_name
        line = f"{idx}. {indicator}{name_display}: {qty:,}{unit_label}{_exp_suffix}"
        prices = []
        if v.cost_price:
            prices.append(f"Cost N{v.cost_price:,}")
        if v.selling_price:
            prices.append(f"Sell N{v.selling_price:,}")
        if prices:
            line += f"\n   {' | '.join(prices)}"
        if v.reorder_quantity is not None and qty <= v.reorder_quantity:
            line += f"\n   ↩️ Reorder at {v.reorder_quantity:,}{unit_label}"
        msg += line + "\n\n"

    msg += f"Total stock value: N{total_value:,}"

    if end < total:
        next_end = min(end + _STOCK_PAGE_SIZE, total)
        msg += f"\n\n─ Showing {start + 1}–{end} of {total} items ─\nSend *MORE* for items {end + 1}–{next_end}"

    if return_ids:
        return msg.strip(), all_ids
    return msg.strip()


def build_supplier_list_message(db, owner_phone):
    suppliers = db.query(Supplier).filter(
        Supplier.owner_phone == owner_phone
    ).order_by(Supplier.name.asc()).limit(20).all()
    if not suppliers:
        return "No supplier record yet.\n\nExample:\nAyo supply me 12kg cocoa at 5000"

    msg = "Suppliers\n\n"
    total_debt = 0
    total_credit = 0
    for index, supplier in enumerate(suppliers, start=1):
        balance = get_supplier_balance(db, supplier.id)
        if balance > 0:
            total_debt += balance
            status = f"Debt: N{balance:,}"
        elif balance < 0:
            total_credit += abs(balance)
            status = f"Credit: N{abs(balance):,}"
        else:
            status = "No debt"
        msg += f"{index}. {supplier.name.title()}: {status}\n"

    msg += f"\nTotal supplier debt: N{total_debt:,}"
    if total_credit:
        msg += f"\nTotal supplier credit: N{total_credit:,}"
    return msg


def build_supplier_due_message(db, owner_phone, days=1):
    start = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days)
    purchases = db.query(SupplierPurchase, Supplier).join(
        Supplier,
        SupplierPurchase.supplier_id == Supplier.id
    ).filter(
        SupplierPurchase.owner_phone == owner_phone,
        SupplierPurchase.due_date >= start,
        SupplierPurchase.due_date < end,
    ).order_by(SupplierPurchase.due_date.asc()).all()

    period_label = "Today" if days == 1 else f"Next {days} Days"
    none_msg = f"No supplier payment due {'today' if days == 1 else f'in the next {days} days'}."

    if not purchases:
        return none_msg

    msg = f"Supplier Payments Due — {period_label}\n\n"
    count = 0
    for purchase, supplier in purchases:
        balance = max((purchase.total or 0) - (purchase.paid_amount or 0), 0)
        if balance == 0:
            continue
        count += 1
        due_label = purchase.due_date.strftime("%d/%m") if purchase.due_date else ""
        due_str = f" (due {due_label})" if days > 1 and due_label else ""
        msg += f"{count}. {supplier.name.title()} - N{balance:,} for {purchase.product.title()}{due_str}\n"
    return msg.strip() if count else none_msg


# ── Manual stock operations ──────────────────────────────────────────────────

def upsert_stock_with_prices(db, owner_phone, product, unit, cost_price, selling_price):
    """Create or update an inventory item's cost and selling prices."""
    product, unit = normalize_item(product, unit)
    item = find_matching_inventory_item(db, owner_phone, product, unit)
    if not item:
        item = InventoryItem(
            owner_phone=owner_phone,
            name=product.lower(),
            unit=unit,
            quantity=0,
            cost_price=cost_price,
            selling_price=selling_price,
            is_available=True,
            category=_auto_category(db, owner_phone, product),
        )
        db.add(item)
    else:
        item.cost_price = cost_price
        item.selling_price = selling_price
        item.is_available = True
        item.updated_at = _utcnow()
    return item


def manual_stock_add(db, owner_phone, product, quantity, unit, user_id, note="Manual add"):
    """Add stock without a supplier transaction (e.g. owner counted and corrected)."""
    return add_inventory_movement(
        db, owner_phone, product, quantity, unit, None,
        "IN", "MANUAL", None, user_id, note,
    )


def update_cost_price(db, owner_phone, product, price):
    """Update cost price for all variants of a product. Returns list of updated items."""
    product_norm, _ = normalize_item(product, None)
    items = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        func.lower(InventoryItem.name).like(f"%{product_norm.lower()}%"),
    ).all()
    for item in items:
        item.cost_price = price
        item.updated_at = _utcnow()
    return items


def delete_stock_item(db, owner_phone, product):
    """Delete inventory item(s) whose name contains the product string. Returns count deleted."""
    product_norm, _ = normalize_item(product, None)
    items = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        func.lower(InventoryItem.name).like(f"%{product_norm.lower()}%"),
    ).all()
    if not items:
        return 0
    ids = [item.id for item in items]
    # Null out FK references before deleting to avoid constraint violations.
    # Movement history is preserved (item_id nulled) so audit trail is not lost.
    db.query(InventoryMovement).filter(
        InventoryMovement.item_id.in_(ids)
    ).update({"item_id": None}, synchronize_session=False)
    db.query(SalesOrderItem).filter(
        SalesOrderItem.inventory_item_id.in_(ids)
    ).update({"inventory_item_id": None}, synchronize_session=False)
    db.query(CustomerConversation).filter(
        CustomerConversation.matched_item_id.in_(ids)
    ).update({"matched_item_id": None}, synchronize_session=False)
    for item in items:
        db.delete(item)
    return len(items)


def manual_stock_remove(db, owner_phone, product, quantity, unit, user_id, note="Manual remove"):
    """Remove stock without a sale (spoilage, theft, expiry, correction)."""
    return add_inventory_movement(
        db, owner_phone, product, quantity, unit, None,
        "OUT", "MANUAL", None, user_id, note,
    )


def manual_stock_set(db, owner_phone, product, quantity, unit, user_id):
    """Set an absolute stock count (physical stock-take correction)."""
    product, unit = normalize_item(product, unit)
    item = find_matching_inventory_item(db, owner_phone, product, unit)
    if not item:
        item = InventoryItem(
            owner_phone=owner_phone,
            name=product.lower(),
            unit=unit,
            quantity=0,
        )
        db.add(item)
        db.flush()

    old_qty = item.quantity or 0
    diff = quantity - old_qty
    if diff != 0:
        movement = InventoryMovement(
            owner_phone=owner_phone,
            item_id=item.id,
            movement_type="IN" if diff > 0 else "OUT",
            quantity=abs(diff),
            source_type="MANUAL_SET",
            recorded_by_id=user_id,
            note=f"Stock count: set to {quantity}",
        )
        db.add(movement)
    item.quantity = quantity
    item.updated_at = _utcnow()
    return item


def set_retail_breakdown(db, owner_phone, product, unit, retail_unit, retail_per_base, retail_price=None):
    """Configure how a product breaks down into smaller retail pieces.

    Example: set_retail_breakdown(db, phone, "egg", "crate", "egg", 30, 70)
    means 1 crate = 30 individual eggs sold at ₦70 each.
    """
    product, unit = normalize_item(product, unit)
    item = find_matching_inventory_item(db, owner_phone, product, unit)
    if not item:
        return None, "Product not found in stock. Add it to stock first."
    item.retail_unit = retail_unit.lower().strip() if retail_unit else None
    item.retail_per_base = int(retail_per_base) if retail_per_base else None
    if retail_price is not None:
        item.retail_price = int(retail_price)
    item.updated_at = _utcnow()
    return item, None


def set_low_stock_alert(db, owner_phone, product, unit, threshold):
    """Set the low-stock alert threshold for an inventory item."""
    product, unit = normalize_item(product, unit)
    item = find_matching_inventory_item(db, owner_phone, product, unit)
    if not item:
        return None
    item.low_stock_alert = threshold
    item.updated_at = _utcnow()
    return item


def set_product_category(db, owner_phone, product, category):
    """Tag all unit-variants of a product with a category label."""
    product, _ = normalize_item(product)
    items = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        func.lower(InventoryItem.name) == product.lower(),
    ).all()
    if not items:
        return []
    for item in items:
        item.category = category.lower().strip()
        item.updated_at = _utcnow()
    return items


def set_reorder_quantity(db, owner_phone, product, unit, quantity):
    """Set the reorder-point threshold for an inventory item."""
    product, unit = normalize_item(product, unit)
    item = find_matching_inventory_item(db, owner_phone, product, unit)
    if not item:
        return None
    item.reorder_quantity = quantity
    item.updated_at = _utcnow()
    return item


def get_total_stock_value(db, owner_phone):
    """Sum of (quantity × cost_price) across all inventory items."""
    items = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        InventoryItem.quantity > 0,
        InventoryItem.cost_price.isnot(None),
    ).all()
    return sum((i.quantity or 0) * (i.cost_price or 0) for i in items)
