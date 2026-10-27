"""
Loyalty: off until the owner picks a stamp card or points. Only paid sales to
a named customer earn (credit sales once the debt is cleared); voids take it
back; the till's "Use reward" takes it off as a discount.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-loyalty-tests-0000000000000000")

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import CreditNote, Customer, LoyaltyEntry, Transaction, User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))
sent = []


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    sent.clear()
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda to, m, *a, **k: sent.append((to, m)) or True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _shop(**loyalty):
    phone = f"2348108{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Mama Shop", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    u = db.query(User).filter(User.phone == phone).first()
    u.subscription_plan = "PREMIUM"; u.subscription_status = "ACTIVE"
    ada = Customer(owner_phone=phone, name="ada", customer_phone="2348037777777", balance=0)
    db.add(ada); db.commit(); cid = ada.id; db.close()
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    if loyalty:
        r = client.put("/app/api/settings/business", cookies=cook, json={"values": loyalty})
        assert r.status_code == 200, r.text
    return phone, cook, cid


def _sell(phone, cook, cid, price=1000, paid=None, **extra):
    r = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "customer_id": cid, "payment_amount": price if paid is None else paid,
        "items": [{"name": "soap", "qty": 1, "unit_price": price}], **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _status(cook, cid):
    return client.get(f"/app/api/loyalty/customer/{cid}", cookies=cook).json()


def test_off_by_default_and_sales_before_switch_on_dont_count():
    phone, cook, cid = _shop()
    _sell(phone, cook, cid)
    assert _status(cook, cid) == {"mode": "off"}
    client.put("/app/api/settings/business", cookies=cook, json={"values": {"loyalty_mode": "stamps"}})
    assert _status(cook, cid)["stamps"] == 0                         # the earlier sale doesn't count


def test_stamps_credit_void_and_use_reward():
    phone, cook, cid = _shop(loyalty_mode="stamps", loyalty_stamps_needed=3)
    a = _sell(phone, cook, cid)
    _sell(phone, cook, cid, price=2000)
    credit = _sell(phone, cook, cid, price=5000, paid=0)            # on credit: no stamp yet
    s = _status(cook, cid)
    assert (s["stamps"], s["needed"], s["reward_ready"]) == (2, 3, False)
    assert "2 of 3 stamps" in [m for _to, m in sent][-1]           # on the WhatsApp receipt

    db = SessionLocal()                                              # the debt is paid
    db.add(Transaction(customer_id=cid, type="PAY", amount=5000, product="paid")); db.commit(); db.close()
    assert _status(cook, cid)["reward_ready"] is True

    client.post(f"/app/api/transactions/{a['receipt_id']}/void", cookies=cook, json={"reason": "mistake"})
    assert _status(cook, cid)["stamps"] == 2                         # void takes it back
    _sell(phone, cook, cid, price=700)
    assert _status(cook, cid)["stamps"] == 3

    r = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "customer_id": cid, "payment_amount": 2500, "loyalty_use": True,
        "items": [{"name": "rice", "qty": 1, "unit_price": 2000}, {"name": "salt", "qty": 1, "unit_price": 500}]})
    assert r.status_code == 200, r.text
    assert r.json()["discount"] == 500 and r.json()["total"] == 2000   # the cheaper item is free
    assert _status(cook, cid)["stamps"] == 0                         # used, and the free sale earns nothing

    client.post(f"/app/api/transactions/{r.json()['receipt_id']}/void", cookies=cook, json={"reason": "redo"})
    assert _status(cook, cid)["stamps"] == 3                         # voided: the reward comes back
    # not enough stamps → refused
    phone2, cook2, cid2 = _shop(loyalty_mode="stamps", loyalty_stamps_needed=3)
    assert client.post("/app/api/pos/save", cookies=cook2, json={
        "owner_phone": phone2, "customer_id": cid2, "payment_amount": 100, "loyalty_use": True,
        "items": [{"name": "x", "qty": 1, "unit_price": 100}]}).status_code == 400


def test_points_refund_use_and_expiry():
    phone, cook, cid = _shop(loyalty_mode="points", loyalty_points_percent=1)
    s1 = _sell(phone, cook, cid, price=10000)
    _sell(phone, cook, cid, price=5000)
    assert _status(cook, cid)["points"] == 150
    db = SessionLocal()                                              # ₦4,000 refunded on the first sale
    db.add(CreditNote(owner_phone=phone, number=1, customer_id=cid, sale_tx_id=s1["receipt_id"], kind="RETURN",
                      mode="REFUND", product="soap", quantity=1, amount=4000, reason="x")); db.commit(); db.close()
    assert _status(cook, cid)["points"] == 110
    r = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "customer_id": cid, "payment_amount": 0, "loyalty_use": True,
        "items": [{"name": "gum", "qty": 1, "unit_price": 80}]}).json()
    assert r["discount"] == 80 and r["total"] == 0
    assert _status(cook, cid)["points"] == 30
    assert "₦30 to use" in [m for _to, m in sent][-1]

    client.put("/app/api/settings/business", cookies=cook, json={"values": {"loyalty_expiry_months": 6}})
    db = SessionLocal()
    for e in db.query(LoyaltyEntry).filter(LoyaltyEntry.customer_id == cid).all():
        e.created_at = datetime.utcnow() - timedelta(days=200)       # all older than 6 months
    db.commit(); db.close()
    assert _status(cook, cid)["points"] == 0


def test_best_customers_and_settings_checks():
    phone, cook, cid = _shop(loyalty_mode="points")
    db = SessionLocal()
    bola = Customer(owner_phone=phone, name="bola", balance=0); db.add(bola); db.commit(); bid = bola.id; db.close()
    _sell(phone, cook, cid, price=3000)
    _sell(phone, cook, bid, price=9000)
    _sell(phone, cook, bid, price=1000)
    best = client.get("/app/api/loyalty/best", cookies=cook).json()
    assert [(c["name"], c["spent"], c["visits"], c["reward"]) for c in best["customers"]] == \
        [("Bola", 10000, 2, 100), ("Ada", 3000, 1, 30)]
    for bad in ({"loyalty_mode": "cashback"}, {"loyalty_stamps_needed": 1}, {"loyalty_points_percent": 50}):
        assert client.put("/app/api/settings/business", cookies=cook, json={"values": bad}).status_code == 400
    _p2, cook2, _c2 = _shop()
    assert client.get(f"/app/api/loyalty/customer/{cid}", cookies=cook2).status_code == 404


@pytest.mark.parametrize("text", [
    "how do I reward my customers?", "can I give customers a stamp card", "how do loyalty points work",
    "how to reward loyal customers",
])
def test_titi_explains_loyalty(text):
    from faq import detect_faq
    from messages import build_app_guide_message
    from parser import parse_message
    p = parse_message(text) or {}
    assert (p["topic"] if p.get("type") == "APP_GUIDE" else detect_faq(text)) == "loyalty"
    a = build_app_guide_message("loyalty")
    assert "Settings → Loyalty" in a and "Use reward" in a and "{till}" not in a and "POS" not in a


def test_discount_question_still_goes_to_discount():
    from faq import detect_faq
    assert detect_faq("how do I give a discount") == "discount"
