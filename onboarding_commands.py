from business_templates import (
    build_business_category_menu,
    build_business_type_menu,
    business_category_by_key,
    make_custom_business_key,
    selected_business_category,
    selected_business_type,
    PARTIAL_SUPPORT_TYPES,
)
from business_templates import has_service_price_catalog
from guided_service_commands import start_guided_service_setup
from guided_stock_commands import start_guided_stock_flow
from messages import (
    build_onboarding_start_message,
    build_post_onboarding_menu,
    build_supported_formats_message,
    build_upgrade_message,
)
from models import Customer, PendingAction, ReminderMemory, User
from reports import build_dashboard_menu_message


ONBOARDING_ACTIONS = [
    "ONBOARD_USER",
    "ONBOARD_USER_CONFIRM",
    "ONBOARD_USER_CATEGORY",
    "ONBOARD_USER_BUSINESS_TYPE",
    "ONBOARD_USER_PARTIAL_CONFIRM",
    "ONBOARD_USER_CUSTOM_TYPE",
]


def add_stock_option_to_menu(message):
    if "add stock" in (message or "").lower():
        return message
    return f"{message}\n4. Add stock"


def add_stock_option_to_dashboard_menu(message):
    if "add stock" in (message or "").lower():
        return message
    return f"{message}\n10. Add stock"


def complete_user_onboarding(
    db,
    user,
    phone,
    pending,
    business_category,
    business_type,
    business_type_label,
):
    name = (pending.customer_name or "").strip()
    if not user:
        user = User(
            phone=phone,
            name=name,
            role="user",
            business_category=business_category,
            business_type=business_type,
            business_type_label=business_type_label,
        )
        db.add(user)
    else:
        user.name = name
        user.business_category = business_category
        user.business_type = business_type
        user.business_type_label = business_type_label

    db.delete(pending)
    db.add(
        PendingAction(
            phone=phone,
            customer_name=name,
            action="POST_ONBOARDING_MENU",
            last_customer="",
        )
    )
    db.commit()
    return user, build_post_onboarding_menu(name, user)


def start_onboarding(db, phone, pending, send_message):
    if pending and pending.action not in ONBOARDING_ACTIONS:
        db.delete(pending)
        db.commit()
        pending = None

    if not pending or pending.action not in ONBOARDING_ACTIONS:
        db.add(PendingAction(phone=phone, action="ONBOARD_USER"))
        db.commit()

    send_message(phone, build_onboarding_start_message())
    return {"status": "onboarding_started"}


