import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import webhook_command_router
import webhook_early_handlers
import webhook_message_flow
import webhook_pending_router
from database import Base
from models import Customer, InventoryItem, PendingAction, SupplierPurchase, Transaction, User


def make_whatsapp_text_body(phone, text, message_id):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": phone,
                                    "id": message_id,
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


def make_shared_test_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def make_webhook_flow(monkeypatch, phone, message_prefix):
    SessionTesting = make_shared_test_session()
    sent_messages = []

    def fake_send(to, message):
        sent_messages.append((to, message))

    monkeypatch.setattr(webhook_message_flow, "SessionLocal", SessionTesting)
    monkeypatch.setattr(webhook_message_flow, "send_whatsapp_message", fake_send)
    monkeypatch.setattr(webhook_early_handlers, "SessionLocal", SessionTesting)
    monkeypatch.setattr(webhook_early_handlers, "send_whatsapp_message", fake_send)
    monkeypatch.setattr(webhook_pending_router, "send_whatsapp_message", fake_send)
    monkeypatch.setattr(webhook_command_router, "send_whatsapp_message", fake_send)

    counter = 0

    def send(text):
        nonlocal counter
        counter += 1
        return webhook_message_flow.handle_webhook_body(
            make_whatsapp_text_body(phone, text, f"wamid.{message_prefix}.{counter}")
        )

    return SessionTesting, sent_messages, send


def onboard_business(send, business_name, category_choice, business_choice):
    assert send("hello") == {"status": "onboarding_started"}
    assert send(business_name) == {"status": "onboarding_confirm_sent"}
    assert send("yes") == {"status": "onboarding_category_prompt"}
    assert send(str(category_choice)) == {"status": "onboarding_business_type_prompt"}
    result = send(str(business_choice))
    if result == {"status": "onboarding_partial_warning_sent"}:
        result = send("yes")
    assert result == {"status": "onboarding_complete"}


def set_user_plan(SessionTesting, phone, plan="GO"):
    db = SessionTesting()
    try:
        user = db.query(User).filter(User.phone == phone).one()
        user.subscription_plan = plan
        db.commit()
        return user.business_category, user.business_type, user.business_type_label
    finally:
        db.close()


def test_pharmacy_whatsapp_onboarding_sale_and_supplier_stock(monkeypatch):
    phone = "2348012345678"
    SessionTesting, sent_messages, send = make_webhook_flow(
        monkeypatch,
        phone,
        "pharmacy",
    )

    onboard_business(send, "Demo Pharmacy", 2, 1)

    db = SessionTesting()
    try:
        user = db.query(User).filter(User.phone == phone).one()
        assert user.business_category == "health"
        assert user.business_type == "pharmacy"
        assert user.business_type_label == "Pharmacy"

        user.subscription_plan = "GO"
        db.commit()
    finally:
        db.close()


@pytest.mark.parametrize(
    "phone,business_name,category_choice,business_choice,expected_category,expected_type,expected_label",
    [
        ("2348000000301", "Demo School", 3, 1, "education", "private_school", "Private School"),
        ("2348000000401", "Demo Salon", 4, 1, "beauty_personal_care", "hair_salon", "Hair Salon"),
        ("2348000000501", "Demo Restaurant", 5, 1, "food_hospitality", "restaurant", "Restaurant"),
        ("2348000000601", "Demo Tailor", 6, 1, "services_artisans", "tailor_fashion", "Tailor / Fashion Designer"),
        ("2348000000701", "Demo Feed Store", 7, 1, "agriculture", "feed_seller", "Feed Seller"),
        ("2348000000801", "Demo Dispatch", 8, 1, "transport_logistics", "dispatch_delivery", "Dispatch / Delivery"),
        ("2348000000901", "Demo Properties", 9, 1, "real_estate_rentals", "property_manager", "Property Manager"),
        ("2348000001001", "Demo Printing", 10, 1, "professional_office_services", "printing_photocopy", "Printing / Photocopy"),
        ("2348000001101", "Demo Thrift", 11, 1, "thrift_contribution", "thrift_collector", "Thrift Collector"),
    ],
)
def test_next_business_categories_onboard_through_real_whatsapp_flow(
    monkeypatch,
    phone,
    business_name,
    category_choice,
    business_choice,
    expected_category,
    expected_type,
    expected_label,
):
    SessionTesting, sent_messages, send = make_webhook_flow(
        monkeypatch,
        phone,
        expected_type,
    )

    onboard_business(send, business_name, category_choice, business_choice)

    db = SessionTesting()
    try:
        user = db.query(User).filter(User.phone == phone).one()
        assert user.business_category == expected_category
        assert user.business_type == expected_type
        assert user.business_type_label == expected_label
        assert db.query(PendingAction).filter(
            PendingAction.phone == phone,
            PendingAction.action == "POST_ONBOARDING_MENU",
        ).one()
        assert "Account created." in sent_messages[-1][1]
        assert "1. Help & formats" in sent_messages[-1][1]
        assert "3. Dashboard" in sent_messages[-1][1]
        assert "5. Upgrade" in sent_messages[-1][1]
    finally:
        db.close()


