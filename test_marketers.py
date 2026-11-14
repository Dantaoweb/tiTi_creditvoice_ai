"""
Marketers (marketers.py): admin adds a marketer; businesses that sign up with
their code — web or WhatsApp — are theirs (free GO trial, no referral); every
plan payment, renewals too, earns the marketer their %; admin marks bonuses
paid; the marketer sees their own numbers.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-marketers-000000000000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
from admin import ROLE_APP_ADMIN
from database import SessionLocal
from main import app
from models import AppAdminRole, MarketerEarning, Referral, User
from parser import normalize_phone
from subscriptions import create_subscription_payment_request

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda *a, **k: True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _phone(prefix="2347101"):
    return f"{prefix}{next(_seq):06d}"


def _register(phone, ref=None, name="Ade Stores"):
    return client.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": "5678",
                                                       **({"ref_code": ref} if ref else {})})


def _login(phone):
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def _admin():
    phone = _phone("2347102")
    _register(phone, name="Admin")
    db = SessionLocal()
    db.add(AppAdminRole(phone=normalize_phone(phone), role=ROLE_APP_ADMIN, is_active=True))
    db.commit(); db.close()
    return _login(phone)


def _pay(admin, biz_phone, plan="PREMIUM", period="MONTHLY"):
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.phone == biz_phone).first()
        p = create_subscription_payment_request(db, owner, plan, period)
        p.payment_method = "BANK_TRANSFER"
        db.commit()
        pid, amount = p.id, p.amount
    finally:
        db.close()
    r = client.post(f"/app/api/admin/subscription-payments/{pid}/approve", cookies=admin)
    assert r.status_code == 200, r.text
    return amount


def test_the_whole_journey():
    admin = _admin()
    r = client.put("/app/api/admin/marketer-settings", cookies=admin, json={"default_percent": 10})
    assert r.json()["default_percent"] == 10

    mphone = _phone()
    r = client.post("/app/api/admin/marketers", cookies=admin, json={"name": "Tunde Bello", "phone": "0" + mphone[3:]})
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["code"].startswith("MKTUND") and m["percent"] == 10 and m["phone"] == mphone
    assert m["link"].endswith(f"ref={m['code']}")

    # A business signs up with the marketer's code: a free GO trial, no referral
    biz = _phone()
    me = _register(biz, ref=m["code"].lower()).json()
    assert me["user"]["plan"] == "GO"
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == biz).first()
        assert u.marketer_id == m["id"] and u.referred_by_code is None
        assert db.query(Referral).filter(Referral.referee_phone == biz).count() == 0
    finally:
        db.close()

    # Trial alone earns nothing; each payment does — renewals too
    assert client.get(f"/app/api/admin/marketers/{m['id']}", cookies=admin).json()["bonus_total"] == 0
    a1 = _pay(admin, biz)
    a2 = _pay(admin, biz)
    detail = client.get(f"/app/api/admin/marketers/{m['id']}", cookies=admin).json()
    assert detail["businesses"] == 1 and detail["paying"] == 1
    assert detail["bonus_total"] == round(a1 * 0.1) + round(a2 * 0.1) and detail["bonus_owed"] == detail["bonus_total"]
    assert [e["renewal"] for e in detail["earnings"]] == [True, False]       # newest first

    # Their own % overrides the default, for payments from now on
    client.put(f"/app/api/admin/marketers/{m['id']}", cookies=admin, json={"percent": 15})
    a3 = _pay(admin, biz, period="YEARLY")
    detail = client.get(f"/app/api/admin/marketers/{m['id']}", cookies=admin).json()
    assert detail["earnings"][0]["percent"] == 15 and detail["earnings"][0]["bonus"] == round(a3 * 0.15)

    # Admin pays them outside the app and marks it
    owed = detail["bonus_owed"]
    r = client.post(f"/app/api/admin/marketers/{m['id']}/pay", cookies=admin, json={"reference": "GTB 1234"})
    assert r.json()["paid"] == owed and r.json()["marketer"]["bonus_owed"] == 0
    assert client.post(f"/app/api/admin/marketers/{m['id']}/pay", cookies=admin, json={}).status_code == 400

    # The marketer logs in with their own account and sees their numbers
    _register(mphone, name="Tunde Bello")
    mc = _login(mphone)
    assert client.get("/app/api/auth/me", cookies=mc).json()["is_marketer"] is True
    mine = client.get("/app/api/marketer/me", cookies=mc).json()
    assert mine["bonus_paid"] == owed and mine["business_list"][0]["phone"] == biz
    # …and a business owner isn't a marketer
    assert client.get("/app/api/marketer/me", cookies=_login(biz)).status_code == 403

    ov = client.get("/app/api/admin/marketers", cookies=admin).json()
    assert ov["totals"]["marketers"] >= 1 and ov["totals"]["paying"] >= 1


def test_referral_codes_still_work_and_businesses_without_a_marketer_earn_nothing():
    admin = _admin()
    referrer = _phone()
    _register(referrer, name="Kemi")
    db = SessionLocal()
    code = db.query(User).filter(User.phone == referrer).first().referral_code
    db.close()
    if code:
        biz = _phone()
        _register(biz, ref=code)
        db = SessionLocal()
        assert db.query(Referral).filter(Referral.referee_phone == biz).count() == 1
        assert db.query(User).filter(User.phone == biz).first().marketer_id is None
        db.close()
    plain = _phone()
    _register(plain)
    before = SessionLocal().query(MarketerEarning).count()
    _pay(admin, plain)
    assert SessionLocal().query(MarketerEarning).count() == before


def test_admin_rules():
    admin = _admin()
    p = _phone()
    m = client.post("/app/api/admin/marketers", cookies=admin, json={"name": "Ngozi", "phone": p, "code": "ngozi-1"}).json()
    assert m["code"] == "NGOZI1"
    assert "already exists" in client.post("/app/api/admin/marketers", cookies=admin,
                                           json={"name": "Again", "phone": p}).json()["detail"]
    assert "already used" in client.post("/app/api/admin/marketers", cookies=admin,
                                         json={"name": "Xavi", "phone": _phone(), "code": "NGOZI1"}).json()["detail"]
    assert client.post("/app/api/admin/marketers", cookies=admin, json={"name": "Y", "phone": _phone(),
                                                                         "percent": 80}).status_code == 400
    # Not admin
    other = _phone(); _register(other)
    assert client.get("/app/api/admin/marketers", cookies=_login(other)).status_code == 403
    # An inactive marketer's code no longer brings businesses (they sign up as normal)
    client.put(f"/app/api/admin/marketers/{m['id']}", cookies=admin, json={"status": "inactive"})
    r = _register(_phone(), ref="NGOZI1")
    assert r.status_code == 404                                  # not a live code any more
    # A marketer can't sign their own phone up with their code
    q = _phone()
    m2 = client.post("/app/api/admin/marketers", cookies=admin, json={"name": "Femi", "phone": q}).json()
    assert _register(q, ref=m2["code"]).status_code == 400


def test_whatsapp_join_with_a_marketer_code():
    import json
    from models import PendingAction
    from onboarding_commands import complete_user_onboarding
    admin = _admin()
    m = client.post("/app/api/admin/marketers", cookies=admin, json={"name": "Wale", "phone": _phone()}).json()
    phone = _phone()
    db = SessionLocal()
    try:
        # What "join <code>" leaves behind, finished by onboarding
        pending = PendingAction(phone=phone, action="ONBOARD_USER", customer_name="Bisi Foods", last_customer="",
                                items_json=json.dumps({"_ref_code": m["code"]}))
        db.add(pending); db.commit()
        complete_user_onboarding(db, None, phone, pending, "food_hospitality", "bakery", "Bakery")
        db.commit()
        u = db.query(User).filter(User.phone == phone).first()
        assert u.marketer_id == m["id"] and u.subscription_plan == "GO" and u.referred_by_code is None
        assert db.query(Referral).filter(Referral.referee_phone == phone).count() == 0
    finally:
        db.close()
