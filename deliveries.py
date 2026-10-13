"""
Goods sold but not all handed over yet — a cement seller sells 100 bags, 60 go
out today, 40 wait in the store for the customer.

- A sale line records how many went out (TransactionItem.delivered_qty; NULL
  means all of it, which is every ordinary sale).
- Only what goes out leaves stock. What is still to deliver stays in the store
  as *reserved*: in store − reserved = what can still be sold.
- Each later trip (GoodsDelivery) takes stock out against the customer's
  oldest open sale first, logged as an OUT movement with source DELIVERY and
  the sale as source_id — so voiding the sale returns it like any sale.
- The customer gets a delivery note: bought · delivered · still to deliver.
"""
from datetime import datetime, timezone

from sqlalchemy import func

from models import (
    Customer, GoodsDelivery, InventoryItem, InventoryMovement, Transaction, TransactionItem,
)


class DeliveryError(ValueError):
    pass


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _num(q):
    q = float(q or 0)
    return int(q) if q == int(q) else round(q, 2)


def _open_lines(db, owner_phone, customer_id=None, inventory_item_id=None):
    """Sale lines with goods still to hand over, oldest first, as
    (line, sale, customer)."""
    q = (db.query(TransactionItem, Transaction, Customer)
         .join(Transaction, TransactionItem.transaction_id == Transaction.id)
         .join(Customer, Transaction.customer_id == Customer.id)
         .filter(Customer.owner_phone == owner_phone,
                 Transaction.is_voided.isnot(True),
                 TransactionItem.delivered_qty.isnot(None),
                 TransactionItem.delivered_qty < TransactionItem.quantity))
    if customer_id:
        q = q.filter(Customer.id == customer_id)
    if inventory_item_id:
        q = q.filter(TransactionItem.inventory_item_id == inventory_item_id)
    return q.order_by(Transaction.created_at.asc(), TransactionItem.id.asc()).all()


def _key(line):
    """What a customer's lines are grouped by: the stock item, or the name."""
    if line.inventory_item_id:
        return f"i:{line.inventory_item_id}"
    return "n:" + (line.product or "").strip().lower()


def reserved_by_item(db, owner_phone):
    """{inventory_item_id: quantity sold but still in the store}."""
    out = {}
    for line, _tx, _c in _open_lines(db, owner_phone):
        if line.inventory_item_id:
            out[line.inventory_item_id] = out.get(line.inventory_item_id, 0) + (
                float(line.quantity or 0) - float(line.delivered_qty or 0))
    return out


def reserved_for_item(db, owner_phone, inventory_item_id):
    return sum(float(l.quantity or 0) - float(l.delivered_qty or 0)
               for l, _t, _c in _open_lines(db, owner_phone, inventory_item_id=inventory_item_id))


def goods_to_deliver(db, owner_phone, customer_id=None):
    """Each customer's goods still to hand over, one row per product, oldest
    waiting first."""
    groups = {}
    for line, tx, cust in _open_lines(db, owner_phone, customer_id):
        k = (cust.id, _key(line))
        g = groups.get(k)
        if not g:
            g = groups[k] = {
                "customer_id": cust.id, "customer": (cust.name or "").title(),
                "customer_phone": cust.customer_phone, "key": _key(line),
                "product": (line.product or "").title(), "unit": line.unit,
                "bought": 0, "delivered": 0, "remaining": 0,
                "since": tx.created_at.isoformat() if tx.created_at else None,
                "sales": [],
            }
        g["bought"] += float(line.quantity or 0)
        g["delivered"] += float(line.delivered_qty or 0)
        g["remaining"] += float(line.quantity or 0) - float(line.delivered_qty or 0)
        g["sales"].append(tx.receipt_number or tx.id)
    rows = list(groups.values())
    for r in rows:
        r["bought"], r["delivered"], r["remaining"] = _num(r["bought"]), _num(r["delivered"]), _num(r["remaining"])
    return rows


def deliver_goods(db, owner_phone, user_id, customer_id, key, quantity, note=None):
    """Hand over `quantity` of a customer's goods, oldest sale first. Takes it
    out of stock and returns what the delivery note says. The caller commits."""
    try:
        quantity = float(quantity)
    except (TypeError, ValueError):
        raise DeliveryError("Enter how many were delivered.")
    if quantity <= 0:
        raise DeliveryError("Enter how many were delivered.")
    lines = [(l, t) for l, t, _c in _open_lines(db, owner_phone, customer_id) if _key(l) == key]
    if not lines:
        raise DeliveryError("Nothing is waiting to be delivered for this customer.")
    bought = sum(float(l.quantity or 0) for l, _t in lines)
    before = sum(float(l.delivered_qty or 0) for l, _t in lines)
    remaining = bought - before
    if quantity > remaining + 1e-9:
        raise DeliveryError(f"Only {_num(remaining)} left to deliver.")

    first = lines[0][0]
    item = (db.query(InventoryItem).filter(InventoryItem.id == first.inventory_item_id).first()
            if first.inventory_item_id else None)
    left = quantity
    for line, tx in lines:
        if left <= 0:
            break
        take = min(left, float(line.quantity or 0) - float(line.delivered_qty or 0))
        line.delivered_qty = float(line.delivered_qty or 0) + take
        left -= take
        if item is not None and item.quantity is not None:
            item.quantity = max(0.0, float(item.quantity or 0) - take)
            item.updated_at = _utcnow()
            db.add(InventoryMovement(
                owner_phone=owner_phone, item_id=item.id, movement_type="OUT",
                quantity=take, unit_price=line.unit_price, source_type="DELIVERY",
                source_id=tx.id, recorded_by_id=user_id,
                note=f"Delivered to customer — sale #{tx.receipt_number or tx.id}",
            ))
    db.add(GoodsDelivery(
        owner_phone=owner_phone, customer_id=customer_id, product=first.product,
        unit=first.unit, quantity=quantity, note=(note or "").strip() or None,
        recorded_by_id=user_id,
    ))
    db.flush()
    return {
        "product": (first.product or "").title(), "unit": first.unit,
        "delivered_now": _num(quantity), "bought": _num(bought),
        "delivered": _num(before + quantity), "remaining": _num(remaining - quantity),
        "note": (note or "").strip() or None,
    }


def _qty(n, unit):
    return f"{n:,} {unit}" if unit else f"{n:,}"


def delivery_note_text(business_name, customer_name, d):
    """The WhatsApp delivery note the customer gets after each trip."""
    lines = [
        f"*{business_name}* — delivery note",
        "",
        f"Hello {customer_name}, we delivered *{_qty(d['delivered_now'], d['unit'])}* of "
        f"{d['product']} today.",
        "",
        f"Bought: {_qty(d['bought'], d['unit'])}",
        f"Delivered so far: {_qty(d['delivered'], d['unit'])}",
        (f"*Still to deliver: {_qty(d['remaining'], d['unit'])}*" if d["remaining"]
         else "*All delivered* ✓"),
    ]
    if d.get("note"):
        lines += ["", f"Note: {d['note']}"]
    lines += ["", "Thank you."]
    return "\n".join(lines)


def goods_lines_text(rows):
    """'Cement — 75 bags still to deliver' lines for a statement."""
    return [f"{r['product']} — {_qty(r['remaining'], r['unit'])} still to deliver "
            f"(of {_qty(r['bought'], r['unit'])})" for r in rows]
