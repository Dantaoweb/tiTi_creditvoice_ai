"""
Regression: token/plan upgrade must actually lift Basic limits (issue #6).

Two bugs were found and fixed:

1. The WhatsApp redeem parser matched a lowercased keyword against an
   uppercased subject with no IGNORECASE flag, so redemption never fired; it
   also stripped the hyphen the stored code contains. Redeeming on WhatsApp
   was impossible.

2. The web active-inventory and school-teacher limit checks read the plan with
   getattr(subscription_dict, "plan", "BASIC") — getattr never finds a dict
   key, so every upgraded user was pinned to BASIC and capped at 5 products /
   3 teachers despite a valid GO/PRO plan.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-token-upgrade-tests-000000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import TokenCode
from parser import parse_message

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _register_login(phone):
    client.post("/app/api/auth/register", json={"name": "T", "phone": phone, "pin": "5678"})
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def _make_token(code, plan="GO", days=30):
    db = SessionLocal()
    db.add(TokenCode(code=code, plan=plan, duration_days=days))
    db.commit()
    db.close()


# ── Bug 1: WhatsApp redeem parser fires (case + hyphen tolerant) ──────────────

@pytest.mark.parametrize("text,expected", [
    ("redeem GO-AB12CD34", "GO-AB12CD34"),
    ("REDEEM go-ab12cd34", "GO-AB12CD34"),
    ("activate code PRO-XYZ99Q11", "PRO-XYZ99Q11"),
    ("use GOAB12CD34", "GOAB12CD34"),
])
def test_redeem_parses(text, expected):
    r = parse_message(text)
    assert r is not None and r.get("type") == "REDEEM_TOKEN"
    assert r.get("code") == expected


# ── Bug 1: web redeem activates even if the hyphen is omitted ─────────────────

def test_web_redeem_without_hyphen_activates():
    cookies = _register_login("2788000001")
    _make_token("GO-AB12CD34", "GO")
    r = client.post("/app/api/token-codes/redeem", json={"code": "goab12cd34"}, cookies=cookies)
    assert r.status_code == 200, r.text
    assert r.json()["plan"] == "GO"
    me = client.get("/app/api/auth/me", cookies=cookies).json()
    assert me["subscription_plan"] == "GO"


# ── Bug 2: upgraded user is no longer capped at 5 active products ─────────────

def _add_item(cookies, phone, name):
    return client.post("/app/api/inventory",
                       json={"owner_phone": phone, "name": name, "selling_price": 100, "quantity": 5},
                       cookies=cookies)


def test_go_user_can_exceed_five_products():
    phone = "2788000002"
    cookies = _register_login(phone)
    _make_token("GO-INVTEST1", "GO")
    assert client.post("/app/api/token-codes/redeem", json={"code": "GO-INVTEST1"},
                       cookies=cookies).status_code == 200
    for i in range(6):
        r = _add_item(cookies, phone, f"go{i}")
        assert r.status_code == 200, f"item {i} rejected: {r.text}"


def test_basic_user_still_capped_at_five():
    phone = "2788000003"
    cookies = _register_login(phone)
    for i in range(5):
        assert _add_item(cookies, phone, f"b{i}").status_code == 200
    sixth = _add_item(cookies, phone, "b5")
    assert sixth.status_code == 403
    assert "limit" in sixth.json()["detail"].lower()
