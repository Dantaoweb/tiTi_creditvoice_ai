import json
from dataclasses import dataclass

from admin_commands import (
    handle_subscription_admin_pending_selection,
    notify_subscription_admins,
)
from artisan_commands import handle_artisan_payment_pending
from constants import (
    ACTION_ARTISAN_PAYMENT_CHOICE,
    ACTION_DASHBOARD_MENU,
    ACTION_ONBOARD_CUSTOMER,
    ACTION_RESIGN_CONFIRM,
    ACTION_STOCK_ADD_CONFIRM,
    FAST_CAPTURE_REVIEW_ACTIONS,
    SELECT_PRODUCT_ACTIONS,
)
from fast_capture_commands import handle_fast_capture_review_pending
from inventory_suppliers import manual_stock_add, upsert_stock_with_prices
from select_product_commands import handle_select_product_pending
from home_menu_commands import handle_home_menu_pending
from messages import edit_prompt_for_pending
from models import Customer, PendingAction, Transaction
from onboarding_commands import (
    add_stock_option_to_menu,
    handle_onboarding_pending,
    handle_post_onboarding_pending,
    start_onboarding,
)
from reminder_commands import handle_reminder_pending
from reports import build_dashboard_menu_message, build_dashboard_selection_message
from staff_commands import handle_resign_pending
from subscription_flow import handle_subscription_pending_flow
from transaction_save import save_confirmed_pending_transaction
from transaction_setup import update_parse_log_outcome
from webhook_admin_handlers import handle_app_admin_dashboard_pending
from webhook_context import can_view_all_business_transactions
from whatsapp_client import send_whatsapp_message


@dataclass
class PendingRouteResult:
    response: dict | None = None
    parsed: dict | None = None
    is_command: bool = False


def _wrap(result):
    """Convert a plain dict early-return into a PendingRouteResult."""
    if isinstance(result, dict):
        return PendingRouteResult(response=result)
    return result


def build_add_stock_help_message():
    return (
        "Stock\n\n"
        "View stock:\n"
        "stock\n\n"
        "Add stock (with supplier):\n"
        "Ayo supply me 10 bags rice at 5000\n"
        "I buy 10 packs paracetamol from Ayo at 1800 each\n\n"
        "Add stock (cash / no supplier):\n"
        "I buy 10 bags rice at 5000 each\n\n"
        "Manual adjustment (owner / full-access staff only for remove & set):\n"
        "add stock 10 bags rice\n"
        "remove stock 5 bags rice (spoilage)\n"
        "remove stock 2 carton malt (expired)\n"
        "set stock rice 50 bags\n\n"
        "Set low-stock alert:\n"
        "stock alert rice 10"
    )


def _handle_dashboard_menu(
    db, phone, text, pending, business_owner_phone, visible_recorded_by_id
):
    normalized = text.strip().lower()

    if normalized in ["10", "add stock", "stock", "inventory"]:
        db.delete(pending)
        db.commit()
        send_whatsapp_message(phone, build_add_stock_help_message())
        return PendingRouteResult(response={"status": "dashboard_add_stock"})

    dashboard_aliases = {
        "today": "1", "this week": "2", "week": "2",
        "this month": "3", "month": "3", "this year": "4", "year": "4",
        "all": "5", "all time": "5",
        "customers": "6", "customer count": "6",
        "customer list": "7", "list customers": "7",
        "debtors": "8", "unpaid": "8", "unpaid debtors": "8",
        "products": "9", "product leaderboard": "9",
    }
    selection = dashboard_aliases.get(normalized, normalized)
    status, msg = build_dashboard_selection_message(
        db, business_owner_phone, selection, visible_recorded_by_id
    )

    if not msg:
        send_whatsapp_message(phone, add_stock_option_to_menu(build_dashboard_menu_message()))
        return PendingRouteResult(response={"status": "invalid_dashboard_menu_option"})

    db.delete(pending)
    db.commit()
    send_whatsapp_message(phone, msg)
    return PendingRouteResult(response={"status": status})


def _handle_transaction_confirm(
    db, phone, text, pending, user, business_owner_phone,
    visible_recorded_by_id, message_id, subscription,
):
    normalized = text.lower().strip()

    if normalized in ["yes", "1", "save"]:
        update_parse_log_outcome(db, phone, was_confirmed=True)
        pending_items = json.loads(pending.items_json or "[]")
        save_result = save_confirmed_pending_transaction(
            db, phone, pending, user, business_owner_phone,
            visible_recorded_by_id, message_id, pending_items,
            subscription, send_whatsapp_message,
        )
        if save_result:
            return PendingRouteResult(response=save_result)

    elif normalized == "3" and pending.source_text:
        db.delete(pending)
        db.commit()
        send_whatsapp_message(phone, "Send the voice note again.")
        return PendingRouteResult(response={"status": "voice_retry_requested"})

    elif normalized in ["edit", "2", "change"]:
        update_parse_log_outcome(db, phone, was_confirmed=False)
        is_voice_edit = bool(pending.source_text)
        edit_msg = edit_prompt_for_pending(pending, user)
        db.delete(pending)
        db.commit()
        send_whatsapp_message(phone, edit_msg)
        return PendingRouteResult(
            response={"status": "voice_text_edit" if is_voice_edit else "edit"}
        )

    return None


