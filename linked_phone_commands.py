"""
Multi-phone / linked numbers.

Owner flow:
  link phone 08012345678   — send a link code to a second number
  unlink phone 08012345678 — remove a linked number
  my phones                — list all linked numbers

Second phone flow:
  link confirm 483920      — confirm linking with the code the owner received
"""
import random
import string
from datetime import datetime, timedelta, timezone

from phone_utils import normalize_phone

from models import LinkedPhone, PendingAction, User


MAX_LINKED_PHONES = 2
LINK_CODE_EXPIRY_MINUTES = 30


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _generate_link_code() -> str:
    return "".join(random.choices(string.digits, k=6))


# ── Link a new phone ──────────────────────────────────────────────────────────

def handle_link_phone(db, user, raw_phone: str, send_message, phone: str) -> dict:
    target_phone = normalize_phone(raw_phone) or raw_phone.strip()

    if not target_phone or len(target_phone) < 7:
        send_message(phone, "Invalid phone number. Try:\nlink phone 08012345678")
        return {"status": "link_invalid_phone"}

    if target_phone == phone or target_phone == user.phone:
        send_message(phone, "You cannot link your own number.")
        return {"status": "link_same_phone"}

    # Check if already a registered owner
    existing_user = db.query(User).filter(User.phone == target_phone).first()
    if existing_user and existing_user.role == "user" and not existing_user.parent_id:
        send_message(
            phone,
            f"{target_phone} already has its own CreditVoice business account.\n\n"
            "You can only link a number that does not have its own account."
        )
        return {"status": "link_phone_has_account"}

    # Check limit
    active_count = db.query(LinkedPhone).filter(
        LinkedPhone.owner_user_id == user.id,
        LinkedPhone.is_active == True,
    ).count()
    if active_count >= MAX_LINKED_PHONES:
        send_message(
            phone,
            f"You have reached the maximum of {MAX_LINKED_PHONES} linked phones.\n\n"
            "To add a new one, first unlink an existing number:\n"
            "unlink phone 08012345678"
        )
        return {"status": "link_limit_reached"}

    # Check if number is already linked to this owner (pending or active)
    existing_link = db.query(LinkedPhone).filter(
        LinkedPhone.linked_phone == target_phone,
    ).first()
    if existing_link:
        if existing_link.owner_user_id == user.id and existing_link.is_active:
            send_message(phone, f"{target_phone} is already linked to your account.")
            return {"status": "link_already_linked"}
        # Remove stale link if it belongs to someone else or is pending
        db.delete(existing_link)
        db.flush()

    code = _generate_link_code()
    link = LinkedPhone(
        owner_user_id=user.id,
        linked_phone=target_phone,
        link_code=code,
        link_code_expires_at=_utcnow() + timedelta(minutes=LINK_CODE_EXPIRY_MINUTES),
        is_active=False,
    )
    db.add(link)
    db.commit()

    # Message to the target phone
    send_message(
        target_phone,
        f"*{user.name.title()}* wants to link this number to their CreditVoice business account.\n\n"
        "If this is you, confirm with the code from the owner:\n"
        "link confirm [code]\n\n"
        "Example: link confirm 483920\n\n"
        "To decline: link decline\n\n"
        "Code expires in 30 minutes."
    )

    # Code goes only to the owner — not to the target phone
    send_message(
        phone,
        f"Link request sent to {target_phone}.\n\n"
        f"Tell them to send:\nlink confirm {code}\n\n"
        "The code expires in 30 minutes.\n"
        "Once confirmed, that number will have full access to your account."
    )
    return {"status": "link_requested"}


# ── Confirm from the second phone ─────────────────────────────────────────────

