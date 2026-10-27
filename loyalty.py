"""
Loyalty — rewards for customers who keep coming back. Off unless the owner
picks one kind in Settings:

- Stamp card: each paid sale is a stamp; at N stamps (10 by default) the next
  one is free — "Use reward" at the till takes one item's price off.
- Points: ₦1 back for every ₦100 spent (1% by default); "Use points" at the
  till takes them off as a discount.

Rules (user, 2026-10-27):
- Only a sale to a named customer earns, and only once it's fully paid: a
  credit sale earns when the debt is cleared (the customer's balance is
  counted against their newest credit sales first, like payments clear the
  oldest).
- A voided sale takes its reward back; a refund lowers points earned; a
  voided sale that used a reward gives it back. A sale that used a reward
  earns nothing.
- Optional expiry (months); used rewards come out of the oldest first.
- Counting starts when loyalty is switched on (or changed to the other kind).

What was earned is worked out from the sales themselves (sync_customer), so
every way of selling — till, Quick Record, tiTi, invoices, appointments —
counts without each one having to remember loyalty.
"""
from datetime import datetime, timedelta

from sqlalchemy import func

from models import CreditNote, Customer, LoyaltyEntry, Transaction, TransactionItem

SALE_TYPES = ("SALE", "BUY")


class LoyaltyError(ValueError):
    pass


def config(db, owner_phone):
    from app_settings import _owner, _raw_business, get_business_settings
    s = get_business_settings(db, owner_phone)
    since = _raw_business(_owner(db, owner_phone)).get("loyalty_since")
    try:
        since = datetime.fromisoformat(since) if since else None
    except ValueError:
        since = None
    return {"mode": s.get("loyalty_mode") or "off", "needed": int(s.get("loyalty_stamps_needed") or 10),
            "percent": float(s.get("loyalty_points_percent") or 1), "expiry": int(s.get("loyalty_expiry_months") or 0),
            "items": set(s.get("loyalty_items") or []), "since": since}


def _qualifying(db, tx, items):
    """The naira of this sale that counts: what was paid for it, less refunds,
    and only the products that count (if the owner chose some)."""
    net = int(tx.amount or 0)
    refunded = db.query(func.coalesce(func.sum(CreditNote.amount), 0)).filter(
        CreditNote.sale_tx_id == tx.id, CreditNote.voided_at.is_(None)).scalar() or 0
    net = max(0, net - int(refunded))
    if not items:
        return net
    lines = db.query(TransactionItem).filter(TransactionItem.transaction_id == tx.id).all()
    total = sum(int(l.total or 0) for l in lines)
    matched = sum(int(l.total or 0) for l in lines if l.inventory_item_id in items)
    return int(round(net * matched / total)) if total else 0


def _unpaid_ids(db, cust):
    """Credit sales still (partly) owed: the balance sits on the newest ones."""
    owed = max(0, int(cust.balance or 0))
    out = set()
    if owed <= 0:
        return out
    q = (db.query(Transaction).filter(Transaction.customer_id == cust.id, Transaction.type == "BUY",
                                      Transaction.amount > 0, Transaction.is_voided.isnot(True))
         .order_by(Transaction.created_at.desc(), Transaction.id.desc()))
    for tx in q.yield_per(200):
        out.add(tx.id)
        owed -= int(tx.amount or 0)
        if owed <= 0:
            break
    return out


def _entries(db, owner_phone, customer_id, cfg):
    """This customer's entries for sales made since loyalty (this kind) began —
    by the sale's date, so an old reward is never mistaken for a missing one."""
    return (db.query(LoyaltyEntry).join(Transaction, Transaction.id == LoyaltyEntry.transaction_id)
            .filter(LoyaltyEntry.owner_phone == owner_phone, LoyaltyEntry.customer_id == customer_id,
                    Transaction.created_at >= cfg["since"]))


