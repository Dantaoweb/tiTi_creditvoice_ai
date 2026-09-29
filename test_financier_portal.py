"""
The financier portal at /financier: admin invites a financier's staff, they set
their own PIN, and they work only their own queue.

A financier is NOT a CreditVoice business and NOT a user's business partner, so
the isolation is what these tests are mostly about.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-financier-portal-0000000")
ADMIN_PHONE = "2348090010000"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import Customer, FinanceApplication, FinancierUser, Transaction, User, utcnow

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000, 3000))

KYC = {"legal_name": "Ade Owner", "state": "Lagos", "city": "Ikeja",
       "address": "12 Allen Avenue", "id_type": "NIN", "id_number": "22233344455",
       "is_registered": False}


@pytest.fixture(autouse=True)
def _reset():
    os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _register(phone, name="Shop"):
    client.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": "5678"})
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


@pytest.fixture
def admin():
    return _register(ADMIN_PHONE, "App Admin")


def _business():
    phone = f"234864{next(_seq):06d}"
    cookies = _register(phone, "Ade Rides")
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == phone).first()
        u.created_at = utcnow() - timedelta(days=200)
        cust = Customer(owner_phone=phone, name="Regular", balance=0)
        db.add(cust); db.flush()
        for m in range(3):
            for i in range(4):
                db.add(Transaction(customer_id=cust.id, type="SALE", amount=150_000,
                                   recorded_by_id=u.id,
                                   created_at=utcnow() - timedelta(days=30 * m + i * 5 + 1)))
        db.commit()
    finally:
        db.close()
    client.post("/app/api/kyc", cookies=cookies, json=KYC)
    return phone, cookies


def _financier(admin, name="Gig Wheels"):
    r = client.post("/app/api/admin/finance-partners", cookies=admin, json={
        "name": name, "asset_types": ["motorcycle"], "eligibility": {},
        "commission_type": "PERCENT_OF_ASSET", "commission_value": 500,
        "commission_due_on": "ON_DELIVERY"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _staff_login(admin, partner_id, name="Ops Person", phone=None, pin="4321"):
    """Admin invites a financier's staff; they accept and end up signed in."""
    phone = phone or f"234865{next(_seq):06d}"
    created = client.post("/app/api/admin/financier-users", cookies=admin, json={
        "finance_partner_id": partner_id, "name": name, "phone": phone})
    assert created.status_code == 200, created.text
    code = created.json()["invite_code"]
    assert code and code.startswith("FIN-")
    assert created.json()["portal_url"] == "/financier"

    accepted = client.post("/app/api/financier/accept-invite", json={"code": code, "pin": pin})
    assert accepted.status_code == 200, accepted.text
    return phone, accepted.cookies, created.json()["id"]


def _application(admin, cook, partner_id, advance_to="SHARED"):
    aid = client.post(f"/app/api/finance-offers/{partner_id}/apply", cookies=cook, json={
        "consent": True, "asset_requested": "motorcycle", "asset_value": 1_000_000}).json()["id"]
    if advance_to:
        r = client.patch(f"/app/api/admin/finance-applications/{aid}", cookies=admin,
                         json={"status": advance_to})
        assert r.status_code == 200, r.text
    return aid


# ── Invite and sign-in ───────────────────────────────────────────────────────

def test_admin_invites_staff_who_set_their_own_pin_and_can_sign_in(admin):
    pid = _financier(admin)
    phone, cookies, _uid = _staff_login(admin, pid, pin="9182")

    me = client.get("/app/api/financier/me", cookies=cookies)
    assert me.status_code == 200, me.text
    assert me.json()["financier_name"] == "Gig Wheels"

    fresh = client.post("/app/api/financier/login", json={"phone": phone, "pin": "9182"})
    assert fresh.status_code == 200 and fresh.json()["name"] == "Ops Person"
    assert client.post("/app/api/financier/login",
                       json={"phone": phone, "pin": "0000"}).status_code == 401

    listed = client.get("/app/api/admin/financier-users", cookies=admin).json()["users"]
    row = next(u for u in listed if u["phone"] == phone)
    assert row["accepted"] is True and row["invite_code"] is None


