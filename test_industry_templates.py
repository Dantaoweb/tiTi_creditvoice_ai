from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from business_templates import HIGH_VALUE_TEMPLATE_KEYS, industry_plan_matrix
from database import Base
from messages import build_owner_home_menu, build_post_onboarding_menu
from models import Customer, PendingAction, Transaction, User
from onboarding_commands import handle_onboarding_pending, handle_post_onboarding_pending
from parser import build_customer_account_summary, parse_message
from plans import format_upgrade_message
from subscriptions import check_thrift_participant_limit


def make_user(business_type, business_category, business_type_label):
    return SimpleNamespace(
        id="owner-id",
        name="demo business",
        role="user",
        parent_id=None,
        business_type=business_type,
        business_category=business_category,
        business_type_label=business_type_label,
    )


def assert_contains(text, expected):
    assert expected in text, f"Expected {expected!r} in:\n{text}"


def make_test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_industry_matrix_and_messages():
    matrix = industry_plan_matrix()
    assert sorted(matrix.keys()) == sorted(HIGH_VALUE_TEMPLATE_KEYS)

    samples = [
        ("provision_store", "retail_trading", "Provision Store", "INVENTORY", "Inventory", "stock is worth"),
        ("pharmacy", "health", "Pharmacy", "INVENTORY", "Inventory", "medicine quantity"),
        ("private_school", "education", "Private School", "DUE_REMINDERS", "Debt reminders", "unpaid fees"),
        ("hair_salon", "beauty_personal_care", "Hair Salon", "STAFF", "Staff", "stylists"),
        ("tailor_fashion", "services_artisans", "Tailor / Fashion Designer", "DUE_REMINDERS", "Debt reminders", "unpaid job balances"),
        ("restaurant", "food_hospitality", "Restaurant", "INVENTORY", "Inventory", "frozen food"),
        ("feed_seller", "agriculture", "Feed Seller", "INVENTORY", "Inventory", "farm inputs"),
        ("dispatch_delivery", "transport_logistics", "Dispatch / Delivery", "TRANSACTION_NOTES", "Transaction notes", "delivery details"),
        ("property_manager", "real_estate_rentals", "Property Manager", "DUE_REMINDERS", "Debt reminders", "rental balances"),
        ("printing_photocopy", "professional_office_services", "Printing / Photocopy", "TRANSACTION_NOTES", "Transaction notes", "service details"),
        ("thrift_collector", "thrift_contribution", "Thrift Collector", "THRIFT_PARTICIPANTS", "Thrift participants", "10-participant limit"),
    ]

    for business_type, category, label, feature, feature_label, expected_value in samples:
        user = make_user(business_type, category, label)
        post_onboarding = build_post_onboarding_menu("demo business", user)
        home_menu = build_owner_home_menu(user, {"plan": "BASIC"})
        upgrade = format_upgrade_message("BASIC", "GO", feature_label, user, feature)

        assert_contains(post_onboarding, "Quick actions:")
        assert_contains(post_onboarding, "How to move around:")
        assert_contains(home_menu, "Send back, cancel, done, or menu")
        assert_contains(upgrade, expected_value)


def test_post_onboarding_add_customer_does_not_trap_user():
    db = make_test_db()
    sent_messages = []
    phone = "2348000000001"
    pending = PendingAction(
        phone=phone,
        customer_name="Demo Business",
        action="POST_ONBOARDING_MENU",
    )
    db.add(pending)
    db.commit()

    result = handle_post_onboarding_pending(
        db,
        phone,
        "2",
        pending,
        make_user("pharmacy", "health", "Pharmacy"),
        "Demo Business",
        lambda to, message: sent_messages.append((to, message)),
    )

    remaining_pending = db.query(PendingAction).filter(
        PendingAction.phone == phone
    ).first()

    assert result == {"status": "post_onboarding_add_customer"}
    assert remaining_pending is None
    assert sent_messages
    assert_contains(sent_messages[-1][1], "John 08012345678")


def test_post_onboarding_allows_natural_transaction_text():
    db = make_test_db()
    phone = "2348000000002"
    pending = PendingAction(
        phone=phone,
        customer_name="Demo Business",
        action="POST_ONBOARDING_MENU",
    )
    db.add(pending)
    db.commit()

    result = handle_post_onboarding_pending(
        db,
        phone,
        "Amina contributed 5000",
        pending,
        make_user("thrift_collector", "thrift_contribution", "Thrift Collector"),
        "Demo Business",
        lambda to, message: None,
    )

    remaining_pending = db.query(PendingAction).filter(
        PendingAction.phone == phone
    ).first()

    assert result is None
    assert remaining_pending is None


def test_thrift_contribution_text_parses_as_payment():
    samples = [
        ("Amina contributed 5000", "amina", 5000),
        ("Tunde paid thrift 2000", "tunde", 2000),
        ("Bola thrift 3k", "bola", 3000),
    ]

    for text, expected_name, expected_amount in samples:
        parsed = parse_message(text)
        assert parsed is not None, text
        assert parsed["type"] == "TRANSACTION"
        assert parsed["action"] == "PAY"
        assert parsed["name"] == expected_name
        assert parsed["paid_amount"] == expected_amount


def test_quantity_unit_item_parses_when_price_has_no_at_keyword():
    samples = [
        "shade buy 2 congos of rice at 400",
        "shade buy 2 congos of rice 400",
        "shade buy 2 congos of rice at 400.",
    ]

    for text in samples:
        parsed = parse_message(text)
        assert parsed is not None, text
        assert parsed["type"] == "TRANSACTION"
        assert parsed["name"] == "shade"
        assert parsed["action"] == "BUY"
        assert parsed["buy_amount"] == 800
        assert parsed["quantity"] == 2
        assert parsed["unit"] == "congos"
        assert parsed["product"] == "rice"
        assert parsed["unit_price"] == 400
        assert parsed["total"] == 800


