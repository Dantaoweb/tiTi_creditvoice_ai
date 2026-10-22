"""
Pay links — "Pay ₦45,000 here: creditvoiceai.com/app/pay/i12-3f9a…".

The customer needs no app and no account: the link opens a page in their
phone's browser with the business, what it's for, the amount, and the bank
account from the owner's Profile to transfer to. They tap "I've paid" (with
a photo of the transfer if they like). The owner is alerted, checks the bank
and confirms — only then is a payment recorded, with a receipt to the
customer. The money goes straight to the business's bank; the app never
holds it.

Links are signed, so nobody can guess another customer's: "i<id>" for an
invoice, "c<id>" for a customer's whole balance. They read the amount live,
so a link sent last week still asks for what's owed today.
"""
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

from models import Customer, Invoice, PaymentClaim, Transaction, User

MAX_PROOF_BYTES = 1_500_000
MAX_PENDING_PER_LINK = 3


class PayLinkError(ValueError):
    pass


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _secret():
    return os.getenv("WEB_SECRET_KEY", "cv-web-secret-change-in-production").encode()


def _sig(body):
    return hmac.new(_secret(), f"pay:{body}".encode(), hashlib.sha256).hexdigest()[:12]


def make_token(kind, obj_id):
    body = f"{kind}{int(obj_id)}"
    return f"{body}-{_sig(body)}"