def test_a_used_or_unknown_invite_code_is_refused(admin):
    pid = _financier(admin)
    created = client.post("/app/api/admin/financier-users", cookies=admin, json={
        "finance_partner_id": pid, "name": "Ops", "phone": f"234866{next(_seq):06d}"}).json()
    code = created["invite_code"]
    assert client.post("/app/api/financier/accept-invite",
                       json={"code": code, "pin": "1234"}).status_code == 200
    # Same code again: it was cleared when accepted.
    assert client.post("/app/api/financier/accept-invite",
                       json={"code": code, "pin": "1234"}).status_code == 400
    assert client.post("/app/api/financier/accept-invite",
                       json={"code": "FIN-ZZZZZZ", "pin": "1234"}).status_code == 400


def test_a_financier_phone_cannot_double_as_a_business_account(admin):
    pid = _financier(admin)
    biz_phone, _cook = _business()
    clash = client.post("/app/api/admin/financier-users", cookies=admin, json={
        "finance_partner_id": pid, "name": "Ops", "phone": biz_phone})
    assert clash.status_code == 409 and "business account" in clash.json()["detail"]


def test_deactivating_ends_their_session_immediately(admin):
    pid = _financier(admin)
    phone, cookies, uid = _staff_login(admin, pid)
    assert client.get("/app/api/financier/me", cookies=cookies).status_code == 200

    assert client.post(f"/app/api/admin/financier-users/{uid}/deactivate",
                       cookies=admin).status_code == 200
    assert client.get("/app/api/financier/me", cookies=cookies).status_code == 401
    assert client.post("/app/api/financier/login",
                       json={"phone": phone, "pin": "4321"}).status_code == 401


def test_reinvite_resets_the_pin_and_logs_old_sessions_out(admin):
    pid = _financier(admin)
    phone, cookies, uid = _staff_login(admin, pid, pin="1111")
    again = client.post(f"/app/api/admin/financier-users/{uid}/reinvite", cookies=admin)
    assert again.status_code == 200 and again.json()["invite_code"].startswith("FIN-")
    assert client.get("/app/api/financier/me", cookies=cookies).status_code == 401
    assert client.post("/app/api/financier/login",
                       json={"phone": phone, "pin": "1111"}).status_code == 401


# ── The two session worlds never mix ─────────────────────────────────────────

def _clean():
    """A client with no cookies of its own — the shared one accumulates them."""
    return TestClient(app, raise_server_exceptions=True)


def test_a_business_session_cannot_reach_the_portal(admin):
    _financier(admin)
    _phone, cook = _business()
    fresh = _clean()
    assert fresh.get("/app/api/financier/applications", cookies=cook).status_code == 401
    assert fresh.get("/app/api/financier/me", cookies=cook).status_code == 401


def test_a_financier_session_cannot_reach_the_business_app_or_admin(admin):
    pid = _financier(admin)
    _phone, cookies, _uid = _staff_login(admin, pid)
    fresh = _clean()
    assert fresh.get("/app/api/scorecard", cookies=cookies).status_code == 401
    assert fresh.get("/app/api/customers", cookies=cookies).status_code == 401
    assert fresh.get("/app/api/admin/finance-applications", cookies=cookies).status_code == 401


def test_the_portal_page_is_served_at_its_own_path():
    r = client.get("/financier")
    assert r.status_code == 200 and "<html" in r.text.lower()
    assert client.get("/financier/login").status_code == 200


# ── The queue ────────────────────────────────────────────────────────────────

def test_a_financier_sees_only_its_own_shared_applications(admin):
    mine = _financier(admin, "Mine Co")
    theirs = _financier(admin, "Theirs Co")
    _p1, cook1 = _business()
    _p2, cook2 = _business()
    _p3, cook3 = _business()
    my_app = _application(admin, cook1, mine)
    their_app = _application(admin, cook2, theirs)
    unshared = _application(admin, cook3, mine, advance_to=None)   # still SUBMITTED

    _phone, cookies, _uid = _staff_login(admin, mine)
    rows = client.get("/app/api/financier/applications", cookies=cookies).json()["applications"]
    ids = {r["id"] for r in rows}
    assert my_app in ids
    assert their_app not in ids          # another financier's work is invisible
    assert unshared not in ids          # not until CreditVoice shares it

    assert client.get(f"/app/api/financier/applications/{their_app}",
                      cookies=cookies).status_code == 404