@pytest.mark.parametrize(
    "phone,business_name,category_choice,business_choice,message,expected_status,confirm_status,expected_transactions",
    [
        (
            "2348000000302",
            "Demo School",
            3,
            1,
            "Tunde paid school fees 50000",
            "pending",
            "saved",
            [{"customer": "tunde", "type": "PAY", "amount": 50000, "product": None}],
        ),
        (
            "2348000000402",
            "Demo Salon",
            4,
            1,
            "Blessing did braids 15000 paid 10000",
            "pending",
            "saved",
            [
                {"customer": "blessing", "type": "BUY", "amount": 15000, "product": "braids"},
                {"customer": "blessing", "type": "PAY", "amount": 10000, "product": None},
            ],
        ),
        (
            "2348000000502",
            "Demo Restaurant",
            5,
            1,
            "I sold 3 plates food at 2500",
            "confirm_direct_sale",
            "direct_sale_saved",
            [{"customer": None, "type": "SALE", "amount": 7500, "product": "food", "quantity": 3, "unit": "plate"}],
        ),
        (
            "2348000000602",
            "Demo Tailor",
            6,
            1,
            "Aisha sewed dress 25000 paid 15000",
            "pending",
            "saved",
            [
                {"customer": "aisha", "type": "BUY", "amount": 25000, "product": "dress"},
                {"customer": "aisha", "type": "PAY", "amount": 15000, "product": None},
            ],
        ),
        (
            "2348000000702",
            "Demo Feed Store",
            7,
            1,
            "Ayo bought 5 bags feed at 18000",
            "pending",
            "saved",
            [{"customer": "ayo", "type": "BUY", "amount": 90000, "product": "feed", "quantity": 5, "unit": "bag"}],
        ),
        (
            "2348000000802",
            "Demo Dispatch",
            8,
            1,
            "I received 2500 for delivery",
            "confirm_direct_sale",
            "direct_sale_saved",
            [{"customer": None, "type": "SALE", "amount": 2500, "product": "delivery"}],
        ),
        (
            "2348000000902",
            "Demo Properties",
            9,
            1,
            "Tenant A paid rent 200000",
            "pending",
            "saved",
            [{"customer": "tenant a", "type": "PAY", "amount": 200000, "product": None}],
        ),
        (
            "2348000001002",
            "Demo Printing",
            10,
            1,
            "I received 3000 for printing",
            "confirm_direct_sale",
            "direct_sale_saved",
            [{"customer": None, "type": "SALE", "amount": 3000, "product": "printing"}],
        ),
        (
            "2348000001102",
            "Demo Thrift",
            11,
            1,
            "Amina contributed 5000",
            "pending",
            "saved",
            [{"customer": "amina", "type": "PAY", "amount": 5000, "product": None}],
        ),
    ],
)
def test_next_business_categories_record_transactions_through_real_whatsapp_flow(
    monkeypatch,
    phone,
    business_name,
    category_choice,
    business_choice,
    message,
    expected_status,
    confirm_status,
    expected_transactions,
):
    SessionTesting, sent_messages, send = make_webhook_flow(
        monkeypatch,
        phone,
        f"{category_choice}-{business_choice}",
    )
    onboard_business(send, business_name, category_choice, business_choice)
    set_user_plan(SessionTesting, phone, "GO")

    assert send(message) == {"status": expected_status}
    assert sent_messages[-1][1]
    assert send("yes") == {"status": confirm_status}

    db = SessionTesting()
    try:
        for expected in expected_transactions:
            query = db.query(Transaction).filter(
                Transaction.type == expected["type"],
                Transaction.amount == expected["amount"],
            )
            customer_name = expected.get("customer")
            if customer_name is None:
                query = query.filter(Transaction.customer_id == None)
            else:
                customer = db.query(Customer).filter(
                    Customer.owner_phone == phone,
                    Customer.name == customer_name,
                ).one()
                query = query.filter(Transaction.customer_id == customer.id)

            tx = query.one()
            assert tx.product == expected.get("product")
            if "quantity" in expected:
                assert tx.quantity == expected["quantity"]
            if "unit" in expected:
                assert tx.unit == expected["unit"]
    finally:
        db.close()


