from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from customer_automation import (
    get_or_create_automation_settings,
    handle_automation_owner_command,
    handle_customer_automation_message,
)
from database import Base
from models import (
    CustomerConversation,
    InventoryItem,
    ReminderMemory,
    SalesOrder,
    SalesOrderPayment,
    User,
)


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def add_owner(db, plan="GO"):
    owner = User(
        id="owner-id",
        name="Demo Stores",
        phone="2348012345678",
        subscription_plan=plan,
        subscription_status="ACTIVE",
    )
    db.add(owner)
    db.commit()
    return owner


def add_stock(db, owner_phone="2348012345678"):
    item = InventoryItem(
        owner_phone=owner_phone,
        name="black shoe",
        quantity=5,
        unit="pairs",
        selling_price=20000,
        size="42",
        color="black",
        payment_modes="bank transfer",
        delivery_options="pickup or dispatch",
        is_available=True,
    )
    db.add(item)
    db.commit()
    return item


def test_owner_can_enable_customer_bot_on_go_plan():
    db = make_db()
    owner = add_owner(db, plan="GO")
    sent = []

    result = handle_automation_owner_command(
        db,
        owner.phone,
        "bot on",
        owner,
        lambda to, message: sent.append((to, message)),
    )

    settings = get_or_create_automation_settings(db, owner.phone)

    assert result == {"status": "automation_bot_on"}
    assert settings.bot_enabled is True
    assert "shop 2348012345678" in sent[-1][1]


def test_basic_owner_is_asked_to_upgrade_for_customer_bot():
    db = make_db()
    owner = add_owner(db, plan="BASIC")
    sent = []

    result = handle_automation_owner_command(
        db,
        owner.phone,
        "bot on",
        owner,
        lambda to, message: sent.append((to, message)),
    )

    assert result == {"status": "automation_upgrade_required"}
    assert "upgrade to go" in sent[-1][1].lower()


def test_customer_can_start_and_get_inventory_answer():
    db = make_db()
    owner = add_owner(db)
    add_stock(db)
    settings = get_or_create_automation_settings(db, owner.phone)
    settings.bot_enabled = True
    db.commit()
    sent = []
    send = lambda to, message: sent.append((to, message))

    assert handle_customer_automation_message(
        db,
        "2348099990000",
        "shop 2348012345678",
        send,
    ) == {"status": "customer_bot_welcome"}

    assert handle_customer_automation_message(
        db,
        "2348099990000",
        "how much is black shoe",
        send,
    ) == {"status": "customer_bot_product_answered"}

    assert "Welcome to Demo Stores" in sent[0][1]
    assert "Price: N20,000" in sent[-1][1]
    assert "Available: 5 pairs" in sent[-1][1]
    assert "Size: 42" in sent[-1][1]


def test_customer_part_payment_creates_pending_evidence_then_owner_confirms():
    db = make_db()
    owner = add_owner(db)
    item = add_stock(db)
    settings = get_or_create_automation_settings(db, owner.phone)
    settings.bot_enabled = True
    settings.auto_order_enabled = True
    settings.allow_part_payment = True
    db.commit()
    sent = []
    send = lambda to, message: sent.append((to, message))

    handle_customer_automation_message(db, "2348099990001", "shop 2348012345678", send)
    handle_customer_automation_message(db, "2348099990001", "black shoe", send)
    result = handle_customer_automation_message(
        db,
        "2348099990001",
        "order 2 paid 10000",
        send,
    )

    order = db.query(SalesOrder).first()
    payment = db.query(SalesOrderPayment).first()
    reminders = db.query(ReminderMemory).all()

    assert result == {"status": "customer_bot_order_created"}
    assert order.total_amount == 40000
    assert order.paid_amount == 0
    assert order.balance_amount == 40000
    assert order.payment_status == "PAYMENT_EVIDENCE_RECEIVED"
    assert payment.amount == 10000
    assert payment.status == "PENDING_OWNER_CONFIRMATION"
    assert len(reminders) == 0
    assert item.id is not None
    assert sent[-2][0] == "2348099990001"
    assert sent[-1][0] == owner.phone

    confirm = handle_automation_owner_command(
        db,
        owner.phone,
        f"confirm payment {order.id}",
        owner,
        send,
    )
    reminders = db.query(ReminderMemory).all()
    assert confirm == {"status": "automation_payment_confirmed"}
    assert order.paid_amount == 10000
    assert order.balance_amount == 30000
    assert order.payment_status == "PART_PAID"
    assert payment.status == "OWNER_CONFIRMED"
    assert len(reminders) == 2
    assert sent[-1][0] == "2348099990001"
    assert "Receipt for order" in sent[-1][1]
    assert "Paid: N10,000" in sent[-1][1]
    assert "Balance: N30,000" in sent[-1][1]


