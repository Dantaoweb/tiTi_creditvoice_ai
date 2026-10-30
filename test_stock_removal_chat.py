"""
On WhatsApp: "remove stock 2 bags rice (spoilage)" records the reason;
"remove item rice" never erases — it asks why, then removes that one product
(hidden, stock accounted for), never every product containing the word.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from models import InventoryItem, InventoryMovement
from test_whatsapp_pharmacy_flow import make_webhook_flow, onboard_business, set_user_plan


def test_chat_removals_are_accounted_for(monkeypatch):
    phone = "2348000005501"
    SessionTesting, sent, send = make_webhook_flow(monkeypatch, phone, "removal")
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda to, m, *a, **k: sent.append((to, m)) or True)
    onboard_business(send, "Demo Pharmacy", 2, 1)
    set_user_plan(SessionTesting, phone, "PREMIUM")
    db = SessionTesting()
    db.add_all([InventoryItem(owner_phone=phone, name="rice", unit="bag", quantity=10, cost_price=60000,
                              selling_price=68000, is_available=True),
                InventoryItem(owner_phone=phone, name="fried rice", unit="plate", quantity=5, cost_price=1500,
                              selling_price=2500, is_available=True)])
    db.commit(); db.close()

    assert send("remove stock 2 bags rice (spoilage)")["status"] == "stock_removed"
    db = SessionTesting()
    mv = db.query(InventoryMovement).filter(InventoryMovement.owner_phone == phone,
                                            InventoryMovement.source_type == "MANUAL").one()
    assert mv.reason == "damaged" and mv.quantity == 2 and mv.unit_price == 60000
    db.close()

    assert send("remove item rice")["status"] == "remove_product_no_reason"
    assert send("remove item rice (expired)")["status"] == "delete_stock_item_done"
    db = SessionTesting()
    try:
        rice = db.query(InventoryItem).filter_by(owner_phone=phone, name="rice").one()        # kept, hidden
        assert rice.removed_at and rice.quantity == 0
        fried = db.query(InventoryItem).filter_by(owner_phone=phone, name="fried rice").one()
        assert fried.removed_at is None and fried.quantity == 5                                   # untouched
    finally:
        db.close()