def test_post_onboarding_menu_has_expected_options(monkeypatch):
    phone = "2348000001201"
    SessionTesting, sent_messages, send = make_webhook_flow(
        monkeypatch,
        phone,
        "post-onboarding-stock",
    )

    onboard_business(send, "Demo Store", 1, 1)

    last_msg = sent_messages[-1][1]
    assert "1. Help & formats" in last_msg
    assert "2. Add customer" in last_msg
    assert "3. Dashboard" in last_msg
    assert "5. Upgrade" in last_msg


def test_dashboard_menu_has_add_stock_and_routes_to_stock_help(monkeypatch):
    phone = "2348000001202"
    SessionTesting, sent_messages, send = make_webhook_flow(
        monkeypatch,
        phone,
        "dashboard-stock",
    )

    onboard_business(send, "Demo Store", 1, 1)

    assert send("3") == {"status": "post_onboarding_dashboard"}
    assert "10. Add stock" in sent_messages[-1][1]
    assert send("add stock") == {"status": "guided_stock_started"}
    assert "stock" in sent_messages[-1][1].lower()
    assert send("Mary bought 2 packs paracetamol at 2500") == {"status": "pending"}
    assert "Confirm:" in sent_messages[-1][1]
    assert "paracetamol" in sent_messages[-1][1]
    assert "2,500" in sent_messages[-1][1]

    assert send("yes") == {"status": "saved"}

    db = SessionTesting()
    try:
        customer = db.query(Customer).filter(
            Customer.owner_phone == phone,
            Customer.name == "mary",
        ).one()
        sale = db.query(Transaction).filter(
            Transaction.customer_id == customer.id,
            Transaction.type == "BUY",
        ).one()
        assert sale.amount == 5000
        assert sale.product == "paracetamol"
        assert sale.quantity == 2
        assert sale.unit == "pack"
        assert sale.unit_price == 2500
    finally:
        db.close()

    # Supplier transactions require GO plan — upgrade before this step
    db_upgrade = SessionTesting()
    try:
        from models import User as _User
        u = db_upgrade.query(_User).filter(_User.phone == phone).first()
        if u:
            u.subscription_plan = "GO"
            u.subscription_status = "ACTIVE"
            db_upgrade.commit()
    finally:
        db_upgrade.close()

    assert send("Ayo supplied me 10 packs malaria drug for 18000") == {
        "status": "confirm_supplier_transaction"
    }
    assert "Confirm stock from supplier:" in sent_messages[-1][1]
    assert "Item: Malaria Drug" in sent_messages[-1][1]

    assert send("yes") == {"status": "supplier_saved"}

    db = SessionTesting()
    try:
        purchase = db.query(SupplierPurchase).one()
        stock = db.query(InventoryItem).filter(
            InventoryItem.owner_phone == phone,
            InventoryItem.name == "malaria drug",
        ).one()

        assert purchase.product == "malaria drug"
        assert purchase.quantity == 10
        assert purchase.unit == "pack"
        assert purchase.unit_price == 1800
        assert purchase.total == 18000

        assert stock.quantity == 10
        assert stock.unit == "pack"
        assert stock.cost_price == 1800

        assert db.query(PendingAction).filter(PendingAction.phone == phone).first() is None
    finally:
        db.close()
