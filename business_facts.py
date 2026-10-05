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
        "key": "margin", "needs_product": True, "compute": _fact_margin,
        "triggers": [
            r"\b(?:profit|margin|gain)\b.*\b(?:on|per|for)\b",
            r"\bhow much (?:do|am) i mak(?:e|ing)\b",
            r"\bam i making (?:money|profit|anything)\b",
            r"\bmy margin\b",
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


def _match_metric(text):
    for metric in METRICS:
        for trigger in metric["triggers"]:
            if re.search(trigger, text, re.IGNORECASE):
                return metric
    return None


def answer(db, owner_phone, text, recorded_by_id=None):
    """Answer a question about this business, or return None to let the older
    handlers try. A half-answer is worse than no answer, so anything uncertain
    falls through rather than guessing."""
    if not text or not owner_phone:
        return None
    lowered = " " + text.strip().lower() + " "
    metric = _match_metric(lowered)
    if not metric:
        return None

    period, remainder = _detect_period(lowered)
    ask = Ask(metric=metric["key"], period=period)

    if metric["needs_product"]:
        from query_handler import _find_product
        name = _clean_product_text(remainder)
        ask.product_text = name
        item = _find_product(db, owner_phone, name) if name else None
        if not item:
            # The question was clear, the product was not. Asking is better than
            # guessing, and far better than "I don't understand".
            known = (db.query(InventoryItem)
                     .filter(InventoryItem.owner_phone == owner_phone)
                     .order_by(InventoryItem.id.desc()).limit(5).all())
            if not known:
                return None          # no stock at all — not our question to answer
            examples = ", ".join(i.name.title() for i in known)
            return (f"Which product do you mean? For example: {examples}.\n\n"
                    f"Try \"average cost of {known[0].name.lower()}\".")
        ask.item = item

    try:
        return metric["compute"](db, owner_phone, ask)
    except Exception:
        _log.exception("business fact %s failed", metric["key"])
        return None
