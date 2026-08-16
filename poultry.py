"""
Poultry-farm workflow.

Two daily operations that generic record-keeping apps miss:

  • Egg collection — birds lay eggs, the farmer sorts them into grades and logs
    the day's count. That is stock coming IN (source EGG_COLLECTION), no cost.
  • Feed usage — feed is fed to the birds daily. That is stock going OUT
    (source FEED_USE), but it is NOT a sale — no customer, no revenue.

Both are ordinary InventoryMovements tagged with a non-sale source, so they
reuse inventory, low-stock alerts and the Insights reports for free. Egg grades
are ordinary products (base unit = crate, sellable per loose egg via the retail
fields), so selling a grade is a normal sale.
"""
from datetime import datetime, timezone, timedelta

from models import InventoryItem, InventoryMovement
from inventory_suppliers import add_inventory_movement

EGGS_PER_CRATE = 30

# Canonical egg grades (key, display label). The product stored in inventory is
# "egg (<label lower>)" so each grade is its own priced product.
EGG_GRADES = [
    ("sorted",        "Sorted / Big"),
    ("medium",        "Medium"),
    ("small",         "Small"),
    ("pullet",        "Pullet"),
    ("extra_small",   "Extremely small"),
    ("cracked",       "Cracked"),
    ("badly_cracked", "Badly cracked"),
    ("unsorted",      "Unsorted"),
]
_GRADE_LABEL = dict(EGG_GRADES)
EGG_PRODUCT = {key: f"egg ({label.lower()})" for key, label in EGG_GRADES}
_PRODUCT_GRADE = {v: k for k, v in EGG_PRODUCT.items()}

EGG_COLLECTION_SOURCE = "EGG_COLLECTION"
FEED_USE_SOURCE = "FEED_USE"


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def is_poultry_user(user):
    return getattr(user, "business_type", None) == "poultry_farm"


def _num(value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 0.0
    return n if n > 0 else 0.0


def _parse_when(date_str):
    """A date string (YYYY-MM-DD) becomes noon on that day so it sits cleanly
    inside the day regardless of timezone. Blank/today → now."""
    if not date_str:
        return _utcnow()
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
    except ValueError:
        return _utcnow()
    today = _utcnow().date()
    if d.date() == today:
        return _utcnow()
    return d.replace(hour=12, minute=0, second=0, microsecond=0)


def _is_feed(item):
    name = (item.name or "").lower()
    cat = (item.category or "").lower()
    return "feed" in name or "mash" in name or cat in ("feed", "animal feed")


def list_feed_items(db, owner_phone):
    """Feed products the farm has bought — the rows shown on the feed-usage form."""
    items = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
    ).order_by(InventoryItem.name.asc()).all()
    return [it for it in items if _is_feed(it)]


def _get_or_create_egg_item(db, owner_phone, grade):
    """Egg grades are precise products — resolve/create each by its exact name so
    the generic fuzzy matcher never merges one grade into another. Grades are
    sellable per loose egg (30 = 1 crate) via the retail fields."""
    name = EGG_PRODUCT[grade]
    item = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        InventoryItem.name == name,
    ).first()
    if not item:
        item = InventoryItem(
            owner_phone=owner_phone, name=name, unit="crate", quantity=0,
            category="poultry", retail_unit="egg", retail_per_base=EGGS_PER_CRATE,
        )
        db.add(item)
        db.flush()
    elif item.unit == "crate" and not item.retail_unit:
        item.retail_unit = "egg"
        item.retail_per_base = EGGS_PER_CRATE
    return item


