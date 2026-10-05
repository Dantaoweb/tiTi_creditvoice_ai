"""
What tiTi knows about a business, held as facts rather than as patterns.

The older query handling grew one regex and one hand-written sentence per
question, which does not reach "answer anything about my business" — it reaches
about ten shapes of question and stops. This is the other half: every
answerable fact is registered once (what triggers it, what it needs, how it is
worked out, how it reads), and one router turns a sentence into metric +
product + period. A new question is usually a new entry, not new code, and a
new way of saying an old question is a new trigger.

Nothing here calls a language model. Everything is counted from what the
business itself recorded.
"""
import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from models import InventoryItem, InventoryMovement, Transaction, utcnow

_log = logging.getLogger(__name__)


# ── Periods ──────────────────────────────────────────────────────────────────
# Ordered longest-first so "last month" is read before "month".

_PERIODS = [
    ("today",        r"\btoday\b|\bso far today\b"),
    ("yesterday",    r"\byesterday\b"),
    ("this_week",    r"\bthis week\b|\bthe week\b"),
    ("last_week",    r"\blast week\b|\bpast week\b"),
    ("this_month",   r"\bthis month\b"),
    ("last_month",   r"\blast month\b|\bpast month\b"),
    ("this_year",    r"\bthis year\b"),
    ("all_time",     r"\ball\s*time\b|\bever\b|\balways\b|\bso far\b|\bin total\b|\boverall\b"),
]

_PERIOD_LABELS = {
    "today": "today", "yesterday": "yesterday",
    "this_week": "this week", "last_week": "last week",
    "this_month": "this month", "last_month": "last month",
    "this_year": "this year", "all_time": "all together",
    None: "all together",
}


def _period_range(period):
    """(start, end) for a period key, or (None, None) for everything."""
    now = utcnow()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "today":
        return midnight, midnight + timedelta(days=1)
    if period == "yesterday":
        return midnight - timedelta(days=1), midnight
    if period == "this_week":
        return midnight - timedelta(days=midnight.weekday()), now
    if period == "last_week":
        this_week = midnight - timedelta(days=midnight.weekday())
        return this_week - timedelta(days=7), this_week
    if period == "this_month":
        return midnight.replace(day=1), now
    if period == "last_month":
        first = midnight.replace(day=1)
        return (first - timedelta(days=1)).replace(day=1), first
    if period == "this_year":
        return midnight.replace(month=1, day=1), now
    return None, None


def _detect_period(text):
    for key, pattern in _PERIODS:
        if re.search(pattern, text):
            return key, re.sub(pattern, " ", text)
    m = re.search(r"\blast\s+(\d{1,3})\s+days?\b", text)
    if m:
        return f"days:{m.group(1)}", re.sub(r"\blast\s+\d{1,3}\s+days?\b", " ", text)
    return None, text


def _range_for(period):
    if period and period.startswith("days:"):
        days = int(period.split(":", 1)[1] or 0)
        now = utcnow()
        return now - timedelta(days=days), now
    return _period_range(period)


def _period_label(period):
    if period and period.startswith("days:"):
        return f"in the last {period.split(':', 1)[1]} days"
    label = _PERIOD_LABELS.get(period, "all together")
    return label if label.startswith(("this", "last", "in ")) else label


# ── Money ────────────────────────────────────────────────────────────────────

def _money(value):
    try:
        return f"₦{int(round(float(value))):,}"
    except (TypeError, ValueError):
        return "₦0"


# ── The facts ────────────────────────────────────────────────────────────────
# Each computer is given (db, owner_phone, ask) and returns a reply string, or
# None to let the older handlers try — never a half-answer.


@dataclass
class Ask:
    """One question, understood."""
    metric: str
    period: Optional[str] = None
    product_text: str = ""
    item: object = None


