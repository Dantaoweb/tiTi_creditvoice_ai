"""
Get-started flow: empty-state detection, keyword business-type inference, and
setting the business type from the suggestion.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-getstarted-00000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner(phone):
    client.post("/app/api/auth/register", json={"name": "Biz", "phone": phone, "pin": "5678"})
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def _add(cook, phone, name):
    return client.post("/app/api/inventory", cookies=cook,
                       json={"owner_phone": phone, "name": name, "selling_price": 100000})


def test_empty_state_then_car_suggestion_then_set():
    phone = "2348210000010"
    cook = _owner(phone)

    # Fresh account: no stock, no type, not enough signal for a suggestion.
    gs = client.get("/app/api/getting-started", cookies=cook).json()
    assert gs["has_priced_stock"] is False
    assert gs["needs_type"] is True
    assert gs["suggestion"] is None

    # Record a few car items → keyword inference should suggest car_dealer.
    _add(cook, phone, "Toyota Corolla 2015")
    _add(cook, phone, "Honda Accord")
    _add(cook, phone, "Lexus RX350")

    gs = client.get("/app/api/getting-started", cookies=cook).json()
    assert gs["has_priced_stock"] is True
    assert gs["suggestion"] is not None
    assert gs["suggestion"]["type"] == "car_dealer"
    assert gs["suggestion"]["label"]

    # Accept it.
    r = client.post("/app/api/getting-started/business-type", cookies=cook,
                    json={"business_type": "car_dealer"})
    assert r.status_code == 200, r.text
    assert r.json()["business_type"] == "car_dealer"

    # Type is now set → no more suggestion, needs_type False.
    gs = client.get("/app/api/getting-started", cookies=cook).json()
    assert gs["needs_type"] is False
    assert gs["suggestion"] is None
    assert gs["business_type"] == "car_dealer"


def test_pharmacy_keyword_inference():
    from business_inference import suggest_business_type
    phone = "2348210000020"
    cook = _owner(phone)
    _add(cook, phone, "Paracetamol tablets")
    _add(cook, phone, "Amoxicillin capsule")
    _add(cook, phone, "Cough syrup")
    db = SessionLocal()
    try:
        s = suggest_business_type(db, phone)
    finally:
        db.close()
    assert s and s["type"] == "pharmacy"


def test_set_business_type_rejects_unknown():
    phone = "2348210000030"
    cook = _owner(phone)
    r = client.post("/app/api/getting-started/business-type", cookies=cook,
                    json={"business_type": "not_a_real_type"})
    assert r.status_code == 400


def test_no_suggestion_below_threshold():
    from business_inference import suggest_business_type
    phone = "2348210000040"
    cook = _owner(phone)
    _add(cook, phone, "Toyota Corolla")  # only one signal
    db = SessionLocal()
    try:
        assert suggest_business_type(db, phone) is None
    finally:
        db.close()
