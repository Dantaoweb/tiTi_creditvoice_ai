"""
Waybills / loading orders (WB-0001) — the paper the loaders and the driver
take with the goods. No prices; signed by whoever issued it, the driver, and
the customer on arrival.

A waybill is made from one of three places:
- a receipt   — the sale's lines;
- an invoice  — the invoice's lines (invoices can now go out in parts);
- a customer  — everything they are still waiting for, across their sales
                (Deliveries page).

Each line ticks how many go on this trip, never more than is in the store
for them (kept aside for them + stock not kept for anyone):
- goods still to deliver leave stock now, when the waybill is created
  (OUT movement: source DELIVERY against the sale, INVOICE against the
  invoice) — printing or sharing it again never takes them again;
- goods already handed over at the sale are only listed (paperwork).

Cancelling a waybill (owner and authorised staff) puts its goods back in the
store and back on the customer's still-to-deliver list. Voiding a sale returns
its stock the usual way and marks its waybills cancelled.
"""
import math
from datetime import datetime, timezone

from deliveries import (
    DeliveryError, _held, _key, _left, _num, _open_lines, free_in_store,
)
from models import (
    Customer, InventoryItem, InventoryMovement, Invoice, InvoiceItem, Transaction,
    TransactionItem, User, Waybill, WaybillLine,
)


class WaybillError(DeliveryError):
    pass


DETAIL_FIELDS = ("driver_name", "driver_phone", "vehicle", "loaders", "address", "note")


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def format_waybill_number(n):
    return f"WB-{int(n):04d}"


def _next_number(db, owner_phone):
    from sqlalchemy import func
    top = db.query(func.max(Waybill.number)).filter(Waybill.owner_phone == owner_phone).scalar()
    return int(top or 0) + 1


def _qty_in(want):
    try:
        q = float(want if want not in (None, "") else 0)
    except (TypeError, ValueError):
        raise WaybillError("Enter how many go on this waybill.")
    if not math.isfinite(q) or q < 0:
        raise WaybillError("Enter how many go on this waybill.")
    return q


def _item(db, inventory_item_id):
    if not inventory_item_id:
        return None
    it = db.query(InventoryItem).filter(InventoryItem.id == inventory_item_id).first()
    return it if (it is not None and it.quantity is not None and it.category != "service") else None


class _Store:
    """Stock not kept for anyone, per item, used up as lines are taken."""

    def __init__(self, db, owner_phone):
        self.db, self.owner_phone, self.free = db, owner_phone, {}

    def get(self, item):
        if item.id not in self.free:
            self.free[item.id] = free_in_store(self.db, self.owner_phone, item)
        return self.free[item.id]

    def use(self, item, qty):
        self.free[item.id] = max(0.0, self.get(item) - qty)


def _take_out(db, owner_phone, item, qty, unit_price, source_type, source_id, user_id, note):
    item.quantity = max(0.0, float(item.quantity or 0) - qty)
    item.updated_at = _utcnow()
    mv = InventoryMovement(
        owner_phone=owner_phone, item_id=item.id, movement_type="OUT", quantity=qty,
        unit_price=unit_price, source_type=source_type, source_id=source_id,
        recorded_by_id=user_id, note=note,
    )
    db.add(mv)
    db.flush()
    return mv


def _short(item, can):
    return WaybillError(
        f"Only {_num(can)} {item.unit or ''} of {item.name.title()} can go out now — that's what is "
        f"in the store for this customer. Add the new stock first.".replace("  ", " "))


# ── Sale lines ────────────────────────────────────────────────────────────────

