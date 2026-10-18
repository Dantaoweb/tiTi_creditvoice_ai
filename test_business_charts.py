"""
The numbers behind the Insights graphs add up, follow who may see profit,
and stay in their scope.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from business_charts import build_charts
from database import Base
from models import Customer, InventoryItem, InventoryMovement, Transaction, TransactionItem, User

OWNER = "2348007000444"
NOW = datetime(2026, 10, 18, 15, 0)          # UTC → 16:00 in Lagos


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e)()
    s.add(User(id="o", phone=OWNER, name="Shop"))
    s.add(InventoryItem(owner_phone=OWNER, name="rice", unit="bag", quantity=50, selling_price=60000,
                        cost_price=50000, is_available=True))
    ade = Customer(owner_phone=OWNER, name="ade", balance=0)
    s.add(ade); s.flush()

    def tx(kind, amount, days_ago, customer=None, product="rice", qty=1):
        t = Transaction(type=kind, amount=amount, customer_id=customer, recorded_by_id="o",
                        product=product, created_at=NOW - timedelta(days=days_ago), message_id=f"m{kind}{amount}{days_ago}")
        s.add(t); s.flush()
        if kind in ("SALE", "BUY"):
            s.add(TransactionItem(transaction_id=t.id, product=product, quantity=qty,
                                  unit_price=amount // qty, total=amount))
    tx("BUY", 60000, 10, ade.id)       # before this week: Ade owes 60,000
    tx("SALE", 120000, 2, qty=2)       # cash sale, 2 bags
    tx("BUY", 60000, 1, ade.id)        # more credit
    tx("PAY", 50000, 0, ade.id)        # Ade pays 50,000 today
    s.commit()
    yield s
    s.close()


def test_the_week_adds_up(db):
    c = build_charts(db, OWNER, "WEEK", can_see_profit=True, now=NOW)
    assert c["grain"] == "day" and len(c["series"]) == 7
    t = c["totals"]
    assert t["cash"] == 120000 and t["credit"] == 60000 and t["sales"] == 180000
    assert t["collected"] == 170000                   # 120,000 cash + 50,000 paid
    assert t["new_debt"] == 60000
    assert t["owed_now"] == 70000                     # 60k before + 60k − 50k
    assert c["series"][0]["owed"] == 60000            # the week starts with the old debt
    assert t["profit"] == 180000 - 3 * 50000          # 3 bags at cost 50,000
    assert c["top"][0]["name"] == "Rice" and c["top"][0]["revenue"] == 180000


def test_staff_who_may_not_see_profit_get_no_profit(db):
    c = build_charts(db, OWNER, "WEEK", can_see_profit=False, now=NOW)
    assert c["profit_hidden"] and "profit" not in c["totals"] and "profit" not in c["series"][0]


def test_periods_have_sensible_points(db):
    assert build_charts(db, OWNER, "TODAY", now=NOW)["grain"] == "hour"
    assert len(build_charts(db, OWNER, "MONTH", now=NOW)["series"]) == 30
    year = build_charts(db, OWNER, "YEAR", now=NOW)
    assert year["grain"] == "month" and len(year["series"]) == 12
    assert build_charts(db, OWNER, None, now=NOW)["grain"] == "month"


def test_a_staff_member_sees_only_their_records(db):
    c = build_charts(db, OWNER, "WEEK", recorded_by_id="someone-else", now=NOW)
    assert c["totals"]["sales"] == 0


def test_the_charts_endpoint_for_a_logged_in_owner():
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-business-charts-0000000")
    from fastapi.testclient import TestClient
    import web_auth
    from main import app
    client = TestClient(app)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    phone = "2348102000123"
    client.post("/app/api/auth/register", json={"name": "Graph Shop", "phone": phone, "pin": "5678"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "items": [{"name": "rice", "qty": 1, "unit_price": 60000}], "payment_amount": 60000})
    for period in ("TODAY", "WEEK", "MONTH", "YEAR", ""):
        r = client.get("/app/api/reports/charts", cookies=cook, params={"period": period} if period else {})
        assert r.status_code == 200, (period, r.text)
    week = client.get("/app/api/reports/charts", cookies=cook, params={"period": "WEEK"}).json()
    assert week["totals"]["sales"] == 60000 and week["profit_hidden"] is False