def test_i_buy_without_supplier_does_not_create_customer_i():
    parsed = parse_message("i buy 1 pack of coke 2400")

    assert parsed is not None
    assert parsed["type"] == "SELF_PURCHASE_NEEDS_SUPPLIER"


def test_customer_account_summary_includes_product_details():
    db = make_test_db()
    owner_phone = "2348000000888"
    customer = Customer(name="shade", owner_phone=owner_phone)
    db.add(customer)
    db.flush()
    db.add(
        Transaction(
            customer_id=customer.id,
            type="BUY",
            amount=2400,
            product="coke",
            quantity=1,
            unit="pack",
            unit_price=2400,
        )
    )
    db.add(
        Transaction(
            customer_id=customer.id,
            type="PAY",
            amount=1000,
        )
    )
    db.commit()

    summary = build_customer_account_summary(db, owner_phone, "shade")

    assert "BUY - 1 pack of coke: ₦2,400" in summary
    assert "PAY: ₦1,000" in summary


def run_onboarding_flow(category_choice, business_choice, expected_category, expected_type, expected_label):
    db = make_test_db()
    sent_messages = []
    phone = f"23480000000{category_choice}"
    pending = PendingAction(phone=phone, action="ONBOARD_USER")
    db.add(pending)
    db.commit()

    send_message = lambda to, message: sent_messages.append((to, message))

    assert handle_onboarding_pending(db, phone, "demo business", pending, None, send_message) == {
        "status": "onboarding_confirm_sent"
    }
    assert pending.action == "ONBOARD_USER_CONFIRM"

    assert handle_onboarding_pending(db, phone, "yes", pending, None, send_message) == {
        "status": "onboarding_category_prompt"
    }
    assert pending.action == "ONBOARD_USER_CATEGORY"
    assert_contains(sent_messages[-1][1], "Choose one number")

    assert handle_onboarding_pending(db, phone, str(category_choice), pending, None, send_message) == {
        "status": "onboarding_business_type_prompt"
    }
    assert pending.action == "ONBOARD_USER_BUSINESS_TYPE"

    assert handle_onboarding_pending(db, phone, "back", pending, None, send_message) == {
        "status": "onboarding_business_type_back"
    }
    assert pending.action == "ONBOARD_USER_CATEGORY"

    assert handle_onboarding_pending(db, phone, str(category_choice), pending, None, send_message) == {
        "status": "onboarding_business_type_prompt"
    }
    assert handle_onboarding_pending(db, phone, str(business_choice), pending, None, send_message) == {
        "status": "user_saved"
    }

    user = db.query(User).filter(User.phone == phone).first()
    next_pending = db.query(PendingAction).filter(PendingAction.phone == phone).first()

    assert user is not None
    assert user.business_category == expected_category
    assert user.business_type == expected_type
    assert user.business_type_label == expected_label
    assert next_pending is not None
    assert next_pending.action == "POST_ONBOARDING_MENU"
    assert_contains(sent_messages[-1][1], "Quick actions:")
    assert_contains(sent_messages[-1][1], "How to move around:")


def test_industry_onboarding_paths():
    samples = [
        (1, 1, "retail_trading", "provision_store", "Provision Store"),
        (2, 1, "health", "pharmacy", "Pharmacy"),
        (3, 1, "education", "private_school", "Private School"),
        (4, 1, "beauty_personal_care", "hair_salon", "Hair Salon"),
        (5, 1, "food_hospitality", "restaurant", "Restaurant"),
        (6, 1, "services_artisans", "tailor_fashion", "Tailor / Fashion Designer"),
        (7, 1, "agriculture", "feed_seller", "Feed Seller"),
        (8, 1, "transport_logistics", "dispatch_delivery", "Dispatch / Delivery"),
        (9, 1, "real_estate_rentals", "property_manager", "Property Manager"),
        (10, 1, "professional_office_services", "printing_photocopy", "Printing / Photocopy"),
        (11, 1, "thrift_contribution", "thrift_collector", "Thrift Collector"),
    ]

    for sample in samples:
        run_onboarding_flow(*sample)


def test_basic_thrift_participant_limit():
    db = make_test_db()
    owner_phone = "2348000000999"
    subscription = {
        "plan": "BASIC",
        "limits": {
            "thrift_participants": 10,
        },
    }

    for index in range(10):
        db.add(
            Customer(
                name=f"participant {index}",
                owner_phone=owner_phone,
            )
        )
    db.commit()

    allowed, message = check_thrift_participant_limit(
        db,
        owner_phone,
        subscription,
    )

    assert allowed is False
    assert_contains(message, "10 thrift participants")
    assert_contains(message, "participant history")


if __name__ == "__main__":
    test_industry_matrix_and_messages()
    test_post_onboarding_add_customer_does_not_trap_user()
    test_post_onboarding_allows_natural_transaction_text()
    test_thrift_contribution_text_parses_as_payment()
    test_quantity_unit_item_parses_when_price_has_no_at_keyword()
    test_i_buy_without_supplier_does_not_create_customer_i()
    test_customer_account_summary_includes_product_details()
    test_industry_onboarding_paths()
    test_basic_thrift_participant_limit()
    print("industry template smoke tests passed")
