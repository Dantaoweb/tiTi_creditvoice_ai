"""
Stock that leaves without being sold — always with a reason, so every loss is
accounted for (user, 2026-10-30).

- Remove Stock (Adjust stock) needs a reason from REASONS; "Other" needs words.
- Removing a product takes its remaining stock out with the same reason, then
  hides the product (removed_at). It is never erased: past sales, receipts and
  stock history still point at it.
- The "Removed stock" report lists every loss in one place — removals by hand,
  removed products, expired write-offs and stock-count shortages — with its
  value at cost price, who did it and why.

Only people who manage stock (owner / authorised staff) can remove stock.
"""
from datetime import datetime, timedelta

from models import InventoryItem, InventoryMovement, User

REASONS = {
    "damaged": "Damaged / broken",
    "expired": "Expired",
    "stolen": "Stolen / missing",
    "own_use": "Used in the business",
    "free": "Given free / sample",
    "returned": "Returned to supplier",
    "correction": "Counting correction",
    "other": "Other",
}
# Losses recorded by other parts of the app, and the reason they stand for
_SOURCES = {"WEB_ADJUST": None, "MANUAL": None, "PRODUCT_REMOVED": None, "EXPIRED_WRITE_OFF": "expired",
            "STOCK_COUNT": "count_short"}
_EXTRA_LABELS = {"count_short": "Short at stock count", "unspecified": "No reason given (before reasons were required)"}


class RemovalError(ValueError):
    pass


def clean_reason(reason, note):
    reason = (reason or "").strip().lower()
    if reason not in REASONS:
        raise RemovalError("Pick why the stock is being removed.")
    note = (note or "").strip()[:500] or None
    if reason == "other" and not note:
        raise RemovalError("Say what happened — the reason is \"Other\".")
    return reason, note


_WORDS = (
    ("expired", ("expir", "expiry", "past date", "out of date")),
    ("damaged", ("damag", "broke", "spoil", "spoilage", "rotten", "torn", "leak", "bad")),
    ("stolen", ("stole", "theft", "thief", "missing", "lost")),
    ("own_use", ("own use", "used in", "we used", "staff use", "used it", "consum")),
    ("free", ("free", "sample", "gift", "dash")),
    ("returned", ("return",)),
    ("correction", ("correct", "count", "mistake", "wrong")),
)


def reason_from_words(text):
    """(reason, note) from what someone typed in chat: "(spoilage)" →
    damaged; anything else → other, with their words as the note."""
    words = (text or "").strip()
    low = words.lower()
    for key, hints in _WORDS:
        if any(h in low for h in hints):
            return key, words
    return ("other", words) if words else (None, None)


def label(reason):
    return REASONS.get(reason) or _EXTRA_LABELS.get(reason) or (reason or "").replace("_", " ").title()


def record_removal(db, item, qty, reason, note, user_id, source_type="WEB_ADJUST"):
    """Take qty out of stock with its reason and what it was worth."""
    reason, note = clean_reason(reason, note)
    qty = float(qty)
    if qty <= 0:
        raise RemovalError("Enter how many to remove.")
    item.quantity = (item.quantity or 0) - qty
    item.updated_at = datetime.utcnow()
    mv = InventoryMovement(owner_phone=item.owner_phone, item_id=item.id, movement_type="OUT", quantity=qty,
                           unit_price=item.cost_price, source_type=source_type, recorded_by_id=user_id,
                           reason=reason, note=note or label(reason))
    db.add(mv)
    db.flush()
    return mv


def remove_product(db, item, reason, note, user_id):
    """Remove a product from the business. Its remaining stock goes out with the
    same reason first, so nothing disappears unaccounted."""
    if item.removed_at:
        raise RemovalError("This product was already removed.")
    reason, note = clean_reason(reason, note)
    left = float(item.quantity or 0)
    if left > 0 and (item.category or "") != "service":
        record_removal(db, item, left, reason, note, user_id, source_type="PRODUCT_REMOVED")
    item.is_available = False
    item.removed_at = datetime.utcnow()
    item.removed_reason = reason if not note else f"{reason}: {note}"[:300]
    db.flush()
    return left


def removed_report(db, owner_phone, days=30, reason=None, user_id=None, branch_id=None):
    """Every loss in the period, newest first, with totals per reason."""
    since = datetime.utcnow() - timedelta(days=days)
    q = (db.query(InventoryMovement, InventoryItem)
         .join(InventoryItem, InventoryItem.id == InventoryMovement.item_id)
         .filter(InventoryMovement.owner_phone == owner_phone,
                 InventoryMovement.movement_type == "OUT",
                 InventoryMovement.source_type.in_(list(_SOURCES)),
                 InventoryMovement.created_at >= since))
    if branch_id is not None:
        q = q.filter(InventoryItem.branch_id == branch_id)
    if user_id:
        q = q.filter(InventoryMovement.recorded_by_id == user_id)
    names = {}
    rows, totals = [], {}
    for mv, item in q.order_by(InventoryMovement.created_at.desc()).limit(2000):
        why = _SOURCES.get(mv.source_type) or mv.reason or "unspecified"
        if reason and why != reason:
            continue
        value = int(round(float(mv.quantity or 0) * int(mv.unit_price or 0)))
        if mv.recorded_by_id and mv.recorded_by_id not in names:
            u = db.query(User).filter(User.id == mv.recorded_by_id).first()
            names[mv.recorded_by_id] = (u.name or "").title() if u else ""
        rows.append({"id": mv.id, "date": mv.created_at.isoformat() if mv.created_at else None,
                     "product": item.name, "unit": item.unit, "quantity": mv.quantity,
                     "reason": why, "reason_label": label(why),
                     "note": mv.note if mv.note and mv.note != label(why) else None,
                     "value": value, "by": names.get(mv.recorded_by_id, ""),
                     "product_removed": mv.source_type == "PRODUCT_REMOVED"})
        t = totals.setdefault(why, {"reason": why, "label": label(why), "value": 0, "count": 0})
        t["value"] += value
        t["count"] += 1
    return {"days": days, "rows": rows,
            "totals": sorted(totals.values(), key=lambda t: -t["value"]),
            "total_value": sum(t["value"] for t in totals.values()),
            "reasons": [{"key": k, "label": v} for k, v in REASONS.items()]}