def handle_link_confirm(db, phone: str, code: str, send_message) -> dict:
    link = db.query(LinkedPhone).filter(
        LinkedPhone.linked_phone == phone,
        LinkedPhone.is_active == False,
    ).first()

    if not link:
        send_message(phone, "No pending link request found for this number.")
        return {"status": "link_confirm_not_found"}

    if link.link_code_expires_at and link.link_code_expires_at < _utcnow():
        db.delete(link)
        db.commit()
        send_message(phone, "This link request has expired. Ask the owner to send a new one.")
        return {"status": "link_confirm_expired"}

    if code != link.link_code:
        send_message(phone, "Wrong code. Ask the owner for the correct code.")
        return {"status": "link_confirm_wrong_code"}

    # Activate the link and clear any stale onboarding pending actions
    link.is_active = True
    link.link_code = None
    link.link_code_expires_at = None
    db.query(PendingAction).filter(PendingAction.phone == phone).delete()
    db.commit()

    owner = db.query(User).filter(User.id == link.owner_user_id).first()
    owner_name = owner.name.title() if owner else "the owner"

    send_message(
        phone,
        f"Linked!\n\nThis number now has full access to *{owner_name}*'s CreditVoice account.\n"
        "You can record transactions, check reports, and use all features."
    )
    if owner:
        send_message(
            owner.phone,
            f"{phone} has confirmed linking to your account.\n"
            "They now have full access to your business records."
        )
    return {"status": "link_confirmed"}


# ── Decline from the second phone ─────────────────────────────────────────────

def handle_link_decline(db, phone: str, send_message) -> dict:
    link = db.query(LinkedPhone).filter(
        LinkedPhone.linked_phone == phone,
        LinkedPhone.is_active == False,
    ).first()

    if not link:
        return None  # silently ignore — not a link flow

    owner = db.query(User).filter(User.id == link.owner_user_id).first()
    db.delete(link)
    db.commit()

    send_message(phone, "Link request declined.")
    if owner:
        send_message(
            owner.phone,
            f"{phone} has declined the link request."
        )
    return {"status": "link_declined"}


# ── Unlink a phone ────────────────────────────────────────────────────────────

def handle_unlink_phone(db, user, raw_phone: str, send_message, phone: str) -> dict:
    target_phone = normalize_phone(raw_phone) or raw_phone.strip()

    link = db.query(LinkedPhone).filter(
        LinkedPhone.owner_user_id == user.id,
        LinkedPhone.linked_phone == target_phone,
    ).first()

    if not link:
        send_message(phone, f"{target_phone} is not linked to your account.")
        return {"status": "unlink_not_found"}

    db.delete(link)
    db.commit()

    send_message(phone, f"{target_phone} has been unlinked from your account.")
    send_message(target_phone, f"Your access to *{user.name.title()}*'s account has been removed.")
    return {"status": "unlinked"}


# ── List linked phones ────────────────────────────────────────────────────────

def handle_my_phones(db, user, send_message, phone: str) -> dict:
    links = db.query(LinkedPhone).filter(
        LinkedPhone.owner_user_id == user.id,
        LinkedPhone.is_active == True,
    ).all()

    if not links:
        send_message(
            phone,
            "No linked phones.\n\n"
            "To link a second number:\nlink phone 08012345678"
        )
    else:
        lines = ["Linked phones:\n"]
        for i, lk in enumerate(links, 1):
            lines.append(f"{i}. {lk.linked_phone}")
        lines.append(f"\nMax allowed: {MAX_LINKED_PHONES}")
        lines.append("To remove: unlink phone 08012345678")
        send_message(phone, "\n".join(lines))
    return {"status": "my_phones"}


# ── Check if a phone is a linked phone (used by webhook_context) ──────────────

def get_pending_link(db, phone: str):
    """Return a LinkedPhone record that is awaiting confirmation, or None."""
    return db.query(LinkedPhone).filter(
        LinkedPhone.linked_phone == phone,
        LinkedPhone.is_active == False,
        LinkedPhone.link_code.isnot(None),
    ).first()


def find_owner_via_linked_phone(db, phone: str):
    link = db.query(LinkedPhone).filter(
        LinkedPhone.linked_phone == phone,
        LinkedPhone.is_active == True,
    ).first()
    if not link:
        return None
    return db.query(User).filter(User.id == link.owner_user_id).first()
