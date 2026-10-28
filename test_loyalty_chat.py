"""
Loyalty through tiTi on WhatsApp: a chat sale to a customer with a reward
ready offers "USE REWARD"; replying it saves the sale with the reward taken
off. The customer's receipt shows their stamps.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from models import Customer, LoyaltyEntry, Transaction
from test_whatsapp_pharmacy_flow import make_webhook_flow, onboard_business, set_user_plan


def test_chat_sale_offers_and_uses_reward(monkeypatch):
    phone = "2348000004401"
    SessionTesting, sent, send = make_webhook_flow(monkeypatch, phone, "loyalty")
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda to, m, *a, **k: sent.append((to, m)) or True)
    import transaction_save
    onboard_business(send, "Demo Salon", 4, 1)
    set_user_plan(SessionTesting, phone, "PREMIUM")
    from app_settings import set_business_settings
    db = SessionTesting()
    set_business_settings(db, phone, {"loyalty_mode": "stamps", "loyalty_stamps_needed": 2}); db.commit(); db.close()

    for price in (15000, 16000):                        # different amounts: not a duplicate
        assert send(f"Blessing did braids {price} paid {price}")["status"] == "pending"
        assert send("yes")["status"] == "saved"
    db = SessionTesting()
    c = db.query(Customer).filter(Customer.owner_phone == phone, Customer.name == "blessing").one()
    c.customer_phone = "2348039999999"; db.commit(); cid = c.id; db.close()

    assert send("Blessing did braids 20000 paid 20000")["status"] == "pending"
    assert "USE REWARD" in sent[-1][1] and "free one (2 stamps)" in sent[-1][1]
    assert send("use reward")["status"] == "saved"
    assert any("Loyalty reward: −N20,000" in m for _to, m in sent)

    db = SessionTesting()
    try:
        last = db.query(Transaction).filter(Transaction.customer_id == cid, Transaction.type == "BUY") \
            .order_by(Transaction.id.desc()).first()
        assert last.amount == 0 and last.discount_amount == 20000
        assert db.query(Transaction).filter(Transaction.customer_id == cid, Transaction.type == "PAY",
                                            Transaction.amount == 0).count() == 0
        assert db.query(LoyaltyEntry).filter(LoyaltyEntry.customer_id == cid, LoyaltyEntry.kind == "use").one().stamps == 2
        assert db.query(Customer).get(cid).balance == 0
    finally:
        db.close()
    receipts = [m for to, m in sent if to == "2348039999999"]
    assert receipts and "0 of 2 stamps" in receipts[-1]


def test_select_product_flow_uses_reward(monkeypatch):
    phone = "2348000002201"
    SessionTesting, sent, send = make_webhook_flow(monkeypatch, phone, "loyalty-sp")
    monkeypatch.setattr("whatsapp_client.send_whatsapp_message", lambda to, m, *a, **k: sent.append((to, m)) or True)
    onboard_business(send, "Demo Pharmacy", 2, 1)
    set_user_plan(SessionTesting, phone, "PREMIUM")
    from app_settings import set_business_settings
    from models import InventoryItem
    db = SessionTesting()
    set_business_settings(db, phone, {"loyalty_mode": "stamps", "loyalty_stamps_needed": 2})
    ada = Customer(owner_phone=phone, name="ada", customer_phone="2348038888888", balance=0)
    db.add_all([ada, InventoryItem(owner_phone=phone, name="panadol", unit="pack", selling_price=500,
                                   quantity=20, is_available=True)])
    db.flush()
    for amt in (700, 800):                                   # two paid sales since loyalty began
        db.add(Transaction(customer_id=ada.id, type="SALE", amount=amt, product="x"))
    db.commit(); cid = ada.id; db.close()

    for t in ("sell panadol", "2", "2", "Ada"):              # product, quantity 2, Checkout, customer
        send(t)
    assert "USE REWARD" in sent[-1][1]
    assert send("use reward")["status"] == "select_product_reward_used"
    assert "Loyalty reward: −N500" in sent[-1][1] and "Total: N500" in sent[-1][1]
    send("500")                                              # paid
    send("yes")
    db = SessionTesting()
    try:
        buy = db.query(Transaction).filter(Transaction.customer_id == cid, Transaction.type == "BUY").one()
        assert buy.amount == 500 and buy.discount_amount == 500
        assert db.query(LoyaltyEntry).filter(LoyaltyEntry.customer_id == cid, LoyaltyEntry.kind == "use").one().stamps == 2
    finally:
        db.close()
    receipts = [m for to, m in sent if to == "2348038888888"]
    assert receipts and "stamps" in receipts[-1]
