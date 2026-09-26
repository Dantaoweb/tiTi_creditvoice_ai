"""
The admin application pipeline and commission ledger: moving a deal from submitted
to delivered, and the fee that follows from the partner's own terms.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-finance-pipeline-000000")
ADMIN_PHONE = "2348090004000"
os.environ["APP_ADMIN_PHONES"] = ADMIN_PHONE

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import AuditLog, Customer, Transaction, User, utcnow

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(1000, 2000))


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
    phone = f"234856{next(_seq):06d}"
    cookies = _register(phone, "Ade Stores")
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
    return phone, cookies


def _partner(admin, **over):
    body = {"name": f"Partner {next(_seq)}", "asset_types": ["motorcycle"], "eligibility": {},
            "commission_type": "PERCENT_OF_ASSET", "commission_value": 500,
            "commission_due_on": "ON_DELIVERY"}
    body.update(over)
    return client.post("/app/api/admin/finance-partners", cookies=admin, json=body).json()["id"]


def _application(admin, asset_value=1_200_000, **partner_over):
    _phone, cook = _business()
    pid = _partner(admin, **partner_over)
    r = client.post(f"/app/api/finance-offers/{pid}/apply", cookies=cook, json={
        "consent": True, "asset_requested": "motorcycle", "asset_value": asset_value})
    assert r.status_code == 200, r.text
    return r.json()["id"], cook


def _patch(admin, rid, **body):
    return client.patch(f"/app/api/admin/finance-applications/{rid}", cookies=admin, json=body)


def _advance(admin, rid, *statuses):
    for s in statuses:
        r = _patch(admin, rid, status=s)
        assert r.status_code == 200, r.text
    return r.json()


def test_admin_sees_applications_with_the_frozen_snapshot(admin):
    rid, _cook = _application(admin)
    listed = client.get("/app/api/admin/finance-applications", cookies=admin).json()
    assert any(x["id"] == rid for x in listed["applications"])
    row = next(x for x in listed["applications"] if x["id"] == rid)
    assert row["business_name"] and row["owner_phone"]
    assert row["next_statuses"] == ["DECLINED", "SHARED", "WITHDRAWN"]

    detail = client.get(f"/app/api/admin/finance-applications/{rid}", cookies=admin).json()
    assert detail["snapshot"]["metrics"]["avg_monthly_sales"] == 400_000
    assert detail["commission_calculated"] == 60_000        # 5% of 1.2m


def test_delivery_makes_the_fee_due_and_the_ledger_tracks_it(admin):
    rid, _cook = _application(admin, asset_value=1_200_000)
    mid = _advance(admin, rid, "SHARED", "IN_REVIEW", "APPROVED")
    assert mid["commission_status"] == "PENDING"            # nothing due yet
    assert mid["approved_at"]

    done = _advance(admin, rid, "DELIVERED")
    assert done["delivered_at"]
    assert done["commission_status"] == "DUE"
    assert done["commission_amount"] == 60_000             # 5% of 1.2m

    inv = client.post(f"/app/api/admin/finance-applications/{rid}/commission", cookies=admin,
                      json={"status": "INVOICED"})
    assert inv.status_code == 200 and inv.json()["commission_status"] == "INVOICED"
    paid = client.post(f"/app/api/admin/finance-applications/{rid}/commission", cookies=admin,
                       json={"status": "PAID"})
    assert paid.json()["commission_status"] == "PAID"

    totals = client.get("/app/api/admin/finance-applications", cookies=admin).json()["commission_totals"]
    assert totals["PAID"] >= 60_000


def test_flat_fee_partner_and_a_negotiated_override(admin):
    rid, _cook = _application(admin, commission_type="FLAT_PER_DEAL", commission_value=25_000)
    done = _advance(admin, rid, "SHARED", "APPROVED", "DELIVERED")
    assert done["commission_amount"] == 25_000

    over = client.post(f"/app/api/admin/finance-applications/{rid}/commission", cookies=admin,
                       json={"status": "DUE", "amount": 30_000})
    assert over.json()["commission_amount"] == 30_000


def test_percent_of_asset_needs_the_asset_value(admin):
    rid, _cook = _application(admin, asset_value=None)
    done = _advance(admin, rid, "SHARED", "APPROVED", "DELIVERED")
    assert done["commission_status"] == "PENDING"
    assert "asset value" in done["commission_reason"].lower()

    # Record what the partner financed, and the fee can be raised.
    assert _patch(admin, rid, asset_value=800_000).status_code == 200
    due = client.post(f"/app/api/admin/finance-applications/{rid}/commission", cookies=admin,
                      json={"status": "DUE"})
    assert due.json()["commission_amount"] == 40_000       # 5% of 800k


def test_repayment_based_fee_waits_for_repayment_records(admin):
    rid, _cook = _application(admin, commission_type="PERCENT_OF_REPAYMENTS", commission_value=1000)
    done = _advance(admin, rid, "SHARED", "APPROVED", "DELIVERED")
    assert done["commission_status"] == "PENDING"
    assert "repayment" in done["commission_reason"].lower()


def test_the_pipeline_cannot_be_skipped_or_reopened(admin):
    rid, _cook = _application(admin)
    jump = _patch(admin, rid, status="DELIVERED")
    assert jump.status_code == 400 and "Cannot go from SUBMITTED to DELIVERED" in jump.json()["detail"]

    _advance(admin, rid, "SHARED", "APPROVED", "DELIVERED")
    reopen = _patch(admin, rid, status="IN_REVIEW")
    assert reopen.status_code == 400
    assert _patch(admin, rid, status="NONSENSE").status_code == 400


def test_declining_requires_a_reason_and_reaches_the_business(admin):
    rid, cook = _application(admin)
    bare = _patch(admin, rid, status="DECLINED")
    assert bare.status_code == 400 and "reason" in bare.json()["detail"].lower()

    ok = _patch(admin, rid, status="DECLINED", decline_reason="Needs 6 months of records")
    assert ok.status_code == 200 and ok.json()["status"] == "DECLINED"
    mine = client.get("/app/api/my-applications", cookies=cook).json()["applications"][0]
    assert mine["status"] == "DECLINED" and mine["decline_reason"] == "Needs 6 months of records"


def test_partner_reference_is_recorded_and_changes_are_audited(admin):
    rid, _cook = _application(admin)
    r = _patch(admin, rid, partner_ref="GW-2026-88", admin_notes="spoke to ops")
    assert r.status_code == 200
    assert r.json()["partner_ref"] == "GW-2026-88"

    db = SessionLocal()
    try:
        assert db.query(AuditLog).filter(
            AuditLog.resource.like(f"finance_application:{rid}%")).count() >= 1
    finally:
        db.close()


def test_businesses_cannot_touch_the_pipeline_or_the_ledger(admin):
    rid, cook = _application(admin)
    assert client.get("/app/api/admin/finance-applications", cookies=cook).status_code == 403
    assert client.patch(f"/app/api/admin/finance-applications/{rid}", cookies=cook,
                        json={"status": "DELIVERED"}).status_code == 403
    assert client.post(f"/app/api/admin/finance-applications/{rid}/commission", cookies=cook,
                       json={"status": "PAID"}).status_code == 403
