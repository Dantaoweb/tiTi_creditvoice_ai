"""
Security of the recent features: numbers must be real numbers, branch staff
see only their branch, crash reports can't be spammed.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-security-recent-000000000")

import json

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import Branch, CameraCrashReport, Customer, InventoryItem, User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda *a, **k: True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _login(phone, pin):
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": pin}).cookies


def _post_raw(path, cook, payload):
    """Send NaN / Infinity as a crafted request would — the normal client
    refuses to."""
    return client.post(path, cookies=cook, content=json.dumps(payload, allow_nan=True),
                       headers={"Content-Type": "application/json"})


def _business():
    """An owner (Premium) with two branches, cement in each, a customer in
    each, a branch admin for branch A and a regular staff in branch A."""
    phone = f"2348101{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Bello Cement", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    try:
        owner = db.query(User).filter_by(phone=phone).one()
        owner.subscription_plan = "PREMIUM"; owner.subscription_status = "ACTIVE"
        a = Branch(owner_phone=phone, name="Ikeja", is_default=True)
        b = Branch(owner_phone=phone, name="Lekki")
        db.add_all([a, b]); db.flush()
        cem_a = InventoryItem(owner_phone=phone, name="cement", unit="bag", quantity=100,
                              selling_price=9000, is_available=True, branch_id=a.id)
        cem_b = InventoryItem(owner_phone=phone, name="cement", unit="bag", quantity=100,
                              selling_price=9000, is_available=True, branch_id=b.id)
        ade = Customer(owner_phone=phone, name="ade", balance=0, branch_id=a.id)
        bola = Customer(owner_phone=phone, name="bola", balance=0, branch_id=b.id)
        admin_phone = f"2348101{next(_seq):06d}"
        clerk_phone = f"2348101{next(_seq):06d}"
        db.add_all([cem_a, cem_b, ade, bola,
                    User(phone=admin_phone, name="Sade", role="delegate", parent_id=owner.id,
                         branch_id=a.id, can_view_all_transactions=True, subscription_status="ACTIVE",
                         recovery_pin_hash=web_auth._hash_pin("1234")),
                    User(phone=clerk_phone, name="Tayo", role="delegate", parent_id=owner.id,
                         branch_id=a.id, can_view_all_transactions=False, subscription_status="ACTIVE",
                         recovery_pin_hash=web_auth._hash_pin("1234"))])
        db.commit()
        ids = {"a": a.id, "b": b.id, "cem_a": cem_a.id, "cem_b": cem_b.id, "ade": ade.id, "bola": bola.id,
               "clerk": _login(clerk_phone, "1234")}
    finally:
        db.close()
    return phone, _login(phone, "5678"), _login(admin_phone, "1234"), ids


def _part_sale(phone, cook, branch, item, customer, qty=10, delivered=0, extra=None):
    line = {"inventory_item_id": item, "name": "cement", "qty": qty, "unit": "bag",
            "unit_price": 9000, "delivered_qty": delivered, **(extra or {})}
    return _post_raw("/app/api/pos/save", cook, {
        "owner_phone": phone, "customer_id": customer, "branch_id": branch,
        "items": [line], "payment_amount": 0})


def test_not_a_number_is_refused_everywhere():
    phone, owner, _staff, ids = _business()
    r = _part_sale(phone, owner, ids["a"], ids["cem_a"], ids["ade"], delivered=float("nan"))
    assert r.status_code == 400, r.text
    r = _part_sale(phone, owner, ids["a"], ids["cem_a"], ids["ade"], extra={"qty": float("inf")})
    assert r.status_code == 400

    assert _part_sale(phone, owner, ids["a"], ids["cem_a"], ids["ade"]).status_code == 200
    [g] = client.get("/app/api/deliveries", cookies=owner).json()["goods"]
    for path, body in [("deliveries/goods", {"quantity": float("nan")}),
                       ("deliveries/goods/cancel", {"quantity": float("nan"), "mode": "CREDIT", "reason": "x"})]:
        r = _post_raw(f"/app/api/{path}", owner, {"customer_id": ids["ade"], "key": g["key"], **body})
        assert r.status_code == 400, (path, r.text)
    db = SessionLocal()
    try:
        assert db.get(InventoryItem, ids["cem_a"]).quantity == 100     # untouched
    finally:
        db.close()


def test_branch_staff_see_and_act_on_their_branch_only():
    phone, owner, staff, ids = _business()
    _part_sale(phone, owner, ids["a"], ids["cem_a"], ids["ade"])
    sale_b = _part_sale(phone, owner, ids["b"], ids["cem_b"], ids["bola"]).json()["receipt_id"]

    assert {g["customer"] for g in client.get("/app/api/deliveries", cookies=owner).json()["goods"]} == {"Ade", "Bola"}
    mine = client.get("/app/api/deliveries", cookies=staff).json()["goods"]
    assert {g["customer"] for g in mine} == {"Ade"}                      # not Lekki's Bola

    bola_key = [g for g in client.get("/app/api/deliveries", cookies=owner).json()["goods"]
                if g["customer"] == "Bola"][0]["key"]
    r = client.post("/app/api/deliveries/goods", cookies=staff,
                    json={"customer_id": ids["bola"], "key": bola_key, "quantity": 1})
    assert r.status_code == 400                                            # nothing of hers in his branch
    assert client.get(f"/app/api/sales/{sale_b}/returnable", cookies=staff).status_code == 404

    # A regular staff in the branch sees only what they recorded themselves
    assert client.get("/app/api/deliveries", cookies=ids["clerk"]).json()["goods"] == []

    # Product checks see the branch's own stock only
    similar = client.get("/app/api/inventory/similar", cookies=staff, params={"name": "cement"}).json()
    assert [p["id"] for p in similar["exact"] + similar["similar"]] == [ids["cem_a"]]


def test_crash_reports_cannot_be_spammed():
    _phone, owner, _staff, _ids = _business()
    for _ in range(8):
        client.post("/app/api/client/camera-crash", cookies=owner,
                    json={"user_agent": "SM-A125F", "stage": "opening"})
    me = client.get("/app/api/auth/me", cookies=owner).json()["id"]
    db = SessionLocal()
    try:
        assert db.query(CameraCrashReport).filter_by(user_id=me).count() == 5
    finally:
        db.close()
