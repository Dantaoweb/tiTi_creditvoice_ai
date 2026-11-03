"""
Held sales at the till ("Hold" → serve the next customer → open it again).

A customer isn't ready (gone to the ATM, still choosing): the cashier holds the
cart and starts a fresh one. As many as needed. A held cart is not a sale — no
stock moves, no debt, no receipt — until it is opened and saved, when it is
removed (web_pos_routes: PosSaveRequest.held_id).

Who sees which: a cashier sees the carts they held; the owner and staff allowed
to see all records see everyone's (the stock rule). Branch staff only ever see
their branch's.
"""
import json
from datetime import timedelta

from models import Customer, HeldSale, InventoryItem, User, utcnow

MAX_HELD = 50           # per business, so a forgotten habit can't pile up
STALE_DAYS = 7          # flagged "still waiting?" after this

# What a till line may carry back to the till. Everything else is dropped.
_LINE_KEYS = {
    "inventory_item_id", "name", "qty", "unit", "unit_price", "sold_unit", "fraction",
    "base_price", "_base_price", "wholesale_price", "wholesale_min_qty", "priceEdited",
    "retail_unit", "retail_per_base", "retail_price", "is_service", "vat_exempt",
    "stock", "free", "expired_qty", "delivered",
}


class HeldError(ValueError):
    pass


def can_see_all(user):
    return bool(user and (not user.parent_id or user.can_view_all_transactions))


def _clean_lines(items):
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        line = {}
        for k in _LINE_KEYS:
            v = it.get(k)
            if v is None or isinstance(v, (bool, int, float)):
                line[k] = v
            elif isinstance(v, str):
                line[k] = v[:120]
        if str(line.get("name") or "").strip():
            out.append(line)
    return out


def _clean_discount(d):
    """The till's discount box as typed: {"input": "500", "pct": False}."""
    if not isinstance(d, dict):
        return None
    return {"input": "".join(ch for ch in str(d.get("input") or "") if ch.isdigit())[:12],
            "pct": bool(d.get("pct"))}


def visible(db, user, owner_phone, eff_branch, rec_by):
    """Held carts this user may see and open."""
    q = db.query(HeldSale).filter(HeldSale.owner_phone == owner_phone)
    if eff_branch is not None:
        q = q.filter(HeldSale.branch_id == eff_branch)
    if rec_by or not can_see_all(user):
        q = q.filter(HeldSale.created_by_id == user.id)
    return q


def hold(db, user, owner_phone, branch_id, *, held_id=None, items=None, discount=None,
         customer_id=None, customer_name=None, customer_phone=None, label=None, total=0,
         scope=None):
    lines = _clean_lines(items)
    if not lines:
        raise HeldError("Add at least one item before holding the sale.")
    if customer_id and not db.query(Customer.id).filter(
            Customer.id == customer_id, Customer.owner_phone == owner_phone).first():
        raise HeldError("That customer was not found.")
    if held_id:
        h = scope.filter(HeldSale.id == held_id).first() if scope is not None else None
        if not h:
            raise HeldError("That held sale is gone — it may have been saved or deleted.")
    else:
        if db.query(HeldSale).filter(HeldSale.owner_phone == owner_phone).count() >= MAX_HELD:
            raise HeldError(f"There are already {MAX_HELD} held sales. Save or delete some first.")
        h = HeldSale(owner_phone=owner_phone, branch_id=branch_id, created_by_id=user.id,
                     created_at=utcnow())
        db.add(h)
    h.customer_id = customer_id or None
    h.customer_name = None if customer_id else ((customer_name or "").strip()[:120] or None)
    h.customer_phone = None if customer_id else ((customer_phone or "").strip()[:20] or None)
    h.label = (label or "").strip()[:80] or None
    h.cart_json = json.dumps({"items": lines, "discount": _clean_discount(discount)})
    h.item_count = len(lines)
    h.total = max(0, int(total or 0))
    h.updated_at = utcnow()
    db.commit()
    return h


def release(db, owner_phone, held_id):
    """The held cart was saved as a sale (or deleted): it's gone."""
    if not held_id:
        return False
    n = db.query(HeldSale).filter(HeldSale.id == held_id, HeldSale.owner_phone == owner_phone).delete()
    db.commit()
    return bool(n)


def _shortages(db, owner_phone, lines):
    """Lines asking for more than can be sold now (stock less what's kept
    aside for customers). The till warns; saving still decides."""
    ids = {l["inventory_item_id"] for l in lines if l.get("inventory_item_id") and not l.get("sold_unit")}
    if not ids:
        return []
    from deliveries import reserved_by_item
    kept = reserved_by_item(db, owner_phone)
    items = {i.id: i for i in db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone, InventoryItem.id.in_(ids)).all()}
    out = []
    for l in lines:
        it = items.get(l.get("inventory_item_id"))
        if l.get("sold_unit") or not it or it.quantity is None:
            continue
        if not it.is_available:
            out.append({"name": l["name"], "free": 0, "removed": True})
            continue
        free = max(0, (it.quantity or 0) - (kept.get(it.id) or 0))
        if float(l.get("qty") or 0) > free:
            out.append({"name": l["name"], "free": free, "removed": False})
    return out


def serialize(db, h, now=None):
    now = now or utcnow()
    data = json.loads(h.cart_json or "{}")
    lines = data.get("items") or []
    cust = None
    if h.customer_id:
        c = db.query(Customer).filter(Customer.id == h.customer_id).first()
        if c:
            cust = {"id": c.id, "name": c.name, "phone": c.customer_phone, "balance": int(c.balance or 0)}
    elif h.customer_name:
        cust = {"id": None, "name": h.customer_name, "phone": h.customer_phone or "", "balance": 0}
    by = db.query(User.name).filter(User.id == h.created_by_id).scalar() if h.created_by_id else None
    created = h.created_at or now
    return {
        "id": h.id,
        "customer": cust,
        "label": h.label,
        "items": lines,
        "discount": data.get("discount"),
        "item_count": h.item_count or len(lines),
        "total": h.total or 0,
        "branch_id": h.branch_id,
        "by": by,
        "created_at": created.isoformat(),
        "updated_at": (h.updated_at or created).isoformat(),
        "stale": (now - created) >= timedelta(days=STALE_DAYS),
        "short": _shortages(db, h.owner_phone, lines),
    }
