"""
Stock transfers between branches: arrives at once by default; with the Branches
page setting on, the receiving branch confirms and a shortfall is recorded as
missing on the way. Cost travels with the goods; an admin kept to a branch only
sends from it and receives into it.
"""
from test_pos_branch_scope import client, _premium_owner, _two_branches, _reset, _seq  # noqa: F401
import web_auth
from database import SessionLocal
from models import User, InventoryItem, InventoryMovement


def _item(phone, name, branch_id, qty, cost=None):
    db = SessionLocal()
    try:
        it = InventoryItem(owner_phone=phone, name=name, unit="bag", selling_price=60000, cost_price=cost,
                           quantity=qty, is_available=True, branch_id=branch_id, barcode=f"200{next(_seq):010d}")
        db.add(it); db.commit(); db.refresh(it)
        return it.id
    finally:
        db.close()


def _stock(phone, name, branch_id):
    db = SessionLocal()
    try:
        it = db.query(InventoryItem).filter_by(owner_phone=phone, name=name, branch_id=branch_id).first()
        return (it.quantity, it.cost_price, it.barcode) if it else None
    finally:
        db.close()


def _send(cook, a, b, item_id, qty, **extra):
    return client.post("/app/api/transfers", cookies=cook, json={
        "from_branch_id": a, "to_branch_id": b, "lines": [{"item_id": item_id, "quantity": qty}], **extra})


def test_arrives_at_once_and_makes_the_product_there():
    phone, cook = _premium_owner()
    ikeja, lekki = _two_branches(cook)
    rice = _item(phone, "rice", ikeja, 50, cost=50000)
    r = _send(cook, ikeja, lekki, rice, 20, carried_by="Musa")
    assert r.status_code == 200, r.text
    tr = r.json()
    assert tr["number"] == "TR-0001" and tr["status"] == "received"
    assert _stock(phone, "rice", ikeja)[0] == 30
    qty, cost, code = _stock(phone, "rice", lekki)
    assert (qty, cost) == (20, 50000) and code == _stock(phone, "rice", ikeja)[2]   # same barcode, own branch
    doc = client.get(f"/app/api/transfers/{tr['id']}", cookies=cook).json()
    assert doc["from_branch"] == "Ikeja" and doc["to_branch"] == "Lekki" and doc["carried_by"] == "Musa"
    assert doc["lines"][0]["sent"] == 20 and "price" not in str(doc["lines"]).lower()
    db = SessionLocal()
    notes = [m.note for m in db.query(InventoryMovement).filter_by(owner_phone=phone).all()]
    db.close()
    assert "Sent to Lekki · TR-0001" in notes and "Came from Ikeja · TR-0001" in notes
    # Lekki's copy can be edited (its barcode is not "already on" Ikeja's rice)
    lekki_id = client.get("/app/api/inventory", cookies=cook, params={"branch_id": lekki}).json()["items"][0]["id"]
    assert client.put(f"/app/api/inventory/{lekki_id}", cookies=cook,
                      json={"barcode": _stock(phone, "rice", lekki)[2], "selling_price": 61000}).status_code == 200


def test_cost_averages_into_what_the_branch_has():
    phone, cook = _premium_owner()
    ikeja, lekki = _two_branches(cook)
    rice = _item(phone, "rice", ikeja, 10, cost=60000)
    _item(phone, "rice", lekki, 10, cost=40000)
    assert _send(cook, ikeja, lekki, rice, 10).status_code == 200
    assert _stock(phone, "rice", lekki)[:2] == (20, 50000)


def test_cannot_send_more_than_there_is_or_to_the_same_branch():
    phone, cook = _premium_owner()
    ikeja, lekki = _two_branches(cook)
    rice = _item(phone, "rice", ikeja, 5)
    assert "only 5" in _send(cook, ikeja, lekki, rice, 6).json()["detail"]
    assert _send(cook, ikeja, ikeja, rice, 1).status_code == 400
    assert _send(cook, lekki, ikeja, rice, 1).status_code == 400          # not in Lekki's stock
    assert _stock(phone, "rice", ikeja)[0] == 5