def _send_sale_line(db, owner_phone, user_id, store, line, tx, qty, wb_number):
    """Send `qty` of a sale line still to deliver: kept-aside goods first,
    then stock not kept for anyone. Returns the OUT movement (or None)."""
    left = _left(line)
    if qty > left + 1e-9:
        raise WaybillError(f"Only {_num(left)} {(line.product or '').title()} still to deliver.")
    item = _item(db, line.inventory_item_id)
    held = _held(line)
    mv = None
    if item is not None:
        from_free = max(0.0, qty - held)
        if from_free > store.get(item) + 1e-9:
            raise _short(item, held + store.get(item))
        store.use(item, from_free)
        mv = _take_out(db, owner_phone, item, qty, line.unit_price, "DELIVERY", tx.id, user_id,
                       f"Waybill {format_waybill_number(wb_number)} — sale #{tx.receipt_number or tx.id}")
    if line.held_qty is not None:
        line.held_qty = max(0.0, float(line.held_qty or 0) - qty)
    line.delivered_qty = float(line.delivered_qty or 0) + qty
    return mv


def sale_waybill_lines(db, owner_phone, tx):
    """A receipt's lines as the waybill form shows them."""
    store = _Store(db, owner_phone)
    out = []
    for line in (db.query(TransactionItem).filter(TransactionItem.transaction_id == tx.id)
                 .order_by(TransactionItem.id.asc()).all()):
        if float(line.quantity or 0) <= 0:
            continue
        row = {"line_id": line.id, "product": (line.product or "").title(), "unit": line.unit,
               "bought": _num(line.quantity)}
        if line.delivered_qty is None:
            # Handed over at the sale: the waybill only lists it
            row.update({"handed_over": True, "to_deliver": 0, "max": _num(line.quantity)})
        else:
            left = _left(line)
            item = _item(db, line.inventory_item_id)
            can = left if item is None else min(left, _held(line) + store.get(item))
            row.update({"handed_over": False, "to_deliver": _num(left), "max": _num(can),
                        "kept": _num(_held(line))})
        out.append(row)
    return out


def _from_sale(db, owner_phone, user_id, wb, tx, lines):
    if tx.is_voided:
        raise WaybillError("This sale was voided.")
    by_id = {l.id: l for l in db.query(TransactionItem).filter(TransactionItem.transaction_id == tx.id).all()}
    store = _Store(db, owner_phone)
    made = []
    for want in lines or []:
        line = by_id.get(int(want.get("line_id") or 0))
        if not line or float(line.quantity or 0) <= 0:
            raise WaybillError("That item isn't on this sale.")
        qty = _qty_in(want.get("quantity"))
        if qty <= 0:
            continue
        if line.delivered_qty is None:
            if qty > float(line.quantity or 0) + 1e-9:
                raise WaybillError(f"Only {_num(line.quantity)} {(line.product or '').title()} were bought.")
            made.append(WaybillLine(product=line.product, unit=line.unit, quantity=qty,
                                    sale_line_id=line.id, moved=False))
            continue
        mv = _send_sale_line(db, owner_phone, user_id, store, line, tx, qty, wb.number)
        made.append(WaybillLine(product=line.product, unit=line.unit, quantity=qty,
                                sale_line_id=line.id, movement_id=mv.id if mv else None, moved=True))
    return made


def _from_customer(db, owner_phone, user_id, wb, customer_id, lines, scope):
    """A customer's goods still to deliver, by product, oldest sale first."""
    open_lines = _open_lines(db, owner_phone, customer_id, scope=scope)
    store = _Store(db, owner_phone)
    made = []
    for want in lines or []:
        key = want.get("key")
        qty = _qty_in(want.get("quantity"))
        if qty <= 0:
            continue
        group = [(l, t) for l, t, _c in open_lines if _key(l) == key]
        if not group:
            raise WaybillError("Nothing is waiting to be delivered for this customer.")
        remaining = sum(_left(l) for l, _t in group)
        if qty > remaining + 1e-9:
            raise WaybillError(f"Only {_num(remaining)} {(group[0][0].product or '').title()} still to deliver.")
        item = _item(db, group[0][0].inventory_item_id)
        if item is not None:
            can = min(remaining, sum(_held(l) for l, _t in group) + store.get(item))
            if qty > can + 1e-9:
                raise _short(item, can)
        left = qty
        for line, tx in group:
            if left <= 0:
                break
            take = min(left, _left(line))
            if take <= 0:
                continue
            mv = _send_sale_line(db, owner_phone, user_id, store, line, tx, take, wb.number)
            made.append(WaybillLine(product=line.product, unit=line.unit, quantity=take,
                                    sale_line_id=line.id, movement_id=mv.id if mv else None, moved=True))
            left -= take
    return made


