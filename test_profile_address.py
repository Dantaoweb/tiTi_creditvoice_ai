"""
Profile edit + business/branch address on receipts.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-profile-address-00000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User

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
    phone = f"234801111{n:04d}"
    client.post("/app/api/auth/register", json={"name": "Ada", "phone": phone, "pin": "5678"})
    db = SessionLocal(); u = db.query(User).filter(User.phone == phone).first()
    u.subscription_plan = "PRO"; u.subscription_status = "ACTIVE"; db.commit(); db.close()
    return phone, client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def test_owner_edits_profile_incl_address():
    phone, cook = _pro_owner()
    r = client.put("/app/api/auth/profile", cookies=cook,
                   json={"name": "Ada Stores", "business_type_label": "Boutique",
                         "address": "12 Market Rd, Ikeja"})
    assert r.status_code == 200, r.text
    me = client.get("/app/api/auth/me", cookies=cook).json()
    assert me["name"] == "Ada Stores"
    assert me["business_type_label"] == "Boutique"
    assert me["address"] == "12 Market Rd, Ikeja"


def test_staff_cannot_change_business_address():
    owner_phone, _c = _pro_owner()
    db = SessionLocal()
    owner = db.query(User).filter(User.phone == owner_phone).first()
    owner.address = "OWNER ADDR"
    sp = f"234809111{next(_seq):04d}"
    staff = User(phone=sp, name="Staff", role="delegate", parent_id=owner.id,
                 recovery_pin_hash=web_auth._hash_pin("1234"), subscription_status="ACTIVE")
    db.add(staff); db.commit(); db.close()
    scook = client.post("/app/api/auth/login", json={"phone": sp, "pin": "1234"}).cookies

    r = client.put("/app/api/auth/profile", cookies=scook,
                   json={"name": "Staff New Name", "address": "HACKED"})
    assert r.status_code == 200
    db = SessionLocal()
    assert db.query(User).filter(User.phone == sp).first().name == "Staff New Name"   # own name ok
    assert db.query(User).filter(User.phone == owner_phone).first().address == "OWNER ADDR"  # untouched
    db.close()


def test_branch_address_create_edit_and_on_receipt():
    phone, cook = _pro_owner()
    # set business address
    client.put("/app/api/auth/profile", cookies=cook, json={"address": "HQ Road"})
    # create branch with address
    b = client.post("/app/api/branches", cookies=cook, json={"name": "Ikeja", "address": "5 Allen Ave"})
    assert b.status_code == 200 and b.json()["address"] == "5 Allen Ave"
    bid = b.json()["id"]
    # edit it
    e = client.put(f"/app/api/branches/{bid}", cookies=cook, json={"name": "Ikeja", "address": "7 Allen Ave"})
    assert e.status_code == 200 and e.json()["address"] == "7 Allen Ave"
    # list returns address
    lst = client.get("/app/api/branches", cookies=cook).json()["branches"]
    assert any(x["address"] == "7 Allen Ave" for x in lst)

    # a sale in that branch shows the branch address on its receipt
    r = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "branch_id": bid,
        "items": [{"name": "x", "qty": 1, "unit_price": 500}], "payment_amount": 500})
    assert r.status_code == 200, r.text
    tx_id = r.json()["receipt_id"]
    rec = client.get(f"/app/api/pos/receipt/{tx_id}", cookies=cook).json()
    assert rec["biz_address"] == "HQ Road"
    assert rec["branch_address"] == "7 Allen Ave"
    assert rec["branch_name"] == "Ikeja"
