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

    # 5. The supplier sees it in their inbox — but the buyer's phone is hidden
    #    until they accept, and the request is awaiting their decision.
    inbox = client.get("/app/api/verified-suppliers/inbox", cookies=sup).json()
    msg = next(m for m in inbox["messages"] if "Ikeja" in (m.get("message") or ""))
    assert msg["connection_status"] == "forwarded"
    assert msg["from_phone"] is None
    mid = msg["id"]

    # 6. Rating is blocked before a handshake.
    early = client.post(f"/app/api/verified-suppliers/{sid}/rate", cookies=buyer, json={"rating": 5})
    assert early.status_code == 403

    # 7. Supplier accepts → both contacts are revealed.
    acc = client.post(f"/app/api/verified-suppliers/connections/{mid}/respond", cookies=sup, json={"action": "accept"})
    assert acc.status_code == 200 and acc.json()["connection_status"] == "accepted", acc.text
    # Supplier now sees the buyer's phone.
    inbox2 = client.get("/app/api/verified-suppliers/inbox", cookies=sup).json()
    assert next(m for m in inbox2["messages"] if m["id"] == mid)["from_phone"] == BUYER
    # Buyer now sees the supplier's phone + can rate.
    conns = client.get("/app/api/verified-suppliers/my-connections", cookies=buyer).json()["connections"]
    mine = next(c for c in conns if c["id"] == mid)
    assert mine["connection_status"] == "accepted" and mine["supplier_phone"] == SUP and mine["can_rate"] is True

    # 8. Rating now succeeds and is counted.
    rr = client.post(f"/app/api/verified-suppliers/{sid}/rate", cookies=buyer, json={"rating": 5, "review": "Fast"})
    assert rr.status_code == 200, rr.text
    ratings = client.get(f"/app/api/verified-suppliers/{sid}/ratings").json()
    assert (ratings.get("rating_count") or ratings.get("count") or len(ratings.get("ratings", []))) >= 1


def _sid(admin):
    apps = client.get("/app/api/admin/supplier-applications", cookies=admin, params={"status": "approved"}).json()
    return apps["applications"][0]["id"]


def test_decline_hides_contact_and_blocks_rating():
    sup, buyer, admin = _login(SUP), _login(BUYER), _login(ADMIN)
    sid = _sid(admin)
    c = client.post(f"/app/api/verified-suppliers/{sid}/contact", cookies=buyer,
                    json={"product_interest": "Cement", "message": "Bulk order for Q3?"})
    assert c.status_code == 200
    mid = next(m["id"] for m in client.get("/app/api/verified-suppliers/inbox", cookies=sup).json()["messages"]
               if "Q3" in m["message"])

    dec = client.post(f"/app/api/verified-suppliers/connections/{mid}/respond", cookies=sup, json={"action": "decline"})
    assert dec.status_code == 200 and dec.json()["connection_status"] == "declined"

    # Buyer sees declined, no phone, cannot rate.
    mine = next(c for c in client.get("/app/api/verified-suppliers/my-connections", cookies=buyer).json()["connections"]
                if c["id"] == mid)
    assert mine["connection_status"] == "declined" and mine["supplier_phone"] is None and mine["can_rate"] is False
    # Responding again is rejected.
    again = client.post(f"/app/api/verified-suppliers/connections/{mid}/respond", cookies=sup, json={"action": "accept"})
    assert again.status_code == 400


def test_admin_can_block_enquiry():
    sup, buyer, admin = _login(SUP), _login(BUYER), _login(ADMIN)
    sid = _sid(admin)
    client.post(f"/app/api/verified-suppliers/{sid}/contact", cookies=buyer,
                json={"product_interest": "Cement", "message": "Spammy blockme request"})
    mid = next(m["id"] for m in client.get("/app/api/verified-suppliers/inbox", cookies=sup).json()["messages"]
               if "blockme" in m["message"])

    b = client.post(f"/app/api/admin/supplier-connections/{mid}/block", cookies=admin)
    assert b.status_code == 200
    # Gone from the supplier's inbox and can't be accepted.
    assert all(m["id"] != mid for m in client.get("/app/api/verified-suppliers/inbox", cookies=sup).json()["messages"])
    resp = client.post(f"/app/api/verified-suppliers/connections/{mid}/respond", cookies=sup, json={"action": "accept"})
    assert resp.status_code == 403
    # A non-admin cannot block.
    assert client.post(f"/app/api/admin/supplier-connections/{mid}/block", cookies=buyer).status_code == 403
