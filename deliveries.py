"""
Goods sold but not all handed over yet — a cement seller sells 100 bags, 60 go
out today, 40 wait in the store for the customer.

- A sale line records how many went out (TransactionItem.delivered_qty; NULL
  means all of it, which is every ordinary sale).
- Only what goes out leaves stock. What is still to deliver is either *kept
  aside* in the store for the customer (no one else can buy it: in store −
  kept aside = what can be sold) or just owed — the owner chose not to keep
  it aside, or it was sold short (more sold than was in store). Keeping aside
  is the owner's choice (Settings → keep goods aside; Add stock; Deliveries).
- Each later trip (a waybill, waybills.py) takes stock out against the customer's
  oldest open sale first, logged as an OUT movement with source DELIVERY and
  the sale as source_id — so voiding the sale returns it like any sale.
- The customer gets a delivery note: bought · delivered · still to deliver.

When it goes wrong — the customer wants the rest refunded, or brings goods
back — a numbered credit note (CN-0001) records it without touching the sale:
- undelivered goods cancelled: they stop being reserved, so they're sellable
  at once (they never left the store);
- delivered goods returned: back into stock if sellable, or kept out if damaged.
The money is either taken off what the customer owes (CREDIT) or handed back
(REFUND). Only the owner and authorised staff may do this.
"""
import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import func

from models import (
    CreditNote, Customer, InventoryItem, InventoryMovement, Transaction,
    TransactionItem,
)


class DeliveryError(ValueError):
    pass


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _num(q):
    q = float(q or 0)
    return int(q) if q == int(q) else round(q, 2)


def _delivered(line):
    """How many of a line went out: all of it for an ordinary sale."""
    return float(line.quantity or 0) if line.delivered_qty is None else float(line.delivered_qty or 0)


def _left(line):
    """Still to deliver: bought − delivered − cancelled."""
    if line.delivered_qty is None:
        return 0.0
    return max(0.0, float(line.quantity or 0) - float(line.delivered_qty or 0)
               - float(line.cancelled_qty or 0))


def _held(line):
    """Of what is still to deliver, how much is kept aside in the store.
    NULL = all of it (every sale made before keeping aside was a choice)."""
    left = _left(line)
    if line.held_qty is None:
        return left
    return max(0.0, min(left, float(line.held_qty or 0)))


def _returnable(line):
    return max(0.0, _delivered(line) - float(line.returned_qty or 0))


def _open_lines(db, owner_phone, customer_id=None, inventory_item_id=None, scope=None):
    """Sale lines with goods still to hand over, oldest first, as
    (line, sale, customer). `scope` is (branch_id, recorded_by_id) from
    web_common._scoped_read: branch staff see their branch's sales only,
    staff with no branch only what they recorded."""
    q = (db.query(TransactionItem, Transaction, Customer)
         .join(Transaction, TransactionItem.transaction_id == Transaction.id)
         .join(Customer, Transaction.customer_id == Customer.id)
         .filter(Customer.owner_phone == owner_phone,
                 Transaction.is_voided.isnot(True),
                 TransactionItem.delivered_qty.isnot(None),
                 TransactionItem.delivered_qty + func.coalesce(TransactionItem.cancelled_qty, 0)
                 < TransactionItem.quantity))
    if customer_id:
        q = q.filter(Customer.id == customer_id)
    if inventory_item_id:
        q = q.filter(TransactionItem.inventory_item_id == inventory_item_id)
    branch_id, recorded_by_id = scope or (None, None)
    if branch_id is not None:
        q = q.filter(Transaction.branch_id == branch_id)
    if recorded_by_id is not None:
        q = q.filter(Transaction.recorded_by_id == recorded_by_id)
    return q.order_by(Transaction.created_at.asc(), TransactionItem.id.asc()).all()


def _key(line):
    """What a customer's lines are grouped by: the stock item, or the name."""
    if line.inventory_item_id:
        return f"i:{line.inventory_item_id}"
    return "n:" + (line.product or "").strip().lower()


def reserved_by_item(db, owner_phone):
    """{inventory_item_id: quantity kept aside in the store for customers}."""
    out = {}
    for line, _tx, _c in _open_lines(db, owner_phone):
        if line.inventory_item_id and _held(line) > 0:
            out[line.inventory_item_id] = out.get(line.inventory_item_id, 0) + _held(line)
    return out


def reserved_for_item(db, owner_phone, inventory_item_id):
    return sum(_held(l) for l, _t, _c in _open_lines(db, owner_phone, inventory_item_id=inventory_item_id))