# ── Invoice lines ─────────────────────────────────────────────────────────────

def _invoice_left(inv, r):
    if inv.delivered_at and r.delivered_qty is None:
        return 0.0                                   # marked delivered in one go
    return max(0.0, float(r.quantity or 0) - float(r.delivered_qty or 0))


def _invoice_units(item, r, qty):
    """Stock units `qty` of an invoice line takes (pieces, halves…)."""
    if r.sold_unit and item.retail_unit and item.retail_per_base \
            and r.sold_unit.lower() == item.retail_unit.lower():
        return qty / item.retail_per_base
    return qty * float(r.fraction or 1.0)


def _invoice_item(db, inv, r):
    item = _item(db, r.inventory_item_id)
    if item is None and r.product:
        from inventory_suppliers import find_matching_inventory_item
        found = find_matching_inventory_item(db, inv.owner_phone, r.product, r.unit)
        item = found if (found is not None and found.quantity is not None and found.category != "service") else None
    return item


def invoice_waybill_lines(db, inv):
    store = _Store(db, inv.owner_phone)
    out = []
    for r in db.query(InvoiceItem).filter(InvoiceItem.invoice_id == inv.id).order_by(InvoiceItem.id.asc()).all():
        left = _invoice_left(inv, r)
        item = _invoice_item(db, inv, r)
        can = left
        if item is not None and left > 0:
            per = _invoice_units(item, r, 1) or 1
            can = min(left, store.get(item) / per)
            can = math.floor(can + 1e-9) if not r.sold_unit and float(r.fraction or 1) == 1 else can
        out.append({"line_id": r.id, "product": (r.product or "").title(), "unit": r.sold_unit or r.unit,
                    "bought": _num(r.quantity), "handed_over": left <= 0, "to_deliver": _num(left),
                    "max": _num(can) if left > 0 else _num(r.quantity)})
    return out


def invoice_delivered_any(db, inv):
    """Has any of the invoice gone out (marked delivered, or on a waybill)?"""
    if inv.delivered_at:
        return True
    return db.query(InvoiceItem).filter(InvoiceItem.invoice_id == inv.id,
                                        InvoiceItem.delivered_qty > 0).first() is not None


def _from_invoice(db, owner_phone, user_id, wb, inv, lines):
    if inv.cancelled_at:
        raise WaybillError("This invoice was cancelled.")
    if inv.is_quote:
        raise WaybillError("This is still a quotation — mark it accepted first.")
    by_id = {r.id: r for r in db.query(InvoiceItem).filter(InvoiceItem.invoice_id == inv.id).all()}
    store = _Store(db, owner_phone)
    made = []
    for want in lines or []:
        r = by_id.get(int(want.get("line_id") or 0))
        if not r:
            raise WaybillError("That item isn't on this invoice.")
        qty = _qty_in(want.get("quantity"))
        if qty <= 0:
            continue
        left = _invoice_left(inv, r)
        if left <= 0:
            if qty > float(r.quantity or 0) + 1e-9:
                raise WaybillError(f"Only {_num(r.quantity)} {(r.product or '').title()} on this invoice.")
            made.append(WaybillLine(product=r.product, unit=r.sold_unit or r.unit, quantity=qty,
                                    invoice_line_id=r.id, moved=False))
            continue
        if qty > left + 1e-9:
            raise WaybillError(f"Only {_num(left)} {(r.product or '').title()} still to deliver.")
        item = _invoice_item(db, inv, r)
        mv = None
        if item is not None:
            units = _invoice_units(item, r, qty)
            if units > store.get(item) + 1e-9:
                per = _invoice_units(item, r, 1) or 1
                raise _short(item, store.get(item) / per)
            store.use(item, units)
            mv = _take_out(db, owner_phone, item, units, r.unit_price, "INVOICE", inv.id, user_id,
                           f"Waybill {format_waybill_number(wb.number)} — invoice")
        r.delivered_qty = float(r.delivered_qty or 0) + qty
        made.append(WaybillLine(product=r.product, unit=r.sold_unit or r.unit, quantity=qty,
                                invoice_line_id=r.id, movement_id=mv.id if mv else None, moved=True))
    # All of it out: the invoice is delivered, as if marked in one go
    rows = list(by_id.values())
    if rows and not inv.delivered_at and all(_invoice_left(inv, r) <= 1e-9 for r in rows):
        inv.delivered_at = _utcnow()
        inv.delivered_by_id = user_id
    return made


