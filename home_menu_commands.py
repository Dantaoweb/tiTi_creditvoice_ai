from context_memory import save_context
from messages import build_home_more_menu, build_owner_home_menu, build_upgrade_message
from plans import PLAN_PRO
from reports import build_dashboard_menu_message


def _group(user):
    from business_templates import menu_group_for_user
    return menu_group_for_user(user) if user else "stock"


def _record_help(db, phone, user, pending, send_message):
    from business_templates import template_examples_for_user
    examples = template_examples_for_user(user) if user else [
        "Ade bought rice 5000", "Ade paid 3000", "dashboard"
    ]
    db.delete(pending)
    db.commit()
    send_message(phone, f"Try sending:\n{examples[0]}\n\n{examples[1]}")


def _go_dashboard(db, phone, pending, send_message):
    pending.action = "DASHBOARD_MENU"
    db.commit()
    save_context(db, phone, last_menu="DASHBOARD_MENU", last_topic="dashboard")
    send_message(phone, build_dashboard_menu_message())
    return {"status": "owner_home_dashboard"}


def _go_more(db, phone, user, pending, send_message):
    pending.action = "HOME_MORE_MENU"
    db.commit()
    send_message(phone, build_home_more_menu(user))
    return {"status": "owner_home_more"}


def _wallet_msg(db, phone, pending, send_message):
    db.delete(pending)
    db.commit()
    send_message(phone, "Wallet is coming soon.\n\nYou will be able to top up, withdraw, and pay bills directly from tiTi.")
    return {"status": "owner_home_wallet"}