def owed_by_item(db, owner_phone):
    """{inventory_item_id: {"waiting": all still to deliver, "kept": of which
    kept aside, "customers": [(name, qty)]}} — the Inventory page's story."""
    out = {}
    for line, _tx, cust in _open_lines(db, owner_phone):
        if not line.inventory_item_id:
            continue
        o = out.setdefault(line.inventory_item_id, {"waiting": 0.0, "kept": 0.0, "customers": {}})
        o["waiting"] += _left(line)
        o["kept"] += _held(line)
        name = (cust.name or "").title()
        o["customers"][name] = o["customers"].get(name, 0) + _left(line)
    for o in out.values():
        o["customers"] = [{"name": n, "quantity": _num(q)} for n, q in o["customers"].items()]
        o["waiting"], o["kept"] = _num(o["waiting"]), _num(o["kept"])
    return out


def waiting_by_customer(db, owner_phone, scope=None):
    """{customer_id: quantity still to deliver} — the Customers "To deliver"
    column and the menu badge, like debtors for money."""
    out = {}
    for line, _tx, cust in _open_lines(db, owner_phone, scope=scope):
        out[cust.id] = out.get(cust.id, 0.0) + _left(line)
    return {k: _num(v) for k, v in out.items() if v > 0}


def free_in_store(db, owner_phone, item):
    """What of an item's stock is not kept aside for anyone."""
    if item is None or item.quantity is None:
        return None
    return max(0.0, float(item.quantity or 0) - reserved_for_item(db, owner_phone, item.id))


def goods_to_deliver(db, owner_phone, customer_id=None, scope=None):
    """Each customer's goods still to hand over, one row per product, oldest
    waiting first."""
    groups = {}
    for line, tx, cust in _open_lines(db, owner_phone, customer_id, scope=scope):
        k = (cust.id, _key(line))
        g = groups.get(k)
        if not g:
            g = groups[k] = {
                "customer_id": cust.id, "customer": (cust.name or "").title(),
                "customer_phone": cust.customer_phone, "key": _key(line),
                "product": (line.product or "").title(), "unit": line.unit,
                "bought": 0, "delivered": 0, "cancelled": 0, "remaining": 0, "kept": 0,
                "since": tx.created_at.isoformat() if tx.created_at else None,
                "sales": [], "inventory_item_id": line.inventory_item_id,
            }
        g["bought"] += float(line.quantity or 0)
        g["delivered"] += float(line.delivered_qty or 0)
        g["cancelled"] += float(line.cancelled_qty or 0)
        g["remaining"] += _left(line)
        g["kept"] += _held(line)
        g["sales"].append(tx.receipt_number or tx.id)
    rows = list(groups.values())
    # What can go out now: what is kept aside for them, plus whatever of the
    # stock is not kept for anyone. None = not a stocked item (no limit).
    items, free = {}, {}
    for r in rows:
        iid = r["inventory_item_id"]
        if iid and iid not in items:
            items[iid] = db.query(InventoryItem).filter(InventoryItem.id == iid).first()
            free[iid] = free_in_store(db, owner_phone, items[iid])
    for r in rows:
        f = free.get(r["inventory_item_id"])
        r["in_store_free"] = None if f is None else _num(f)
        r["can_send"] = (_num(r["remaining"]) if f is None
                         else _num(min(r["remaining"], r["kept"] + f)))
        for k in ("bought", "delivered", "cancelled", "remaining", "kept"):
            r[k] = _num(r[k])
    return rows


def set_kept_aside(db, owner_phone, customer_id, key, kept, scope=None):
    """Keep `kept` of a customer's goods aside in the store (0 = release them
    all, sellable to anyone again; they stay owed). Oldest sale first. Only
    goods actually in the store and not kept for someone else can be kept."""
    try:
        kept = float(kept)
    except (TypeError, ValueError):
        raise DeliveryError("Enter how many to keep aside.")
    if not math.isfinite(kept) or kept < 0:
        raise DeliveryError("Enter how many to keep aside.")
    lines = [l for l, _t, _c in _open_lines(db, owner_phone, customer_id, scope=scope) if _key(l) == key]
    if not lines:
        raise DeliveryError("Nothing is waiting to be delivered for this customer.")
    remaining = sum(_left(l) for l in lines)
    if kept > remaining + 1e-9:
        raise DeliveryError(f"They are only waiting for {_num(remaining)}.")
    now = sum(_held(l) for l in lines)
    item = (db.query(InventoryItem).filter(InventoryItem.id == lines[0].inventory_item_id).first()
            if lines[0].inventory_item_id else None)
    if kept > now + 1e-9 and item is not None and item.quantity is not None:
        free = free_in_store(db, owner_phone, item)
        if kept - now > free + 1e-9:
            raise DeliveryError(
                f"Only {_num(free)} {item.unit or ''} of {item.name.title()} in store is free to "
                f"keep aside.".replace("  ", " "))
    left = kept
    for line in lines:
        take = min(left, _left(line))
        line.held_qty = take
        left -= take
    db.flush()
    return {"kept": _num(kept), "remaining": _num(remaining)}


