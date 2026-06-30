"""
Natural language query handler for tiTi.

Intercepts conversational queries BEFORE the transaction parser runs, so phrases
like "how much does Bankole owe me?" are answered directly instead of being
misclassified as incomplete transactions asking for an amount.

Returns a formatted string response, or None if no query pattern matched.
"""

import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from models import Transaction, Customer, InventoryItem


# ── Formatting ────────────────────────────────────────────────────────────────

def _fmt(amount) -> str:
    if amount is None:
        return "₦0"
    try:
        v = int(round(float(amount)))
        return f"₦{v:,}"
    except Exception:
        return "₦0"


def _date_str(dt) -> Optional[str]:
    if not dt:
        return None
    d = dt.date() if hasattr(dt, "date") else dt
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{d.day} {months[d.month - 1]} {d.year}"


def _overdue_label(dt) -> str:
    if not dt:
        return ""
    d = dt.date() if hasattr(dt, "date") else dt
    today = datetime.now(timezone.utc).date()
    if d < today:
        days = (today - d).days
        return f"overdue by {days} day{'s' if days != 1 else ''}"
    elif d == today:
        return "due today"
    else:
        days = (d - today).days
        return f"due in {days} day{'s' if days != 1 else ''}"


# ── Name cleaning ─────────────────────────────────────────────────────────────

_DROP_WORDS = {
    "please", "kindly", "just", "quickly", "a", "an", "the", "my", "our",
    "me", "you", "us", "him", "her", "them", "it",
    "for", "of", "to", "from", "about", "in", "on", "at",
    "with", "by", "into", "up", "is", "are", "was", "has", "have",
    "that", "this", "which", "who", "what",
    "customer", "client", "debtor", "buyer", "person", "people",
    "record", "account", "there",
    # Business nouns that trail into captured name groups
    "debt", "balance", "payment", "amount", "money", "credit",
    "due", "date", "fee", "fees", "loan", "owing",
}


def _clean_entity(raw: str) -> str:
    raw = re.sub(r"[?!.,;:\"']+", "", raw).strip().lower()
    words = [w for w in raw.split() if w and w not in _DROP_WORDS]
    return " ".join(words).strip()


# ── Database helpers ──────────────────────────────────────────────────────────

def _find_customers(db, owner_phone: str, name: str, recorded_by_id):
    if not name or len(name) < 2:
        return []
    q = db.query(Customer).filter(
        Customer.owner_phone == owner_phone,
        Customer.name.ilike(f"%{name}%"),
    )
    if recorded_by_id:
        q = (
            q.join(Transaction, Transaction.customer_id == Customer.id)
             .filter(Transaction.recorded_by_id == recorded_by_id)
             .distinct(Customer.id)
        )
    return q.all()


def _balance(db, customer_id: int, recorded_by_id) -> float:
    def _sum(tx_type):
        q = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.customer_id == customer_id,
            Transaction.type == tx_type,
            Transaction.is_voided.isnot(True),
        )
        if recorded_by_id:
            q = q.filter(Transaction.recorded_by_id == recorded_by_id)
        return q.scalar() or 0
    return _sum("BUY") - _sum("PAY")


def _totals(db, customer_id: int, recorded_by_id):
    def _sum(tx_type):
        q = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.customer_id == customer_id,
            Transaction.type == tx_type,
            Transaction.is_voided.isnot(True),
        )
        if recorded_by_id:
            q = q.filter(Transaction.recorded_by_id == recorded_by_id)
        return q.scalar() or 0
    return _sum("BUY"), _sum("PAY")


def _latest_due_date(db, customer_id: int, recorded_by_id):
    q = db.query(Transaction).filter(
        Transaction.customer_id == customer_id,
        Transaction.type == "BUY",
        Transaction.due_date.isnot(None),
        Transaction.is_voided.isnot(True),
    )
    if recorded_by_id:
        q = q.filter(Transaction.recorded_by_id == recorded_by_id)
    tx = q.order_by(Transaction.due_date.desc()).first()
    return tx.due_date if tx else None


def _recent_txs(db, customer_id: int, recorded_by_id, limit=7):
    q = db.query(Transaction).filter(
        Transaction.customer_id == customer_id,
        Transaction.is_voided.isnot(True),
    )
    if recorded_by_id:
        q = q.filter(Transaction.recorded_by_id == recorded_by_id)
    return q.order_by(Transaction.created_at.desc()).limit(limit).all()


def _find_product(db, owner_phone: str, name: str):
    if not name or len(name) < 2:
        return None
    return db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        InventoryItem.name.ilike(f"%{name}%"),
    ).first()


# ── Response formatters ───────────────────────────────────────────────────────

