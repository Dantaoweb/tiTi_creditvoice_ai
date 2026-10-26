"""
Purchase orders: write and send an order to a supplier (no money, no stock),
receive what arrives against it (stock + supplier purchase, like stock
received), and close it keeping any shortfall on record.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-purchase-orders-00000000")

import pytest
from fastapi.testclient import TestClient

import web_auth
from database import SessionLocal
from main import app
from models import InventoryItem, StockBatch, Supplier, SupplierPurchase, User

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(100, 999))
sent = []


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    sent.clear()
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message",
                        lambda to, m, *a, **k: sent.append((to, m)) or True)
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield


def _shop():
    n = next(_seq)
    phone, staff_phone = f"2348104{n:06d}", f"2348105{n:06d}"
    client.post("/app/api/auth/register", json={"name": "Bello Stores", "phone": phone, "pin": "5678"})
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.phone == phone).first()
        owner.subscription_plan = "PRO"; owner.subscription_status = "ACTIVE"
        db.add(User(phone=staff_phone, name="Sule", role="delegate", parent_id=owner.id,
                    can_view_all_transactions=False, recovery_pin_hash=web_auth._hash_pin("1234"),
                    subscription_status="ACTIVE"))
        cement = InventoryItem(owner_phone=phone, name="cement", unit="bag", quantity=3, low_stock_alert=10,
                               cost_price=8000, selling_price=9000, is_available=True, usual_supplier="dangote")
        sup = Supplier(owner_phone=phone, name="dangote", phone="2348039999999")
        db.add_all([cement, sup]); db.commit()
        ids = cement.id, sup.id
    finally:
        db.close()
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    staff = client.post("/app/api/auth/login", json={"phone": staff_phone, "pin": "1234"}).cookies
    return phone, cook, staff, *ids


def _qty(item_id):
    db = SessionLocal()
    try:
        return db.query(InventoryItem).get(item_id).quantity
    finally:
        db.close()


def _po(cook, cement, sup, qty=100):
    return client.post("/app/api/purchase-orders", cookies=cook, json={
        "supplier_id": sup, "expected_date": "2026-11-05", "note": "Deliver to the back gate",
        "lines": [{"inventory_item_id": cement, "quantity": qty, "unit_cost": 8000},
                  {"product": "iron rod", "unit": "piece", "quantity": 50, "unit_cost": 6000}]})


def test_order_send_receive_in_parts_then_close():
    phone, cook, _s, cement, sup = _shop()
    r = _po(cook, cement, sup)
    assert r.status_code == 200, r.text
    po = r.json()
    assert po["number"] == "PO-0001" and po["status"] == "draft" and po["total"] == 1100000
    assert _qty(cement) == 3                                       # an order moves no stock

    s = client.post(f"/app/api/purchase-orders/{po['id']}/send", cookies=cook).json()
    assert s["status"] == "sent" and s["sent"] and sent[0][0] == "2348039999999"
    assert "PURCHASE ORDER PO-0001" in sent[0][1] and "Cement: 100 bag @ N8,000 = N800,000" in sent[0][1]

    cem_line, rod_line = po["lines"][0]["id"], po["lines"][1]["id"]
    rec = client.post(f"/app/api/purchase-orders/{po['id']}/receive", cookies=cook, json={
        "lines": [{"line_id": cem_line, "quantity": 80, "expiry_date": "2027-06", "batch_no": "DC-77"}],
        "paid_now": 400000, "due_date": "2026-11-30"}).json()
    assert rec["status"] == "part_received" and rec["still_expected"] == 70
    assert _qty(cement) == 83
    db = SessionLocal()
    try:
        p = db.query(SupplierPurchase).filter(SupplierPurchase.owner_phone == phone).one()
        assert (p.quantity, p.total, p.paid_amount) == (80, 640000, 400000)      # 240,000 owed
        b = db.query(StockBatch).filter(StockBatch.item_id == cement).order_by(StockBatch.id.desc()).first()
        assert b.batch_no == "DC-77" and b.expiry_date.year == 2027
    finally:
        db.close()

    # Can't receive more than ordered
    r = client.post(f"/app/api/purchase-orders/{po['id']}/receive", cookies=cook, json={
        "lines": [{"line_id": cem_line, "quantity": 21}]})
    assert r.status_code == 400 and "Only 20" in r.json()["detail"]

    closed = client.post(f"/app/api/purchase-orders/{po['id']}/close", cookies=cook,
                         json={"reason": "Supplier ran out"}).json()
    assert closed["status"] == "closed"
    shorts = {l["product"]: l["short"] for l in closed["lines"]}
    assert shorts == {"Cement": 20, "Iron Rod": 50}                # what never came stays on record


def test_full_delivery_marks_it_received_and_creates_new_products():
    _p, cook, _s, cement, sup = _shop()
    po = _po(cook, cement, sup, qty=10).json()
    rec = client.post(f"/app/api/purchase-orders/{po['id']}/receive", cookies=cook, json={
        "lines": [{"line_id": l["id"], "quantity": l["quantity"]} for l in po["lines"]]}).json()
    assert rec["status"] == "received" and rec["still_expected"] == 0
    db = SessionLocal()
    try:
        rod = db.query(InventoryItem).filter(InventoryItem.owner_phone == _p, InventoryItem.name == "iron rod").one()
        assert rod.quantity == 50 and rod.usual_supplier == "dangote"
    finally:
        db.close()


def test_cancel_edit_and_who_can():
    _p, cook, staff, cement, sup = _shop()
    po = _po(cook, cement, sup).json()
    assert client.get("/app/api/purchase-orders", cookies=staff).status_code == 403
    edited = client.put(f"/app/api/purchase-orders/{po['id']}", cookies=cook, json={
        "supplier_id": sup, "lines": [{"inventory_item_id": cement, "quantity": 30, "unit_cost": 8000}]}).json()
    assert edited["total"] == 240000
    assert client.post(f"/app/api/purchase-orders/{po['id']}/close", cookies=cook, json={}).status_code == 400
    assert client.post(f"/app/api/purchase-orders/{po['id']}/cancel", cookies=cook).json()["status"] == "cancelled"
    assert client.post(f"/app/api/purchase-orders", cookies=cook, json={"supplier_id": sup, "lines": []}).status_code == 400


def test_low_stock_suggestions_by_supplier():
    _p, cook, _s, cement, _sup = _shop()
    groups = client.get("/app/api/purchase-orders/suggestions", cookies=cook).json()["groups"]
    assert groups == [{"supplier": "Dangote", "items": [{
        "inventory_item_id": cement, "product": "Cement", "unit": "bag", "in_stock": 3, "alert_at": 10,
        "unit_cost": 8000, "suggest": 17}]}]


@pytest.mark.parametrize("text", [
    "how do I make a purchase order?", "how can I order stock from my supplier?", "how to reorder goods",
])
def test_titi_explains_purchase_orders(text):
    from faq import detect_faq
    from messages import build_app_guide_message
    from parser import parse_message
    p = parse_message(text) or {}
    assert (p["topic"] if p.get("type") == "APP_GUIDE" else detect_faq(text)) == "purchase_order"
    a = build_app_guide_message("purchase_order")
    assert "Goods arrived" in a and "PO-0001" in a and "still expected" in a
