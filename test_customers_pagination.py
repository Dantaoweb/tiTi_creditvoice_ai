"""
Customer list must reach EVERY customer: the old endpoint returned only the 200
newest, so older customers (often the long-standing debtors) vanished from the
Debtors tab and Total Outstanding, and Quick Record/POS offered to re-create
them as new customers, splitting their debt across two records.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-cust-paging-00000000000000")

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import Customer, Transaction, utcnow

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000, 2000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner():
    phone = f"234846{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    cookies = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, cookies


def _seed(phone, n):
    """n customers; customer 0 is the OLDEST and owes 5,000."""
    db = SessionLocal()
    now = utcnow()
    for i in range(n):
        db.add(Customer(owner_phone=phone, name=f"customer {i:03d}",
                        balance=5000 if i == 0 else 0,
                        created_at=now - timedelta(minutes=n - i)))
    db.commit(); db.close()


def _get(cook, **params):
    r = client.get("/app/api/customers", cookies=cook, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_every_customer_reachable_past_200():
    phone, cook = _owner()
    _seed(phone, 230)
    seen, offset = [], 0
    while True:
        d = _get(cook, limit=100, offset=offset)
        assert d["total"] == 230
        seen += [c["name"] for c in d["customers"]]
        if not d["has_more"]:
            break
        offset += len(d["customers"])
    assert len(set(seen)) == 230 and "customer 000" in seen


def test_old_debtor_in_debtors_and_summary():
    phone, cook = _owner()
    _seed(phone, 230)
    d = _get(cook, debtors="true")
    assert [c["name"] for c in d["customers"]] == ["customer 000"]
    s = client.get("/app/api/customers/summary", cookies=cook).json()
    assert s["total"] == 230 and s["debtors"] == 1 and s["outstanding"] == 5000


def test_debtors_sorted_biggest_first_with_overdue():
    phone, cook = _owner()
    db = SessionLocal()
    small = Customer(owner_phone=phone, name="small", balance=0)
    big = Customer(owner_phone=phone, name="big", balance=0)
    db.add_all([small, big]); db.flush()
    # The Transaction listeners keep customers.balance current.
    db.add(Transaction(customer_id=big.id, type="BUY", amount=9000,
                       due_date=utcnow() - timedelta(days=3)))
    db.add(Transaction(customer_id=small.id, type="BUY", amount=100,
                       due_date=utcnow() + timedelta(days=3)))
    db.commit(); db.close()
    rows = _get(cook, debtors="true")["customers"]
    assert [c["name"] for c in rows] == ["big", "small"]
    assert rows[0]["has_overdue"] is True and rows[1]["has_overdue"] is False
    assert rows[1]["next_due"] is not None
    s = client.get("/app/api/customers/summary", cookies=cook).json()
    assert s["debtors"] == 2 and s["outstanding"] == 9100 and s["overdue"] == 1


def test_search_name_phone_and_exact_first():
    phone, cook = _owner()
    db = SessionLocal()
    db.add_all([
        Customer(owner_phone=phone, name="Mama Tunde", balance=0),
        Customer(owner_phone=phone, name="Tunde", balance=0, customer_phone="2348031234567"),
    ])
    db.commit(); db.close()
    assert [c["name"] for c in _get(cook, q="tunde")["customers"]] == ["Tunde", "Mama Tunde"]
    assert [c["name"] for c in _get(cook, q="08031234567")["customers"]] == ["Tunde"]
    assert _get(cook, q="%")["total"] == 0


def test_add_customer_rejects_same_name_any_case():
    phone, cook = _owner()
    r1 = client.post("/app/api/customers", cookies=cook, json={"owner_phone": phone, "name": "Mama Bola"})
    assert r1.status_code == 200, r1.text
    r2 = client.post("/app/api/customers", cookies=cook, json={"owner_phone": phone, "name": "mama bola"})
    assert r2.status_code == 409


def test_pos_new_customer_reuses_existing_any_case():
    phone, cook = _owner()
    cid = client.post("/app/api/customers", cookies=cook,
                      json={"owner_phone": phone, "name": "Mama Bola"}).json()["id"]
    r = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "customer_name": "mama bola",
        "items": [{"name": "rice", "qty": 1, "unit_price": 700}], "payment_amount": 0,
    })
    assert r.status_code == 200, r.text
    rows = _get(cook, q="bola")["customers"]
    assert [c["id"] for c in rows] == [cid] and rows[0]["balance"] == 700