def handle_pending_actions(
    db,
    phone,
    text,
    pending,
    user,
    subscription,
    business_name,
    business_owner_phone,
    visible_recorded_by_id,
    message_id,
    parsed,
    is_command,
):
    # ── Subscription admin selection ─────────────────────────────────────────
    if pending and not is_command:
        result = _wrap(handle_subscription_admin_pending_selection(
            db, phone, text, pending, user, send_whatsapp_message,
        ))
        if result and result.response:
            return result

    # ── Subscription payment flow ────────────────────────────────────────────
    if pending and not is_command:
        result = _wrap(handle_subscription_pending_flow(
            db, phone, text, pending, user, subscription,
            business_name, parsed, send_whatsapp_message, notify_subscription_admins,
        ))
        if result and result.response:
            return result

    # ── Post-onboarding menu ─────────────────────────────────────────────────
    if pending and not is_command:
        result = _wrap(handle_post_onboarding_pending(
            db, phone, text, pending, user, business_name, send_whatsapp_message,
        ))
        if result and result.response:
            return result

    # ── Artisan payment choice ───────────────────────────────────────────────
    if pending and pending.action == ACTION_ARTISAN_PAYMENT_CHOICE and not is_command:
        return _wrap(handle_artisan_payment_pending(
            db, phone, text, pending,
            business_owner_phone, visible_recorded_by_id, send_whatsapp_message,
        ))

    # ── Home menu navigation ─────────────────────────────────────────────────
    if pending and not is_command:
        home_result = handle_home_menu_pending(
            db, phone, text, pending, user, subscription,
            business_name, can_view_all_business_transactions(user), send_whatsapp_message,
        )
        if home_result:
            if home_result.get("parsed"):
                parsed = home_result["parsed"]
                is_command = True
            else:
                return PendingRouteResult(response=home_result)

    # ── User onboarding confirmation ─────────────────────────────────────────
    if pending and not is_command:
        result = _wrap(handle_onboarding_pending(
            db, phone, text, pending, user, send_whatsapp_message,
        ))
        if result and result.response:
            return result

    # ── Start onboarding for unknown users ───────────────────────────────────
    if not user and not parsed:
        return _wrap(start_onboarding(db, phone, pending, send_whatsapp_message))

    # ── Staff delegate greeting ──────────────────────────────────────────────
    if user and user.role == "delegate" and text.lower().strip() in ["hello", "hi", "titi"]:
        send_whatsapp_message(
            phone,
            f"Hello {user.name.title()}!\n\n"
            f"You are logged in as a staff member for {business_name.title()}.\n\n"
            "You can record transactions or check balances for the business here."
        )
        return PendingRouteResult(response={"status": "delegate_greeted"})

    # ── Staff resignation confirmation ───────────────────────────────────────
    if pending and pending.action == ACTION_RESIGN_CONFIRM and not is_command:
        return _wrap(handle_resign_pending(
            db, phone, text, pending, user,
            business_owner_phone, business_name, send_whatsapp_message,
        ))

    # ── Customer onboarding confirmation ─────────────────────────────────────
    if pending and pending.action == ACTION_ONBOARD_CUSTOMER and not is_command:
        result = _wrap(_handle_onboard_customer(
            db, phone, text, pending, user,
            business_owner_phone, message_id, send_whatsapp_message,
        ))
        if result and result.response:
            return result

    # ── Fast Capture end-of-day review ──────────────────────────────────────
    if pending and pending.action in FAST_CAPTURE_REVIEW_ACTIONS and not is_command:
        result = handle_fast_capture_review_pending(
            db, phone, text, pending, business_owner_phone, send_whatsapp_message,
        )
        if result:
            return _wrap(result)

    # ── Select product cart flow ─────────────────────────────────────────────
    if pending and pending.action in SELECT_PRODUCT_ACTIONS and not is_command:
        result = handle_select_product_pending(
            db, phone, text, pending, user,
            business_owner_phone, visible_recorded_by_id,
            subscription, message_id, business_name, send_whatsapp_message,
        )
        if result:
            return _wrap(result)

    # ── Add stock with prices confirmation ───────────────────────────────────
    if pending and pending.action == ACTION_STOCK_ADD_CONFIRM and not is_command:
        result = _wrap(_handle_stock_add_confirm(
            db, phone, text, pending, user, business_owner_phone, send_whatsapp_message,
        ))
        if result and result.response:
            return result

    # ── App admin dashboard ──────────────────────────────────────────────────
    if pending and not is_command:
        result = _wrap(handle_app_admin_dashboard_pending(
            db, phone, text, pending,
        ))
        if result and result.response:
            return result

    # ── Dashboard menu selection ─────────────────────────────────────────────
    if pending and pending.action == ACTION_DASHBOARD_MENU and not is_command:
        return _handle_dashboard_menu(
            db, phone, text, pending, business_owner_phone, visible_recorded_by_id,
        )

    # ── Reminder flows ───────────────────────────────────────────────────────
    if pending and not is_command:
        result = _wrap(handle_reminder_pending(
            db, phone, text, pending,
            business_owner_phone, visible_recorded_by_id, send_whatsapp_message,
        ))
        if result and result.response:
            return result

    # ── Transaction YES / EDIT / voice-retry confirmation ───────────────────
    if pending and not is_command:
        result = _handle_transaction_confirm(
            db, phone, text, pending, user, business_owner_phone,
            visible_recorded_by_id, message_id, subscription,
        )
        if result:
            return result

    return PendingRouteResult(parsed=parsed, is_command=is_command)


