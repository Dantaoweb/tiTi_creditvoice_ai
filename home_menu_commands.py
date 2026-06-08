from context_memory import save_context
from messages import build_upgrade_message
from plans import PLAN_PRO
from reports import build_dashboard_menu_message


def handle_owner_home_menu(db, phone, text, pending, user, subscription, send_message):
    normalized = text.lower().strip()

    if normalized in ["1", "record", "record transaction", "transaction"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Record a sale:\nAde bought rice 5000\nAde paid 3000")
        return {"status": "owner_home_record_help"}

    if normalized in ["2", "select product", "sell", "product", "products"]:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "SELECT_PRODUCT"}}

    if normalized in ["3", "add customer", "customer"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Add a customer:\nJohn 08012345678\nor: add customer John")
        return {"status": "owner_home_add_customer"}

    if normalized in ["4", "dashboard"]:
        pending.action = "DASHBOARD_MENU"
        db.commit()
        save_context(db, phone, last_menu="DASHBOARD_MENU", last_topic="dashboard")
        send_message(phone, build_dashboard_menu_message())
        return {"status": "owner_home_dashboard"}

    if normalized in ["5", "stock", "inventory", "my stock", "my inventory"]:
        db.delete(pending)
        db.commit()
        save_context(db, phone, last_topic="stock")
        return {"parsed": {"type": "INVENTORY_LIST"}}

    if normalized in ["6", "supplier", "suppliers", "supplier list", "my suppliers"]:
        db.delete(pending)
        db.commit()
        save_context(db, phone, last_topic="suppliers")
        return {"parsed": {"type": "SUPPLIER_LIST"}}

    if normalized in ["7", "due", "reminders", "due reminders", "debt reminders"]:
        db.delete(pending)
        db.commit()
        save_context(db, phone, last_menu="DUE_MENU", last_topic="due")
        return {"parsed": {"type": "DUE_MENU"}}

    if normalized in ["8", "upgrade", "my plan", "plan"]:
        pending.action = "UPGRADE_MENU"
        db.commit()
        save_context(db, phone, last_topic="upgrade")
        send_message(phone, build_upgrade_message(user))
        return {"status": "owner_home_upgrade"}

    if normalized in ["10", "staff", "staff menu"] and subscription["plan"] == PLAN_PRO:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "STAFF_MENU"}}

    if normalized in ["9", "formats", "help", "format"]:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "FORMATS"}}

    if normalized in ["cancel", "exit", "back", "done", "stop"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Closed. You can continue anytime.")
        return {"status": "owner_home_closed"}

    db.delete(pending)
    db.commit()
    return None


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
        send_message(phone, "Record a sale:\nAde bought rice 5000\nAde paid 3000")
        return {"status": "staff_home_record_help"}

    if normalized in ["2", "select product", "sell", "product", "products"]:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "SELECT_PRODUCT"}}

    if normalized in ["3", "customers", "customer list", "list customers"]:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "CUSTOMER_LIST", "period": None}}

    if normalized in ["4", "dashboard"]:
        pending.action = "DASHBOARD_MENU"
        db.commit()
        save_context(db, phone, last_menu="DASHBOARD_MENU", last_topic="dashboard")
        send_message(phone, build_dashboard_menu_message())
        return {"status": "staff_home_dashboard"}

    if normalized in ["5", "stock", "inventory", "my stock", "my inventory"]:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "INVENTORY_LIST"}}

    if normalized in ["6", "supplier", "suppliers", "supplier list", "my suppliers"]:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "SUPPLIER_LIST"}}

    if normalized in ["7", "formats", "help", "format"]:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "FORMATS"}}

    if normalized in ["8", "resign"]:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "RESIGN_REQUEST"}}

    if normalized in ["cancel", "exit", "back", "done", "stop"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Closed. You can continue anytime.")
        return {"status": "staff_home_closed"}

    db.delete(pending)
    db.commit()
    return None


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
