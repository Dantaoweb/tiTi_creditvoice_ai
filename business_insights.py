"""
What tiTi notices without being asked.

Answering a question is useful; the thing a trader cannot do for themselves is
spot the slow problems — a cost that crept up while the price stayed still, a
shelf that empties on Thursday, a good customer who quietly stopped coming.
Those are all in the records already. Nobody has time to go looking.

Every threshold here is measured against the business's own history rather than
a number we picked. A shop selling four bags a day and one selling four a month
are not comparable, and a warning that fires for both teaches people to ignore
warnings.

No language model: this is arithmetic on what they recorded.
"""
import logging
from datetime import timedelta

from models import Customer, InventoryItem, Transaction, utcnow

_log = logging.getLogger(__name__)

# How sure we have to be before interrupting someone.
_COST_RISE_PCT = 8           # a cost rise worth mentioning
_MIN_ENTRIES_FOR_TREND = 2   # one purchase is not a trend
_RUNWAY_DAYS = 7             # "you run out this week"
_QUIET_DAYS = 45             # a regular who has gone quiet
_MIN_VISITS_TO_BE_A_REGULAR = 3


def _money(value):
    from business_facts import _money as fmt
    return fmt(value)


def _insight(key, title, body, link=None, weight=0):
    return {"key": key, "title": title, "body": body, "link": link, "weight": weight}


# ── The things worth noticing ────────────────────────────────────────────────

def _selling_below_cost(db, owner_phone, costs):
    """The worst thing a shop can do without realising: every sale loses money."""
    found = []
    for item in db.query(InventoryItem).filter(
            InventoryItem.owner_phone == owner_phone,
            InventoryItem.selling_price.isnot(None),
            InventoryItem.selling_price > 0).all():
        cost = costs.get((item.name or "").strip().lower())
        if cost and cost > item.selling_price:
            found.append((item, cost - item.selling_price))
    if not found:
        return None
    found.sort(key=lambda pair: pair[1], reverse=True)
    item, loss = found[0]
    unit = item.unit or "unit"
    body = (f"{item.name.title()} costs you {_money(costs[(item.name or '').strip().lower()])} "
            f"but you sell it at {_money(item.selling_price)} — you lose "
            f"{_money(loss)} on every {unit} you sell.")
    if len(found) > 1:
        body += f"\n\n{len(found) - 1} other product(s) are the same."
    body += "\n\nCheck your prices on the Inventory page."
    return _insight("below_cost", "⚠️ You are selling below cost", body,
                    link="/inventory", weight=int(loss) + 1_000_000)


def _cost_crept_up(db, owner_phone):
    """A cost that rose while the price stood still — felt, rarely measured."""
    from business_facts import _in_movements, _weighted_average

    best = None
    for item in db.query(InventoryItem).filter(
            InventoryItem.owner_phone == owner_phone).all():
        movements = _in_movements(db, owner_phone, item.id, None)
        if len(movements) < _MIN_ENTRIES_FOR_TREND:
            continue
        earlier = movements[:-1]
        latest = movements[-1]
        earlier_avg = _weighted_average(earlier)[0]
        if not earlier_avg or not latest.unit_price:
            continue
        rise = latest.unit_price - earlier_avg
        if rise <= 0:
            continue
        pct = 100.0 * rise / earlier_avg
        if pct < _COST_RISE_PCT:
            continue
        if best is None or rise > best[1]:
            best = (item, rise, pct, earlier_avg, latest.unit_price)
    if not best:
        return None

    item, rise, pct, earlier_avg, latest = best
    unit = item.unit or "unit"
    body = (f"{item.name.title()} used to cost you about {_money(earlier_avg)} per {unit}. "
            f"You last bought it at {_money(latest)} — {_money(rise)} more ({pct:.0f}%).")
    if item.selling_price:
        margin = item.selling_price - latest
        if margin > 0:
            body += (f"\n\nYour price is still {_money(item.selling_price)}, so you now make "
                     f"{_money(margin)} per {unit} instead of "
                     f"{_money(item.selling_price - earlier_avg)}.")
        else:
            body += (f"\n\nAt your price of {_money(item.selling_price)} you are now losing "
                     f"money on it.")
    return _insight("cost_up", f"📈 {item.name.title()} is costing you more", body,
                    link="/inventory", weight=int(rise))