def _in_movements(db, owner_phone, item_id, period=None):
    """Stock that came IN with a cost on it — the record of what they pay.

    A movement with no price is not a zero-cost purchase, it is a purchase
    nobody priced, so it is left out of every average rather than dragging it
    down.
    """
    q = db.query(InventoryMovement).filter(
        InventoryMovement.owner_phone == owner_phone,
        InventoryMovement.item_id == item_id,
        InventoryMovement.movement_type == "IN",
        InventoryMovement.unit_price.isnot(None),
        InventoryMovement.unit_price > 0,
        InventoryMovement.quantity > 0,
    )
    start, end = _range_for(period)
    if start is not None:
        q = q.filter(InventoryMovement.created_at >= start,
                     InventoryMovement.created_at < end)
    return q.order_by(InventoryMovement.created_at.asc()).all()


def _weighted_average(movements):
    """Weighted by quantity — buying 50 bags at ₦68k and 1 at ₦90k averages
    near ₦68k, which is what the business actually paid."""
    qty = sum(float(m.quantity or 0) for m in movements)
    spent = sum(float(m.quantity or 0) * float(m.unit_price or 0) for m in movements)
    return (spent / qty) if qty else None, qty, spent


def _no_cost_yet(item, period):
    """Said the same way everywhere: we do not know, and here is why."""
    when = "" if period in (None, "all_time") else f" {_period_label(period)}"
    return (f"I don't know what you pay for *{item.name.title()}*{when} — no cost price "
            f"has been recorded with your stock.\n\n"
            f"Add it when you add stock (\"add stock {item.name.lower()} 10 cost 2000 sell 2500\") "
            f"and I can track it from then on.")


def _fact_avg_cost(db, owner_phone, ask):
    movements = _in_movements(db, owner_phone, ask.item.id, ask.period)
    if not movements:
        return _no_cost_yet(ask.item, ask.period)
    avg, qty, spent = _weighted_average(movements)
    name = ask.item.name.title()
    unit = ask.item.unit or "unit"
    lines = [f"*{name}* costs you about *{_money(avg)}* per {unit} on average "
             f"({_period_label(ask.period)})."]
    lines.append(f"Based on {len(movements)} stock entr{'y' if len(movements) == 1 else 'ies'} — "
                 f"{qty:g} {unit}(s) for {_money(spent)}.")

    first, last = movements[0].unit_price, movements[-1].unit_price
    if len(movements) > 1 and first and last and first != last:
        direction = "up" if last > first else "down"
        change = abs(last - first)
        pct = round(100.0 * change / first) if first else 0
        lines.append(f"It has gone {direction} from {_money(first)} to {_money(last)} "
                     f"({'+' if direction == 'up' else '−'}{_money(change)}, {pct}%).")

    sell = ask.item.selling_price
    if sell and avg:
        margin = sell - avg
        pct = round(100.0 * margin / sell) if sell else 0
        if margin > 0:
            lines.append(f"You sell at {_money(sell)}, so you make about "
                         f"*{_money(margin)}* per {unit} ({pct}%).")
        else:
            lines.append(f"⚠️ You sell at {_money(sell)} — that is *below* what it costs you. "
                         f"You lose about {_money(abs(margin))} per {unit}.")
    return "\n".join(lines)


def _fact_last_cost(db, owner_phone, ask):
    movements = _in_movements(db, owner_phone, ask.item.id, ask.period)
    if not movements:
        return _no_cost_yet(ask.item, ask.period)
    last = movements[-1]
    when = last.created_at.strftime("%d %b %Y") if last.created_at else "recently"
    unit = ask.item.unit or "unit"
    reply = (f"You last bought *{ask.item.name.title()}* at *{_money(last.unit_price)}* "
             f"per {unit}, on {when}.")
    if len(movements) > 1:
        avg, _qty, _spent = _weighted_average(movements)
        reply += f"\nYour average is {_money(avg)}."
    return reply


