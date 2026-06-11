from context_memory import save_context
from messages import build_home_more_menu, build_owner_home_menu, build_upgrade_message
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

    if normalized in ["3", "add stock", "stock", "add", "inventory"]:
        from business_templates import has_service_price_catalog
        if has_service_price_catalog(user):
            from guided_service_commands import start_guided_service_setup
            return start_guided_service_setup(db, phone, user, send_message)
        else:
            from guided_stock_commands import start_guided_stock_flow
            return start_guided_stock_flow(db, phone, user, send_message)

    if normalized in ["4", "customers", "my customers", "customer list"]:
        db.delete(pending)
        db.commit()
        save_context(db, phone, last_topic="customers")
        return {"parsed": {"type": "CUSTOMER_LIST", "period": None}}

    if normalized in ["5", "reminders", "due", "due reminders", "debt reminders"]:
        db.delete(pending)
        db.commit()
        save_context(db, phone, last_menu="DUE_MENU", last_topic="due")
        return {"parsed": {"type": "DUE_MENU"}}

    if normalized in ["6", "dashboard"]:
        pending.action = "DASHBOARD_MENU"
        db.commit()
        save_context(db, phone, last_menu="DASHBOARD_MENU", last_topic="dashboard")
        send_message(phone, build_dashboard_menu_message())
        return {"status": "owner_home_dashboard"}

    if normalized in ["7", "wallet"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Wallet is coming soon.\n\nYou will be able to top up, withdraw, and pay bills directly from tiTi.")
        return {"status": "owner_home_wallet"}

    if normalized in ["8", "help", "formats", "format"]:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "FORMATS"}}

    if normalized in ["9", "more"]:
        pending.action = "HOME_MORE_MENU"
        db.commit()
        send_message(phone, build_home_more_menu())
        return {"status": "owner_home_more"}

    if normalized in ["cancel", "exit", "back", "done", "stop"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Closed. You can continue anytime.")
        return {"status": "owner_home_closed"}

    db.delete(pending)
    db.commit()
    return None


def handle_home_more_menu(db, phone, text, pending, user, subscription, send_message):
    normalized = text.lower().strip()

    if normalized in ["1", "suppliers", "supplier"]:
        db.delete(pending)
        db.commit()
        save_context(db, phone, last_topic="suppliers")
        return {"parsed": {"type": "SUPPLIER_LIST"}}

    if normalized in ["2", "my plan", "plan", "upgrade"]:
        pending.action = "UPGRADE_MENU"
        db.commit()
        save_context(db, phone, last_topic="upgrade")
        send_message(phone, build_upgrade_message(user))
        return {"status": "more_upgrade"}

    if normalized in ["3", "staff"]:
        if subscription.get("plan") == PLAN_PRO:
            db.delete(pending)
            db.commit()
            return {"parsed": {"type": "STAFF_MENU"}}
        send_message(phone, "Staff management requires PRO plan.\n\nSend UPGRADE to see plans.")
        return {"status": "more_staff_no_plan"}

    if normalized in ["4", "back", "main menu", "home", "menu"]:
        pending.action = "OWNER_HOME_MENU"
        db.commit()
        send_message(phone, build_owner_home_menu(user, subscription))
        return {"status": "more_back"}

    if normalized in ["cancel", "exit", "stop", "done"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Closed. You can continue anytime.")
        return {"status": "more_closed"}

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

    if normalized in ["3", "customers", "my customers", "customer list"]:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "CUSTOMER_LIST", "period": None}}

    if normalized in ["4", "dashboard"]:
        pending.action = "DASHBOARD_MENU"
        db.commit()
        save_context(db, phone, last_menu="DASHBOARD_MENU", last_topic="dashboard")
        send_message(phone, build_dashboard_menu_message())
        return {"status": "staff_home_dashboard"}

    if normalized in ["5", "stock", "inventory", "my stock"]:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "INVENTORY_LIST"}}

    if normalized in ["6", "help", "formats", "format"]:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "FORMATS"}}

    if normalized in ["7", "resign"]:
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

    if pending.action == "HOME_MORE_MENU":
        return handle_home_more_menu(
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