def _qty_or_fail(quantity, word="delivered"):
    try:
        quantity = float(quantity)
    except (TypeError, ValueError):
        raise DeliveryError(f"Enter how many were {word}.")
    if not math.isfinite(quantity) or quantity <= 0:      # NaN / Infinity from a crafted request
        raise DeliveryError(f"Enter how many were {word}.")
    return quantity


def deliver_goods(db, owner_phone, user_id, customer_id, key, quantity, note=None, scope=None):
    """Hand over `quantity` of a customer's goods, oldest sale first — a
    waybill with one product (waybills.py). Takes it out of stock and returns
    what the delivery note says. The caller commits."""
    from waybills import create_waybill
    quantity = _qty_or_fail(quantity)
    lines = [(l, t) for l, t, _c in _open_lines(db, owner_phone, customer_id, scope=scope) if _key(l) == key]
    if not lines:
        raise DeliveryError("Nothing is waiting to be delivered for this customer.")
    first = lines[0][0]
    bought = sum(float(l.quantity or 0) for l, _t in lines)
    before = sum(float(l.delivered_qty or 0) for l, _t in lines)
    cancelled = sum(float(l.cancelled_qty or 0) for l, _t in lines)
    remaining = sum(_left(l) for l, _t in lines)
    if quantity > remaining + 1e-9:
        raise DeliveryError(f"Only {_num(remaining)} left to deliver.")
    wb = create_waybill(db, owner_phone, user_id, customer_id=customer_id,
                        lines=[{"key": key, "quantity": quantity}], details={"note": note}, scope=scope)
    from waybills import format_waybill_number
    return {
        "product": (first.product or "").title(), "unit": first.unit,
        "delivered_now": _num(quantity), "bought": _num(bought),
        "delivered": _num(before + quantity), "cancelled": _num(cancelled),
        "remaining": _num(remaining - quantity),
        "note": (note or "").strip() or None,
        "waybill_id": wb.id, "waybill_number": format_waybill_number(wb.number),
    }


# ── Credit notes: cancel undelivered goods, take back delivered goods ─────────

def _next_cn_number(db, owner_phone):
    top = db.query(func.max(CreditNote.number)).filter(CreditNote.owner_phone == owner_phone).scalar()
    return int(top or 0) + 1


def format_cn_number(n):
    return f"CN-{int(n):04d}"


def _line_value(tx, line, qty):
    """What `qty` of a line was sold for, after its share of any discount off
    the whole sale — so a refund never hands back more than was paid."""
    gross = qty * int(line.unit_price or 0)
    discount = int(tx.discount_amount or 0)
    if discount:
        lines_total = sum(int(l.total or 0) for l in tx.items_cache) or 1
        gross = gross * (1 - discount / lines_total)
    # VAT added on top was paid too, so it comes back with the goods
    if getattr(tx, "vat_mode", None) == "add" and tx.vat_rate and not getattr(line, "vat_exempt", False):
        gross = gross * (1 + float(tx.vat_rate) / 100)
    return int(round(gross))


