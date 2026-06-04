"""
Account recovery via PIN.

Owner flow:
  set pin 1234          — store a 4-6 digit recovery PIN (hashed)
  change pin 1234 5678  — change PIN (old PIN required)
  remove pin 1234       — remove PIN

Recovery flow (from the new phone number):
  recover 08012345678 1234   — recover account by old phone + PIN
"""
import binascii
import hashlib
import os
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import text


MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 60


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── PIN hashing (PBKDF2-HMAC-SHA256, 100k iterations) ────────────────────────

def _hash_pin(pin: str, salt: bytes = None) -> str:
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 100_000)
    return binascii.hexlify(salt).decode() + ":" + binascii.hexlify(dk).decode()


def _verify_pin(pin: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split(":")
        salt = binascii.unhexlify(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 100_000)
        return binascii.hexlify(dk).decode() == dk_hex
    except Exception:
        return False


def _is_valid_pin(pin: str) -> bool:
    return bool(re.match(r"^\d{4,6}$", pin))


# ── Cascade phone update across all owner_phone tables ───────────────────────

_OWNER_PHONE_TABLES = [
    "customers",
    "suppliers",
    "supplier_purchases",
    "supplier_payments",
    "inventory_items",
    "inventory_movements",
    "automation_settings",
    "customer_conversations",
    "sales_orders",
    "fast_capture_settings",
    "fast_capture_entries",
    "reminder_automation_settings",
    "reminder_queue",
    "reminder_send_logs",
]

_PHONE_TABLES = [
    "pending_actions",
    "reminder_memory",
]


def _cascade_phone_update(db, old_phone: str, new_phone: str):
    for table in _OWNER_PHONE_TABLES:
        db.execute(
            text(f"UPDATE {table} SET owner_phone = :new WHERE owner_phone = :old"),
            {"new": new_phone, "old": old_phone},
        )
    for table in _PHONE_TABLES:
        db.execute(
            text(f"UPDATE {table} SET phone = :new WHERE phone = :old"),
            {"new": new_phone, "old": old_phone},
        )
    db.execute(
        text("UPDATE users SET phone = :new WHERE phone = :old"),
        {"new": new_phone, "old": old_phone},
    )


# ── Command handlers ──────────────────────────────────────────────────────────

def handle_set_pin(db, user, pin: str, send_message, phone: str) -> dict:
    if not _is_valid_pin(pin):
        send_message(phone, "PIN must be 4 to 6 digits. Example:\nset pin 1234")
        return {"status": "pin_invalid"}

    user.recovery_pin_hash = _hash_pin(pin)
    user.pin_attempts = 0
    user.pin_locked_until = None
    db.commit()

    send_message(
        phone,
        "Recovery PIN saved.\n\n"
        "Keep it safe — you will need it to recover your account if you change your phone number.\n\n"
        "To change your PIN:\nchange pin 1234 5678\n\n"
        "To remove your PIN:\nremove pin 1234"
    )
    return {"status": "pin_set"}


def handle_change_pin(db, user, old_pin: str, new_pin: str, send_message, phone: str) -> dict:
    if not user.recovery_pin_hash:
        send_message(phone, "You do not have a PIN set yet.\n\nTo set one:\nset pin 1234")
        return {"status": "pin_not_set"}

    if not _is_valid_pin(new_pin):
        send_message(phone, "New PIN must be 4 to 6 digits.")
        return {"status": "pin_invalid"}

    if not _verify_pin(old_pin, user.recovery_pin_hash):
        send_message(phone, "Old PIN is incorrect. Try again.")
        return {"status": "pin_wrong"}

    user.recovery_pin_hash = _hash_pin(new_pin)
    db.commit()
    send_message(phone, "PIN changed successfully.")
    return {"status": "pin_changed"}


def handle_remove_pin(db, user, pin: str, send_message, phone: str) -> dict:
    if not user.recovery_pin_hash:
        send_message(phone, "You do not have a PIN set.")
        return {"status": "pin_not_set"}

    if not _verify_pin(pin, user.recovery_pin_hash):
        send_message(phone, "PIN is incorrect.")
        return {"status": "pin_wrong"}

    user.recovery_pin_hash = None
    user.pin_attempts = 0
    user.pin_locked_until = None
    db.commit()
    send_message(phone, "Recovery PIN removed. Your account can no longer be recovered if you lose this number.")
    return {"status": "pin_removed"}


def handle_recover_account(db, new_phone: str, old_phone: str, pin: str, send_message) -> dict:
    from models import User
    from phone_utils import normalize_phone

    old_phone_normalized = normalize_phone(old_phone) or old_phone.strip()

    owner = db.query(User).filter(User.phone == old_phone_normalized).first()

    if not owner:
        send_message(
            new_phone,
            "No account found for that phone number.\n\n"
            "Check the number and try again:\nrecover 08012345678 1234"
        )
        return {"status": "recovery_account_not_found"}

    if not owner.recovery_pin_hash:
        send_message(
            new_phone,
            "That account does not have a recovery PIN set.\n\n"
            "Account recovery is not possible without a PIN.\n"
            "Please contact support for help."
        )
        return {"status": "recovery_no_pin"}

    # Lockout check
    if owner.pin_locked_until and owner.pin_locked_until > _utcnow():
        remaining = int((owner.pin_locked_until - _utcnow()).total_seconds() / 60) + 1
        send_message(
            new_phone,
            f"Too many wrong attempts. Try again in {remaining} minute(s)."
        )
        return {"status": "recovery_locked"}

    if not _verify_pin(pin, owner.recovery_pin_hash):
        owner.pin_attempts = (owner.pin_attempts or 0) + 1
        if owner.pin_attempts >= MAX_ATTEMPTS:
            owner.pin_locked_until = _utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
            owner.pin_attempts = 0
            db.commit()
            send_message(
                new_phone,
                f"Too many wrong attempts. Account locked for {LOCKOUT_MINUTES} minutes."
            )
            return {"status": "recovery_locked"}
        remaining_attempts = MAX_ATTEMPTS - owner.pin_attempts
        db.commit()
        send_message(
            new_phone,
            f"Wrong PIN. {remaining_attempts} attempt(s) remaining."
        )
        return {"status": "recovery_wrong_pin"}

    # PIN correct — check new_phone is not already taken
    existing = db.query(User).filter(User.phone == new_phone).first()
    if existing:
        send_message(
            new_phone,
            "This phone number already has a CreditVoice account.\n\n"
            "If you want to transfer your old account here, please contact support."
        )
        return {"status": "recovery_new_phone_taken"}

    # Cascade update
    try:
        _cascade_phone_update(db, old_phone_normalized, new_phone)
        db.commit()
    except Exception:
        db.rollback()
        send_message(new_phone, "Something went wrong during recovery. Please try again or contact support.")
        return {"status": "recovery_error"}

    send_message(
        new_phone,
        f"Account recovered successfully.\n\n"
        f"Your business account has been transferred to this number.\n"
        f"All your data, customers, stock, and transactions are intact.\n\n"
        "Please set a new PIN:\nset pin 1234"
    )
    return {"status": "recovery_success"}
