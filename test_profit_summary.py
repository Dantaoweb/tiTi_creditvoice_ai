"""
Gross profit: what sales were charged minus what the goods cost.

One calculation behind the Dashboard card, Insights' profit by product and
tiTi's answer. A discount comes off the profit; a product with no cost is
named, never counted as pure profit; voided sales and other businesses'
sales never count.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-profit-summary-00000000000")

import uuid

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import Customer, InventoryItem, InventoryMovement, Transaction, TransactionItem, User
from reports import get_profit_summary

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _shop():
    phone = f"2348069{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Ade Stores", "phone": phone, "pin": "5678"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.phone == phone).first()
        # Rice bought at N700 a bag (stock received); beans has no cost at all.
        rice = InventoryItem(owner_phone=phone, name="rice", unit="bag", quantity=100, selling_price=1000)
        db.add(rice); db.flush()
        db.add(InventoryMovement(owner_phone=phone, item_id=rice.id, movement_type="IN",
                                 quantity=100, unit_price=700, source_type="SUPPLIER_PURCHASE"))
        db.add(InventoryItem(owner_phone=phone, name="beans", unit="bag", quantity=50, selling_price=2000))
        cust = Customer(owner_phone=phone, name="Ada", balance=0)
        db.add(cust); db.commit()
        return phone, cook, owner.id, cust.id
    finally:
        db.close()


def _sale(phone, owner_id, lines, amount=None, discount=None, kind="SALE", voided=False, cust_id=None):
    db = SessionLocal()
    try:
        total = sum(q * p for _n, q, p in lines)
        tx = Transaction(customer_id=cust_id, type=kind, amount=amount if amount is not None else total,
                         discount_amount=discount, recorded_by_id=owner_id,
                         message_id=f"m-{uuid.uuid4()}", is_voided=voided)
        db.add(tx); db.flush()
        for name, q, p in lines:
            db.add(TransactionItem(transaction_id=tx.id, product=name, quantity=q, unit_price=p, total=q * p))
        db.commit()
    finally:
        db.close()


def _summary(phone):
    db = SessionLocal()
    try:
        return get_profit_summary(db, phone)
    finally:
        db.close()


def test_profit_is_sales_minus_cost_of_goods():
    phone, _cook, owner, _c = _shop()
    _sale(phone, owner, [("rice", 10, 1000)])                    # 10,000 sales, 7,000 cost
    p = _summary(phone)
    assert (p["revenue"], p["cost"], p["gross_profit"], p["margin_pct"]) == (10000, 7000, 3000, 30)
    assert p["products"][0]["name"] == "Rice" and p["products"][0]["profit"] == 3000


def test_a_discount_comes_off_the_profit():
    phone, _cook, owner, cust = _shop()
    _sale(phone, owner, [("rice", 10, 1000)], amount=9000, discount=1000, kind="BUY", cust_id=cust)
    p = _summary(phone)
    assert p["revenue"] == 9000 and p["gross_profit"] == 2000 and p["discounts"] == 1000


def test_a_product_with_no_cost_is_named_not_counted():
    phone, _cook, owner, _c = _shop()
    _sale(phone, owner, [("rice", 10, 1000), ("beans", 2, 2000)])
    p = _summary(phone)
    assert p["revenue"] == 14000 and p["known_revenue"] == 10000
    assert p["gross_profit"] == 3000                              # beans not treated as pure profit
    assert p["no_cost_revenue"] == 4000
    assert [r["name"] for r in p["no_cost_products"]] == ["Beans"]


def test_a_loss_is_a_negative_profit():
    phone, _cook, owner, _c = _shop()
    _sale(phone, owner, [("rice", 10, 500)])                     # sold below the N700 cost
    p = _summary(phone)
    assert p["gross_profit"] == -2000 and p["products"][0]["profit"] == -2000


def test_voided_and_other_businesses_sales_never_count():
    phone, _cook, owner, _c = _shop()
    _sale(phone, owner, [("rice", 10, 1000)], voided=True)
    other, _oc, other_owner, _oc2 = _shop()
    _sale(other, other_owner, [("rice", 50, 1000)])
    assert _summary(phone)["revenue"] == 0


def test_the_dashboard_and_insights_show_it():
    phone, cook, owner, _c = _shop()
    _sale(phone, owner, [("rice", 10, 1000)])
    dash = client.get("/app/api/dashboard", cookies=cook).json()
    assert dash["profit"]["gross_profit"] == 3000 and "products" not in dash["profit"]
    ins = client.get("/app/api/reports/inventory-insights", cookies=cook).json()
    assert ins["profit"]["products"][0]["profit"] == 3000


def test_titi_gives_the_same_figure_with_the_discount():
    from business_facts import _fact_profit

    class Ask:
        period = None
    phone, _cook, owner, cust = _shop()
    _sale(phone, owner, [("rice", 10, 1000)], amount=9000, discount=1000, kind="BUY", cust_id=cust)
    db = SessionLocal()
    try:
        text = _fact_profit(db, phone, Ask())
    finally:
        db.close()
    assert "N2,000" in text or "₦2,000" in text
    assert "discount" in text.lower() and "before expenses" in text.lower()
