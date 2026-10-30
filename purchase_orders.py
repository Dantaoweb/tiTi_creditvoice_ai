"""
Purchase orders (PO-0001) — what you ordered from a supplier, before it comes.

- Writing and sending a PO moves no money and no stock (like an invoice).
- When goods arrive you receive against it: each line's arrived quantity goes
  into stock and becomes a supplier purchase (paid or owed), exactly like
  "stock received" — with an optional expiry date and batch per line.
- What hasn't come is "still expected" (part received). Closing an order
  keeps any shortfall on record ("20 never arrived").
"""
from datetime import datetime, timezone

from sqlalchemy import func

from models import InventoryItem, PurchaseOrder, PurchaseOrderLine, Supplier, SupplierPurchase


class POError(ValueError):
    pass


STATUS_LABELS = {
    "draft": "Draft", "sent": "Sent", "part_received": "Part received",
    "received": "Received", "closed": "Closed", "cancelled": "Cancelled",
}


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def format_po_number(n):
    return f"PO-{int(n):04d}"


def _lines(db, po):
    return db.query(PurchaseOrderLine).filter(PurchaseOrderLine.po_id == po.id).order_by(PurchaseOrderLine.id).all()


def _clean_lines(db, owner_phone, lines):
    out = []
    for l in lines or []:
        name = (l.get("product") or l.get("name") or "").strip()
        item = None
        if l.get("inventory_item_id"):
            item = db.query(InventoryItem).filter(InventoryItem.id == l["inventory_item_id"],
                                                  InventoryItem.owner_phone == owner_phone).first()
            if item is None:
                raise POError("A product on this order isn't in your stock list.")
            name = name or item.name
        if not name:
            continue
        try:
            qty = float(l.get("quantity") or 0)
            cost = int(l["unit_cost"]) if l.get("unit_cost") not in (None, "") else None
        except (TypeError, ValueError):
            raise POError("Enter quantities and costs as numbers.")
        if qty <= 0 or qty != int(qty):
            raise POError(f"Enter how many {name} to order (whole number).")
        if cost is not None and cost < 0:
            raise POError("A cost can't be negative.")
        out.append({"inventory_item_id": item.id if item else None, "product": name.lower()[:120],
                    "unit": (l.get("unit") or (item.unit if item else None) or None),
                    "quantity": int(qty), "unit_cost": cost if cost is not None else (item.cost_price if item else None)})
    if not out:
        raise POError("Add at least one product to the order.")
    return out


def _supplier(db, owner_phone, supplier_id=None, supplier_name=None):
    if supplier_id:
        sup = db.query(Supplier).filter(Supplier.id == supplier_id, Supplier.owner_phone == owner_phone).first()
        if not sup:
            raise POError("Supplier not found.")
        return sup
    name = (supplier_name or "").strip()
    if not name:
        raise POError("Choose the supplier.")
    from inventory_suppliers import find_or_create_supplier
    sup = find_or_create_supplier(db, owner_phone, name)
    db.flush()
    return sup


def create_po(db, owner_phone, user_id, lines, supplier_id=None, supplier_name=None,
              expected_date=None, note=None, branch_id=None):
    sup = _supplier(db, owner_phone, supplier_id, supplier_name)
    clean = _clean_lines(db, owner_phone, lines)
    top = db.query(func.max(PurchaseOrder.number)).filter(PurchaseOrder.owner_phone == owner_phone).scalar()
    po = PurchaseOrder(owner_phone=owner_phone, branch_id=branch_id, number=int(top or 0) + 1,
                       supplier_id=sup.id, status="draft", expected_date=expected_date,
                       note=(note or "").strip()[:300] or None, created_by_id=user_id)
    db.add(po)
    db.flush()
    for l in clean:
        db.add(PurchaseOrderLine(po_id=po.id, **l))
    db.flush()
    return po


def update_po(db, po, lines, supplier_id=None, supplier_name=None, expected_date=None, note=None):
    if po.status not in ("draft", "sent"):
        raise POError("Goods have already come in on this order, so it can't be changed.")
    clean = _clean_lines(db, po.owner_phone, lines)
    if supplier_id or supplier_name:
        po.supplier_id = _supplier(db, po.owner_phone, supplier_id, supplier_name).id
    po.expected_date = expected_date
    po.note = (note or "").strip()[:300] or None
    db.query(PurchaseOrderLine).filter(PurchaseOrderLine.po_id == po.id).delete()
    for l in clean:
        db.add(PurchaseOrderLine(po_id=po.id, **l))
    db.flush()
    return po


