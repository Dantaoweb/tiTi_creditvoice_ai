"""
Editing a customer's name/phone via PUT /app/api/customers/{id}.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-edit-customer-0000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(6000, 7000))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner():
    n = next(_seq)
    phone = f"234822{n:06d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    cookies = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    return phone, cookies


def _add(cookies, phone, name):
    return client.post("/app/api/customers", cookies=cookies,
                       json={"owner_phone": phone, "name": name}).json()


def test_rename_customer():
    phone, cook = _owner()
    c = _add(cook, phone, "ade")
    r = client.put(f"/app/api/customers/{c['id']}", cookies=cook,
                   json={"name": "Ade Bello", "phone": "08011112222"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Ade Bello"
    assert r.json()["phone"] == "08011112222"
    # Shows up renamed in the list
    rows = client.get("/app/api/customers", cookies=cook,
                      params={"owner_phone": phone}).json()["customers"]
    assert any(x["name"] == "Ade Bello" for x in rows)


def test_rename_blocks_duplicate():
    phone, cook = _owner()
    _add(cook, phone, "musa")
    b = _add(cook, phone, "bola")
    r = client.put(f"/app/api/customers/{b['id']}", cookies=cook, json={"name": "musa"})
    assert r.status_code == 409


def test_rename_empty_rejected():
    phone, cook = _owner()
    c = _add(cook, phone, "sade")
    r = client.put(f"/app/api/customers/{c['id']}", cookies=cook, json={"name": "   "})
    assert r.status_code == 400


def test_cannot_edit_other_owners_customer():
    p1, cook1 = _owner()
    c = _add(cook1, p1, "kemi")
    _p2, cook2 = _owner()
    r = client.put(f"/app/api/customers/{c['id']}", cookies=cook2, json={"name": "hacked"})
    assert r.status_code == 404
