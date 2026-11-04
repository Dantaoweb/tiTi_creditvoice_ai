"""
Distributors / van sales — goods go out with a seller in the morning, the
unsold come back in the evening, and the seller pays for what was sold.

  Send out   the goods leave stock (they're with the seller now) at the
             seller's price: a lower price for them, or retail less their
             commission — the same sum either way.
  Settle     what came back good goes back into stock; what came back stale or
             damaged is removed with that reason; what was sold becomes a sale
             with a receipt, and what isn't paid is the seller's debt (Debts,
             reminders) — the seller is a customer.

A seller has one run out at a time: sending more adds to it.
"""
from datetime import datetime, timedelta

from models import Customer, InventoryItem, InventoryMovement, VanRun, VanRunLine, utcnow


class VanError(ValueError):
    pass


def _whole(v, what):
    try:
        q = float(v or 0)
    except (TypeError, ValueError):
        raise VanError(f"Enter {what} as a number.")
    if q < 0 or q != int(q):
        raise VanError(f"Enter {what} as a whole number.")
    return int(q)


def default_price(item):
    """What a seller pays by default: the wholesale price, else the selling price."""
    return int(item.wholesale_price or item.selling_price or 0)


def open_run(db, owner_phone, customer_id):
    return db.query(VanRun).filter(VanRun.owner_phone == owner_phone, VanRun.customer_id == customer_id,
                                   VanRun.status == "out").first()


def send_out(db, owner_phone, user_id, lines, customer_id=None, customer_name=None, customer_phone=None,
             note=None, branch_id=None):
    from web_pos import resolve_sale_customer
    cid = resolve_sale_customer(db, owner_phone, customer_id, customer_name, customer_phone)
    if not cid:
        raise VanError("Pick the seller, or type their name.")
    wanted = []
    for l in lines or []:
        qty = _whole(l.get("qty"), "how many")
        if not qty:
            continue
        it = db.query(InventoryItem).filter(InventoryItem.id == int(l.get("item_id") or 0),
                                            InventoryItem.owner_phone == owner_phone,
                                            InventoryItem.is_available.isnot(False)).first()
        if not it:
            raise VanError("That product isn't in your stock.")
        if branch_id is not None and it.branch_id not in (None, branch_id):
            raise VanError(f"{it.name.title()} belongs to another branch.")
        price = l.get("unit_price")
        price = default_price(it) if price in (None, "") else _whole(price, "the price")
        if price <= 0:
            raise VanError(f"Set the seller's price for {it.name.title()}.")
        if it.quantity is not None and qty > float(it.quantity or 0):
            raise VanError(f"Only {int(it.quantity or 0)} {it.name.title()} in stock.")
        wanted.append((it, qty, price))
    if not wanted:
        raise VanError("Add what they're taking.")

    run = open_run(db, owner_phone, cid)
    if not run:
        run = VanRun(owner_phone=owner_phone, branch_id=branch_id, customer_id=cid, status="out",
                     note=(note or "").strip()[:200] or None, created_by_id=user_id, created_at=utcnow())
        db.add(run)
        db.flush()
    seller = db.query(Customer).filter(Customer.id == cid).first()
    for it, qty, price in wanted:
        line = db.query(VanRunLine).filter(VanRunLine.run_id == run.id, VanRunLine.item_id == it.id).first()
        if not line:
            line = VanRunLine(run_id=run.id, item_id=it.id, qty_out=0, qty_back=0, qty_spoilt=0)
            db.add(line)
        line.qty_out = float(line.qty_out or 0) + qty
        line.unit_price = price
        if it.quantity is not None:
            it.quantity = float(it.quantity or 0) - qty
        it.updated_at = utcnow()
        db.add(InventoryMovement(owner_phone=owner_phone, item_id=it.id, movement_type="OUT", quantity=qty,
                                 unit_price=it.cost_price, source_type="VAN_OUT", source_id=run.id,
                                 recorded_by_id=user_id, note=f"Taken out to sell by {seller.name if seller else 'seller'}"))
    db.commit()
    return run


def settle(db, owner_phone, user_id, run_id, returns, paid, due_date=None, spoilt_reason="expired"):
    """`returns`: {line_id: {"back": n, "spoilt": n}}. Everything not returned was sold."""
    from stock_removal import record_removal, RemovalError
    from web_pos import save_pos_sale
    run = db.query(VanRun).filter(VanRun.id == run_id, VanRun.owner_phone == owner_phone).first()
    if not run:
        raise VanError("That run was not found.")
    if run.status != "out":
        raise VanError("This run was already settled.")
    seller = db.query(Customer).filter(Customer.id == run.customer_id).first()
    who = seller.name if seller else "seller"
    lines = db.query(VanRunLine).filter(VanRunLine.run_id == run.id).all()
    items = {i.id: i for i in db.query(InventoryItem).filter(InventoryItem.id.in_([l.item_id for l in lines] or [0])).all()}
    sold_items, sold_value = [], 0
    for l in lines:
        r = (returns or {}).get(str(l.id)) or (returns or {}).get(l.id) or {}
        back, spoilt = _whole(r.get("back"), "how many came back"), _whole(r.get("spoilt"), "how many are spoilt")
        if back + spoilt > l.qty_out:
            it = items.get(l.item_id)
            raise VanError(f"More came back than went out for {it.name.title() if it else 'an item'}.")
        l.qty_back, l.qty_spoilt = back, spoilt
        sold = int(l.qty_out) - back - spoilt
        it = items.get(l.item_id)
        if it and back + spoilt:
            if it.quantity is not None:
                it.quantity = float(it.quantity or 0) + back + spoilt
            db.add(InventoryMovement(owner_phone=owner_phone, item_id=it.id, movement_type="IN",
                                     quantity=back + spoilt, unit_price=it.cost_price, source_type="VAN_RETURN",
                                     source_id=run.id, recorded_by_id=user_id, note=f"Brought back unsold by {who}"))
            if spoilt:
                try:
                    record_removal(db, it, spoilt, spoilt_reason, f"Brought back by {who}", user_id,
                                   source_type="WEB_ADJUST")
                except RemovalError as e:
                    raise VanError(str(e))
        if sold > 0 and it:
            sold_items.append({"inventory_item_id": it.id, "name": it.name, "qty": sold, "unit": it.unit,
                               "unit_price": int(l.unit_price or 0)})
            sold_value += sold * int(l.unit_price or 0)

    paid = _whole(paid, "the amount paid")
    if paid > sold_value:
        raise VanError(f"That's more than the goods sold ({_naira(sold_value)}). Record extra as a debt payment from Debts.")
    if sold_items:
        result = save_pos_sale(db, owner_phone, user_id, run.customer_id, sold_items, paid,
                               branch_id=run.branch_id, due_date=due_date if paid < sold_value else None,
                               deduct_stock=False, commit=False,
                               label=f"Van sales — {who}", vat=None)
        run.sale_tx_id = result["receipt_id"]
    run.status, run.sold_value, run.paid = "settled", sold_value, paid
    run.settled_at, run.settled_by_id = utcnow(), user_id
    db.commit()
    return run