def deliver_rest_of_invoice(db, inv, user_id):
    """"Mark delivered" after some went on waybills: take out only the rest."""
    from invoices import format_invoice_number
    for r in db.query(InvoiceItem).filter(InvoiceItem.invoice_id == inv.id).all():
        left = _invoice_left(inv, r)
        if left <= 0:
            continue
        item = _invoice_item(db, inv, r)
        if item is not None:
            _take_out(db, inv.owner_phone, item, _invoice_units(item, r, left), r.unit_price,
                      "INVOICE", inv.id, user_id, f"Delivered on {format_invoice_number(inv.number)}")
        r.delivered_qty = float(r.quantity or 0)


# ── Create / cancel ───────────────────────────────────────────────────────────

def _clean_details(details):
    out = {}
    for f in DETAIL_FIELDS:
        v = (details or {}).get(f)
        v = str(v).strip()[:300] if v is not None else ""
        out[f] = v or None
    return out


def create_waybill(db, owner_phone, user_id, *, tx=None, inv=None, customer_id=None,
                   lines=None, details=None, scope=None):
    """Make a waybill. Exactly one of `tx` (a sale), `inv` (an invoice) or
    `customer_id` (their goods still to deliver). The caller commits."""
    if sum(x is not None for x in (tx, inv, customer_id)) != 1:
        raise WaybillError("Make the waybill from a receipt, an invoice or a customer.")
    wb = Waybill(owner_phone=owner_phone, number=_next_number(db, owner_phone),
                 created_by_id=user_id, **_clean_details(details))
    if tx is not None:
        wb.transaction_id, wb.customer_id, wb.branch_id = tx.id, tx.customer_id, tx.branch_id
    elif inv is not None:
        wb.invoice_id, wb.customer_id, wb.branch_id = inv.id, inv.customer_id, inv.branch_id
    else:
        wb.customer_id = customer_id
    db.add(wb)
    db.flush()
    if tx is not None:
        made = _from_sale(db, owner_phone, user_id, wb, tx, lines)
    elif inv is not None:
        made = _from_invoice(db, owner_phone, user_id, wb, inv, lines)
    else:
        made = _from_customer(db, owner_phone, user_id, wb, customer_id, lines, scope)
    if not made:
        raise WaybillError("Tick at least one item and say how many go on this waybill.")
    if customer_id is not None:
        # One sale only → link it, so the receipt lists this waybill
        sales = {db.query(TransactionItem.transaction_id).filter(TransactionItem.id == l.sale_line_id).scalar()
                 for l in made}
        if len(sales) == 1:
            wb.transaction_id = next(iter(sales))
        # Its branch, when all its sales are from one — so branch staff see it
        branches = {b for b, in db.query(Transaction.branch_id).filter(Transaction.id.in_(sales)).all()}
        if len(branches) == 1:
            wb.branch_id = branches.pop()
    for l in made:
        l.waybill_id = wb.id
        db.add(l)
    db.flush()
    return wb


