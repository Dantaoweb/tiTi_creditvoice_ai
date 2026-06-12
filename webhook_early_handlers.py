from constants import GUIDED_SERVICE_SETUP_ACTIONS, GUIDED_STOCK_ACTIONS, STOCK_MENU_ACTIONS
from database import SessionLocal
from models import PendingAction, ReminderMemory, User
from parser import (
    build_customer_account_summary,
    parse_customer_account_request,
    parse_message,
    parse_slash_date,
)
from reports import get_due_in_2_days, get_due_today, get_overdue_debtors
from subscriptions import ensure_feature_allowed
from webhook_admin_handlers import is_admin_command_allowed
from webhook_context import visibility_recorded_by_id
from whatsapp_client import send_whatsapp_message


def is_reminder_automation_text(text):
    normalized = (text or "").strip().lower()
    return normalized.startswith((
        "reminder automation",
        "reminder preview",
        "auto reminders",
        "reminder time",
        "run reminder automation",
        "preview reminder automation",
        "reminder queue",
        "send reminder",
        "skip reminder",
        "edit reminder",
    ))


def handle_early_webhook_message(incoming):
    try:
        value = incoming.value
        print("Webhook value keys:", list(value.keys()), flush=True)

        if not incoming.message:
            print("Webhook contains no messages; likely status/delivery event", flush=True)
        else:
            message = incoming.message
            phone = incoming.phone
            text = incoming.text
            print(f"Webhook parsed message from {phone}: {text}", flush=True)

            if phone and text:
                debug_db = SessionLocal()
                try:
                    sender_exists = debug_db.query(User).filter(
                        User.phone == phone
                    ).first()
                    print(
                        f"Webhook sender registered: {bool(sender_exists)}",
                        flush=True
                    )
                    if not sender_exists:
                        admin_preview = parse_message(text)
                        admin_allowed = is_admin_command_allowed(
                            debug_db,
                            phone,
                            admin_preview,
                        )

                        if not admin_allowed:
                            print("Unregistered sender will continue to onboarding flow", flush=True)
                            raise LookupError("continue_to_onboarding")

                    early_visible_recorded_by_id = visibility_recorded_by_id(sender_exists)

                    pending = debug_db.query(PendingAction).filter(
                        PendingAction.phone == phone
                    ).order_by(
                        PendingAction.created_at.desc()
                    ).first()

                    _guided_actions = GUIDED_STOCK_ACTIONS | GUIDED_SERVICE_SETUP_ACTIONS | STOCK_MENU_ACTIONS
                    if (
                        pending
                        and pending.action not in _guided_actions
                        and text.lower().strip() in ["exit", "exist", "cancel", "done", "back", "stop", "close", "quit", "end"]
                    ):
                        debug_db.delete(pending)
                        debug_db.commit()
                        send_whatsapp_message(
                            phone,
                            "Closed. You can continue recording transactions."
                        )
                        return {"status": "pending_cancelled"}

                    if is_reminder_automation_text(text):
                        raise LookupError("continue_to_main_flow")

                    if pending and pending.action in ["CUSTOMER_SUMMARY_MENU", "CUSTOMER_SUMMARY_DATE"]:
                        print(f"Customer summary follow-up reached: {text}", flush=True)

                        business_owner_phone = sender_exists.phone
                        if sender_exists.parent_id:
                            owner = debug_db.query(User).filter(
                                User.id == sender_exists.parent_id
                            ).first()
                            if owner:
                                business_owner_phone = owner.phone

                        replacement_account_request = parse_customer_account_request(text)
                        if replacement_account_request:
                            pending.customer_name = replacement_account_request["name"]
                            pending.action = "CUSTOMER_SUMMARY_MENU"
                            pending.last_customer = replacement_account_request["name"]
                            debug_db.commit()

                            msg = build_customer_account_summary(
                                debug_db,
                                business_owner_phone,
                                replacement_account_request["name"],
                                period=replacement_account_request["period"],
                                target_date=replacement_account_request["target_date"],
                                include_menu=True,
                                recorded_by_id=early_visible_recorded_by_id
                            )
                            send_whatsapp_message(phone, msg)
                            return {"status": "customer_summary_replaced"}

                        normalized = text.lower().strip()
                        period_map = {
                            "1": "TODAY",
                            "today": "TODAY",
                            "2": "WEEK",
                            "week": "WEEK",
                            "this week": "WEEK",
                            "3": "MONTH",
                            "month": "MONTH",
                            "this month": "MONTH",
                            "4": "YEAR",
                            "year": "YEAR",
                            "this year": "YEAR",
                            "5": None,
                            "all": None,
                            "all time": None,
                        }

                        if pending.action == "CUSTOMER_SUMMARY_MENU" and normalized in ["6", "date", "by date"]:
                            pending.action = "CUSTOMER_SUMMARY_DATE"
                            debug_db.commit()
                            send_whatsapp_message(
                                phone,
                                f"Send date for {pending.customer_name.title()} like:\n19/05/2026"
                            )
                            return {"status": "customer_summary_date_prompt"}

                        target_date = None
                        if pending.action == "CUSTOMER_SUMMARY_DATE":
                            target_date = parse_slash_date(normalized)
                            if not target_date:
                                send_whatsapp_message(
                                    phone,
                                    "Invalid date. Send date like:\n19/05/2026"
                                )
                                return {"status": "invalid_customer_summary_date"}
                            period = "DATE"
                        else:
                            if normalized not in period_map:
                                send_whatsapp_message(
                                    phone,
                                    "Choose an account view:\n"
                                    "1. Today\n"
                                    "2. This week\n"
                                    "3. This month\n"
                                    "4. This year\n"
                                    "5. All time\n"
                                    "6. By date\n\n"
                                    "You can also send another customer, like:\n"
                                    "Ade account\n\n"
                                    "Send exit, back, done, or cancel to close."
                                )
                                return {"status": "invalid_customer_summary_option"}
                            period = period_map[normalized]

                        msg = build_customer_account_summary(
                            debug_db,
                            business_owner_phone,
                            pending.customer_name,
                            period=period,
                            target_date=target_date,
                            include_menu=True,
                            recorded_by_id=early_visible_recorded_by_id
                        )
                        pending.action = "CUSTOMER_SUMMARY_MENU"
                        debug_db.commit()
                        send_whatsapp_message(phone, msg)
                        return {"status": "customer_summary_followup"}

                    account_request = parse_customer_account_request(text)
                    if account_request:
                        print("Customer account direct handler reached", flush=True)

                        business_owner_phone = sender_exists.phone
                        if sender_exists.parent_id:
                            owner = debug_db.query(User).filter(
                                User.id == sender_exists.parent_id
                            ).first()
                            if owner:
                                business_owner_phone = owner.phone

                        debug_db.query(PendingAction).filter(
                            PendingAction.phone == phone
                        ).delete()
                        debug_db.add(
                            PendingAction(
                                phone=phone,
                                customer_name=account_request["name"],
                                action="CUSTOMER_SUMMARY_MENU",
                                last_customer=account_request["name"]
                            )
                        )
                        debug_db.commit()

                        msg = build_customer_account_summary(
                            debug_db,
                            business_owner_phone,
                            account_request["name"],
                            period=account_request["period"],
                            target_date=account_request["target_date"],
                            include_menu=True,
                            recorded_by_id=early_visible_recorded_by_id
                        )
                        send_whatsapp_message(phone, msg)
                        return {"status": "customer_summary_menu"}

                    if text.lower().strip() == "due":
                        print("Due direct handler reached", flush=True)
                        allowed, upgrade_msg = ensure_feature_allowed(
                            debug_db,
                            sender_exists,
                            "DUE_REMINDERS",
                            "Debt reminders"
                        )
                        if not allowed:
                            send_whatsapp_message(phone, upgrade_msg)
                            return {"status": "due_menu_plan_blocked"}

                        try:
                            debug_db.query(PendingAction).filter(
                                PendingAction.phone == phone
                            ).delete()
                            debug_db.add(
                                PendingAction(
                                    phone=phone,
                                    customer_name="",
                                    action="DUE_MENU",
                                    last_customer=""
                                )
                            )
                            debug_db.commit()
                        except Exception as exc:
                            debug_db.rollback()
                            print("Due pending action failed:", repr(exc), flush=True)

                        send_whatsapp_message(
                            phone,
                            "Due Reminder Menu\n\n"
                            "1. Debts due in 2 days\n"
                            "2. Debts due today\n"
                            "3. Overdue debtors\n\n"
                            "Reply with 1, 2, or 3."
                        )
                        return {"status": "due_menu"}

                    if pending and pending.action == "DUE_MENU" and text.strip() in ["1", "2", "3"]:
                        print(f"Due menu selection reached: {text}", flush=True)

                        business_owner_phone = sender_exists.phone
                        if sender_exists.parent_id:
                            owner = debug_db.query(User).filter(
                                User.id == sender_exists.parent_id
                            ).first()
                            if owner:
                                business_owner_phone = owner.phone

                        debug_db.query(ReminderMemory).filter(
                            ReminderMemory.phone == phone
                        ).delete()
                        debug_db.delete(pending)

                        if text.strip() == "1":
                            due_list = get_due_in_2_days(debug_db, business_owner_phone, early_visible_recorded_by_id)
                            title = "Due in 2 Days"
                            empty_msg = "No debts due in 2 days."
                            reminder_type = "DUE_2_DAYS"
                        elif text.strip() == "2":
                            due_list = get_due_today(debug_db, business_owner_phone, early_visible_recorded_by_id)
                            title = "Due Today"
                            empty_msg = "No debts due today."
                            reminder_type = "DUE_TODAY"
                        else:
                            due_list = get_overdue_debtors(debug_db, business_owner_phone, early_visible_recorded_by_id)
                            title = "Overdue Debtors"
                            empty_msg = "No overdue debtors."
                            reminder_type = "OVERDUE"

                        if not due_list:
                            debug_db.commit()
                            send_whatsapp_message(phone, empty_msg)
                            return {"status": "due_menu_empty"}

                        msg = f"{title}\n\n"
                        for i, debtor in enumerate(due_list, start=1):
                            memory = ReminderMemory(
                                phone=phone,
                                customer_id=debtor.get("customer_id"),
                                customer_name=debtor["name"],
                                customer_phone=debtor.get("customer_phone"),
                                balance=debtor["balance"],
                                due_date=debtor["due_date"],
                                reminder_type=reminder_type
                            )
                            debug_db.add(memory)

                            if text.strip() == "3":
                                due_date_text = debtor["due_date"].strftime("%d/%m/%Y")
                                msg += (
                                    f"{i}. {debtor['name']}\n"
                                    f"Balance: N{debtor['balance']:,}\n"
                                    f"Due: {due_date_text}\n"
                                    f"Overdue: {debtor.get('overdue_days', 0)} days\n\n"
                                )
                            else:
                                msg += f"{i}. {debtor['name'].title()}: N{debtor['balance']:,}\n"

                        debug_db.add(
                            PendingAction(
                                phone=phone,
                                customer_name="",
                                action="REMINDER_SELECTION",
                                last_customer=""
                            )
                        )
                        debug_db.commit()

                        numbers = ", ".join(str(i) for i in range(1, len(due_list) + 1))
                        msg += f"\nSend:\n{numbers} to preview the reminder before sending to customer."
                        send_whatsapp_message(phone, msg)
                        return {"status": "due_menu_selection"}
                finally:
                    debug_db.close()
    except LookupError as exc:
        if str(exc) not in ["continue_to_onboarding", "continue_to_main_flow"]:
            print("Webhook early parse lookup error:", repr(exc), flush=True)
    except Exception as exc:
        print("Webhook early parse error:", repr(exc), flush=True)


    return None


