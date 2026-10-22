"""
Stock count (SC-0001) — count the shelves, see what's different, fix stock.

1. Start a count: every stocked product (or one category; branch staff count
   their branch). Goods kept aside for customers are in the store, so they
   are counted too.
2. Count: type what is really there. By default the counter does not see the
   app's numbers (Settings → blind count), so they count instead of copying.
   Anything left empty isn't counted and isn't changed.
3. Submit: the app's numbers are taken at that moment and the differences
   valued at cost. Staff submit; the owner or authorised staff approves.
4. Approve: each product changes by its difference (counted − app's number
   at submission), so sales made while the count waited aren't wiped out.
   Each difference has a reason — the losses report adds them up.
"""
from datetime import datetime, timezone

from sqlalchemy import func

from models import InventoryItem, InventoryMovement, StockCount, StockCountLine, User

REASONS = {
    "miscount": "Counted wrong before",
    "damaged": "Damaged",
    "expired": "Expired",
    "missing": "Stolen / missing",
    "found": "Found extra",
    "other": "Other",
}


class StockCountError(ValueError):
    pass


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _num(q):
    q = float(q or 0)
    return int(q) if q == int(q) else round(q, 2)


def format_count_number(n):
    return f"SC-{int(n):04d}"


def _stocked(query):
    return query.filter(InventoryItem.quantity.isnot(None),
                        func.coalesce(InventoryItem.category, "") != "service")


def start_count(db, owner_phone, user_id, items_query, category=None, branch_id=None, blind=True):
    """A new count over the products in `items_query` (already scoped to what
    this person may see), optionally one category."""
    q = _stocked(items_query)
    label = "All products"
    if category:
        q = q.filter(func.lower(InventoryItem.category) == category.strip().lower())
        label = category.strip().title()
    items = q.order_by(func.lower(func.coalesce(InventoryItem.category, "")), func.lower(InventoryItem.name)).all()
    if not items:
        raise StockCountError("No products with stock to count here.")
    top = db.query(func.max(StockCount.number)).filter(StockCount.owner_phone == owner_phone).scalar()
    sc = StockCount(owner_phone=owner_phone, branch_id=branch_id, number=int(top or 0) + 1,
                    scope_label=label, status="counting", blind=bool(blind), created_by_id=user_id)
    db.add(sc)
    db.flush()
    for it in items:
        db.add(StockCountLine(count_id=sc.id, item_id=it.id, product=it.name, unit=it.unit,
                              category=it.category))
    db.flush()
    return sc


def _lines(db, sc):
    return (db.query(StockCountLine).filter(StockCountLine.count_id == sc.id)
            .order_by(func.lower(func.coalesce(StockCountLine.category, "")), func.lower(StockCountLine.product))
            .all())