def record_egg_collection(db, owner_phone, rows, recorded_by_id=None, date=None):
    """rows: [{"grade": <key>, "crates": <n>}]. Adds each grade to stock as an
    IN movement tagged EGG_COLLECTION. Returns the total crates logged."""
    when = _parse_when(date)
    total = 0.0
    for r in rows or []:
        grade = r.get("grade")
        crates = _num(r.get("crates"))
        if grade not in EGG_PRODUCT or crates <= 0:
            continue
        # Ensure the exact-named grade item exists first, so add_inventory_movement
        # resolves it by exact match instead of fuzzily matching another grade.
        item = _get_or_create_egg_item(db, owner_phone, grade)
        add_inventory_movement(
            db, owner_phone, item.name, crates, "crate",
            None, "IN", EGG_COLLECTION_SOURCE, None,
            recorded_by_id, note="Egg collection", created_at=when,
        )
        total += crates
    db.commit()
    return total


def record_feed_usage(db, owner_phone, rows, recorded_by_id=None, date=None):
    """rows: [{"item_id": <id>, "quantity": <n>}]. Deducts each feed from stock
    as an OUT movement tagged FEED_USE (consumption, not a sale)."""
    when = _parse_when(date)
    total = 0.0
    for r in rows or []:
        item_id = r.get("item_id")
        qty = _num(r.get("quantity"))
        if not item_id or qty <= 0:
            continue
        item = db.query(InventoryItem).filter(
            InventoryItem.id == item_id,
            InventoryItem.owner_phone == owner_phone,
        ).first()
        if not item:
            continue
        add_inventory_movement(
            db, owner_phone, item.name, qty, item.unit,
            None, "OUT", FEED_USE_SOURCE, None,
            recorded_by_id, note="Feed used", created_at=when,
        )
        total += qty
    db.commit()
    return total


def _daily_history(db, owner_phone, source, days):
    """Group movements of one source into per-day rows (most recent first):
    {date, total, by_name: {name: qty}}."""
    start = _utcnow() - timedelta(days=days)
    movs = db.query(InventoryMovement).filter(
        InventoryMovement.owner_phone == owner_phone,
        InventoryMovement.source_type == source,
        InventoryMovement.created_at >= start,
    ).all()
    names = {}
    if movs:
        ids = {m.item_id for m in movs}
        for it in db.query(InventoryItem).filter(InventoryItem.id.in_(ids)).all():
            names[it.id] = it.name
    by_day = {}
    for m in movs:
        day = (m.created_at or _utcnow()).date().isoformat()
        d = by_day.setdefault(day, {"date": day, "total": 0.0, "by_name": {}})
        d["total"] += m.quantity or 0
        nm = names.get(m.item_id, "—")
        d["by_name"][nm] = d["by_name"].get(nm, 0.0) + (m.quantity or 0)
    return [by_day[k] for k in sorted(by_day, reverse=True)]


def egg_collection_history(db, owner_phone, days=30):
    return _daily_history(db, owner_phone, EGG_COLLECTION_SOURCE, days)


def feed_usage_history(db, owner_phone, days=30):
    return _daily_history(db, owner_phone, FEED_USE_SOURCE, days)


def _today_total(db, owner_phone, source):
    start = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return db.query(InventoryMovement).filter(
        InventoryMovement.owner_phone == owner_phone,
        InventoryMovement.source_type == source,
        InventoryMovement.created_at >= start,
    ).with_entities(InventoryMovement.quantity).all()


def _grade_label_from_name(name):
    grade = _PRODUCT_GRADE.get(name)
    if grade:
        return _GRADE_LABEL[grade]
    return (name or "").replace("egg (", "").replace(")", "").strip().title()