def _runs_out_this_week(db, owner_phone):
    """Predicted from this product's own pace, for items nobody set an alert on.

    Items with a low-stock alert already have their own notification; this is
    for everything else, which is most of them.
    """
    from business_facts import _sale_lines

    sold = {}
    for name, qty, _rev in _sale_lines(db, owner_phone, "days:30"):
        if name:
            sold[name] = sold.get(name, 0.0) + qty
    if not sold:
        return None

    soonest = None
    for item in db.query(InventoryItem).filter(
            InventoryItem.owner_phone == owner_phone,
            InventoryItem.quantity > 0).all():
        if item.low_stock_alert is not None:
            continue                     # the low-stock alert owns this one
        qty_sold = sold.get((item.name or "").strip().lower())
        if not qty_sold:
            continue
        per_day = qty_sold / 30.0
        days_left = float(item.quantity or 0) / per_day if per_day else None
        if days_left is None or days_left > _RUNWAY_DAYS:
            continue
        if soonest is None or days_left < soonest[1]:
            soonest = (item, days_left, per_day)
    if not soonest:
        return None

    item, days_left, per_day = soonest
    unit = item.unit or "unit"
    when = ("today" if days_left < 1 else
            "tomorrow" if days_left < 2 else f"in about {int(round(days_left))} days")
    body = (f"You have {float(item.quantity or 0):g} {unit}(s) of {item.name.title()} left "
            f"and have been selling about {per_day:.1f} a day.\n\n"
            f"At that pace you run out {when}.")
    return _insight("runs_out", f"🛒 {item.name.title()} runs out {when}", body,
                    link="/inventory", weight=int(10_000 / max(days_left, 0.5)))


def _regular_gone_quiet(db, owner_phone):
    """A customer who used to come and stopped — worth a call, easily missed."""
    from sqlalchemy import func
    from reports import get_owner_transaction_query

    rows = (get_owner_transaction_query(db, owner_phone)
            .filter(Transaction.customer_id.isnot(None),
                    Transaction.type.in_(("SALE", "BUY")))
            .with_entities(Transaction.customer_id,
                           func.count(Transaction.id),
                           func.max(Transaction.created_at),
                           func.sum(Transaction.amount))
            .group_by(Transaction.customer_id).all())
    cutoff = utcnow() - timedelta(days=_QUIET_DAYS)
    candidates = [
        r for r in rows
        if (r[1] or 0) >= _MIN_VISITS_TO_BE_A_REGULAR and r[2] and r[2] < cutoff
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda r: r[3] or 0, reverse=True)
    customer_id, visits, last_seen, spent = candidates[0]
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return None

    days = (utcnow() - last_seen).days
    body = (f"{customer.name.title()} bought from you {visits} times "
            f"({_money(spent)} in total) but has not been back in {days} days.")
    if (customer.balance or 0) > 0:
        body += f"\n\nThey also owe {_money(customer.balance)}."
    body += "\n\nA quick call might bring them back."
    return _insight("quiet_regular", f"👤 {customer.name.title()} has gone quiet", body,
                    link="/customers", weight=int(spent or 0) // 100)


_GENERATORS = (
    ("below_cost", _selling_below_cost),      # takes the cost map
    ("cost_up", _cost_crept_up),
    ("runs_out", _runs_out_this_week),
    ("quiet_regular", _regular_gone_quiet),
)


def find_insights(db, owner_phone):
    """Everything worth telling this business today, most valuable first.

    One failing generator must not cost the business the others, so each is
    isolated.
    """
    from business_facts import _avg_cost_by_name

    try:
        costs = _avg_cost_by_name(db, owner_phone)
    except Exception:
        _log.exception("insight cost map failed for %s", owner_phone)
        costs = {}

    found = []
    for key, generator in _GENERATORS:
        try:
            result = (generator(db, owner_phone, costs) if key == "below_cost"
                      else generator(db, owner_phone))
        except Exception:
            _log.exception("insight %s failed for %s", key, owner_phone)
            continue
        if result:
            found.append(result)
    found.sort(key=lambda i: i["weight"], reverse=True)
    return found