def _issue_credit_note(db, owner_phone, user_id, picks, kind, mode, reason, restock=None):
    """Record one credit note over (line, sale, qty) picks. Each sale gets its
    own negative transaction so a voided sale takes its credit note with it."""
    reason = (reason or "").strip()
    if not reason:
        raise DeliveryError("Say why — the reason is kept for any dispute later.")
    mode = (mode or "").upper()
    if mode not in ("CREDIT", "REFUND"):
        raise DeliveryError("Choose: take it off what they owe, or give the money back.")
    number = _next_cn_number(db, owner_phone)
    by_sale = {}
    for line, tx, qty in picks:
        by_sale.setdefault(tx.id, (tx, []))[1].append((line, qty))

    total, rows = 0, []
    for tx, entries in by_sale.values():
        if mode == "CREDIT" and not tx.customer_id:
            raise DeliveryError("A walk-in sale has no account to credit — give the money back instead.")
        tx.items_cache = db.query(TransactionItem).filter(TransactionItem.transaction_id == tx.id).all()
        values = [(line, qty, _line_value(tx, line, qty)) for line, qty in entries]
        amount = sum(v for _l, _q, v in values)
        what = ", ".join(f"{_num(q)}{(' ' + l.unit) if l.unit else ''} {(l.product or '').title()}"
                         for l, q, _v in values)
        label = "not delivered, cancelled" if kind == "UNDELIVERED" else "returned"
        credit_tx = Transaction(
            customer_id=tx.customer_id,
            # Off the balance → a negative charge; cash back → a negative sale.
            type="BUY" if mode == "CREDIT" else "SALE",
            amount=-amount,
            product=f"Credit note {format_cn_number(number)}: {what} {label}",
            recorded_by_id=user_id,
            message_id=f"credit-note-{uuid.uuid4()}",
            branch_id=tx.branch_id,
        )
        # The VAT inside what's refunded / credited comes off "VAT collected"
        if tx.vat_amount and tx.vat_rate:
            _r = float(tx.vat_rate)
            _vat_back = sum(v * _r / (100 + _r) for l, _q, v in values if not getattr(l, "vat_exempt", False))
            if _vat_back:
                credit_tx.vat_amount = -int(round(_vat_back))
                credit_tx.vat_rate, credit_tx.vat_mode = tx.vat_rate, tx.vat_mode
        db.add(credit_tx)
        db.flush()
        for line, qty, value in values:
            db.add(TransactionItem(
                transaction_id=credit_tx.id, product=line.product, quantity=-qty,
                unit=line.unit, unit_price=line.unit_price, total=-value,
                inventory_item_id=line.inventory_item_id,
            ))
            if kind == "UNDELIVERED":
                line.cancelled_qty = float(line.cancelled_qty or 0) + qty
            else:
                line.returned_qty = float(line.returned_qty or 0) + qty
                if restock == "SELLABLE" and line.inventory_item_id:
                    item = db.query(InventoryItem).filter(InventoryItem.id == line.inventory_item_id).first()
                    if item is not None and item.quantity is not None:
                        item.quantity = float(item.quantity or 0) + qty
                        item.updated_at = _utcnow()
                        db.add(InventoryMovement(
                            owner_phone=owner_phone, item_id=item.id, movement_type="IN",
                            quantity=qty, unit_price=line.unit_price, source_type="RETURN",
                            source_id=credit_tx.id, recorded_by_id=user_id,
                            note=f"Returned by customer — {format_cn_number(number)}",
                        ))
            db.add(CreditNote(
                owner_phone=owner_phone, number=number, customer_id=tx.customer_id,
                sale_tx_id=tx.id, sale_line_id=line.id, credit_tx_id=credit_tx.id,
                kind=kind, mode=mode, restock=restock if kind == "RETURN" else None,
                product=line.product, unit=line.unit, quantity=qty, amount=value,
                reason=reason, recorded_by_id=user_id,
            ))
            rows.append({"product": (line.product or "").title(), "unit": line.unit,
                         "quantity": _num(qty), "amount": value,
                         "sale": tx.receipt_number or tx.id})
        total += amount
    db.flush()
    return {"number": format_cn_number(number), "kind": kind, "mode": mode, "restock": restock,
            "reason": reason, "amount": total, "lines": rows}


def cancel_undelivered(db, owner_phone, user_id, customer_id, key, quantity, mode, reason, scope=None):
    """Cancel goods a customer bought that were never delivered — newest sale
    first, the purchase most likely being called off. They were never out of
    the store, so they simply stop being reserved and can be sold again."""
    quantity = _qty_or_fail(quantity, "cancelled")
    lines = [(l, t) for l, t, _c in _open_lines(db, owner_phone, customer_id, scope=scope) if _key(l) == key]
    if not lines:
        raise DeliveryError("Nothing is waiting to be delivered for this customer.")
    remaining = sum(_left(l) for l, _t in lines)
    if quantity > remaining + 1e-9:
        raise DeliveryError(f"Only {_num(remaining)} still to deliver — you can't cancel more.")
    bought = sum(float(l.quantity or 0) for l, _t in lines)
    delivered = sum(float(l.delivered_qty or 0) for l, _t in lines)
    cancelled_before = sum(float(l.cancelled_qty or 0) for l, _t in lines)
    picks, left = [], quantity
    for line, tx in reversed(lines):
        if left <= 0:
            break
        take = min(left, _left(line))
        picks.append((line, tx, take))
        left -= take
    note = _issue_credit_note(db, owner_phone, user_id, picks, "UNDELIVERED", mode, reason)
    note.update({
        "bought": _num(bought), "delivered": _num(delivered),
        "cancelled": _num(cancelled_before + quantity), "remaining": _num(remaining - quantity),
    })
    return note