def _fact_cost_trend(db, owner_phone, ask):
    movements = _in_movements(db, owner_phone, ask.item.id, ask.period)
    if len(movements) < 2:
        if not movements:
            return _no_cost_yet(ask.item, ask.period)
        return (f"You have only one cost recorded for *{ask.item.name.title()}* — "
                f"{_money(movements[0].unit_price)}. Record a few more stock entries "
                f"and I can show you whether it is rising.")
    first, last = movements[0].unit_price, movements[-1].unit_price
    unit = ask.item.unit or "unit"
    if first == last:
        return (f"*{ask.item.name.title()}* has cost you {_money(first)} per {unit} "
                f"throughout — no change.")
    direction = "risen" if last > first else "fallen"
    change = abs(last - first)
    pct = round(100.0 * change / first) if first else 0
    lines = [f"*{ask.item.name.title()}* has {direction} from {_money(first)} to "
             f"{_money(last)} per {unit} — {_money(change)} ({pct}%)."]
    sell = ask.item.selling_price
    if sell and last > first:
        # The part a trader feels but may not have worked out.
        lines.append(f"Your selling price is still {_money(sell)}, so each {unit} now "
                     f"earns you {_money(change)} less than it did.")
    return "\n".join(lines)


def _fact_total_spent(db, owner_phone, ask):
    movements = _in_movements(db, owner_phone, ask.item.id, ask.period)
    if not movements:
        return _no_cost_yet(ask.item, ask.period)
    _avg, qty, spent = _weighted_average(movements)
    unit = ask.item.unit or "unit"
    return (f"You have spent *{_money(spent)}* on *{ask.item.name.title()}* "
            f"{_period_label(ask.period)} — {qty:g} {unit}(s) across "
            f"{len(movements)} stock entr{'y' if len(movements) == 1 else 'ies'}.")


def _fact_margin(db, owner_phone, ask):
    item = ask.item
    sell = item.selling_price
    if not sell:
        return (f"No selling price is set for *{item.name.title()}*, so I cannot work out "
                f"your margin. Set it on the Inventory page.")
    movements = _in_movements(db, owner_phone, item.id, None)
    avg = _weighted_average(movements)[0] if movements else (item.cost_price or None)
    if not avg:
        return _no_cost_yet(item, None)
    unit = item.unit or "unit"
    margin = sell - avg
    pct = round(100.0 * margin / sell) if sell else 0
    if margin <= 0:
        return (f"⚠️ *{item.name.title()}* costs you {_money(avg)} and you sell at "
                f"{_money(sell)} — you lose {_money(abs(margin))} per {unit}.")
    return (f"*{item.name.title()}*: costs {_money(avg)}, sells at {_money(sell)} — "
            f"you make *{_money(margin)}* per {unit} ({pct}%).")


def _fact_best_seller(db, owner_phone, ask):
    """Top products by what they brought in, from the sales themselves."""
    from sqlalchemy import func
    from reports import get_owner_transaction_query

    q = get_owner_transaction_query(db, owner_phone)
    start, end = _range_for(ask.period)
    if start is not None:
        q = q.filter(Transaction.created_at >= start, Transaction.created_at < end)
    rows = (q.filter(Transaction.product.isnot(None),
                     Transaction.type.in_(("SALE", "BUY")))
            .with_entities(Transaction.product,
                           func.sum(Transaction.amount),
                           func.count(Transaction.id))
            .group_by(Transaction.product)
            .order_by(func.sum(Transaction.amount).desc())
            .limit(5).all())
    rows = [r for r in rows if r[0]]
    if not rows:
        return (f"I have no product sales recorded {_period_label(ask.period)}, so I cannot "
                f"tell you your best seller yet.")
    lines = [f"Your best sellers {_period_label(ask.period)}:"]
    for name, total, count in rows:
        lines.append(f"• {str(name).title()} — {_money(total)} across {count} sale(s)")
    return "\n".join(lines)


