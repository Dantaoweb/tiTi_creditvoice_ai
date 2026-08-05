"""
App-admin user directory now reports per-business activity (transactions total /
30-day, last active, customers, stock) and can rank businesses by activity.
"""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-admin-perf-0000000000000")
os.environ["APP_ADMIN_PHONES"] = "2348090000001"

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, Customer, Transaction

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _reset():
    # app_admin_phones() reads env live; another test module may have overwritten
    # APP_ADMIN_PHONES at import, so restore ours before each test (whole suite
    # runs in one process on CI).
    os.environ["APP_ADMIN_PHONES"] = "2348090000001"
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _register(phone, name="Biz"):
    client.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": "5678"})


def _seed_tx(owner_phone, n):
    """Give a business n customer-linked transactions."""
    db = SessionLocal()
    try:
        c = Customer(owner_phone=owner_phone, name=f"cust-{owner_phone}")
        db.add(c); db.commit(); db.refresh(c)
        for _ in range(n):
            db.add(Transaction(customer_id=c.id, type="BUY", amount=1000,
                               message_id=f"m-{uuid.uuid4()}"))
        db.commit()
    finally:
        db.close()


def test_admin_sees_per_user_activity_and_ranking():
    admin_phone = "2348090000001"
    _register(admin_phone, "Admin")
    cookies = client.post("/app/api/auth/login",
                          json={"phone": admin_phone, "pin": "5678"}).cookies

    # Three businesses with different activity levels.
    _register("2348090000010", "Busy")
    _register("2348090000011", "Medium")
    _register("2348090000012", "Quiet")
    _seed_tx("2348090000010", 8)
    _seed_tx("2348090000011", 3)
    # Quiet business: no transactions.

    d = client.get("/app/api/admin/users", cookies=cookies, params={"sort": "active"})
    assert d.status_code == 200, d.text
    users = d.json()["users"]
    by_phone = {u["phone"]: u for u in users}

    # Metrics present and correct.
    assert by_phone["2348090000010"]["transactions_total"] == 8
    assert by_phone["2348090000011"]["transactions_total"] == 3
    assert by_phone["2348090000012"]["transactions_total"] == 0
    assert by_phone["2348090000010"]["customers"] == 1
    assert by_phone["2348090000010"]["last_active"] is not None
    assert by_phone["2348090000012"]["last_active"] is None

    # Ranking: Busy (8) ranks above Medium (3) ranks above Quiet (0).
    order = [u["phone"] for u in users if u["phone"] in
             ("2348090000010", "2348090000011", "2348090000012")]
    assert order.index("2348090000010") < order.index("2348090000011") < order.index("2348090000012")


def test_non_admin_blocked():
    _register("2348090000020", "NotAdmin")
    cookies = client.post("/app/api/auth/login",
                          json={"phone": "2348090000020", "pin": "5678"}).cookies
    d = client.get("/app/api/admin/users", cookies=cookies)
    assert d.status_code == 403
