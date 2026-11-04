"""
Business page: an admin switches it on after the one-time payment; the owner
chooses what shows and turns it on; visitors see /b/<name> and ask for a
quotation; the owner turns that request into a quotation with one tap.
Never shown: stock counts, cost prices, products not picked.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-business-page-0000000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
import web_pay_link_routes
from database import SessionLocal
from main import app
from models import Customer, InventoryItem, Invoice, PageEnquiry, User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda *a, **k: True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    web_pay_link_routes._hits.clear()
    yield


def _login(phone, pin="5678"):
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": pin}).cookies


def _business(name="Adeola Sanitary Wares"):
    phone = f"2347071{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": "5678"})
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(phone=phone).one()
        u.business_type_label = name
        u.address = "12 Ojo Road, Alaba"
        u.subscription_plan = "PREMIUM"; u.subscription_status = "ACTIVE"
        tank = InventoryItem(owner_phone=phone, name="water tank 2000l", unit="piece", selling_price=185000,
                             cost_price=150000, quantity=7, is_available=True, category="tanks")
        wc = InventoryItem(owner_phone=phone, name="close couple wc", unit="set", selling_price=95000,
                           cost_price=70000, quantity=0, is_available=True, category="sanitary")
        hidden = InventoryItem(owner_phone=phone, name="secret stock", selling_price=1000, quantity=3,
                               is_available=True)
        db.add_all([tank, wc, hidden]); db.commit()
        ids = (u.id, tank.id, wc.id, hidden.id)
    finally:
        db.close()
    return phone, _login(phone), ids


def _admin():
    from admin import ROLE_APP_ADMIN, normalize_phone
    from models import AppAdminRole
    phone = f"2347072{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Admin", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    db.add(AppAdminRole(phone=normalize_phone(phone), role=ROLE_APP_ADMIN, is_active=True))
    db.commit(); db.close()
    return _login(phone)


def _switch_on(admin, uid, slug=None):
    return client.post(f"/app/api/admin/business-page/{uid}", cookies=admin,
                       json={"enabled": True, **({"slug": slug} if slug else {})})


def test_the_whole_journey():
    phone, cook, (uid, tank, wc, hidden) = _business()
    admin = _admin()

    # Not paid for: the owner can see it's not active, can't change it; no page
    st = client.get("/app/api/business-page", cookies=cook).json()
    assert st["enabled"] is False and st["live"] is False
    assert client.put("/app/api/business-page", cookies=cook, json={"on": True}).status_code == 403

    # Admin switches it on: an address from the business name
    r = _switch_on(admin, uid)
    assert r.status_code == 200, r.text
    assert r.json()["page_slug"] == "adeola-sanitary-wares"
    assert client.get("/b/adeola-sanitary-wares").status_code == 404      # the owner hasn't turned it on

    r = client.put("/app/api/business-page", cookies=cook, json={
        "on": True, "about": "Tanks, WCs, tiles and doors.\n\nDelivery across Lagos.",
        "hours": "Mon–Sat 8am–6pm", "items": [tank, wc]})
    assert r.status_code == 200 and r.json()["live"] is True

    page = client.get("/b/adeola-sanitary-wares")
    assert page.status_code == 200
    body = page.text
    assert "Adeola Sanitary Wares" in body and "Water Tank 2000L" in body and "₦185,000" in body
    assert "Mon–Sat 8am–6pm" in body and "12 Ojo Road" in body and "wa.me/" in body
    assert "Ask for availability" in body                 # the WC is out of stock — said, not counted
    assert "Secret Stock" not in body and "150,000" not in body and ">7<" not in body

    # Prices can be hidden
    client.put("/app/api/business-page", cookies=cook, json={"show_prices": False})
    assert "₦185,000" not in client.get("/b/adeola-sanitary-wares").text

    # A visitor asks for a quotation (a plain form post)
    r = client.post("/b/adeola-sanitary-wares", data={
        "name": "Engr Bello", "phone": "0803 111 2222", "message": "For a duplex in Lekki",
        f"q{tank}": "2", f"q{hidden}": "5"}, follow_redirects=False)
    assert r.status_code == 303 and "sent=1" in r.headers["location"]
    assert "request was sent" in client.get("/b/adeola-sanitary-wares?sent=1").text

    enq = client.get("/app/api/business-page/enquiries", cookies=cook).json()["enquiries"]
    assert len(enq) == 1 and enq[0]["name"] == "Engr Bello"
    assert enq[0]["items"] == [{"id": tank, "name": "Water Tank 2000L", "qty": 2}]    # hidden item ignored
    assert client.get("/app/api/business-page", cookies=cook).json()["new_enquiries"] == 1

    # One tap: a quotation for him, at today's prices
    r = client.post(f"/app/api/business-page/enquiries/{enq[0]['id']}/quote", cookies=cook)
    assert r.status_code == 200, r.text
    inv_id = r.json()["invoice_id"]
    doc = client.get(f"/app/api/invoices/doc/{inv_id}", cookies=cook).json()
    assert doc["customer"]["name"] == "Engr Bello" and doc["total"] == 370000
    assert "duplex in Lekki" in doc["note"]
    assert client.post(f"/app/api/business-page/enquiries/{enq[0]['id']}/quote", cookies=cook).status_code == 400

    # Turned off: the page is gone
    client.put("/app/api/business-page", cookies=cook, json={"on": False})
    assert client.get("/b/adeola-sanitary-wares").status_code == 404


def test_bad_requests_and_bots():
    phone, cook, (uid, tank, _wc, _h) = _business("Kola Tiles")
    _switch_on(_admin(), uid, slug="kola-tiles")
    client.put("/app/api/business-page", cookies=cook, json={"on": True, "items": [tank]})
    r = client.post("/b/kola-tiles", data={"name": "A", "phone": "123"})
    assert r.status_code == 400 and "Enter your name" in r.text
    r = client.post("/b/kola-tiles", data={"name": "Ade", "phone": "08031112222"})
    assert r.status_code == 400 and "Say what you need" in r.text and 'value="Ade"' in r.text   # kept what they typed
    # The hidden field only bots fill: looks sent, nothing saved
    r = client.post("/b/kola-tiles", data={"name": "Bot", "phone": "08031112222", "message": "x",
                                          "website": "spam.example"}, follow_redirects=False)
    assert r.status_code == 303
    db = SessionLocal()
    assert db.query(PageEnquiry).filter(PageEnquiry.owner_phone == phone).count() == 0
    db.close()
    # What a visitor types is shown as text, never run
    r = client.post("/b/kola-tiles", data={"name": "<script>x</script>", "phone": "1"})
    assert "<script>x</script>" not in r.text and "&lt;script&gt;" in r.text


def test_addresses_staff_and_admin_rules():
    _p1, cook1, (uid1, *_r) = _business("Lagos Doors")
    p2, cook2, (uid2, *_s) = _business("Lagos Doors")
    admin = _admin()
    assert _switch_on(admin, uid1).json()["page_slug"] == "lagos-doors"
    assert _switch_on(admin, uid2).json()["page_slug"] == "lagos-doors-2"          # the next free one
    r = _switch_on(admin, uid2, slug="lagos-doors")
    assert r.status_code == 400 and "taken" in r.json()["detail"]
    assert _switch_on(admin, uid2, slug="admin").status_code == 400
    assert _switch_on(admin, uid2, slug="ab").status_code == 400
    # Not an admin
    assert client.post(f"/app/api/admin/business-page/{uid2}", cookies=cook1, json={"enabled": True}).status_code == 403
    # Staff can't change the page; a cashier can't see the requests
    db = SessionLocal()
    owner = db.query(User).filter(User.phone == p2).first()
    sp = f"2347073{next(_seq):06d}"
    db.add(User(phone=sp, name="Cashier", role="delegate", parent_id=owner.id,
                recovery_pin_hash=web_auth._hash_pin("1234"), subscription_status="ACTIVE"))
    db.commit(); db.close()
    staff = _login(sp, "1234")
    assert client.put("/app/api/business-page", cookies=staff, json={"on": True}).status_code == 403
    assert client.get("/app/api/business-page/enquiries", cookies=staff).status_code == 403
    # Admin switches it off: the page goes, whatever the owner chose
    client.put("/app/api/business-page", cookies=cook2, json={"on": True})
    assert client.get("/b/lagos-doors-2").status_code == 200
    client.post(f"/app/api/admin/business-page/{uid2}", cookies=admin, json={"enabled": False})
    assert client.get("/b/lagos-doors-2").status_code == 404


def test_sitemap_lists_live_pages():
    _p, cook, (uid, *_r) = _business("Sitemap Tanks")
    _switch_on(_admin(), uid, slug="sitemap-tanks")
    assert "/b/sitemap-tanks" not in client.get("/sitemap.xml").text
    client.put("/app/api/business-page", cookies=cook, json={"on": True})
    assert "https://creditvoiceai.com/b/sitemap-tanks" in client.get("/sitemap.xml").text


def test_titi_explains_the_business_page():
    from faq import FAQ_ANSWERS, detect_faq
    assert detect_faq("how do i get a business page?") == "business_page"
    assert detect_faq("can i have my own website?") == "business_page"
    assert "one-time payment" in FAQ_ANSWERS["business_page"] and "Make quotation" in FAQ_ANSWERS["business_page"]