def _qty(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        q = float(v)
    except (TypeError, ValueError):
        raise StockCountError("Counts must be numbers.")
    if q != q or q < 0 or q in (float("inf"),):
        raise StockCountError("Counts can't be negative.")
    return q


def save_counts(db, sc, counts):
    """Save what was counted so far: {line_id: qty or None}."""
    if sc.status != "counting":
        raise StockCountError("This count has already been sent for approval.")
    by_id = {l.id: l for l in _lines(db, sc)}
    for line_id, qty in (counts or {}).items():
        line = by_id.get(int(line_id))
        if line is None:
            raise StockCountError("That product isn't on this count.")
        line.counted_qty = _qty(qty)
    db.flush()


def submit_count(db, sc, user_id):
    """Counting done: take the app's numbers now and value the differences."""
    if sc.status != "counting":
        raise StockCountError("This count has already been sent for approval.")
    lines = [l for l in _lines(db, sc) if l.counted_qty is not None]
    if not lines:
        raise StockCountError("Count at least one product first.")
    for l in lines:
        item = db.query(InventoryItem).filter(InventoryItem.id == l.item_id).first()
        l.expected_qty = float(item.quantity or 0) if item else 0.0
        l.cost_price = int(item.cost_price or 0) if item and item.cost_price else None
        diff = l.counted_qty - l.expected_qty
        if abs(diff) > 1e-9 and not l.reason:
            l.reason = "found" if diff > 0 else None
    sc.status = "submitted"
    sc.submitted_by_id = user_id
    sc.submitted_at = _utcnow()
    db.flush()


def set_reasons(db, sc, reasons):
    """{line_id: reason key} — why each product differs."""
    if sc.status not in ("counting", "submitted"):
        raise StockCountError("This count is closed.")
    by_id = {l.id: l for l in _lines(db, sc)}
    for line_id, reason in (reasons or {}).items():
        line = by_id.get(int(line_id))
        if line is None:
            raise StockCountError("That product isn't on this count.")
        if reason and reason not in REASONS:
            raise StockCountError("Pick one of the reasons shown.")
        line.reason = reason or None
    db.flush()


def approve_count(db, sc, user_id):
    """Change stock by each difference, with its reason. Once."""
    if sc.status != "submitted":
        raise StockCountError("Only a count sent for approval can be approved.")
    lines = [l for l in _lines(db, sc) if l.counted_qty is not None and l.expected_qty is not None]
    missing = [l for l in lines if abs(l.counted_qty - l.expected_qty) > 1e-9 and not l.reason]
    if missing:
        raise StockCountError(f"Say why {missing[0].product.title()} is different "
                              f"({len(missing)} product{'s' if len(missing) != 1 else ''} without a reason).")
    for l in lines:
        diff = l.counted_qty - l.expected_qty
        if abs(diff) <= 1e-9:
            l.applied_qty = 0.0
            continue
        item = db.query(InventoryItem).filter(InventoryItem.id == l.item_id).first()
        if item is None:
            continue
        item.quantity = max(0.0, float(item.quantity or 0) + diff)
        item.updated_at = _utcnow()
        db.add(InventoryMovement(
            owner_phone=sc.owner_phone, item_id=item.id, movement_type="IN" if diff > 0 else "OUT",
            quantity=abs(diff), unit_price=l.cost_price, source_type="STOCK_COUNT", source_id=sc.id,
            recorded_by_id=user_id,
            note=f"Stock count {format_count_number(sc.number)}: {REASONS.get(l.reason, l.reason)}",
        ))
        l.applied_qty = diff
    sc.status = "approved"
    sc.approved_by_id = user_id
    sc.approved_at = _utcnow()
    db.flush()


def cancel_count(db, sc):
    if sc.status in ("approved", "cancelled"):
        raise StockCountError("This count is already closed.")
    sc.status = "cancelled"
    sc.cancelled_at = _utcnow()
    db.flush()


def _value(l):
    if l.counted_qty is None or l.expected_qty is None:
        return None
    return int(round((l.counted_qty - l.expected_qty) * (l.cost_price or 0)))


def count_document(db, sc, show_expected=True, show_money=True):
    """The count as the page shows it. `show_expected` False while a blind
    count is still being counted; `show_money` False for staff who don't see
    cost-based figures."""
    names = {u.id: (u.name or "").title() for u in db.query(User).filter(User.id.in_(
        [x for x in (sc.created_by_id, sc.submitted_by_id, sc.approved_by_id) if x] or [""])).all()}
    lines, lost, found, differ, counted = [], 0, 0, 0, 0
    for l in _lines(db, sc):
        row = {"id": l.id, "item_id": l.item_id, "product": (l.product or "").title(), "unit": l.unit,
               "category": (l.category or "").title() or None,
               "counted": None if l.counted_qty is None else _num(l.counted_qty), "reason": l.reason}
        if l.counted_qty is not None:
            counted += 1
        if show_expected:
            expected = l.expected_qty
            if expected is None:            # not submitted yet: what the app says now
                item = db.query(InventoryItem).filter(InventoryItem.id == l.item_id).first()
                expected = float(item.quantity or 0) if item else None
            row["expected"] = None if expected is None else _num(expected)
            if l.counted_qty is not None and expected is not None:
                row["difference"] = _num(l.counted_qty - expected)
                if abs(l.counted_qty - expected) > 1e-9:
                    differ += 1
            if show_money:
                v = _value(l)
                row["value"] = v
                if v is not None and v < 0:
                    lost += -v
                elif v:
                    found += v
        lines.append(row)
    return {
        "id": sc.id, "number": format_count_number(sc.number), "status": sc.status,
        "scope": sc.scope_label, "blind": bool(sc.blind), "branch_id": sc.branch_id,
        "created_at": sc.created_at.isoformat() if sc.created_at else None,
        "submitted_at": sc.submitted_at.isoformat() if sc.submitted_at else None,
        "approved_at": sc.approved_at.isoformat() if sc.approved_at else None,
        "counted_by": names.get(sc.submitted_by_id) or names.get(sc.created_by_id),
        "approved_by": names.get(sc.approved_by_id),
        "lines": lines, "counted": counted, "total": len(lines),
        "differ": differ if show_expected else None,
        "value_lost": lost if (show_expected and show_money) else None,
        "value_found": found if (show_expected and show_money) else None,
        "reasons": REASONS,
    }


def list_counts(db, owner_phone, branch_id=None, limit=50):
    q = db.query(StockCount).filter(StockCount.owner_phone == owner_phone)
    if branch_id is not None:
        q = q.filter(StockCount.branch_id == branch_id)
    out = []
    for sc in q.order_by(StockCount.id.desc()).limit(limit).all():
        n = db.query(func.count(StockCountLine.id)).filter(StockCountLine.count_id == sc.id,
                                                           StockCountLine.counted_qty.isnot(None)).scalar()
        out.append({"id": sc.id, "number": format_count_number(sc.number), "status": sc.status,
                    "scope": sc.scope_label, "counted": int(n or 0),
                    "created_at": sc.created_at.isoformat() if sc.created_at else None})
    return out


def losses(db, owner_phone, since, branch_id=None):
    """Stock lost or found on approved counts since `since`, by reason, at cost."""
    q = (db.query(StockCountLine, StockCount).join(StockCount, StockCountLine.count_id == StockCount.id)
         .filter(StockCount.owner_phone == owner_phone, StockCount.status == "approved",
                 StockCount.approved_at >= since, StockCountLine.applied_qty.isnot(None),
                 StockCountLine.applied_qty != 0))
    if branch_id is not None:
        q = q.filter(StockCount.branch_id == branch_id)
    by_reason, lost, found = {}, 0, 0
    for l, _sc in q.all():
        v = int(round(float(l.applied_qty) * (l.cost_price or 0)))
        r = by_reason.setdefault(l.reason or "other", {"reason": REASONS.get(l.reason or "other"), "value": 0})
        r["value"] += v
        if v < 0:
            lost += -v
        else:
            found += v
    return {"lost": lost, "found": found,
            "by_reason": sorted(by_reason.values(), key=lambda r: r["value"])}
