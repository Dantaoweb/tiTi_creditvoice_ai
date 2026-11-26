"""
Stock moved between branches (TR-0001).

- The goods leave the sending branch when the transfer is made.
- The receiving branch gets them straight away, unless the owner chose on the
  Branches page that the receiving branch confirms ("transfer_confirm"). Then
  the transfer is "on the way" until someone there taps Received and says what
  actually arrived; a shortfall is recorded as missing on the way (it shows in
  the Removed stock report, at cost).
- A product the receiving branch doesn't have yet is made there, copying the
  name, unit, prices, category and barcode — nobody types it again.
- The goods travel at the sending branch's cost price; the receiving branch's
  cost is averaged with what it already holds, so profit stays right in both.
- Every move is in each product's stock movements: "Sent to Lekki · TR-0001",
  "Came from Ikeja · TR-0001".

Who: the owner and admins who see the whole business, between any branches;
an admin kept to their branch only sends from it, and receives into it.
"""
import math

from sqlalchemy import func

from models import Branch, InventoryItem, InventoryMovement, StockTransfer, StockTransferLine, User, utcnow


class TransferError(ValueError):
    pass


def format_number(n):
    return f"TR-{int(n):04d}"


def _next_number(db, owner_phone):
    top = db.query(func.max(StockTransfer.number)).filter(StockTransfer.owner_phone == owner_phone).scalar()
    return int(top or 0) + 1


def _num(x):
    x = float(x or 0)
    return int(x) if x == int(x) else round(x, 3)


def _qty(text):
    try:
        q = float(text)
    except (TypeError, ValueError):
        raise TransferError("Enter how many of each product to send.")
    if not math.isfinite(q) or q < 0:
        raise TransferError("Enter how many of each product to send.")
    return q


def _branch(db, owner_phone, branch_id):
    b = db.query(Branch).filter(Branch.id == branch_id, Branch.owner_phone == owner_phone).first() \
        if branch_id is not None else None
    if not b:
        raise TransferError("Pick two of your branches.")
    return b


def _twin_in(db, owner_phone, item, branch_id):
    """The same product in the other branch, if it has it."""
    from similar_products import check_new_product
    twins = check_new_product(db, owner_phone, item.name, item.unit, branch_id)["exact"]
    for t in twins:   # a removed product there doesn't count — the goods would vanish into it
        found = db.query(InventoryItem).filter(InventoryItem.id == t["id"]).first()
        if found and found.removed_at is None:
            return found
    return None


_COPY = ("name", "unit", "cost_price", "selling_price", "low_stock_alert", "retail_unit", "retail_per_base",
         "retail_price", "wholesale_price", "wholesale_min_qty", "category", "vat_exempt", "usual_supplier",
         "attributes_json", "barcode")


def _copy_to(db, item, branch_id):
    new = InventoryItem(owner_phone=item.owner_phone, branch_id=branch_id, quantity=0.0, is_available=True,
                        **{f: getattr(item, f) for f in _COPY if hasattr(item, f)})
    db.add(new)
    db.flush()
    return new


def create_transfer(db, owner_phone, user, from_branch_id, to_branch_id, lines,
                    carried_by=None, carrier_phone=None, note=None, confirm=False):
    """Send stock. `lines` = [{"item_id", "quantity"}]. Returns the transfer."""
    src = _branch(db, owner_phone, from_branch_id)
    dst = _branch(db, owner_phone, to_branch_id)
    if src.id == dst.id:
        raise TransferError("The two branches must be different.")
    wanted = {}
    for line in lines or []:
        q = _qty(line.get("quantity"))
        if q > 0:
            wanted[int(line.get("item_id") or 0)] = wanted.get(int(line.get("item_id") or 0), 0) + q
    if not wanted:
        raise TransferError("Add at least one product and how many to send.")
    items = {i.id: i for i in db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone, InventoryItem.id.in_(list(wanted))).all()}
    for item_id, q in wanted.items():
        item = items.get(item_id)
        if not item or item.branch_id != src.id or item.removed_at is not None:
            raise TransferError(f"That product isn't in {src.name}'s stock.")
        if item.quantity is None:
            raise TransferError(f"{item.name.title()} is a service — there's no stock to send.")
        if q > float(item.quantity or 0) + 1e-9:
            raise TransferError(f"{src.name} has only {_num(item.quantity)}{' ' + item.unit if item.unit else ''} "
                                f"of {item.name.title()}.")

    tr = StockTransfer(owner_phone=owner_phone, number=_next_number(db, owner_phone),
                       from_branch_id=src.id, to_branch_id=dst.id, status="on_the_way",
                       carried_by=(carried_by or "").strip()[:80] or None,
                       carrier_phone=(carrier_phone or "").strip()[:30] or None,
                       note=(note or "").strip()[:300] or None,
                       created_by_id=user.id if user else None)
    db.add(tr)
    db.flush()
    num = format_number(tr.number)
    for item_id, q in wanted.items():
        item = items[item_id]
        to_item = _twin_in(db, owner_phone, item, dst.id) or _copy_to(db, item, dst.id)
        item.quantity = float(item.quantity or 0) - q
        db.add(InventoryMovement(owner_phone=owner_phone, item_id=item.id, movement_type="OUT", quantity=q,
                                 unit_price=item.cost_price, source_type="TRANSFER_OUT", source_id=tr.id,
                                 note=f"Sent to {dst.name} · {num}",
                                 recorded_by_id=user.id if user else None))
        db.add(StockTransferLine(transfer_id=tr.id, from_item_id=item.id, to_item_id=to_item.id,
                                 product=item.name, unit=item.unit, qty_sent=q, unit_cost=item.cost_price))
    db.flush()
    if not confirm:
        receive(db, tr, user, None)
    return tr


