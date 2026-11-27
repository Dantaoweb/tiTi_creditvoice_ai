"""
What an ordinary staff member may do — the owner's tick-boxes on Staff
(staff_access.STAFF_RULES). Everything allowed by default; unticked → refused.
"""
import json

from test_pos_branch_scope import client, _premium_owner, _stock, _reset, _seq  # noqa: F401
from test_whatsapp_part_delivery import shop  # noqa: F401
import web_auth
from database import SessionLocal
from models import User, InventoryItem


def _staff(owner_phone, blocked=None):
    db = SessionLocal()
    owner = db.query(User).filter(User.phone == owner_phone).first()
    sp = f"234881{next(_seq):06d}1"[:13]
    u = User(phone=sp, name="Sade", role="delegate", parent_id=owner.id, can_view_all_transactions=False,
             recovery_pin_hash=web_auth._hash_pin("1234"), subscription_status="ACTIVE",
             staff_blocked=json.dumps(blocked) if blocked is not None else None)
    db.add(u); db.commit(); uid = u.id; db.close()
    return uid, client.post("/app/api/auth/login", json={"phone": sp, "pin": "1234"}).cookies


def _sale(cook, phone, item_id, price, qty=1, paid=None, discount=0, customer=None):
    body = {"owner_phone": phone, "items": [{"inventory_item_id": item_id, "name": "rice", "quantity": qty,
                                             "qty": qty, "unit_price": price}],
            "payment_amount": price * qty - discount if paid is None else paid, "discount": discount}
    if customer:
        body["customer_name"] = customer
    return client.post("/app/api/pos/save", cookies=cook, json=body)


def test_default_everything_allowed():
    phone, owner = _premium_owner()
    rice = _stock(phone, "rice", None)                    # selling price 1000
    _uid, staff = _staff(phone)
    assert _sale(staff, phone, rice, 1000, discount=100).status_code == 200
    assert _sale(staff, phone, rice, 800).status_code == 200
    assert _sale(staff, phone, rice, 1000, paid=0, customer="ade").status_code == 200


def test_owner_unticks_and_the_till_refuses():
    phone, owner = _premium_owner()
    rice = _stock(phone, "rice", None)
    uid, staff = _staff(phone)
    r = client.put(f"/app/api/staff/{uid}/blocked", cookies=owner,
                   json={"blocked": ["discount", "below_price", "credit", "void", "customers_edit", "see_stock"]})
    assert r.status_code == 200 and len(r.json()["blocked"]) == 6
    assert client.put(f"/app/api/staff/{uid}/blocked", cookies=staff, json={"blocked": []}).status_code == 403
    me = [m for m in client.get("/app/api/staff/members", cookies=owner).json()["members"] if m["id"] == uid][0]
    assert "credit" in me["blocked"]

    assert "Discounts are switched off" in _sale(staff, phone, rice, 1000, discount=100).json()["detail"]
    assert "below the set price" in _sale(staff, phone, rice, 800).json()["detail"]
    assert "on credit is switched off" in _sale(staff, phone, rice, 1000, paid=500, customer="ade").json()["detail"]
    ok = _sale(staff, phone, rice, 1000)                  # full price, paid in full: fine
    assert ok.status_code == 200, ok.text
    assert _sale(owner, phone, rice, 800, paid=0, customer="ade").status_code == 200   # the owner is never limited

    tx = ok.json()["receipt_id"]
    assert "Voiding sales is switched off" in client.post(f"/app/api/transactions/{tx}/void", cookies=staff,
                                                           json={"reason": "x"}).json()["detail"]
    assert client.post("/app/api/customers", cookies=staff,
                       json={"owner_phone": phone, "name": "Bola"}).status_code == 403
    inv = client.get("/app/api/inventory", cookies=staff).json()["items"]
    assert inv and all(i["quantity"] is None and i["qty_hidden"] for i in inv)
    assert client.get(f"/app/api/inventory/{rice}/movements", cookies=staff).json()["movements"] == []
    assert client.get("/app/api/inventory", cookies=owner).json()["items"][0]["quantity"] is not None


def test_wholesale_price_is_not_below_the_set_price():
    phone, owner = _premium_owner()
    rice = _stock(phone, "rice", None)
    db = SessionLocal()
    it = db.get(InventoryItem, rice); it.wholesale_price = 900; it.wholesale_min_qty = 5; db.commit(); db.close()
    uid, staff = _staff(phone, ["below_price"])
    assert _sale(staff, phone, rice, 900, qty=5).status_code == 200      # wholesale at its quantity: allowed
    assert _sale(staff, phone, rice, 900, qty=2).status_code == 403      # under the quantity: below the price


def test_whatsapp_stock_question_refused_for_staff():
    from query_handler import handle_natural_language_query
    phone, owner = _premium_owner()
    _stock(phone, "rice", None)
    uid, _ = _staff(phone, ["see_stock"])
    db = SessionLocal()
    try:
        assert "Stock levels are for the owner" in handle_natural_language_query(db, phone, "how many rice is left", uid)
    finally:
        db.close()


def test_whatsapp_staff_refused_and_allowed(shop):   # noqa: F811
    """A staff member's own WhatsApp: credit, below price and stock refused; a
    full-price paid sale still goes through."""
    import webhook_message_flow
    from test_whatsapp_pharmacy_flow import make_whatsapp_text_body
    Session, say, phone = shop
    db = Session()
    owner = db.query(User).filter(User.phone == phone).one()
    sp = f"234882{next(_seq):06d}1"[:13]
    db.add(User(phone=sp, name="Sade", role="delegate", parent_id=owner.id, can_view_all_transactions=False,
                subscription_status="ACTIVE", whatsapp_linked=True,
                staff_blocked=json.dumps(["credit", "below_price", "see_stock"])))
    db.commit(); db.close()
    n = iter(range(1, 99))

    def staff_says(text):
        return webhook_message_flow.handle_webhook_body(make_whatsapp_text_body(sp, text, f"wamid.staff.{next(n)}"))

    assert staff_says("ade bought cement 5000")["status"] == "blocked_for_staff"            # on credit
    assert staff_says("ade bought cement 3000 paid 3000")["status"] == "blocked_for_staff"  # below the set price
    assert staff_says("stock")["status"] in ("stock_hidden_for_staff", "query_handled")     # refusal text: test above
    res = staff_says("ade bought cement 5000 paid 5000")
    assert res.get("status") not in ("blocked_for_staff",), res
