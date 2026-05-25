import re

from admin import support_line
from messages import build_plan_message, build_plan_payment_message, build_upgrade_message
from models import PendingAction, SubscriptionPayment
from plans import PLAN_GO, PLAN_PRO, normalize_plan
from subscriptions import create_subscription_payment_request, get_business_owner_user


def is_subscription_evidence_text(text):
    return bool(re.search(
        r"\b(receipt|ref|reference|transfer|payment|sent|paid)\b",
        text.lower()
    ))


def handle_subscription_media_receipt(
    db,
    phone,
    pending,
    user,
    message,
    message_type,
    evidence_ref,
    send_message,
    notify_admins,
):
    if (
        message_type not in ["image", "document"]
        or not pending
        or pending.action != "SUBSCRIPTION_PAYMENT_PENDING"
    ):
        return None

    payment = db.query(SubscriptionPayment).filter(
        SubscriptionPayment.id == pending.reminder_id,
        SubscriptionPayment.status == "PENDING"
    ).first()
    if not payment:
        return None

    owner = get_business_owner_user(db, user)
    payment.evidence_type = message_type.upper()
    payment.evidence_ref = evidence_ref(message, message_type)
    db.commit()
    notify_admins(db, payment, owner, send_message, evidence_received=True)
    send_message(
        phone,
        "Receipt received. Your subscription request is waiting for admin confirmation."
        f"{support_line()}"
    )
    return {"status": "subscription_receipt_received"}


def handle_upgrade_menu_pending(db, phone, text, pending, user, subscription, business_name, send_message):
    normalized = text.lower().strip()

    if normalized in ["1", "go"]:
        pending.action = "UPGRADE_PLAN_SELECTED"
        pending.customer_name = PLAN_GO
        db.commit()
        send_message(phone, build_plan_payment_message(PLAN_GO))
        return {"status": "upgrade_go_selected"}

    if normalized in ["2", "pro"]:
        pending.action = "UPGRADE_PLAN_SELECTED"
        pending.customer_name = PLAN_PRO
        db.commit()
        send_message(phone, build_plan_payment_message(PLAN_PRO))
        return {"status": "upgrade_pro_selected"}

    if normalized in ["3", "my plan", "plan"]:
        send_message(phone, build_plan_message(subscription))
        return {"status": "upgrade_my_plan"}

    if normalized in ["4", "cancel", "exit", "back"]:
        pending_business_name = pending.customer_name or business_name
        db.delete(pending)
        if not user:
            db.add(
                PendingAction(
                    phone=phone,
                    customer_name=pending_business_name,
                    action="POST_ONBOARDING_MENU",
                    last_customer=pending_business_name
                )
            )
        db.commit()
        send_message(phone, "Upgrade cancelled.")
        return {"status": "upgrade_cancelled"}

    send_message(phone, build_upgrade_message(user))
    return {"status": "upgrade_menu_waiting"}


def handle_upgrade_plan_selected(
    db,
    phone,
    text,
    pending,
    user,
    send_message,
    notify_admins,
):
    normalized = text.lower().strip()
    evidence_text = is_subscription_evidence_text(text)

    if normalized in ["cancel", "exit", "back", "stop"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Upgrade request closed.")
        return {"status": "upgrade_plan_cancelled"}

    if evidence_text or normalized in ["paid", "done", "i have paid", "i paid"]:
        plan = normalize_plan(pending.customer_name)
        payment = create_subscription_payment_request(db, user, plan)
        pending.action = "SUBSCRIPTION_PAYMENT_PENDING"
        pending.customer_name = plan
        pending.reminder_id = payment.id
        pending.last_customer = plan

        owner = get_business_owner_user(db, user)
        has_evidence = evidence_text and normalized not in ["paid", f"paid {plan.lower()}"]
        if has_evidence:
            payment.evidence_type = "TEXT"
            payment.evidence_ref = text[:500]

        db.commit()
        notify_admins(db, payment, owner, send_message, evidence_received=has_evidence)

        if has_evidence:
            send_message(
                phone,
                "Payment evidence received. Your subscription request is waiting for admin confirmation."
                f"{support_line()}"
            )
            return {"status": "subscription_text_evidence_received"}

        send_message(
            phone,
            f"Thank you. Your {plan} subscription request has been received.\n\n"
            "Please send your payment receipt screenshot or payment reference here. An admin will confirm and activate your plan."
            f"{support_line()}"
        )
        return {"status": "subscription_payment_pending"}

    send_message(
        phone,
        "After payment, send PAID GO or PAID PRO.\n"
        "You can also send your receipt screenshot or payment reference here."
    )
    return {"status": "upgrade_plan_waiting_for_payment"}


def handle_subscription_payment_pending(
    db,
    phone,
    text,
    pending,
    user,
    parsed,
    send_message,
    notify_admins,
):
    evidence_text = is_subscription_evidence_text(text)
    if parsed and not evidence_text:
        return None

    normalized = text.lower().strip()
    if normalized in ["cancel", "exit", "back", "stop"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Subscription payment request closed.")
        return {"status": "subscription_payment_cancelled"}

    payment = db.query(SubscriptionPayment).filter(
        SubscriptionPayment.id == pending.reminder_id,
        SubscriptionPayment.status == "PENDING"
    ).first()
    if not payment:
        return None

    owner = get_business_owner_user(db, user)
    payment.evidence_type = "TEXT"
    payment.evidence_ref = text[:500]
    db.commit()
    notify_admins(db, payment, owner, send_message, evidence_received=True)
    send_message(
        phone,
        "Payment evidence received. Your subscription request is waiting for admin confirmation."
        f"{support_line()}"
    )
    return {"status": "subscription_text_evidence_received"}


def handle_subscription_pending_flow(
    db,
    phone,
    text,
    pending,
    user,
    subscription,
    business_name,
    parsed,
    send_message,
    notify_admins,
):
    if not pending:
        return None

    if pending.action == "UPGRADE_MENU":
        return handle_upgrade_menu_pending(
            db,
            phone,
            text,
            pending,
            user,
            subscription,
            business_name,
            send_message,
        )

    if pending.action == "UPGRADE_PLAN_SELECTED":
        return handle_upgrade_plan_selected(
            db,
            phone,
            text,
            pending,
            user,
            send_message,
            notify_admins,
        )

    if pending.action == "SUBSCRIPTION_PAYMENT_PENDING":
        return handle_subscription_payment_pending(
            db,
            phone,
            text,
            pending,
            user,
            parsed,
            send_message,
            notify_admins,
        )

    return None
