"""
Expiry — which goods in the store expire, and when.

Each delivery is a batch (StockBatch) with its own expiry date, if given.
Selling never picks a batch: we assume the oldest goods go first, so what
is still in the store is the newest deliveries adding up to today's stock.
Stock older than any batch (from before batches were kept) carries the
product's own expiry date, if one was set on WhatsApp.

- expiry_by_item: each product's dated goods still in store, soonest first;
- expiring: everything expired or expiring within N days (alerts, Inventory);
- write_off_expired: take expired goods out of stock as a loss.
"""
from datetime import datetime, timedelta, timezone

from models import InventoryItem, InventoryMovement, StockBatch


class ExpiryError(ValueError):
    pass


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _num(q):
    q = float(q or 0)
    return int(q) if q == int(q) else round(q, 2)


def parse_expiry(value):
    """'2027-03' / '2027-03-15' / '03/2027' → a date (month-only = 1st)."""
    if not value:
        return None
    v = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%m/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    raise ExpiryError("Enter the expiry date like 2027-03 or 03/2027.")


def _in_store(item, batches):
    """[(expiry, qty, batch_no)] of the goods still in store with a date."""
    left = float(item.quantity or 0)
    out = []
    for b in sorted(batches, key=lambda b: (b.received_at or datetime.min), reverse=True):
        if left <= 1e-9:
            break
        take = min(left, float(b.quantity or 0))
        left -= take
        # A delivery with no date of its own takes the product's (set on WhatsApp)
        exp = b.expiry_date or item.expiry_date
        if exp and take > 0:
            out.append((exp, take, b.batch_no or (item.batch_no if not b.expiry_date else None)))
    if left > 1e-9 and item.expiry_date:          # older stock, dated the old way
        out.append((item.expiry_date, left, item.batch_no))
    return sorted(out, key=lambda r: r[0])


def expiry_by_item(db, items):
    """{item_id: [{"expiry", "quantity", "batch_no"}…]} soonest first."""
    ids = [i.id for i in items if i.quantity is not None]
    batches = {}
    if ids:
        for b in db.query(StockBatch).filter(StockBatch.item_id.in_(ids)).all():
            batches.setdefault(b.item_id, []).append(b)
    out = {}
    for it in items:
        if it.quantity is None:
            continue
        rows = _in_store(it, batches.get(it.id, []))
        if rows:
            out[it.id] = [{"expiry": e.date().isoformat(), "quantity": _num(q), "batch_no": bn} for e, q, bn in rows]
    return out


def item_expiry_summary(rows, warn_days, now=None):
    """For one product's rows: expired qty, soon qty, soonest date."""
    now = now or _utcnow()
    soon_limit = (now + timedelta(days=warn_days)).date().isoformat()
    today = now.date().isoformat()
    expired = sum(r["quantity"] for r in rows if r["expiry"] < today)
    soon = sum(r["quantity"] for r in rows if today <= r["expiry"] <= soon_limit)
    nxt = next((r["expiry"] for r in rows if r["expiry"] >= today), None)
    return {"expired_qty": _num(expired), "soon_qty": _num(soon), "next_expiry": nxt,
            "rows": rows}


def expiring(db, owner_phone, warn_days, branch_id=None):
    """Products with goods expired or expiring within `warn_days`."""
    q = db.query(InventoryItem).filter(InventoryItem.owner_phone == owner_phone,
                                       InventoryItem.quantity > 0)
    if branch_id is not None:
        q = q.filter(InventoryItem.branch_id == branch_id)
    items = q.all()
    by_item = expiry_by_item(db, items)
    out = []
    for it in items:
        rows = by_item.get(it.id)
        if not rows:
            continue
        s = item_expiry_summary(rows, warn_days)
        if s["expired_qty"] or s["soon_qty"]:
            out.append({"item_id": it.id, "name": it.name.title(), "unit": it.unit,
                        "in_store": _num(it.quantity), "cost_price": it.cost_price, **s})
    out.sort(key=lambda r: (r["expired_qty"] == 0, r["rows"][0]["expiry"]))
    return out


def write_off_expired(db, owner_phone, item, quantity, user_id):
    """Expired goods thrown away: out of stock, counted as a loss (at cost)."""
    try:
        quantity = float(quantity)
    except (TypeError, ValueError):
        raise ExpiryError("Enter how many to write off.")
    if quantity <= 0 or quantity != quantity:
        raise ExpiryError("Enter how many to write off.")
    if quantity > float(item.quantity or 0) + 1e-9:
        raise ExpiryError(f"Only {_num(item.quantity)} in stock.")
    item.quantity = max(0.0, float(item.quantity or 0) - quantity)
    item.updated_at = _utcnow()
    mv = InventoryMovement(owner_phone=owner_phone, item_id=item.id, movement_type="OUT", quantity=quantity,
                           unit_price=item.cost_price, source_type="EXPIRED_WRITE_OFF", recorded_by_id=user_id,
                           note="Expired — written off")
    db.add(mv)
    # The oldest goods are the expired ones: drop them from the oldest batches
    left = quantity
    for b in (db.query(StockBatch).filter(StockBatch.item_id == item.id)
              .order_by(StockBatch.received_at.asc()).all()):
        if left <= 1e-9:
            break
        take = min(left, float(b.quantity or 0))
        b.quantity = float(b.quantity or 0) - take
        left -= take
    db.flush()
    return mv


def expiry_alert_text(rows, warn_days, business_name=None):
    lines = [f"⏳ *Expiry alert*{(' — ' + business_name) if business_name else ''}", ""]
    expired = [r for r in rows if r["expired_qty"]]
    soon = [r for r in rows if r["soon_qty"]]
    if expired:
        lines.append("*Expired — don't sell, write off:*")
        lines += [f"• {r['name']}: {r['expired_qty']}{(' ' + r['unit']) if r['unit'] else ''}" for r in expired[:10]]
    if soon:
        if expired:
            lines.append("")
        lines.append(f"*Expiring within {warn_days} days — sell these first:*")
        for r in soon[:10]:
            d = next(x["expiry"] for x in r["rows"] if x["expiry"] >= _utcnow().date().isoformat())
            lines.append(f"• {r['name']}: {r['soon_qty']}{(' ' + r['unit']) if r['unit'] else ''} "
                         f"(by {datetime.fromisoformat(d).strftime('%d %b %Y')})")
    lines += ["", "Open Inventory → Expiry on the app to write off expired goods."]
    return "\n".join(lines)