def _format_balance(db, customers, recorded_by_id) -> str:
    if len(customers) > 1:
        if len(customers) > 5:
            names = ", ".join(c.name for c in customers[:5]) + f" +{len(customers)-5} more"
            return (
                f"I found {len(customers)} customers matching that name.\n\n"
                f"{names}\n\nBe more specific — use their full name."
            )
        lines = [f"I found {len(customers)} customers with that name:\n"]
        for c in customers:
            bal = _balance(db, c.id, recorded_by_id)
            phone_str = f" · {c.customer_phone}" if c.customer_phone else ""
            if bal > 0:
                lines.append(f"• {c.name}{phone_str} — owes {_fmt(bal)}")
            elif bal < 0:
                lines.append(f"• {c.name}{phone_str} — you owe them {_fmt(-bal)}")
            else:
                lines.append(f"• {c.name}{phone_str} — no outstanding balance")
        lines.append("\nType their full name to see details.")
        return "\n".join(lines)

    c = customers[0]
    bal = _balance(db, c.id, recorded_by_id)
    total_buy, total_pay = _totals(db, c.id, recorded_by_id)
    due_date = _latest_due_date(db, c.id, recorded_by_id)

    if bal == 0:
        msg = f"*{c.name}* — fully settled. No outstanding balance."
        if total_buy:
            msg += f"\n\nTotal bought: {_fmt(total_buy)} | Total paid: {_fmt(total_pay)}"
        return msg

    if bal < 0:
        msg = f"*{c.name}* — you owe them {_fmt(-bal)}."
        if total_buy:
            msg += f"\n\nTotal from you: {_fmt(total_buy)} | Total paid to them: {_fmt(total_pay)}"
        return msg

    lines = [f"*{c.name}* owes you *{_fmt(bal)}*"]
    lines.append(f"Total credit: {_fmt(total_buy)} | Paid so far: {_fmt(total_pay)}")

    if due_date:
        label = _overdue_label(due_date)
        dd = _date_str(due_date)
        if "overdue" in label:
            lines.append(f"⚠️ Due date: {dd} ({label})")
        else:
            lines.append(f"Due date: {dd} ({label})")

    if c.customer_phone:
        lines.append(f"Phone: {c.customer_phone}")

    return "\n".join(lines)


def _format_due_date(db, customers, recorded_by_id) -> str:
    if len(customers) > 1:
        lines = [f"I found {len(customers)} customers with that name — which one?\n"]
        for c in customers:
            phone_str = f" ({c.customer_phone})" if c.customer_phone else ""
            lines.append(f"• {c.name}{phone_str}")
        lines.append("\nType their full name.")
        return "\n".join(lines)

    c = customers[0]
    due_date = _latest_due_date(db, c.id, recorded_by_id)
    bal = _balance(db, c.id, recorded_by_id)

    if not due_date:
        if bal > 0:
            return (
                f"*{c.name}* owes you {_fmt(bal)} but no due date is set.\n\n"
                f"To set one, type: due date {c.name} 30/07/2026"
            )
        return f"*{c.name}* has no outstanding balance and no due date on record."

    dd = _date_str(due_date)
    label = _overdue_label(due_date)
    lines = [f"*{c.name}* payment due: *{dd}*"]
    if label:
        prefix = "⚠️" if "overdue" in label else "🗓"
        lines.append(f"{prefix} {label.capitalize()}")
    if bal > 0:
        lines.append(f"\nOutstanding: {_fmt(bal)}")
    elif bal == 0:
        lines.append("\nBalance: fully settled ✓")

    return "\n".join(lines)


def _format_history(db, customers, recorded_by_id) -> str:
    if len(customers) > 1:
        lines = [f"I found {len(customers)} customers with that name:\n"]
        for c in customers:
            bal = _balance(db, c.id, recorded_by_id)
            phone_str = f" · {c.customer_phone}" if c.customer_phone else ""
            lines.append(f"• {c.name}{phone_str} — balance: {_fmt(bal)}")
        lines.append("\nType their full name to see transaction history.")
        return "\n".join(lines)

    c = customers[0]
    txs = _recent_txs(db, c.id, recorded_by_id, limit=7)
    bal = _balance(db, c.id, recorded_by_id)

    if not txs:
        return f"*{c.name}* has no recorded transactions."

    lines = [f"*{c.name}* — last {len(txs)} transaction{'s' if len(txs) != 1 else ''}:\n"]
    for tx in txs:
        d = _date_str(tx.created_at) or "—"
        if tx.type == "BUY":
            prod = f" · {tx.product.title()}" if tx.product else ""
            lines.append(f"• {d}{prod}: credit {_fmt(tx.amount)}")
        elif tx.type == "PAY":
            lines.append(f"• {d}: payment {_fmt(tx.amount)} ✓")
        elif tx.type == "SALE":
            prod = f" · {tx.product.title()}" if tx.product else ""
            lines.append(f"• {d}{prod}: sale {_fmt(tx.amount)}")

    if bal > 0:
        lines.append(f"\nBalance: {_fmt(bal)} outstanding")
    elif bal == 0:
        lines.append("\nBalance: fully settled ✓")
    else:
        lines.append(f"\nBalance: you owe them {_fmt(-bal)}")

    return "\n".join(lines)


