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
    """Fresh owner with two branches (A=Ikeja, B=Lekki). In branch A: a sale by a
    regular staff (AdaA) and a colleague sale by the owner (AdaA2). In branch B:
    a sale (BolaB). A regular staff and a branch admin are both on branch A.
    Returns (owner_phone, staff_phone, admin_phone)."""
    n = next(_seq)
    owner_phone = f"234807777{n:04d}"
    staff_phone = f"234807778{n:04d}"
    admin_phone = f"234807779{n:04d}"
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
    admin = User(phone=admin_phone, name="Bimpe", role="delegate", parent_id=owner.id,
                 branch_id=a_id, can_view_all_transactions=True,   # branch admin
                 recovery_pin_hash=web_auth._hash_pin("1234"), subscription_status="ACTIVE")
    db.add_all([staff, admin]); db.commit()
    staff_id = staff.id

    ca = Customer(name="AdaA", owner_phone=owner_phone, branch_id=a_id, balance=5000)
    ca2 = Customer(name="AdaA2", owner_phone=owner_phone, branch_id=a_id, balance=7000)
    cb = Customer(name="BolaB", owner_phone=owner_phone, branch_id=b_id, balance=3000)
    db.add_all([ca, ca2, cb]); db.commit()
    db.add(Transaction(customer_id=ca.id, type="BUY", amount=5000, branch_id=a_id,
                       recorded_by_id=staff_id, message_id=f"m-{uuid.uuid4()}"))     # staff's own
    db.add(Transaction(customer_id=ca2.id, type="BUY", amount=7000, branch_id=a_id,
                       recorded_by_id=owner.id, message_id=f"m-{uuid.uuid4()}"))      # colleague, same branch
    db.add(Transaction(customer_id=cb.id, type="BUY", amount=3000, branch_id=b_id,
                       recorded_by_id=owner.id, message_id=f"m-{uuid.uuid4()}"))      # other branch
    db.commit(); db.close()
    return owner_phone, staff_phone, admin_phone


def _login(phone, pin):
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": pin}).cookies


def test_regular_staff_sees_only_own_records():
    _o, staff_phone, _a = _setup()
    staff = _login(staff_phone, "1234")

    txns = client.get("/app/api/transactions", cookies=staff).json()["transactions"]
    assert [t["amount"] for t in txns] == [5000]            # only their own sale
    custs = {c["name"] for c in client.get("/app/api/customers", cookies=staff).json()["customers"]}
    assert custs == {"AdaA"}                                 # not the colleague's AdaA2, not BolaB


def test_branch_admin_sees_whole_branch_not_others():
    _o, _s, admin_phone = _setup()
    admin = _login(admin_phone, "1234")

    amounts = sorted(t["amount"] for t in client.get("/app/api/transactions", cookies=admin).json()["transactions"])
    assert amounts == [5000, 7000]                           # both Ikeja sales, not Lekki's 3000
    custs = {c["name"] for c in client.get("/app/api/customers", cookies=admin).json()["customers"]}
    assert custs == {"AdaA", "AdaA2"}                        # whole branch, not BolaB


def test_owner_sees_all_branches():
    owner_phone, _s, _a = _setup()
    owner = _login(owner_phone, "5678")
    txns = client.get("/app/api/transactions", cookies=owner).json()["transactions"]
    assert len(txns) == 3
    custs = {c["name"] for c in client.get("/app/api/customers", cookies=owner).json()["customers"]}
    assert custs == {"AdaA", "AdaA2", "BolaB"}


def test_new_records_stamped_with_creators_branch():
    # New records are tagged to the creator's branch. A regular staff records a
    # customer (allowed); a branch admin adds stock (stock is admin-only). Both
    # land in branch A and stay visible to the branch admin.
    owner_phone, staff_phone, admin_phone = _setup()
    staff = _login(staff_phone, "1234")
    admin = _login(admin_phone, "1234")

    assert client.post("/app/api/customers", cookies=staff,
                       json={"owner_phone": owner_phone, "name": "Fresh"}).status_code == 200
    # Stock is owner/branch-admin only — a regular staff is blocked
    assert client.post("/app/api/inventory", cookies=staff,
                       json={"owner_phone": owner_phone, "name": "blocked", "selling_price": 100, "quantity": 3}).status_code == 403
    # The branch admin can add it, stamped to their branch
    assert client.post("/app/api/inventory", cookies=admin,
                       json={"owner_phone": owner_phone, "name": "newstock", "selling_price": 100, "quantity": 3}).status_code == 200

    db = SessionLocal()
    branch_a = db.query(User).filter(User.phone == staff_phone).first().branch_id
    from models import InventoryItem
    assert db.query(Customer).filter_by(owner_phone=owner_phone, name="Fresh").first().branch_id == branch_a
    assert db.query(InventoryItem).filter_by(owner_phone=owner_phone, name="newstock").first().branch_id == branch_a
    db.close()

    names = {c["name"] for c in client.get("/app/api/customers", cookies=admin).json()["customers"]}
    assert "Fresh" in names
    stock = {i["name"] for i in client.get("/app/api/inventory", cookies=admin).json()["items"]}
    assert "newstock" in stock
