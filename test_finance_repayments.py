"""
Repayments for a financed asset, riding the supplier rails: one installment per
supplier purchase, owner-claimed versus confirmed evidence, and the repayment
record feeding the next scorecard.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-finance-repay-00000000000")
ADMIN_PHONE = "2348090005000"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
import business_scorecard as bs
import finance_installments as fi
from database import SessionLocal
from models import (
    Customer, FinanceApplication, Supplier, SupplierPayment, SupplierPurchase,
    Transaction, User, utcnow,
)

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000, 3000))

# Applying requires identity details (asked at application, not sign-up).
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
    phone = f"234857{next(_seq):06d}"
    cookies = _register(phone, "Ade Rides")
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == phone).first()
        u.created_at = utcnow() - timedelta(days=200)
        cust = Customer(owner_phone=phone, name="Regular", balance=0)
        db.add(cust); db.flush()
        for m in range(4):
            for i in range(4):
                db.add(Transaction(customer_id=cust.id, type="SALE", amount=100_000,
                                   recorded_by_id=u.id,
                                   created_at=utcnow() - timedelta(days=30 * m + i * 5 + 1)))
        db.commit()
    finally:
        db.close()
    client.post("/app/api/kyc", cookies=cookies, json=KYC)
    return phone, cookies


def _delivered_application(admin, **partner_over):
    """A business with a delivered asset, ready for a repayment plan."""
    phone, cook = _business()
    body = {"name": f"Wheels {next(_seq)}", "asset_types": ["motorcycle"], "eligibility": {},
            "commission_type": "PERCENT_OF_ASSET", "commission_value": 500,
            "commission_due_on": "ON_DELIVERY"}
    body.update(partner_over)
    pid = client.post("/app/api/admin/finance-partners", cookies=admin, json=body).json()["id"]
    aid = client.post(f"/app/api/finance-offers/{pid}/apply", cookies=cook, json={
        "consent": True, "asset_requested": "motorcycle", "asset_value": 1_200_000}).json()["id"]
    for s in ("SHARED", "APPROVED", "DELIVERED"):
        r = client.patch(f"/app/api/admin/finance-applications/{aid}", cookies=admin, json={"status": s})
        assert r.status_code == 200, r.text
    return phone, cook, aid


def _schedule(admin, aid, installments=4, amount_each=100_000, every="WEEKLY", first_due=None):
    return client.post(f"/app/api/admin/finance-applications/{aid}/schedule", cookies=admin,
                       json={"installments": installments, "amount_each": amount_each,
                             "every": every, "first_due": first_due})


# ── The plan ─────────────────────────────────────────────────────────────────

def test_schedule_becomes_one_supplier_purchase_per_installment(admin):
    phone, cook, aid = _delivered_application(admin)
    r = _schedule(admin, aid, installments=4, amount_each=100_000)
    assert r.status_code == 200, r.text
    s = r.json()["schedule"]
    assert s["count"] == 4 and s["total"] == 400_000 and s["outstanding"] == 400_000
    assert [i["installment_no"] for i in s["installments"]] == [1, 2, 3, 4]
    # A week apart, each with its own due date.
    dues = [i["due_date"][:10] for i in s["installments"]]
    assert len(set(dues)) == 4

    db = SessionLocal()
    try:
        rows = db.query(SupplierPurchase).filter(
            SupplierPurchase.finance_application_id == aid).all()
        assert len(rows) == 4
        assert "installment 1 of 4" in rows[0].product.lower()
        # Tagged as financing, and the partner exists as a supplier of this business.
        sup = db.query(Supplier).filter(Supplier.id == rows[0].supplier_id).first()
        assert sup.finance_partner_id and sup.owner_phone == phone
    finally:
        db.close()


def test_schedule_needs_delivery_and_cannot_be_created_twice(admin):
    phone, cook = _business()
    pid = client.post("/app/api/admin/finance-partners", cookies=admin, json={
        "name": "Too Early", "asset_types": ["freezer"], "eligibility": {},
        "commission_type": "FLAT_PER_DEAL", "commission_value": 10_000,
        "commission_due_on": "ON_DELIVERY"}).json()["id"]
    aid = client.post(f"/app/api/finance-offers/{pid}/apply", cookies=cook,
                      json={"consent": True, "asset_requested": "freezer"}).json()["id"]
    early = _schedule(admin, aid)
    assert early.status_code == 400 and "delivered" in early.json()["detail"].lower()

    _phone2, _cook2, aid2 = _delivered_application(admin)
    assert _schedule(admin, aid2).status_code == 200
    again = _schedule(admin, aid2)
    assert again.status_code == 400 and "already has a repayment plan" in again.json()["detail"]


def test_bad_schedules_are_refused(admin):
    _phone, _cook, aid = _delivered_application(admin)
    assert _schedule(admin, aid, installments=0).status_code == 400
    assert _schedule(admin, aid, amount_each=0).status_code == 400
    assert _schedule(admin, aid, every="DAILY").status_code == 400
    assert _schedule(admin, aid, first_due="not-a-date").status_code == 400


# ── Recording and confirming ─────────────────────────────────────────────────

def test_owner_repayment_is_claimed_until_confirmed(admin):
    phone, cook, aid = _delivered_application(admin)
    _schedule(admin, aid, installments=3, amount_each=50_000)

    r = client.post(f"/app/api/my-applications/{aid}/repayments", cookies=cook,
                    json={"installment_no": 1, "amount": 50_000})
    assert r.status_code == 200, r.text
    s = r.json()["schedule"]
    assert r.json()["awaiting_confirmation"] is True
    assert s["paid"] == 50_000 and s["confirmed_paid"] == 0      # claimed only
    assert s["installments"][0]["settled"] is True
    assert s["installments"][0]["verification"] == "CLAIMED"

    # Claimed repayments do NOT build a repayment record.
    card = client.get("/app/api/scorecard", cookies=cook).json()
    assert card["metrics"]["repayment_settled"] == 0

    c = client.post(f"/app/api/admin/finance-applications/{aid}/repayments/confirm",
                    cookies=admin, json={})
    assert c.status_code == 200 and c.json()["confirmed"] == 1
    assert c.json()["schedule"]["confirmed_paid"] == 50_000

    card = client.get("/app/api/scorecard", cookies=cook).json()
    assert card["metrics"]["repayment_settled"] == 1
    assert card["metrics"]["repaid_confirmed"] == 50_000
    assert card["metrics"]["repayment_on_time_pct"] == 100.0


def test_admin_recorded_repayment_counts_immediately(admin):
    phone, cook, aid = _delivered_application(admin)
    _schedule(admin, aid, installments=2, amount_each=25_000)
    r = client.post(f"/app/api/admin/finance-applications/{aid}/repayments", cookies=admin,
                    json={"installment_no": 1, "amount": 25_000})
    assert r.status_code == 200, r.text
    assert r.json()["schedule"]["confirmed_paid"] == 25_000


def test_overpayment_is_clamped_and_settled_installments_refused(admin):
    phone, cook, aid = _delivered_application(admin)
    _schedule(admin, aid, installments=2, amount_each=10_000)
    r = client.post(f"/app/api/my-applications/{aid}/repayments", cookies=cook,
                    json={"installment_no": 1, "amount": 999_999})
    assert r.json()["schedule"]["paid"] == 10_000        # clamped to the installment
    again = client.post(f"/app/api/my-applications/{aid}/repayments", cookies=cook,
                        json={"installment_no": 1, "amount": 5_000})
    assert again.status_code == 400 and "already fully paid" in again.json()["detail"]
    missing = client.post(f"/app/api/my-applications/{aid}/repayments", cookies=cook,
                          json={"installment_no": 9, "amount": 1_000})
    assert missing.status_code == 400


def test_late_payment_is_recorded_as_late(admin):
    phone, cook, aid = _delivered_application(admin)
    # A plan whose first installment was already due a week ago.
    past = (utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    _schedule(admin, aid, installments=2, amount_each=20_000, first_due=past)
    s = client.get(f"/app/api/my-applications/{aid}/schedule", cookies=cook).json()["schedule"]
    # Installment 2 falls due a week after the first, i.e. today — so both count.
    assert s["installments"][0]["overdue"] is True and s["overdue_count"] >= 1

    client.post(f"/app/api/admin/finance-applications/{aid}/repayments", cookies=admin,
                json={"installment_no": 1, "amount": 20_000})
    card = client.get("/app/api/scorecard", cookies=cook).json()["metrics"]
    assert card["repayment_settled"] == 1
    assert card["repayment_on_time_pct"] == 0.0      # paid, but paid late


# ── Scorecard behaviour ──────────────────────────────────────────────────────

def test_financing_does_not_contaminate_the_supplier_metric(admin):
    phone, cook, aid = _delivered_application(admin)
    db = SessionLocal()
    try:
        # An ordinary trade supplier, fully paid.
        sup = Supplier(name="Rice Depot", owner_phone=phone)
        db.add(sup); db.flush()
        db.add(SupplierPurchase(supplier_id=sup.id, owner_phone=phone, product="rice",
                                total=100_000, paid_amount=100_000))
        db.commit()
    finally:
        db.close()
    _schedule(admin, aid, installments=4, amount_each=300_000)   # 1.2m of financing, unpaid

    m = client.get("/app/api/scorecard", cookies=cook).json()["metrics"]
    assert m["supplier_paid_pct"] == 100.0      # trade credit untouched by the asset
    assert m["financed_total"] == 1_200_000
    assert m["financing_outstanding"] == 1_200_000


def test_repayment_component_only_applies_to_financed_businesses(admin):
    _phone, plain_cook = _business()
    plain = client.get("/app/api/scorecard", cookies=plain_cook).json()
    assert plain["metrics"]["has_financing"] is False
    assert all(c["key"] != "repayment_record" for c in plain["components"])

    _p2, financed_cook, aid = _delivered_application(admin)
    _schedule(admin, aid, installments=2, amount_each=50_000)
    client.post(f"/app/api/admin/finance-applications/{aid}/repayments", cookies=admin,
                json={"installment_no": 1, "amount": 50_000})
    financed = client.get("/app/api/scorecard", cookies=financed_cook).json()
    assert financed["metrics"]["has_financing"] is True
    assert any(c["key"] == "repayment_record" for c in financed["components"])


# ── Commission triggers that needed repayments ───────────────────────────────

def test_fee_on_first_repayment(admin):
    _phone, cook, aid = _delivered_application(
        admin, commission_due_on="ON_FIRST_REPAYMENT", commission_type="FLAT_PER_DEAL",
        commission_value=15_000)
    _schedule(admin, aid, installments=3, amount_each=40_000)
    before = client.get("/app/api/admin/finance-applications", cookies=admin).json()
    row = next(x for x in before["applications"] if x["id"] == aid)
    assert row["commission_status"] == "PENDING"

    r = client.post(f"/app/api/admin/finance-applications/{aid}/repayments", cookies=admin,
                    json={"installment_no": 1, "amount": 40_000})
    assert r.json()["commission_status"] == "DUE"
    assert r.json()["commission_amount"] == 15_000


def test_fee_as_a_share_of_repayments_on_completion(admin):
    _phone, cook, aid = _delivered_application(
        admin, commission_due_on="ON_COMPLETION", commission_type="PERCENT_OF_REPAYMENTS",
        commission_value=1000)     # 10%
    _schedule(admin, aid, installments=2, amount_each=100_000)
    mid = client.post(f"/app/api/admin/finance-applications/{aid}/repayments", cookies=admin,
                      json={"installment_no": 1, "amount": 100_000})
    assert mid.json()["commission_status"] == "PENDING"      # not complete yet

    done = client.post(f"/app/api/admin/finance-applications/{aid}/repayments", cookies=admin,
                       json={"installment_no": 2, "amount": 100_000})
    assert done.json()["schedule"]["complete"] is True
    assert done.json()["commission_status"] == "DUE"
    assert done.json()["commission_amount"] == 20_000        # 10% of 200k repaid


# ── Access ───────────────────────────────────────────────────────────────────

def test_only_the_owner_and_admin_can_touch_a_plan(admin):
    _phone, cook, aid = _delivered_application(admin)
    _schedule(admin, aid, installments=2, amount_each=10_000)
    _other, other_cook = _business()
    assert client.get(f"/app/api/my-applications/{aid}/schedule", cookies=other_cook).status_code == 404
    assert client.post(f"/app/api/my-applications/{aid}/repayments", cookies=other_cook,
                       json={"installment_no": 1, "amount": 1_000}).status_code == 404
    assert client.post(f"/app/api/admin/finance-applications/{aid}/schedule", cookies=cook,
                       json={"installments": 2, "amount_each": 1_000}).status_code == 403
    assert client.post(f"/app/api/admin/finance-applications/{aid}/repayments/confirm",
                       cookies=cook, json={}).status_code == 403
