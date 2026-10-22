"""
Pay links: the customer opens a page from WhatsApp (no app, no account),
sees what to pay and the bank to transfer to, and taps "I've paid". The owner
checks their bank and confirms — only then is a payment recorded.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-pay-links-000000000000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import AppNotification, Customer, InventoryItem, PaymentClaim, User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))
sent = []
ACCT = {"bank": "GTBank", "number": "0123456789", "name": "Bello Stores"}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    sent.clear()
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message",
                        lambda to, m, *a, **k: sent.append((to, m)) or True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _shop(bank=True):
    n = next(_seq)
    phone, staff_phone, cust_phone = f"2348099{n:06d}", f"2348100{n:06d}", f"2348101{n:06d}"
    client.post("/app/api/auth/register", json={"name": "Bello Stores", "phone": phone, "pin": "5678"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    if bank:
        client.put("/app/api/auth/profile", cookies=cook, json={"name": "Bello Stores", "bank_accounts": [ACCT]})
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.phone == phone).first()
        owner.subscription_plan = "PRO"; owner.subscription_status = "ACTIVE"
        db.add(User(phone=staff_phone, name="Sule", role="delegate", parent_id=owner.id,
                    can_view_all_transactions=False, recovery_pin_hash=web_auth._hash_pin("1234"),
                    subscription_status="ACTIVE"))
        item = InventoryItem(owner_phone=phone, name="rice", unit="bag", quantity=100,
                             selling_price=45000, cost_price=40000, is_available=True)
        cust = Customer(owner_phone=phone, name="ade", customer_phone=cust_phone, balance=0)
        db.add_all([item, cust]); db.commit()
        ids = item.id, cust.id
    finally:
        db.close()
    staff = client.post("/app/api/auth/login", json={"phone": staff_phone, "pin": "1234"}).cookies
    return phone, cook, staff, cust_phone, *ids


def _invoice(cook, item_id, cust):
    r = client.post("/app/api/invoices/new", cookies=cook, json={
        "customer_id": cust, "items": [{"inventory_item_id": item_id, "name": "rice", "qty": 1, "unit_price": 45000}]})
    return client.get(f"/app/api/invoices/doc/{r.json()['id']}", cookies=cook).json()


def _token(link):
    return link.rsplit("/", 1)[1]


def test_links_are_signed():
    from payment_links import make_token, read_token
    t = make_token("i", 12)
    assert read_token(t) == ("invoice", 12)
    assert read_token(t.replace("i12", "i13")) is None and read_token("c5-000000000000") is None
    assert client.get("/app/api/public/pay/i13-abcdefabcdef").status_code == 404


def test_invoice_link_page_claim_confirm():
    phone, cook, staff, _cp, item_id, cust = _shop()
    doc = _invoice(cook, item_id, cust)
    assert doc["pay_link"] and "/app/pay/i" in doc["pay_link"]
    from invoices import format_invoice_doc_text
    assert "Paid? Tell us here:" in format_invoice_doc_text(doc)

    token = _token(doc["pay_link"])
    page = client.get(f"/app/api/public/pay/{token}").json()          # no login
    assert (page["amount"], page["label"], page["bank_accounts"]) == (45000, doc["ref"], [ACCT])
    assert page["claim_pending"] is False

    sent.clear()
    r = client.post(f"/app/api/public/pay/{token}/claim", json={"name": "Ade", "note": "sent from Opay"})
    assert r.status_code == 200 and r.json()["claim_pending"] is True
    assert sent and sent[0][0] == phone and "PAYMENT TO CONFIRM" in sent[0][1]
    db = SessionLocal()
    try:
        assert db.query(AppNotification).filter(AppNotification.owner_phone == phone,
                                                AppNotification.event_type == "payment_claim").count() == 1
    finally:
        db.close()

    claims = client.get("/app/api/payment-claims", cookies=cook).json()
    assert claims["pending"] == 1 and claims["claims"][0]["amount"] == 45000
    cid = claims["claims"][0]["id"]
    # Regular staff can't confirm money
    assert client.post(f"/app/api/payment-claims/{cid}/confirm", cookies=staff, json={}).status_code == 403

    sent.clear()
    done = client.post(f"/app/api/payment-claims/{cid}/confirm", cookies=cook, json={"amount": 30000}).json()
    assert done["status"] == "confirmed"
    inv = client.get(f"/app/api/invoices/doc/{doc['id']}", cookies=cook).json()
    assert inv["status"] == "part_paid" and inv["amount_paid"] == 30000          # the rest is debt
    assert any("RECEIPT" in m.upper() for _to, m in sent)                       # customer got a receipt
    assert client.get(f"/app/api/public/pay/{token}").json()["settled"] is True
    assert client.post(f"/app/api/payment-claims/{cid}/confirm", cookies=cook, json={}).status_code == 400


def test_balance_link_and_reject():
    phone, cook, _s, cust_phone, item_id, cust = _shop()
    client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "customer_id": cust, "payment_amount": 0,
        "items": [{"inventory_item_id": item_id, "name": "rice", "qty": 1, "unit": "bag", "unit_price": 45000}]})
    link = client.get(f"/app/api/pay-links/customer/{cust}", cookies=cook).json()["link"]
    assert "/app/pay/c" in link
    token = _token(link)
    assert client.get(f"/app/api/public/pay/{token}").json()["amount"] == 45000

    client.post(f"/app/api/public/pay/{token}/claim", json={"amount": 10000})
    cid = client.get("/app/api/payment-claims", cookies=cook).json()["claims"][0]["id"]
    assert client.post(f"/app/api/payment-claims/{cid}/reject", cookies=cook, json={}).status_code == 400
    sent.clear()
    r = client.post(f"/app/api/payment-claims/{cid}/reject", cookies=cook, json={"reason": "Not in my account yet"})
    assert r.json()["status"] == "rejected"
    assert sent and sent[0][0] == cust_phone and "couldn't find" in sent[0][1]

    # Again, confirmed: the balance goes down
    client.post(f"/app/api/public/pay/{token}/claim", json={"amount": 10000})
    cid = [c for c in client.get("/app/api/payment-claims", cookies=cook).json()["claims"] if c["status"] == "pending"][0]["id"]
    client.post(f"/app/api/payment-claims/{cid}/confirm", cookies=cook, json={})
    assert client.get(f"/app/api/public/pay/{token}").json()["amount"] == 35000


def test_no_bank_account_no_link():
    _phone, cook, _s, _cp, item_id, cust = _shop(bank=False)
    assert _invoice(cook, item_id, cust)["pay_link"] is None


def test_customer_replies_paid_on_whatsapp():
    phone, cook, _s, cust_phone, item_id, cust = _shop()
    doc = _invoice(cook, item_id, cust)
    from payment_links import whatsapp_paid_reply
    db = SessionLocal()
    try:
        assert whatsapp_paid_reply(db, cust_phone, "hello") is None
        out = whatsapp_paid_reply(db, cust_phone, "I have paid 45,000")
        db.commit()
        assert "We've told" in out["reply"] and out["claim"].amount == 45000
        assert out["claim"].invoice_id == doc["id"] and out["claim"].source == "whatsapp"
        assert whatsapp_paid_reply(db, "2348000000000", "paid") is None       # not anyone's customer
    finally:
        db.close()


@pytest.mark.parametrize("text", [
    "how do customers use the pay link?", "how do I confirm payment", "customer says he paid, what do I do?",
    "can customers pay by transfer?",
])
def test_titi_explains_pay_links(text):
    from faq import detect_faq
    from messages import build_app_guide_message
    from parser import parse_message
    p = parse_message(text) or {}
    assert (p["topic"] if p.get("type") == "APP_GUIDE" else detect_faq(text)) == "pay_link"
    a = build_app_guide_message("pay_link")
    assert "My Profile" in a and "Payments to confirm" in a and "PAID" in a