def _handle_stock_add_confirm(db, phone, text, pending, user, business_owner_phone, send_message):
    """Save or cancel the STOCK_ADD_WITH_PRICES confirmation."""
    normalized = text.strip().lower()

    if normalized in ["edit", "no", "cancel", "back"]:
        db.delete(pending)
        db.commit()
        send_message(
            phone,
            "Cancelled. Send your stock again:\n"
            "add stock rice cost 3000 sell 4000"
        )
        return {"status": "stock_add_confirm_cancelled"}

    if normalized != "yes":
        send_message(phone, "Reply YES to save or EDIT to change.")
        return {"status": "stock_add_confirm_waiting"}

    items = json.loads(pending.items_json or "[]")
    saved = []

    try:
        for item_data in items:
            item = upsert_stock_with_prices(
                db,
                business_owner_phone,
                item_data["product"],
                item_data.get("unit"),
                item_data["cost"],
                item_data["sell"],
            )
            qty = item_data.get("quantity")
            if qty:
                manual_stock_add(db, business_owner_phone, item_data["product"], qty, item_data.get("unit"), user.id)
            unit_label = f" {item.unit}" if item.unit else ""
            qty_label = f" | {qty:,}{unit_label} in stock" if qty else ""
            saved.append(f"{item.name.title()}{unit_label} — sell N{item.selling_price:,}{qty_label}")
        db.delete(pending)
        db.commit()
    except Exception:
        db.rollback()
        send_message(phone, "Something went wrong saving your stock. Please try again.")
        return {"status": "stock_add_confirm_error"}

    send_message(
        phone,
        "Stock saved:\n" + "\n".join(saved) + "\n\nSend 'select product' to start selling."
    )
    return {"status": "stock_add_confirm_saved"}


def _handle_onboard_customer(
    db, phone, text, pending, user, business_owner_phone, message_id, send_message,
):
    """Confirm or cancel adding a new customer from a detected phone+name pair."""
    normalized = text.lower().strip()

    if normalized in ["yes", "1", "save"]:
        customer = db.query(Customer).filter(
            Customer.name == pending.customer_name,
            Customer.owner_phone == business_owner_phone,
        ).first()

        if not customer:
            customer = Customer(
                name=pending.customer_name,
                owner_phone=business_owner_phone,
                customer_phone=pending.customer_phone,
            )
            db.add(customer)
        else:
            if pending.customer_phone:
                customer.customer_phone = pending.customer_phone

        db.delete(pending)
        db.commit()

        phone_status = customer.customer_phone or "no phone added"
        send_message(
            phone,
            f"Customer saved: {customer.name.title()} -> {phone_status}.\n"
            "You can now record transactions for this customer."
        )
        return {"status": "customer_onboarded"}

    if normalized in ["edit", "2", "change"]:
        db.delete(pending)
        db.commit()
        send_message(phone, "Okay, send the customer again:\nJohn 08012345678")
        return {"status": "customer_onboarded_edit"}

    send_message(
        phone,
        "Customer ready to save. Reply YES or 1 to confirm, EDIT or 2 to send again."
    )
    return {"status": "customer_onboarded_confirm"}
