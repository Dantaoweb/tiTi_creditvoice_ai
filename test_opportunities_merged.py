"""
One noticeboard. A business should not have to look in two places for an offer,
so financier offers appear among the opportunities — carrying that financier's
requirements — while ordinary cards keep their own intake form.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-merged-opps-00000000000000")
ADMIN_PHONE = "2348090012000"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
import business_scorecard as bs
from database import SessionLocal
from models import Customer, Opportunity, OpportunityApplication, Transaction, User, utcnow

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000, 3000))

KYC = {"legal_name": "Ade Owner", "state": "Lagos", "city": "Ikeja",
       "address": "12 Allen Avenue", "id_type": "NIN", "id_number": "22233344455",
       "is_registered": False}


@pytest.fixture(autouse=True)
def _reset():
    os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE
    db = SessionLocal()
    try:
        # Applications reference the cards, so they go first.
        db.query(OpportunityApplication).delete()
        db.query(Opportunity).delete()
        bs.save_config(db, bs.DEFAULT_CONFIG, updated_by="test", note="baseline")
        db.commit()
    finally:
        db.close()
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


def _business(with_kyc=True):
    phone = f"234868{next(_seq):06d}"
    cookies = _register(phone, "Ade Rides")
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == phone).first()
        u.created_at = utcnow() - timedelta(days=200)
        cust = Customer(owner_phone=phone, name="Regular", balance=0)
        db.add(cust); db.flush()
        for m in range(3):
            for i in range(4):
                db.add(Transaction(customer_id=cust.id, type="SALE", amount=120_000,
                                   recorded_by_id=u.id,
                                   created_at=utcnow() - timedelta(days=30 * m + i * 5 + 1)))
        db.commit()
    finally:
        db.close()
    if with_kyc:
        client.post("/app/api/kyc", cookies=cookies, json=KYC)
    return phone, cookies


def _financier(admin, name="Gig Wheels", **over):
    body = {"name": name, "asset_types": ["motorcycle"], "eligibility": {},
            "commission_type": "FLAT_PER_DEAL", "commission_value": 10_000,
            "commission_due_on": "ON_DELIVERY"}
    body.update(over)
    r = client.post("/app/api/admin/finance-partners", cookies=admin, json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _card(admin, **over):
    body = {"title": "Free business training", "partner_name": "SMEDAN",
            "category": "trade", "description": "A two-day workshop.",
            "link_url": "", "is_active": True, "application_fields": "[]"}
    body.update(over)
    r = client.post("/app/api/admin/opportunities", cookies=admin, json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _mine(cook):
    r = client.get("/app/api/opportunities/mine", cookies=cook)
    assert r.status_code == 200, r.text
    return {o["title"]: o for o in r.json()["opportunities"]}, r.json()


# ── One list, two kinds ──────────────────────────────────────────────────────

def test_ordinary_cards_and_financier_offers_arrive_in_one_list(admin):
    _phone, cook = _business()
    _card(admin)
    _financier(admin)
    by_title, body = _mine(cook)

    assert "Free business training" in by_title
    assert by_title["Free business training"]["kind"] == "general"
    finance = next(o for o in body["opportunities"] if o["kind"] == "finance")
    assert finance["partner_name"] == "Gig Wheels"
    assert finance["checks"] is not None and finance["coverage"] == "Nationwide"
    assert finance["score"] is not None


def test_a_financier_with_no_card_is_still_reachable(admin):
    _phone, cook = _business()
    _financier(admin, name="Quiet Co")
    _by_title, body = _mine(cook)
    quiet = next(o for o in body["opportunities"] if o["partner_name"] == "Quiet Co")
    assert quiet["kind"] == "finance" and quiet["id"].startswith("financier:")
    assert "Spread the cost" in quiet["description"]


def test_an_admin_card_linked_to_a_financier_becomes_their_offer(admin):
    _phone, cook = _business()
    pid = _financier(admin, name="Wheels Plus")
    _card(admin, title="Buy a bike, pay weekly", category="finance",
          description="Own your motorcycle while you work.", finance_partner_id=pid)

    _by_title, body = _mine(cook)
    cards = [o for o in body["opportunities"] if o["partner_name"] == "Wheels Plus"]
    # The partner is represented once — by their card, not twice.
    assert len(cards) == 1
    card = cards[0]
    assert card["title"] == "Buy a bike, pay weekly"      # admin's own wording
    assert card["kind"] == "finance" and card["financier_id"] == pid
    assert card["checks"] is not None


def test_each_financier_card_shows_that_financiers_own_requirements(admin):
    _phone, cook = _business()
    _financier(admin, name="Easy Co", eligibility={"min_months_recorded": 1})
    _financier(admin, name="Strict Co", eligibility={"min_avg_monthly_sales": 90_000_000})
    _by_title, body = _mine(cook)
    offers = {o["partner_name"]: o for o in body["opportunities"] if o["kind"] == "finance"}
    assert offers["Easy Co"]["eligible"] is True
    assert offers["Strict Co"]["eligible"] is False


def test_coverage_and_applied_status_come_through(admin):
    phone, cook = _business()
    far = _financier(admin, name="Kano Only", nationwide=False, states_covered=["Kano"])
    near = _financier(admin, name="Lagos Co", nationwide=False, states_covered=["Lagos"])
    client.post(f"/app/api/finance-offers/{near}/apply", cookies=cook,
                json={"consent": True, "asset_requested": "motorcycle"})

    _by_title, body = _mine(cook)
    offers = {o["partner_name"]: o for o in body["opportunities"] if o["kind"] == "finance"}
    assert offers["Kano Only"]["covered"] is False
    assert offers["Lagos Co"]["applied_status"] == "SUBMITTED"


def test_applying_to_an_ordinary_card_still_uses_its_own_form(admin):
    _phone, cook = _business()
    cid = _card(admin, application_fields='[{"label":"Why you?","type":"text"}]')
    r = client.post(f"/app/api/opportunities/{cid}/apply", cookies=cook,
                    json={"answers": {"Why you?": "I sell fast"}})
    assert r.status_code == 200, r.text
    _by_title, body = _mine(cook)
    card = next(o for o in body["opportunities"] if o["id"] == cid)
    assert card["applied_status"] == "submitted"


def test_the_missing_details_are_reported_once_for_the_whole_page(admin):
    _phone, cook = _business(with_kyc=False)
    _financier(admin)
    _by_title, body = _mine(cook)
    assert body["kyc_complete"] is False
    assert {m["key"] for m in body["kyc_missing"]} >= {"state", "id_number"}


def test_inactive_cards_and_paused_financiers_are_hidden(admin):
    _phone, cook = _business()
    _card(admin, title="Old notice", is_active=False)
    _financier(admin, name="Paused Co", is_active=False)
    _by_title, body = _mine(cook)
    names = {o["title"] for o in body["opportunities"]} | {o["partner_name"] for o in body["opportunities"]}
    assert "Old notice" not in names and "Paused Co" not in names


def test_the_public_list_leaks_no_per_business_detail(admin):
    _phone, cook = _business()
    _financier(admin)
    public = client.get("/app/api/opportunities").json()["opportunities"]
    for card in public:
        assert "checks" not in card and "score" not in card and "eligible" not in card
