"""
Stock management is owner / branch-admin only. A regular (non-admin) staff can
record sales but must not add, edit, bulk-import or adjust inventory.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-stock-permission-000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, InventoryItem

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner_and_staff(full_access):
    n = next(_seq)
    owner_phone = f"234805555{n:04d}"
    staff_phone = f"234805556{n:04d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": owner_phone, "pin": "5678"})
    db = SessionLocal()
    owner = db.query(User).filter(User.phone == owner_phone).first()
    owner.subscription_plan = "PRO"; owner.subscription_status = "ACTIVE"
    staff = User(phone=staff_phone, name="S", role="delegate", parent_id=owner.id,
                 can_view_all_transactions=full_access,
                 recovery_pin_hash=web_auth._hash_pin("1234"), subscription_status="ACTIVE")
    db.add(staff); db.commit(); db.close()
    o = client.post("/app/api/auth/login", json={"phone": owner_phone, "pin": "5678"}).cookies
    s = client.post("/app/api/auth/login", json={"phone": staff_phone, "pin": "1234"}).cookies
    return owner_phone, o, s


def _add(cookies, owner_phone, name):
    return client.post("/app/api/inventory", cookies=cookies,
                       json={"owner_phone": owner_phone, "name": name, "selling_price": 100, "quantity": 5})


def test_regular_staff_cannot_manage_stock():
    owner_phone, _owner, staff = _owner_and_staff(full_access=False)
    assert _add(staff, owner_phone, "sugar").status_code == 403
    assert client.post("/app/api/inventory/bulk", cookies=staff,
                       json={"owner_phone": owner_phone, "names": ["rice"]}).status_code == 403
    # /auth/me tells the frontend to hide the controls
    me = client.get("/app/api/auth/me", cookies=staff).json()
    assert me["full_access"] is False


def test_owner_and_branch_admin_can_manage_stock():
    owner_phone, owner, _s = _owner_and_staff(full_access=False)
    assert _add(owner, owner_phone, "owned").status_code == 200

    owner_phone2, _o2, admin = _owner_and_staff(full_access=True)   # branch admin
    r = _add(admin, owner_phone2, "adminstock")
    assert r.status_code == 200, r.text
    assert client.get("/app/api/auth/me", cookies=admin).json()["full_access"] is True


def test_regular_staff_cannot_edit_or_adjust():
    owner_phone, owner, staff = _owner_and_staff(full_access=False)
    item_id = _add(owner, owner_phone, "milk").json()["id"]
    assert client.put(f"/app/api/inventory/{item_id}", cookies=staff,
                      json={"selling_price": 999}).status_code == 403
    assert client.post(f"/app/api/inventory/{item_id}/adjust", cookies=staff,
                       json={"qty_delta": 5, "note": "x"}).status_code == 403
