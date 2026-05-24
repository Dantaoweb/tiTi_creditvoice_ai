from models import PendingAction, ReminderMemory
from parser import build_reminder_text
from reports import get_due_in_2_days, get_due_today, get_overdue_debtors
from subscriptions import ensure_feature_allowed


def build_due_menu_message():
    return (
        "Due Reminder Menu\n\n"
        "1. Due in 2 Days\n"
        "2. Due Today\n"
        "3. Overdue Debtors\n\n"
        "Reply with:\n1, 2, or 3"
    )


def save_due_reminders(db, phone, due_list, reminder_type):
    db.query(ReminderMemory).filter(
        ReminderMemory.phone == phone
    ).delete()

    for debtor in due_list:
        db.add(
            ReminderMemory(
                phone=phone,
                customer_id=debtor["customer_id"],
                customer_name=debtor["name"],
                customer_phone=debtor.get("customer_phone"),
                balance=debtor["balance"],
                due_date=debtor["due_date"],
                reminder_type=reminder_type,
            )
        )


def format_due_selection(selection, due_list):
    if selection == "1":
        title = "Due in 2 Days"
        empty_msg = "No debts due in 2 days."
        reminder_type = "DUE_2_DAYS"
    elif selection == "2":
        title = "Due Today"
        empty_msg = "No debts due today."
        reminder_type = "DUE_TODAY"
    else:
        title = "Overdue Debtors"
        empty_msg = "No overdue debtors."
        reminder_type = "OVERDUE"

    if not due_list:
        return reminder_type, None, empty_msg

    msg = f"{title}\n\n"
    for index, debtor in enumerate(due_list, start=1):
        if selection == "3":
            due_date_text = debtor["due_date"].strftime("%d/%m/%Y")
            msg += (
                f"{index}. {debtor['name']}\n"
                f"Balance: N{debtor['balance']:,}\n"
                f"Due: {due_date_text}\n"
                f"Overdue: {debtor.get('overdue_days', 0)} days\n\n"
            )
        else:
            msg += f"{index}. {debtor['name']} -> N{debtor['balance']:,}\n"

    numbers = ", ".join(str(index) for index in range(1, len(due_list) + 1))
    msg += f"\nSend:\n{numbers} to preview the reminder before sending to customer."
    return reminder_type, msg, empty_msg


def handle_due_menu_selection(
    db,
    phone,
    selection,
    business_owner_phone,
    visible_recorded_by_id,
    pending,
    send_message,
):
    if selection == "1":
        due_list = get_due_in_2_days(db, business_owner_phone, visible_recorded_by_id)
    elif selection == "2":
        due_list = get_due_today(db, business_owner_phone, visible_recorded_by_id)
    elif selection == "3":
        due_list = get_overdue_debtors(db, business_owner_phone, visible_recorded_by_id)
    else:
        return None

    reminder_type, msg, empty_msg = format_due_selection(selection, due_list)
    save_due_reminders(db, phone, due_list, reminder_type)

    if not due_list:
        db.delete(pending)
        db.commit()
        send_message(phone, empty_msg)
        status_map = {"1": "due_2_days", "2": "due_today", "3": "overdue_menu"}
        return {"status": status_map[selection]}

    db.add(PendingAction(phone=phone, action="REMINDER_SELECTION"))
    db.delete(pending)
    db.commit()
    send_message(phone, msg)
    status_map = {"1": "due_2_days", "2": "due_today", "3": "overdue_menu"}
    return {"status": status_map[selection]}