def _naira(n):
    return f"₦{int(n):,}"


def run_dict(db, run, names=None):
    names = names if names is not None else {}
    lines = db.query(VanRunLine).filter(VanRunLine.run_id == run.id).order_by(VanRunLine.id).all()
    for l in lines:
        if l.item_id not in names:
            it = db.query(InventoryItem).filter(InventoryItem.id == l.item_id).first()
            names[l.item_id] = ((it.name or "").title(), it.unit) if it else ("?", None)
    seller = db.query(Customer).filter(Customer.id == run.customer_id).first()
    out_value = sum(int(l.qty_out or 0) * int(l.unit_price or 0) for l in lines)
    return {
        "id": run.id, "status": run.status,
        "seller": {"id": seller.id, "name": seller.name, "phone": seller.customer_phone,
                   "owes": max(0, int(seller.balance or 0))} if seller else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "settled_at": run.settled_at.isoformat() if run.settled_at else None,
        "note": run.note, "out_value": out_value, "sold_value": run.sold_value, "paid": run.paid,
        "owed_now": (run.sold_value or 0) - (run.paid or 0) if run.status == "settled" else None,
        "receipt_id": run.sale_tx_id,
        "lines": [{"id": l.id, "item_id": l.item_id, "name": names[l.item_id][0], "unit": names[l.item_id][1],
                   "out": int(l.qty_out or 0), "back": int(l.qty_back or 0), "spoilt": int(l.qty_spoilt or 0),
                   "sold": int(l.qty_out or 0) - int(l.qty_back or 0) - int(l.qty_spoilt or 0),
                   "unit_price": int(l.unit_price or 0)} for l in lines],
    }


def overview(db, owner_phone, days=30, branch_id=None):
    """What's out with sellers now, settled runs in the period, and per seller:
    taken, came back, sold, paid and what they owe."""
    since = datetime.utcnow() - timedelta(days=days)
    q = db.query(VanRun).filter(VanRun.owner_phone == owner_phone)
    if branch_id is not None:
        q = q.filter(VanRun.branch_id == branch_id)
    out = q.filter(VanRun.status == "out").order_by(VanRun.created_at.asc()).all()
    done = q.filter(VanRun.status == "settled", VanRun.settled_at >= since).order_by(VanRun.settled_at.desc()).limit(300).all()
    names = {}
    out_d = [run_dict(db, r, names) for r in out]
    done_d = [run_dict(db, r, names) for r in done]
    sellers = {}
    for r in done_d:
        if not r["seller"]:
            continue
        s = sellers.setdefault(r["seller"]["id"], {"seller": r["seller"], "runs": 0, "taken": 0, "back": 0,
                                                   "spoilt": 0, "sold": 0, "sold_value": 0, "paid": 0})
        s["runs"] += 1
        for l in r["lines"]:
            s["taken"] += l["out"]; s["back"] += l["back"]; s["spoilt"] += l["spoilt"]; s["sold"] += l["sold"]
        s["sold_value"] += r["sold_value"] or 0
        s["paid"] += r["paid"] or 0
    for s in sellers.values():
        s["sold_pct"] = round(100 * s["sold"] / s["taken"], 1) if s["taken"] else None
    return {"out": out_d, "settled": done_d,
            "sellers": sorted(sellers.values(), key=lambda s: -s["sold_value"])}


def van_sold_and_out(db, owner_phone, item_ids, since, branch_id=None):
    """For the production report: per product, sold through sellers (settled
    in the period) and out with sellers right now."""
    q = (db.query(VanRun, VanRunLine).join(VanRunLine, VanRunLine.run_id == VanRun.id)
         .filter(VanRun.owner_phone == owner_phone, VanRunLine.item_id.in_(list(item_ids) or [0])))
    if branch_id is not None:
        q = q.filter(VanRun.branch_id == branch_id)
    sold, out = {}, {}
    for run, l in q.all():
        if run.status == "settled" and run.settled_at and run.settled_at >= since:
            sold[l.item_id] = sold.get(l.item_id, 0) + int(l.qty_out or 0) - int(l.qty_back or 0) - int(l.qty_spoilt or 0)
        elif run.status == "out":
            out[l.item_id] = out.get(l.item_id, 0) + int(l.qty_out or 0)
    return sold, out
