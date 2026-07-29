from datetime import datetime, timezone


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

from models import (
    ReminderAutomationSettings,
    ReminderMemory,
    ReminderQueue,
    ReminderSendLog,
)
from plans import PLAN_PRO
from subscriptions import ensure_feature_allowed, get_business_subscription


def get_or_create_reminder_settings(db, owner_phone):
    settings = db.query(ReminderAutomationSettings).filter(
        ReminderAutomationSettings.owner_phone == owner_phone
    ).first()
    if settings:
        return settings

    settings = ReminderAutomationSettings(owner_phone=owner_phone)
    db.add(settings)
    db.flush()
    return settings


def reminder_status_message(settings):
    return (
        "Reminder Automation\n\n"
        f"Preview: {'ON' if settings.preview_enabled else 'OFF'}\n"
        f"Auto-send: {'ON' if settings.auto_send_enabled else 'OFF'}\n"
        f"Time: {settings.reminder_time or '08:00'}\n\n"
        "Commands:\n"
        "reminder preview on\n"
        "reminder preview off\n"
        "auto reminders on\n"
        "auto reminders off\n"
        "reminder time 8am\n"
        "run reminder automation\n"
        "reminder queue"
    )


def today_key():
    return _utcnow().strftime("%Y-%m-%d")


def already_sent_today(db, owner_phone, reminder):
    return db.query(ReminderSendLog).filter(
        ReminderSendLog.owner_phone == owner_phone,
        ReminderSendLog.customer_phone == reminder.customer_phone,
        ReminderSendLog.reminder_type == reminder.reminder_type,
        ReminderSendLog.source_type == "REMINDER_MEMORY",
        ReminderSendLog.source_id == reminder.id,
        ReminderSendLog.sent_date == today_key(),
    ).first() is not None


def queued_reminder_exists(db, owner_phone, reminder):
    return db.query(ReminderQueue).filter(
        ReminderQueue.owner_phone == owner_phone,
        ReminderQueue.source_type == "REMINDER_MEMORY",
        ReminderQueue.source_id == reminder.id,
        ReminderQueue.status.in_(["PENDING_OWNER_CONFIRMATION", "EDITING"]),
    ).first() is not None


def build_queue_message(reminder):
    name = (reminder.customer_name or "customer").title()
    due = reminder.due_date.strftime("%d/%m/%Y") if reminder.due_date else "today"
    if reminder.reminder_type in ["DUE_TODAY", "ORDER_BALANCE", "CUSTOMER_ORDER_BALANCE"]:
        return (
            f"Hello {name},\n\n"
            f"This is a reminder that your outstanding balance is N{reminder.balance:,}.\n"
            f"Due: {due}\n\n"
            "Thank you."
        )
    return (
        f"Hello {name},\n\n"
        f"This is a reminder that your outstanding balance of N{reminder.balance:,} "
        f"will be due on {due}.\n\n"
        "Thank you."
    )


def queue_due_reminder(db, owner_phone, reminder):
    queue_item = ReminderQueue(
        owner_phone=owner_phone,
        customer_phone=reminder.customer_phone,
        customer_name=reminder.customer_name,
        balance=reminder.balance,
        due_date=reminder.due_date,
        reminder_type=reminder.reminder_type,
        source_type="REMINDER_MEMORY",
        source_id=reminder.id,
        message_text=build_queue_message(reminder),
    )
    db.add(queue_item)
    db.flush()
    return queue_item


def create_send_log(db, owner_phone, queue_item):
    db.add(
        ReminderSendLog(
            owner_phone=owner_phone,
            customer_phone=queue_item.customer_phone,
            reminder_type=queue_item.reminder_type,
            source_type=queue_item.source_type,
            source_id=queue_item.source_id,
            sent_date=today_key(),
        )
    )


