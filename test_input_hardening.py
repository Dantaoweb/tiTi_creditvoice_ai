"""
Security hardening from the active assessment:
- POS rejects negative quantities/prices (no negative-amount transactions).
- CSV export neutralises formula injection (=, +, -, @ prefixed cells).
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-input-hardening-000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, Customer, Transaction

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _pro_owner():
    n = next(_seq)
    phone = f"234803333{n:04d}"
    client.post("/app/api/auth/register", json={"name": "O", "phone": phone, "pin": "5678"})
    db = SessionLocal(); u = db.query(User).filter(User.phone == phone).first()
    u.subscription_plan = "PRO"; u.subscription_status = "ACTIVE"; db.commit(); db.close()
    return phone, client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def test_pos_rejects_negative_price():
    phone, cook = _pro_owner()
    r = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "items": [{"name": "x", "qty": 1, "unit_price": -99999}], "payment_amount": 0})
    assert r.status_code != 200
    db = SessionLocal()
    assert db.query(Transaction).filter(Transaction.amount < 0).count() == 0
    db.close()


def test_pos_rejects_negative_qty():
    phone, cook = _pro_owner()
    r = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "items": [{"name": "x", "qty": -5, "unit_price": 100}], "payment_amount": 0})
    assert r.status_code != 200


def test_csv_export_neutralises_formula_injection():
    from export_utils import _csv_safe, _sanitize_rows
    assert _csv_safe("=HYPERLINK(\"http://evil\")").startswith("'=")
    assert _csv_safe("+1+1").startswith("'+")
    assert _csv_safe("-2+3").startswith("'-")
    assert _csv_safe("@SUM(A1)").startswith("'@")
    assert _csv_safe("normal name") == "normal name"     # untouched
    assert _csv_safe(1500) == 1500                        # numbers pass through
    rows = _sanitize_rows([["=cmd", "safe", 10]])
    assert rows[0][0] == "'=cmd" and rows[0][1] == "safe" and rows[0][2] == 10