def egg_production_report(db, owner_phone, period=None):
    """Period report tying the poultry workflow together:
      • per grade — crates collected vs sold, and current stock;
      • egg income (revenue from egg sales in the period);
      • feed bought vs feed used (valued at cost);
      • margin over feed = egg income − feed cost used.

    Feed cost used is valued at each feed's cost price (COGS-style) and is kept
    separate from cash spend so it is not double-counted; it is feed-only, not a
    full profit figure."""
    from reports import get_period_range
    start, end = get_period_range(period)

    def _in_period(q):
        if start is not None:
            q = q.filter(InventoryMovement.created_at >= start,
                         InventoryMovement.created_at < end)
        return q

    def _movements(item_ids, direction, source=None):
        if not item_ids:
            return []
        q = db.query(InventoryMovement).filter(
            InventoryMovement.owner_phone == owner_phone,
            InventoryMovement.item_id.in_(item_ids),
            InventoryMovement.movement_type == direction,
        )
        if source:
            q = q.filter(InventoryMovement.source_type == source)
        return _in_period(q).all()

    # ── Eggs: collected (production IN) vs sold (OUT) per grade ──
    egg_items = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        InventoryItem.name.like("egg (%"),
    ).all()
    egg_ids = [it.id for it in egg_items]
    collected, sold, income = {}, {}, {}
    for m in _movements(egg_ids, "IN", EGG_COLLECTION_SOURCE):
        collected[m.item_id] = collected.get(m.item_id, 0) + (m.quantity or 0)
    for m in _movements(egg_ids, "OUT"):   # eggs only leave via a sale
        sold[m.item_id] = sold.get(m.item_id, 0) + (m.quantity or 0)
        income[m.item_id] = income.get(m.item_id, 0) + (m.quantity or 0) * (m.unit_price or 0)

    rows = []
    for it in egg_items:
        rows.append({
            "label": _grade_label_from_name(it.name),
            "collected": collected.get(it.id, 0),
            "sold": sold.get(it.id, 0),
            "in_stock": it.quantity or 0,
            "income": income.get(it.id, 0),
        })
    order = {EGG_PRODUCT[k]: i for i, (k, _) in enumerate(EGG_GRADES)}
    rows.sort(key=lambda r: order.get(f"egg ({r['label'].lower()})", 99))
    egg_income = sum(r["income"] for r in rows)
    eggs_total = {
        "collected": sum(r["collected"] for r in rows),
        "sold": sum(r["sold"] for r in rows),
        "in_stock": sum(r["in_stock"] for r in rows),
    }

    # ── Feed: bought (IN, at cost) vs used (FEED_USE OUT, valued at cost) ──
    feed_items = list_feed_items(db, owner_phone)
    feed_ids = [f.id for f in feed_items]
    cost_of = {f.id: (f.cost_price or 0) for f in feed_items}
    feed_bought = sum((m.quantity or 0) * (m.unit_price or 0)
                      for m in _movements(feed_ids, "IN"))
    used_movs = _movements(feed_ids, "OUT", FEED_USE_SOURCE)
    feed_used_qty = sum((m.quantity or 0) for m in used_movs)
    feed_cost_used = sum((m.quantity or 0) * cost_of.get(m.item_id, 0) for m in used_movs)

    return {
        "period": period,
        "eggs": rows,
        "eggs_total": eggs_total,
        "egg_income": egg_income,
        "feed_bought": feed_bought,
        "feed_used_qty": feed_used_qty,
        "feed_cost_used": feed_cost_used,
        "margin_over_feed": egg_income - feed_cost_used,
    }


def poultry_summary(db, owner_phone):
    """Header numbers for the poultry screen: today's eggs, today's feed, and
    current egg + feed stock on hand."""
    eggs_today = sum((q or 0) for (q,) in _today_total(db, owner_phone, EGG_COLLECTION_SOURCE))
    feed_today = sum((q or 0) for (q,) in _today_total(db, owner_phone, FEED_USE_SOURCE))

    egg_items = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        InventoryItem.name.like("egg (%"),
    ).all()
    eggs_in_stock = sum((it.quantity or 0) for it in egg_items)
    feed_in_stock = sum((it.quantity or 0) for it in list_feed_items(db, owner_phone))
    return {
        "eggs_collected_today": eggs_today,
        "feed_used_today": feed_today,
        "eggs_in_stock": eggs_in_stock,
        "feed_in_stock": feed_in_stock,
    }