def _fact_dead_stock(db, owner_phone, ask):
    """Money sitting still: stock on hand that nothing has sold for 60 days."""
    from sqlalchemy import func
    from reports import get_owner_transaction_query

    since = utcnow() - timedelta(days=60)
    sold = {
        (row[0] or "").strip().lower()
        for row in get_owner_transaction_query(db, owner_phone)
        .filter(Transaction.created_at >= since, Transaction.product.isnot(None))
        .with_entities(Transaction.product).distinct().all()
    }
    items = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        InventoryItem.quantity > 0,
    ).all()
    idle = [i for i in items if (i.name or "").strip().lower() not in sold]
    if not idle:
        return "Nothing is sitting idle — everything in your stock has sold in the last 60 days ✓"

    def tied_up(i):
        cost = i.cost_price or i.selling_price or 0
        return float(i.quantity or 0) * float(cost)

    idle.sort(key=tied_up, reverse=True)
    total = sum(tied_up(i) for i in idle)
    lines = [f"*{len(idle)} item(s)* have not sold in 60 days"
             + (f" — about {_money(total)} tied up:" if total else ":")]
    for i in idle[:10]:
        value = tied_up(i)
        lines.append(f"• {i.name.title()} — {i.quantity:g} {i.unit or 'unit'}(s)"
                     + (f", {_money(value)}" if value else ""))
    if len(idle) > 10:
        lines.append(f"…and {len(idle) - 10} more")
    return "\n".join(lines)


def _avg_cost_by_name(db, owner_phone):
    """Every product's weighted average cost, keyed by lowercase name.

    One pass instead of a query per sale line — a busy month is thousands of
    lines, and this runs while someone waits for a reply.
    """
    from sqlalchemy import func

    rows = (
        db.query(InventoryItem.name,
                 func.sum(InventoryMovement.quantity * InventoryMovement.unit_price),
                 func.sum(InventoryMovement.quantity))
        .join(InventoryMovement, InventoryMovement.item_id == InventoryItem.id)
        .filter(InventoryItem.owner_phone == owner_phone,
                InventoryMovement.movement_type == "IN",
                InventoryMovement.unit_price.isnot(None),
                InventoryMovement.unit_price > 0,
                InventoryMovement.quantity > 0)
        .group_by(InventoryItem.name).all()
    )
    costs = {}
    for name, spent, qty in rows:
        if name and qty:
            costs[name.strip().lower()] = float(spent) / float(qty)
    # An item with no movement history can still carry a cost price typed in by
    # hand — better than nothing, and clearly marked as the fallback.
    for item in db.query(InventoryItem).filter(
            InventoryItem.owner_phone == owner_phone,
            InventoryItem.cost_price.isnot(None),
            InventoryItem.cost_price > 0).all():
        costs.setdefault((item.name or "").strip().lower(), float(item.cost_price))
    return costs


def _sale_lines(db, owner_phone, period):
    """(product, quantity, revenue) for each thing sold in the period.

    Reads the itemised lines where a sale has them and falls back to the sale
    itself where it does not, so a quick one-line sale still counts.
    """
    from models import TransactionItem
    from reports import get_owner_transaction_query

    q = get_owner_transaction_query(db, owner_phone)
    start, end = _range_for(period)
    if start is not None:
        q = q.filter(Transaction.created_at >= start, Transaction.created_at < end)
    sales = q.filter(Transaction.type.in_(("SALE", "BUY"))).all()
    if not sales:
        return []

    ids = [s.id for s in sales]
    items_by_tx = {}
    for line in db.query(TransactionItem).filter(
            TransactionItem.transaction_id.in_(ids)).all():
        items_by_tx.setdefault(line.transaction_id, []).append(line)

    lines = []
    for sale in sales:
        rows = items_by_tx.get(sale.id)
        if rows:
            for row in rows:
                lines.append(((row.product or "").strip().lower(),
                              float(row.quantity or 1), float(row.total or 0)))
        else:
            lines.append(((sale.product or "").strip().lower(),
                          float(sale.quantity or 1), float(sale.amount or 0)))
    return lines