def test_owner_can_manage_products_and_bot_settings_from_whatsapp():
    db = make_db()
    owner = add_owner(db)
    sent = []
    send = lambda to, message: sent.append((to, message))

    assert handle_automation_owner_command(
        db,
        owner.phone,
        "add product black shoe price 20000 qty 5 unit pairs size 42 color black",
        owner,
        send,
    ) == {"status": "automation_product_saved"}

    item = db.query(InventoryItem).filter(InventoryItem.name == "black shoe").first()
    assert item.selling_price == 20000
    assert item.quantity == 5
    assert item.unit == "pairs"
    assert item.size == "42"
    assert item.color == "black"

    assert handle_automation_owner_command(
        db,
        owner.phone,
        "set price black shoe 25000",
        owner,
        send,
    ) == {"status": "automation_product_price_updated"}
    assert item.selling_price == 25000

    assert handle_automation_owner_command(
        db,
        owner.phone,
        "payment mode bank transfer or POS",
        owner,
        send,
    ) == {"status": "automation_payment_mode_updated"}
    assert handle_automation_owner_command(
        db,
        owner.phone,
        "delivery note dispatch available in Lagos",
        owner,
        send,
    ) == {"status": "automation_delivery_note_updated"}
    assert handle_automation_owner_command(
        db,
        owner.phone,
        "pickup address 12 Allen Avenue",
        owner,
        send,
    ) == {"status": "automation_pickup_address_updated"}
    assert handle_automation_owner_command(
        db,
        owner.phone,
        "business hours 8am to 7pm",
        owner,
        send,
    ) == {"status": "automation_business_hours_updated"}
    assert handle_automation_owner_command(
        db,
        owner.phone,
        "min deposit 50%",
        owner,
        send,
    ) == {"status": "automation_min_deposit_updated"}

    settings = get_or_create_automation_settings(db, owner.phone)
    assert settings.payment_modes == "bank transfer or POS"
    assert settings.delivery_note == "dispatch available in Lagos"
    assert settings.pickup_address == "12 Allen Avenue"
    assert settings.business_hours == "8am to 7pm"
    assert settings.min_deposit_percent == 50

    assert handle_automation_owner_command(
        db,
        owner.phone,
        "product black shoe off",
        owner,
        send,
    ) == {"status": "automation_product_availability_updated"}
    assert item.is_available is False