def queue_debtor_reminders(db, owner_phone, recorded_by_id=None):
    """Generate reminder-queue items from the owner's CURRENT unpaid debtors —
    the live source of truth — so every debtor with a phone gets a message, not
    only those that happen to be in ReminderMemory. Deduped per customer per day.
    Returns {"queued": n, "debtors": total, "no_phone": k}."""
    from reports import get_unpaid_debtors
    debtors, _total = get_unpaid_debtors(db, owner_phone, recorded_by_id)
    queued = 0
    no_phone = 0
    for d in debtors:
        phone = d.get("customer_phone")
        cid = d.get("customer_id")
        if (d.get("balance") or 0) <= 0 or cid is None:
            continue
        if not phone:
            no_phone += 1
            continue
        # Already pending for this customer, or already sent today → skip.
        if db.query(ReminderQueue).filter(
            ReminderQueue.owner_phone == owner_phone,
            ReminderQueue.source_type == "DEBTOR",
            ReminderQueue.source_id == cid,
            ReminderQueue.status.in_(["PENDING_OWNER_CONFIRMATION", "EDITING"]),
        ).first():
            continue
        if db.query(ReminderSendLog).filter(
            ReminderSendLog.owner_phone == owner_phone,
            ReminderSendLog.source_type == "DEBTOR",
            ReminderSendLog.source_id == cid,
            ReminderSendLog.sent_date == today_key(),
        ).first():
            continue

        due = d.get("due_date")
        name = (d.get("name") or "customer").title()
        due_str = due.strftime("%d/%m/%Y") if due else None
        msg = (
            f"Hello {name},\n\n"
            f"This is a friendly reminder that your outstanding balance is "
            f"N{int(d['balance']):,}."
            + (f"\nDue date: {due_str}" if due_str else "")
            + "\n\nKindly settle when you can. Thank you."
        )
        db.add(ReminderQueue(
            owner_phone=owner_phone,
            customer_phone=phone,
            customer_name=d.get("name"),
            balance=int(d["balance"]),
            due_date=due,
            reminder_type="OVERDUE" if d.get("overdue") else "DUE",
            source_type="DEBTOR",
            source_id=cid,
            message_text=msg,
            status="PENDING_OWNER_CONFIRMATION",
        ))
        queued += 1
    db.commit()
    return {"queued": queued, "debtors": len(debtors), "no_phone": no_phone}


def run_reminder_automation(db, owner_phone, send_message, dry_run=False):
    settings = get_or_create_reminder_settings(db, owner_phone)
    reminders = db.query(ReminderMemory).filter(
        ReminderMemory.phone == owner_phone,
        ReminderMemory.balance > 0,
    ).order_by(
        ReminderMemory.due_date.asc()
    ).limit(50).all()

    queued = 0
    sent = 0
    skipped = 0
    previews = []

    for reminder in reminders:
        if not reminder.customer_phone:
            skipped += 1
            continue
        if already_sent_today(db, owner_phone, reminder):
            skipped += 1
            continue
        if queued_reminder_exists(db, owner_phone, reminder):
            skipped += 1
            continue
        if dry_run:
            previews.append(build_queue_message(reminder))
            continue

        queue_item = queue_due_reminder(db, owner_phone, reminder)
        queued += 1
        if settings.auto_send_enabled:
            send_message(queue_item.customer_phone, queue_item.message_text)
            queue_item.status = "SENT"
            create_send_log(db, owner_phone, queue_item)
            sent += 1

    db.commit()
    return {
        "queued": queued,
        "sent": sent,
        "skipped": skipped,
        "previews": previews,
    }


def reminder_queue_message(db, owner_phone):
    queue = db.query(ReminderQueue).filter(
        ReminderQueue.owner_phone == owner_phone,
        ReminderQueue.status.in_(["PENDING_OWNER_CONFIRMATION", "EDITING"]),
    ).order_by(
        ReminderQueue.created_at.asc()
    ).limit(10).all()
    if not queue:
        return "No reminder preview waiting."

    msg = "Reminder Queue\n\n"
    for item in queue:
        msg += (
            f"#{item.id} - {item.customer_name.title()}\n"
            f"Phone: {item.customer_phone or 'Not set'}\n"
            f"Balance: N{item.balance:,}\n"
            f"Preview:\n{item.message_text}\n\n"
            f"Reply: send reminder {item.id}, skip reminder {item.id}, or edit reminder {item.id} your message\n\n"
        )
    return msg.strip()