def test_receiving_branch_confirms_and_shortfall_is_missing():
    phone, cook = _premium_owner()
    ikeja, lekki = _two_branches(cook)
    assert client.put("/app/api/settings/business", cookies=cook,
                      json={"values": {"transfer_confirm": True}}).status_code == 200
    rice = _item(phone, "rice", ikeja, 50, cost=50000)
    tr = _send(cook, ikeja, lekki, rice, 20).json()
    assert tr["status"] == "on_the_way"
    assert _stock(phone, "rice", ikeja)[0] == 30 and _stock(phone, "rice", lekki)[0] == 0
    lst = client.get("/app/api/transfers", cookies=cook).json()
    assert lst["to_receive"] == 1 and lst["confirm"] is True
    doc = client.get(f"/app/api/transfers/{tr['id']}", cookies=cook).json()
    line = doc["lines"][0]["id"]
    done = client.post(f"/app/api/transfers/{tr['id']}/receive", cookies=cook,
                       json={"received": {str(line): 18}, "note": "2 bags torn"}).json()
    assert done["status"] == "received" and done["lines"][0]["received"] == 18 and done["short"] is True
    assert _stock(phone, "rice", lekki)[0] == 18
    removed = client.get("/app/api/inventory/removed", cookies=cook).json()
    assert "Missing on the way" in str(removed)
    assert client.post(f"/app/api/transfers/{tr['id']}/receive", cookies=cook, json={}).status_code == 400


def test_cancel_while_on_the_way_brings_goods_back():
    phone, cook = _premium_owner()
    ikeja, lekki = _two_branches(cook)
    client.put("/app/api/settings/business", cookies=cook, json={"values": {"transfer_confirm": True}})
    rice = _item(phone, "rice", ikeja, 50)
    tr = _send(cook, ikeja, lekki, rice, 20).json()
    assert client.post(f"/app/api/transfers/{tr['id']}/cancel", cookies=cook, json={"reason": ""}).status_code == 400
    r = client.post(f"/app/api/transfers/{tr['id']}/cancel", cookies=cook, json={"reason": "Bus didn't come"})
    assert r.json()["status"] == "cancelled"
    assert _stock(phone, "rice", ikeja)[0] == 50 and _stock(phone, "rice", lekki)[0] == 0


def test_admin_kept_to_a_branch():
    phone, cook = _premium_owner()
    ikeja, lekki = _two_branches(cook)
    client.put("/app/api/settings/business", cookies=cook, json={"values": {"transfer_confirm": True}})
    ikeja_rice = _item(phone, "rice", ikeja, 50)
    lekki_beans = _item(phone, "beans", lekki, 30)
    db = SessionLocal()
    owner = db.query(User).filter(User.phone == phone).first()
    sp = f"234880{next(_seq):06d}1"[:13]
    db.add(User(phone=sp, name="B", role="delegate", parent_id=owner.id, branch_id=lekki,
                can_view_all_transactions=True, staff_limits='["own_branch"]',
                recovery_pin_hash=web_auth._hash_pin("1234"), subscription_status="ACTIVE"))
    db.commit(); db.close()
    c = client.post("/app/api/auth/login", json={"phone": sp, "pin": "1234"}).cookies
    assert _send(c, ikeja, lekki, ikeja_rice, 5).status_code == 403          # not from Ikeja
    assert _send(c, lekki, ikeja, lekki_beans, 5).status_code == 200         # from their own branch
    tr = _send(cook, ikeja, lekki, ikeja_rice, 5).json()                     # owner sends them rice
    doc = client.get(f"/app/api/transfers/{tr['id']}", cookies=c).json()
    assert doc["can_receive"] is True and doc["can_cancel"] is False
    assert client.post(f"/app/api/transfers/{tr['id']}/receive", cookies=c, json={}).status_code == 200
