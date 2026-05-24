from messages import build_owner_home_menu, build_staff_home_menu, build_upgrade_message
from plans import PLAN_PRO
from reports import build_dashboard_menu_message


def handle_owner_home_menu(db, phone, text, pending, user, subscription, send_message):
    normalized = text.lower().strip()

    if normalized in ["1", "record", "record transaction", "transaction"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Send a transaction like:\nAde bought rice 5000\nAde paid 3000")
        return {"status": "owner_home_record_help"}

    if normalized in ["2", "add customer", "customer"]:
        db.delete(pending)
        db.commit()
        send_message(
            phone,
            "To add a customer, send their name and phone number like:\n"
            "John 08012345678\n\nYou can also send:\nadd customer John"
        )
        return {"status": "owner_home_add_customer"}

    if normalized in ["3", "dashboard"]:
        pending.action = "DASHBOARD_MENU"
        db.commit()
        send_message(phone, build_dashboard_menu_message())
        return {"status": "owner_home_dashboard"}

    if normalized in ["4", "upgrade", "my plan", "plan"]:
        pending.action = "UPGRADE_MENU"
        db.commit()
        send_message(phone, build_upgrade_message())
        return {"status": "owner_home_upgrade"}

    if normalized in ["5", "staff", "staff menu"] and subscription["plan"] == PLAN_PRO:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "STAFF_MENU"}}

    if normalized in ["5", "6", "formats", "help", "format"]:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "FORMATS"}}

    if normalized in ["cancel", "exit", "back", "done", "stop"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Closed. You can continue anytime.")
        return {"status": "owner_home_closed"}

    send_message(phone, build_owner_home_menu(user, subscription))
    return {"status": "owner_home_waiting"}


def handle_staff_home_menu(
    db,
    phone,
    text,
    pending,
    user,
    business_name,
    can_view_all,
    send_message,
):
    normalized = text.lower().strip()

    if normalized in ["1", "record", "record transaction", "transaction"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Send a transaction like:\nAde bought rice 5000\nAde paid 3000")
        return {"status": "staff_home_record_help"}

    if normalized in ["2", "customers", "customer list", "list customers"]:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "CUSTOMER_LIST", "period": None}}

    if normalized in ["3", "dashboard"]:
        pending.action = "DASHBOARD_MENU"
        db.commit()
        send_message(phone, build_dashboard_menu_message())
        return {"status": "staff_home_dashboard"}

    if normalized in ["4", "resign"]:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "RESIGN_REQUEST"}}

    if normalized in ["cancel", "exit", "back", "done", "stop"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Closed. You can continue anytime.")
        return {"status": "staff_home_closed"}

    send_message(phone, build_staff_home_menu(user, business_name, can_view_all))
    return {"status": "staff_home_waiting"}


def handle_home_menu_pending(
    db,
    phone,
    text,
    pending,
    user,
    subscription,
    business_name,
    can_view_all,
    send_message,
):
    if not pending:
        return None

    if pending.action == "OWNER_HOME_MENU":
        return handle_owner_home_menu(
            db,
            phone,
            text,
            pending,
            user,
            subscription,
            send_message,
        )

    if pending.action == "STAFF_HOME_MENU":
        return handle_staff_home_menu(
            db,
            phone,
            text,
            pending,
            user,
            business_name,
            can_view_all,
            send_message,
        )

    return None
