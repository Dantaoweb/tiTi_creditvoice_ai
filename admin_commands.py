from datetime import datetime, timedelta

from admin import (
    ROLE_APP_ADMIN,
    app_admin_phones,
    build_app_admin_dashboard_message,
    format_admin_roles,
    format_pending_subscriptions,
    format_user_list,
    is_app_admin,
    is_subscription_admin,
    set_admin_role,
    subscription_admin_phones,
    support_line,
)
from messages import build_plan_message
from models import PendingAction, SubscriptionPayment, User
from plans import PLAN_BASIC, normalize_plan
from subscriptions import (
    approve_subscription_payment,
    create_subscription_payment_request,
    get_business_owner_user,
    get_business_subscription,
    get_business_users_by_effective_plan,
)


def notify_subscription_admins(db, payment, owner, send_message, evidence_received=False):
    admin_phones = []
    for admin_phone in subscription_admin_phones() + app_admin_phones():
        if admin_phone and admin_phone not in admin_phones:
            admin_phones.append(admin_phone)

    if not admin_phones:
        return

    owner_name = owner.name.title() if owner and owner.name else payment.phone
    evidence_line = "Evidence received: yes" if evidence_received else "Evidence received: no"
    message = (
        "Subscription Payment Pending\n\n"
        f"Business: {owner_name}\n"
        f"Phone: {payment.phone}\n"
        f"Plan: {payment.plan}\n"
        f"Amount: N{payment.amount:,}\n"
        f"{evidence_line}\n\n"
        f"Approve: approve {payment.phone}\n"
        f"Reject: reject {payment.phone}"
    )

    for admin_phone in admin_phones:
        send_message(admin_phone, message)