def cancel_waybill(db, owner_phone, user_id, wb, reason):
    """The goods did not go: back in the store and back on the customer's
    still-to-deliver list (kept aside again when Settings say so)."""
    from app_settings import business_setting
    if wb.cancelled_at:
        raise WaybillError("This waybill is already cancelled.")
    reason = (reason or "").strip()
    if not reason:
        raise WaybillError("Say why — the reason is kept on the waybill.")
    keep = business_setting(db, owner_phone, "keep_aside")
    for l in db.query(WaybillLine).filter(WaybillLine.waybill_id == wb.id).all():
        if not l.moved:
            continue
        mv = db.query(InventoryMovement).filter(InventoryMovement.id == l.movement_id).first() \
            if l.movement_id else None
        if l.sale_line_id:
            line = db.query(TransactionItem).filter(TransactionItem.id == l.sale_line_id).first()
            sale = db.query(Transaction).filter(Transaction.id == line.transaction_id).first() if line else None
            if sale is None or sale.is_voided:
                continue                     # the void already returned its stock
            line.delivered_qty = max(0.0, float(line.delivered_qty or 0) - float(l.quantity or 0))
            if line.held_qty is not None and keep and mv is not None:
                line.held_qty = float(line.held_qty or 0) + float(l.quantity or 0)
        elif l.invoice_line_id:
            r = db.query(InvoiceItem).filter(InvoiceItem.id == l.invoice_line_id).first()
            if r is not None:
                inv = db.query(Invoice).filter(Invoice.id == r.invoice_id).first()
                if inv is not None and inv.delivered_at and r.delivered_qty is None:
                    r.delivered_qty = float(r.quantity or 0)
                r.delivered_qty = max(0.0, float(r.delivered_qty or 0) - float(l.quantity or 0))
                if inv is not None:
                    inv.delivered_at, inv.delivered_by_id = None, None
        if mv is not None and mv.source_type in ("DELIVERY", "INVOICE"):
            item = db.query(InventoryItem).filter(InventoryItem.id == mv.item_id).first()
            mv.source_type = f"{mv.source_type}_CANCELLED"      # a later void must not return it again
            if item is not None:
                item.quantity = float(item.quantity or 0) + float(mv.quantity or 0)
                item.updated_at = _utcnow()
                db.add(InventoryMovement(
                    owner_phone=owner_phone, item_id=item.id, movement_type="IN",
                    quantity=mv.quantity, unit_price=mv.unit_price, source_type="WAYBILL_CANCELLED",
                    source_id=wb.id, recorded_by_id=user_id,
                    note=f"Waybill {format_waybill_number(wb.number)} cancelled — {reason}"[:300],
                ))
    wb.cancelled_at = _utcnow()
    wb.cancelled_by_id = user_id
    wb.cancel_reason = reason[:300]
    db.flush()
    return wb


def on_sale_voided(db, tx, user_id=None):
    """A voided sale takes its waybills with it (its stock comes back through
    the void). The caller commits."""
    line_ids = [i for i, in db.query(TransactionItem.id).filter(TransactionItem.transaction_id == tx.id).all()]
    if not line_ids:
        return
    wb_ids = {w for w, in db.query(WaybillLine.waybill_id).filter(WaybillLine.sale_line_id.in_(line_ids)).all()}
    for wb in db.query(Waybill).filter(Waybill.id.in_(wb_ids), Waybill.cancelled_at.is_(None)).all() if wb_ids else []:
        others = (db.query(WaybillLine).join(TransactionItem, WaybillLine.sale_line_id == TransactionItem.id)
                  .filter(WaybillLine.waybill_id == wb.id, TransactionItem.transaction_id != tx.id).first())
        if others is None:
            wb.cancelled_at, wb.cancelled_by_id = _utcnow(), user_id
            wb.cancel_reason = f"Sale #{tx.receipt_number or tx.id} voided"


# ── Reading ───────────────────────────────────────────────────────────────────

