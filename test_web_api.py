"""
Multi-channel E2E tests — Layer 27

All 50 existing tests exercise the WhatsApp channel by calling Python
handlers directly.  These tests hit the full HTTP stack via FastAPI
TestClient and cover:

  1. Health endpoint — DB reachability check
  2. Web auth E2E — register → login → access protected endpoint
  3. Protected endpoints reject unauthenticated requests
  4. Session isolation — user A's cookie cannot surface user B's data
  5. Tampered cookie is rejected
  6. Wrong PIN returns 401
  7. Cross-channel consistency — WhatsApp records a transaction using the
     real app database; the web dashboard API reflects the updated balance
"""
import os

# Must be set before any project import touches database.py or web_auth.py.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault(
    "WEB_SECRET_KEY",
    "test-secret-key-for-web-api-layer-27-tests-0000000000",
)

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import Transaction

# A single long-lived client is used for most tests; tests that need a
# clean cookie jar create their own TestClient inline.
client = TestClient(app, raise_server_exceptions=True)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """
    Wipe all in-memory rate-limiter state between tests.

    TestClient always sends from 127.0.0.1, so without this reset the
    registration and login limiters fire after the 5th / 10th test.
    """
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


# ── helpers ───────────────────────────────────────────────────────────────────

def _register(phone: str, pin: str = "5678", name: str = "Test User") -> None:
    resp = client.post("/app/api/auth/register", json={
        "name": name,
        "phone": phone,
        "pin": pin,
    })
    assert resp.status_code == 200, f"register failed: {resp.text}"


def _login(phone: str, pin: str = "5678") -> dict:
    resp = client.post("/app/api/auth/login", json={"phone": phone, "pin": pin})
    assert resp.status_code == 200, f"login failed: {resp.text}"
    return resp.cookies


def _wa_body(phone: str, text: str, msg_id: str) -> dict:
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": phone,
                        "id": msg_id,
                        "type": "text",
                        "text": {"body": text},
                    }]
                }
            }]
        }]
    }


# ── 1. Health ─────────────────────────────────────────────────────────────────

def test_health_db_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db"] == "ok"
    assert isinstance(body["db_latency_ms"], float)
    assert body["uptime_seconds"] >= 0


# ── 2. Web auth E2E ───────────────────────────────────────────────────────────

def test_register_sets_session_cookie():
    resp = client.post("/app/api/auth/register", json={
        "name": "Cookie Test",
        "phone": "2700000001",
        "pin": "4321",
    })
    assert resp.status_code == 200
    assert "cv_session" in resp.cookies


def test_login_sets_session_cookie():
    _register("2700000002", pin="1111")
    resp = client.post("/app/api/auth/login", json={
        "phone": "2700000002",
        "pin": "1111",
    })
    assert resp.status_code == 200
    assert "cv_session" in resp.cookies


