"""
End-to-end Verified Supplier flow: a Pro business applies, an app-admin approves,
the supplier appears in the public directory, a retailer contacts them, the
message lands in their inbox, and a rating is recorded.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-vsupplier-000000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from admin import ROLE_APP_ADMIN
from database import SessionLocal
from models import User, AppAdminRole
from parser import normalize_phone

client = TestClient(app, raise_server_exceptions=True)

ADMIN = "2348270000001"
SUP   = "2348270000002"   # the applying supplier (Pro)
BUYER = "2348270000003"   # a retailer who contacts them


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


@pytest.fixture(scope="module", autouse=True)
def _seed():
    for ph in (ADMIN, SUP, BUYER):
        client.post("/app/api/auth/register", json={"name": "U", "phone": ph, "pin": "5678"})
    db = SessionLocal()
    try:
        db.add(AppAdminRole(phone=normalize_phone(ADMIN), role=ROLE_APP_ADMIN, is_active=True))
        sup = db.query(User).filter(User.phone == SUP).first()
        sup.subscription_plan = "PRO"; sup.subscription_status = "ACTIVE"
        sup.business_type_label = "Dangote Cement Depot"
        db.commit()
    finally:
        db.close()


def _login(phone):
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def test_full_verified_supplier_flow():
    sup = _login(SUP)
    admin = _login(ADMIN)

    # 1. Apply.
    r = client.post("/app/api/verified-suppliers/apply", cookies=sup, json={
        "supplier_type": "wholesaler",
        "bio": "Bulk cement supplier",
        "states_covered": ["Lagos", "Ogun"],
        "can_deliver": True,
        "products": [{"product_name": "Cement", "category": "building", "available_sizes": ["50kg"],
                      "min_order_qty": 100, "min_order_unit": "bags", "price_range": "N5000-5500"}],
    })
    assert r.status_code == 200, r.text

    # Not yet in the directory (still pending).
    assert client.get("/app/api/verified-suppliers/directory", params={"product": "cement"}).json()["total"] == 0

    # 2. Admin sees it pending, then approves.
    apps = client.get("/app/api/admin/supplier-applications", cookies=admin, params={"status": "pending"}).json()
    sid = next(a["id"] for a in (apps if isinstance(apps, list) else apps.get("applications", apps.get("suppliers", []))))
    ap = client.post(f"/app/api/admin/supplier-applications/{sid}/approve", cookies=admin)
    assert ap.status_code == 200, ap.text

    # 3. Now in the public directory, findable by product.
    d = client.get("/app/api/verified-suppliers/directory", params={"product": "cement"}).json()
    assert d["total"] == 1
    listing = d["suppliers"][0]
    assert listing["supplier_type"] == "wholesaler"
    assert "Lagos" in listing["states_covered"]

    # 4. A retailer contacts them.
    buyer = _login(BUYER)
    c = client.post(f"/app/api/verified-suppliers/{sid}/contact", cookies=buyer,
                    json={"product_interest": "Cement", "message": "Do you deliver to Ikeja?"})
    assert c.status_code == 200, c.text

    # 5. The supplier sees it in their inbox.
    inbox = client.get("/app/api/verified-suppliers/inbox", cookies=sup).json()
    msgs = inbox.get("messages", inbox) if isinstance(inbox, dict) else inbox
    assert any("Ikeja" in (m.get("message") or "") for m in (msgs if isinstance(msgs, list) else []))

    # 6. Rating is recorded.
    rr = client.post(f"/app/api/verified-suppliers/{sid}/rate", cookies=buyer, json={"rating": 5, "review": "Fast"})
    assert rr.status_code == 200, rr.text
    ratings = client.get(f"/app/api/verified-suppliers/{sid}/ratings").json()
    assert (ratings.get("rating_count") or ratings.get("count") or len(ratings.get("ratings", []))) >= 1