def waybill_summary(db, wb):
    lines = db.query(WaybillLine).filter(WaybillLine.waybill_id == wb.id).order_by(WaybillLine.id.asc()).all()
    cust = db.query(Customer).filter(Customer.id == wb.customer_id).first() if wb.customer_id else None
    return {
        "id": wb.id, "number": format_waybill_number(wb.number),
        "customer": (cust.name or "").title() if cust else None,
        "created_at": wb.created_at.isoformat() if wb.created_at else None,
        "cancelled": wb.cancelled_at is not None,
        "transaction_id": wb.transaction_id, "invoice_id": wb.invoice_id,
        "driver_name": wb.driver_name, "vehicle": wb.vehicle,
        "what": ", ".join(f"{_num(l.quantity)}{(' ' + l.unit) if l.unit else ''} {(l.product or '').title()}"
                          for l in _grouped(lines)),
    }


def _grouped(lines):
    """One row per product (a customer's waybill can draw on several sales)."""
    out = {}
    for l in lines:
        k = ((l.product or "").strip().lower(), (l.unit or "").lower())
        if k in out:
            out[k].quantity = float(out[k].quantity or 0) + float(l.quantity or 0)
        else:
            out[k] = WaybillLine(product=l.product, unit=l.unit, quantity=float(l.quantity or 0), moved=l.moved)
    return list(out.values())


def list_waybills(db, owner_phone, *, tx_id=None, invoice_id=None, customer_id=None,
                  branch_id=None, limit=100):
    q = db.query(Waybill).filter(Waybill.owner_phone == owner_phone)
    if tx_id is not None:
        line_ids = [i for i, in db.query(TransactionItem.id).filter(TransactionItem.transaction_id == tx_id).all()]
        wb_ids = {w for w, in db.query(WaybillLine.waybill_id).filter(WaybillLine.sale_line_id.in_(line_ids)).all()} \
            if line_ids else set()
        q = q.filter((Waybill.transaction_id == tx_id) | Waybill.id.in_(wb_ids or {0}))
    if invoice_id is not None:
        q = q.filter(Waybill.invoice_id == invoice_id)
    if customer_id is not None:
        q = q.filter(Waybill.customer_id == customer_id)
    if branch_id is not None:
        q = q.filter(Waybill.branch_id == branch_id)
    return [waybill_summary(db, wb) for wb in q.order_by(Waybill.id.desc()).limit(limit).all()]


def last_details(db, owner_phone, customer_id=None):
    """Fill the form from the last waybill (this customer's for the address)."""
    last = (db.query(Waybill).filter(Waybill.owner_phone == owner_phone)
            .order_by(Waybill.id.desc()).first())
    out = {"driver_name": None, "driver_phone": None, "vehicle": None, "loaders": None, "address": None}
    if last:
        out.update(driver_name=last.driver_name, driver_phone=last.driver_phone,
                   vehicle=last.vehicle, loaders=last.loaders)
    if customer_id:
        mine = (db.query(Waybill).filter(Waybill.owner_phone == owner_phone, Waybill.customer_id == customer_id,
                                         Waybill.address.isnot(None))
                .order_by(Waybill.id.desc()).first())
        if mine:
            out["address"] = mine.address
    return out