def _format_product_price(db, owner_phone: str, name: str) -> Optional[str]:
    item = _find_product(db, owner_phone, name)
    if not item:
        return None
    if not item.selling_price and not item.cost_price and item.quantity is None:
        return None

    unit_str = f" per {item.unit}" if item.unit else ""
    lines = [f"*{item.name.title()}*"]
    if item.selling_price:
        lines.append(f"Selling price: {_fmt(item.selling_price)}{unit_str}")
    if item.cost_price:
        lines.append(f"Cost price: {_fmt(item.cost_price)}{unit_str}")
    if item.retail_price and item.retail_unit:
        lines.append(f"Retail: {_fmt(item.retail_price)} per {item.retail_unit}")
    if item.quantity is not None:
        qty = f"{item.quantity:g}"
        lines.append(f"Stock: {qty}{' ' + item.unit if item.unit else ''}")

    return "\n".join(lines)


def _format_product_stock(db, owner_phone: str, name: str) -> Optional[str]:
    item = _find_product(db, owner_phone, name)
    if not item or item.quantity is None:
        return None

    qty = f"{item.quantity:g}"
    unit_str = f" {item.unit}" if item.unit else ""
    lines = [f"*{item.name.title()}* — stock: {qty}{unit_str}"]

    if item.low_stock_alert is not None and item.quantity <= item.low_stock_alert:
        lines.append(f"⚠️ Low stock! Alert at {item.low_stock_alert}{unit_str}")
    if item.selling_price:
        lines.append(f"Selling: {_fmt(item.selling_price)}" + (f" per {item.unit}" if item.unit else ""))
    if item.cost_price:
        lines.append(f"Cost: {_fmt(item.cost_price)}")

    return "\n".join(lines)


# ── Pattern matching ──────────────────────────────────────────────────────────

# Debt/owing words (incl. Nigerian Pidgin "owning")
_DEBT = r"(?:owe|owes|owing|owed|owning|own(?=\s|$))"

# Query opener words
_CHECK = r"(?:check|show(?:\s+me)?|see|view|look\s+up|find|tell\s+me|display|give\s+me)"

# ---- Customer balance patterns (each has one capture group = candidate name) ----
_BALANCE_PATTERNS = [
    # "how much does/is NAME owe/owing me?"
    rf"how\s+much\s+(?:does|is|do|has)?\s*(.+?)\s+{_DEBT}(?:\s+(?:me|you|us))?[?!.]*$",
    # "how much NAME is owing" (pidgin word order)
    rf"^how\s+much\s+(?:is\s+)?(.+?)\s+{_DEBT}[?!.]*$",
    # "can you check how much NAME is owing me"
    rf"can\s+you\s+{_CHECK}\s+how\s+much\s+(.+?)\s+(?:is\s+)?{_DEBT}",
    # "check NAME balance/account/debt/outstanding/owing"
    rf"{_CHECK}\s+(.+?)'?s?\s+(?:balance|account|debt|outstanding|owing|credit)",
    # "what is/are NAME's balance/account/debt"
    r"what(?:'s|\s+is|\s+are)\s+(.+?)'?s?\s+(?:balance|account|debt|outstanding|owing)",
    # "NAME balance/account/outstanding/debt" (standalone phrase)
    r"^(.+?)'?s?\s+(?:balance|account|outstanding|debt)[?!.]*$",
    # "NAME is owing/owes me" (e.g. "bankole is owing me")
    rf"^(.+?)\s+(?:is\s+)?{_DEBT}(?:\s+(?:me|you|us))?[?!.]*$",
    # "show me NAME" — lower priority, try after others fail
    r"^(?:show|tell)\s+me\s+(.+?)[?!.]*$",
]

# ---- Customer due date patterns ----
_DUE_PATTERNS = [
    # "when is NAME due/paying/payment"
    r"when\s+(?:is|was|does|will)\s+(.+?)\s+(?:due|pay(?:ing)?|payment|due\s+date|pay\s+me)",
    # "NAME due date/payment date"
    r"^(.+?)'?s?\s+(?:due\s+date|payment\s+date|due|payment)[?!.]*$",
    # "when does NAME pay me/settle/clear"
    r"when\s+does\s+(.+?)\s+(?:pay|settle|clear|owe|pay\s+me)",
    # "NAME when due" / "when NAME due"
    r"(?:when\s+)?(.+?)\s+when\s+(?:is\s+)?(?:it\s+)?due",
]

