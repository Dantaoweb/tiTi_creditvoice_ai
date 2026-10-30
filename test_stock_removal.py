"""
Stock that leaves without a sale is always accounted for (reason, value, who);
removing a product takes its stock out with that reason and hides it, never
erasing it. And the phone printed on receipts is the business's choice.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-stock-removal-00000000000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import InventoryItem, InventoryMovement, User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda *a, **k: True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _shop():
    phone = f"2348109{next(_seq):06d}"
    client.post("/app/api/auth/register", json={"name": "Ade Stores", "phone": phone, "pin": "5678"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    db = SessionLocal()
    u = db.query(User).filter_by(phone=phone).one()
    u.subscription_plan = "PREMIUM"; u.subscription_status = "ACTIVE"
    rice = InventoryItem(owner_phone=phone, name="rice", unit="bag", quantity=20, cost_price=60000,
                         selling_price=68000, is_available=True, barcode="6151100099990")
    db.add(rice); db.commit(); rid = rice.id; db.close()
    return phone, cook, rid


def _staff(owner_phone, authorised):
    phone = f"2348109{next(_seq):06d}"
    db = SessionLocal()
    owner = db.query(User).filter_by(phone=owner_phone).one()
    db.add(User(phone=phone, name="Sade", role="delegate", parent_id=owner.id, can_view_all_transactions=authorised,
                subscription_status="ACTIVE", recovery_pin_hash=web_auth._hash_pin("1234")))
    db.commit(); db.close()
    return client.post("/app/api/auth/login", json={"phone": phone, "pin": "1234"}).cookies


def test_removing_stock_needs_a_reason_and_records_its_value():
    _p, cook, rid = _shop()
    assert client.post(f"/app/api/inventory/{rid}/adjust", cookies=cook, json={"qty_delta": -2}).status_code == 400
    assert client.post(f"/app/api/inventory/{rid}/adjust", cookies=cook,
                       json={"qty_delta": -2, "reason": "other"}).status_code == 400          # "Other" needs words
    r = client.post(f"/app/api/inventory/{rid}/adjust", cookies=cook,
                    json={"qty_delta": -2, "reason": "damaged", "note": "rats"})
    assert r.status_code == 200 and r.json()["new_quantity"] == 18
    rep = client.get("/app/api/inventory/removed", cookies=cook).json()
    row = rep["rows"][0]
    assert (row["reason"], row["reason_label"], row["value"], row["note"]) == ("damaged", "Damaged / broken", 120000, "rats")
    assert rep["totals"][0]["value"] == 120000 and rep["total_value"] == 120000
    # adding stock is unchanged
    assert client.post(f"/app/api/inventory/{rid}/adjust", cookies=cook, json={"qty_delta": 3}).json()["new_quantity"] == 21


def test_removing_a_product_accounts_for_its_stock_and_hides_it():
    phone, cook, rid = _shop()
    assert client.post(f"/app/api/inventory/{rid}/remove", cookies=cook, json={"reason": ""}).status_code == 400
    r = client.post(f"/app/api/inventory/{rid}/remove", cookies=cook, json={"reason": "expired", "note": "old batch"}).json()
    assert r["removed"] and r["stock_taken_out"] == 20
    names = [i["name"] for i in client.get("/app/api/inventory", cookies=cook).json()["items"]]
    assert "rice" not in names                                                         # hidden from stock
    assert client.get("/app/api/pos/scan", cookies=cook, params={"code": "6151100099990"}).json()["found"] is False
    rep = client.get("/app/api/inventory/removed?reason=expired", cookies=cook).json()
    assert rep["rows"][0]["product_removed"] and rep["rows"][0]["value"] == 1200000
    db = SessionLocal()
    try:
        item = db.query(InventoryItem).get(rid)                                       # kept, not erased
        assert item.removed_at and item.quantity == 0 and item.is_available is False
        from inventory_suppliers import find_matching_inventory_item
        assert find_matching_inventory_item(db, phone, "rice") is None                 # a new "rice" is a new product
    finally:
        db.close()
    assert client.post(f"/app/api/inventory/{rid}/remove", cookies=cook, json={"reason": "damaged"}).status_code == 400


def test_only_people_who_manage_stock_can_remove():
    phone, cook, rid = _shop()
    plain = _staff(phone, authorised=False)
    assert client.post(f"/app/api/inventory/{rid}/remove", cookies=plain, json={"reason": "damaged"}).status_code == 403
    assert client.get("/app/api/inventory/removed", cookies=plain).status_code == 403
    allowed = _staff(phone, authorised=True)
    r = client.post(f"/app/api/inventory/{rid}/adjust", cookies=allowed, json={"qty_delta": -1, "reason": "stolen"})
    assert r.status_code == 200
    assert client.get("/app/api/inventory/removed", cookies=cook).json()["rows"][0]["by"] == "Sade"


def test_chat_reasons_are_understood():
    from stock_removal import reason_from_words
    assert reason_from_words("spoilage")[0] == "damaged"
    assert reason_from_words("expired")[0] == "expired"
    assert reason_from_words("given to church") == ("other", "given to church")


def test_the_phone_on_receipts_is_the_businesss_choice():
    phone, cook, rid = _shop()
    assert client.put("/app/api/auth/profile", cookies=cook,
                      json={"name": "Ade Stores", "receipt_phones": "abc"}).status_code == 400
    assert client.put("/app/api/auth/profile", cookies=cook, json={"name": "Ade Stores",
                      "receipt_phones": "0803 111 2222 / 0905 333 4444"}).json()["receipt_phones"] == "0803 111 2222 / 0905 333 4444"
    sale = client.post("/app/api/pos/save", cookies=cook, json={
        "owner_phone": phone, "items": [{"name": "rice", "qty": 1, "unit_price": 68000, "inventory_item_id": rid}],
        "payment_amount": 68000}).json()
    rec = client.get(f"/app/api/pos/receipt/{sale['receipt_id']}", cookies=cook).json()
    assert rec["biz_phone"] == "0803 111 2222 / 0905 333 4444"
    from web_pos import format_receipt_text
    assert "Tel: 0803 111 2222 / 0905 333 4444" in format_receipt_text(rec)
    # A branch's own phone wins on that branch's receipts; empty = the business's
    b = client.post("/app/api/branches", cookies=cook, json={"name": "Ikeja", "phone": "0701 000 0000"})
    assert b.status_code == 200, b.text
    if True:
        assert b.json()["phone"] == "0701 000 0000"
        from printables import receipt_phone
        db = SessionLocal()
        try:
            owner = db.query(User).filter_by(phone=phone).one()
            assert receipt_phone(db, owner, b.json()["id"]) == "0701 000 0000"
            assert receipt_phone(db, owner, None) == "0803 111 2222 / 0905 333 4444"
        finally:
            db.close()
    # Cleared: back to the login phone
    client.put("/app/api/auth/profile", cookies=cook, json={"name": "Ade Stores", "receipt_phones": ""})
    assert client.get(f"/app/api/pos/receipt/{sale['receipt_id']}", cookies=cook).json()["biz_phone"] == phone


@pytest.mark.parametrize("text", ["how do i remove stock", "how to delete a product", "how do i remove damaged goods"])
def test_titi_explains_removing_stock(text):
    from faq import detect_faq
    from messages import build_app_guide_message
    from parser import parse_message
    p = parse_message(text) or {}
    assert (p.get("topic") if p.get("type") == "APP_GUIDE" else detect_faq(text)) == "remove_stock"
    a = build_app_guide_message("remove_stock")
    assert "Remove product" in a and "Removed stock" in a and "(damaged)" in a