def waybill_document(db, wb):
    """Everything the printed waybill shows — no prices."""
    from invoices import _business_header, format_invoice_number
    doc = _business_header(db, wb.owner_phone, wb.branch_id)
    cust = db.query(Customer).filter(Customer.id == wb.customer_id).first() if wb.customer_id else None
    creator = db.query(User).filter(User.id == wb.created_by_id).first() if wb.created_by_id else None
    lines = db.query(WaybillLine).filter(WaybillLine.waybill_id == wb.id).order_by(WaybillLine.id.asc()).all()
    ref = None
    if wb.transaction_id:
        tx = db.query(Transaction).filter(Transaction.id == wb.transaction_id).first()
        ref = f"Receipt #{tx.receipt_number or tx.id}" if tx else None
    elif wb.invoice_id:
        inv = db.query(Invoice).filter(Invoice.id == wb.invoice_id).first()
        ref = format_invoice_number(inv.number) if inv else None
    else:
        sales = sorted({t.receipt_number or t.id for t in (
            db.query(Transaction).join(TransactionItem, TransactionItem.transaction_id == Transaction.id)
            .filter(TransactionItem.id.in_([l.sale_line_id for l in lines if l.sale_line_id] or [0])).all())})
        ref = ("Receipt " + ", ".join(f"#{s}" for s in sales)) if sales else None
    doc.update({
        "id": wb.id, "number": format_waybill_number(wb.number), "ref": ref,
        "transaction_id": wb.transaction_id, "invoice_id": wb.invoice_id,
        "customer": {"id": cust.id, "name": (cust.name or "").title(), "phone": cust.customer_phone} if cust else None,
        **{f: getattr(wb, f) for f in DETAIL_FIELDS},
        "issued_by": (creator.name or "").title() if creator else None,
        "created_at": wb.created_at.isoformat() if wb.created_at else None,
        "cancelled_at": wb.cancelled_at.isoformat() if wb.cancelled_at else None,
        "cancel_reason": wb.cancel_reason,
        "lines": [{"product": (l.product or "").title(), "unit": l.unit, "quantity": _num(l.quantity),
                   "handed_over": not l.moved} for l in _grouped(lines)],
    })
    doc["still_to_deliver"] = _still_after(db, wb, cust)
    return doc


def _still_after(db, wb, cust):
    """What the customer is still waiting for, per product on this waybill."""
    if not cust:
        return []
    names = {(l.product or "").strip().lower() for l in
             db.query(WaybillLine).filter(WaybillLine.waybill_id == wb.id, WaybillLine.moved.is_(True)).all()}
    if wb.invoice_id:
        inv = db.query(Invoice).filter(Invoice.id == wb.invoice_id).first()
        rows = db.query(InvoiceItem).filter(InvoiceItem.invoice_id == wb.invoice_id).all() if inv else []
        return [{"product": (r.product or "").title(), "unit": r.sold_unit or r.unit,
                 "quantity": _num(_invoice_left(inv, r))}
                for r in rows if (r.product or "").strip().lower() in names and _invoice_left(inv, r) > 0]
    out = {}
    for line, _t, _c in _open_lines(db, wb.owner_phone, cust.id):
        n = (line.product or "").strip().lower()
        if n in names:
            o = out.setdefault(n, {"product": (line.product or "").title(), "unit": line.unit, "quantity": 0.0})
            o["quantity"] += _left(line)
    return [dict(o, quantity=_num(o["quantity"])) for o in out.values()]


def _q(n, unit):
    return f"{n:,} {unit}" if unit else f"{n:,}"


def waybill_note_text(doc):
    """The WhatsApp note the customer gets: what is on its way."""
    lines = [f"*{doc.get('biz_name') or 'Our business'}* — waybill {doc['number']}", ""]
    who = (doc.get("customer") or {}).get("name") or "there"
    lines.append(f"Hello {who}, these goods are on their way to you:")
    for l in doc["lines"]:
        lines.append(f"• {_q(l['quantity'], l['unit'])} {l['product']}")
    if doc.get("driver_name") or doc.get("vehicle"):
        lines += ["", "Driver: " + " · ".join(x for x in (doc.get("driver_name"), doc.get("driver_phone"),
                                                         doc.get("vehicle")) if x)]
    if doc["still_to_deliver"]:
        lines += ["", "*Still to deliver:*"]
        lines += [f"• {_q(s['quantity'], s['unit'])} {s['product']}" for s in doc["still_to_deliver"]]
    elif any(not l["handed_over"] for l in doc["lines"]):
        lines += ["", "*All delivered* ✓"]
    if doc.get("ref"):
        lines += ["", f"For {doc['ref']}."]
    lines += ["", "Please check the goods and sign the waybill. Thank you."]
    return "\n".join(lines)
