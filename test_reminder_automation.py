from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import (
    ReminderAutomationSettings,
    ReminderMemory,
    ReminderQueue,
    ReminderSendLog,
    User,
)
from reminder_automation import (
    handle_reminder_automation_command,
    run_reminder_automation,
)


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def add_owner(db, plan="GO"):
    owner = User(
        id=f"owner-{plan}",
        name="Demo Business",
        phone=f"23480{plan.lower()}",
        subscription_plan=plan,
        subscription_status="ACTIVE",
    )
    db.add(owner)
    db.commit()
    return owner


def add_reminder(db, owner_phone, customer_phone="2348099991111"):
    reminder = ReminderMemory(
        phone=owner_phone,
        customer_name="amina",
        customer_phone=customer_phone,
        balance=12000,
        due_date=datetime.utcnow(),
        reminder_type="ORDER_BALANCE",
    )
    db.add(reminder)
    db.commit()
    return reminder


def test_go_can_queue_preview_and_owner_can_edit_send_skip():
    db = make_db()
    owner = add_owner(db, "GO")
    add_reminder(db, owner.phone)
    sent = []
    send = lambda to, message: sent.append((to, message))

    result = handle_reminder_automation_command(
        db,
        owner.phone,
        "run reminder automation",
        owner,
        send,
    )
    queue_item = db.query(ReminderQueue).first()

    assert result == {"status": "reminder_automation_run"}
    assert queue_item is not None
    assert queue_item.status == "PENDING_OWNER_CONFIRMATION"
    assert queue_item.customer_phone == "2348099991111"

    assert handle_reminder_automation_command(
        db,
        owner.phone,
        "reminder queue",
        owner,
        send,
    ) == {"status": "reminder_queue"}
    assert f"#{queue_item.id}" in sent[-1][1]

    assert handle_reminder_automation_command(
        db,
        owner.phone,
        f"edit reminder {queue_item.id} Hello Amina, please balance N12000 today.",
        owner,
        send,
    ) == {"status": "reminder_queue_edited"}
    assert queue_item.message_text == "Hello Amina, please balance N12000 today."

    assert handle_reminder_automation_command(
        db,
        owner.phone,
        f"send reminder {queue_item.id}",
        owner,
        send,
    ) == {"status": "reminder_queue_sent"}
    assert sent[-2][0] == "2348099991111"
    assert queue_item.status == "SENT"
    assert db.query(ReminderSendLog).count() == 1

    assert handle_reminder_automation_command(
        db,
        owner.phone,
        "run reminder automation",
        owner,
        send,
    ) == {"status": "reminder_automation_run"}
    assert db.query(ReminderQueue).count() == 1


def test_skip_reminder_queue_item():
    db = make_db()
    owner = add_owner(db, "GO")
    add_reminder(db, owner.phone)
    sent = []
    send = lambda to, message: sent.append((to, message))

    run_reminder_automation(db, owner.phone, send)
    queue_item = db.query(ReminderQueue).first()

    assert handle_reminder_automation_command(
        db,
        owner.phone,
        f"skip reminder {queue_item.id}",
        owner,
        send,
    ) == {"status": "reminder_queue_skipped"}
    assert queue_item.status == "SKIPPED"


def test_basic_plan_can_use_reminder_automation():
    db = make_db()
    owner = add_owner(db, "BASIC")
    add_reminder(db, owner.phone)
    sent = []

    result = handle_reminder_automation_command(
        db,
        owner.phone,
        "run reminder automation",
        owner,
        lambda to, message: sent.append((to, message)),
    )

    assert result == {"status": "reminder_automation_run"}


def test_auto_send_is_pro_only_and_sends_for_pro():
    db = make_db()
    go_owner = add_owner(db, "GO")
    add_reminder(db, go_owner.phone)
    sent = []

    assert handle_reminder_automation_command(
        db,
        go_owner.phone,
        "auto reminders on",
        go_owner,
        lambda to, message: sent.append((to, message)),
    ) == {"status": "reminder_auto_send_pro_required"}

    pro_owner = add_owner(db, "PRO")
    add_reminder(db, pro_owner.phone, "2348099992222")
    settings = ReminderAutomationSettings(owner_phone=pro_owner.phone, auto_send_enabled=True)
    db.add(settings)
    db.commit()
    sent = []

    result = run_reminder_automation(db, pro_owner.phone, lambda to, message: sent.append((to, message)))

    assert result["sent"] == 1
    assert sent[0][0] == "2348099992222"
    assert db.query(ReminderSendLog).filter(
        ReminderSendLog.owner_phone == pro_owner.phone
    ).count() == 1


if __name__ == "__main__":
    test_go_can_queue_preview_and_owner_can_edit_send_skip()
    test_skip_reminder_queue_item()
    test_basic_plan_cannot_use_reminder_automation()
    test_auto_send_is_pro_only_and_sends_for_pro()
    print("reminder automation smoke tests passed")