def handle_admin_subscription_command(db, phone, parsed, user, send_message, notify_admins):
    command_type = parsed.get("type")

    if command_type == "SUBSCRIPTION_PAID":
        payment = create_subscription_payment_request(db, user, parsed["plan"])
        db.query(PendingAction).filter(
            PendingAction.phone == phone
        ).delete()
        db.add(
            PendingAction(
                phone=phone,
                customer_name=parsed["plan"],
                action="SUBSCRIPTION_PAYMENT_PENDING",
                reminder_id=payment.id,
                last_customer=""
            )
        )
        owner = get_business_owner_user(db, user)
        db.commit()
        notify_admins(db, payment, owner, send_message, evidence_received=False)
        send_message(
            phone,
            f"Thank you. Your {parsed['plan']} subscription request has been received.\n\n"
            "Please send your payment receipt screenshot here. An admin will confirm and activate your plan."
            f"{support_line()}"
        )
        return {"status": "subscription_payment_pending"}

    if command_type == "PENDING_SUBSCRIPTIONS":
        if not is_subscription_admin(phone, db):
            send_message(phone, "Only subscription admins can view pending subscriptions.")
            return {"status": "unauthorized_pending_subscriptions"}

        payments = db.query(SubscriptionPayment, User).outerjoin(
            User,
            SubscriptionPayment.user_id == User.id
        ).filter(
            SubscriptionPayment.status == "PENDING"
        ).order_by(
            SubscriptionPayment.created_at.asc()
        ).all()
        send_message(phone, format_pending_subscriptions(payments))
        db.query(PendingAction).filter(
            PendingAction.phone == phone
        ).delete()
        if payments:
            db.add(
                PendingAction(
                    phone=phone,
                    customer_name="",
                    action="SUBSCRIPTION_APPROVAL_LIST",
                    last_customer=""
                )
            )
        db.commit()
        return {"status": "pending_subscriptions"}

    if command_type == "APP_ADMIN_DASHBOARD":
        if not is_app_admin(phone, db):
            send_message(phone, "Only app admins can view the app admin dashboard.")
            return {"status": "unauthorized_app_admin_dashboard"}

        db.query(PendingAction).filter(
            PendingAction.phone == phone
        ).delete()
        db.add(
            PendingAction(
                phone=phone,
                customer_name="",
                action="APP_ADMIN_DASHBOARD",
                last_customer=""
            )
        )
        db.commit()
        send_message(phone, build_app_admin_dashboard_message(db))
        return {"status": "app_admin_dashboard"}

    if command_type == "APP_ADMIN_USERS_BY_PLAN":
        if not is_app_admin(phone, db):
            send_message(phone, "Only app admins can view app users.")
            return {"status": "unauthorized_app_admin_users"}

        users = get_business_users_by_effective_plan(db, parsed["plan"])
        title = "FREE/BASIC Users" if parsed["plan"] == PLAN_BASIC else f"{parsed['plan']} Users"
        send_message(phone, format_user_list(users, title))
        return {"status": "app_admin_users_by_plan"}

    if command_type == "MANAGE_APP_ADMIN_ROLE":
        if not is_app_admin(phone, db):
            send_message(phone, "Only app admins can manage admin roles.")
            return {"status": "unauthorized_admin_role_management"}

        if not parsed.get("role"):
            send_message(phone, "Unknown admin role.")
            return {"status": "unknown_admin_role"}

        if parsed["role"] == ROLE_APP_ADMIN and parsed["phone"] in app_admin_phones() and not parsed["active"]:
            send_message(
                phone,
                "Root app admins from Render APP_ADMIN_PHONES cannot be denied from WhatsApp."
            )
            return {"status": "cannot_deny_root_app_admin"}

        role_record = set_admin_role(
            db,
            parsed["phone"],
            parsed["role"],
            parsed["active"],
            actor_user=user
        )
        db.commit()
        status_text = "allowed" if role_record.is_active else "denied"
        send_message(
            phone,
            f"{role_record.phone} is now {status_text} for {role_record.role}."
        )
        return {"status": "admin_role_updated"}

    if command_type == "LIST_APP_ADMIN_ROLES":
        if not is_app_admin(phone, db):
            send_message(phone, "Only app admins can view admin roles.")
            return {"status": "unauthorized_admin_role_list"}

        send_message(phone, format_admin_roles(db))
        return {"status": "admin_roles"}

    if command_type == "APPROVE_SUBSCRIPTION":
        if not is_subscription_admin(phone, db):
            send_message(phone, "Only subscription admins can approve subscriptions.")
            return {"status": "unauthorized_subscription_approval"}

        payment = db.query(SubscriptionPayment).filter(
            SubscriptionPayment.phone == parsed["phone"],
            SubscriptionPayment.status == "PENDING"
        ).order_by(
            SubscriptionPayment.created_at.desc()
        ).first()
        if not payment:
            send_message(phone, "No pending subscription payment found for that phone.")
            return {"status": "subscription_payment_not_found"}

        owner = approve_subscription_payment(db, payment, user)
        db.query(PendingAction).filter(
            PendingAction.phone == owner.phone,
            PendingAction.action == "SUBSCRIPTION_PAYMENT_PENDING"
        ).delete()
        db.commit()
        send_message(
            phone,
            f"Approved {owner.name.title()} for {owner.subscription_plan}.\n"
            f"Expires: {owner.subscription_expires_at.strftime('%d/%m/%Y')}"
        )
        send_message(
            owner.phone,
            f"Your {owner.subscription_plan} plan is now active.\n"
            f"Expires: {owner.subscription_expires_at.strftime('%d/%m/%Y')}\n\n"
            "Send MY PLAN anytime to check your subscription."
        )
        return {"status": "subscription_approved"}

    if command_type == "REJECT_SUBSCRIPTION":
        if not is_subscription_admin(phone, db):
            send_message(phone, "Only subscription admins can reject subscriptions.")
            return {"status": "unauthorized_subscription_rejection"}

        payment = db.query(SubscriptionPayment).filter(
            SubscriptionPayment.phone == parsed["phone"],
            SubscriptionPayment.status == "PENDING"
        ).order_by(
            SubscriptionPayment.created_at.desc()
        ).first()
        if not payment:
            send_message(phone, "No pending subscription payment found for that phone.")
            return {"status": "subscription_payment_not_found"}

        payment.status = "REJECTED"
        owner = db.query(User).filter(User.id == payment.user_id).first()
        if owner:
            db.query(PendingAction).filter(
                PendingAction.phone == owner.phone,
                PendingAction.action == "SUBSCRIPTION_PAYMENT_PENDING"
            ).delete()
        db.commit()
        send_message(phone, "Subscription payment rejected.")
        if owner:
            send_message(
                owner.phone,
                "Your subscription payment could not be confirmed. Please send a clearer receipt."
                f"{support_line()}"
            )
        return {"status": "subscription_rejected"}

    if command_type == "ACTIVATE_PLAN":
        if not is_subscription_admin(phone, db):
            send_message(phone, "Only subscription admins can activate plans.")
            return {"status": "unauthorized_plan_activation"}

        target_user = db.query(User).filter(
            User.phone == parsed["phone"]
        ).first()
        if not target_user:
            send_message(phone, "User not found for that phone number.")
            return {"status": "plan_target_not_found"}

        target_owner = get_business_owner_user(db, target_user)
        target_owner.subscription_plan = normalize_plan(parsed["plan"])
        target_owner.subscription_status = "ACTIVE"
        if parsed.get("days"):
            target_owner.subscription_expires_at = datetime.utcnow() + timedelta(days=parsed["days"])
        else:
            target_owner.subscription_expires_at = None
        db.commit()

        updated_subscription = get_business_subscription(db, target_owner)
        send_message(
            phone,
            f"Plan updated for {target_owner.name.title()}.\n\n"
            f"{build_plan_message(updated_subscription)}"
        )
        if target_owner.phone != phone:
            send_message(
                target_owner.phone,
                f"Your CreditVoice plan is now {target_owner.subscription_plan}."
            )
        return {"status": "plan_activated"}

    return None