# ---- Customer history/transactions patterns ----
_HISTORY_PATTERNS = [
    # "show NAME history/transactions/record/statement/account"
    rf"{_CHECK}\s+(.+?)'?s?\s+(?:history|transactions|record|records|statement|purchases|account|log)",
    # "what did NAME buy/purchase/take/borrow/order"
    r"what\s+did\s+(.+?)\s+(?:buy|purchase|take|borrow|order|get)",
    # "NAME history/transactions/record" (standalone)
    r"^(.+?)'?s?\s+(?:history|transactions|record|statement|log)[?!.]*$",
    # "show NAME transactions"
    r"^(?:show|see|view)\s+(.+?)\s+(?:transactions|history|record)[?!.]*$",
]

# ---- Product price patterns ----
_PRODUCT_PRICE_PATTERNS = [
    # "how much is/are rice?" (NO debt word — already screened above)
    r"^how\s+much\s+(?:is|are|does|for|of)?\s+(.+?)[?!.]*$",
    # "price of/for rice"
    r"(?:price|cost)\s+(?:of|for|is|per|per\s+unit)?\s+(.+?)[?!.]*$",
    # "what is the price of rice?"
    r"what(?:'s|\s+is)\s+(?:the\s+)?(?:price|cost|rate)\s+(?:of|for)?\s+(.+?)[?!.]*$",
    # "rice price/cost"
    r"^(.+?)\s+(?:price|cost|rate)[?!.]*$",
]

# ---- Product stock patterns ----
_PRODUCT_STOCK_PATTERNS = [
    # "how many bags of rice?" / "how much rice left?"
    r"^how\s+(?:many|much)\s+(?:\w+\s+(?:of|for)\s+)?(.+?)(?:\s+(?:do\s+i\s+have|is\s+left|remaining|in\s+stock|left|available))?[?!.]*$",
    # "rice stock/quantity/level"
    r"^(.+?)\s+(?:stock|quantity|level|remaining|available|left|count)[?!.]*$",
    # "stock of rice"
    r"^(?:stock|inventory|quantity)\s+(?:of|for)?\s+(.+?)[?!.]*$",
]


def _first_match(patterns, text):
    """Return first non-empty capture group from any pattern, or None."""
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            captured = m.group(1).strip()
            if captured:
                return captured
    return None


# ── Main entry point ──────────────────────────────────────────────────────────

def handle_natural_language_query(
    db,
    owner_phone: str,
    text: str,
    recorded_by_id=None,
) -> Optional[str]:
    """
    Detect and answer a natural-language query.

    Returns a formatted response string, or None if no query pattern matched.
    Callers should return early when a non-None value is returned.
    """
    t = text.strip()
    if not t:
        return None

    # Fast-reject: if text is 1–2 words it's almost certainly a command or
    # transaction shorthand, not a conversational query.
    # Exception: "NAME balance" / "NAME account" (exactly 2 words) should still hit.
    word_count = len(t.split())
    is_short = word_count <= 2

    # ── 1. Customer balance queries ───────────────────────────────────────────
    raw_name = _first_match(_BALANCE_PATTERNS if not is_short else
                             # For short text only allow "NAME balance/account" pattern
                             [r"^(.+?)'?s?\s+(?:balance|account|outstanding|debt)[?!.]*$"],
                             t)
    if raw_name:
        name = _clean_entity(raw_name)
        if name:
            customers = _find_customers(db, owner_phone, name, recorded_by_id)
            if customers:
                return _format_balance(db, customers, recorded_by_id)

    # ── 2. Customer due date queries ──────────────────────────────────────────
    raw_name = _first_match(_DUE_PATTERNS, t)
    if raw_name:
        name = _clean_entity(raw_name)
        if name:
            customers = _find_customers(db, owner_phone, name, recorded_by_id)
            if customers:
                return _format_due_date(db, customers, recorded_by_id)

    # ── 3. Customer history queries ───────────────────────────────────────────
    raw_name = _first_match(_HISTORY_PATTERNS, t)
    if raw_name:
        name = _clean_entity(raw_name)
        if name:
            customers = _find_customers(db, owner_phone, name, recorded_by_id)
            if customers:
                return _format_history(db, customers, recorded_by_id)

    # ── 4. Product price queries ──────────────────────────────────────────────
    raw_prod = _first_match(_PRODUCT_PRICE_PATTERNS, t)
    if raw_prod:
        prod = _clean_entity(raw_prod)
        if prod:
            result = _format_product_price(db, owner_phone, prod)
            if result:
                return result

    # ── 5. Product stock queries ──────────────────────────────────────────────
    raw_prod = _first_match(_PRODUCT_STOCK_PATTERNS, t)
    if raw_prod:
        prod = _clean_entity(raw_prod)
        if prod:
            result = _format_product_stock(db, owner_phone, prod)
            if result:
                return result

    return None
