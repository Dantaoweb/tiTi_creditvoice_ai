import re
from datetime import datetime, timezone

from whatsapp_client import send_whatsapp_message


MAX_INVITE_ATTEMPTS = 3


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def handle_delegate_invitation(db, phone, text, user, business_owner_phone, business_name):
    if not user or user.role != "delegate_pending":
        return None

    normalized = text.lower().strip()

    # ── Decline ───────────────────────────────────────────────────────────────
    if normalized in ["2", "no", "decline", "reject"]:
        user.role = "user"
        user.parent_id = None
        user.can_view_all_transactions = False
        user.invite_code = None
        user.invite_code_attempts = 0
        user.invite_expires_at = None
        db.commit()
        send_whatsapp_message(
            phone,
            f"Invitation declined.\n\nYou are no longer associated with {business_name.title()}.",
        )
        send_whatsapp_message(
            business_owner_phone,
            f"{user.name.title()} has declined your staff invitation.",
        )
        return {"status": "delegate_declined"}

    # ── Check for expired invite ──────────────────────────────────────────────
    if user.invite_expires_at and user.invite_expires_at < _utcnow():
        user.role = "user"
        user.parent_id = None
        user.invite_code = None
        user.invite_code_attempts = 0
        user.invite_expires_at = None
        db.commit()
        send_whatsapp_message(
            phone,
            "This invitation has expired.\n\n"
            "Ask the business owner to send a new invite."
        )
        return {"status": "delegate_invite_expired"}

    # ── Parse "accept [code]" ─────────────────────────────────────────────────
    accept_match = re.match(r"^accept\s+(?P<code>\d{4,8})$", normalized)

    if not accept_match:
        # Any other message — show the instructions again
        send_whatsapp_message(
            phone,
            f"You have a pending staff invitation from *{business_name.title()}*.\n\n"
            f"Ask {business_name.title()} for your accept code, then reply:\n"
            f"accept [code]\n\n"
            "Example: accept 483920\n\n"
            "To decline: decline"
        )
        return {"status": "delegate_greeted"}

    code_entered = accept_match.group("code")

    # ── Check attempts ────────────────────────────────────────────────────────
    attempts = user.invite_code_attempts or 0
    if attempts >= MAX_INVITE_ATTEMPTS:
        user.role = "user"
        user.parent_id = None
        user.invite_code = None
        user.invite_code_attempts = 0
        user.invite_expires_at = None
        db.commit()
        send_whatsapp_message(
            phone,
            "Too many wrong attempts. This invitation has been cancelled.\n\n"
            "Ask the business owner to send a new invite."
        )
        send_whatsapp_message(
            business_owner_phone,
            f"Staff invite for {user.name.title()} was cancelled after too many wrong code attempts.\n"
            "Send a new invite if needed."
        )
        return {"status": "delegate_invite_cancelled"}

    # ── Verify code ───────────────────────────────────────────────────────────
    if not user.invite_code or code_entered != user.invite_code:
        user.invite_code_attempts = attempts + 1
        remaining = MAX_INVITE_ATTEMPTS - user.invite_code_attempts
        db.commit()
        send_whatsapp_message(
            phone,
            f"Wrong code. {remaining} attempt(s) remaining.\n\n"
            "Ask the business owner for the correct code."
        )
        return {"status": "delegate_wrong_code"}

    # ── Code correct — accept ─────────────────────────────────────────────────
    user.role = "delegate"
    user.invite_code = None
    user.invite_code_attempts = 0
    user.invite_expires_at = None
    db.commit()

    send_whatsapp_message(
        phone,
        f"Access accepted!\n\n"
        f"You are now an authorised staff member for *{business_name.title()}*.\n"
        "You can start recording transactions immediately."
    )
    send_whatsapp_message(
        business_owner_phone,
        f"{user.name.title()} has accepted your staff invitation and is now active."
    )
    return {"status": "delegate_accepted"}
