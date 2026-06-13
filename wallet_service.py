"""
Wallet service — business logic layer for CreditVoice Wallet.

Current state: FOUNDATION ONLY.
All functions are wired and tested; fintech integration points are clearly
marked with # FINTECH_INTEGRATION comments so the partner hook-up is a
drop-in, not a rewrite.

Integration checklist (when license + partner is ready):
  1. Replace virtual account provisioning stub with partner API call
  2. Wire POST /webhook/payment-received to your partner's IP whitelist + HMAC
  3. Set WALLET_WEBHOOK_SECRET env var for HMAC verification
  4. Set PAYMENT_LINK_BASE_URL env var for shareable links
"""

import os
import uuid
from datetime import datetime, timezone

from models import Customer, Transaction, Wallet, WalletTransaction

PAYMENT_LINK_BASE_URL = os.getenv("PAYMENT_LINK_BASE_URL", "https://pay.creditvoice.app")
WALLET_WEBHOOK_SECRET = os.getenv("WALLET_WEBHOOK_SECRET", "")


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _new_ref():
    return f"CV-{uuid.uuid4().hex[:12].upper()}"


# ── Wallet access ──────────────────────────────────────────────────────────────

def get_or_create_wallet(db, owner_phone: str) -> Wallet:
    wallet = db.query(Wallet).filter(Wallet.owner_phone == owner_phone).first()
    if not wallet:
        wallet = Wallet(owner_phone=owner_phone)
        db.add(wallet)
        db.flush()
    return wallet


def get_wallet_summary(db, owner_phone: str) -> dict:
    wallet = get_or_create_wallet(db, owner_phone)
    recent = (
        db.query(WalletTransaction)
        .filter(WalletTransaction.owner_phone == owner_phone)
        .order_by(WalletTransaction.created_at.desc())
        .limit(20)
        .all()
    )
    unmatched = [t for t in recent if t.direction == "in" and not t.matched_customer_id]
    return {
        "balance": wallet.balance,
        "total_received": wallet.total_received,
        "total_withdrawn": wallet.total_withdrawn,
        "virtual_account_number": wallet.virtual_account_number,
        "virtual_account_bank": wallet.virtual_account_bank,
        "virtual_account_name": wallet.virtual_account_name,
        "payment_link": _build_payment_link(wallet),
        "waitlist": wallet.waitlist,
        "live": bool(wallet.virtual_account_number),   # True when fintech integrated
        "unmatched_count": len(unmatched),
        "transactions": [_serialize_tx(t) for t in recent],
    }


def _build_payment_link(wallet: Wallet) -> str | None:
    if not wallet.payment_link_slug:
        return None
    return f"{PAYMENT_LINK_BASE_URL}/{wallet.payment_link_slug}"


def _serialize_tx(t: WalletTransaction) -> dict:
    return {
        "id": t.id,
        "reference": t.reference,
        "amount": t.amount,
        "direction": t.direction,
        "type": t.type,
        "status": t.status,
        "sender_name": t.sender_name,
        "sender_bank": t.sender_bank,
        "narration": t.narration,
        "matched_customer_id": t.matched_customer_id,
        "matched_by": t.matched_by,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "settled_at": t.settled_at.isoformat() if t.settled_at else None,
    }


# ── Waitlist ───────────────────────────────────────────────────────────────────

def register_waitlist(db, owner_phone: str) -> Wallet:
    wallet = get_or_create_wallet(db, owner_phone)
    wallet.waitlist = True
    wallet.updated_at = _utcnow()
    db.commit()
    return wallet


# ── Incoming payment processing ────────────────────────────────────────────────
# FINTECH_INTEGRATION: this function is called by the webhook handler when a
# fintech partner notifies us of a successful inbound transfer to the business's
# virtual account. The partner call is already stubbed in web_routes.py.