def handle_reminder_pending(
    db,
    phone,
    text,
    pending,
    business_owner_phone,
    visible_recorded_by_id,
    send_message,
):
    normalized = text.lower().strip()

    if pending.action == "DUE_MENU":
        return handle_due_menu_selection(
            db,
            phone,
            text.strip(),
            business_owner_phone,
            visible_recorded_by_id,
            pending,
            send_message,
        )

    if pending.action == "REMINDER_SELECTION":
        if not text.isdigit():
            send_message(phone, "Reply with reminder number.\nExample: 1")
            return {"status": "invalid_reminder_selection"}

        index = int(text)
        reminders = db.query(ReminderMemory).filter(
            ReminderMemory.phone == phone
        ).all()

        if index < 1 or index > len(reminders):
            send_message(phone, "Reminder number not found.")
            return {"status": "reminder_not_found"}

        reminder = reminders[index - 1]
        preview = build_reminder_text(reminder)

        if reminder.customer_phone:
            confirm_msg = (
                f"Preview reminder for {reminder.customer_name.title()}:\n\n"
                f"{preview}\n\n"
                f"Reply YES to send this reminder to {reminder.customer_name.title()} "
                f"at {reminder.customer_phone}, or EDIT to cancel."
            )
        else:
            confirm_msg = (
                f"Preview reminder for {reminder.customer_name.title()}:\n\n"
                f"{preview}\n\n"
                "Customer phone is not set yet.\n"
                "To send this reminder, set the phone first:\n\n"
                f"{reminder.customer_name} phone 08012345678\n\n"
                "I will keep this reminder open. After setting the phone, reply YES to send."
            )

        pending.action = "REMINDER_CONFIRM"
        pending.reminder_id = reminder.id
        db.commit()
        send_message(phone, confirm_msg)
        return {"status": "reminder_preview"}

    if pending.action == "REMINDER_CONFIRM":
        if normalized == "yes":
            reminder = db.query(ReminderMemory).filter(
                ReminderMemory.id == pending.reminder_id
            ).first()

            if not reminder:
                send_message(phone, "Reminder not found. Please select again.")
                db.delete(pending)
                db.commit()
                return {"status": "reminder_missing"}

            if not reminder.customer_phone:
                send_message(
                    phone,
                    f"Customer phone is not set for {reminder.customer_name.title()}.\n\n"
                    "Set it using:\n"
                    f"{reminder.customer_name} phone 08012345678\n\n"
                    "I will keep this reminder open. After setting the phone, reply YES again."
                )
                return {"status": "waiting_for_phone"}

            reminder_text = build_reminder_text(reminder)
            send_message(reminder.customer_phone, reminder_text)
            send_message(
                phone,
                f"Reminder sent to {reminder.customer_name.title()} ({reminder.customer_phone})."
            )
            db.delete(pending)
            db.commit()
            return {"status": "reminder_sent"}

        if normalized == "edit":
            db.delete(pending)
            db.commit()
            send_message(phone, "Reminder cancelled. Reply DUE to start again.")
            return {"status": "reminder_cancelled"}

        send_message(phone, "Reply YES to send the reminder to the customer or EDIT to cancel.")
        return {"status": "reminder_confirm_prompt"}

    return None


def handle_reminder_command(db, phone, parsed, user, send_message):
    command_type = parsed.get("type")

    if command_type == "REMIND":
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "DUE_REMINDERS", "Debt reminders")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "reminder_plan_blocked"}

        parts = parsed["text"].split()
        if len(parts) != 2 or not parts[1].isdigit():
            send_message(phone, "Use:\nREMIND 1")
            return {"status": "invalid_remind"}

        index = int(parts[1])
        reminders = db.query(ReminderMemory).filter(
            ReminderMemory.phone == phone
        ).all()

        if index < 1 or index > len(reminders):
            send_message(phone, "Reminder number not found.")
            return {"status": "reminder_not_found"}

        reminder = reminders[index - 1]
        send_message(phone, build_reminder_text(reminder))
        return {"status": "remind"}

    if command_type == "DUE_MENU":
        allowed, upgrade_msg = ensure_feature_allowed(db, user, "DUE_REMINDERS", "Debt reminders")
        if not allowed:
            send_message(phone, upgrade_msg)
            return {"status": "due_menu_plan_blocked"}

        db.query(PendingAction).filter(
            PendingAction.phone == phone
        ).delete()
        db.add(PendingAction(phone=phone, action="DUE_MENU"))
        db.commit()

        send_message(phone, build_due_menu_message())
        return {"status": "due_menu"}

    return None
