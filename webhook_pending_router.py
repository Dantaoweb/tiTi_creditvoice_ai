import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from admin_commands import (
    handle_subscription_admin_pending_selection,
    notify_subscription_admins,
)
from home_menu_commands import handle_home_menu_pending
from messages import edit_prompt_for_pending
from models import Customer, Transaction
from onboarding_commands import (
    handle_onboarding_pending,
    handle_post_onboarding_pending,
    start_onboarding,
)
from reminder_commands import handle_reminder_pending
from reports import build_dashboard_menu_message, build_dashboard_selection_message
from subscription_flow import handle_subscription_pending_flow
from transaction_save import save_confirmed_pending_transaction
from transaction_setup import build_projected_balance_line
from webhook_admin_handlers import handle_app_admin_dashboard_pending
from webhook_context import can_view_all_business_transactions
from whatsapp_client import send_whatsapp_message


@dataclass
class PendingRouteResult:
    response: dict | None = None
    parsed: dict | None = None
    is_command: bool = False


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
    if pending and not is_command:
        subscription_admin_selection_result = handle_subscription_admin_pending_selection(
            db,
            phone,
            text,
            pending,
            user,
            send_whatsapp_message,
        )
        if subscription_admin_selection_result:
            return subscription_admin_selection_result

    if pending and not is_command:
        subscription_pending_result = handle_subscription_pending_flow(
            db,
            phone,
            text,
            pending,
            user,
            subscription,
            business_name,
            parsed,
            send_whatsapp_message,
            notify_subscription_admins
        )
        if subscription_pending_result:
            return subscription_pending_result
    if pending and not is_command:
        post_onboarding_result = handle_post_onboarding_pending(
            db,
            phone,
            text,
            pending,
            user,
            business_name,
            send_whatsapp_message
        )
        if post_onboarding_result:
            return post_onboarding_result
    if pending and pending.action == "ARTISAN_PAYMENT_CHOICE" and not is_command:
        normalized = text.lower().strip()
        if normalized in ["1", "service", "work", "income", "new work"]:
            pending.action = "SALE"
            pending.buy_amount = pending.paid_amount
            pending.product = pending.product or f"service/work - {pending.customer_name}"
            pending.quantity = 1
            pending.unit_price = pending.buy_amount
            db.commit()
            send_whatsapp_message(
                phone,
                f"Confirm service income, no customer debt:\n"
                f"{pending.product.title()} - N{pending.buy_amount:,}\n"
                "Reply YES or 1 to save, EDIT or 2 to change."
            )
            return {"status": "artisan_service_confirm"}

        if normalized in ["2", "debt", "debit", "old debt", "existing debt"]:
            customer = db.query(Customer).filter(
                Customer.name == pending.customer_name,
                Customer.owner_phone == business_owner_phone
            ).first()
            if not customer:
                customer = Customer(
                    name=pending.customer_name,
                    owner_phone=business_owner_phone
                )
                db.add(customer)
                db.flush()

            pending.action = "PAY"
            pending.last_customer = customer.name
            db.commit()
            balance_after_line = build_projected_balance_line(
                db,
                customer.id,
                {"buy_amount": 0, "paid_amount": pending.paid_amount},
                visible_recorded_by_id
            )
            send_whatsapp_message(
                phone,
                f"Confirm debt payment:\n"
                f"{customer.name.title()} paid N{pending.paid_amount:,}\n"
                f"{balance_after_line}\n"
                "Reply YES or 1 to save, EDIT or 2 to change."
            )
            return {"status": "artisan_debt_payment_confirm"}

        if normalized in ["edit", "change", "cancel", "back", "exit"]:
            db.delete(pending)
            db.commit()
            send_whatsapp_message(
                phone,
                "Enter again. Example:\nI received 1000 for doing chair\nor\nAde paid 7000"
            )
            return {"status": "artisan_choice_cancelled"}

        send_whatsapp_message(
            phone,
            f"{pending.customer_name.title()} paid you N{pending.paid_amount:,}.\n\n"
            "What is this for?\n"
            "1. For the work/service you did, no customer debt\n"
            "2. He/she paid debt owed to you"
        )
        return {"status": "artisan_choice_waiting"}

    if pending and not is_command:
        home_menu_result = handle_home_menu_pending(
            db,
            phone,
            text,
            pending,
            user,
            subscription,
            business_name,
            can_view_all_business_transactions(user),
            send_whatsapp_message
        )
        if home_menu_result:
            if home_menu_result.get("parsed"):
                parsed = home_menu_result["parsed"]
                is_command = True
            else:
                return home_menu_result
    # =========================
    # ðŸ‘¤ USER ONBOARDING / PROFILE UPDATE (CONFIRMATION)
    if pending and not is_command:
        onboarding_result = handle_onboarding_pending(
            db,
            phone,
            text,
            pending,
            user,
            send_whatsapp_message
        )
        if onboarding_result:
            return onboarding_result

    if not user and not parsed:
        return start_onboarding(db, phone, pending, send_whatsapp_message)
    # Special Greeting for a Delegate's first time or on 'hello'
    if user and user.role == "delegate" and text.lower().strip() in ["hello", "hi", "titi"]:
        send_whatsapp_message(
            phone,
            f"Hello {user.name.title()}! ðŸ‘‹\n\n"
            f"You are logged in as a staff member for *{business_name.title()}*.\n\n"
            "You can record transactions or check balances for the business here."
        )
        return {"status": "delegate_greeted"}

    if pending and pending.action == "RESIGN_CONFIRM" and not is_command:
        normalized = text.strip()
        if normalized in ["1", "yes"]:
            # Save admin phone for notification before clearing association
            admin_notify_phone = business_owner_phone

            user.role = "user"
            user.parent_id = None
            user.can_view_all_transactions = False
            db.delete(pending)
            db.commit()
            send_whatsapp_message(
                phone,
                f"âœ… You have successfully resigned. You no longer have access to {business_name.title()}'s data."
            )
            # Notify Admin
            if admin_notify_phone != phone:
                send_whatsapp_message(
                    admin_notify_phone,
                    f"ðŸ“¢ Notification: {user.name.title()} has RESIGNED as your staff member."
                )
            return {"status": "resigned_success"}
        
        if normalized in ["2", "no", "edit"]:
            db.delete(pending)
            db.commit()
            send_whatsapp_message(phone, "Resignation cancelled. You are still staff.")
            return {"status": "resigned_cancelled"}
        
        send_whatsapp_message(
            phone,
            f"Are you sure you want to stop working with *{business_name.title()}*?\n\n1. Yes, Confirm\n2. No, Cancel"
        )
        return {"status": "resigned_confirm_waiting"}

    if pending and pending.action == "ONBOARD_CUSTOMER" and not is_command:
        normalized = text.lower().strip()
        if normalized in ["yes", "1", "save"]:
            if pending.action == "SALE":
                recent_tx = db.query(Transaction).filter(
                    Transaction.type == "SALE",
                    Transaction.amount == pending.buy_amount,
                    Transaction.product == pending.product,
                    Transaction.recorded_by_id == user.id,
                    Transaction.created_at >= datetime.utcnow() - timedelta(minutes=2)
                ).first()

                if recent_tx:
                    send_whatsapp_message(
                        phone,
                        "A similar direct sale was already recorded just a moment ago."
                    )
                    db.delete(pending)
                    db.commit()
                    return {"status": "duplicate_sale_prevention"}

                tx = Transaction(
                    customer_id=None,
                    type="SALE",
                    amount=pending.buy_amount,
                    product=pending.product,
                    quantity=pending.quantity,
                    unit=pending.unit,
                    unit_price=pending.unit_price,
                    recorded_by_id=user.id,
                    message_id=message_id,
                    created_at=datetime.utcnow()
                )
                db.add(tx)
                db.delete(pending)
                db.commit()

                send_whatsapp_message(
                    phone,
                    f"âœ… Direct sale saved.\n"
                    f"{pending.product.title()}: â‚¦{pending.buy_amount:,}"
                )
                return {"status": "direct_sale_saved"}

            customer = db.query(Customer).filter(
                Customer.name == pending.customer_name,
                Customer.owner_phone == business_owner_phone
            ).first()

            if not customer:
                customer = Customer(
                    name=pending.customer_name,
                    owner_phone=business_owner_phone,
                    customer_phone=pending.customer_phone
                )
                db.add(customer)
            else:
                if pending.customer_phone:
                    customer.customer_phone = pending.customer_phone

            db.delete(pending)
            db.commit()

            phone_status = customer.customer_phone or "no phone added"
            send_whatsapp_message(
                phone,
                f"Customer saved: {customer.name.title()} -> {phone_status}.\n"
                "You can now record transactions for this customer."
            )
            return {"status": "customer_onboarded"}

        if normalized in ["edit", "2", "change"]:
            db.delete(pending)
            db.commit()

            send_whatsapp_message(
                phone,
                "Okay, please send the customer again like:\nJohn 08012345678"
            )
            return {"status": "customer_onboarded_edit"}

        send_whatsapp_message(
            phone,
            "I found a customer ready to save. Reply YES or 1 to confirm, EDIT or 2 to send it again."
        )
        return {"status": "customer_onboarded_confirm"}

    if pending and not is_command:
        app_admin_dashboard_result = handle_app_admin_dashboard_pending(
            db,
            phone,
            text,
            pending,
        )
        if app_admin_dashboard_result:
            return app_admin_dashboard_result

        if pending.action == "DASHBOARD_MENU":
            normalized = text.strip().lower()
            dashboard_aliases = {
                "today": "1",
                "this week": "2",
                "week": "2",
                "this month": "3",
                "month": "3",
                "this year": "4",
                "year": "4",
                "all": "5",
                "all time": "5",
                "customers": "6",
                "customer count": "6",
                "customer list": "7",
                "list customers": "7",
                "debtors": "8",
                "unpaid": "8",
                "unpaid debtors": "8",
                "products": "9",
                "product leaderboard": "9"
            }
            selection = dashboard_aliases.get(normalized, normalized)
            status, msg = build_dashboard_selection_message(
                db,
                business_owner_phone,
                selection,
                visible_recorded_by_id
            )

            if not msg:
                send_whatsapp_message(phone, build_dashboard_menu_message())
                return {"status": "invalid_dashboard_menu_option"}

            db.delete(pending)
            db.commit()
            send_whatsapp_message(phone, msg)
            return {"status": status}

        reminder_pending_result = handle_reminder_pending(
            db,
            phone,
            text,
            pending,
            business_owner_phone,
            visible_recorded_by_id,
            send_whatsapp_message
        )
        if reminder_pending_result:
            return reminder_pending_result
        normalized = text.lower().strip()
        if normalized in ["yes", "1", "save"]:
            pending_items = json.loads(pending.items_json or "[]")
            save_result = save_confirmed_pending_transaction(
                db,
                phone,
                pending,
                user,
                business_owner_phone,
                visible_recorded_by_id,
                message_id,
                pending_items,
                subscription,
                send_whatsapp_message
            )
            if save_result:
                return save_result
        elif normalized == "3" and pending.source_text:
            db.delete(pending)
            db.commit()
            send_whatsapp_message(phone, "Send the voice note again.")
            return {"status": "voice_retry_requested"}

        elif normalized in ["edit", "2", "change"]:
            is_voice_edit = bool(pending.source_text)
            edit_msg = edit_prompt_for_pending(pending, user)
            db.delete(pending)
            db.commit()
            send_whatsapp_message(phone, edit_msg)
            return {"status": "voice_text_edit" if is_voice_edit else "edit"}


    return PendingRouteResult(parsed=parsed, is_command=is_command)

