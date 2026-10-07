"""
Invoices (web).

An invoice is a request to pay, written before money or goods change hands. It
is not a debt and does not move stock until something actually happens:
  - delivered → the goods leave stock (once)
  - paid      → it becomes a sale with a receipt; whatever was not paid
                becomes the customer's debt.

Numbers are system-assigned per business, and continue after the older
invoices that were numbers stamped on credit sales — those keep their numbers
and stay listed, but no new ones are made from a sale.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-invoice-tests-00000000000000")

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import Customer, InventoryItem, InventoryMovement, Invoice, Transaction, User
from invoices import format_invoice_number

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


@pytest.fixture(autouse=True)
def _no_whatsapp(monkeypatch):
    """Nothing in these tests may reach WhatsApp; tests that care read the box."""
    box = []
    import whatsapp_client
    monkeypatch.setattr(whatsapp_client, "send_whatsapp_message",
                        lambda phone, msg: box.append((phone, msg)))
    return box


_phone_seq = iter(range(2777100000, 2777199999))


def _business():
    phone = str(next(_phone_seq))
    client.post("/app/api/auth/register", json={"name": "Biz", "phone": phone, "pin": "5678"})
    cookies = client.post("/app/api/auth/login", json={"phone": phone, "pin": "5678"}).cookies
    db = SessionLocal()
    uid = db.query(User).filter(User.phone == phone).first().id
    db.close()
    return phone, cookies, uid


def _customer(owner_phone, name="Ada", phone=None):
    db = SessionLocal()
    c = Customer(name=name, owner_phone=owner_phone, balance=0, customer_phone=phone)
    db.add(c); db.commit()
    cid = c.id
    db.close()
    return cid


def _stock(owner_phone, name="rice", qty=10, price=1000):
    db = SessionLocal()
    item = InventoryItem(owner_phone=owner_phone, name=name, unit="bag",
                         quantity=qty, selling_price=price)
    db.add(item); db.commit()
    iid = item.id
    db.close()
    return iid


def _qty(item_id):
    db = SessionLocal()
    q = db.query(InventoryItem).filter(InventoryItem.id == item_id).first().quantity
    db.close()
    return q


def _balance(customer_id):
    db = SessionLocal()
    b = db.query(Customer).filter(Customer.id == customer_id).first().balance or 0
    db.close()
    return b


def _new(cookies, customer_id, items, **extra):
    r = client.post("/app/api/invoices/new", cookies=cookies,
                    json={"customer_id": customer_id, "items": items, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _rice(item_id, qty=2, price=1000):
    return {"inventory_item_id": item_id, "name": "rice", "qty": qty, "unit": "bag", "unit_price": price}


# ── Writing an invoice changes nothing real ─────────────────────────────────

def test_format_invoice_number():
    assert format_invoice_number(1) == "INV-0001"
    assert format_invoice_number(482) == "INV-0482"
    assert format_invoice_number(None) is None


def test_an_invoice_is_not_a_debt_and_moves_no_stock():
    phone, cookies, _ = _business()
    cid = _customer(phone)
    iid = _stock(phone, qty=10)

    doc = _new(cookies, cid, [_rice(iid, qty=3)])

    assert doc["ref"] == "INV-0001"
    assert doc["status"] == "draft"
    assert doc["total"] == 3000
    assert _balance(cid) == 0                      # nobody owes anything yet
    assert _qty(iid) == 10                         # nothing has left the shop
    db = SessionLocal()
    try:
        assert db.query(Transaction).filter(Transaction.customer_id == cid).count() == 0
    finally:
        db.close()


def test_an_invoice_needs_a_customer_and_an_item():
    phone, cookies, _ = _business()
    cid = _customer(phone)
    r = client.post("/app/api/invoices/new", cookies=cookies, json={"customer_id": cid, "items": []})
    assert r.status_code == 400
    r = client.post("/app/api/invoices/new", cookies=cookies,
                    json={"items": [{"name": "Repair", "qty": 1, "unit_price": 500}]})
    assert r.status_code == 400


def test_a_new_customer_can_be_typed_in():
    phone, cookies, _ = _business()
    r = client.post("/app/api/invoices/new", cookies=cookies, json={
        "customer_name": "Mama Bola", "customer_phone": "2348000000001",
        "items": [{"name": "Repair", "qty": 1, "unit_price": 500}],
    })
    assert r.status_code == 200, r.text
    assert r.json()["customer"]["name"] == "Mama Bola"


def test_numbers_are_sequential_and_per_business():
    a_phone, a_cookies, _ = _business()
    b_phone, b_cookies, _ = _business()
    a_cust, b_cust = _customer(a_phone), _customer(b_phone)
    item = [{"name": "Repair", "qty": 1, "unit_price": 500}]
    assert _new(a_cookies, a_cust, item)["number"] == 1
    assert _new(a_cookies, a_cust, item)["number"] == 2
    assert _new(b_cookies, b_cust, item)["number"] == 1


def test_numbers_continue_after_the_older_invoices():
    """INV-0003 already exists on a credit sale, so the next invoice is 4."""
    phone, cookies, uid = _business()
    cid = _customer(phone)
    db = SessionLocal()
    db.add(Transaction(customer_id=cid, type="BUY", amount=1000, product="Goods",
                       message_id=f"buy-{uuid.uuid4()}", recorded_by_id=uid, invoice_number=3))
    db.commit(); db.close()
    assert _new(cookies, cid, [{"name": "Repair", "qty": 1, "unit_price": 500}])["number"] == 4


# ── Paying turns it into a sale; the unpaid part becomes debt ───────────────

def test_paid_in_full_is_a_cash_sale_with_no_debt(_no_whatsapp):
    phone, cookies, _ = _business()
    cid = _customer(phone, phone="2348111111111")
    iid = _stock(phone, qty=10)
    doc = _new(cookies, cid, [_rice(iid, qty=2)])

    r = client.post(f"/app/api/invoices/doc/{doc['id']}/pay", cookies=cookies, json={"amount": 2000})
    assert r.status_code == 200, r.text
    paid = r.json()
    assert paid["status"] == "paid"
    assert _balance(cid) == 0

    db = SessionLocal()
    try:
        sale = db.query(Transaction).filter(Transaction.id == paid["transaction_id"]).first()
        assert sale.type == "SALE" and sale.amount == 2000
        assert sale.product == "Invoice INV-0001"
    finally:
        db.close()
    receipt = client.get(f"/app/api/pos/receipt/{paid['transaction_id']}", cookies=cookies)
    assert receipt.status_code == 200
    assert _no_whatsapp and _no_whatsapp[-1][0] == "2348111111111"   # receipt went out


def test_part_payment_moves_the_rest_to_debt():
    phone, cookies, _ = _business()
    cid = _customer(phone)
    due = (datetime.now(timezone.utc) + timedelta(days=7)).replace(tzinfo=None).isoformat()
    doc = _new(cookies, cid, [{"name": "Repair", "qty": 1, "unit_price": 5000}], due_date=due)

    paid = client.post(f"/app/api/invoices/doc/{doc['id']}/pay", cookies=cookies,
                       json={"amount": 2000}).json()
    assert paid["status"] == "part_paid"
    assert paid["amount_paid"] == 2000
    assert paid["moved_to_debt"] == 3000
    assert _balance(cid) == 3000

    db = SessionLocal()
    try:
        sale = db.query(Transaction).filter(Transaction.id == paid["transaction_id"]).first()
        assert sale.type == "BUY" and sale.due_date is not None   # the debt keeps the due date
    finally:
        db.close()
    receipt = client.get(f"/app/api/pos/receipt/{paid['transaction_id']}", cookies=cookies).json()
    assert receipt["paid"] == 2000 and receipt["balance_owed"] == 3000


def test_paying_nothing_puts_it_all_on_debt():
    phone, cookies, _ = _business()
    cid = _customer(phone)
    doc = _new(cookies, cid, [{"name": "Repair", "qty": 1, "unit_price": 5000}])
    paid = client.post(f"/app/api/invoices/doc/{doc['id']}/pay", cookies=cookies,
                       json={"amount": 0}).json()
    assert paid["status"] == "part_paid"
    assert _balance(cid) == 5000


def test_a_fractional_quantity_paid_in_full_leaves_no_debt():
    phone, cookies, _ = _business()
    cid = _customer(phone)
    doc = _new(cookies, cid, [{"name": "Cloth", "qty": 1.5, "unit_price": 333}])
    paid = client.post(f"/app/api/invoices/doc/{doc['id']}/pay", cookies=cookies,
                       json={"amount": doc["total"]}).json()
    assert paid["status"] == "paid"
    assert _balance(cid) == 0


def test_cannot_pay_twice_or_more_than_the_total():
    phone, cookies, _ = _business()
    cid = _customer(phone)
    doc = _new(cookies, cid, [{"name": "Repair", "qty": 1, "unit_price": 5000}])
    url = f"/app/api/invoices/doc/{doc['id']}/pay"
    assert client.post(url, cookies=cookies, json={"amount": 6000}).status_code == 400
    assert client.post(url, cookies=cookies, json={"amount": 5000}).status_code == 200
    assert client.post(url, cookies=cookies, json={"amount": 5000}).status_code == 400
    assert _balance(cid) == 0


def test_voiding_the_sale_puts_the_invoice_back_to_waiting():
    phone, cookies, _ = _business()
    cid = _customer(phone)
    doc = _new(cookies, cid, [{"name": "Repair", "qty": 1, "unit_price": 5000}])
    paid = client.post(f"/app/api/invoices/doc/{doc['id']}/pay", cookies=cookies,
                       json={"amount": 0}).json()
    assert _balance(cid) == 5000

    r = client.post(f"/app/api/transactions/{paid['transaction_id']}/void", cookies=cookies,
                    json={"reason": "Wrong customer"})
    assert r.status_code == 200, r.text
    again = client.get(f"/app/api/invoices/doc/{doc['id']}", cookies=cookies).json()
    assert again["status"] == "draft" and again["transaction_id"] is None
    assert _balance(cid) == 0
    # …and it can be paid properly now.
    assert client.post(f"/app/api/invoices/doc/{doc['id']}/pay", cookies=cookies,
                       json={"amount": 5000}).status_code == 200


# ── Stock leaves when the goods are delivered ───────────────────────────────

def test_delivery_takes_the_goods_out_of_stock_once():
    phone, cookies, _ = _business()
    cid = _customer(phone)
    iid = _stock(phone, qty=10)
    doc = _new(cookies, cid, [_rice(iid, qty=3)])
    url = f"/app/api/invoices/doc/{doc['id']}/deliver"

    r = client.post(url, cookies=cookies)
    assert r.status_code == 200, r.text
    assert r.json()["delivered_at"]
    assert _qty(iid) == 7
    assert _balance(cid) == 0                      # delivered is still not paid

    assert client.post(url, cookies=cookies).status_code == 400
    assert _qty(iid) == 7

    db = SessionLocal()
    try:
        mv = db.query(InventoryMovement).filter(InventoryMovement.item_id == iid).one()
        assert mv.source_type == "INVOICE" and mv.source_id == doc["id"]
    finally:
        db.close()


def test_paying_after_delivery_does_not_take_stock_again():
    phone, cookies, _ = _business()
    cid = _customer(phone)
    iid = _stock(phone, qty=10)
    doc = _new(cookies, cid, [_rice(iid, qty=3)])
    client.post(f"/app/api/invoices/doc/{doc['id']}/deliver", cookies=cookies)
    client.post(f"/app/api/invoices/doc/{doc['id']}/pay", cookies=cookies, json={"amount": 3000})
    assert _qty(iid) == 7


def test_paying_before_delivery_leaves_stock_until_delivered():
    phone, cookies, _ = _business()
    cid = _customer(phone)
    iid = _stock(phone, qty=10)
    doc = _new(cookies, cid, [_rice(iid, qty=3)])
    client.post(f"/app/api/invoices/doc/{doc['id']}/pay", cookies=cookies, json={"amount": 3000})
    assert _qty(iid) == 10
    assert client.post(f"/app/api/invoices/doc/{doc['id']}/deliver", cookies=cookies).status_code == 200
    assert _qty(iid) == 7


# ── Editing and cancelling only while nothing has happened ──────────────────

def test_can_edit_until_something_happens():
    phone, cookies, _ = _business()
    cid = _customer(phone)
    iid = _stock(phone, qty=10)
    doc = _new(cookies, cid, [_rice(iid, qty=1)])
    url = f"/app/api/invoices/doc/{doc['id']}"

    r = client.put(url, cookies=cookies, json={"items": [_rice(iid, qty=4)], "note": "Bring a van"})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 4000 and r.json()["note"] == "Bring a van"

    client.post(f"{url}/deliver", cookies=cookies)
    assert client.put(url, cookies=cookies, json={"items": [_rice(iid, qty=1)]}).status_code == 400


def test_cancel_a_draft_but_not_delivered_goods():
    phone, cookies, _ = _business()
    cid = _customer(phone)
    iid = _stock(phone, qty=10)

    draft = _new(cookies, cid, [_rice(iid)])
    r = client.post(f"/app/api/invoices/doc/{draft['id']}/cancel", cookies=cookies)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert client.post(f"/app/api/invoices/doc/{draft['id']}/pay", cookies=cookies,
                       json={"amount": 0}).status_code == 400
    assert _balance(cid) == 0

    delivered = _new(cookies, cid, [_rice(iid)])
    client.post(f"/app/api/invoices/doc/{delivered['id']}/deliver", cookies=cookies)
    assert client.post(f"/app/api/invoices/doc/{delivered['id']}/cancel", cookies=cookies).status_code == 400


# ── Who can see it ──────────────────────────────────────────────────────────

def test_another_business_cannot_see_or_touch_it():
    a_phone, a_cookies, _ = _business()
    _b_phone, b_cookies, _ = _business()
    doc = _new(a_cookies, _customer(a_phone), [{"name": "Repair", "qty": 1, "unit_price": 500}])
    base = f"/app/api/invoices/doc/{doc['id']}"
    assert client.get(base, cookies=b_cookies).status_code == 404
    assert client.post(f"{base}/pay", cookies=b_cookies, json={"amount": 500}).status_code == 404
    assert client.post(f"{base}/deliver", cookies=b_cookies).status_code == 404
    assert client.get("/app/api/invoices", cookies=b_cookies).json()["invoices"] == []


def test_cannot_invoice_another_business_customer():
    a_phone, _a_cookies, _ = _business()
    _b_phone, b_cookies, _ = _business()
    r = client.post("/app/api/invoices/new", cookies=b_cookies, json={
        "customer_id": _customer(a_phone), "items": [{"name": "Repair", "qty": 1, "unit_price": 500}],
    })
    assert r.status_code == 400


# ── Sending ─────────────────────────────────────────────────────────────────

def test_send_records_when_and_asks_for_payment(_no_whatsapp):
    phone, cookies, _ = _business()
    cid = _customer(phone, phone="2348123456789")
    doc = _new(cookies, cid, [{"name": "Repair", "qty": 1, "unit_price": 5000}])
    r = client.post(f"/app/api/invoices/doc/{doc['id']}/send", cookies=cookies)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "sent" and r.json()["sent_at"]
    to, msg = _no_whatsapp[-1]
    assert to == "2348123456789"
    assert "INVOICE" in msg and "INV-0001" in msg and "Amount due: N5,000" in msg
    assert "Keep this receipt" not in msg


def test_send_without_a_phone_is_refused():
    phone, cookies, _ = _business()
    doc = _new(cookies, _customer(phone), [{"name": "Repair", "qty": 1, "unit_price": 5000}])
    r = client.post(f"/app/api/invoices/doc/{doc['id']}/send", cookies=cookies)
    assert r.status_code == 400 and "phone" in r.json()["detail"].lower()


def test_existing_debt_is_shown_but_not_added_to_the_invoice():
    phone, cookies, uid = _business()
    cid = _customer(phone)
    db = SessionLocal()
    db.add(Transaction(customer_id=cid, type="BUY", amount=1500, product="Old",
                       message_id=f"buy-{uuid.uuid4()}", recorded_by_id=uid))
    db.commit(); db.close()
    doc = _new(cookies, cid, [{"name": "Repair", "qty": 1, "unit_price": 5000}])
    assert doc["total"] == 5000
    assert doc["other_debt"] == 1500 and doc["total_due_now"] == 6500


# ── The list ────────────────────────────────────────────────────────────────

def test_list_status_and_what_is_awaiting_payment():
    phone, cookies, _ = _business()
    cid = _customer(phone)
    past = (datetime.now(timezone.utc) - timedelta(days=2)).replace(tzinfo=None).isoformat()
    item = [{"name": "Repair", "qty": 1, "unit_price": 1000}]
    _new(cookies, cid, item)                                  # open
    _new(cookies, cid, item, due_date=past)                   # overdue
    paid = _new(cookies, cid, item)
    client.post(f"/app/api/invoices/doc/{paid['id']}/pay", cookies=cookies, json={"amount": 1000})

    data = client.get("/app/api/invoices", cookies=cookies).json()
    s = data["summary"]
    assert (s["open"], s["overdue"], s["paid"]) == (1, 1, 1)
    assert s["total_due"] == 2000
    assert [r["invoice_number"] for r in data["invoices"]] == [3, 2, 1]

    overdue = client.get("/app/api/invoices?status=overdue", cookies=cookies).json()["invoices"]
    assert len(overdue) == 1 and overdue[0]["kind"] == "invoice"


# ── The older invoices: numbers stamped on credit sales ─────────────────────

def _old_invoice(owner_phone, uid, cid, number, amount=5000):
    db = SessionLocal()
    tx = Transaction(customer_id=cid, type="BUY", amount=amount, product="Goods",
                     message_id=f"buy-{uuid.uuid4()}", recorded_by_id=uid, invoice_number=number)
    db.add(tx); db.commit()
    tid = tx.id
    db.close()
    return tid


def _pay_old(cid, amount):
    db = SessionLocal()
    db.add(Transaction(customer_id=cid, type="PAY", amount=amount, message_id=f"pay-{uuid.uuid4()}"))
    db.commit(); db.close()


def test_a_sale_can_no_longer_be_turned_into_an_invoice():
    phone, cookies, uid = _business()
    cid = _customer(phone)
    db = SessionLocal()
    tx = Transaction(customer_id=cid, type="BUY", amount=5000, product="Goods",
                     message_id=f"buy-{uuid.uuid4()}", recorded_by_id=uid)
    db.add(tx); db.commit(); tid = tx.id; db.close()

    assert client.post(f"/app/api/invoices/{tid}/issue", cookies=cookies).status_code == 400
    assert client.post(f"/app/api/invoices/{tid}/send", cookies=cookies).status_code == 400
    db = SessionLocal()
    try:
        assert db.query(Transaction).filter(Transaction.id == tid).first().invoice_number is None
    finally:
        db.close()


def test_older_invoices_keep_their_number_and_stay_listed():
    phone, cookies, uid = _business()
    cid = _customer(phone)
    tid = _old_invoice(phone, uid, cid, number=1)

    r = client.post(f"/app/api/invoices/{tid}/issue", cookies=cookies)
    assert r.status_code == 200 and r.json()["invoice_number"] == 1

    rows = client.get("/app/api/invoices", cookies=cookies).json()["invoices"]
    assert len(rows) == 1
    assert rows[0]["kind"] == "sale" and rows[0]["invoice_ref"] == "INV-0001"
    assert rows[0]["status"] == "open" and rows[0]["outstanding"] == 5000


def test_older_invoice_can_still_be_sent(_no_whatsapp):
    phone, cookies, uid = _business()
    cid = _customer(phone, phone="2348123456789")
    tid = _old_invoice(phone, uid, cid, number=1)
    r = client.post(f"/app/api/invoices/{tid}/send", cookies=cookies)
    assert r.status_code == 200, r.text
    assert "INVOICE" in _no_whatsapp[-1][1]


def test_older_invoices_settle_oldest_first():
    phone, cookies, uid = _business()
    cid = _customer(phone)
    t1 = _old_invoice(phone, uid, cid, number=1, amount=4000)
    t2 = _old_invoice(phone, uid, cid, number=2, amount=6000)
    _pay_old(cid, 4000)
    rows = {(r["kind"], r["id"]): r for r in client.get("/app/api/invoices", cookies=cookies).json()["invoices"]}
    assert rows[("sale", t1)]["status"] == "paid"
    assert rows[("sale", t2)]["status"] == "open" and rows[("sale", t2)]["outstanding"] == 6000


def test_older_invoice_text_uses_invoice_wording():
    """An invoice requests payment, so the receipt footer reads wrong on it."""
    from invoices import format_invoice_text
    msg = format_invoice_text({
        "config": {"footer": "Keep this receipt for reference.", "customer_label": "Customer"},
        "customer": {"name": "Ada"},
        "biz_name": "Shop",
        "total": 5000,
        "balance_owed": 5000,
        "invoice_number": 1,
        "items": [],
    })
    assert "Keep this receipt" not in msg
    assert "settle this invoice" in msg.lower()
