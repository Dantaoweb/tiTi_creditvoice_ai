"""
Web partner flow: a copyable invite link (token) that any logged-in invitee can
open and accept — binding their account as the partner — plus a scoped web
overview of the business they joined.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-partners-000000000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, BusinessPartner

client = TestClient(app)
_seq = iter(range(7300, 7999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _user(name):
    n = next(_seq)
    phone = f"234818{n:06d}"
    client.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": "2468"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "2468"}).cookies
    return phone, cook


def _pending_invite(owner_phone, partner_phone, token):
    db = SessionLocal()
    try:
        from datetime import datetime, timezone
        bp = BusinessPartner(
            owner_phone=owner_phone, partner_phone=partner_phone,
            role="investor", access_level="financial",
            equity_percent=25.0, investment_amount=500000,
            status="pending", invite_token=token,
            invited_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(bp); db.commit()
        return bp.id
    finally:
        db.close()


def test_invite_link_can_be_opened_and_accepted():
    owner_phone, _ = _user("Owner")
    inv_phone, inv_cook = _user("Investor")
    bp_id = _pending_invite(owner_phone, "234800000000", "tok-abc-123")

    info = client.get("/app/api/partners/join/tok-abc-123", cookies=inv_cook).json()
    assert info["role_label"] == "Investor"
    assert info["investment_amount"] == 500000
    assert info["status"] == "pending"
    assert info["is_own_invite"] is False

    r = client.post("/app/api/partners/join/tok-abc-123/accept", cookies=inv_cook)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"

    # Bound to the accepting account, now active.
    db = SessionLocal()
    try:
        bp = db.query(BusinessPartner).filter(BusinessPartner.id == bp_id).one()
        assert bp.status == "active"
        assert bp.partner_phone == inv_phone
    finally:
        db.close()


def test_owner_cannot_accept_own_invite():
    owner_phone, owner_cook = _user("Owner")
    _pending_invite(owner_phone, "234800000001", "tok-self")
    r = client.post("/app/api/partners/join/tok-self/accept", cookies=owner_cook)
    assert r.status_code == 400


def test_scoped_overview_after_accept():
    owner_phone, _ = _user("Owner")
    inv_phone, inv_cook = _user("Investor")
    bp_id = _pending_invite(owner_phone, "234800000002", "tok-ov")
    client.post("/app/api/partners/join/tok-ov/accept", cookies=inv_cook)

    ov = client.get(f"/app/api/partners/overview/{bp_id}", cookies=inv_cook).json()
    assert ov["role_label"] == "Investor"
    assert ov["show_sales"] is True          # financial access sees sales summary
    assert ov["show_investment"] is True
    assert ov["show_customers"] is False     # not full access
    assert ov["investment_amount"] == 500000
    assert ov["equity_percent"] == 25.0
    assert "sales_30d" in ov


def test_owner_list_backfills_invite_token():
    owner_phone, owner_cook = _user("Owner")
    _pending_invite(owner_phone, "234800000003", None)  # legacy row, no token
    data = client.get("/app/api/partners", cookies=owner_cook).json()
    assert len(data["partners"]) == 1
    assert data["partners"][0]["invite_token"]  # a link is now available
