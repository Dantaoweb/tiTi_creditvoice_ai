"""
Security fixes (2026-11-15):
- the Monnify subscription webhook always checks its signature — a forged
  "PAID" with no signature used to activate a plan for free;
- the public supplier directory and ratings never show phone numbers or
  CreditVoice's review notes;
- an offline record is never replayed to a login that was signed out since.
"""
import hashlib
import hmac
import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-security-fixes-000000000")

import pytest
from fastapi.testclient import TestClient

import web_auth

from database import SessionLocal
from main import app
from models import SubscriptionPayment, User, VerifiedSupplier

client = TestClient(app)
_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _pending_card_payment():
    phone = f"2347131{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Free Rider", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.phone == phone).first()
        p = SubscriptionPayment(user_id=u.id, phone=phone, plan="PREMIUM", amount=10000, status="PENDING",
                                payment_method="MONNIFY", evidence_ref="CVREF-TEST-1" + str(next(_seq)))
        db.add(p); db.commit()
        return phone, p.id, p.evidence_ref
    finally:
        db.close()


def _event(ref):
    return json.dumps({"eventType": "SUCCESSFUL_TRANSACTION",
                       "eventData": {"paymentStatus": "PAID", "paymentReference": ref, "amountPaid": 10000}}).encode()


def _status(pid):
    db = SessionLocal()
    try:
        return db.query(SubscriptionPayment).filter(SubscriptionPayment.id == pid).first().status
    finally:
        db.close()


def test_forged_card_payment_is_refused(monkeypatch):
    monkeypatch.setenv("MONNIFY_SECRET_KEY", "monnify-test-secret")
    _phone, pid, ref = _pending_card_payment()
    body = _event(ref)
    # No signature at all: refused (this used to activate the plan)
    r = client.post("/app/api/webhooks/monnify/subscription", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 401 and _status(pid) == "PENDING"
    # A wrong signature: refused
    r = client.post("/app/api/webhooks/monnify/subscription", content=body,
                    headers={"Content-Type": "application/json", "monnify-signature": "00" * 64})
    assert r.status_code == 401 and _status(pid) == "PENDING"
    # Monnify's real signature: accepted
    sig = hmac.new(b"monnify-test-secret", body, hashlib.sha512).hexdigest()
    r = client.post("/app/api/webhooks/monnify/subscription", content=body,
                    headers={"Content-Type": "application/json", "monnify-signature": sig})
    assert r.status_code == 200 and _status(pid) == "APPROVED"


def test_no_key_in_production_means_no_webhook(monkeypatch):
    monkeypatch.delenv("MONNIFY_SECRET_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    _phone, pid, ref = _pending_card_payment()
    r = client.post("/app/api/webhooks/monnify/subscription", content=_event(ref),
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 401 and _status(pid) == "PENDING"


def test_public_directory_shows_no_phone_numbers():
    phone = f"2347132{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Cement Depot", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    try:
        db.add(VerifiedSupplier(owner_phone=phone, supplier_type="manufacturer", bio="We sell cement",
                                verification_status="approved", rejection_reason="internal note"))
        db.commit()
    finally:
        db.close()
    anon = TestClient(app)
    body = anon.get("/app/api/verified-suppliers/directory").text
    assert phone not in body and "internal note" not in body
    assert "Cement Depot" in body or "We sell cement" in body


def test_offline_answer_not_replayed_after_signing_out_everywhere():
    c = TestClient(app)
    phone = f"2347133{next(_seq):06d}"
    c.post("/app/api/auth/register", json={"name": "Replay Shop", "phone": phone, "pin": "5678"})
    c.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"})
    h = {"X-Client-Ref": "replay-after-revoke-1"}
    assert c.post("/app/api/expenses", headers=h, json={"amount": 100, "category": "Other"}).status_code == 200
    db = SessionLocal()
    u = db.query(User).filter(User.phone == phone).first()
    u.token_version = (u.token_version or 0) + 1          # signed out everywhere
    db.commit(); db.close()
    r = c.post("/app/api/expenses", headers=h, json={"amount": 100, "category": "Other"})
    assert r.status_code == 401 and "X-Client-Ref-Replayed" not in r.headers
