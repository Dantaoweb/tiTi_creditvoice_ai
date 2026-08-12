"""
Dashboard period filter: "All Time" (the web client sends "", which apiFetch
drops) must resolve to all-time, not silently fall back to today's figures.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-dash-period-0000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(7000, 7999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner():
    n = next(_seq)
    phone = f"234899911{n:04d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    return phone, client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def test_dashboard_absent_period_is_all_time_not_today():
    _p, cook = _owner()
    # No period param = what the client sends for "All Time" (empty is dropped).
    r = client.get("/app/api/dashboard", cookies=cook).json()
    assert r["period"] is None
    assert r["period_label"] == "all time"

    # An explicit period still filters as before.
    today = client.get("/app/api/dashboard", params={"period": "TODAY"}, cookies=cook).json()
    assert today["period"] == "TODAY" and today["period_label"] == "today"

    week = client.get("/app/api/dashboard", params={"period": "WEEK"}, cookies=cook).json()
    assert week["period"] == "WEEK" and week["period_label"] == "this week"