def read_token(token):
    """(kind, id) for a genuine link, else None."""
    try:
        body, sig = (token or "").rsplit("-", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(sig, _sig(body)) or body[:1] not in ("i", "c") or not body[1:].isdigit():
        return None
    return ("invoice" if body[0] == "i" else "debt"), int(body[1:])


def base_url():
    return (os.getenv("APP_BASE_URL") or "https://creditvoiceai.com").rstrip("/")


def link_for(kind, obj_id):
    return f"{base_url()}/app/pay/{make_token('i' if kind == 'invoice' else 'c', obj_id)}"


def invoice_pay_link(db, inv):
    """The pay link for an invoice — only while something is still asked for
    and the business has a bank account on its Profile."""
    from printables import bank_accounts
    owner = db.query(User).filter(User.phone == inv.owner_phone).first()
    if not owner or not bank_accounts(owner) or inv.cancelled_at or inv.transaction_id or inv.is_quote:
        return None
    return link_for("invoice", inv.id)


def debt_pay_link(db, customer):
    from printables import bank_accounts
    owner = db.query(User).filter(User.phone == customer.owner_phone).first()
    if not owner or not bank_accounts(owner) or int(customer.balance or 0) <= 0:
        return None
    return link_for("debt", customer.id)


def _target(db, token):
    found = read_token(token)
    if not found:
        raise PayLinkError("This payment link isn't valid.")
    kind, obj_id = found
    if kind == "invoice":
        inv = db.query(Invoice).filter(Invoice.id == obj_id).first()
        if not inv:
            raise PayLinkError("This payment link isn't valid.")
        return kind, inv.owner_phone, inv, (db.query(Customer).filter(Customer.id == inv.customer_id).first()
                                            if inv.customer_id else None)
    cust = db.query(Customer).filter(Customer.id == obj_id).first()
    if not cust:
        raise PayLinkError("This payment link isn't valid.")
    return kind, cust.owner_phone, None, cust


def page(db, token):
    """What the public pay page shows."""
    from invoices import _business_header, format_invoice_number
    from printables import bank_accounts
    kind, owner_phone, inv, cust = _target(db, token)
    owner = db.query(User).filter(User.phone == owner_phone).first()
    head = _business_header(db, owner_phone, getattr(inv, "branch_id", None), kind="invoice")
    if kind == "invoice":
        label = format_invoice_number(inv.number)
        amount = 0 if (inv.cancelled_at or inv.transaction_id) else int(inv.total or 0)
        settled = bool(inv.transaction_id)
    else:
        label = "Balance"
        amount = max(0, int(cust.balance or 0))
        settled = amount <= 0
    pending = (db.query(PaymentClaim).filter(PaymentClaim.owner_phone == owner_phone,
                                             PaymentClaim.status == "pending",
                                             PaymentClaim.invoice_id == (inv.id if inv else None),
                                             PaymentClaim.customer_id == (cust.id if cust else None))
               .order_by(PaymentClaim.id.desc()).first())
    return {
        "biz_name": head.get("biz_name"), "biz_logo": head.get("biz_logo"), "biz_phone": head.get("biz_phone"),
        "kind": kind, "label": label, "amount": amount, "settled": settled,
        "cancelled": bool(inv and inv.cancelled_at),
        "customer_name": (cust.name or "").title() if cust else None,
        "bank_accounts": bank_accounts(owner) if owner else [],
        "claim_pending": bool(pending),
        "claimed_at": pending.created_at.isoformat() if pending and pending.created_at else None,
    }


def claim(db, token, amount=None, payer_name=None, note=None, proof=None, source="link"):
    """The customer says they've paid. Tells the owner; records nothing yet."""
    from invoices import format_invoice_number
    kind, owner_phone, inv, cust = _target(db, token)
    info = page(db, token)
    if info["cancelled"]:
        raise PayLinkError("This invoice was cancelled.")
    if info["settled"]:
        raise PayLinkError("This is already paid. Thank you!")
    since = _utcnow() - timedelta(hours=24)
    recent = db.query(PaymentClaim).filter(
        PaymentClaim.owner_phone == owner_phone, PaymentClaim.status == "pending",
        PaymentClaim.created_at >= since,
        PaymentClaim.invoice_id == (inv.id if inv else None),
        PaymentClaim.customer_id == (cust.id if cust else None)).count()
    if recent >= MAX_PENDING_PER_LINK:
        raise PayLinkError("You've already told them — they'll confirm once they see the money.")
    try:
        amount = int(amount) if amount not in (None, "") else info["amount"]
    except (TypeError, ValueError):
        raise PayLinkError("Enter the amount you paid.")
    if amount <= 0 or amount > max(info["amount"], 1) * 2:
        raise PayLinkError("Enter the amount you paid.")
    if proof:
        if not isinstance(proof, str) or not proof.startswith("data:image/") or len(proof) > MAX_PROOF_BYTES * 4 // 3:
            raise PayLinkError("The photo must be an image under 1.5MB.")
    c = PaymentClaim(owner_phone=owner_phone, customer_id=cust.id if cust else None,
                     invoice_id=inv.id if inv else None, kind=kind,
                     label=format_invoice_number(inv.number) if inv else "Balance",
                     amount=amount, payer_name=(payer_name or "").strip()[:100] or None,
                     note=(note or "").strip()[:300] or None, proof_data=proof or None, source=source)
    db.add(c)
    db.flush()
    return c


def _record_debt_payment(db, owner_phone, customer, amount, user_id, label):
    from web_pos import next_receipt_number
    import uuid
    tx = Transaction(customer_id=customer.id, type="PAY", amount=amount,
                     product=f"Payment by transfer — {label}", recorded_by_id=user_id,
                     message_id=f"pay-link-{uuid.uuid4()}", branch_id=customer.branch_id,
                     receipt_number=next_receipt_number(db, owner_phone))
    db.add(tx)
    db.flush()
    return tx


def confirm(db, claim_row, user_id, amount=None):
    """The owner saw the money: record it. An unpaid invoice becomes a sale
    paid with this amount (the rest is debt, as when paying an invoice);
    a balance or an invoice already turned into a sale gets a payment."""
    if claim_row.status != "pending":
        raise PayLinkError("This was already dealt with.")
    try:
        amount = int(amount) if amount not in (None, "") else int(claim_row.amount)
    except (TypeError, ValueError):
        raise PayLinkError("Enter the amount that arrived.")
    if amount <= 0:
        raise PayLinkError("Enter the amount that arrived.")
    receipt_id = None
    inv = db.query(Invoice).filter(Invoice.id == claim_row.invoice_id).first() if claim_row.invoice_id else None
    if inv is not None and not inv.transaction_id and not inv.cancelled_at:
        from invoices import pay_invoice
        _inv, result = pay_invoice(db, inv, user_id, min(amount, int(inv.total or 0)))
        receipt_id = result.get("receipt_id")
    else:
        cust = db.query(Customer).filter(Customer.id == claim_row.customer_id).first() if claim_row.customer_id else None
        if cust is None:
            raise PayLinkError("The customer for this payment no longer exists.")
        receipt_id = _record_debt_payment(db, claim_row.owner_phone, cust, amount, user_id, claim_row.label).id
    claim_row.status = "confirmed"
    claim_row.amount = amount
    claim_row.decided_at = _utcnow()
    claim_row.decided_by_id = user_id
    claim_row.pay_tx_id = receipt_id
    db.flush()
    return receipt_id


def reject(db, claim_row, user_id, reason):
    if claim_row.status != "pending":
        raise PayLinkError("This was already dealt with.")
    reason = (reason or "").strip()
    if not reason:
        raise PayLinkError("Say why — the customer is told.")
    claim_row.status = "rejected"
    claim_row.reject_reason = reason[:200]
    claim_row.decided_at = _utcnow()
    claim_row.decided_by_id = user_id
    db.flush()


def claim_row_dict(db, c, with_proof=False):
    cust = db.query(Customer).filter(Customer.id == c.customer_id).first() if c.customer_id else None
    return {
        "id": c.id, "kind": c.kind, "label": c.label, "amount": c.amount, "status": c.status,
        "customer": (cust.name or "").title() if cust else None, "customer_id": c.customer_id,
        "invoice_id": c.invoice_id, "payer_name": c.payer_name, "note": c.note, "source": c.source,
        "has_proof": bool(c.proof_data), "proof": c.proof_data if with_proof else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "reject_reason": c.reject_reason, "pay_tx_id": c.pay_tx_id,
    }


def pay_line(link):
    return f"Pay here: {link}" if link else None


# ── "PAID" on WhatsApp ────────────────────────────────────────────────────────

import re as _re

_PAID_RE = _re.compile(r"^\s*(?:i\s+(?:have\s+|ve\s+|'ve\s+)?|i've\s+|have\s+)?(?:paid|sent|transferred)\b"
                       r"(?:[^\d]*(?P<amount>\d[\d,]*))?", _re.I)


def whatsapp_paid_reply(db, phone, text):
    """A customer (not an app user) writes "paid" / "I have paid 5000" to the
    business number. If that phone is one business's customer who owes money
    or has an unpaid invoice, the owner is asked to confirm. Returns the reply
    to send, or None to let the message go on as usual."""
    m = _PAID_RE.match(text or "")
    if not m or len(text) > 120:
        return None
    digits = _re.sub(r"\D", "", phone or "")
    variants = {digits, "0" + digits[3:] if digits.startswith("234") else digits, digits[-10:]}
    custs = [c for c in db.query(Customer).filter(Customer.customer_phone.isnot(None)).all()
             if _re.sub(r"\D", "", c.customer_phone or "") in variants
             or _re.sub(r"\D", "", c.customer_phone or "")[-10:] == digits[-10:]]
    owing = []
    for c in custs:
        inv = (db.query(Invoice).filter(Invoice.customer_id == c.id, Invoice.cancelled_at.is_(None),
                                        Invoice.transaction_id.is_(None), Invoice.is_quote.isnot(True))
               .order_by(Invoice.id.desc()).first())
        if inv or int(c.balance or 0) > 0:
            owing.append((c, inv))
    if not owing:
        return None
    from business_templates import business_display_name
    if len({c.owner_phone for c, _i in owing}) > 1:
        lines = ["Thanks! Which business did you pay? Tap its link to tell them:"]
        for c, inv in owing:
            owner = db.query(User).filter(User.phone == c.owner_phone).first()
            link = link_for("invoice", inv.id) if inv else link_for("debt", c.id)
            lines.append(f"• {business_display_name(owner) if owner else 'Business'}: {link}")
        return {"reply": "\n".join(lines), "claim": None}
    c, inv = owing[0]
    amount = int(m.group("amount").replace(",", "")) if m.group("amount") else None
    token = make_token("i", inv.id) if inv else make_token("c", c.id)
    row = claim(db, token, amount=amount, payer_name=(c.name or "").title(), source="whatsapp")
    owner = db.query(User).filter(User.phone == c.owner_phone).first()
    return {"reply": f"Thanks! We've told *{business_display_name(owner) if owner else 'the business'}* "
                     f"you paid ₦{row.amount:,} for {row.label}. They'll confirm once they see it in their bank, "
                     f"and you'll get a receipt.",
            "claim": row}