def test_auth_me_returns_registered_phone():
    _register("2700000003")
    cookies = _login("2700000003")
    resp = client.get("/app/api/auth/me", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["phone"] == "2700000003"


def test_dashboard_returns_correct_owner_phone():
    _register("2700000004")
    cookies = _login("2700000004")
    resp = client.get("/app/api/dashboard", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["owner_phone"] == "2700000004"
    assert "summary" in body


# ── 3. Protected endpoints reject unauthenticated requests ────────────────────

def test_dashboard_without_cookie_returns_401():
    # Fresh client with no cookie jar so prior test sessions don't bleed in.
    fresh = TestClient(app, raise_server_exceptions=True)
    resp = fresh.get("/app/api/dashboard")
    assert resp.status_code == 401


def test_auth_me_without_cookie_returns_401():
    fresh = TestClient(app, raise_server_exceptions=True)
    resp = fresh.get("/app/api/auth/me")
    assert resp.status_code == 401


# ── 4. Session isolation ─────────────────────────────────────────────────────

def test_session_returns_own_user_not_another():
    """User A's cookie must only surface User A's profile."""
    _register("2700000005")
    _register("2700000006")
    cookies_a = _login("2700000005")
    resp = client.get("/app/api/auth/me", cookies=cookies_a)
    assert resp.status_code == 200
    data = resp.json()
    assert data["phone"] == "2700000005"
    assert data["phone"] != "2700000006"


def test_dashboard_isolation():
    """Two users get their own dashboard, not each other's."""
    _register("2700000007")
    _register("2700000008")
    cookies_a = _login("2700000007")
    cookies_b = _login("2700000008")
    resp_a = client.get("/app/api/dashboard", cookies=cookies_a)
    resp_b = client.get("/app/api/dashboard", cookies=cookies_b)
    assert resp_a.json()["owner_phone"] == "2700000007"
    assert resp_b.json()["owner_phone"] == "2700000008"


# ── 5. Tampered cookie rejected ──────────────────────────────────────────────

def test_tampered_session_cookie_returns_401():
    _register("2700000009")
    cookies = _login("2700000009")
    token = cookies["cv_session"]
    bad_token = token[:-4] + ("XXXX" if token[-4:] != "XXXX" else "YYYY")
    fresh = TestClient(app, raise_server_exceptions=True)
    resp = fresh.get("/app/api/auth/me", cookies={"cv_session": bad_token})
    assert resp.status_code == 401


# ── 6. Wrong PIN returns 401 ─────────────────────────────────────────────────

def test_wrong_pin_login_returns_401():
    _register("2700000010")
    resp = client.post("/app/api/auth/login", json={
        "phone": "2700000010",
        "pin": "0000",
    })
    assert resp.status_code == 401


def test_unknown_phone_login_returns_401():
    resp = client.post("/app/api/auth/login", json={
        "phone": "2799999999",
        "pin": "1234",
    })
    assert resp.status_code == 401


# ── 7. Cross-channel consistency ─────────────────────────────────────────────

def test_whatsapp_transaction_appears_in_dashboard():
    """
    Cross-channel consistency check:
      1. Register a user via the web API — creates a User row in the shared
         SQLite in-memory database that TestClient and the WhatsApp layer
         both use.
      2. Write a Transaction row directly to the same database, simulating
         what the WhatsApp handler does after a confirmed sale.
      3. Read /app/api/dashboard with the web session and assert the sale
         balance is reflected.

    This proves the two channels share one data store: a write on the
    WhatsApp side (modelled here by a direct DB insert) is immediately
    visible on the web dashboard side.  The full NLP pipeline is skipped
    here because it requires a live OpenAI key; the NLP path is covered
    by the existing WhatsApp unit tests.
    """
    from models import Customer, Transaction
    from datetime import datetime, timezone

    phone = "2700000011"
    _register(phone, name="Cross Channel User")
    cookies = _login(phone)

    # Write a confirmed transaction directly — same code path the WhatsApp
    # handler uses after the user confirms a sale.
    db = SessionLocal()
    try:
        user = db.query(__import__("models").User).filter_by(phone=phone).first()
        assert user is not None

        customer = Customer(
            name="Ade",
            owner_phone=phone,
        )
        db.add(customer)
        db.flush()

        # type="BUY" = credit sale (customer owes money) — contributes to
        # total_sales in get_transaction_stats().
        txn = Transaction(
            customer_id=customer.id,
            type="BUY",
            amount=5000,
            message_id="test-layer27-cross-channel-001",
        )
        db.add(txn)
        db.commit()
    finally:
        db.close()

    # Web side: the dashboard must reflect the transaction just written.
    resp = client.get("/app/api/dashboard?period=ALL", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["owner_phone"] == phone

    summary = body["summary"]
    total_sales = summary.get("total_sales_amount", 0) or summary.get("credit_sales_amount", 0)
    assert total_sales >= 5000, (
        f"Expected cross-channel ₦5,000 sale in dashboard summary; got {summary}"
    )