def handle_post_onboarding_pending(
    db,
    phone,
    text,
    pending,
    user,
    business_name,
    send_message,
):
    if not pending or pending.action != "POST_ONBOARDING_MENU":
        return None

    normalized = text.lower().strip()
    if normalized in ["1", "formats", "format", "f"]:
        db.delete(pending)
        db.commit()
        send_message(phone, build_supported_formats_message(user))
        return {"status": "post_onboarding_formats"}

    if normalized in ["2", "add customer", "customer"]:
        db.delete(pending)
        db.commit()
        send_message(
            phone,
            "To add a customer, send their name and phone number like:\n"
            "John 08012345678\n\n"
            "You can also save only the name:\n"
            "add customer John"
        )
        return {"status": "post_onboarding_add_customer"}

    if normalized in ["3", "dashboard"]:
        pending.action = "DASHBOARD_MENU"
        db.commit()
        send_message(phone, add_stock_option_to_dashboard_menu(build_dashboard_menu_message()))
        return {"status": "post_onboarding_dashboard"}

    if normalized in ["4", "add products", "add your products", "products", "stock", "add stock",
                       "price list", "set up price list", "services",
                       "view participants", "participants", "reminders"]:
        db.delete(pending)
        db.commit()
        from business_templates import template_key_for_user
        if user and template_key_for_user(user) == "thrift_contribution":
            send_message(
                phone,
                "To record contributions:\n"
                "*[name] contributed [amount]*\n\n"
                "Example: Amina contributed 5000\n\n"
                "Send *due* to see balances and send reminders.\n"
                "Send *customers* to see all participants."
            )
            return {"status": "post_onboarding_thrift_guide"}
        if has_service_price_catalog(user):
            return start_guided_service_setup(db, phone, user, send_message)
        return start_guided_stock_flow(db, phone, user, send_message)

    if normalized in ["5", "upgrade"]:
        pending.action = "UPGRADE_MENU"
        db.commit()
        send_message(phone, build_upgrade_message(user))
        return {"status": "post_onboarding_upgrade"}

    if normalized in ["cancel", "exit", "back", "done", "stop"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Closed. You can continue anytime.")
        return {"status": "post_onboarding_closed"}

    db.delete(pending)
    db.commit()
    return None


def handle_onboarding_pending(db, phone, text, pending, user, send_message):
    if not pending or pending.action not in ONBOARDING_ACTIONS:
        return None

    if pending.action == "ONBOARD_USER":
        full_name = text.strip()
        if full_name == "" or full_name.lower() in ["continue", "start", "yes", "ok", "1"]:
            send_message(phone, "Please reply with the name you want to use.")
            return {"status": "onboarding_name_required"}

        pending.action = "ONBOARD_USER_CONFIRM"
        pending.customer_name = full_name
        db.commit()
        send_message(
            phone,
            f"Confirm name: *{full_name.title()}*?\n\n"
            "Reply YES or 1 to save, EDIT or 2 to change."
        )
        return {"status": "onboarding_confirm_sent"}

    if pending.action == "ONBOARD_USER_CONFIRM":
        normalized = text.lower().strip()
        if normalized in ["yes", "1", "save"]:
            pending.action = "ONBOARD_USER_CATEGORY"
            db.commit()
            send_message(phone, build_business_category_menu())
            return {"status": "onboarding_category_prompt"}

        if normalized in ["edit", "2", "change"]:
            pending.action = "ONBOARD_USER"
            db.commit()
            send_message(phone, "No problem! Please reply with the name you want to use.")
            return {"status": "onboarding_restart"}

        send_message(
            phone,
            f"Confirm name: *{pending.customer_name}*?\n\n"
            "Reply YES or 1 to save, EDIT or 2 to change."
        )
        return {"status": "waiting_onboarding_confirmation"}

    if pending.action == "ONBOARD_USER_CATEGORY":
        if text.lower().strip() in ["back", "menu", "cancel"]:
            pending.action = "ONBOARD_USER_CONFIRM"
            db.commit()
            send_message(
                phone,
                f"Confirm name: *{pending.customer_name}*?\n\n"
                "Reply YES or 1 to continue, EDIT or 2 to change."
            )
            return {"status": "onboarding_category_back"}

        category = selected_business_category(text)
        if not category:
            send_message(phone, build_business_category_menu())
            return {"status": "onboarding_invalid_category"}

        pending.last_customer = category["key"]
        if category["key"] == "other":
            pending.action = "ONBOARD_USER_CUSTOM_TYPE"
            db.commit()
            send_message(phone, "Please type your business type.\nExample: Event Decoration")
            return {"status": "onboarding_custom_type_prompt"}

        pending.action = "ONBOARD_USER_BUSINESS_TYPE"
        db.commit()
        send_message(phone, build_business_type_menu(category))
        return {"status": "onboarding_business_type_prompt"}

    if pending.action == "ONBOARD_USER_BUSINESS_TYPE":
        category = business_category_by_key(pending.last_customer)
        if not category:
            pending.action = "ONBOARD_USER_CATEGORY"
            db.commit()
            send_message(phone, build_business_category_menu())
            return {"status": "onboarding_category_missing"}

        if text.lower().strip() in ["back", "menu", "cancel"]:
            pending.action = "ONBOARD_USER_CATEGORY"
            db.commit()
            send_message(phone, build_business_category_menu())
            return {"status": "onboarding_business_type_back"}

        business_type_key, business_type_label = selected_business_type(category, text)
        if not business_type_key:
            send_message(phone, build_business_type_menu(category))
            return {"status": "onboarding_invalid_business_type"}

        if business_type_key.startswith("other_"):
            pending.action = "ONBOARD_USER_CUSTOM_TYPE"
            db.commit()
            send_message(phone, "Please type your business type.\nExample: Event Decoration")
            return {"status": "onboarding_custom_type_prompt"}

        if business_type_key in PARTIAL_SUPPORT_TYPES:
            info = PARTIAL_SUPPORT_TYPES[business_type_key]
            pending.action = "ONBOARD_USER_PARTIAL_CONFIRM"
            pending.product = business_type_key
            pending.customer_phone = business_type_label
            db.commit()
            send_message(
                phone,
                f"⚠️ Limited fit: {info['label']}\n\n"
                f"CreditVoice will help you:\n✅ {info['works']}\n\n"
                f"What's missing today:\n❌ {info['missing']}\n\n"
                "You can still use CreditVoice to manage who owes you and track payments.\n\n"
                "Reply *YES* to continue or *BACK* to pick a different type."
            )
            return {"status": "onboarding_partial_warning_sent"}

        new_user, msg = complete_user_onboarding(
            db,
            user,
            phone,
            pending,
            category["key"],
            business_type_key,
            business_type_label,
        )
        send_message(phone, msg)
        return {"status": "onboarding_complete"}

    if pending.action == "ONBOARD_USER_PARTIAL_CONFIRM":
        normalized = text.lower().strip()
        if normalized in ["back", "menu", "cancel", "no"]:
            pending.action = "ONBOARD_USER_BUSINESS_TYPE"
            pending.product = None
            pending.customer_phone = None
            db.commit()
            category = business_category_by_key(pending.last_customer)
            send_message(phone, build_business_type_menu(category))
            return {"status": "onboarding_partial_back"}

        if normalized in ["yes", "1", "continue", "ok"]:
            btype_key = pending.product or ""
            btype_label = pending.customer_phone or ""
            cat_key = pending.last_customer or ""
            new_user, msg = complete_user_onboarding(
                db, user, phone, pending, cat_key, btype_key, btype_label,
            )
            send_message(phone, msg)
            return {"status": "onboarding_complete"}

        send_message(phone, "Reply *YES* to continue or *BACK* to pick a different type.")
        return {"status": "onboarding_partial_waiting"}

    if pending.action == "ONBOARD_USER_CUSTOM_TYPE":
        if text.lower().strip() in ["back", "menu", "cancel"]:
            pending.action = "ONBOARD_USER_CATEGORY"
            db.commit()
            send_message(phone, build_business_category_menu())
            return {"status": "onboarding_custom_type_back"}

        custom_label = text.strip()
        if custom_label == "" or custom_label.lower() in ["continue", "start", "yes", "ok", "1"]:
            send_message(phone, "Please type your business type.\nExample: Event Decoration")
            return {"status": "onboarding_custom_type_required"}

        new_user, msg = complete_user_onboarding(
            db,
            user,
            phone,
            pending,
            pending.last_customer or "other",
            make_custom_business_key(custom_label),
            custom_label.title(),
        )
        send_message(phone, msg)
        return {"status": "onboarding_complete"}

    return None


def handle_profile_command(
    db,
    phone,
    parsed,
    pending,
    business_owner_phone,
    send_message,
):
    command_type = parsed.get("type")

    if command_type == "REONBOARD":
        db.query(PendingAction).filter(PendingAction.phone == phone).delete()
        db.add(PendingAction(phone=phone, action="ONBOARD_USER"))
        db.commit()
        send_message(
            phone,
            "No problem! Let's update your profile.\n\n"
            "Please reply with the *Business Name* you want to use. This name will appear on your reports and customer reminders."
        )
        return {"status": "onboarding_restarted"}

    if command_type == "SET_PHONE":
        target_name = parsed["name"].lower().strip()

        # Guard: reject command words masquerading as customer names.
        # "add number 090..." / "save number 090..." → name="add"/"save"
        _bad_names = {"add", "save", "update", "set", "enter", "new", "record", "edit"}
        if target_name in _bad_names:
            send_message(
                phone,
                "Please include the customer name.\nExample:\n"
                "Dr Ashake Olatobi phone 09076397678"
            )
            return {"status": "set_phone_missing_name"}

        target_phone = parsed.get("customer_phone")
        target_phone = target_phone.strip() if target_phone else None

        existing_customer = db.query(Customer).filter(
            Customer.name == target_name,
            Customer.owner_phone == business_owner_phone,
        ).first()

        if existing_customer and target_phone:
            existing_customer.customer_phone = target_phone
            db.query(ReminderMemory).filter(
                ReminderMemory.phone == phone,
                ReminderMemory.customer_name == target_name,
            ).update({ReminderMemory.customer_phone: target_phone})
            db.commit()

            if pending and pending.action in ["REMINDER_SELECTION", "REMINDER_CONFIRM"]:
                send_message(
                    phone,
                    f"Saved phone for {existing_customer.name.title()}: {target_phone}\n\n"
                    "Phone set! Now reply *YES* to send the reminder."
                )
                return {"status": "reminder_phone_updated"}

        db.query(PendingAction).filter(
            PendingAction.phone == phone,
            PendingAction.action == "ONBOARD_CUSTOMER",
        ).delete()
        db.add(
            PendingAction(
                phone=phone,
                customer_name=target_name,
                customer_phone=target_phone,
                action="ONBOARD_CUSTOMER",
            )
        )
        db.commit()

        phone_line = f" with phone {target_phone}" if target_phone else " without a phone number"
        if existing_customer:
            message = f"You already have a customer named {target_name.title()}{phone_line}.\n"
        else:
            message = f"You added a new customer {target_name.title()}{phone_line}.\n"
        send_message(phone, message + "\nReply YES or 1 to save, EDIT or 2 to send it again.")
        return {"status": "confirm_onboard_customer"}

    return None
