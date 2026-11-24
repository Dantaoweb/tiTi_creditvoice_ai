"""
Staff: inviting never takes over an existing account; an admin sees the whole
business by default (branch or not) and the owner picks what they can't see;
customers with no branch are served by every branch; staff see the customers
they added; removing staff signs them out.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-staff-admin-000000000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import AppNotification, Customer, InventoryItem, User

_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda *a, **k: True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _phone(p="2347141"):
    return f"{p}{next(_seq):06d}"


def _owner(name="Bisi Stores"):
    c = TestClient(app)
    phone = _phone()
    c.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": "5678"})
    db = SessionLocal()
    u = db.query(User).filter(User.phone == phone).first()
    u.subscription_plan = "PREMIUM"; u.subscription_status = "ACTIVE"
    db.commit(); db.close()
    c.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"})
    return c, phone


def _invite_and_join(owner_c, name="Sade", admin=False, branch_id=None, phone=None):
    phone = phone or _phone("2347142")
    r = owner_c.post("/app/api/staff/invite", json={"name": name, "phone": phone, "branch_id": branch_id,
                                                    "as_branch_admin": admin and branch_id is not None})
    assert r.status_code == 200, r.text
    staff = TestClient(app)
    j = staff.post("/app/api/staff/accept", json={"phone": phone, "code": r.json()["invite_code"], "new_pin": "1234"})
    assert j.status_code == 200, j.text
    if not j.json().get("signed_in"):
        staff.post("/app/api/auth/login", json={"phone": phone, "pin": "1234"})
    db = SessionLocal()
    sid = db.query(User).filter(User.phone == phone).first().id
    db.close()
    if admin and branch_id is None:
        assert owner_c.post(f"/app/api/staff/{sid}/access", json={"full_access": True}).status_code == 200
    return staff, sid, phone


def _customer(owner_phone, name, branch_id=None, balance=0):
    db = SessionLocal()
    try:
        c = Customer(owner_phone=owner_phone, name=name, balance=balance, branch_id=branch_id)
        db.add(c); db.commit()
        return c.id
    finally:
        db.close()


def _names(client, **params):
    r = client.get("/app/api/customers", params=params)
    assert r.status_code == 200, r.text
    return {c["name"] for c in r.json()["customers"]}


# ── Inviting never takes over an existing account ────────────────────────────

def test_a_number_that_runs_its_own_business_cant_be_taken():
    owner, _p = _owner()
    victim, vphone = _owner("Victim Shop")
    _customer(vphone, "victim's customer")
    r = owner.post("/app/api/staff/invite", json={"name": "Grab", "phone": vphone})
    assert r.status_code == 409 and "its own business" in r.json()["detail"]
    db = SessionLocal()
    v = db.query(User).filter(User.phone == vphone).first()
    assert v.parent_id is None and v.role != "delegate_pending"      # untouched
    db.close()
    assert "victim's customer" in _names(victim)                      # still their own business


def test_an_existing_empty_account_changes_only_when_it_accepts():
    owner, ophone = _owner()
    other = TestClient(app)
    sphone = _phone("2347143")
    other.post("/app/api/auth/register", json={"name": "Tunde", "phone": sphone, "pin": "4321"})
    r = owner.post("/app/api/staff/invite", json={"name": "Tunde", "phone": sphone})
    assert r.status_code == 200
    db = SessionLocal()
    t = db.query(User).filter(User.phone == sphone).first()
    assert t.parent_id is None and t.invite_owner_id is not None     # held, not changed
    db.close()
    members = owner.get("/app/api/staff/members").json()["members"]
    assert any(m["phone"] == sphone and m["pending"] for m in members)
    j = TestClient(app).post("/app/api/staff/accept", json={"phone": sphone, "code": r.json()["invite_code"]})
    assert j.status_code == 200, j.text
    db = SessionLocal()
    t = db.query(User).filter(User.phone == sphone).first()
    owner_id = db.query(User).filter(User.phone == ophone).first().id
    assert t.parent_id == owner_id and t.role == "delegate" and t.invite_owner_id is None
    assert db.query(AppNotification).filter(AppNotification.owner_phone == ophone,
                                            AppNotification.event_type == "staff_joined").count() == 1
    db.close()


# ── Admins see the whole business; the owner picks what they can't ──────────

def test_admin_without_a_branch_serves_every_customer():
    owner, ophone = _owner()
    _customer(ophone, "mama bola", balance=5000)
    admin, aid, _ = _invite_and_join(owner, "Admin Ade", admin=True)
    cashier, cid, _ = _invite_and_join(owner, "Cashier Kemi")
    assert "mama bola" in _names(admin) and "mama bola" in _names(admin, debtors="true")
    # Ordinary staff see the business's customers to serve them (the default)…
    assert "mama bola" in _names(cashier)
    assert cashier.post("/app/api/customers", json={"owner_phone": ophone, "name": "Kemi's buyer"}).status_code == 200
    # …or only their own, when the owner chooses
    assert owner.post(f"/app/api/staff/{cid}/customers", json={"on": False}).json()["sees_customers"] is False
    assert "mama bola" not in _names(cashier)
    assert "kemi's buyer" in {n.lower() for n in _names(cashier)}      # the one they added
    m = next(x for x in owner.get("/app/api/staff/members").json()["members"] if x["id"] == cid)
    assert m["sees_customers"] is False
    assert cashier.post(f"/app/api/staff/{cid}/customers", json={"on": True}).status_code == 403   # owner only
    # The admin sees profit, the dashboard, expenses and supplier debts by default
    assert admin.get("/app/api/dashboard").status_code == 200
    assert admin.get("/app/api/expenses").status_code == 200
    assert admin.get("/app/api/suppliers").status_code == 200


def test_owner_picks_what_an_admin_cant_see():
    owner, ophone = _owner()
    admin, aid, _ = _invite_and_join(owner, "Admin Ade", admin=True)
    db = SessionLocal()
    it = InventoryItem(owner_phone=ophone, name="rice", selling_price=1000, cost_price=700, quantity=10, is_available=True)
    db.add(it); db.commit(); item = it.id; db.close()
    r = owner.put(f"/app/api/staff/{aid}/limits", json={"limits": ["dashboard", "expenses", "suppliers", "stock", "profit"]})
    assert r.status_code == 200 and set(r.json()["limits"]) == {"dashboard", "expenses", "suppliers", "stock", "profit"}
    me = admin.get("/app/api/auth/me").json()
    assert set(me["staff_limits"]) == {"dashboard", "expenses", "suppliers", "stock", "profit"}
    for path in ("/app/api/dashboard", "/app/api/reports/charts", "/app/api/expenses", "/app/api/suppliers"):
        assert admin.get(path).status_code == 403, path
    assert admin.post(f"/app/api/inventory/{item}/adjust", json={"qty_delta": -1, "reason": "damaged"}).status_code == 403
    # Profit and cost prices hidden from the stock list
    rows = admin.get("/app/api/inventory").json()
    row = next(i for i in (rows.get("items") or rows.get("inventory") or []) if i["name"].lower() == "rice")
    assert not row.get("cost_price")
    # …but they still sell and see customers
    assert admin.get("/app/api/customers").status_code == 200
    assert owner.put(f"/app/api/staff/{aid}/limits", json={"limits": ["nonsense"]}).status_code == 400
    # A staff member can't change their own limits
    assert admin.put(f"/app/api/staff/{aid}/limits", json={"limits": []}).status_code == 403


def test_branches_admin_sees_all_unless_kept_to_their_branch():
    owner, ophone = _owner()
    a = owner.post("/app/api/branches", json={"name": "Ikeja"}).json()["id"]
    b = owner.post("/app/api/branches", json={"name": "Lekki"}).json()["id"]
    _customer(ophone, "ikeja buyer", branch_id=a)
    _customer(ophone, "lekki buyer", branch_id=b)
    _customer(ophone, "everyone's buyer", branch_id=None)
    admin, aid, _ = _invite_and_join(owner, "Branch Boss", admin=True, branch_id=a)
    assert {"ikeja buyer", "lekki buyer", "everyone's buyer"} <= _names(admin)       # whole business by default
    owner.put(f"/app/api/staff/{aid}/limits", json={"limits": ["own_branch"]})
    seen = _names(admin)
    assert "ikeja buyer" in seen and "everyone's buyer" in seen and "lekki buyer" not in seen


def test_removing_staff_signs_them_out():
    owner, _ = _owner()
    staff, sid, sphone = _invite_and_join(owner, "Leaver")
    assert staff.get("/app/api/customers").status_code == 200
    assert owner.post(f"/app/api/staff/{sid}/remove").status_code == 200
    assert staff.get("/app/api/customers").status_code == 401
    db = SessionLocal()
    u = db.query(User).filter(User.phone == sphone).first()
    assert u.parent_id is None
    db.close()
    other, _ = _owner()
    assert other.post(f"/app/api/staff/{sid}/remove").status_code == 404           # not theirs


def test_titi_explains_staff_admins():
    from messages import build_app_guide_message
    from models import User as _U
    a = build_app_guide_message("staff", _U(phone="1", business_type="provision_store"))
    assert "Make admin" in a and "can't see" in a and "Remove from business" in a
    assert "business's customers" in a and "cost prices" in a
    assert "receive a WhatsApp message" not in a



def test_ordinary_staff_never_see_cost_prices():
    owner, ophone = _owner()
    db = SessionLocal()
    db.add(InventoryItem(owner_phone=ophone, name="beans", selling_price=1500, cost_price=1100, quantity=20,
                         is_available=True))
    db.commit(); db.close()
    cashier, _cid, _ = _invite_and_join(owner, "Cashier Ola")
    admin, _aid, _ = _invite_and_join(owner, "Admin Femi", admin=True)

    def cost(client, path, key):
        d = client.get(path, params={"owner_phone": ophone}).json()
        return next(i for i in d[key] if i["name"].lower() == "beans").get("cost_price")
    assert cost(cashier, "/app/api/inventory", "items") is None
    assert cost(cashier, "/app/api/pos/products", "products") is None
    assert cost(admin, "/app/api/inventory", "items") == 1100           # admins do, unless kept from profit
    assert cost(owner, "/app/api/pos/products", "products") == 1100


def test_inviting_can_choose_only_their_own_customers():
    owner, ophone = _owner()
    _customer(ophone, "owner's buyer")
    phone = _phone("2347144")
    r = owner.post("/app/api/staff/invite", json={"name": "Only Own", "phone": phone, "see_customers": False})
    staff = TestClient(app)
    staff.post("/app/api/staff/accept", json={"phone": phone, "code": r.json()["invite_code"], "new_pin": "1234"})
    assert "owner's buyer" not in _names(staff)
