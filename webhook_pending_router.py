import json
import re
from dataclasses import dataclass

from admin_commands import (
    handle_subscription_admin_pending_selection,
    notify_subscription_admins,
)
from artisan_commands import handle_artisan_payment_pending
from constants import (
    ACTION_ARTISAN_PAYMENT_CHOICE,
    ACTION_AWAITING_CLARIFICATION,
    ACTION_DASHBOARD_MENU,
    ACTION_ONBOARD_CUSTOMER,
    ACTION_RESIGN_CONFIRM,
    ACTION_SERVICE_JOB_CONFIRM,
    ACTION_STOCK_ADD_CONFIRM,
    ACTION_STOCK_ITEM_ADD_QTY,
    ACTION_STOCK_ITEM_MENU,
    ACTION_STOCK_ITEM_RENAME,
    ACTION_STOCK_ITEM_UPDATE_PRICE,
    ACTION_STOCK_MENU,
    FAST_CAPTURE_REVIEW_ACTIONS,
    GUIDED_SERVICE_SETUP_ACTIONS,
    GUIDED_STOCK_ACTIONS,
    SELECT_PRODUCT_ACTIONS,
    STOCK_MENU_ACTIONS,
)
from context_memory import get_active_menu
from fast_capture_commands import handle_fast_capture_review_pending
from guided_service_commands import handle_guided_service_pending
from guided_stock_commands import handle_guided_stock_pending, start_guided_stock_flow
from service_job_commands import handle_service_job_confirm
from inventory_suppliers import manual_stock_add, upsert_stock_with_prices
from select_product_commands import handle_select_product_pending
from home_menu_commands import handle_home_menu_pending
from messages import build_invalid_message, edit_prompt_for_pending
from parser import interpret_text_with_openai_followup, parse_message
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

    # Keep pending as DASHBOARD_MENU so the user can send another number
    # without being dropped back to the home menu.
    db.commit()
    send_whatsapp_message(phone, msg)
    return PendingRouteResult(response={"status": status})