def handle_owner_home_menu(db, phone, text, pending, user, subscription, send_message):
    normalized = text.lower().strip()
    group = _group(user)

    # ── Global keywords — always work regardless of menu group ────────────────

    if normalized in ["record", "record sale", "record transaction", "transaction",
                       "record payment", "record fee", "record fee payment",
                       "record contribution", "record job"]:
        _record_help(db, phone, user, pending, send_message)
        return {"status": "owner_home_record_help"}

    if normalized in ["my trucks", "trucks", "truck list", "all trucks", "registered trucks"]:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "MY_TRUCKS"}}

    if normalized in ["record trip", "trip", "new trip", "add trip"]:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "RECORD_TRIP_WIZARD"}}

    if normalized in ["add truck", "register truck", "new truck"]:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "ADD_TRUCK_WIZARD"}}

    if normalized in ["select product", "sell"]:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "SELECT_PRODUCT"}}

    if normalized in ["select service", "services"] and group == "clinic":
        from guided_service_commands import start_guided_service_setup
        return start_guided_service_setup(db, phone, user, send_message)

    if normalized in ["select group", "rates", "contribution rates", "groups",
                      "rate", "group rates", "price list"] and group == "thrift":
        from guided_service_commands import start_guided_service_setup
        return start_guided_service_setup(db, phone, user, send_message)

    if normalized in ["fee schedule", "fee list", "fees", "price list", "fee prices"] and group == "school":
        from guided_service_commands import start_guided_service_setup
        return start_guided_service_setup(db, phone, user, send_message)

    if normalized in ["menu", "price list", "food menu", "menu prices"] and group == "food":
        from guided_service_commands import start_guided_service_setup
        return start_guided_service_setup(db, phone, user, send_message)

    if normalized in ["stock", "inventory", "add stock", "textbooks", "textbook",
                       "consumables", "supplies"]:
        from business_templates import has_service_price_catalog
        if group not in ("clinic", "school", "food") and has_service_price_catalog(user):
            from guided_service_commands import start_guided_service_setup
            return start_guided_service_setup(db, phone, user, send_message)
        from guided_stock_commands import start_guided_stock_flow
        return start_guided_stock_flow(db, phone, user, send_message)

    if normalized in ["price list", "price lists", "service prices"]:
        from guided_service_commands import start_guided_service_setup
        return start_guided_service_setup(db, phone, user, send_message)

    if normalized in ["service jobs", "jobs"]:
        db.delete(pending)
        db.commit()
        from business_templates import template_examples_for_user
        examples = template_examples_for_user(user) if user else [
            "John brought 10 shirts, 5 trousers", "John paid 3000"
        ]
        send_message(
            phone,
            f"Record a service job:\n*{examples[0]}*\n\n"
            f"Payment: *{examples[1]}*\n\n"
            "Send *price list* to view or update your service prices."
        )
        return {"status": "owner_home_service_jobs"}

    if normalized in ["customers", "my customers", "customer list",
                       "students", "my students", "student list",
                       "participants", "my participants",
                       "patients", "my patients", "patient list"]:
        db.delete(pending)
        db.commit()
        save_context(db, phone, last_topic="customers")
        return {"parsed": {"type": "CUSTOMER_LIST", "period": None}}

    if normalized in ["reminders", "due", "due reminders", "debt reminders",
                       "fee defaulters", "defaulters", "outstanding fees"]:
        db.delete(pending)
        db.commit()
        save_context(db, phone, last_menu="DUE_MENU", last_topic="due")
        return {"parsed": {"type": "DUE_MENU"}}

    if normalized == "dashboard":
        return _go_dashboard(db, phone, pending, send_message)

    if normalized == "wallet":
        return _wallet_msg(db, phone, pending, send_message)

    if normalized in ["help", "formats", "format"]:
        db.delete(pending)
        db.commit()
        return {"parsed": {"type": "FORMATS"}}

    if normalized in ["more", "more options"]:
        return _go_more(db, phone, user, pending, send_message)

    if normalized in ["teachers", "teacher", "staff"]:
        if subscription.get("plan") == PLAN_PRO:
            db.delete(pending)
            db.commit()
            return {"parsed": {"type": "STAFF_MENU"}}
        label = "teacher" if group == "school" else "staff"
        send_message(phone, f"Adding {label}s requires PRO plan.\n\nSend UPGRADE to see plans.")
        return {"status": "owner_home_staff_no_plan"}

    # ── Numbered options — group-specific routing ─────────────────────────────

    if normalized.isdigit():
        opt = int(normalized)

        # ── Food group (9-option menu) ─────────────────────────────────────────
        if group == "food":
            if opt == 1:
                _record_help(db, phone, user, pending, send_message)
                return {"status": "owner_home_record_help"}
            if opt == 2:  # Select product
                db.delete(pending)
                db.commit()
                return {"parsed": {"type": "SELECT_PRODUCT"}}
            if opt == 3:  # Menu / price list
                from guided_service_commands import start_guided_service_setup
                return start_guided_service_setup(db, phone, user, send_message)
            if opt == 4:  # My customers
                db.delete(pending)
                db.commit()
                save_context(db, phone, last_topic="customers")
                return {"parsed": {"type": "CUSTOMER_LIST", "period": None}}
            if opt == 5:  # Reminders
                db.delete(pending)
                db.commit()
                save_context(db, phone, last_menu="DUE_MENU", last_topic="due")
                return {"parsed": {"type": "DUE_MENU"}}
            if opt == 6:  # Stock / inventory
                from guided_stock_commands import start_guided_stock_flow
                return start_guided_stock_flow(db, phone, user, send_message)
            if opt == 7:  # Dashboard
                return _go_dashboard(db, phone, pending, send_message)
            if opt == 8:
                return _wallet_msg(db, phone, pending, send_message)
            if opt == 9:
                return _go_more(db, phone, user, pending, send_message)

        # ── Service group (9-option menu) ──────────────────────────────────────
        elif group == "service":
            if opt == 1:
                _record_help(db, phone, user, pending, send_message)
                return {"status": "owner_home_record_help"}
            if opt == 2:
                db.delete(pending)
                db.commit()
                from business_templates import template_examples_for_user
                examples = template_examples_for_user(user) if user else [
                    "John brought 10 shirts, 5 trousers", "John paid 3000"
                ]
                send_message(
                    phone,
                    f"Record a service job:\n*{examples[0]}*\n\n"
                    f"Payment: *{examples[1]}*\n\n"
                    "Send *price list* to view or update your service prices."
                )
                return {"status": "owner_home_service_jobs"}
            if opt == 3:
                from guided_service_commands import start_guided_service_setup
                return start_guided_service_setup(db, phone, user, send_message)
            if opt == 4:
                db.delete(pending)
                db.commit()
                save_context(db, phone, last_topic="customers")
                return {"parsed": {"type": "CUSTOMER_LIST", "period": None}}
            if opt == 5:
                db.delete(pending)
                db.commit()
                save_context(db, phone, last_menu="DUE_MENU", last_topic="due")
                return {"parsed": {"type": "DUE_MENU"}}
            if opt == 6:
                return _go_dashboard(db, phone, pending, send_message)
            if opt == 7:
                return _wallet_msg(db, phone, pending, send_message)
            if opt == 8:
                db.delete(pending)
                db.commit()
                return {"parsed": {"type": "FORMATS"}}
            if opt == 9:
                return _go_more(db, phone, user, pending, send_message)

        # ── School group (9-option menu) ───────────────────────────────────────
        elif group == "school":
            if opt == 1:
                _record_help(db, phone, user, pending, send_message)
                return {"status": "owner_home_record_help"}
            if opt == 2:
                db.delete(pending)
                db.commit()
                save_context(db, phone, last_topic="customers")
                return {"parsed": {"type": "CUSTOMER_LIST", "period": None}}
            if opt == 3:
                db.delete(pending)
                db.commit()
                save_context(db, phone, last_menu="DUE_MENU", last_topic="due")
                return {"parsed": {"type": "DUE_MENU"}}
            if opt == 4:  # Fee schedule
                from guided_service_commands import start_guided_service_setup
                return start_guided_service_setup(db, phone, user, send_message)
            if opt == 5:  # Dashboard
                return _go_dashboard(db, phone, pending, send_message)
            if opt == 6:  # Textbooks / stock
                from guided_stock_commands import start_guided_stock_flow
                return start_guided_stock_flow(db, phone, user, send_message)
            if opt == 7:
                return _wallet_msg(db, phone, pending, send_message)
            if opt == 8:
                db.delete(pending)
                db.commit()
                return {"parsed": {"type": "FORMATS"}}
            if opt == 9:
                return _go_more(db, phone, user, pending, send_message)

        # ── Thrift group (8-option menu) ───────────────────────────────────────
        elif group == "thrift":
            if opt == 1:
                _record_help(db, phone, user, pending, send_message)
                return {"status": "owner_home_record_help"}
            if opt == 2:  # Select group / rate
                from guided_service_commands import start_guided_service_setup
                return start_guided_service_setup(db, phone, user, send_message)
            if opt == 3:  # Participants
                db.delete(pending)
                db.commit()
                save_context(db, phone, last_topic="customers")
                return {"parsed": {"type": "CUSTOMER_LIST", "period": None}}
            if opt == 4:  # Reminders
                db.delete(pending)
                db.commit()
                save_context(db, phone, last_menu="DUE_MENU", last_topic="due")
                return {"parsed": {"type": "DUE_MENU"}}
            if opt == 5:  # Reports
                db.delete(pending)
                db.commit()
                return {"parsed": {"type": "REPORT_MENU"}}
            if opt == 6:  # Dashboard
                return _go_dashboard(db, phone, pending, send_message)
            if opt == 7:  # Help
                db.delete(pending)
                db.commit()
                return {"parsed": {"type": "FORMATS"}}
            if opt == 8:
                return _wallet_msg(db, phone, pending, send_message)
            if opt == 9:
                return _go_more(db, phone, user, pending, send_message)

        # ── Clinic group (9-option menu) ──────────────────────────────────────
        elif group == "clinic":
            if opt == 1:
                _record_help(db, phone, user, pending, send_message)
                return {"status": "owner_home_record_help"}
            if opt == 2:  # Select service
                from guided_service_commands import start_guided_service_setup
                return start_guided_service_setup(db, phone, user, send_message)
            if opt == 3:  # Price list
                from guided_service_commands import start_guided_service_setup
                return start_guided_service_setup(db, phone, user, send_message)
            if opt == 4:  # My patients
                db.delete(pending)
                db.commit()
                save_context(db, phone, last_topic="customers")
                return {"parsed": {"type": "CUSTOMER_LIST", "period": None}}
            if opt == 5:  # Reminders
                db.delete(pending)
                db.commit()
                save_context(db, phone, last_menu="DUE_MENU", last_topic="due")
                return {"parsed": {"type": "DUE_MENU"}}
            if opt == 6:  # Dashboard
                return _go_dashboard(db, phone, pending, send_message)
            if opt == 7:  # Stock / consumables
                from guided_stock_commands import start_guided_stock_flow
                return start_guided_stock_flow(db, phone, user, send_message)
            if opt == 8:  # Wallet
                return _wallet_msg(db, phone, pending, send_message)
            if opt == 9:  # More
                return _go_more(db, phone, user, pending, send_message)

        # ── Fee group (8-option menu) ──────────────────────────────────────────
        elif group == "fee":
            if opt == 1:
                _record_help(db, phone, user, pending, send_message)
                return {"status": "owner_home_record_help"}
            if opt == 2:
                db.delete(pending)
                db.commit()
                save_context(db, phone, last_topic="customers")
                return {"parsed": {"type": "CUSTOMER_LIST", "period": None}}
            if opt == 3:
                db.delete(pending)
                db.commit()
                save_context(db, phone, last_menu="DUE_MENU", last_topic="due")
                return {"parsed": {"type": "DUE_MENU"}}
            if opt == 4:
                return _go_dashboard(db, phone, pending, send_message)
            if opt == 5:
                return _go_dashboard(db, phone, pending, send_message)
            if opt == 6:
                db.delete(pending)
                db.commit()
                return {"parsed": {"type": "FORMATS"}}
            if opt == 7:
                return _wallet_msg(db, phone, pending, send_message)
            if opt == 8:
                return _go_more(db, phone, user, pending, send_message)

        # ── Stock group / default (9-option menu) ──────────────────────────────
        else:
            if opt == 1:
                _record_help(db, phone, user, pending, send_message)
                return {"status": "owner_home_record_help"}
            if opt == 2:
                db.delete(pending)
                db.commit()
                return {"parsed": {"type": "SELECT_PRODUCT"}}
            if opt == 3:
                from business_templates import has_service_price_catalog
                if has_service_price_catalog(user):
                    from guided_service_commands import start_guided_service_setup
                    return start_guided_service_setup(db, phone, user, send_message)
                from guided_stock_commands import start_guided_stock_flow
                return start_guided_stock_flow(db, phone, user, send_message)
            if opt == 4:
                db.delete(pending)
                db.commit()
                save_context(db, phone, last_topic="customers")
                return {"parsed": {"type": "CUSTOMER_LIST", "period": None}}
            if opt == 5:
                db.delete(pending)
                db.commit()
                save_context(db, phone, last_menu="DUE_MENU", last_topic="due")
                return {"parsed": {"type": "DUE_MENU"}}
            if opt == 6:
                return _go_dashboard(db, phone, pending, send_message)
            if opt == 7:
                return _wallet_msg(db, phone, pending, send_message)
            if opt == 8:
                db.delete(pending)
                db.commit()
                return {"parsed": {"type": "FORMATS"}}
            if opt == 9:
                return _go_more(db, phone, user, pending, send_message)

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
    group = _group(user)

    if group == "school":
        # School more menu: 1=Textbooks, 2=plan, 3=Teachers, 4=back
        if normalized in ["1", "textbooks", "textbook", "textbook stock", "stock", "inventory"]:
            db.delete(pending)
            db.commit()
            from guided_stock_commands import start_guided_stock_flow
            return start_guided_stock_flow(db, phone, user, send_message)

        if normalized in ["2", "my plan", "plan", "upgrade"]:
            pending.action = "UPGRADE_MENU"
            db.commit()
            save_context(db, phone, last_topic="upgrade")
            send_message(phone, build_upgrade_message(user))
            return {"status": "more_upgrade"}

        if normalized in ["3", "teachers", "teacher", "staff"]:
            if subscription.get("plan") == PLAN_PRO:
                db.delete(pending)
                db.commit()
                return {"parsed": {"type": "STAFF_MENU"}}
            send_message(phone, "Adding teachers requires PRO plan.\n\nSend UPGRADE to see plans.")
            return {"status": "more_teachers_no_plan"}

        if normalized in ["4", "back", "main menu", "home", "menu"]:
            pending.action = "OWNER_HOME_MENU"
            db.commit()
            send_message(phone, build_owner_home_menu(user, subscription))
            return {"status": "more_back"}

    elif group == "service":
        from business_templates import template_key_for_user as _tku
        _is_salon = _tku(user) == "salon_beauty" if user else False
        if normalized in ["1", "products", "stock", "inventory", "products / stock"] and _is_salon:
            db.delete(pending)
            db.commit()
            from guided_stock_commands import start_guided_stock_flow
            return start_guided_stock_flow(db, phone, user, send_message)
        if normalized in ["1", "suppliers", "supplier"] and not _is_salon:
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

    else:
        # Standard more menu: 1=Suppliers, 2=plan, 3=Staff, 4=back
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
        from biz_language import get_lang
        _L = get_lang(user)
        send_message(phone, f"Record a transaction:\n{_L['example_credit']}\n{_L['example_pay']}")
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