def test_owner_can_manage_customer_bot_orders():
    db = make_db()
    owner = add_owner(db)
    add_stock(db)
    settings = get_or_create_automation_settings(db, owner.phone)
    settings.bot_enabled = True
    settings.auto_order_enabled = True
    db.commit()
    sent = []
    send = lambda to, message: sent.append((to, message))

    handle_customer_automation_message(db, "2348099990003", "shop 2348012345678", send)
    handle_customer_automation_message(db, "2348099990003", "black shoe", send)
    handle_customer_automation_message(db, "2348099990003", "order 1 paid 5000", send)

    order = db.query(SalesOrder).first()

    assert handle_automation_owner_command(
        db,
        owner.phone,
        "orders",
        owner,
        send,
    ) == {"status": "automation_orders"}
    assert f"#{order.id}" in sent[-1][1]

    assert handle_automation_owner_command(
        db,
        owner.phone,
        f"confirm order {order.id}",
        owner,
        send,
    ) == {"status": "automation_order_updated"}
    assert order.status == "CONFIRMED"
    assert sent[-1][0] == "2348099990003"
    assert "has been confirmed" in sent[-1][1]

    assert handle_automation_owner_command(
        db,
        owner.phone,
        f"paid order {order.id} 15000",
        owner,
        send,
    ) == {"status": "automation_order_payment_evidence_added"}
    assert order.paid_amount == 0
    assert order.balance_amount == 20000
    assert order.payment_status == "PAYMENT_EVIDENCE_RECEIVED"

    assert handle_automation_owner_command(
        db,
        owner.phone,
        f"reject payment {order.id}",
        owner,
        send,
    ) == {"status": "automation_payment_rejected"}
    assert order.paid_amount == 0
    assert order.balance_amount == 20000
    assert order.payment_status == "PAYMENT_REJECTED"
    assert sent[-1][0] == "2348099990003"
    assert "could not be confirmed" in sent[-1][1]

    assert handle_automation_owner_command(
        db,
        owner.phone,
        f"paid order {order.id} 20000",
        owner,
        send,
    ) == {"status": "automation_order_payment_evidence_added"}

    assert handle_automation_owner_command(
        db,
        owner.phone,
        f"confirm payment {order.id}",
        owner,
        send,
    ) == {"status": "automation_payment_confirmed"}
    assert order.paid_amount == 20000
    assert order.balance_amount == 0
    assert order.payment_status == "PAID"
    assert sent[-1][0] == "2348099990003"
    assert "Your payment has been confirmed" in sent[-1][1]

    assert handle_automation_owner_command(
        db,
        owner.phone,
        f"deliver order {order.id}",
        owner,
        send,
    ) == {"status": "automation_order_updated"}
    assert order.delivery_status == "OUT_FOR_DELIVERY"
    assert sent[-1][0] == "2348099990003"
    assert "out for delivery" in sent[-1][1]

    assert handle_automation_owner_command(
        db,
        owner.phone,
        f"order {order.id} delivered",
        owner,
        send,
    ) == {"status": "automation_order_updated"}
    assert order.status == "COMPLETED"
    assert order.delivery_status == "DELIVERED"
    assert sent[-1][0] == "2348099990003"
    assert "marked delivered" in sent[-1][1]


def test_interested_customers_and_follow_up():
    db = make_db()
    owner = add_owner(db)
    add_stock(db)
    settings = get_or_create_automation_settings(db, owner.phone)
    settings.bot_enabled = True
    db.commit()
    sent = []
    send = lambda to, message: sent.append((to, message))

    handle_customer_automation_message(db, "2348099990005", "shop 2348012345678", send)
    handle_customer_automation_message(db, "2348099990005", "how much black shoe", send)

    assert handle_automation_owner_command(
        db,
        owner.phone,
        "interested customers",
        owner,
        send,
    ) == {"status": "automation_interested_customers"}
    assert "2348099990005" in sent[-1][1]
    assert "Black Shoe" in sent[-1][1]

    assert handle_automation_owner_command(
        db,
        owner.phone,
        "follow up black shoe",
        owner,
        send,
    ) == {"status": "automation_followup_sent"}
    assert sent[-2][0] == "2348099990005"
    assert "Black Shoe is still available" in sent[-2][1]
    assert sent[-1][0] == owner.phone
    assert "Follow-up sent to 1" in sent[-1][1]