def _fact_profit(db, owner_phone, ask):
    """What was actually made, not what was taken in.

    Only the part with a known cost can be counted, so the reply says how much
    of the revenue that covers rather than quietly treating unknown costs as
    zero — which would report every unpriced sale as pure profit.
    """
    lines = _sale_lines(db, owner_phone, ask.period)
    if not lines:
        return f"No sales recorded {_period_label(ask.period)}."

    costs = _avg_cost_by_name(db, owner_phone)
    revenue = sum(rev for _n, _q, rev in lines)
    known_revenue, cost_total = 0.0, 0.0
    for name, qty, rev in lines:
        unit_cost = costs.get(name)
        if unit_cost is None:
            continue
        known_revenue += rev
        cost_total += qty * unit_cost

    if known_revenue <= 0:
        return (f"You sold *{_money(revenue)}* {_period_label(ask.period)}, but I cannot work "
                f"out your profit — no cost prices are recorded for what you sold.\n\n"
                f"Add a cost when you add stock and I can tell you what you are making.")

    profit = known_revenue - cost_total
    pct = round(100.0 * profit / known_revenue) if known_revenue else 0
    lines_out = [f"{_period_label(ask.period).capitalize()} you sold *{_money(revenue)}* "
                 f"and made about *{_money(profit)}* profit ({pct}%)."]
    lines_out.append(f"That is {_money(known_revenue)} of sales minus {_money(cost_total)} "
                     f"it cost you.")
    if known_revenue < revenue * 0.99:
        missing = revenue - known_revenue
        lines_out.append(f"⚠️ {_money(missing)} of your sales have no cost recorded, so they "
                         f"are not counted in that profit.")
    return "\n".join(lines_out)


def _fact_sales_total(db, owner_phone, ask):
    """Sales for the periods the older handler cannot do.

    It already answers today, this week and this month, and answers them well —
    this covers yesterday, last week, last month, the year and "last N days".
    """
    if ask.period in (None, "today", "this_week", "this_month"):
        return None                        # let the existing answer stand
    from reports import get_owner_transaction_query

    start, end = _range_for(ask.period)
    q = get_owner_transaction_query(db, owner_phone)
    if start is not None:
        q = q.filter(Transaction.created_at >= start, Transaction.created_at < end)
    rows = q.all()
    if not rows:
        return f"No sales recorded {_period_label(ask.period)}."

    cash = sum(r.amount or 0 for r in rows if r.type == "SALE")
    credit = sum(r.amount or 0 for r in rows if r.type == "BUY")
    paid = sum(r.amount or 0 for r in rows if r.type == "PAY")
    return (f"Sales {_period_label(ask.period)}: *{_money(cash + credit)}*\n"
            f"• Cash/direct: {_money(cash)}\n"
            f"• Credit sales: {_money(credit)}\n"
            f"• Payments received: {_money(paid)}\n"
            f"• Transactions: {len(rows)}")


def _fact_stock_value(db, owner_phone, ask):
    """What is sitting on the shelf, at what it cost and what it would fetch."""
    items = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        InventoryItem.quantity > 0).all()
    if not items:
        return "You have nothing in stock right now."

    costs = _avg_cost_by_name(db, owner_phone)
    at_cost, at_selling, unpriced = 0.0, 0.0, 0
    for item in items:
        qty = float(item.quantity or 0)
        unit_cost = costs.get((item.name or "").strip().lower())
        if unit_cost:
            at_cost += qty * unit_cost
        else:
            unpriced += 1
        if item.selling_price:
            at_selling += qty * float(item.selling_price)

    lines = [f"You have *{len(items)} product(s)* in stock."]
    if at_cost:
        lines.append(f"They cost you about *{_money(at_cost)}*.")
    if at_selling:
        lines.append(f"Sold at your prices they would bring in {_money(at_selling)}"
                     + (f" — about {_money(at_selling - at_cost)} profit." if at_cost else "."))
    if unpriced:
        lines.append(f"({unpriced} product(s) have no cost recorded, so they are not "
                     f"counted in the cost figure.)")
    return "\n".join(lines)


