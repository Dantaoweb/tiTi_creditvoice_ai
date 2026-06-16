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
    ACTION_AWAITING_STOCK_PRICE,
    ACTION_CHANGE_DUE_DATE,
    ACTION_DASHBOARD_MENU,
    ACTION_DEBTOR_MANAGE_MENU,
    ACTION_ONBOARD_CUSTOMER,
    ACTION_PRODUCT_BUYERS_MENU,
    ACTION_RESIGN_CONFIRM,
    ACTION_RESTOCK_ALERT_CONFIRM,
    ACTION_RESTOCK_ALERT_SELECT,
    ACTION_SERVICE_JOB_CONFIRM,
    ACTION_STOCK_ADD_CONFIRM,
    ACTION_STOCK_ITEM_ADD_QTY,
    ACTION_STOCK_ITEM_CHANGE_UNIT,
    ACTION_STOCK_ITEM_DELETE_CONFIRM,
    ACTION_STOCK_ITEM_MENU,
    ACTION_STOCK_ITEM_RENAME,
    ACTION_STOCK_ITEM_SET_CATEGORY,
    ACTION_STOCK_ITEM_SET_EXPIRY,
    ACTION_STOCK_ITEM_UPDATE_PRICE,
    ACTION_STOCK_MENU,
    ACTION_UNPAID_DEBTORS_MENU,
    FAST_CAPTURE_REVIEW_ACTIONS,
    GUIDED_SERVICE_SETUP_ACTIONS,
    GUIDED_STOCK_ACTIONS,
    SELECT_PRODUCT_ACTIONS,
    STOCK_MENU_ACTIONS,
    TRUCK_WIZARD_ACTIONS,
    TRIP_WIZARD_ACTIONS,
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
from reports import build_dashboard_menu_message, build_dashboard_selection_message, get_balance, get_unpaid_debtors
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
    db, phone, text, pending, business_owner_phone, visible_recorded_by_id, user=None
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
        db, business_owner_phone, selection, visible_recorded_by_id, user
    )

    if not msg:
        send_whatsapp_message(phone, add_stock_option_to_menu(build_dashboard_menu_message()))
        return PendingRouteResult(response={"status": "invalid_dashboard_menu_option"})

    # Unpaid debtors list is interactive — switch to dedicated menu pending
    if status == "dashboard_unpaid_debtors":
        pending.action = ACTION_UNPAID_DEBTORS_MENU
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
        page = payload.get("page", 0)

        if normalized in ["add", "add stock", "new", "new product"] or normalized.startswith("add "):
            db.delete(pending)
            db.commit()
            return start_guided_stock_flow(db, phone, user, send_message)

        if normalized in ["more", "next", "more items"]:
            from inventory_suppliers import build_inventory_list_message as _bil
            product_filter = payload.get("product")
            new_page = page + 1
            msg, all_ids = _bil(db, business_owner_phone, product_filter, return_ids=True, page=new_page)
            payload["page"] = new_page
            payload["item_ids"] = all_ids
            pending.payload_json = json.dumps(payload)
            db.commit()
            footer = "\n\n─────────────\nReply a *number* to manage that item.\nReply *ADD* to add a new product."
            send_message(phone, msg + footer)
            return {"status": "stock_menu_next_page"}

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
            payload["selected_category"] = item.category or ""
            payload["selected_expiry"] = item.expiry_date.strftime("%m/%Y") if item.expiry_date else ""
            payload["selected_batch"] = item.batch_no or ""
            pending.payload_json = json.dumps(payload)
            db.commit()

            cat_line = f"Category: {item.category.title()}\n" if item.category else ""
            _exp_line = ""
            if item.expiry_date:
                from datetime import datetime as _dt
                _now = _dt.utcnow()
                _days = (item.expiry_date - _now).days
                _exp_str = item.expiry_date.strftime("%m/%Y")
                _exp_line = (
                    f"⚠ Expires: {_exp_str} (EXPIRED)\n" if _days < 0
                    else f"⚠ Expires: {_exp_str} ({_days}d)\n" if _days <= 30
                    else f"Expires: {_exp_str}\n"
                )
            _batch_line = f"Batch: {item.batch_no}\n" if item.batch_no else ""
            send_message(
                phone,
                f"*{item.name.title()}{unit_label}*\n"
                f"Qty: {qty:,}{unit_label}\n"
                f"{cost_line}  |  {sell_line}\n"
                f"{cat_line}{_exp_line}{_batch_line}\n"
                "1. Add more stock\n"
                "2. Update price\n"
                "3. Delete item\n"
                "4. Rename item\n"
                "5. Change unit\n"
                "6. Buyers & restock\n"
                "7. Set category\n"
                "8. Expiry / Batch no.\n\n"
                "Reply *BACK* to return to stock list."
            )
            return {"status": "stock_item_menu_shown"}

        # "rename [item]" or "edit [item]" from the stock list — go straight to rename
        import re as _re
        _rename_list_m = _re.match(
            r"^(?:rename|edit|correct|fix)\s+(.+)$", normalized
        )
        if _rename_list_m:
            _target = _rename_list_m.group(1).strip()
            from models import InventoryItem as _InvR
            _match_item = (
                db.query(_InvR)
                .filter(
                    _InvR.owner_phone == business_owner_phone,
                    _InvR.name.ilike(f"%{_target}%"),
                )
                .first()
            )
            if _match_item:
                pending.action = ACTION_STOCK_ITEM_RENAME
                pending.payload_json = json.dumps({
                    "selected_id": _match_item.id,
                    "selected_name": _match_item.name,
                    "selected_unit": _match_item.unit or "",
                })
                db.commit()
                send_message(phone, f"New name for *{_match_item.name.title()}*?\n\nSend the corrected product name.")
                return {"status": "stock_rename_from_list"}
            send_message(phone, f"Product '{_target}' not found. Send *stock* to see your list.")
            db.delete(pending)
            db.commit()
            return {"status": "stock_rename_not_found"}

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
            from inventory_suppliers import build_inventory_list_message as _bil
            back_page = payload.get("page", 0)
            msg, all_ids = _bil(db, business_owner_phone, return_ids=True, page=back_page)
            pending.action = ACTION_STOCK_MENU
            pending.payload_json = json.dumps({"item_ids": all_ids, "page": back_page})
            db.commit()
            footer = "\n\n─────────────\nReply a *number* to manage that item.\nReply *ADD* to add a new product."
            send_message(phone, msg + footer)
            return {"status": "stock_back_to_list"}

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
            from models import InventoryItem as _InvD
            _item_d = db.query(_InvD).filter(_InvD.id == item_id).first()
            qty_info = ""
            if _item_d:
                qty = _item_d.quantity or 0
                unit_label_d = f" {_item_d.unit}" if _item_d.unit else ""
                qty_info = f"\nCurrent stock: {qty:,}{unit_label_d}"
            pending.action = ACTION_STOCK_ITEM_DELETE_CONFIRM
            db.commit()
            send_message(
                phone,
                f"⚠️ Delete *{item_name.title()}*?{qty_info}\n\n"
                "This will remove the item and all its price data.\n"
                "Transaction history will not be affected.\n\n"
                "Reply *YES* to confirm delete\nReply *NO* or *BACK* to cancel."
            )
            return {"status": "stock_item_delete_confirm_prompt"}

        if normalized in ["4", "rename", "rename item", "edit", "edit name",
                          "correct", "correct name", "fix", "fix name",
                          "change name", "update name"]:
            pending.action = ACTION_STOCK_ITEM_RENAME
            db.commit()
            send_message(phone, f"New name for *{item_name.title()}*?\n\nSend the corrected product name.")
            return {"status": "stock_item_rename_prompt"}

        if normalized in ["5", "change unit", "unit"]:
            pending.action = ACTION_STOCK_ITEM_CHANGE_UNIT
            db.commit()
            current_unit = item_unit or "none"
            send_message(
                phone,
                f"Current unit for *{item_name.title()}*: {current_unit}\n\n"
                "Send the new unit (e.g. bag, kg, piece, box)\n"
                "or send *REMOVE* to clear the unit."
            )
            return {"status": "stock_item_change_unit_prompt"}

        if normalized in ["6", "buyers", "restock", "buyers & restock", "buyers and restock"]:
            if not user:
                send_message(phone, "Register first to use this feature.")
                return {"status": "restock_no_user"}
            db.delete(pending)
            db.commit()
            from restock_commands import handle_restock_command
            return handle_restock_command(
                db, phone, item_name, user, business_owner_phone, visible_recorded_by_id, send_message,
            )

        if normalized in ["7", "category", "set category", "set cat"]:
            pending.action = ACTION_STOCK_ITEM_SET_CATEGORY
            db.commit()
            _cat_now = payload.get("selected_category", "") or ""
            cat_hint = f"\nCurrent: {_cat_now.title()}" if _cat_now else ""
            send_message(
                phone,
                f"Category for *{item_name.title()}*?{cat_hint}\n\n"
                "Examples: grains, drinks, toiletries, electronics\n"
                "Or send *REMOVE* to clear the category."
            )
            return {"status": "stock_item_set_category_prompt"}

        if normalized in ["8", "expiry", "batch", "expiry batch", "batch no", "expiry / batch no.", "set expiry"]:
            pending.action = ACTION_STOCK_ITEM_SET_EXPIRY
            db.commit()
            _exp_now = payload.get("selected_expiry", "") or ""
            _bat_now = payload.get("selected_batch", "") or ""
            cur = ""
            if _exp_now:
                cur += f"\nCurrent expiry: {_exp_now}"
            if _bat_now:
                cur += f"\nCurrent batch: {_bat_now}"
            send_message(
                phone,
                f"Expiry / Batch for *{item_name.title()}*?{cur}\n\n"
                "Send expiry date (MM/YYYY) and optionally batch/NAFDAC number.\n"
                "Examples:\n"
                "  06/2026\n"
                "  06/2026 BN-1234\n"
                "  06/2026 NAFDAC A4-1234\n\n"
                "Send *REMOVE* to clear both. Send *SKIP* to cancel."
            )
            return {"status": "stock_item_set_expiry_prompt"}

        send_message(
            phone,
            f"*{item_name.title()}*\n\n"
            "1. Add more stock\n2. Update price\n3. Delete item\n"
            "4. Rename item\n5. Change unit\n6. Buyers & restock\n"
            "7. Set category\n8. Expiry / Batch no.\n\n"
            "Reply BACK to return."
        )
        return {"status": "stock_item_menu_reprompt"}

    # ── Add qty to existing item ─────────────────────────────────────────────
    if action == ACTION_STOCK_ITEM_ADD_QTY:
        item_name = payload.get("selected_name", "")
        item_unit = payload.get("selected_unit")
        qty_str = normalized.replace(",", "").split()[0] if normalized.strip() else ""
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

        item_id = payload.get("selected_id")
        if item_id:
            from models import InventoryItem as _InvItem
            _inv = db.query(_InvItem).filter(_InvItem.id == item_id).first()
            if _inv:
                _inv.cost_price = cost
                _inv.selling_price = sell
                _inv.is_available = True
        else:
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

    # ── Change unit ──────────────────────────────────────────────────────────
    if action == ACTION_STOCK_ITEM_CHANGE_UNIT:
        item_id = payload.get("selected_id")
        item_name = payload.get("selected_name", "")

        if normalized in ["back", "cancel", "skip"]:
            db.delete(pending)
            db.commit()
            return None

        from models import InventoryItem as _InvCU
        item = db.query(_InvCU).filter(_InvCU.id == item_id).first()
        if not item:
            db.delete(pending)
            db.commit()
            send_message(phone, "Item not found. Send *stock* to refresh.")
            return {"status": "stock_item_change_unit_not_found"}

        if normalized == "remove":
            item.unit = None
            unit_display = "removed"
        else:
            new_unit = text.strip().lower()
            if not new_unit or len(new_unit) > 20:
                send_message(phone, "Send a unit name (e.g. bag, kg, piece) or REMOVE to clear.")
                return {"status": "stock_item_change_unit_invalid"}
            item.unit = new_unit
            unit_display = new_unit

        db.commit()
        db.delete(pending)
        db.commit()
        send_message(
            phone,
            f"Unit updated: *{item_name.title()}* — {unit_display}\n\n"
            "Send *stock* to see your updated inventory."
        )
        return {"status": "stock_item_change_unit_saved"}

    # ── Delete confirmation ──────────────────────────────────────────────────
    if action == ACTION_STOCK_ITEM_DELETE_CONFIRM:
        item_id = payload.get("selected_id")
        item_name = payload.get("selected_name", "")

        if normalized in ["no", "back", "cancel", "stop"]:
            pending.action = ACTION_STOCK_ITEM_MENU
            db.commit()
            from models import InventoryItem as _InvBack
            _item_back = db.query(_InvBack).filter(_InvBack.id == item_id).first()
            if _item_back:
                qty = _item_back.quantity or 0
                unit_label = f" {_item_back.unit}" if _item_back.unit else ""
                cost_line = f"Cost: N{_item_back.cost_price:,}" if _item_back.cost_price else "Cost: not set"
                sell_line = f"Sell: N{_item_back.selling_price:,}" if _item_back.selling_price else "Sell: not set"
                _cat_line = f"Category: {_item_back.category.title()}\n" if _item_back.category else ""
                send_message(
                    phone,
                    f"*{item_name.title()}{unit_label}*\n"
                    f"Qty: {qty:,}{unit_label}\n"
                    f"{cost_line}  |  {sell_line}\n"
                    f"{_cat_line}\n"
                    "1. Add more stock\n"
                    "2. Update price\n"
                    "3. Delete item\n"
                    "4. Rename item\n"
                    "5. Change unit\n"
                    "6. Buyers & restock\n"
                    "7. Set category\n"
                    "8. Expiry / Batch no.\n\n"
                    "Reply *BACK* to return to stock list."
                )
            else:
                send_message(phone, "Delete cancelled.")
            return {"status": "stock_item_delete_cancelled"}

        if normalized in ["yes", "1", "confirm", "delete"]:
            from inventory_suppliers import delete_stock_item
            delete_stock_item(db, business_owner_phone, item_name)
            db.commit()
            db.delete(pending)
            db.commit()
            send_message(phone, f"Deleted *{item_name.title()}* from your stock.\n\nSend *stock* to see your updated inventory.")
            return {"status": "stock_item_deleted"}

        send_message(
            phone,
            f"Reply *YES* to confirm deleting *{item_name.title()}*\nor *NO* to cancel."
        )
        return {"status": "stock_item_delete_confirm_reprompt"}

    # ── Set expiry date / batch number ───────────────────────────────────────
    if action == ACTION_STOCK_ITEM_SET_EXPIRY:
        import re as _re
        from datetime import datetime as _dtp
        item_id = payload.get("selected_id")
        item_name = payload.get("selected_name", "")

        if normalized in ["skip", "cancel", "back"]:
            db.delete(pending)
            db.commit()
            return None

        from models import InventoryItem as _InvEx
        _inv_ex = db.query(_InvEx).filter(_InvEx.id == item_id).first()
        if not _inv_ex:
            send_message(phone, "Item not found. Send *stock* to refresh.")
            db.delete(pending)
            db.commit()
            return {"status": "stock_item_expiry_not_found"}

        if normalized in ["remove", "clear", "none", "delete"]:
            _inv_ex.expiry_date = None
            _inv_ex.batch_no = None
            db.commit()
            db.delete(pending)
            db.commit()
            send_message(phone, f"Expiry and batch cleared for *{item_name.title()}*.")
            return {"status": "stock_item_expiry_cleared"}

        # Parse "MM/YYYY [optional batch text]"
        _exp_m = _re.match(r"^(\d{1,2})[/\-](\d{4})\s*(.*)?$", text.strip())
        if not _exp_m:
            send_message(
                phone,
                "Send expiry as MM/YYYY, e.g.:\n  06/2026\n  06/2026 BN-1234\n\nOr REMOVE to clear."
            )
            return {"status": "stock_item_expiry_invalid"}

        month, year = int(_exp_m.group(1)), int(_exp_m.group(2))
        if not (1 <= month <= 12):
            send_message(phone, "Invalid month. Use MM/YYYY, e.g. 06/2026")
            return {"status": "stock_item_expiry_bad_month"}

        try:
            _exp_date = _dtp(year, month, 1)
        except ValueError:
            send_message(phone, "Invalid date. Use MM/YYYY, e.g. 06/2026")
            return {"status": "stock_item_expiry_bad_date"}

        _batch_text = _exp_m.group(3).strip() if _exp_m.group(3) else None
        _inv_ex.expiry_date = _exp_date
        if _batch_text:
            _inv_ex.batch_no = _batch_text

        from datetime import datetime as _dtx
        _days = (_exp_date - _dtx.utcnow()).days
        db.commit()
        db.delete(pending)
        db.commit()

        _exp_str = _exp_date.strftime("%m/%Y")
        _warn = " ⚠ This batch is expired!" if _days < 0 else (f" ⚠ Expires in {_days} days." if _days <= 30 else "")
        _batch_confirm = f"\nBatch: {_batch_text}" if _batch_text else ""
        send_message(
            phone,
            f"Updated *{item_name.title()}*:\nExpiry: {_exp_str}{_warn}{_batch_confirm}"
        )
        return {"status": "stock_item_expiry_saved"}

    # ── Set category ─────────────────────────────────────────────────────────
    if action == ACTION_STOCK_ITEM_SET_CATEGORY:
        item_id = payload.get("selected_id")
        item_name = payload.get("selected_name", "")

        if normalized in ["back", "cancel", "skip"]:
            db.delete(pending)
            db.commit()
            return None

        from models import InventoryItem as _InvCat
        _inv_cat = db.query(_InvCat).filter(_InvCat.id == item_id).first()
        if not _inv_cat:
            send_message(phone, "Item not found. Send *stock* to refresh.")
            db.delete(pending)
            db.commit()
            return {"status": "stock_item_set_category_not_found"}

        if normalized in ["remove", "clear", "none", "delete"]:
            _inv_cat.category = None
        else:
            _inv_cat.category = text.strip().lower()

        db.commit()
        db.delete(pending)
        db.commit()
        if _inv_cat.category:
            send_message(
                phone,
                f"Category set to *{_inv_cat.category.title()}* for *{item_name.title()}*.\n\n"
                "Items with the same category are grouped together in your stock list."
            )
        else:
            send_message(phone, f"Category cleared for *{item_name.title()}*.")
        return {"status": "stock_item_category_saved"}

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
    # ── Awaiting stock price (buy+paid with unknown total) ──────────────────
    if pending and pending.action == ACTION_AWAITING_STOCK_PRICE and not is_command:
        from parser import extract_amounts
        normalized = text.lower().strip()
        cname = (pending.customer_name or "customer").title()
        paid = pending.paid_amount or 0
        prod = (pending.product or "item").title()
        qty = pending.quantity or 1
        unit_str = pending.unit or ""
        qty_label = f"{qty} {unit_str}".strip() if unit_str else str(qty)

        if normalized in ["full", "all paid", "paid all", "complete", "full payment"]:
            buy_amount = paid
        else:
            amounts = extract_amounts(normalized)
            if not amounts:
                send_message(
                    phone,
                    f"Reply with the total price for {qty_label} {prod}.\n"
                    f"Or reply *FULL* if N{paid:,} is the full price."
                )
                return PendingRouteResult(response={"status": "awaiting_stock_price_retry"})
            buy_amount = amounts[0]

        unit_price = round(buy_amount / qty) if qty > 1 else buy_amount
        pending.action = "COMBINED"
        pending.buy_amount = buy_amount
        pending.unit_price = unit_price
        db.commit()

        from transaction_setup import build_projected_balance_line
        customer = db.query(Customer).filter(
            Customer.name == pending.customer_name,
            Customer.owner_phone == business_owner_phone,
        ).first()
        if not customer:
            customer = Customer(name=pending.customer_name, owner_phone=business_owner_phone)
            db.add(customer)
            db.commit()
            pending.last_customer = customer.name
            db.commit()

        balance_line = build_projected_balance_line(
            db, customer.id, {"buy_amount": buy_amount, "paid_amount": paid}, visible_recorded_by_id,
        )
        balance = buy_amount - paid
        if balance <= 0:
            balance_text = "Fully paid, no balance."
        else:
            balance_text = f"Balance: N{balance:,}"

        send_message(
            phone,
            f"Confirm:\n{cname} bought {qty_label} {prod}\n"
            f"Total: N{buy_amount:,}\n"
            f"Paid:  N{paid:,}\n"
            f"{balance_text}"
            f"{balance_line}\n\n"
            "Reply YES or 1 to save, EDIT or 2 to change."
        )
        return PendingRouteResult(response={"status": "stock_price_resolved_confirm"})

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
        # If user sends a service job while price list is open, save items and route to job
        if pending.action == ACTION_GUIDED_SERVICE_SETUP:
            from parser import parse_message as _pm
            _quick_parse = _pm(text)
            if _quick_parse and _quick_parse.get("type") == "SERVICE_JOB":
                from guided_service_commands import handle_guided_service_pending as _hgsp, _load as _gsp_load, _save_service_items as _gsp_save
                _payload = _gsp_load(pending)
                _items = _payload.get("items", [])
                if _items:
                    _gsp_save(db, business_owner_phone, _items)
                db.delete(pending)
                db.commit()
                from service_job_commands import start_service_job_confirm as _sjc
                result = _sjc(db, phone, business_owner_phone, user, _quick_parse, send_whatsapp_message)
                if result:
                    return _wrap(result)

        result = handle_guided_service_pending(
            db, phone, text, pending, user, business_owner_phone, send_whatsapp_message,
        )
        if result:
            return _wrap(result)

    # ── Truck add wizard ─────────────────────────────────────────────────────
    if pending and pending.action in TRUCK_WIZARD_ACTIONS and not is_command:
        from truck_commands import handle_add_truck_pending
        result = handle_add_truck_pending(db, phone, text, pending, send_whatsapp_message)
        if result:
            return _wrap(result)

    # ── Record trip wizard ───────────────────────────────────────────────────
    if pending and pending.action in TRIP_WIZARD_ACTIONS and not is_command:
        from truck_commands import handle_record_trip_pending
        result = handle_record_trip_pending(
            db, phone, text, pending, user, business_owner_phone, send_whatsapp_message
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

    # ── Unpaid debtors — pick debtor to manage ──────────────────────────────
    if pending and pending.action == ACTION_UNPAID_DEBTORS_MENU and not is_command:
        result = _wrap(_handle_unpaid_debtors_menu(
            db, phone, text, pending, business_owner_phone, visible_recorded_by_id,
        ))
        if result and result.response:
            return result

    # ── Debtor sub-menu (send reminder / change due date / view account) ────
    if pending and pending.action == ACTION_DEBTOR_MANAGE_MENU and not is_command:
        result = _wrap(_handle_debtor_manage_menu(
            db, phone, text, pending, business_owner_phone, visible_recorded_by_id, user,
        ))
        if result and result.response:
            return result

    # ── Change due date — accept new date from user ───────────────────────
    if pending and pending.action == ACTION_CHANGE_DUE_DATE and not is_command:
        result = _wrap(_handle_change_due_date(
            db, phone, text, pending, business_owner_phone,
        ))
        if result and result.response:
            return result

    # ── Restock alert flows ──────────────────────────────────────────────────
    if pending and pending.action == ACTION_PRODUCT_BUYERS_MENU and not is_command:
        from restock_commands import handle_product_buyers_menu
        result = _wrap(handle_product_buyers_menu(
            db, phone, text, pending, business_owner_phone, visible_recorded_by_id, send_whatsapp_message,
        ))
        if result and result.response:
            return result

    if pending and pending.action == ACTION_RESTOCK_ALERT_SELECT and not is_command:
        from restock_commands import handle_restock_alert_select
        result = _wrap(handle_restock_alert_select(
            db, phone, text, pending, send_whatsapp_message,
        ))
        if result and result.response:
            return result

    if pending and pending.action == ACTION_RESTOCK_ALERT_CONFIRM and not is_command:
        from restock_commands import handle_restock_alert_confirm
        result = _wrap(handle_restock_alert_confirm(
            db, phone, text, pending, user, send_whatsapp_message,
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
                db, phone, text, pending, business_owner_phone, visible_recorded_by_id, user,
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


# ── Unpaid debtors management ────────────────────────────────────────────────

def _handle_unpaid_debtors_menu(db, phone, text, pending, business_owner_phone, visible_recorded_by_id):
    normalized = text.strip()
    if not normalized.isdigit():
        send_whatsapp_message(phone, "Reply with a number to manage a debtor.")
        return {"status": "unpaid_menu_invalid"}

    index = int(normalized)
    debtors, _ = get_unpaid_debtors(db, business_owner_phone, visible_recorded_by_id)

    if index < 1 or index > len(debtors):
        tip = f"Reply 1–{len(debtors)}." if debtors else "No unpaid debtors found."
        send_whatsapp_message(phone, tip)
        return {"status": "unpaid_menu_out_of_range"}

    debtor = debtors[index - 1]
    cname = debtor["name"]
    balance = debtor["balance"]
    due_date = debtor.get("due_date")

    if debtor.get("overdue"):
        due_line = f"Due: {due_date.strftime('%d/%m/%Y')} (OVERDUE {debtor['overdue_days']}d)"
    elif due_date:
        due_line = f"Due: {due_date.strftime('%d/%m/%Y')}"
    else:
        due_line = "No due date set"

    sub_msg = (
        f"{cname.title()} - N{balance:,}\n"
        f"{due_line}\n\n"
        "1. Send reminder\n"
        "2. Change due date\n"
        "3. View account"
    )

    pending.action = ACTION_DEBTOR_MANAGE_MENU
    pending.customer_name = cname
    pending.last_customer = cname
    db.commit()

    send_whatsapp_message(phone, sub_msg)
    return {"status": "debtor_manage_menu"}


def _handle_debtor_manage_menu(db, phone, text, pending, business_owner_phone, visible_recorded_by_id, user):
    normalized = text.strip()
    cname = pending.customer_name or ""

    if normalized == "1":
        from models import ReminderMemory
        from parser import build_reminder_text

        customer = db.query(Customer).filter(
            Customer.name == cname,
            Customer.owner_phone == business_owner_phone,
        ).first()
        if not customer:
            send_whatsapp_message(phone, "Customer not found.")
            db.delete(pending)
            db.commit()
            return {"status": "debtor_manage_not_found"}

        balance = get_balance(db, customer.id, visible_recorded_by_id)

        latest_tx = db.query(Transaction).filter(
            Transaction.customer_id == customer.id,
            Transaction.type == "BUY",
            Transaction.due_date.isnot(None),
        ).order_by(Transaction.due_date.desc()).first()

        if not latest_tx:
            send_whatsapp_message(
                phone,
                f"{cname.title()} has no due date set.\n\nReply 2 to set one first."
            )
            return {"status": "debtor_no_due_for_reminder"}

        db.query(ReminderMemory).filter(ReminderMemory.phone == phone).delete()
        from datetime import datetime
        today = datetime.now().date()
        reminder_type = "OVERDUE" if latest_tx.due_date.date() < today else "DUE_TODAY"
        reminder = ReminderMemory(
            phone=phone,
            customer_id=customer.id,
            customer_name=cname,
            customer_phone=customer.customer_phone,
            balance=balance,
            due_date=latest_tx.due_date,
            reminder_type=reminder_type,
        )
        db.add(reminder)
        db.flush()

        preview = build_reminder_text(reminder)

        if customer.customer_phone:
            confirm_msg = (
                f"Preview for {cname.title()}:\n\n"
                f"{preview}\n\n"
                f"YES to send to {customer.customer_phone}. EDIT to cancel."
            )
        else:
            confirm_msg = (
                f"Preview for {cname.title()}:\n\n"
                f"{preview}\n\n"
                f"No phone set. Send:\n{cname} phone 08012345678\n"
                "Then reply YES."
            )

        pending.action = "REMINDER_CONFIRM"
        pending.reminder_id = reminder.id
        db.commit()

        send_whatsapp_message(phone, confirm_msg)
        return {"status": "reminder_preview"}

    if normalized == "2":
        pending.action = ACTION_CHANGE_DUE_DATE
        db.commit()
        send_whatsapp_message(
            phone,
            f"Set new due date for {cname.title()}.\n\n"
            "Reply with the date.\n"
            "Examples: 25/06/2026  •  25 June  •  tomorrow"
        )
        return {"status": "change_due_date_prompt"}

    if normalized == "3":
        from parser import build_customer_account_summary
        summary = build_customer_account_summary(
            db, business_owner_phone, cname,
            recorded_by_id=visible_recorded_by_id,
        )
        pending.action = ACTION_DASHBOARD_MENU
        db.commit()
        send_whatsapp_message(phone, summary)
        return {"status": "debtor_account_view"}

    send_whatsapp_message(phone, "Reply 1, 2, or 3.")
    return {"status": "debtor_manage_invalid"}


def _parse_new_due_date(text):
    """Parse user-supplied date text for the change-due-date flow."""
    from datetime import datetime, timedelta
    t = text.strip().lower()

    if t in ("tomorrow", "tmr", "tmrw"):
        return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

    if t in ("next week",):
        return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=7)

    # DD/MM/YYYY or DD/MM/YY
    slash = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", t)
    if slash:
        day, month, year = int(slash.group(1)), int(slash.group(2)), int(slash.group(3))
        if year < 100:
            year += 2000
        try:
            return datetime(year, month, day)
        except ValueError:
            pass

    months = {
        "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
        "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
        "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    }

    # "20 June [2026]"
    dm = re.search(r"(\d{1,2})\s+([a-z]+)(?:\s+(\d{4}))?", t)
    if dm:
        mon = months.get(dm.group(2))
        if mon:
            year = int(dm.group(3)) if dm.group(3) else datetime.now().year
            try:
                d = datetime(year, mon, int(dm.group(1)))
                if d.date() < datetime.now().date():
                    d = d.replace(year=d.year + 1)
                return d
            except ValueError:
                pass

    # "June 20 [2026]"
    md = re.search(r"([a-z]+)\s+(\d{1,2})(?:\s+(\d{4}))?", t)
    if md:
        mon = months.get(md.group(1))
        if mon:
            year = int(md.group(3)) if md.group(3) else datetime.now().year
            try:
                d = datetime(year, mon, int(md.group(2)))
                if d.date() < datetime.now().date():
                    d = d.replace(year=d.year + 1)
                return d
            except ValueError:
                pass

    return None


def _handle_change_due_date(db, phone, text, pending, business_owner_phone):
    cname = pending.customer_name or ""

    new_date = _parse_new_due_date(text)
    if not new_date:
        send_whatsapp_message(
            phone,
            "Date not recognised.\n\n"
            "Try: 25/06/2026  •  25 June  •  tomorrow"
        )
        return {"status": "change_due_date_invalid"}

    customer = db.query(Customer).filter(
        Customer.name == cname,
        Customer.owner_phone == business_owner_phone,
    ).first()
    if not customer:
        send_whatsapp_message(phone, "Customer not found.")
        db.delete(pending)
        db.commit()
        return {"status": "change_due_date_no_customer"}

    latest_tx = db.query(Transaction).filter(
        Transaction.customer_id == customer.id,
        Transaction.type == "BUY",
    ).order_by(Transaction.created_at.desc()).first()

    if not latest_tx:
        send_whatsapp_message(phone, f"No buy transaction found for {cname.title()}.")
        db.delete(pending)
        db.commit()
        return {"status": "change_due_date_no_tx"}

    latest_tx.due_date = new_date
    db.delete(pending)
    db.commit()

    date_str = new_date.strftime("%d/%m/%Y")
    send_whatsapp_message(phone, f"Due date for {cname.title()} updated to {date_str}.")
    return {"status": "due_date_changed"}


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