def handle_reminder_queue_action(db, phone, clean, normalized, owner_phone, send_message):
    send_match = normalized.startswith("send reminder ")
    skip_match = normalized.startswith("skip reminder ")
    edit_match = normalized.startswith("edit reminder ")
    if not (send_match or skip_match or edit_match):
        return None

    parts = normalized.split(maxsplit=2)
    if len(parts) < 3 or not parts[2].split(maxsplit=1)[0].isdigit():
        send_message(phone, "Use: send reminder 1, skip reminder 1, or edit reminder 1 your message")
        return {"status": "reminder_queue_invalid"}

    reminder_id_text, _, edit_text = parts[2].partition(" ")
    clean_parts = clean.split(maxsplit=3)
    clean_edit_text = clean_parts[3] if len(clean_parts) == 4 else ""
    reminder_id = int(reminder_id_text)
    item = db.query(ReminderQueue).filter(
        ReminderQueue.id == reminder_id,
        ReminderQueue.owner_phone == owner_phone,
    ).first()
    if not item:
        send_message(phone, f"Reminder #{reminder_id} not found.")
        return {"status": "reminder_queue_not_found"}

    if skip_match:
        item.status = "SKIPPED"
        item.updated_at = _utcnow()
        db.commit()
        send_message(phone, f"Reminder #{item.id} skipped.")
        return {"status": "reminder_queue_skipped"}

    if edit_match:
        if not clean_edit_text.strip():
            send_message(phone, f"Send: edit reminder {item.id} your new reminder message")
            return {"status": "reminder_queue_edit_missing"}
        item.message_text = clean_edit_text.strip()
        item.status = "PENDING_OWNER_CONFIRMATION"
        item.updated_at = _utcnow()
        db.commit()
        send_message(
            phone,
            f"Reminder #{item.id} updated.\n\n"
            f"{item.message_text}\n\n"
            f"Reply: send reminder {item.id}"
        )
        return {"status": "reminder_queue_edited"}

    if not item.customer_phone:
        send_message(phone, f"Customer phone is missing for reminder #{item.id}.")
        return {"status": "reminder_queue_phone_missing"}
    if item.status == "SENT":
        send_message(phone, f"Reminder #{item.id} was already sent.")
        return {"status": "reminder_queue_already_sent"}
    send_message(item.customer_phone, item.message_text)
    item.status = "SENT"
    item.updated_at = _utcnow()
    create_send_log(db, owner_phone, item)
    db.commit()
    send_message(phone, f"Reminder #{item.id} sent to {item.customer_name.title()}.")
    return {"status": "reminder_queue_sent"}


def handle_reminder_automation_command(db, phone, text, user, send_message):
    if not user:
        return None
    clean = (text or "").strip()
    normalized = clean.lower()
    if not normalized.startswith((
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
    )):
        return None

    subscription = get_business_subscription(db, user)
    owner = subscription["owner"] or user
    allowed, upgrade_msg = ensure_feature_allowed(
        db,
        owner,
        "REMINDER_AUTOMATION",
        "automatic reminder previews",
    )
    if not allowed:
        send_message(phone, upgrade_msg)
        return {"status": "reminder_automation_upgrade_required"}

    settings = get_or_create_reminder_settings(db, owner.phone)

    queue_action = handle_reminder_queue_action(
        db,
        phone,
        clean,
        normalized,
        owner.phone,
        send_message,
    )
    if queue_action:
        return queue_action

    if normalized in ["reminder automation", "reminder automation status"]:
        send_message(phone, reminder_status_message(settings))
        return {"status": "reminder_automation_status"}

    if normalized in ["reminder preview on", "reminder preview off"]:
        settings.preview_enabled = normalized.endswith("on")
        settings.updated_at = _utcnow()
        db.commit()
        send_message(phone, f"Reminder preview is {'ON' if settings.preview_enabled else 'OFF'}.")
        return {"status": "reminder_preview_updated"}

    if normalized in ["auto reminders on", "auto reminders off"]:
        if normalized.endswith("on") and subscription["plan"] != PLAN_PRO:
            send_message(phone, "Auto-send reminders are for PRO. GO can queue previews for owner confirmation.")
            return {"status": "reminder_auto_send_pro_required"}
        settings.auto_send_enabled = normalized.endswith("on")
        settings.updated_at = _utcnow()
        db.commit()
        send_message(phone, f"Auto reminders are {'ON' if settings.auto_send_enabled else 'OFF'}.")
        return {"status": "reminder_auto_send_updated"}

    if normalized.startswith("reminder time "):
        settings.reminder_time = clean.split(" ", 2)[2].strip()
        settings.updated_at = _utcnow()
        db.commit()
        send_message(phone, f"Reminder time saved: {settings.reminder_time}")
        return {"status": "reminder_time_updated"}

    if normalized == "preview reminder automation":
        result = run_reminder_automation(db, owner.phone, send_message, dry_run=True)
        if not result["previews"]:
            send_message(phone, "No reminders ready for preview.")
        else:
            send_message(phone, "Preview reminder automation\n\n" + "\n\n---\n\n".join(result["previews"][:5]))
        return {"status": "reminder_automation_preview"}

    if normalized == "run reminder automation":
        result = run_reminder_automation(db, owner.phone, send_message)
        summary = (
            "Reminder automation run complete.\n\n"
            f"Queued: {result['queued']}\n"
            f"Sent: {result['sent']}\n"
            f"Skipped: {result['skipped']}\n\n"
            "Send reminder queue to review previews."
        )
        send_message(phone, summary)
        # Also send supplier due payments for the next 3 days
        try:
            from inventory_suppliers import build_supplier_due_message
            supplier_msg = build_supplier_due_message(db, owner.phone, days=3)
            if "No supplier payment" not in supplier_msg:
                send_message(phone, supplier_msg)
        except Exception:
            pass
        return {"status": "reminder_automation_run"}

    if normalized == "reminder queue":
        send_message(phone, reminder_queue_message(db, owner.phone))
        return {"status": "reminder_queue"}

    return None
