"""
Phase 4: branch management is owner-only, and deleting a branch re-homes its
data instead of orphaning it (which would make it invisible under isolation).
"""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-branch-admin-ops-0000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, Customer, Transaction, Branch, InventoryItem

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _setup():
    n = next(_seq)
    owner_phone = f"234806666{n:04d}"
    staff_phone = f"234806667{n:04d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": owner_phone, "pin": "5678"})
    db = SessionLocal()
    owner = db.query(User).filter(User.phone == owner_phone).first()
    # Multi-branch is a Premium capability (Pro is capped at 1 branch).
    owner.subscription_plan = "PREMIUM"; owner.subscription_status = "ACTIVE"
    main = Branch(owner_phone=owner_phone, name="Main", is_default=True)
    extra = Branch(owner_phone=owner_phone, name="Extra", is_default=False)
    db.add_all([main, extra]); db.commit()
    main_id, extra_id = main.id, extra.id
    staff = User(phone=staff_phone, name="Staff", role="delegate", parent_id=owner.id,
                 branch_id=extra_id, recovery_pin_hash=web_auth._hash_pin("1234"),
                 subscription_status="ACTIVE")
    db.add(staff); db.commit()
    db.close()
    return owner_phone, staff_phone, main_id, extra_id


def _login(phone, pin):
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": pin}).cookies


def test_staff_cannot_manage_branches():
    _o, staff_phone, main_id, _e = _setup()
    staff = _login(staff_phone, "1234")
    assert client.post("/app/api/branches", cookies=staff, json={"name": "Sneaky"}).status_code == 403
    assert client.delete(f"/app/api/branches/{main_id}", cookies=staff).status_code == 403
    assert client.post(f"/app/api/branches/{main_id}/default", cookies=staff).status_code == 403


def test_owner_can_manage_branches():
    owner_phone, _s, main_id, _e = _setup()
    owner = _login(owner_phone, "5678")
    created = client.post("/app/api/branches", cookies=owner, json={"name": "Third"})
    assert created.status_code == 200
    assert client.post(f"/app/api/branches/{main_id}/default", cookies=owner).status_code == 200


def test_deleting_a_branch_rehomes_its_data():
    owner_phone, staff_phone, main_id, extra_id = _setup()

    db = SessionLocal()
    c = Customer(name="Ext", owner_phone=owner_phone, branch_id=extra_id)
    i = InventoryItem(owner_phone=owner_phone, name="extstock", branch_id=extra_id)
    db.add_all([c, i]); db.commit()
    db.add(Transaction(customer_id=c.id, type="BUY", amount=100, branch_id=extra_id,
                       message_id=f"m-{uuid.uuid4()}"))
    db.commit(); db.close()

    owner = _login(owner_phone, "5678")
    r = client.delete(f"/app/api/branches/{extra_id}", cookies=owner)
    assert r.status_code == 200, r.text
    assert r.json()["reassigned_to_branch_id"] == main_id

    db = SessionLocal()
    assert db.query(Customer).filter_by(name="Ext").first().branch_id == main_id
    assert db.query(InventoryItem).filter_by(name="extstock").first().branch_id == main_id
    assert db.query(User).filter_by(phone=staff_phone).first().branch_id == main_id
    assert db.query(Transaction).filter_by(branch_id=extra_id).count() == 0
    db.close()