def returnable_lines(db, owner_phone, tx_id):
    """A sale's lines that can still come back: delivered and not yet returned."""
    tx = _owned_sale(db, owner_phone, tx_id)
    out = []
    for line in db.query(TransactionItem).filter(TransactionItem.transaction_id == tx.id).all():
        if float(line.quantity or 0) <= 0:
            continue
        out.append({
            "line_id": line.id, "product": (line.product or "").title(), "unit": line.unit,
            "quantity": _num(line.quantity), "delivered": _num(_delivered(line)),
            "returned": _num(line.returned_qty or 0), "returnable": _num(_returnable(line)),
            "unit_price": int(line.unit_price or 0),
        })
    return {"sale_id": tx.id, "receipt_number": tx.receipt_number,
            "has_customer": bool(tx.customer_id), "lines": out}


def _owned_sale(db, owner_phone, tx_id):
    from reports import get_owner_transaction_query
    tx = (get_owner_transaction_query(db, owner_phone)
          .filter(Transaction.id == tx_id, Transaction.type.in_(("SALE", "BUY")),
                  Transaction.amount > 0).first())
    if not tx:
        raise DeliveryError("Sale not found.")
    return tx


def return_goods(db, owner_phone, user_id, tx_id, lines, mode, restock, reason):
    """Delivered goods brought back: `lines` is [{line_id, quantity}]."""
    tx = _owned_sale(db, owner_phone, tx_id)
    restock = (restock or "").upper()
    if restock not in ("SELLABLE", "DAMAGED"):
        raise DeliveryError("Say whether the goods can be sold again or are damaged.")
    by_id = {l.id: l for l in db.query(TransactionItem).filter(TransactionItem.transaction_id == tx.id).all()}
    picks = []
    for want in lines or []:
        line = by_id.get(int(want.get("line_id") or 0))
        if not line:
            raise DeliveryError("That item isn't on this sale.")
        try:
            qty = float(want.get("quantity") or 0)
        except (TypeError, ValueError):
            raise DeliveryError("Enter how many came back.")
        if not math.isfinite(qty) or qty <= 0:
            continue
        if qty > _returnable(line) + 1e-9:
            raise DeliveryError(f"Only {_num(_returnable(line))} {(line.product or '').title()} "
                                f"can come back — that's what was delivered and not returned yet.")
        picks.append((line, tx, qty))
    if not picks:
        raise DeliveryError("Enter how many came back.")
    return _issue_credit_note(db, owner_phone, user_id, picks, "RETURN", mode, reason, restock)