def _lines(db, tr):
    return db.query(StockTransferLine).filter(StockTransferLine.transfer_id == tr.id) \
        .order_by(StockTransferLine.id.asc()).all()


def receive(db, tr, user, received, note=None):
    """The goods are in. `received` = {line_id: quantity that arrived}; None or a
    missing line = all of it. A shortfall is recorded as missing on the way."""
    if tr.status != "on_the_way":
        raise TransferError("This transfer is already settled.")
    src = db.query(Branch).filter(Branch.id == tr.from_branch_id).first()
    num = format_number(tr.number)
    by = user.id if user else None
    for line in _lines(db, tr):
        got = line.qty_sent
        if received and line.id in received:
            got = min(_qty(received[line.id]), line.qty_sent)
        item = db.query(InventoryItem).filter(InventoryItem.id == line.to_item_id).first()
        if not item:
            continue
        old_q = max(0.0, float(item.quantity or 0))
        if line.unit_cost and got > 0:
            item.cost_price = round((old_q * item.cost_price + got * line.unit_cost) / (old_q + got)) \
                if (item.cost_price and old_q > 0) else line.unit_cost
        item.quantity = float(item.quantity or 0) + got
        db.add(InventoryMovement(owner_phone=tr.owner_phone, item_id=item.id, movement_type="IN",
                                 quantity=line.qty_sent, unit_price=line.unit_cost, source_type="TRANSFER_IN",
                                 source_id=tr.id, note=f"Came from {src.name if src else 'another branch'} · {num}",
                                 recorded_by_id=by))
        short = line.qty_sent - got
        if short > 1e-9:
            db.add(InventoryMovement(owner_phone=tr.owner_phone, item_id=item.id, movement_type="OUT",
                                     quantity=short, unit_price=line.unit_cost, source_type="TRANSFER_SHORT",
                                     source_id=tr.id, reason="stolen", note=f"Missing on the way · {num}",
                                     recorded_by_id=by))
        line.qty_received = got
    tr.status = "received"
    tr.received_by_id = by
    tr.received_at = utcnow()
    tr.receive_note = (note or "").strip()[:300] or None
    db.flush()
    return tr


def cancel(db, tr, user, reason):
    """Still on the way and not going: the goods go back to the sending branch."""
    if tr.status != "on_the_way":
        raise TransferError("Only a transfer still on the way can be cancelled.")
    reason = (reason or "").strip()
    if not reason:
        raise TransferError("Say why — the reason is kept on the transfer.")
    num = format_number(tr.number)
    for line in _lines(db, tr):
        item = db.query(InventoryItem).filter(InventoryItem.id == line.from_item_id).first()
        if not item:
            continue
        item.quantity = float(item.quantity or 0) + line.qty_sent
        db.add(InventoryMovement(owner_phone=tr.owner_phone, item_id=item.id, movement_type="IN",
                                 quantity=line.qty_sent, unit_price=line.unit_cost, source_type="TRANSFER_BACK",
                                 source_id=tr.id, note=f"Transfer cancelled · {num}",
                                 recorded_by_id=user.id if user else None))
        line.qty_received = 0
    tr.status = "cancelled"
    tr.receive_note = reason[:300]
    tr.received_by_id = user.id if user else None
    tr.received_at = utcnow()
    db.flush()
    return tr


def visible(db, owner_phone, scope_branch=None):
    q = db.query(StockTransfer).filter(StockTransfer.owner_phone == owner_phone)
    if scope_branch is not None:
        q = q.filter((StockTransfer.from_branch_id == scope_branch) | (StockTransfer.to_branch_id == scope_branch))
    return q


def _names(db, ids):
    return {u.id: (u.name or "").title() for u in db.query(User).filter(User.id.in_([i for i in ids if i])).all()}


def summary(db, tr, branches):
    lines = _lines(db, tr)
    return {
        "id": tr.id, "number": format_number(tr.number), "status": tr.status,
        "from_branch": branches.get(tr.from_branch_id), "to_branch": branches.get(tr.to_branch_id),
        "from_branch_id": tr.from_branch_id, "to_branch_id": tr.to_branch_id,
        "items": len(lines),
        "created_at": tr.created_at.isoformat() if tr.created_at else None,
        "received_at": tr.received_at.isoformat() if tr.received_at else None,
        "short": any(l.qty_received is not None and l.qty_received < l.qty_sent for l in lines)
        and tr.status == "received",
    }


def document(db, tr):
    """Everything the printed transfer note shows — no prices."""
    from invoices import _business_header
    doc = _business_header(db, tr.owner_phone, tr.from_branch_id, kind="waybill")
    branches = {b.id: b.name for b in db.query(Branch).filter(Branch.owner_phone == tr.owner_phone).all()}
    people = _names(db, [tr.created_by_id, tr.received_by_id])
    doc.update(summary(db, tr, branches))
    doc.update({
        "carried_by": tr.carried_by, "carrier_phone": tr.carrier_phone, "note": tr.note,
        "issued_by": people.get(tr.created_by_id), "received_by": people.get(tr.received_by_id),
        "receive_note": tr.receive_note,
        "lines": [{"id": l.id, "product": (l.product or "").title(), "unit": l.unit, "sent": _num(l.qty_sent),
                   "received": None if l.qty_received is None else _num(l.qty_received)}
                  for l in _lines(db, tr)],
    })
    return doc
