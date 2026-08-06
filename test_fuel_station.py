"""
Filling-station operations: deliveries raise the tank, a shift close computes
litres/expected/shortfall and draws down the tank + rolls the pump meter, and a
dip records variance against the computed level. Gated to fuel businesses.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-fuel-station-0000000000")

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


def _fuel_owner(phone):
    client.post("/app/api/auth/register", json={"name": "Station", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == phone).first()
        u.business_category = "energy_fuel"
        u.business_type = "filling_station"
        db.commit()
    finally:
        db.close()
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def _plain_owner(phone):
    client.post("/app/api/auth/register", json={"name": "Shop", "phone": phone, "pin": "5678"})
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def test_full_shift_cycle_reconciles_and_moves_tank():
    cook = _fuel_owner("2348240000001")

    tank = client.post("/app/api/fuel/tanks", cookies=cook,
                       json={"name": "Tank 1", "product": "PMS", "capacity_litres": 30000,
                             "current_level_litres": 5000}).json()
    pump = client.post("/app/api/fuel/pumps", cookies=cook,
                       json={"name": "Pump 1", "product": "PMS", "tank_id": tank["id"],
                             "current_meter": 10000}).json()
    client.post("/app/api/fuel/price", cookies=cook, json={"product": "PMS", "price_per_litre": 750})

    # Delivery raises the tank: 5000 + 20000 = 25000
    d = client.post("/app/api/fuel/deliveries", cookies=cook,
                    json={"tank_id": tank["id"], "litres": 20000, "supplier": "Depot"})
    assert d.status_code == 200 and d.json()["tank_level"] == 25000

    # Open a shift — opening meter defaults to the pump meter, price to current.
    op = client.post("/app/api/fuel/shifts/open", cookies=cook, json={"pump_id": pump["id"]})
    assert op.status_code == 200, op.text
    assert op.json()["opening_meter"] == 10000
    assert op.json()["price_per_litre"] == 750
    shift_id = op.json()["id"]

    # Can't open a second shift on the same pump.
    assert client.post("/app/api/fuel/shifts/open", cookies=cook,
                       json={"pump_id": pump["id"]}).status_code == 409

    # Close: 10200 - 10000 = 200 L * 750 = 150,000 expected. Collected 140,000 -> short 10,000.
    cl = client.post(f"/app/api/fuel/shifts/{shift_id}/close", cookies=cook,
                     json={"closing_meter": 10200, "cash_amount": 120000,
                           "pos_amount": 20000, "credit_amount": 0})
    assert cl.status_code == 200, cl.text
    body = cl.json()
    assert body["litres_sold"] == 200
    assert body["expected_amount"] == 150000
    assert body["shortfall"] == 10000

    # Overview: tank drew down 200 L (25000 - 200), pump meter rolled to 10200.
    ov = client.get("/app/api/fuel/overview", cookies=cook).json()
    t = next(x for x in ov["tanks"] if x["id"] == tank["id"])
    assert t["current_level_litres"] == 24800
    p = next(x for x in ov["pumps"] if x["id"] == pump["id"])
    assert p["current_meter"] == 10200
    assert ov["today"]["litres_sold"] == 200
    assert ov["today"]["shortfall"] == 10000


def test_closing_below_opening_rejected():
    cook = _fuel_owner("2348240000010")
    tank = client.post("/app/api/fuel/tanks", cookies=cook,
                       json={"name": "T", "product": "AGO"}).json()
    pump = client.post("/app/api/fuel/pumps", cookies=cook,
                       json={"name": "P", "product": "AGO", "tank_id": tank["id"],
                             "current_meter": 500}).json()
    sid = client.post("/app/api/fuel/shifts/open", cookies=cook, json={"pump_id": pump["id"]}).json()["id"]
    r = client.post(f"/app/api/fuel/shifts/{sid}/close", cookies=cook, json={"closing_meter": 400})
    assert r.status_code == 400


def test_dip_records_variance():
    cook = _fuel_owner("2348240000020")
    tank = client.post("/app/api/fuel/tanks", cookies=cook,
                       json={"name": "T", "product": "PMS", "current_level_litres": 8000}).json()
    r = client.post("/app/api/fuel/dips", cookies=cook,
                    json={"tank_id": tank["id"], "dipped_litres": 7900, "note": "morning"})
    assert r.status_code == 200, r.text
    assert r.json()["computed_litres"] == 8000
    assert r.json()["variance_litres"] == -100


def test_non_fuel_business_blocked():
    cook = _plain_owner("2348240000030")
    assert client.get("/app/api/fuel/overview", cookies=cook).status_code == 403
    assert client.post("/app/api/fuel/tanks", cookies=cook,
                       json={"name": "X", "product": "PMS"}).status_code == 403