def _fact_runs_out(db, owner_phone, ask):
    """When the shelf empties, from how fast it has actually been selling.

    Thirty days of this product's own sales, not a guess and not a fixed
    threshold — a shop selling four bags a day and one selling four a month
    should not be told the same thing.
    """
    item = ask.item
    name = (item.name or "").strip().lower()
    since = utcnow() - timedelta(days=30)
    lines = [l for l in _sale_lines(db, owner_phone, "days:30") if l[0] == name]
    sold = sum(qty for _n, qty, _rev in lines)
    on_hand = float(item.quantity or 0)
    unit = item.unit or "unit"

    if sold <= 0:
        if on_hand <= 0:
            return f"You have no *{item.name.title()}* left, and none has sold in 30 days."
        return (f"You have *{on_hand:g} {unit}(s)* of {item.name.title()}, but none has sold "
                f"in the last 30 days — so I cannot say when it will run out.")

    per_day = sold / 30.0
    if on_hand <= 0:
        return (f"You have no *{item.name.title()}* left. You were selling about "
                f"{per_day:.1f} {unit}(s) a day — worth restocking.")
    days_left = on_hand / per_day
    when = "today" if days_left < 1 else (
        "tomorrow" if days_left < 2 else f"in about {int(round(days_left))} days")
    reply = (f"*{item.name.title()}*: {on_hand:g} {unit}(s) left, selling about "
             f"{per_day:.1f} a day — you run out *{when}*.")
    if days_left < 7:
        reply += "\n⚠️ Time to restock."
    return reply


def _fact_quiet_customers(db, owner_phone, ask):
    """Customers who used to buy and have gone quiet."""
    from models import Customer
    from reports import get_owner_transaction_query

    since = utcnow() - timedelta(days=60)
    recent_ids = {
        row[0] for row in get_owner_transaction_query(db, owner_phone)
        .filter(Transaction.created_at >= since,
                Transaction.customer_id.isnot(None))
        .with_entities(Transaction.customer_id).distinct().all()
    }
    customers = db.query(Customer).filter(Customer.owner_phone == owner_phone).all()
    quiet = [c for c in customers
             if c.id not in recent_ids and (c.last_transaction_at or c.created_at)]
    if not customers:
        return "You have no customers on record yet."
    if not quiet:
        return "Every customer on your list has bought something in the last 60 days ✓"

    quiet.sort(key=lambda c: c.last_transaction_at or c.created_at or utcnow())
    lines = [f"*{len(quiet)} customer(s)* have not bought in 60 days:"]
    for c in quiet[:10]:
        last = c.last_transaction_at or c.created_at
        when = f" — last seen {last.strftime('%d %b %Y')}" if last else ""
        owing = f", owes {_money(c.balance)}" if (c.balance or 0) > 0 else ""
        lines.append(f"• {c.name.title()}{when}{owing}")
    if len(quiet) > 10:
        lines.append(f"…and {len(quiet) - 10} more")
    return "\n".join(lines)


# ── The registry ─────────────────────────────────────────────────────────────
# `triggers` are what the question sounds like, including the way people
# actually type on a phone. `needs_product` says the fact is about one item, so
# the router must find which. Order matters: the first metric whose trigger
# matches wins, so the specific ones come before the general ones.