def credit_notes_for_sale(db, sale_tx_id):
    rows = (db.query(CreditNote).filter(CreditNote.sale_tx_id == sale_tx_id, CreditNote.voided_at.is_(None))
            .order_by(CreditNote.id.asc()).all())
    notes = {}
    for r in rows:
        n = notes.setdefault(r.number, {
            "number": format_cn_number(r.number), "kind": r.kind, "mode": r.mode,
            "restock": r.restock, "reason": r.reason, "amount": 0, "lines": [],
            "credit_tx_id": r.credit_tx_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
        n["amount"] += int(r.amount or 0)
        n["lines"].append({"product": (r.product or "").title(), "unit": r.unit, "quantity": _num(r.quantity)})
    return list(notes.values())


def credit_note_for_tx(db, credit_tx_id):
    rows = db.query(CreditNote).filter(CreditNote.credit_tx_id == credit_tx_id).all()
    if not rows:
        return None
    sale = db.query(Transaction).filter(Transaction.id == rows[0].sale_tx_id).first()
    return {
        "number": format_cn_number(rows[0].number), "kind": rows[0].kind, "mode": rows[0].mode,
        "restock": rows[0].restock, "reason": rows[0].reason,
        "sale_receipt": (sale.receipt_number or sale.id) if sale else None,
        "voided": rows[0].voided_at is not None,
    }


def on_transaction_voided(db, owner_phone, tx, user_id=None):
    """Keep credit notes true when something is voided.
    - A credit note's own transaction voided: the goods are owed / out again —
      cancelled goods are reserved again, returned sellable goods leave stock.
    - A sale voided: its credit notes go with it (otherwise the customer would
      be credited twice — the sale is gone and the credit note still counts)."""
    rows = db.query(CreditNote).filter(CreditNote.credit_tx_id == tx.id, CreditNote.voided_at.is_(None)).all()
    if rows:
        _undo_credit_rows(db, owner_phone, rows, user_id)
        return
    from waybills import on_sale_voided
    on_sale_voided(db, tx, user_id)
    for credit_tx_id, in (db.query(CreditNote.credit_tx_id)
                          .filter(CreditNote.sale_tx_id == tx.id, CreditNote.voided_at.is_(None))
                          .distinct().all()):
        ctx = db.query(Transaction).filter(Transaction.id == credit_tx_id).first()
        if ctx and not ctx.is_voided:
            ctx.is_voided = True
            ctx.void_reason = f"Sale #{tx.receipt_number or tx.id} voided"
            ctx.voided_by_id = user_id
            ctx.voided_at = _utcnow()
        _undo_credit_rows(db, owner_phone, db.query(CreditNote).filter(
            CreditNote.credit_tx_id == credit_tx_id, CreditNote.voided_at.is_(None)).all(), user_id)


def _undo_credit_rows(db, owner_phone, rows, user_id):
    for r in rows:
        line = db.query(TransactionItem).filter(TransactionItem.id == r.sale_line_id).first()
        if line is not None:
            if r.kind == "UNDELIVERED":
                line.cancelled_qty = max(0.0, float(line.cancelled_qty or 0) - float(r.quantity or 0))
            else:
                line.returned_qty = max(0.0, float(line.returned_qty or 0) - float(r.quantity or 0))
        if r.kind == "RETURN" and r.restock == "SELLABLE" and line is not None and line.inventory_item_id:
            item = db.query(InventoryItem).filter(InventoryItem.id == line.inventory_item_id).first()
            if item is not None and item.quantity is not None:
                item.quantity = max(0.0, float(item.quantity or 0) - float(r.quantity or 0))
                item.updated_at = _utcnow()
                db.add(InventoryMovement(
                    owner_phone=owner_phone, item_id=item.id, movement_type="OUT",
                    quantity=r.quantity, unit_price=line.unit_price, source_type="RETURN_REVERSAL",
                    source_id=r.credit_tx_id, recorded_by_id=user_id,
                    note=f"Credit note {format_cn_number(r.number)} voided",
                ))
        r.voided_at = _utcnow()


# ── Messages ──────────────────────────────────────────────────────────────────

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
    ]
    if d.get("cancelled"):
        lines.append(f"Cancelled: {_qty(d['cancelled'], d['unit'])}")
    lines.append(f"*Still to deliver: {_qty(d['remaining'], d['unit'])}*" if d["remaining"]
                 else "*All delivered* ✓")
    if d.get("note"):
        lines += ["", f"Note: {d['note']}"]
    lines += ["", "Thank you."]
    return "\n".join(lines)


def credit_note_text(business_name, customer_name, note):
    """The credit note the customer gets on WhatsApp."""
    what = "\n".join(f"• {_qty(l['quantity'], l['unit'])} {l['product']}" for l in note["lines"])
    head = ("not delivered — cancelled" if note["kind"] == "UNDELIVERED" else "returned to us")
    money = (f"*N{note['amount']:,} refunded to you.*" if note["mode"] == "REFUND"
             else f"*N{note['amount']:,} taken off your balance.*")
    lines = [
        f"*{business_name}* — credit note {note['number']}",
        "",
        f"Hello {customer_name}, these goods were {head}:",
        what,
        "",
        money,
    ]
    if note["kind"] == "UNDELIVERED" and "bought" in note:
        unit = note["lines"][0]["unit"] if note["lines"] else None
        lines += ["",
                  f"Bought: {_qty(note['bought'], unit)} · Delivered: {_qty(note['delivered'], unit)} · "
                  f"Cancelled: {_qty(note['cancelled'], unit)}",
                  (f"Still to deliver: {_qty(note['remaining'], unit)}" if note["remaining"]
                   else "Nothing left to deliver.")]
    lines += ["", f"Reason: {note['reason']}", "", "Thank you."]
    return "\n".join(lines)


def goods_lines_text(rows):
    """'Cement — 75 bags still to deliver' lines for a statement."""
    return [f"{r['product']} — {_qty(r['remaining'], r['unit'])} still to deliver "
            f"(of {_qty(r['bought'], r['unit'])})" for r in rows]
