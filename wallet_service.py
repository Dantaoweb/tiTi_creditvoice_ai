"""
Wallet service — Monnify Reserved Account integration.

Env vars required for live operation:
  MONNIFY_API_KEY        — from Monnify dashboard
  MONNIFY_SECRET_KEY     — from Monnify dashboard (also used for webhook HMAC)
  MONNIFY_CONTRACT_CODE  — from Monnify dashboard
  MONNIFY_BASE_URL       — https://sandbox.monnify.com (test) or https://api.monnify.com (live)
  PAYMENT_LINK_BASE_URL  — base URL for shareable payment links (optional)
"""

import base64
import hashlib
import hmac
import os
import uuid
from datetime import datetime, timezone

import requests

from models import Customer, Transaction, Wallet, WalletTransaction

PAYMENT_LINK_BASE_URL = os.getenv("PAYMENT_LINK_BASE_URL", "https://pay.creditvoice.app")
MONNIFY_API_KEY       = os.getenv("MONNIFY_API_KEY", "")
MONNIFY_SECRET_KEY    = os.getenv("MONNIFY_SECRET_KEY", "")
MONNIFY_CONTRACT_CODE = os.getenv("MONNIFY_CONTRACT_CODE", "")
MONNIFY_BASE_URL      = os.getenv("MONNIFY_BASE_URL", "https://sandbox.monnify.com")

# Common Nigerian bank codes → names (for readable webhook display)
_BANK_NAMES = {
    "011": "First Bank", "014": "MainStreet Bank", "023": "CitiBank",
    "032": "Union Bank",  "033": "UBA",             "035": "Wema Bank",
    "037": "Jaiz Bank",   "040": "Ecobank",         "044": "Access Bank",
    "050": "Ecobank",     "057": "Zenith Bank",     "058": "GTBank",
    "068": "Standard Chartered", "070": "Fidelity Bank", "076": "Polaris Bank",
    "082": "Keystone Bank",      "090": "Sterling Bank",  "214": "FCMB",
    "215": "Unity Bank",  "221": "Stanbic IBTC",    "232": "Sterling Bank",
    "301": "Jaiz Bank",   "305": "Ekondo MFB",      "309": "Ecobank",
    "315": "GTBank",      "327": "Paga",             "401": "ASO Savings",
    "50211": "Kuda",      "50515": "Moniepoint",     "100004": "Opay",
    "100033": "PalmPay",
}


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


# ── Monnify token ─────────────────────────────────────────────────────────────

def _get_monnify_token() -> str:
    """Exchange API key + secret for a short-lived Bearer token."""
    credentials = base64.b64encode(
        f"{MONNIFY_API_KEY}:{MONNIFY_SECRET_KEY}".encode()
    ).decode()
    resp = requests.post(
        f"{MONNIFY_BASE_URL}/api/v1/auth/login",
        headers={"Authorization": f"Basic {credentials}"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["responseBody"]["accessToken"]


def create_monnify_checkout(reference: str, amount: int, customer_name: str,
                            customer_email: str, description: str,
                            redirect_url: str | None = None) -> str | None:
    """Initialize a Monnify transaction and return its hosted checkout URL.

    `reference` must be stored on SubscriptionPayment.evidence_ref so the
    Monnify webhook (/app/api/webhooks/monnify/subscription) can match the
    payment and activate the plan. Returns None if Monnify is unconfigured or
    the call fails (caller should fall back to bank transfer)."""
    if not (MONNIFY_API_KEY and MONNIFY_SECRET_KEY and MONNIFY_CONTRACT_CODE):
        return None
    try:
        token = _get_monnify_token()
        body = {
            "amount": amount,
            "customerName": customer_name,
            "customerEmail": customer_email,
            "paymentReference": reference,
            "paymentDescription": description,
            "currencyCode": "NGN",
            "contractCode": MONNIFY_CONTRACT_CODE,
            "paymentMethods": ["CARD", "ACCOUNT_TRANSFER"],
        }
        if redirect_url:
            body["redirectUrl"] = redirect_url
        resp = requests.post(
            f"{MONNIFY_BASE_URL}/api/v1/merchant/transactions/init-transaction",
            json=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("responseBody", {}).get("checkoutUrl")
    except Exception as exc:
        print(f"[monnify] checkout init failed: {exc}", flush=True)
        return None


# ── Virtual account provisioning ───────────────────────────────────────────────

def provision_virtual_account(db, owner_phone: str, business_name: str) -> dict:
    """
    Create a Monnify Reserved Account for a CreditVoice business.
    Each business gets a permanent NUBAN (Wema Bank / Sterling Bank).
    Idempotent — safe to call again if the wallet already has an account.
    """
    wallet = get_or_create_wallet(db, owner_phone)
    if wallet.virtual_account_number:
        return {
            "account_number": wallet.virtual_account_number,
            "bank": wallet.virtual_account_bank,
            "account_name": wallet.virtual_account_name,
        }

    token = _get_monnify_token()
    account_name = f"CV {business_name}"[:50]

    resp = requests.post(
        f"{MONNIFY_BASE_URL}/api/v2/bank-transfer/reserved-accounts",
        json={
            "accountReference":  owner_phone,
            "accountName":       account_name,
            "currencyCode":      "NGN",
            "contractCode":      MONNIFY_CONTRACT_CODE,
            "customerName":      business_name,
            "customerEmail":     f"{owner_phone}@creditvoice.app",
            "getAllAvailableBanks": False,
        },
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()["responseBody"]

    # Monnify returns a list under "accounts" when getAllAvailableBanks=True,
    # or a single object otherwise — normalise to grab the first/only entry.
    accounts = body.get("accounts") or []
    primary  = accounts[0] if accounts else body

    wallet.virtual_account_number = primary.get("accountNumber") or body.get("accountNumber")
    wallet.virtual_account_bank   = primary.get("bankName") or body.get("bankName")
    wallet.virtual_account_name   = body.get("accountName", account_name)
    wallet.virtual_account_ref    = body.get("accountReference", owner_phone)
    wallet.updated_at             = _utcnow()
    db.commit()

    return {
        "account_number": wallet.virtual_account_number,
        "bank":           wallet.virtual_account_bank,
        "account_name":   wallet.virtual_account_name,
    }


# ── Webhook signature verification ────────────────────────────────────────────

def verify_webhook_signature(payload_bytes: bytes, signature_header: str) -> bool:
    """Verify that the webhook came from Monnify (HMAC-SHA512 of raw body)."""
    if not MONNIFY_SECRET_KEY:
        if os.getenv("ENVIRONMENT", "production") == "development":
            import warnings
            warnings.warn(
                "MONNIFY_SECRET_KEY not set — webhook signature check skipped in dev mode.",
                stacklevel=2,
            )
            return True
        # Fail-secure in production: reject all webhooks if key is not configured
        print("[wallet] CRITICAL: MONNIFY_SECRET_KEY not set — rejecting webhook.", flush=True)
        return False
    expected = hmac.new(
        MONNIFY_SECRET_KEY.encode(),
        payload_bytes,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header or "")


def resolve_bank_name(code: str) -> str:
    """Map a Monnify bank code to a human-readable name."""
    return _BANK_NAMES.get(str(code), code or "Unknown bank")