def test_the_evidence_is_visible_but_not_our_fee_or_contacts(admin):
    pid = _financier(admin)
    _phone, cook = _business()
    aid = _application(admin, cook, pid)
    _fphone, cookies, _uid = _staff_login(admin, pid)

    detail = client.get(f"/app/api/financier/applications/{aid}", cookies=cookies).json()
    assert detail["snapshot"]["metrics"]["avg_monthly_sales"] == 600_000
    assert detail["kyc"]["legal_name"] == "Ade Owner"
    # Commission is ours alone.
    assert "commission_amount" not in detail and "commission_status" not in detail
    # Before approval: no phone, no ID number.
    assert detail["contact_phone"] is None
    assert "id_number" not in detail["kyc"]

    client.patch(f"/app/api/financier/applications/{aid}", cookies=cookies,
                 json={"status": "APPROVED"})
    after = client.get(f"/app/api/financier/applications/{aid}", cookies=cookies).json()
    assert after["contact_phone"] and after["kyc"]["id_number"]


def test_a_financier_drives_its_own_deal_and_our_fee_follows(admin):
    pid = _financier(admin)
    _phone, cook = _business()
    aid = _application(admin, cook, pid)
    _fphone, cookies, _uid = _staff_login(admin, pid)

    assert client.patch(f"/app/api/financier/applications/{aid}", cookies=cookies,
                        json={"status": "IN_REVIEW"}).status_code == 200
    approved = client.patch(f"/app/api/financier/applications/{aid}", cookies=cookies,
                            json={"status": "APPROVED", "asset_value": 900_000,
                                  "partner_ref": "GW-77"})
    assert approved.status_code == 200 and approved.json()["partner_ref"] == "GW-77"

    delivered = client.patch(f"/app/api/financier/applications/{aid}", cookies=cookies,
                             json={"status": "DELIVERED"})
    assert delivered.status_code == 200 and delivered.json()["delivered_at"]

    # Our fee was raised by their own action — 5% of the 900k they financed.
    admin_view = client.get(f"/app/api/admin/finance-applications/{aid}", cookies=admin).json()
    assert admin_view["commission_status"] == "DUE" and admin_view["commission_amount"] == 45_000


def test_a_financier_cannot_skip_stages_or_decline_without_a_reason(admin):
    pid = _financier(admin)
    _phone, cook = _business()
    aid = _application(admin, cook, pid)
    _fphone, cookies, _uid = _staff_login(admin, pid)

    jump = client.patch(f"/app/api/financier/applications/{aid}", cookies=cookies,
                        json={"status": "DELIVERED"})
    assert jump.status_code == 400 and "Cannot move from SHARED to DELIVERED" in jump.json()["detail"]
    bare = client.patch(f"/app/api/financier/applications/{aid}", cookies=cookies,
                        json={"status": "DECLINED"})
    assert bare.status_code == 400 and "reason" in bare.json()["detail"].lower()

    ok = client.patch(f"/app/api/financier/applications/{aid}", cookies=cookies,
                      json={"status": "DECLINED", "decline_reason": "Rider has no licence"})
    assert ok.status_code == 200
    # …and the business is told why.
    mine = client.get("/app/api/my-applications", cookies=cook).json()["applications"][0]
    assert mine["status"] == "DECLINED" and mine["decline_reason"] == "Rider has no licence"


def test_a_financier_confirming_a_repayment_makes_it_verified_evidence(admin):
    pid = _financier(admin)
    phone, cook = _business()
    aid = _application(admin, cook, pid)
    _fphone, cookies, _uid = _staff_login(admin, pid)
    client.patch(f"/app/api/financier/applications/{aid}", cookies=cookies, json={"status": "APPROVED"})
    client.patch(f"/app/api/financier/applications/{aid}", cookies=cookies, json={"status": "DELIVERED"})
    assert client.post(f"/app/api/admin/finance-applications/{aid}/schedule", cookies=admin,
                       json={"installments": 2, "amount_each": 50_000,
                             "every": "WEEKLY"}).status_code == 200

    # The business says it paid…
    client.post(f"/app/api/my-applications/{aid}/repayments", cookies=cook,
                json={"installment_no": 1, "amount": 50_000})
    assert client.get("/app/api/scorecard", cookies=cook).json()["metrics"]["repayment_settled"] == 0

    # …the financier confirms the money arrived, and it counts.
    r = client.post(f"/app/api/financier/applications/{aid}/confirm-repayment",
                    cookies=cookies, json={})
    assert r.status_code == 200 and r.json()["confirmed"] == 1
    assert client.get("/app/api/scorecard", cookies=cook).json()["metrics"]["repayment_settled"] == 1
