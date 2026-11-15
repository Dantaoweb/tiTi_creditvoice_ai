"""
Offline records carry their own ID (X-Client-Ref, offline_ref.py): the phone
retrying a sale whose reply was lost gets the first answer back, and the sale
is recorded once. Different IDs, users or refused requests aren't affected.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-offline-ref-00000000000000")

from fastapi.testclient import TestClient

from database import SessionLocal
from main import app
from models import InventoryItem, Transaction, User

_seq = iter(range(100, 999))


def _shop():
    c = TestClient(app)
    phone = f"2347121{next(_seq):06d}"
    c.post("/app/api/auth/register", json={"name": "Offline Shop", "phone": phone, "pin": "5678"})
    c.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"})
    db = SessionLocal()
    try:
        it = InventoryItem(owner_phone=phone, name="sugar", unit="bag", selling_price=1000, quantity=50, is_available=True)
        db.add(it); db.commit()
        return c, phone, it.id
    finally:
        db.close()


def _sales(phone):
    db = SessionLocal()
    try:
        uid = db.query(User).filter(User.phone == phone).first().id
        return db.query(Transaction).filter(Transaction.recorded_by_id == uid).count()
    finally:
        db.close()


def _stock(item_id):
    db = SessionLocal()
    try:
        return db.query(InventoryItem).filter(InventoryItem.id == item_id).first().quantity
    finally:
        db.close()


def _sale(c, phone, item_id, ref=None):
    return c.post("/app/api/pos/save", headers={"X-Client-Ref": ref} if ref else {}, json={
        "owner_phone": phone, "payment_amount": 2000,
        "items": [{"inventory_item_id": item_id, "name": "sugar", "qty": 2, "unit_price": 1000}]})


def test_a_retried_sale_is_recorded_once():
    c, phone, item = _shop()
    first = _sale(c, phone, item, "off-sale-0001")
    assert first.status_code == 200
    again = _sale(c, phone, item, "off-sale-0001")
    assert again.status_code == 200 and again.json() == first.json()
    assert again.headers.get("X-Client-Ref-Replayed") == "1"
    assert _sales(phone) == 1 and _stock(item) == 48

    # A different ID is a different sale; no ID behaves as before
    _sale(c, phone, item, "off-sale-0002")
    _sale(c, phone, item)
    assert _sales(phone) == 3 and _stock(item) == 44


def test_ids_are_per_account_and_refusals_can_be_sent_again():
    c1, p1, i1 = _shop()
    c2, p2, i2 = _shop()
    assert _sale(c1, p1, i1, "same-ref-0001").status_code == 200
    assert _sale(c2, p2, i2, "same-ref-0001").status_code == 200       # another account: its own sale
    assert _sales(p1) == 1 and _sales(p2) == 1
    # A refused record isn't remembered: fixed and sent again with the same ID, it goes through
    bad = c1.post("/app/api/pos/save", headers={"X-Client-Ref": "fix-me-00001"},
                  json={"owner_phone": p1, "customer_id": 99999999, "payment_amount": 0,
                        "items": [{"name": "x", "qty": 1, "unit_price": 100}]})
    assert bad.status_code >= 400
    assert _sale(c1, p1, i1, "fix-me-00001").status_code == 200
    assert _sales(p1) == 2


def test_the_app_is_kept_on_the_phone_for_offline():
    from pathlib import Path
    sw = (Path(__file__).parent / "frontend" / "public" / "sw.js").read_text(encoding="utf-8")
    assert '"/app/assets/"' in sw and '"/app/api/"' in sw            # the app's files and its data
    assert 'req.method !== "GET"' in sw                                # writes go through the offline queue
    assert '"cv-clear-api"' in sw                                      # forgotten on logout
    js = (Path(__file__).parent / "frontend" / "src" / "lib" / "useOfflineSync.js").read_text(encoding="utf-8")
    assert "apiPostOnce" in js and "dequeue(item.id);\n          continue;" not in js   # never thrown away on logout
