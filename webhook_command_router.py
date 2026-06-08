from admin_commands import handle_admin_subscription_command, notify_subscription_admins
from analytics_commands import handle_analytics_command
from void_commands import handle_void_transaction
from customer_commands import handle_customer_command
from inventory_suppliers import save_product_alias, set_product_category, set_reorder_quantity
from messages import (
    build_plan_message,
    build_supported_formats_message,
    build_upgrade_message,
)
from models import PendingAction, ProductAlias
from onboarding_commands import handle_profile_command
from linked_phone_commands import (
    handle_link_phone, handle_unlink_phone, handle_my_phones,
)
from recovery_commands import handle_set_pin, handle_change_pin, handle_remove_pin
from reminder_commands import handle_reminder_command
from report_commands import handle_report_command
from select_product_commands import start_select_product
from staff_commands import handle_staff_command
from supplier_commands import handle_supplier_command
from transaction_setup import handle_transaction_setup
from whatsapp_client import send_whatsapp_message


def handle_parsed_command(
    db,
    phone,
    text,
    parsed,
    pending,
    user,
    subscription,
    business_name,
    business_owner_phone,
    visible_recorded_by_id,
    voice_transcript_text,
):
    if parsed["type"] == "FORMATS":
        msg = build_supported_formats_message(user)
        send_whatsapp_message(phone, msg)
        return {"status": "formats"}

    if parsed["type"] == "PRODUCT_ALIAS":
        alias = parsed["alias"].lower().strip()
        canonical = parsed["canonical"].lower().strip()
        if not user:
            send_whatsapp_message(phone, "Register first before setting product aliases.")
            return {"status": "product_alias_no_user"}
        save_product_alias(db, business_owner_phone, alias, canonical)
        send_whatsapp_message(
            phone,
            f"Got it. *{alias.title()}* will now be treated as *{canonical.title()}* "
            f"in your inventory.\n\nTo remove it, send: alias {alias} = {alias}"
        )
        return {"status": "product_alias_saved"}

    if parsed["type"] == "SET_PRODUCT_CATEGORY":
        product = parsed["product"]
        category = parsed["category"]
        items = set_product_category(db, business_owner_phone, product, category)
        if not items:
            send_whatsapp_message(
                phone,
                f"No stock item found for *{product.title()}*.\n"
                "Add it first, then set the category."
            )
            return {"status": "set_category_not_found"}
        db.commit()
        send_whatsapp_message(
            phone,
            f"*{product.title()}* tagged as *{category.title()}*.\n\n"
            "Send *stock* to see your updated inventory."
        )
        return {"status": "set_category_saved"}

    if parsed["type"] == "SET_REORDER_QUANTITY":
        product = parsed["product"]
        quantity = parsed["quantity"]
        unit = parsed.get("unit")
        item = set_reorder_quantity(db, business_owner_phone, product, unit, quantity)
        if not item:
            send_whatsapp_message(
                phone,
                f"No stock item found for *{product.title()}*.\n"
                "Add it first, then set your reorder point."
            )
            return {"status": "set_reorder_not_found"}
        db.commit()
        unit_label = f" {item.unit}" if item.unit else ""
        send_whatsapp_message(
            phone,
            f"Reorder point set for *{item.name.title()}*: "
            f"N{quantity:,}{unit_label}.\n\n"
            "tiTi will flag it in your stock list when you reach this level."
        )
        return {"status": "set_reorder_saved"}

    if parsed["type"] == "SELECT_PRODUCT":
        return start_select_product(db, phone, business_owner_phone, send_whatsapp_message)

    if parsed["type"].startswith("CONVO_"):
        analytics_result = handle_analytics_command(
            db, phone, parsed, user, business_owner_phone,
            visible_recorded_by_id, send_whatsapp_message,
        )
        if analytics_result:
            return analytics_result

    if parsed["type"] == "SET_PIN":
        return handle_set_pin(db, user, parsed["pin"], send_whatsapp_message, phone)

    if parsed["type"] == "CHANGE_PIN":
        return handle_change_pin(db, user, parsed["old_pin"], parsed["new_pin"], send_whatsapp_message, phone)

    if parsed["type"] == "REMOVE_PIN":
        return handle_remove_pin(db, user, parsed["pin"], send_whatsapp_message, phone)

    if parsed["type"] == "LINK_PHONE":
        return handle_link_phone(db, user, parsed["phone"], send_whatsapp_message, phone)

    if parsed["type"] == "UNLINK_PHONE":
        return handle_unlink_phone(db, user, parsed["phone"], send_whatsapp_message, phone)

    if parsed["type"] == "MY_PHONES":
        return handle_my_phones(db, user, send_whatsapp_message, phone)

    if parsed["type"] == "VOID_TRANSACTION":
        return handle_void_transaction(
            db, phone, parsed, user, business_owner_phone,
            visible_recorded_by_id, send_whatsapp_message,
        )

    if parsed["type"] == "STAFF_REPORT":
        from reports import get_staff_performance
        from subscriptions import ensure_feature_allowed
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "STAFF", "Staff report")
        if not allowed:
            send_whatsapp_message(phone, upgrade_msg)
            return {"status": "staff_report_plan_blocked"}
        period = parsed.get("period")
        staff_data = get_staff_performance(db, business_owner_phone, period)
        if not staff_data:
            send_whatsapp_message(phone, "No staff found. Add staff with the staff menu.")
            return {"status": "staff_report_empty"}
        period_label = {"TODAY": "Today", "WEEK": "This Week", "MONTH": "This Month"}.get(period, "This Month")
        msg = f"Staff Performance — {period_label}\n\n"
        for i, s in enumerate(staff_data, 1):
            msg += (
                f"{i}. {s['name'].title()}\n"
                f"   Sales: N{s['sales']:,}  |  Payments: N{s['payments']:,}\n"
                f"   Transactions: {s['transactions']}  |  Customers: {s['customers_served']}\n"
            )
            if s["top_products"]:
                msg += "   Sold:\n"
                for p in s["top_products"]:
                    msg += f"   - {p['product']}: {p['qty']} unit(s), N{p['total']:,}\n"
            msg += "\n"
        send_whatsapp_message(phone, msg.strip())
        return {"status": "staff_report"}

    supplier_result = handle_supplier_command(
        db,
        phone,
        parsed,
        user,
        business_owner_phone,
        voice_transcript_text,
        send_whatsapp_message
    )
    if supplier_result:
        return supplier_result
    if parsed["type"] == "ARTISAN_PAYMENT_CHOICE":
        db.query(PendingAction).filter(
            PendingAction.phone == phone
        ).delete()
        db.add(
            PendingAction(
                phone=phone,
                customer_name=parsed["name"].lower(),
                action="ARTISAN_PAYMENT_CHOICE",
                paid_amount=parsed["amount"],
                product=f"{parsed.get('description', 'service/work')} - {parsed['name'].lower()}",
                last_customer=parsed["name"].lower()
            )
        )
        db.commit()
        send_whatsapp_message(
            phone,
            f"{parsed['name'].title()} paid you N{parsed['amount']:,}.\n\n"
            "What is this for?\n"
            "1. For the work/service you did, no customer debt\n"
            "2. He/she paid debt owed to you"
        )
        return {"status": "artisan_payment_choice"}

    if parsed["type"] == "MY_PLAN":
        send_whatsapp_message(phone, build_plan_message(subscription))
        return {"status": "my_plan"}

    if parsed["type"] == "MY_QUOTA":
        from datetime import datetime, timedelta, timezone
        from models import Transaction as _Tx
        from transaction_setup import get_month_start
        from reports import get_owner_transaction_query
        limits = subscription["limits"]
        tx_limit = limits.get("monthly_transactions")
        if tx_limit is None:
            send_whatsapp_message(phone, f"Your {subscription['plan']} plan has no transaction limit.\n\nRecord as many as you need.")
        else:
            used = get_owner_transaction_query(db, business_owner_phone).filter(
                _Tx.created_at >= get_month_start()
            ).count()
            remaining = max(0, tx_limit - used)
            now = datetime.now(timezone.utc)
            next_month = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
            reset_date = next_month.strftime("%d %B %Y")
            warn = "You are close to your limit. Send UPGRADE for unlimited transactions." if remaining <= 10 else "Send UPGRADE to remove this limit."
            send_whatsapp_message(
                phone,
                f"Transactions this month: {used} of {tx_limit}\n"
                f"Remaining: {remaining}\n"
                f"Resets on: {reset_date}\n\n"
                f"{warn}"
            )
        return {"status": "my_quota"}

    if parsed["type"] == "UPGRADE_MENU":
        db.query(PendingAction).filter(
            PendingAction.phone == phone
        ).delete()
        db.add(
            PendingAction(
                phone=phone,
                customer_name="",
                action="UPGRADE_MENU",
                last_customer=""
            )
        )
        db.commit()
        send_whatsapp_message(phone, build_upgrade_message(user))
        return {"status": "upgrade_menu"}

    admin_subscription_result = handle_admin_subscription_command(
        db,
        phone,
        parsed,
        user,
        send_whatsapp_message,
        notify_subscription_admins
    )
    if admin_subscription_result:
        return admin_subscription_result

    staff_result = handle_staff_command(
        db,
        phone,
        parsed,
        user,
        subscription,
        business_name,
        send_whatsapp_message
    )
    if staff_result:
        return staff_result

    profile_result = handle_profile_command(
        db,
        phone,
        parsed,
        pending,
        business_owner_phone,
        send_whatsapp_message
    )
    if profile_result:
        return profile_result
    reminder_result = handle_reminder_command(
        db,
        phone,
        parsed,
        user,
        send_whatsapp_message
    )
    if reminder_result:
        return reminder_result
    report_result = handle_report_command(
        db,
        phone,
        text,
        parsed,
        user,
        business_owner_phone,
        visible_recorded_by_id,
        send_whatsapp_message
    )
    if report_result:
        return report_result
    customer_result = handle_customer_command(
        db,
        phone,
        text,
        parsed,
        user,
        business_owner_phone,
        visible_recorded_by_id,
        send_whatsapp_message
    )
    if customer_result:
        return customer_result
    transaction_setup_result = handle_transaction_setup(
        db,
        phone,
        parsed,
        user,
        business_owner_phone,
        subscription,
        visible_recorded_by_id,
        voice_transcript_text,
        send_whatsapp_message
    )
    if transaction_setup_result:
        return transaction_setup_result

    return None