def mark_sent(db, po):
    if po.status in ("cancelled", "closed"):
        raise POError("This order is closed.")
    if po.status == "draft":
        po.status = "sent"
    po.sent_at = _utcnow()
    db.flush()


def receive(db, po, user_id, arrived, paid_now=None, due_date=None):
    """Goods came in: `arrived` = [{line_id, quantity, expiry_date?, batch_no?}].
    Each becomes stock + a supplier purchase (paid_now spread over them in
    order; the rest owed, due on due_date)."""
    from expiry import parse_expiry
    from inventory_suppliers import add_inventory_movement
    if po.status in ("cancelled", "closed", "received"):
        raise POError("This order is closed — record further deliveries as stock received.")
    by_id = {l.id: l for l in _lines(db, po)}
    picks = []
    for a in arrived or []:
        line = by_id.get(int(a.get("line_id") or 0))
        if line is None:
            raise POError("That product isn't on this order.")
        try:
            q = float(a.get("quantity") or 0)
        except (TypeError, ValueError):
            raise POError("Enter how many arrived.")
        if q <= 0:
            continue
        if q != int(q):
            raise POError("Enter whole numbers.")
        left = line.quantity - (line.received_qty or 0)
        if q > left:
            raise POError(f"Only {left} {line.product.title()} still expected on this order.")
        picks.append((line, int(q), parse_expiry(a.get("expiry_date")), (a.get("batch_no") or "").strip() or None))
    if not picks:
        raise POError("Enter how many of each product arrived.")
    total = sum(q * (l.unit_cost or 0) for l, q, _e, _b in picks)
    try:
        pay_left = total if paid_now in (None, "") else max(0, min(int(paid_now), total))
    except (TypeError, ValueError):
        raise POError("Enter the amount paid as a number.")
    sup = db.query(Supplier).filter(Supplier.id == po.supplier_id).first()
    purchases = []
    for line, q, exp, batch in picks:
        line_total = q * (line.unit_cost or 0)
        paid = min(pay_left, line_total)
        pay_left -= paid
        purchase = SupplierPurchase(
            supplier_id=po.supplier_id, owner_phone=po.owner_phone, product=line.product, quantity=q,
            unit=line.unit, unit_price=line.unit_cost, total=line_total, paid_amount=paid,
            due_date=due_date if paid < line_total else None, recorded_by_id=user_id, created_at=_utcnow(),
        )
        db.add(purchase)
        db.flush()
        item = add_inventory_movement(
            db, po.owner_phone, line.product, q, line.unit, line.unit_cost, "IN", "SUPPLIER_PURCHASE",
            purchase.id, user_id, f"{format_po_number(po.number)} from {(sup.name if sup else 'supplier').title()}",
            expiry_date=exp, batch_no=batch,
        )
        if item is not None:
            line.inventory_item_id = line.inventory_item_id or item.id
            if sup and not item.usual_supplier and (sup.name or "").lower() != "others":
                item.usual_supplier = sup.name
        line.received_qty = (line.received_qty or 0) + q
        purchases.append(purchase.id)
    lines = list(by_id.values())
    po.status = "received" if all((l.received_qty or 0) >= l.quantity for l in lines) else "part_received"
    if po.status == "received":
        po.closed_at = _utcnow()
    db.flush()
    return purchases


def close_po(db, po, reason=None):
    """Stop expecting the rest. What never came stays on record."""
    if po.status in ("closed", "cancelled", "received"):
        raise POError("This order is already closed.")
    if po.status in ("draft", "sent"):
        raise POError("Nothing has arrived on this order yet — cancel it instead.")
    po.status = "closed"
    po.closed_at = _utcnow()
    po.close_reason = (reason or "").strip()[:200] or None
    db.flush()


def cancel_po(db, po):
    if po.status not in ("draft", "sent"):
        raise POError("Goods have already come in on this order — close it instead.")
    po.status = "cancelled"
    po.closed_at = _utcnow()
    db.flush()


