"""
tiTi explains the scorecard and says what to do about it — the same answers in
the app, in web chat and on WhatsApp.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-scorecard-advice-0000000")
ADMIN_PHONE = "2348090009000"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
import business_scorecard as bs
import scorecard_advice as advice
from conftest import month_slot
from database import SessionLocal
from models import Customer, Supplier, SupplierPurchase, Transaction, User, utcnow
from query_handler import handle_natural_language_query as ask

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
        bs.save_config(db, bs.DEFAULT_CONFIG, updated_by="test", note="baseline")
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


def _business(months=3, per_month=3, overdue_supplier=False, credit=False):
    phone = f"234862{next(_seq):06d}"
    cookies = _register(phone, "Ade Rides")
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == phone).first()
        u.created_at = utcnow() - timedelta(days=200)
        cust = Customer(owner_phone=phone, name="Regular", balance=0)
        db.add(cust); db.flush()
        for m in range(months):
            for i in range(per_month):
                db.add(Transaction(customer_id=cust.id, type="BUY" if credit else "SALE",
                                   amount=100_000, recorded_by_id=u.id,
                                   created_at=month_slot(m, i, 6, per_month)))
        if overdue_supplier:
            sup = Supplier(name="Depot", owner_phone=phone)
            db.add(sup); db.flush()
            db.add(SupplierPurchase(supplier_id=sup.id, owner_phone=phone, product="parts",
                                    total=200_000, paid_amount=20_000,
                                    due_date=utcnow() - timedelta(days=10)))
        db.commit()
    finally:
        db.close()
    client.post("/app/api/kyc", cookies=cookies, json=KYC)
    return phone, cookies


def _ask(phone, text):
    db = SessionLocal()
    try:
        return ask(db, phone, text)
    finally:
        db.close()


# ── The advice itself ────────────────────────────────────────────────────────

def test_advice_names_the_biggest_win_first_with_real_numbers():
    phone, cook = _business(overdue_supplier=True)
    r = client.get("scorecard/advice", cookies=cook) if False else client.get(
        "/app/api/scorecard/advice", cookies=cook)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["score"] is not None and body["explanations"]
    # Every explanation says what the measurement means, in plain words.
    assert all(e["meaning"] for e in body["explanations"] if e["key"] != "sales_floor")
    # Actions are ordered by how much they would move the score.
    gains = [a["possible_gain"] for a in body["actions"] if a["possible_gain"]]
    assert gains == sorted(gains, reverse=True)
    # The supplier action quotes the actual overdue amount.
    supplier = next((a for a in body["actions"] if a["key"] == "supplier_discipline"), None)
    assert supplier and "180,000" in supplier["action"]


def test_things_not_being_recorded_are_shown_as_opportunities():
    phone, cook = _business()             # no cost prices, no suppliers
    body = client.get("/app/api/scorecard/advice", cookies=cook).json()
    keys = {a["key"]: a["action"] for a in body["actions"]}
    assert "margin" in keys and "cost price" in keys["margin"].lower()
    assert "supplier_discipline" in keys


def test_advice_can_be_judged_by_one_partners_rules(admin):
    phone, cook = _business()
    pid = client.post("/app/api/admin/finance-partners", cookies=admin, json={
        "name": "Takings Only", "asset_types": ["motorcycle"], "eligibility": {},
        "scorecard_overrides": {"components": {
            "sales_volume": {"weight": 100},
            "sales_floor": {"enabled": False}, "consistency": {"enabled": False},
            "tenure": {"enabled": False}, "margin": {"enabled": False},
            "repeat_customers": {"enabled": False}, "collections": {"enabled": False},
            "supplier_discipline": {"enabled": False},
        }},
        "commission_type": "FLAT_PER_DEAL", "commission_value": 1,
        "commission_due_on": "ON_DELIVERY"}).json()["id"]

    body = client.get(f"/app/api/scorecard/advice?partner_id={pid}", cookies=cook).json()
    assert body["partner_name"] == "Takings Only"
    assert [e["key"] for e in body["explanations"]] == ["sales_volume"]


# ── tiTi in chat / WhatsApp ──────────────────────────────────────────────────

@pytest.mark.parametrize("question", [
    "what is my business score",
    "my score",
    "scorecard",
    "what is my credit score",
])
def test_titi_answers_what_is_my_score(question):
    phone, _cook = _business()
    reply = _ask(phone, question)
    assert reply and "business score is" in reply
    assert "out of 100" in reply
    assert "improve my score" in reply        # points them at the next step


@pytest.mark.parametrize("question", [
    "how do i improve my score",
    "improve my business score",
    "why is my score low",
])
def test_titi_answers_how_to_improve(question):
    phone, _cook = _business(overdue_supplier=True)
    reply = _ask(phone, question)
    assert reply and "raise your business score" in reply.lower()
    assert "180,000" in reply                 # the real overdue figure


def test_titi_explains_a_term_it_used():
    phone, _cook = _business()
    reply = _ask(phone, "what is credit collected")
    assert reply and "gave on credit" in reply
    assert _ask(phone, "what is gross margin") is not None
    # Something it has no definition for falls through to the other handlers.
    assert _ask(phone, "what is the capital of Ghana") is None


def test_titi_answers_whether_financing_is_within_reach(admin):
    phone, cook = _business()
    client.post("/app/api/admin/finance-partners", cookies=admin, json={
        "name": "Reachable Co", "asset_types": ["motorcycle"],
        "eligibility": {"min_months_recorded": 1},
        "commission_type": "FLAT_PER_DEAL", "commission_value": 1,
        "commission_due_on": "ON_DELIVERY"})
    client.post("/app/api/admin/finance-partners", cookies=admin, json={
        "name": "Formal Only", "asset_types": ["freezer"],
        "eligibility": {"requires_registered_business": 1},
        "commission_type": "FLAT_PER_DEAL", "commission_value": 1,
        "commission_due_on": "ON_DELIVERY"})

    reply = _ask(phone, "can i get financing for a motorcycle")
    assert reply
    assert "Reachable Co" in reply
    assert "Formal Only" in reply and "CAC-registered" in reply


def test_a_business_with_no_score_is_told_why_not():
    phone = f"234863{next(_seq):06d}"
    _register(phone, "Brand New")
    db = SessionLocal()
    try:
        bs.save_config(db, {**bs.DEFAULT_CONFIG, "min_months_recorded": 3},
                       updated_by="test", note="raise minimum")
    finally:
        db.close()
    reply = _ask(phone, "my score")
    assert reply and "don't have a score yet" in reply


def test_ordinary_questions_still_reach_the_old_handlers():
    """The new intents must not swallow the existing customer queries."""
    phone, cook = _business(credit=True)          # credit sales leave a balance
    db = SessionLocal()
    try:
        name = db.query(Customer).filter(Customer.owner_phone == phone).first().name
    finally:
        db.close()
    reply = _ask(phone, f"how much does {name} owe me")
    assert reply and "900,000" in reply
