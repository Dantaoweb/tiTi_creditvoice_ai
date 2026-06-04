import random
import string
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from models import PendingAction, Transaction, User
from subscriptions import check_staff_limit, ensure_feature_allowed


def _generate_invite_code():
    return "".join(random.choices(string.digits, k=6))


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def handle_staff_command(db, phone, parsed, user, subscription, business_name, send_message):
    command_type = parsed.get("type")
    staff_command_types = [
        "STAFF_MENU",
        "GRANT_STAFF_VIEW_ALL",
        "REVOKE_STAFF_VIEW_ALL",
        "REMOVE_STAFF",
        "ADD_STAFF",
        "RESIGN_REQUEST",
    ]

    if command_type not in staff_command_types:
        return None

    if not user:
        send_message(phone, "Please register your business before using staff commands.")
        return {"status": "staff_command_unregistered"}

    if command_type == "STAFF_MENU":
        if user.role != "user" or user.parent_id is not None:
            send_message(phone, "âŒ Only business owners can view the staff management menu.")
            return {"status": "unauthorized_staff_menu"}

        allowed, upgrade_msg = ensure_feature_allowed(db, user, "STAFF", "Staff management")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "staff_plan_blocked"}

        staff_members = db.query(User).filter(User.parent_id == user.id).all()

        if not staff_members:
            send_message(
                phone,
                "You have no staff members registered yet.\n\n"
                "To add staff, send:\n*ADD STAFF [phone] [name]*"
            )
            return {"status": "staff_menu_empty"}

        msg = "ðŸ‘¥ Staff Management\n\n"
        for index, member in enumerate(staff_members, start=1):
            status = "âœ… Active" if member.role == "delegate" else "â³ Pending Invitation"
            access = "Can view all transactions" if member.can_view_all_transactions else "Own records only"

            sales = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
                Transaction.recorded_by_id == member.id,
                Transaction.type == "BUY"
            ).scalar()

            payments = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
                Transaction.recorded_by_id == member.id,
                Transaction.type == "PAY"
            ).scalar()

            msg += (
                f"{index}. *{member.name.title()}*\n"
                f"   Status: {status}\n"
                f"   Access: {access}\n"
                f"   Recorded: â‚¦{sales:,} (Sales), â‚¦{payments:,} (Payments)\n\n"
            )

        msg += (
            "Permission commands:\n"
            "GRANT STAFF [phone] VIEW ALL\n"
            "REVOKE STAFF [phone] VIEW ALL"
        )

        send_message(phone, msg)
        return {"status": "staff_menu_sent"}

    if command_type in ["GRANT_STAFF_VIEW_ALL", "REVOKE_STAFF_VIEW_ALL"]:
        if user.role != "user" or user.parent_id is not None:
            send_message(phone, "Only business owners can change staff permissions.")
            return {"status": "unauthorized_staff_permission"}

        allowed, upgrade_msg = ensure_feature_allowed(db, user, "STAFF_PERMISSION", "Staff permissions")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "staff_permission_plan_blocked"}

        staff_phone = parsed["phone"]
        staff_user = db.query(User).filter(
            User.phone == staff_phone,
            User.parent_id == user.id
        ).first()

        if not staff_user:
            send_message(
                phone,
                f"Staff member with phone {staff_phone} not found in your business list."
            )
            return {"status": "staff_not_found"}

        grant_access = command_type == "GRANT_STAFF_VIEW_ALL"
        staff_user.can_view_all_transactions = grant_access
        db.commit()

        permission_text = (
            "can now view all business transactions"
            if grant_access
            else "can now view only their own records"
        )
        send_message(
            phone,
            f"Updated {staff_user.name.title()}: {permission_text}."
        )
        send_message(
            staff_phone,
            f"Your CreditVoice access for *{user.name.title()}* was updated. You {permission_text}."
        )
        return {"status": "staff_permission_updated"}

    if command_type == "REMOVE_STAFF":
        if user.role != "user" or user.parent_id is not None:
            send_message(phone, "âŒ Only business owners can remove staff.")
            return {"status": "unauthorized_remove_staff"}

        allowed, upgrade_msg = ensure_feature_allowed(db, user, "STAFF", "Staff management")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "remove_staff_plan_blocked"}

        staff_phone = parsed["phone"]
        staff_user = db.query(User).filter(
            User.phone == staff_phone,
            User.parent_id == user.id
        ).first()

        if not staff_user:
            send_message(
                phone,
                f"âŒ Staff member with phone {staff_phone} not found in your business list."
            )
            return {"status": "staff_not_found"}

        staff_name = staff_user.name
        staff_user.role = "user"
        staff_user.parent_id = None
        staff_user.can_view_all_transactions = False
        db.commit()

        send_message(phone, f"âœ… Access revoked for {staff_name.title()} ({staff_phone}).")
        send_message(
            staff_phone,
            f"ðŸ“¢ Notification: Your access to *{user.name.title()}*'s business data has been revoked."
        )
        return {"status": "staff_removed"}

    if command_type == "ADD_STAFF":
        if user.role != "user" or user.parent_id is not None:
            send_message(phone, "âŒ Only business owners can add staff.")
            return {"status": "unauthorized_add_staff"}

        allowed, upgrade_msg = ensure_feature_allowed(db, user, "STAFF", "Adding staff")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "add_staff_plan_blocked"}

        staff_allowed, staff_limit_msg = check_staff_limit(db, user, subscription)
        if not staff_allowed:
            send_message(phone, staff_limit_msg)
            return {"status": "staff_limit_reached"}

        staff_phone = parsed["phone"]
        staff_name = parsed["name"]

        staff_user = db.query(User).filter(User.phone == staff_phone).first()
        if staff_user:
            staff_user.role = "delegate_pending"
            staff_user.parent_id = user.id
            staff_user.name = staff_name
            staff_user.can_view_all_transactions = False
        else:
            staff_user = User(
                phone=staff_phone,
                name=staff_name,
                role="delegate_pending",
                parent_id=user.id,
                can_view_all_transactions=False
            )
            db.add(staff_user)

        invite_code = _generate_invite_code()
        staff_user.invite_code = invite_code
        staff_user.invite_code_attempts = 0
        staff_user.invite_expires_at = _utcnow() + timedelta(hours=24)
        db.commit()

        # Staff message — does NOT contain the code
        send_message(
            staff_phone,
            f"Hello {staff_name.title()}!\n\n"
            f"*{user.name.title()}* has invited you to join their business on CreditVoice as staff.\n\n"
            f"Ask {user.name.title()} for your accept code, then reply:\n"
            f"accept [code]\n\n"
            "Example: accept 483920\n\n"
            "To decline: decline"
        )

        # Owner message — contains the code
        send_message(
            phone,
            f"Staff invitation sent to {staff_name.title()} ({staff_phone}).\n\n"
            f"Their accept code is: *{invite_code}*\n\n"
            f"Tell {staff_name.title()} to send:\n"
            f"accept {invite_code}\n\n"
            "The code expires in 24 hours."
        )
        return {"status": "staff_invited"}

    if command_type == "RESIGN_REQUEST":
        if user.role != "delegate":
            send_message(phone, "You are not currently registered as staff for any business.")
            return {"status": "resign_not_applicable"}

        res_pending = PendingAction(
            phone=phone,
            action="RESIGN_CONFIRM"
        )
        db.add(res_pending)
        db.commit()

        send_message(
            phone,
            f"I received your request to stop working with *{business_name.title()}*.\n\n"
            "Are you sure? This will remove your access to their records.\n\n1. Yes, Confirm\n2. No, Cancel"
        )
        return {"status": "resign_confirm_sent"}

    return None


def handle_resign_pending(db, phone, text, pending, user, business_owner_phone, business_name, send_message):
    """
    Handles the RESIGN_CONFIRM pending state.
    Extracted from webhook_pending_router so the router stays a thin dispatcher.
    """
    normalized = text.strip()

    if normalized in ["1", "yes"]:
        user.role = "user"
        user.parent_id = None
        user.can_view_all_transactions = False
        db.delete(pending)
        db.commit()
        send_message(
            phone,
            f"You have successfully resigned. You no longer have access to {business_name.title()}'s data."
        )
        if business_owner_phone != phone:
            send_message(
                business_owner_phone,
                f"Notice: {user.name.title()} has resigned as your staff member."
            )
        return {"status": "resigned_success"}

    if normalized in ["2", "no", "edit"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Resignation cancelled. You are still staff.")
        return {"status": "resigned_cancelled"}

    send_message(
        phone,
        f"Are you sure you want to stop working with {business_name.title()}?\n\n1. Yes, Confirm\n2. No, Cancel"
    )
    return {"status": "resign_confirm_waiting"}