def test_daily_assistant_commands():
    db = make_db()
    owner = add_owner(db)
    item = add_stock(db)
    item.low_stock_alert = 10
    settings = get_or_create_automation_settings(db, owner.phone)
    settings.bot_enabled = True
    settings.auto_order_enabled = True
    db.commit()
    sent = []
    send = lambda to, message: sent.append((to, message))

    handle_customer_automation_message(db, "2348099990006", "shop 2348012345678", send)
    handle_customer_automation_message(db, "2348099990006", "black shoe", send)
    handle_customer_automation_message(db, "2348099990006", "order 1 paid 5000 ref a1", send)
    order = db.query(SalesOrder).first()

    assert handle_automation_owner_command(
        db,
        owner.phone,
        "today",
        owner,
        send,
    ) == {"status": "automation_today"}
    assert "Payment evidence to confirm: 1" in sent[-1][1]
    assert "Low stock items: 1" in sent[-1][1]

    assert handle_automation_owner_command(
        db,
        owner.phone,
        "pending payments",
        owner,
        send,
    ) == {"status": "automation_pending_payments"}
    assert f"Order #{order.id}" in sent[-1][1]
    assert "Amount claimed: N5,000" in sent[-1][1]

    handle_automation_owner_command(db, owner.phone, f"confirm payment {order.id}", owner, send)
    handle_automation_owner_command(db, owner.phone, f"confirm order {order.id}", owner, send)

    assert handle_automation_owner_command(
        db,
        owner.phone,
        "deliveries",
        owner,
        send,
    ) == {"status": "automation_deliveries"}
    assert f"Order #{order.id}" in sent[-1][1]

    assert handle_automation_owner_command(
        db,
        owner.phone,
        "low stock",
        owner,
        send,
    ) == {"status": "automation_low_stock"}
    assert "Black Shoe" in sent[-1][1]

    assert handle_automation_owner_command(
        db,
        owner.phone,
        "send reminders",
        owner,
        send,
    ) == {"status": "automation_reminders_sent"}
    assert sent[-2][0] == "2348099990006"
    assert "order balance is N15,000" in sent[-2][1]
    assert "Order balance reminders sent: 1" in sent[-1][1]


def test_minimum_deposit_blocks_low_customer_payment():
    db = make_db()
    owner = add_owner(db)
    add_stock(db)
    settings = get_or_create_automation_settings(db, owner.phone)
    settings.bot_enabled = True
    settings.auto_order_enabled = True
    settings.min_deposit_percent = 50
    db.commit()
    sent = []
    send = lambda to, message: sent.append((to, message))

    handle_customer_automation_message(db, "2348099990004", "shop 2348012345678", send)
    handle_customer_automation_message(db, "2348099990004", "black shoe", send)
    result = handle_customer_automation_message(
        db,
        "2348099990004",
        "order 1 paid 5000",
        send,
    )

    assert result == {"status": "customer_bot_deposit_too_low"}
    assert db.query(SalesOrder).count() == 0
    assert "Minimum deposit is 50%" in sent[-1][1]


def test_uncertain_product_alerts_owner_and_takeover_stops_bot():
    db = make_db()
    owner = add_owner(db)
    settings = get_or_create_automation_settings(db, owner.phone)
    settings.bot_enabled = True
    db.commit()
    sent = []
    send = lambda to, message: sent.append((to, message))

    handle_customer_automation_message(db, "2348099990002", "shop 2348012345678", send)
    result = handle_customer_automation_message(db, "2348099990002", "do you have red cap", send)

    conversation = db.query(CustomerConversation).filter(
        CustomerConversation.customer_phone == "2348099990002"
    ).first()

    assert result == {"status": "customer_bot_product_uncertain"}
    assert conversation.status == "NEEDS_OWNER"
    assert sent[-1][0] == owner.phone
    assert "take over 2348099990002" in sent[-1][1]

    takeover = handle_automation_owner_command(
        db,
        owner.phone,
        "take over 2348099990002",
        owner,
        send,
    )
    assert takeover == {"status": "automation_takeover"}
    assert conversation.status == "HUMAN_TAKEOVER"


if __name__ == "__main__":
    test_owner_can_enable_customer_bot_on_go_plan()
    test_basic_owner_is_asked_to_upgrade_for_customer_bot()
    test_customer_can_start_and_get_inventory_answer()
    test_customer_part_payment_creates_pending_evidence_then_owner_confirms()
    test_owner_can_manage_products_and_bot_settings_from_whatsapp()
    test_owner_can_manage_customer_bot_orders()
    test_interested_customers_and_follow_up()
    test_daily_assistant_commands()
    test_minimum_deposit_blocks_low_customer_payment()
    test_uncertain_product_alerts_owner_and_takeover_stops_bot()
    print("customer automation smoke tests passed")