def process_incoming_payment(
    db,
    owner_phone: str,
    amount: int,
    sender_name: str,
    sender_bank: str,
    narration: str,
    fintech_ref: str,
    sender_account: str = "",
) -> WalletTransaction:
    wallet = get_or_create_wallet(db, owner_phone)

    # Idempotency — don't double-process the same payment
    existing = db.query(WalletTransaction).filter(
        WalletTransaction.fintech_ref == fintech_ref
    ).first()
    if existing:
        return existing

    tx = WalletTransaction(
        owner_phone=owner_phone,
        reference=_new_ref(),
        fintech_ref=fintech_ref,
        amount=amount,
        direction="in",
        type="collection",
        status="settled",
        sender_name=sender_name,
        sender_account=sender_account,
        sender_bank=sender_bank,
        narration=narration,
        settled_at=_utcnow(),
    )
    db.add(tx)
    db.flush()

    # Update wallet totals
    wallet.balance = (wallet.balance or 0) + amount
    wallet.total_received = (wallet.total_received or 0) + amount
    wallet.updated_at = _utcnow()

    # Attempt auto-match to a customer
    matched_customer = _auto_match(db, owner_phone, sender_name, narration, amount)
    if matched_customer:
        tx.matched_customer_id = matched_customer.id
        tx.matched_at = _utcnow()
        tx.matched_by = "auto"
        # Record the payment against the customer's credit balance
        pay_tx = Transaction(
            customer_id=matched_customer.id,
            type="PAY",
            amount=amount,
            product="Wallet payment",
        )
        db.add(pay_tx)

    db.commit()
    return tx


def _auto_match(db, owner_phone: str, sender_name: str, narration: str, amount: int):
    """
    Try to find a customer from sender name or narration.
    Simple word-overlap match — good enough for informal business names.
    """
    if not sender_name and not narration:
        return None

    search_words = set()
    for src in (sender_name or "", narration or ""):
        for w in src.lower().split():
            if len(w) >= 3:
                search_words.add(w)

    if not search_words:
        return None

    customers = db.query(Customer).filter(Customer.owner_phone == owner_phone).all()
    for customer in customers:
        name_words = set(customer.name.lower().split())
        if name_words & search_words:
            return customer
    return None


# ── Manual matching ────────────────────────────────────────────────────────────

def manually_match_payment(db, wallet_tx_id: int, customer_id: int, owner_phone: str):
    tx = db.query(WalletTransaction).filter(
        WalletTransaction.id == wallet_tx_id,
        WalletTransaction.owner_phone == owner_phone,
    ).first()
    if not tx:
        return None, "Transaction not found."
    customer = db.query(Customer).filter(
        Customer.id == customer_id,
        Customer.owner_phone == owner_phone,
    ).first()
    if not customer:
        return None, "Customer not found."

    # Remove previous auto-matched Transaction if any
    if tx.matched_customer_id and tx.matched_customer_id != customer_id:
        db.query(Transaction).filter(
            Transaction.customer_id == tx.matched_customer_id,
            Transaction.type == "PAY",
            Transaction.amount == tx.amount,
            Transaction.product == "Wallet payment",
        ).delete()

    tx.matched_customer_id = customer.id
    tx.matched_at = _utcnow()
    tx.matched_by = "manual"

    # Record payment
    pay_tx = Transaction(
        customer_id=customer.id,
        type="PAY",
        amount=tx.amount,
        product="Wallet payment",
    )
    db.add(pay_tx)
    db.commit()
    return tx, None


# ── Virtual account provisioning stub ─────────────────────────────────────────
# FINTECH_INTEGRATION: replace this stub with a real API call to your partner
# (Providus, Wema ALAT, Stitch, etc.) to create a dedicated virtual account.

def provision_virtual_account(db, owner_phone: str, business_name: str) -> dict:
    """
    Stub — returns a placeholder. Replace with partner API call.

    Partner call should return:
        account_number, bank_name, account_name, partner_ref
    """
    # TODO: call fintech partner API here
    # Example (Providus):
    #   response = requests.post(
    #       "https://api.providus.ng/PiPCreateReservedAccountNumber",
    #       json={"merchant_ref": owner_phone, "name": business_name},
    #       headers={"Authorization": f"Bearer {PARTNER_TOKEN}"},
    #   )
    #   data = response.json()
    #   return {
    #       "account_number": data["account_number"],
    #       "bank": "Providus Bank",
    #       "account_name": data["account_name"],
    #       "ref": data["merchant_ref"],
    #   }
    raise NotImplementedError("Virtual account provisioning requires fintech partner integration.")


# ── Webhook signature verification ────────────────────────────────────────────
# FINTECH_INTEGRATION: uncomment and adapt to your partner's HMAC scheme.

def verify_webhook_signature(payload_bytes: bytes, signature_header: str) -> bool:
    """Verify that the webhook came from our fintech partner, not an attacker."""
    if not WALLET_WEBHOOK_SECRET:
        return True  # dev mode — skip verification
    import hmac
    import hashlib
    expected = hmac.new(
        WALLET_WEBHOOK_SECRET.encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header or "")
