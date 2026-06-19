from admin_commands import handle_admin_subscription_command, notify_subscription_admins
from partner_commands import (
    handle_set_staff_profile, handle_view_staff_profile,
    handle_invite_partner, handle_accept_partner, handle_remove_partner,
    handle_view_partners, handle_partner_status,
    handle_partner_business_overview,
    handle_add_note, handle_view_notes,
)
from business_templates import build_business_category_menu
from analytics_commands import handle_analytics_command
from void_commands import handle_void_transaction
from customer_commands import handle_customer_command
from guided_service_commands import start_guided_service_setup
from inventory_suppliers import (
    save_product_alias, set_product_category, set_reorder_quantity,
    update_cost_price, delete_stock_item,
)
from messages import (
    build_plan_message,
    build_supported_formats_message,
    build_upgrade_message,
    build_what_can_do_message,
    build_bulk_add_result_message,
    build_app_guide_message,
)
from models import InventoryItem, PendingAction, ProductAlias
from onboarding_commands import handle_profile_command
from service_job_commands import start_service_job_confirm
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

    if parsed["type"] == "SET_COST_PRICE":
        product = parsed["product"]
        price = parsed["price"]
        items = update_cost_price(db, business_owner_phone, product, price)
        if not items:
            send_whatsapp_message(
                phone,
                f"No stock item found for *{product.title()}*.\n"
                "Add it first with:\nadd stock rice cost 3000 sell 4000"
            )
            return {"status": "set_cost_price_not_found"}
        db.commit()
        names = ", ".join(sorted({i.name.title() for i in items}))
        send_whatsapp_message(
            phone,
            f"Cost price updated for *{names}*: N{price:,}\n\n"
            "Send *stock* to see your updated inventory."
        )
        return {"status": "set_cost_price_saved"}

    if parsed["type"] == "DELETE_STOCK_ITEM":
        product = parsed["product"]
        count = delete_stock_item(db, business_owner_phone, product)
        if not count:
            send_whatsapp_message(
                phone,
                f"No stock item found matching *{product.title()}*."
            )
            return {"status": "delete_stock_item_not_found"}
        db.commit()
        send_whatsapp_message(
            phone,
            f"Deleted {count} stock item(s) matching *{product.title()}*.\n\n"
            "Send *stock* to see your updated inventory."
        )
        return {"status": "delete_stock_item_done"}

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

    if parsed["type"] == "UPDATE_BUSINESS_TYPE":
        if not user:
            send_whatsapp_message(phone, "Register first to set your business type.")
            return {"status": "update_biz_type_no_user"}
        db.query(PendingAction).filter(PendingAction.phone == phone).delete()
        db.add(PendingAction(
            phone=phone,
            action="ONBOARD_USER_CATEGORY",
            customer_name=user.name or "",
            last_customer="",
        ))
        db.commit()
        send_whatsapp_message(phone, build_business_category_menu())
        return {"status": "update_business_type"}

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

    # ── Staff profile ─────────────────────────────────────────────────────────
    if parsed["type"] == "SET_STAFF_PROFILE":
        return handle_set_staff_profile(db, phone, parsed, user, business_owner_phone, send_whatsapp_message)

    if parsed["type"] == "VIEW_STAFF_PROFILE":
        return handle_view_staff_profile(db, phone, parsed, user, business_owner_phone, send_whatsapp_message)

    # ── Partner management ────────────────────────────────────────────────────
    if parsed["type"] == "INVITE_PARTNER":
        return handle_invite_partner(db, phone, parsed, user, business_owner_phone, send_whatsapp_message)

    if parsed["type"] == "ACCEPT_PARTNER":
        return handle_accept_partner(db, phone, parsed, send_whatsapp_message)

    if parsed["type"] == "REMOVE_PARTNER":
        return handle_remove_partner(db, phone, parsed, user, business_owner_phone, send_whatsapp_message)

    if parsed["type"] == "VIEW_PARTNERS":
        return handle_view_partners(db, phone, user, business_owner_phone, send_whatsapp_message)

    if parsed["type"] == "PARTNER_STATUS":
        return handle_partner_status(db, phone, send_whatsapp_message)

    if parsed["type"] == "PARTNER_BUSINESS_OVERVIEW":
        return handle_partner_business_overview(db, phone, parsed, send_whatsapp_message)

    # ── Shared notes ──────────────────────────────────────────────────────────
    if parsed["type"] == "ADD_NOTE":
        return handle_add_note(db, phone, parsed, user, business_owner_phone, send_whatsapp_message)

    if parsed["type"] == "VIEW_NOTES":
        return handle_view_notes(db, phone, parsed, user, business_owner_phone, send_whatsapp_message)

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
        send_whatsapp_message(phone, build_plan_message(subscription, user))
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

    # ── Service price list commands ──────────────────────────────────────────
    if parsed["type"] == "PRICE_LIST":
        if not user:
            send_whatsapp_message(phone, "Register your business first.")
            return {"status": "price_list_no_user"}
        return start_guided_service_setup(db, phone, user, send_whatsapp_message)

    if parsed["type"] == "SET_RETAIL_BREAKDOWN":
        if not user:
            send_whatsapp_message(phone, "Register your business first.")
            return {"status": "breakdown_no_user"}
        from inventory_suppliers import set_retail_breakdown
        product = parsed["product"]
        ret_unit = parsed["retail_unit"]
        ret_per = parsed["retail_per_base"]
        ret_price = parsed.get("retail_price")
        item, err = set_retail_breakdown(
            db, business_owner_phone, product, None, ret_unit, ret_per, ret_price,
        )
        db.commit()
        if err or not item:
            send_whatsapp_message(
                phone,
                f"Could not find *{product.title()}* in your stock.\n"
                "Add it to stock first, then set the breakdown.\n\n"
                f"Example: *breakdown eggs: egg 30 70*\n(30 eggs per crate, ₦70 each)"
            )
            return {"status": "breakdown_not_found"}
        base = item.unit or "unit"
        price_note = f" at ₦{ret_price:,} each" if ret_price else ""
        send_whatsapp_message(
            phone,
            f"Retail breakdown set ✓\n\n"
            f"*{item.name.title()}* ({base})\n"
            f"→ {ret_per} {ret_unit}s per {base}{price_note}\n\n"
            f"Now when you sell, you can say:\n"
            f"*Emeka bought 3 {ret_unit} {product}*\n"
            f"and stock will be deducted correctly."
        )
        return {"status": "breakdown_saved"}

    if parsed["type"] == "SET_SERVICE_PRICE":
        if not user:
            send_whatsapp_message(phone, "Register your business first.")
            return {"status": "set_service_price_no_user"}
        item_name = parsed["item"].strip().lower()
        price = parsed["price"]
        from sqlalchemy import func as _func
        existing = db.query(InventoryItem).filter(
            InventoryItem.owner_phone == business_owner_phone,
            _func.lower(InventoryItem.name) == item_name,
            InventoryItem.quantity == None,
        ).first()
        if existing:
            existing.selling_price = price
            db.commit()
            label = f"{existing.name.title()}{' (' + existing.unit + ')' if existing.unit else ''}"
            send_whatsapp_message(phone, f"Price updated: *{label}* — N{price:,}")
        else:
            db.add(InventoryItem(
                owner_phone=business_owner_phone,
                name=item_name,
                unit=None,
                quantity=None,
                selling_price=price,
                cost_price=None,
                is_available=True,
                category="service",
            ))
            db.commit()
            send_whatsapp_message(phone, f"Price set: *{item_name.title()}* — N{price:,}\n\nSend *price list* to see all prices.")
        return {"status": "set_service_price_saved"}

    # ── Natural language stock price update: "price garri 2500 3500" ────────────
    if parsed["type"] == "UPDATE_STOCK_PRICE":
        if not user:
            send_whatsapp_message(phone, "Register your business first.")
            return {"status": "update_stock_price_no_user"}
        product_query = parsed["product"].strip().lower()
        cost = parsed["cost"]
        sell = parsed["sell"]
        from sqlalchemy import func as _func2
        from models import InventoryItem as _InvItem2
        item = db.query(_InvItem2).filter(
            _InvItem2.owner_phone == business_owner_phone,
            _func2.lower(_InvItem2.name) == product_query,
            _InvItem2.quantity != None,
        ).first()
        if not item:
            # fuzzy: product name contained in stored name or vice versa
            candidates = db.query(_InvItem2).filter(
                _InvItem2.owner_phone == business_owner_phone,
                _InvItem2.quantity != None,
            ).all()
            for c in candidates:
                if product_query in c.name.lower() or c.name.lower() in product_query:
                    item = c
                    break
        if item:
            item.cost_price = cost
            item.selling_price = sell
            db.commit()
            send_whatsapp_message(
                phone,
                f"Price updated: *{item.name.title()}*\n"
                f"Cost: N{cost:,}  |  Sell: N{sell:,}\n\n"
                "Send *stock* to see your inventory."
            )
        else:
            send_whatsapp_message(
                phone,
                f"Stock item '{product_query.title()}' not found.\n"
                "Send *stock* to see your inventory."
            )
        return {"status": "update_stock_price_done"}

    # ── Service job (customer brought/dropped items) ─────────────────────────
    if parsed["type"] == "SERVICE_JOB":
        if not user:
            send_whatsapp_message(phone, "Register your business first.")
            return {"status": "service_job_no_user"}
        return start_service_job_confirm(
            db, phone, business_owner_phone, user, parsed, send_whatsapp_message
        )

    # ── What can you do / help / how to use ─────────────────────────────────
    if parsed["type"] == "WHAT_CAN_DO":
        send_whatsapp_message(phone, build_what_can_do_message(user))
        return {"status": "what_can_do"}

    # ── App navigation guide ─────────────────────────────────────────────────
    if parsed["type"] == "APP_GUIDE":
        topic = parsed.get("topic", "")
        send_whatsapp_message(phone, build_app_guide_message(topic))
        return {"status": "app_guide"}

    # ── Bulk product name add ────────────────────────────────────────────────
    if parsed["type"] == "BULK_ADD_PRODUCTS":
        if not user:
            send_whatsapp_message(phone, "Register your business first before adding products.")
            return {"status": "bulk_add_no_user"}
        names = parsed.get("names", [])
        saved, already_exist = [], []
        for raw_name in names:
            name_clean = raw_name.strip().lower()
            if not name_clean:
                continue
            existing = db.query(InventoryItem).filter(
                InventoryItem.owner_phone == business_owner_phone,
                InventoryItem.name == name_clean,
            ).first()
            if existing:
                already_exist.append(name_clean)
            else:
                item = InventoryItem(
                    owner_phone=business_owner_phone,
                    name=name_clean,
                    unit=None,
                    quantity=None,
                    cost_price=None,
                    selling_price=None,
                    is_service=False,
                    is_available=True,
                )
                db.add(item)
                saved.append(name_clean)
        if saved:
            db.commit()
        if not saved and already_exist:
            send_whatsapp_message(
                phone,
                f"All {len(already_exist)} product(s) already exist in your inventory.\n"
                "Send *stock* to see your inventory."
            )
        else:
            send_whatsapp_message(phone, build_bulk_add_result_message(saved, already_exist or None))
        return {"status": "bulk_add_done"}

    return None