def po_document(db, po):
    from invoices import _business_header
    doc = _business_header(db, po.owner_phone, po.branch_id, kind="purchase_order")
    sup = db.query(Supplier).filter(Supplier.id == po.supplier_id).first()
    lines = []
    for l in _lines(db, po):
        got = l.received_qty or 0
        lines.append({"id": l.id, "inventory_item_id": l.inventory_item_id, "product": l.product.title(),
                      "unit": l.unit, "quantity": l.quantity, "unit_cost": l.unit_cost,
                      "total": l.quantity * (l.unit_cost or 0), "received": got,
                      "expected": max(0, l.quantity - got),
                      "short": max(0, l.quantity - got) if po.status == "closed" else 0})
    doc.update({
        "id": po.id, "number": format_po_number(po.number), "status": po.status,
        "status_label": STATUS_LABELS.get(po.status, po.status),
        "supplier": {"id": sup.id, "name": (sup.name or "").title(), "phone": sup.phone} if sup else None,
        "expected_date": po.expected_date.date().isoformat() if po.expected_date else None,
        "note": po.note, "close_reason": po.close_reason,
        "created_at": po.created_at.isoformat() if po.created_at else None,
        "sent_at": po.sent_at.isoformat() if po.sent_at else None,
        "lines": lines, "total": sum(l["total"] for l in lines),
        "still_expected": sum(l["expected"] for l in lines) if po.status in ("sent", "part_received", "draft") else 0,
    })
    return doc


def po_text(doc):
    """The WhatsApp message for the supplier."""
    out = [f"*PURCHASE ORDER {doc['number']}*", doc.get("biz_name") or ""]
    if doc.get("biz_phone"):
        out.append(f"Tel: {doc['biz_phone']}")
    out.append("--------------------")
    for l in doc["lines"]:
        unit = f" {l['unit']}" if l.get("unit") else ""
        price = f" @ N{l['unit_cost']:,} = N{l['total']:,}" if l.get("unit_cost") else ""
        out.append(f"{l['product']}: {l['quantity']}{unit}{price}")
    out.append("--------------------")
    if doc["total"]:
        out.append(f"*Total: N{doc['total']:,}*")
    if doc.get("expected_date"):
        out.append(f"Please deliver by {doc['expected_date']}.")
    if doc.get("note"):
        out.append(doc["note"])
    out.append("Please confirm. Thank you.")
    return "\n".join(x for x in out if x is not None)


def list_pos(db, owner_phone, branch_id=None):
    q = db.query(PurchaseOrder).filter(PurchaseOrder.owner_phone == owner_phone)
    if branch_id is not None:
        q = q.filter(PurchaseOrder.branch_id == branch_id)
    out = []
    for po in q.order_by(PurchaseOrder.id.desc()).limit(200).all():
        sup = db.query(Supplier).filter(Supplier.id == po.supplier_id).first()
        lines = _lines(db, po)
        out.append({"id": po.id, "number": format_po_number(po.number), "status": po.status,
                    "status_label": STATUS_LABELS.get(po.status, po.status),
                    "supplier": (sup.name or "").title() if sup else None,
                    "total": sum(l.quantity * (l.unit_cost or 0) for l in lines),
                    "items": len(lines),
                    "expected_date": po.expected_date.date().isoformat() if po.expected_date else None,
                    "created_at": po.created_at.isoformat() if po.created_at else None})
    return out


def reorder_suggestions(db, owner_phone, branch_id=None):
    """Low-stock products grouped by their usual supplier — to start an order."""
    q = db.query(InventoryItem).filter(InventoryItem.owner_phone == owner_phone,
                                       InventoryItem.removed_at.is_(None),
                                       InventoryItem.low_stock_alert.isnot(None),
                                       InventoryItem.quantity.isnot(None),
                                       InventoryItem.quantity <= InventoryItem.low_stock_alert)
    if branch_id is not None:
        q = q.filter(InventoryItem.branch_id == branch_id)
    groups = {}
    for it in q.order_by(InventoryItem.name).all():
        key = (it.usual_supplier or "").strip().title() or None
        groups.setdefault(key, []).append({
            "inventory_item_id": it.id, "product": it.name.title(), "unit": it.unit,
            "in_stock": it.quantity, "alert_at": it.low_stock_alert, "unit_cost": it.cost_price,
            "suggest": max(1, int((it.low_stock_alert or 0) * 2 - (it.quantity or 0))),
        })
    return [{"supplier": k, "items": v} for k, v in groups.items()]