METRICS = [
    {
        "key": "cost_trend", "needs_product": True, "compute": _fact_cost_trend,
        "triggers": [
            r"\bcost\s+trend\b", r"\bprice\s+trend\b",
            r"(?:is|are|has|have)\s+.*\b(?:cost|price)\b.*\b(?:going up|gone up|rising|risen|increas|going down|gone down|fall|drop)",
            r"\b(?:how much more|how much less)\b.*\b(?:cost|pay)\b",
            r"\b(?:cost|price)\b.*\b(?:change[d]?|increase[d]?|dropped|rise|risen)\b",
        ],
    },
    {
        "key": "last_cost", "needs_product": True, "compute": _fact_last_cost,
        "triggers": [
            r"\blast\s+(?:cost|price)\b",
            r"\b(?:last|latest|recent)\s+time\s+i\s+(?:bought|buy)\b",
            r"\bhow much did i (?:buy|pay for)\b.*\b(?:last|recently)\b",
            r"\b(?:current|latest)\s+(?:buying|cost)\s+price\b",
        ],
    },
    {
        "key": "avg_cost", "needs_product": True, "compute": _fact_avg_cost,
        "triggers": [
            r"\b(?:average|avg|mean)\s+(?:cost|price|buying price)\b",
            r"\b(?:cost|buying)\s+price\b",
            r"\bhow much (?:do|does|did) (?:i|it|we) (?:buy|pay for|get)\b",
            r"\bwhat (?:do|did) i (?:buy|pay)\b",
            r"\bhow much (?:do|did) i buy\b",
            r"\bwetin i dey buy\b",            # pidgin
            r"\bcost me\b",
        ],
    },
    {
        "key": "total_spent", "needs_product": True, "compute": _fact_total_spent,
        "triggers": [
            r"\bhow much have i spent\b", r"\bhow much did i spend\b",
            r"\btotal spent\b", r"\bspent on\b",
        ],
    },
    {
        # About one product. The whole-business version of this question is the
        # `profit` fact, which is why nothing here fires without a product word.
        "key": "margin", "needs_product": True, "compute": _fact_margin,
        "triggers": [
            r"\b(?:profit|margin|gain)\s+(?:on|per|from)\b",
            r"\bhow much (?:do|am) i mak(?:e|ing)\s+(?:on|per|from)\b",
            r"\bmy margin\b",
        ],
    },
    {
        "key": "runs_out", "needs_product": True, "compute": _fact_runs_out,
        "triggers": [
            r"\b(?:when|how long).*\b(?:run out|finish|last)\b",
            r"\bwill .* (?:run out|finish)\b",
            r"\bdo i need to (?:restock|buy|order)\b",
            r"\bshould i (?:restock|reorder|buy more)\b",
            r"\bhow (?:long|many days) (?:will|before)\b",
        ],
    },
    {
        "key": "profit", "needs_product": False, "compute": _fact_profit,
        "triggers": [
            r"\b(?:how much|what).*\bprofit\b",
            r"\bmy profit\b", r"\bprofit (?:this|last|today|yesterday)\b",
            r"\b(?:did|am|have) i (?:make|made|making|gain|gained)\b.*\b(?:profit|money|anything)\b",
            r"\bam i (?:making|losing) money\b",
            r"\bhow much did i (?:gain|clear)\b",
        ],
    },
    {
        "key": "stock_value", "needs_product": False, "compute": _fact_stock_value,
        "triggers": [
            r"\b(?:value|worth)\s+of\s+(?:my\s+)?(?:stock|inventory|goods)\b",
            r"\b(?:stock|inventory)\s+(?:value|worth)\b",
            r"\bhow much (?:is|are) my (?:stock|goods|inventory) worth\b",
            r"\bhow much (?:money )?(?:do i have )?(?:tied up|in stock)\b",
        ],
    },
    {
        "key": "quiet_customers", "needs_product": False, "compute": _fact_quiet_customers,
        "triggers": [
            r"\bcustomers?\b.*\b(?:stopped|not|haven'?t|hasn'?t|no longer)\b.*\b(?:buy|buying|bought|coming|come)\b",
            r"\b(?:who|which customers?)\b.*\b(?:gone quiet|stopped buying|not been)\b",
            r"\blost customers?\b", r"\bquiet customers?\b",
            r"\bcustomers?\b.*\bnot (?:seen|bought)\b",
        ],
    },
    {
        "key": "sales_total", "needs_product": False, "compute": _fact_sales_total,
        "triggers": [
            r"\bhow much did i (?:sell|make|earn)\b",
            r"\b(?:total|my)\s+(?:sales|revenue|income)\b",
            r"\bwhat did i (?:sell|make)\b",
            r"\bsales\s+(?:yesterday|last week|last month|this year)\b",
        ],
    },
    {
        "key": "best_seller", "needs_product": False, "compute": _fact_best_seller,
        "triggers": [
            r"\bbest\s*(?:selling|seller)\b", r"\btop\s+(?:product|selling|seller|item)",
            r"\bwhat (?:sells|sold) (?:the )?most\b", r"\bmost sold\b",
            r"\bwhich (?:product|item) (?:sells|sold) (?:the )?(?:most|best)\b",
        ],
    },
    {
        "key": "dead_stock", "needs_product": False, "compute": _fact_dead_stock,
        "triggers": [
            r"\bdead\s+stock\b", r"\bnot\s+selling\b", r"\bslow\s*(?:moving|seller)",
            r"\bwhich (?:product|item|goods?).*\b(?:not|never) (?:sell|sold|moving)\b",
            r"\bidle stock\b", r"\bstuck (?:stock|goods)\b",
        ],
    },
]


