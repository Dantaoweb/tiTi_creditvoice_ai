"""
Stock Received (Quick Form) records BOTH a physical stock increase AND a
SupplierPurchase against a supplier (defaulting to "Others"), for new and
existing products.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-stock-received-0000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import User, InventoryItem, Supplier, SupplierPurchase

client = TestClient(app, raise_server_exceptions=True)
_seq = iter(range(9000, 9999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _owner():
    n = next(_seq)
    phone = f"234814{n:06d}"
    client.post("/app/api/auth/register", json={"name": "Owner", "phone": phone, "pin": "5678"})
    return phone, client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies


def _item_qty(phone, name):
    db = SessionLocal()
    try:
        it = db.query(InventoryItem).filter(
            InventoryItem.owner_phone == phone, InventoryItem.name == name.lower()
        ).first()
        return it.quantity if it else None
    finally:
        db.close()


def _supplier_and_purchases(phone, supplier_name):
    db = SessionLocal()
    try:
        sup = db.query(Supplier).filter(
            Supplier.owner_phone == phone, Supplier.name == supplier_name.lower()
        ).first()
        if not sup:
            return None, 0
        n = db.query(SupplierPurchase).filter(SupplierPurchase.supplier_id == sup.id).count()
        return sup, n
    finally:
        db.close()


def test_stock_received_new_product_creates_item_supplier_and_purchase():
    phone, cook = _owner()
    r = client.post("/app/api/inventory/stock-received", cookies=cook, json={
        "product": "Cocoa", "quantity": 50, "cost_per_unit": 1000, "supplier": "Dangote",
    })
    assert r.status_code == 200, r.text
    assert r.json()["new_quantity"] == 50
    assert isinstance(r.json().get("purchase_id"), int)
    assert _item_qty(phone, "cocoa") == 50

    # The purchase is retrievable as a rich supplier receipt.
    rec = client.get(f"/app/api/suppliers/receipt/purchase/{r.json()['purchase_id']}", cookies=cook).json()
    assert rec["kind"] == "purchase" and rec["biz_name"]
    assert rec["supplier"]["name"] == "Dangote" and rec["items"][0]["product"] == "Cocoa"
    # And it shows in the supplier receipts list.
    lst = client.get("/app/api/suppliers/receipts", cookies=cook).json()["receipts"]
    assert any(x["kind"] == "purchase" and x["id"] == r.json()["purchase_id"] for x in lst)
    sup, n = _supplier_and_purchases(phone, "dangote")
    assert sup is not None and n == 1


def test_stock_received_captures_due_date():
    phone, cook = _owner()
    r = client.post("/app/api/inventory/stock-received", cookies=cook, json={
        "product": "Palm Oil", "quantity": 30, "cost_per_unit": 2000,
        "paid_now": 0, "supplier": "Emeka", "due_date": "2026-10-01",
    })
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        sup_id = db.query(Supplier).filter(Supplier.owner_phone == phone, Supplier.name == "emeka").first().id
    finally:
        db.close()
    p = client.get(f"/app/api/suppliers/{sup_id}", cookies=cook).json()["purchases"][0]
    assert p["due_date"][:10] == "2026-10-01"

    # Bad date is rejected.
    bad = client.post("/app/api/inventory/stock-received", cookies=cook, json={
        "product": "Salt", "quantity": 5, "due_date": "not-a-date",
    })
    assert bad.status_code == 400


def test_supplier_list_with_due_date_does_not_500():
    """A purchase with a due date + outstanding balance must not crash the
    My Supply Chain list on the naive/aware datetime comparison."""
    phone, cook = _owner()
    # Overdue credit purchase (past due date, still owing).
    client.post("/app/api/inventory/stock-received", cookies=cook, json={
        "product": "Yam", "quantity": 40, "cost_per_unit": 500,
        "paid_now": 0, "supplier": "Ibrahim", "due_date": "2020-01-01",
    })
    r = client.get("/app/api/suppliers", cookies=cook)
    assert r.status_code == 200, r.text
    sup = next(s for s in r.json()["suppliers"] if s["name"] == "ibrahim")
    assert sup["has_overdue"] is True and sup["balance"] == 20000


def test_stock_received_existing_product_adds_quantity():
    phone, cook = _owner()
    # Create an existing priced product with opening stock 10.
    client.post("/app/api/inventory", cookies=cook, json={
        "owner_phone": phone, "name": "Rice", "quantity": 10, "selling_price": 5000,
    })
    db = SessionLocal()
    try:
        item_id = db.query(InventoryItem).filter(
            InventoryItem.owner_phone == phone, InventoryItem.name == "rice"
        ).first().id
    finally:
        db.close()

    r = client.post("/app/api/inventory/stock-received", cookies=cook, json={
        "item_id": item_id, "quantity": 15, "cost_per_unit": 4000, "supplier": "Ayo",
    })
    assert r.status_code == 200, r.text
    assert _item_qty(phone, "rice") == 25  # 10 + 15
    sup, n = _supplier_and_purchases(phone, "ayo")
    assert sup is not None and n == 1


def test_stock_received_defaults_supplier_to_others():
    phone, cook = _owner()
    r = client.post("/app/api/inventory/stock-received", cookies=cook, json={
        "product": "Beans", "quantity": 20,
    })
    assert r.status_code == 200, r.text
    assert r.json()["supplier"] == "Others"
    assert _item_qty(phone, "beans") == 20
    sup, n = _supplier_and_purchases(phone, "others")
    assert sup is not None and n == 1


def test_stock_received_rejects_zero_quantity():
    _p, cook = _owner()
    r = client.post("/app/api/inventory/stock-received", cookies=cook, json={
        "product": "Milk", "quantity": 0,
    })
    assert r.status_code == 400


def test_credit_purchase_then_pay_supplier_clears_balance():
    phone, cook = _owner()
    # Receive on credit: total 100000, paid 40000 → owe 60000.
    r = client.post("/app/api/inventory/stock-received", cookies=cook, json={
        "product": "Cement", "quantity": 100, "cost_per_unit": 1000,
        "paid_now": 40000, "supplier": "BUA",
    })
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        sup_id = db.query(Supplier).filter(
            Supplier.owner_phone == phone, Supplier.name == "bua"
        ).first().id
    finally:
        db.close()

    # Detail shows the debt.
    d = client.get(f"/app/api/suppliers/{sup_id}", cookies=cook).json()
    assert d["total_bought"] == 100000 and d["total_paid"] == 40000 and d["balance"] == 60000
    assert len(d["purchases"]) == 1

    # Pay the rest.
    pr = client.post(f"/app/api/suppliers/{sup_id}/pay", cookies=cook, json={"amount": 60000})
    assert pr.status_code == 200 and pr.json()["balance"] == 0, pr.text
    assert isinstance(pr.json().get("payment_id"), int)
    # The payment is retrievable as a rich supplier receipt.
    rec = client.get(f"/app/api/suppliers/receipt/payment/{pr.json()['payment_id']}", cookies=cook).json()
    assert rec["kind"] == "payment" and rec["amount"] == 60000 and rec["biz_name"]

    d2 = client.get(f"/app/api/suppliers/{sup_id}", cookies=cook).json()
    assert d2["balance"] == 0 and len(d2["payments"]) == 1


def test_add_supplier_manually_and_reject_duplicate():
    phone, cook = _owner()
    r = client.post("/app/api/suppliers", cookies=cook, json={"name": "GTB Distributors"})
    assert r.status_code == 200 and r.json()["name"] == "Gtb Distributors", r.text
    # It shows in the list with a zero balance.
    names = [s["name"] for s in client.get("/app/api/suppliers", cookies=cook).json()["suppliers"]]
    assert "gtb distributors" in names
    # Duplicate (case-insensitive) is rejected.
    dup = client.post("/app/api/suppliers", cookies=cook, json={"name": "gtb distributors"})
    assert dup.status_code == 409


def test_add_supplier_with_phone_and_edit():
    _p, cook = _owner()
    r = client.post("/app/api/suppliers", cookies=cook, json={"name": "Musa Hausa", "phone": "08030000001"})
    assert r.status_code == 200 and r.json()["phone"] == "08030000001", r.text
    sid = r.json()["id"]
    assert client.get(f"/app/api/suppliers/{sid}", cookies=cook).json()["phone"] == "08030000001"

    # Edit name + phone.
    e = client.put(f"/app/api/suppliers/{sid}", cookies=cook, json={"name": "Musa Trading", "phone": "08030000002"})
    assert e.status_code == 200 and e.json()["phone"] == "08030000002", e.text
    d2 = client.get(f"/app/api/suppliers/{sid}", cookies=cook).json()
    assert d2["name"] == "musa trading" and d2["phone"] == "08030000002"

    # Renaming onto another existing supplier is rejected.
    client.post("/app/api/suppliers", cookies=cook, json={"name": "Existing Co"})
    clash = client.put(f"/app/api/suppliers/{sid}", cookies=cook, json={"name": "Existing Co"})
    assert clash.status_code == 409


def test_edit_purchase_due_date():
    phone, cook = _owner()
    client.post("/app/api/inventory/stock-received", cookies=cook, json={
        "product": "Blocks", "quantity": 200, "cost_per_unit": 500, "paid_now": 0, "supplier": "Lafarge",
    })
    db = SessionLocal()
    try:
        sup_id = db.query(Supplier).filter(Supplier.owner_phone == phone, Supplier.name == "lafarge").first().id
    finally:
        db.close()
    pid = client.get(f"/app/api/suppliers/{sup_id}", cookies=cook).json()["purchases"][0]["id"]

    r = client.put(f"/app/api/suppliers/purchases/{pid}/due-date", cookies=cook, json={"due_date": "2026-09-15"})
    assert r.status_code == 200 and r.json()["due_date"][:10] == "2026-09-15", r.text

    # Clear it.
    r2 = client.put(f"/app/api/suppliers/purchases/{pid}/due-date", cookies=cook, json={"due_date": None})
    assert r2.status_code == 200 and r2.json()["due_date"] is None


def test_stock_note_becomes_a_business_note():
    phone, cook = _owner()
    client.post("/app/api/inventory/stock-received", cookies=cook, json={
        "product": "Sugar", "quantity": 8, "supplier": "Ade", "note": "Batch B12, half broken",
    })
    from models import BusinessNote
    db = SessionLocal()
    try:
        n = db.query(BusinessNote).filter(
            BusinessNote.owner_phone == phone, BusinessNote.category == "delivery"
        ).first()
        assert n is not None and "Batch B12" in n.body
    finally:
        db.close()
    # It shows in the Notes menu under the delivery category.
    notes = client.get("/app/api/notes?category=delivery", cookies=cook).json()["notes"]
    assert any("Batch B12" in x["body"] for x in notes)


def test_incoming_delivery_appears_in_deliveries():
    _p, cook = _owner()
    client.post("/app/api/inventory/stock-received", cookies=cook, json={
        "product": "Flour", "quantity": 20, "cost_per_unit": 1500, "paid_now": 0,
        "supplier": "Honeywell", "due_date": "2026-11-20",
    })
    inc = client.get("/app/api/deliveries", cookies=cook).json().get("incoming", [])
    assert any(x["supplier"] == "Honeywell" and x["balance"] == 30000 for x in inc), inc


def test_edit_purchase_quantity_and_cost_syncs_stock():
    phone, cook = _owner()
    # Receive 10 @ 1000 = 10000, unpaid.
    client.post("/app/api/inventory/stock-received", cookies=cook, json={
        "product": "Yam", "quantity": 10, "cost_per_unit": 1000, "paid_now": 0, "supplier": "Ibro",
    })
    assert _item_qty(phone, "yam") == 10
    db = SessionLocal()
    try:
        sup_id = db.query(Supplier).filter(Supplier.owner_phone == phone, Supplier.name == "ibro").first().id
    finally:
        db.close()
    pid = client.get(f"/app/api/suppliers/{sup_id}", cookies=cook).json()["purchases"][0]["id"]

    # Correct to 15 @ 1200 = 18000; physical stock rises by +5 (10 → 15).
    r = client.put(f"/app/api/suppliers/purchases/{pid}", cookies=cook, json={"quantity": 15, "unit_price": 1200})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 18000 and r.json()["balance"] == 18000
    assert _item_qty(phone, "yam") == 15

    d = client.get(f"/app/api/suppliers/{sup_id}", cookies=cook).json()
    assert d["total_bought"] == 18000 and d["purchases"][0]["quantity"] == 15

    # Zero/negative quantity is rejected.
    bad = client.put(f"/app/api/suppliers/purchases/{pid}", cookies=cook, json={"quantity": 0})
    assert bad.status_code == 400


def test_edit_purchase_rejects_other_owner():
    _p, cook = _owner()
    _p2, cook2 = _owner()
    client.post("/app/api/inventory/stock-received", cookies=cook2, json={
        "product": "Gari", "quantity": 4, "supplier": "Theirs",
    })
    db = SessionLocal()
    try:
        pid = db.query(SupplierPurchase).join(Supplier).filter(Supplier.name == "theirs").first().id
    finally:
        db.close()
    r = client.put(f"/app/api/suppliers/purchases/{pid}", cookies=cook, json={"quantity": 2})
    assert r.status_code == 404


def test_record_purchase_from_supplier_modal_grows_stock():
    """Supplier-first purchase: records against the supplier AND grows physical
    stock, mirroring Quick Record → Stock Received."""
    phone, cook = _owner()
    # Create the supplier first (manually), then buy from within its card.
    sid = client.post("/app/api/suppliers", cookies=cook, json={"name": "Emeka Farms"}).json()["id"]

    r = client.post(f"/app/api/suppliers/{sid}/purchase", cookies=cook, json={
        "product": "Cocoa", "quantity": 100, "cost_per_unit": 800,
        "paid_now": 20000, "due_date": "2026-12-01", "note": "Truck A",
    })
    assert r.status_code == 200, r.text
    assert r.json()["new_quantity"] == 100
    assert r.json()["balance"] == 60000   # 80000 total - 20000 paid

    # Physical stock was created + grown.
    assert _item_qty(phone, "cocoa") == 100

    # A second buy from the same supplier aggregates onto the same item.
    r2 = client.post(f"/app/api/suppliers/{sid}/purchase", cookies=cook, json={
        "product": "Cocoa", "quantity": 50, "cost_per_unit": 800,
    })
    assert r2.status_code == 200, r2.text
    assert _item_qty(phone, "cocoa") == 150

    # Detail shows both purchases, the due date, and the delivery note went to Notes.
    d = client.get(f"/app/api/suppliers/{sid}", cookies=cook).json()
    assert len(d["purchases"]) == 2
    assert any(p["due_date"] and p["due_date"][:10] == "2026-12-01" for p in d["purchases"])
    notes = client.get("/app/api/notes?category=delivery", cookies=cook).json()["notes"]
    assert any("Truck A" in n["body"] for n in notes)


def test_supplier_detail_date_range_window():
    """?from&to scopes rows + totals to the period; opening/closing balance
    account for what was carried in; balance stays the current all-time owed."""
    from datetime import datetime
    from models import SupplierPurchase
    phone, cook = _owner()
    sid = client.post("/app/api/suppliers", cookies=cook, json={"name": "Seasonal"}).json()["id"]

    # Two purchases in different months, both unpaid (owing).
    client.post(f"/app/api/suppliers/{sid}/purchase", cookies=cook, json={
        "product": "Grain", "quantity": 10, "cost_per_unit": 1000, "paid_now": 0})
    client.post(f"/app/api/suppliers/{sid}/purchase", cookies=cook, json={
        "product": "Grain", "quantity": 5, "cost_per_unit": 1000, "paid_now": 0})
    # Backdate the first purchase into January.
    db = SessionLocal()
    try:
        first = db.query(SupplierPurchase).filter(SupplierPurchase.owner_phone == phone).order_by(
            SupplierPurchase.id.asc()).first()
        first.created_at = datetime(2026, 1, 15)
        db.commit()
    finally:
        db.close()

    # Window over February onward: only the second purchase shows; opening
    # balance carries the January debt (10000); closing = 10000 + 5000.
    d = client.get(f"/app/api/suppliers/{sid}?from=2026-02-01&to=2099-01-01", cookies=cook).json()
    assert len(d["purchases"]) == 1 and d["total_bought"] == 5000
    assert d["opening_balance"] == 10000 and d["closing_balance"] == 15000
    assert d["balance"] == 15000               # current all-time owed
    assert d["range"]["from"] == "2026-02-01"

    # No range → all-time, no opening carry.
    allt = client.get(f"/app/api/suppliers/{sid}", cookies=cook).json()
    assert len(allt["purchases"]) == 2 and allt["total_bought"] == 15000 and allt["range"] is None


def test_supplier_statement_pdf_downloads():
    phone, cook = _owner()
    sid = client.post("/app/api/suppliers", cookies=cook, json={"name": "Emeka Farms", "phone": "0803"}).json()["id"]
    client.post(f"/app/api/suppliers/{sid}/purchase", cookies=cook, json={
        "product": "Cocoa", "quantity": 40, "cost_per_unit": 1000, "paid_now": 10000})
    client.post(f"/app/api/suppliers/{sid}/pay", cookies=cook, json={"amount": 5000})

    r = client.get(f"/app/api/suppliers/{sid}/statement", cookies=cook)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content[:4] == b"%PDF" and len(r.content) > 800
    assert "statement_emeka_farms.pdf" in r.headers.get("content-disposition", "")

    # A ranged statement also renders.
    r2 = client.get(f"/app/api/suppliers/{sid}/statement?from=2026-01-01&to=2099-01-01", cookies=cook)
    assert r2.status_code == 200 and r2.content[:4] == b"%PDF"

    # Not this owner's supplier.
    _p2, cook2 = _owner()
    assert client.get(f"/app/api/suppliers/{sid}/statement", cookies=cook2).status_code == 404


def test_record_purchase_rejects_other_owners_supplier():
    _p, cook = _owner()
    _p2, cook2 = _owner()
    foreign = client.post("/app/api/suppliers", cookies=cook2, json={"name": "Foreign Co"}).json()["id"]
    r = client.post(f"/app/api/suppliers/{foreign}/purchase", cookies=cook, json={
        "product": "Rice", "quantity": 5,
    })
    assert r.status_code == 404


def test_pay_rejects_other_owners_supplier():
    _p, cook = _owner()
    # A supplier that belongs to a different owner.
    _p2, cook2 = _owner()
    client.post("/app/api/inventory/stock-received", cookies=cook2, json={
        "product": "Sand", "quantity": 5, "supplier": "Foreign",
    })
    db = SessionLocal()
    try:
        foreign_id = db.query(Supplier).filter(Supplier.name == "foreign").first().id
    finally:
        db.close()
    r = client.post(f"/app/api/suppliers/{foreign_id}/pay", cookies=cook, json={"amount": 1000})
    assert r.status_code == 404