def _handle_stock_menu(db, phone, text, pending, user, business_owner_phone, send_message):
    """Handle replies after the stock list — number to manage item, ADD to add new."""
    normalized = text.strip().lower()
    action = pending.action
    try:
        payload = json.loads(pending.payload_json or "{}")
    except Exception:
        payload = {}

    # ── Main stock list menu ─────────────────────────────────────────────────
    if action == ACTION_STOCK_MENU:
        item_ids = payload.get("item_ids", [])

        if normalized in ["add", "add stock", "new", "new product"]:
            db.delete(pending)
            db.commit()
            return start_guided_stock_flow(db, phone, user, send_message)

        if normalized.isdigit():
            index = int(normalized) - 1
            if index < 0 or index >= len(item_ids):
                send_message(phone, f"Send a number between 1 and {len(item_ids)}, or ADD to add new stock.")
                return {"status": "stock_menu_out_of_range"}

            from inventory_suppliers import find_inventory_item as _fii
            from models import InventoryItem as _Inv
            item = db.query(_Inv).filter(_Inv.id == item_ids[index]).first()
            if not item:
                send_message(phone, "Item not found. Send *stock* to refresh.")
                db.delete(pending)
                db.commit()
                return {"status": "stock_menu_item_missing"}

            qty = item.quantity or 0
            unit_label = f" {item.unit}" if item.unit else ""
            cost_line = f"Cost: N{item.cost_price:,}" if item.cost_price else "Cost: not set"
            sell_line = f"Sell: N{item.selling_price:,}" if item.selling_price else "Sell: not set"

            pending.action = ACTION_STOCK_ITEM_MENU
            payload["selected_id"] = item.id
            payload["selected_name"] = item.name
            payload["selected_unit"] = item.unit
            pending.payload_json = json.dumps(payload)
            db.commit()

            send_message(
                phone,
                f"*{item.name.title()}{unit_label}*\n"
                f"Qty: {qty:,}{unit_label}\n"
                f"{cost_line}  |  {sell_line}\n\n"
                "1. Add more stock\n"
                "2. Update price\n"
                "3. Delete item\n"
                "4. Rename item\n\n"
                "Reply *BACK* to return to stock list."
            )
            return {"status": "stock_item_menu_shown"}

        # Anything else — exit the stock menu and process normally
        db.delete(pending)
        db.commit()
        return None

    # ── Item detail menu ─────────────────────────────────────────────────────
    if action == ACTION_STOCK_ITEM_MENU:
        item_id = payload.get("selected_id")
        item_name = payload.get("selected_name", "")
        item_unit = payload.get("selected_unit")

        if normalized in ["back", "menu", "cancel", "0"]:
            db.delete(pending)
            db.commit()
            return None

        if normalized in ["1", "add", "add more", "add stock"]:
            pending.action = ACTION_STOCK_ITEM_ADD_QTY
            db.commit()
            unit_label = f" {item_unit}" if item_unit else ""
            send_message(phone, f"How many{unit_label} of *{item_name.title()}* are you adding?")
            return {"status": "stock_item_add_qty_prompt"}

        if normalized in ["2", "price", "update price", "update"]:
            pending.action = ACTION_STOCK_ITEM_UPDATE_PRICE
            db.commit()
            unit_label = f" per {item_unit}" if item_unit else ""
            send_message(
                phone,
                f"New cost price{unit_label} for *{item_name.title()}*?\n"
                "(Send 0 or SKIP to keep current)\n\n"
                "Format: cost then sell — e.g.  500 700"
            )
            return {"status": "stock_item_update_price_prompt"}

        if normalized in ["3", "delete", "remove"]:
            from inventory_suppliers import delete_stock_item
            count = delete_stock_item(db, business_owner_phone, item_name)
            db.commit()
            db.delete(pending)
            db.commit()
            send_message(phone, f"Deleted *{item_name.title()}* from your stock.\n\nSend *stock* to see your updated inventory.")
            return {"status": "stock_item_deleted"}

        if normalized in ["4", "rename", "rename item", "edit name"]:
            pending.action = ACTION_STOCK_ITEM_RENAME
            db.commit()
            send_message(phone, f"New name for *{item_name.title()}*?\n\nSend the corrected product name.")
            return {"status": "stock_item_rename_prompt"}

        send_message(
            phone,
            f"*{item_name.title()}*\n\n"
            "1. Add more stock\n2. Update price\n3. Delete item\n4. Rename item\n\nReply BACK to return."
        )
        return {"status": "stock_item_menu_reprompt"}

    # ── Add qty to existing item ─────────────────────────────────────────────
    if action == ACTION_STOCK_ITEM_ADD_QTY:
        item_name = payload.get("selected_name", "")
        item_unit = payload.get("selected_unit")
        qty_str = normalized.replace(",", "")
        if not qty_str.isdigit() or int(qty_str) < 1:
            send_message(phone, "Send a number greater than 0. Example: 20")
            return {"status": "stock_item_add_qty_invalid"}
        qty = int(qty_str)
        manual_stock_add(db, business_owner_phone, item_name, qty, item_unit, None, "Manual add")
        db.commit()
        db.delete(pending)
        db.commit()
        unit_label = f" {item_unit}" if item_unit else ""
        send_message(phone, f"Added {qty:,}{unit_label} to *{item_name.title()}*.\n\nSend *stock* to see your updated inventory.")
        return {"status": "stock_item_qty_added"}

    # ── Update price ─────────────────────────────────────────────────────────
    if action == ACTION_STOCK_ITEM_UPDATE_PRICE:
        item_name = payload.get("selected_name", "")
        item_unit = payload.get("selected_unit")

        parts = text.strip().replace(",", "").split()
        nums = []
        for p in parts:
            p2 = p.lower().replace("n", "").strip()
            try:
                nums.append(int(float(p2)))
            except ValueError:
                pass

        if not nums:
            send_message(phone, "Send cost and sell price. Example:  500 700\nOr send SKIP to cancel.")
            return {"status": "stock_item_update_price_invalid"}

        cost = nums[0] if len(nums) >= 1 else 0
        sell = nums[1] if len(nums) >= 2 else nums[0]

        upsert_stock_with_prices(db, business_owner_phone, item_name, item_unit, cost, sell)
        db.commit()
        db.delete(pending)
        db.commit()
        send_message(
            phone,
            f"Price updated for *{item_name.title()}*.\n"
            f"Cost: N{cost:,}  |  Sell: N{sell:,}\n\n"
            "Send *stock* to see your updated inventory."
        )
        return {"status": "stock_item_price_updated"}

    # ── Rename item ──────────────────────────────────────────────────────────
    if action == ACTION_STOCK_ITEM_RENAME:
        item_id = payload.get("selected_id")
        item_name = payload.get("selected_name", "")

        if normalized in ["back", "cancel", "skip"]:
            db.delete(pending)
            db.commit()
            return None

        new_name = text.strip()
        if len(new_name) < 2:
            send_message(phone, "Send the new product name. Example: Paracetamol 500mg")
            return {"status": "stock_item_rename_invalid"}

        from models import InventoryItem as _Inv
        from item_normalizer import normalize_item as _norm
        norm_name, _ = _norm(new_name, None)
        item = db.query(_Inv).filter(_Inv.id == item_id).first()
        if not item:
            db.delete(pending)
            db.commit()
            send_message(phone, "Item not found. Send *stock* to refresh.")
            return {"status": "stock_item_rename_not_found"}

        old_name = item.name
        item.name = norm_name
        db.commit()
        db.delete(pending)
        db.commit()
        send_message(
            phone,
            f"Renamed *{old_name.title()}* → *{norm_name.title()}*.\n\n"
            "Send *stock* to see your updated inventory."
        )
        return {"status": "stock_item_renamed"}

    return None


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
    # ── Awaiting clarification follow-up ────────────────────────────────────
    if pending and pending.action == ACTION_AWAITING_CLARIFICATION and not is_command:
        original_text = pending.source_text or ""
        clarification_question = pending.product or ""
        followup = interpret_text_with_openai_followup(original_text, clarification_question, text)
        db.delete(pending)
        db.commit()
        if followup and followup.get("understood"):
            normalized = (followup.get("normalized_text") or "").strip()
            if normalized:
                followup_parsed = parse_message(normalized)
                if followup_parsed:
                    print(f"OpenAI clarification resolved: {normalized}", flush=True)
                    return PendingRouteResult(parsed=followup_parsed, is_command=followup_parsed["type"] != "TRANSACTION")
        send_whatsapp_message(phone, build_invalid_message(user))
        return PendingRouteResult(response={"status": "clarification_unresolved"})

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

    # ── Context memory recovery: numbered reply after PendingAction expired ───
    # When a user's PendingAction is gone (expired/deleted) but their session is
    # still active within the 10-minute window, recreate a temporary PendingAction
    # so the home/dashboard menu handlers can process the numbered selection normally.
    if not pending and not is_command and user and re.match(r"^\d+$", text.strip()):
        active_menu = get_active_menu(db, phone)
        if active_menu in ("OWNER_HOME_MENU", "STAFF_HOME_MENU", "DASHBOARD_MENU"):
            pending = PendingAction(phone=phone, action=active_menu)
            db.add(pending)
            db.commit()

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

    # ── Guided stock add (catalog Q&A) ───────────────────────────────────────
    if pending and pending.action in GUIDED_STOCK_ACTIONS and not is_command:
        if parsed and parsed.get("type") == "TRANSACTION":
            db.delete(pending)
            db.commit()
        else:
            result = handle_guided_stock_pending(
                db, phone, text, pending, user, business_owner_phone, send_whatsapp_message,
            )
            if result:
                return _wrap(result)

    # ── Guided service price list setup ──────────────────────────────────────
    if pending and pending.action in GUIDED_SERVICE_SETUP_ACTIONS and not is_command:
        result = handle_guided_service_pending(
            db, phone, text, pending, user, business_owner_phone, send_whatsapp_message,
        )
        if result:
            return _wrap(result)

    # ── Service job confirm (brought/drop flow) ───────────────────────────────
    if pending and pending.action == ACTION_SERVICE_JOB_CONFIRM and not is_command:
        result = handle_service_job_confirm(
            db, phone, text, pending, user, business_owner_phone, send_whatsapp_message,
        )
        if result:
            return _wrap(result)

    # ── Stock menu (after viewing stock list) ────────────────────────────────
    if pending and pending.action in STOCK_MENU_ACTIONS and not is_command:
        if parsed and parsed.get("type") == "TRANSACTION" and pending.action != ACTION_STOCK_MENU:
            db.delete(pending)
            db.commit()
        else:
            result = _handle_stock_menu(
                db, phone, text, pending, user, business_owner_phone, send_whatsapp_message,
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
        if parsed and parsed.get("type") == "TRANSACTION":
            db.delete(pending)
            db.commit()
        else:
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
