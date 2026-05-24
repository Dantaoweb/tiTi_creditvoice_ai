from admin import (
    build_app_admin_selection_message,
    is_app_admin,
    is_subscription_admin,
)
from whatsapp_client import send_whatsapp_message


APP_ADMIN_COMMAND_TYPES = [
    "APP_ADMIN_DASHBOARD",
    "APP_ADMIN_USERS_BY_PLAN",
    "MANAGE_APP_ADMIN_ROLE",
    "LIST_APP_ADMIN_ROLES",
]

SUBSCRIPTION_ADMIN_COMMAND_TYPES = [
    "PENDING_SUBSCRIPTIONS",
    "APPROVE_SUBSCRIPTION",
    "REJECT_SUBSCRIPTION",
    "ACTIVATE_PLAN",
]

ADMIN_COMMAND_TYPES = APP_ADMIN_COMMAND_TYPES + SUBSCRIPTION_ADMIN_COMMAND_TYPES


def is_admin_command_allowed(db, phone, parsed):
    if not parsed:
        return False
    return (
        parsed["type"] in APP_ADMIN_COMMAND_TYPES and is_app_admin(phone, db)
    ) or (
        parsed["type"] in SUBSCRIPTION_ADMIN_COMMAND_TYPES
        and is_subscription_admin(phone, db)
    )


def filter_unregistered_admin_command(db, phone, user, parsed, is_command):
    if user or not parsed:
        return parsed, is_command

    admin_command_requested = parsed["type"] in ADMIN_COMMAND_TYPES
    if not is_admin_command_allowed(db, phone, parsed) and not admin_command_requested:
        return None, False

    return parsed, is_command


def handle_app_admin_dashboard_pending(
    db,
    phone,
    text,
    pending,
    require_app_admin=False,
):
    if not pending or pending.action != "APP_ADMIN_DASHBOARD":
        return None
    if require_app_admin and not is_app_admin(phone, db):
        return None

    normalized = text.strip().lower()
    status, msg = build_app_admin_selection_message(db, normalized)
    if status == "app_admin_unknown":
        send_whatsapp_message(phone, msg)
        return {"status": "invalid_app_admin_dashboard_option"}

    db.delete(pending)
    db.commit()
    send_whatsapp_message(phone, msg)
    return {"status": status}
