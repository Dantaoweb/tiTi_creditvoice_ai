from whatsapp_client import send_whatsapp_message


def handle_delegate_invitation(db, phone, text, user, business_owner_phone, business_name):
    if not user or user.role != "delegate_pending":
        return None

    normalized = text.lower().strip()
    if normalized in ["1", "yes", "accept", "approve"]:
        user.role = "delegate"
        db.commit()
        send_whatsapp_message(
            phone,
            f"âœ… Access Accepted!\n\nYou are now an authorized staff member for *{business_name.title()}*. You can start recording transactions immediately.",
        )
        send_whatsapp_message(
            business_owner_phone,
            f"ðŸ“¢ Notification: {user.name.title()} has ACCEPTED your staff invitation.",
        )
        return {"status": "delegate_accepted"}

    if normalized in ["2", "no", "decline", "reject"]:
        user.role = "user"
        user.parent_id = None
        user.can_view_all_transactions = False
        db.commit()
        send_whatsapp_message(
            phone,
            f"âŒ Invitation Declined.\n\nYou are no longer associated with {business_name.title()}.",
        )
        send_whatsapp_message(
            business_owner_phone,
            f"ðŸ“¢ Notification: {user.name.title()} has DECLINED your staff invitation.",
        )
        return {"status": "delegate_declined"}

    send_whatsapp_message(
        phone,
        f"Hello {user.name.title()}! *{business_name.title()}* has added you as a staff member.\n\n"
        "Do you accept this invitation?\n\n1. Yes, Accept\n2. No, Decline",
    )
    return {"status": "delegate_invitation_pending"}
