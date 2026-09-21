"""
Customer balance statement — the short message a business sends a customer who
asks "what do I owe?".

Built in one place so the web button, the WhatsApp command and any future
automation all send the same wording. The owner can edit it before sending.
"""
from models import Customer, Transaction


def _naira(amount):
    return f"N{int(amount or 0):,}"


def _day(dt):
    return dt.strftime("%d %b %Y") if dt else ""


def recent_activity(db, customer_id, limit=5):
    """The customer's latest transactions, newest first (voided ones excluded)."""
    return (
        db.query(Transaction)
        .filter(
            Transaction.customer_id == customer_id,
            Transaction.is_voided.isnot(True),
        )
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .limit(limit)
        .all()
    )


def _line(tx):
    when = _day(tx.created_at)
    if tx.type == "PAY":
        return f"• {when}: paid {_naira(tx.amount)}"
    what = (tx.product or "Purchase").strip()
    # POS sales are stored as "POS Sale (3 items)" — read as a purchase line.
    if what.lower().startswith("pos sale"):
        what = "Purchase"
    return f"• {when}: {what.title()} — {_naira(tx.amount)}"


def oldest_unpaid_at(db, customer_id):
    """When the customer's oldest unsettled credit sale was recorded — the
    'owing since' date. None when they have never bought on credit."""
    tx = (
        db.query(Transaction)
        .filter(
            Transaction.customer_id == customer_id,
            Transaction.type == "BUY",
            Transaction.is_voided.isnot(True),
        )
        .order_by(Transaction.created_at.asc(), Transaction.id.asc())
        .first()
    )
    return tx.created_at if tx else None


def build_balance_message(db, owner_user, customer, include_items=True):
    """The editable statement text: what they owe (or are owed), since when,
    and their recent activity."""
    from business_templates import business_display_name
    from reports import get_balance

    balance = customer.balance if customer.balance is not None else get_balance(db, customer.id)
    balance = int(balance or 0)
    name = (customer.name or "there").split()[0].title()
    biz = business_display_name(owner_user) if owner_user else "Our business"

    lines = [f"*{biz}*", ""]
    if balance > 0:
        lines.append(f"Hello {name}, your balance with us is *{_naira(balance)}*.")
        since = oldest_unpaid_at(db, customer.id)
        if since:
            lines.append(f"Owing since {_day(since)}.")
    elif balance < 0:
        lines.append(f"Hello {name}, you have *{_naira(-balance)}* credit with us.")
    else:
        lines.append(f"Hello {name}, your account is fully settled. Thank you!")

    if include_items:
        rows = recent_activity(db, customer.id)
        if rows:
            lines.append("")
            lines.append("Recent activity:")
            lines.extend(_line(tx) for tx in rows)

    lines.append("")
    if balance > 0:
        lines.append("Kindly pay when you can. Thank you.")
    else:
        lines.append("Thank you for your business.")
    owner_phone = getattr(owner_user, "phone", None) if owner_user else None
    if owner_phone:
        lines.append(f"Questions? Call {owner_phone}")
    return "\n".join(lines)


def self_send_url(phone, message):
    """A wa.me link so the owner can send from their OWN phone — the only way
    to reach a customer who never messaged the business's tiTi number
    (WhatsApp blocks free-form messages outside the 24-hour window)."""
    from urllib.parse import quote
    from parser import normalize_phone

    digits = normalize_phone(phone) or "".join(ch for ch in (phone or "") if ch.isdigit())
    if not digits:
        return None
    return f"https://wa.me/{digits}?text={quote(message)}"


def find_customer(db, owner_phone, customer_id):
    return (
        db.query(Customer)
        .filter(Customer.id == customer_id, Customer.owner_phone == owner_phone)
        .first()
    )