def sync_customer(db, owner_phone, customer_id, cfg=None):
    """Bring what this customer earned up to date with their sales."""
    cfg = cfg or config(db, owner_phone)
    if cfg["mode"] == "off" or not cfg["since"] or not customer_id:
        return
    cust = db.query(Customer).filter(Customer.id == customer_id, Customer.owner_phone == owner_phone).first()
    if not cust:
        return
    entries = _entries(db, owner_phone, customer_id, cfg).all()
    earned = {e.transaction_id: e for e in entries if e.kind == "earn"}
    used_on = {e.transaction_id for e in entries if e.kind == "use" and not e.cancelled_at}
    now = datetime.utcnow()

    # Voided sales: take back what they earned; give back what they used
    tx_ids = {e.transaction_id for e in entries if e.transaction_id}
    voided = {t.id for t in db.query(Transaction.id).filter(Transaction.id.in_(tx_ids), Transaction.is_voided.is_(True))} \
        if tx_ids else set()
    for e in entries:
        if e.transaction_id in voided and not e.cancelled_at:
            e.cancelled_at = now

    unpaid = _unpaid_ids(db, cust)
    sales = db.query(Transaction).filter(Transaction.customer_id == customer_id, Transaction.type.in_(SALE_TYPES),
                                         Transaction.amount > 0, Transaction.is_voided.isnot(True),
                                         Transaction.created_at >= cfg["since"]).all()
    for tx in sales:
        if tx.id in unpaid or tx.id in used_on:
            continue
        q = _qualifying(db, tx, cfg["items"])
        stamps = 1 if (cfg["mode"] == "stamps" and q > 0) else 0
        points = int(q * cfg["percent"] // 100) if cfg["mode"] == "points" else 0
        e = earned.get(tx.id)
        if e is None:
            if stamps or points:
                db.add(LoyaltyEntry(owner_phone=owner_phone, customer_id=customer_id, transaction_id=tx.id,
                                    kind="earn", stamps=stamps, points=points, created_at=now))
        elif not e.cancelled_at and (e.stamps, e.points) != (stamps, points):
            e.stamps, e.points = stamps, points               # a refund lowered it
    db.flush()


def available(db, owner_phone, customer_id, cfg=None, now=None):
    """Stamps or points the customer can use now (oldest used first; earned
    ones older than the expiry are gone unless already used)."""
    cfg = cfg or config(db, owner_phone)
    if cfg["mode"] == "off" or not cfg["since"]:
        return 0
    unit = LoyaltyEntry.stamps if cfg["mode"] == "stamps" else LoyaltyEntry.points
    base = (_entries(db, owner_phone, customer_id, cfg)
            .filter(LoyaltyEntry.cancelled_at.is_(None))
            .with_entities(LoyaltyEntry.kind, LoyaltyEntry.created_at, unit).all())
    used = sum(v or 0 for k, _t, v in base if k == "use")
    cutoff = (now or datetime.utcnow()) - timedelta(days=30 * cfg["expiry"]) if cfg["expiry"] else None
    old = sum(v or 0 for k, t, v in base if k == "earn" and cutoff and t < cutoff)
    recent = sum(v or 0 for k, t, v in base if k == "earn" and not (cutoff and t < cutoff))
    return max(0, recent - max(0, used - old))


def status(db, owner_phone, customer_id):
    cfg = config(db, owner_phone)
    if cfg["mode"] == "off":
        return {"mode": "off"}
    sync_customer(db, owner_phone, customer_id, cfg)
    n = available(db, owner_phone, customer_id, cfg)
    if cfg["mode"] == "stamps":
        return {"mode": "stamps", "stamps": n, "needed": cfg["needed"], "reward_ready": n >= cfg["needed"]}
    return {"mode": "points", "points": n, "reward_ready": n > 0}


def reward_for_cart(db, owner_phone, customer_id, items):
    """(naira off, units used) for using the customer's reward on this cart."""
    cfg = config(db, owner_phone)
    if cfg["mode"] == "off":
        raise LoyaltyError("Loyalty is off.")
    if not customer_id:
        raise LoyaltyError("Choose the customer to use their reward.")
    sync_customer(db, owner_phone, customer_id, cfg)
    n = available(db, owner_phone, customer_id, cfg)
    total = sum(int(round(float(i.get("qty") or 1) * int(i.get("unit_price") or 0))) for i in items)
    if cfg["mode"] == "stamps":
        if n < cfg["needed"]:
            raise LoyaltyError(f"They have {n} of {cfg['needed']} stamps — not enough for a free one yet.")
        prices = [int(i.get("unit_price") or 0) for i in items
                  if not cfg["items"] or i.get("inventory_item_id") in cfg["items"]]
        prices = [p for p in prices if p > 0]
        if not prices:
            raise LoyaltyError("Nothing in this sale counts for the free one.")
        return min(min(prices), total), cfg["needed"]
    if n <= 0:
        raise LoyaltyError("They have no points to use yet.")
    off = min(n, total)
    return off, off


def record_use(db, owner_phone, customer_id, tx_id, units):
    cfg = config(db, owner_phone)
    db.add(LoyaltyEntry(owner_phone=owner_phone, customer_id=customer_id, transaction_id=tx_id, kind="use",
                        stamps=units if cfg["mode"] == "stamps" else 0,
                        points=units if cfg["mode"] == "points" else 0, created_at=datetime.utcnow()))
    db.flush()


def receipt_line(db, owner_phone, customer_id):
    """A line for the customer's WhatsApp receipt, or None."""
    if not customer_id:
        return None
    s = status(db, owner_phone, customer_id)
    if s["mode"] == "stamps":
        if s["reward_ready"]:
            return f"🎁 Loyalty: {s['stamps']} stamps — your next one is FREE. Just ask!"
        left = s["needed"] - s["stamps"]
        return f"⭐ Loyalty: {s['stamps']} of {s['needed']} stamps — {left} more for a free one."
    if s["mode"] == "points" and s["points"] > 0:
        return f"⭐ Loyalty: you have ₦{s['points']:,} to use on your next visit."
    return None


def best_customers(db, owner_phone, days=90, limit=30, branch_id=None):
    """Who spent most in the last `days`, with their reward if loyalty is on."""
    since = datetime.utcnow() - timedelta(days=days)
    q = db.query(Transaction.customer_id, func.sum(Transaction.amount), func.count(Transaction.id)).filter(
        Transaction.customer_id.isnot(None), Transaction.type.in_(SALE_TYPES), Transaction.is_voided.isnot(True),
        Transaction.created_at >= since)
    q = q.join(Customer, Customer.id == Transaction.customer_id).filter(Customer.owner_phone == owner_phone)
    if branch_id is not None:
        q = q.filter(Transaction.branch_id == branch_id)
    rows = q.group_by(Transaction.customer_id).order_by(func.sum(Transaction.amount).desc()).limit(limit).all()
    cfg = config(db, owner_phone)
    names = {c.id: c for c in db.query(Customer).filter(Customer.id.in_([r[0] for r in rows]))} if rows else {}
    out = []
    for cid, spent, visits in rows:
        c = names.get(cid)
        item = {"id": cid, "name": (c.name or "").title() if c else "", "phone": c.customer_phone if c else None,
                "spent": int(spent or 0), "visits": int(visits or 0)}
        if cfg["mode"] != "off":
            sync_customer(db, owner_phone, cid, cfg)
            item["reward"] = available(db, owner_phone, cid, cfg)
        out.append(item)
    db.flush()
    return {"mode": cfg["mode"], "needed": cfg["needed"], "days": days, "customers": out}


def sync_business(db, owner_phone):
    """Daily: catch up every customer who bought since loyalty began."""
    cfg = config(db, owner_phone)
    if cfg["mode"] == "off" or not cfg["since"]:
        return
    ids = [i for i, in db.query(Transaction.customer_id).join(Customer, Customer.id == Transaction.customer_id)
           .filter(Customer.owner_phone == owner_phone, Transaction.created_at >= cfg["since"],
                   Transaction.customer_id.isnot(None)).distinct()]
    for cid in ids:
        sync_customer(db, owner_phone, cid, cfg)
    db.commit()