def handle_subscription_admin_pending_selection(db, phone, text, pending, user, send_message):
    if not pending or pending.action != "SUBSCRIPTION_APPROVAL_LIST":
        return None

    if not is_subscription_admin(phone, db):
        return None

    normalized = text.lower().strip()
    if normalized in ["cancel", "exit", "back", "done", "stop"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Subscription approval list closed.")
        return {"status": "subscription_approval_list_closed"}

    reject_match = normalized.startswith("reject ")
    number_text = normalized.replace("reject", "", 1).strip() if reject_match else normalized
    if not number_text.isdigit():
        send_message(
            phone,
            "Reply with a pending subscription number to approve, like 1.\n"
            "To reject, send reject 1."
        )
        return {"status": "invalid_subscription_approval_selection"}

    payments = db.query(SubscriptionPayment, User).outerjoin(
        User,
        SubscriptionPayment.user_id == User.id
    ).filter(
        SubscriptionPayment.status == "PENDING"
    ).order_by(
        SubscriptionPayment.created_at.asc()
    ).all()

    index = int(number_text)
    if index < 1 or index > len(payments):
        send_message(phone, "Pending subscription number not found.")
        return {"status": "subscription_approval_selection_not_found"}

    payment, owner = payments[index - 1]
    if reject_match:
        payment.status = "REJECTED"
        if owner:
            db.query(PendingAction).filter(
                PendingAction.phone == owner.phone,
                PendingAction.action == "SUBSCRIPTION_PAYMENT_PENDING"
            ).delete()
        db.delete(pending)
        db.commit()
        send_message(phone, f"Rejected subscription payment for {payment.phone}.")
        if owner:
            send_message(
                owner.phone,
                "Your subscription payment could not be confirmed. Please send a clearer receipt."
                f"{support_line()}"
            )
        return {"status": "subscription_rejected_by_number"}

    owner = approve_subscription_payment(db, payment, user)
    db.query(PendingAction).filter(
        PendingAction.phone == owner.phone,
        PendingAction.action == "SUBSCRIPTION_PAYMENT_PENDING"
    ).delete()
    db.delete(pending)
    db.commit()
    send_message(
        phone,
        f"Approved {owner.name.title()} for {owner.subscription_plan}.\n"
        f"Expires: {owner.subscription_expires_at.strftime('%d/%m/%Y')}"
    )
    send_message(
        owner.phone,
        f"Your {owner.subscription_plan} plan is now active.\n"
        f"Expires: {owner.subscription_expires_at.strftime('%d/%m/%Y')}\n\n"
        "Send MY PLAN anytime to check your subscription."
    )
    return {"status": "subscription_approved_by_number"}