# ── The router ───────────────────────────────────────────────────────────────

# Words that are never part of a product name, stripped before the lookup.
_NOISE = re.compile(
    r"\b(?:what|whats|what's|is|are|the|my|our|for|of|a|an|do|does|did|i|we|me|how|much|many"
    r"|please|abeg|tell|show|give|know|about|on|per|unit|price|cost|average|avg|mean|buying"
    r"|buy|bought|pay|paid|spent|spend|total|profit|margin|gain|make|making|now|currently"
    r"|trend|change|changed|last|latest|recent|time|it|this|that|been|has|have|up|down"
    r"|rising|risen|increase|increased|dropped|fall|fallen|going|gone|wetin|dey|abi|na)\b",
    re.I,
)


def _clean_product_text(text):
    text = _NOISE.sub(" ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _matching_metrics(text):
    """Every metric whose trigger fires, in registry order."""
    hits = []
    for metric in METRICS:
        for trigger in metric["triggers"]:
            if re.search(trigger, text, re.IGNORECASE):
                hits.append(metric)
                break
    return hits


def answer(db, owner_phone, text, recorded_by_id=None):
    """Answer a question about this business, or return None to let the older
    handlers try. A half-answer is worse than no answer, so anything uncertain
    falls through rather than guessing."""
    if not text or not owner_phone:
        return None
    candidates = _matching_metrics(" " + text.strip().lower() + " ")
    if not candidates:
        return None

    period, remainder = _detect_period(" " + text.strip().lower() + " ")
    product_name = _clean_product_text(remainder)
    item = None
    if product_name:
        from query_handler import _find_product
        item = _find_product(db, owner_phone, product_name)

    # "Am I making profit this month" and "what do I make on rice" share words.
    # A metric about one product only wins when a product was actually named,
    # so an unnamed product never turns a question about the whole business
    # into "which product do you mean?".
    ordered = ([m for m in candidates if not m["needs_product"] or item]
               + [m for m in candidates if m["needs_product"] and not item])

    for metric in ordered:
        if metric["needs_product"] and not item:
            known = (db.query(InventoryItem)
                     .filter(InventoryItem.owner_phone == owner_phone)
                     .order_by(InventoryItem.id.desc()).limit(5).all())
            if not known:
                return None          # no stock at all — not our question to answer
            examples = ", ".join(i.name.title() for i in known)
            return (f"Which product do you mean? For example: {examples}.\n\n"
                    f"Try \"average cost of {known[0].name.lower()}\".")
        ask = Ask(metric=metric["key"], period=period,
                  product_text=product_name, item=item)
        try:
            reply = metric["compute"](db, owner_phone, ask)
        except Exception:
            _log.exception("business fact %s failed", metric["key"])
            return None
        if reply:
            return reply
        # The metric declined (it knows another handler answers this better) —
        # try the next one that matched.
    return None
