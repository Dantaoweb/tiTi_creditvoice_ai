"""
Phase 2: branch isolation is enforced on reads.
A branch-assigned staff sees only their branch; the owner sees everything.
"""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-branch-enforcement-00000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, Customer, Transaction, Branch

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
    """Fresh owner (unique phone) with two branches; a customer + a sale in each;
    a staff assigned to branch A. Returns (owner_phone, staff_phone)."""
    n = next(_seq)
    owner_phone = f"234807777{n:04d}"
    staff_phone = f"234807778{n:04d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": owner_phone, "pin": "5678"})
    db = SessionLocal()
    owner = db.query(User).filter(User.phone == owner_phone).first()
    owner.subscription_plan = "PRO"; owner.subscription_status = "ACTIVE"
    a = Branch(owner_phone=owner_phone, name="Ikeja", is_default=True)
    b = Branch(owner_phone=owner_phone, name="Lekki", is_default=False)
    db.add_all([a, b]); db.commit()
    a_id, b_id = a.id, b.id

    staff = User(phone=staff_phone, name="Sade", role="delegate", parent_id=owner.id,
                 branch_id=a_id, can_view_all_transactions=False,
                 recovery_pin_hash=web_auth._hash_pin("1234"), subscription_status="ACTIVE")
    db.add(staff); db.commit()
    staff_id = staff.id

    ca = Customer(name="AdaA", owner_phone=owner_phone, branch_id=a_id, balance=5000)
    cb = Customer(name="BolaB", owner_phone=owner_phone, branch_id=b_id, balance=3000)
    db.add_all([ca, cb]); db.commit()
    db.add(Transaction(customer_id=ca.id, type="BUY", amount=5000, branch_id=a_id,
                       recorded_by_id=staff_id, message_id=f"m-{uuid.uuid4()}"))
    db.add(Transaction(customer_id=cb.id, type="BUY", amount=3000, branch_id=b_id,
                       recorded_by_id=owner.id, message_id=f"m-{uuid.uuid4()}"))
    db.commit(); db.close()
    return owner_phone, staff_phone


def _login(phone, pin):
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": pin}).cookies


def test_branch_staff_sees_only_their_branch():
    _owner_phone, staff_phone = _setup()
    staff = _login(staff_phone, "1234")

    txns = client.get("/app/api/transactions", cookies=staff).json()["transactions"]
    assert len(txns) == 1 and txns[0]["amount"] == 5000     # Ikeja only, not Lekki

    custs = {c["name"] for c in client.get("/app/api/customers", cookies=staff).json()["customers"]}
    assert custs == {"AdaA"}                                 # not BolaB

    dash = client.get("/app/api/dashboard", cookies=staff).json()
    # Debtors on the dashboard are branch-scoped too
    debtor_names = {d["name"] for d in dash.get("debtors", [])}
    assert "BolaB" not in debtor_names


def test_owner_sees_all_branches():
    owner_phone, _staff_phone = _setup()
    owner = _login(owner_phone, "5678")
    txns = client.get("/app/api/transactions", cookies=owner).json()["transactions"]
    assert len(txns) == 2
    custs = {c["name"] for c in client.get("/app/api/customers", cookies=owner).json()["customers"]}
    assert custs == {"AdaA", "BolaB"}
