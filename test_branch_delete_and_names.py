"""
Branches page fixes: deleting a branch moves EVERYTHING in it (not only
customers, stock, sales and staff) to the remaining default; branch names are
unique ignoring capitals and spaces; a transfer keeps its history after a branch
is gone, and a branch with stock on the way can't be deleted.
"""
from test_pos_branch_scope import client, _premium_owner, _two_branches, _stock, _reset  # noqa: F401
from database import SessionLocal
from models import Expense, HeldSale, InventoryItem, Branch


def test_names_unique_ignoring_capitals_and_spaces():
    phone, cook = _premium_owner()
    ikeja, lekki = _two_branches(cook)
    assert client.post("/app/api/branches", cookies=cook, json={"name": "  ikeja "}).status_code == 400
    assert client.post("/app/api/branches", cookies=cook, json={"name": "Yaba   Market"}).json()["name"] == "Yaba Market"
    assert client.put(f"/app/api/branches/{lekki}", cookies=cook, json={"name": "IKEJA"}).status_code == 400
    assert client.put(f"/app/api/branches/{lekki}", cookies=cook, json={"name": "Lekki Phase 1"}).status_code == 200
    assert client.put(f"/app/api/branches/{lekki}", cookies=cook, json={"name": "lekki phase 1"}).status_code == 200  # itself


def test_delete_moves_everything_and_counts_products_twice():
    phone, cook = _premium_owner()
    ikeja, lekki = _two_branches(cook)
    _stock(phone, "rice", ikeja)
    _stock(phone, "rice", lekki)
    _stock(phone, "beans", lekki)
    db = SessionLocal()
    db.add(Expense(owner_phone=phone, amount=500, branch_id=lekki))
    db.add(HeldSale(owner_phone=phone, branch_id=lekki))
    db.commit(); db.close()
    r = client.delete(f"/app/api/branches/{lekki}", cookies=cook).json()
    assert r["reassigned_to_branch_id"] == ikeja and r["products_twice"] == 1
    db = SessionLocal()
    try:
        assert db.query(Expense).filter_by(owner_phone=phone).one().branch_id == ikeja
        assert db.query(HeldSale).filter_by(owner_phone=phone).one().branch_id == ikeja
        assert {i.branch_id for i in db.query(InventoryItem).filter_by(owner_phone=phone)} == {ikeja}
        assert db.query(Branch).filter_by(id=lekki).first() is None
    finally:
        db.close()


def test_transfers_and_deleting_a_branch():
    phone, cook = _premium_owner()
    ikeja, lekki = _two_branches(cook)
    rice = _stock(phone, "rice", ikeja)
    client.put("/app/api/settings/business", cookies=cook, json={"values": {"transfer_confirm": True}})
    tr = client.post("/app/api/transfers", cookies=cook, json={
        "from_branch_id": ikeja, "to_branch_id": lekki, "lines": [{"item_id": rice, "quantity": 2}]}).json()
    assert "on its way" in client.delete(f"/app/api/branches/{lekki}", cookies=cook).json()["detail"]
    client.post(f"/app/api/transfers/{tr['id']}/receive", cookies=cook, json={})
    assert client.delete(f"/app/api/branches/{lekki}", cookies=cook).status_code == 200
    doc = client.get(f"/app/api/transfers/{tr['id']}", cookies=cook).json()
    assert (doc["from_branch"], doc["to_branch"]) == ("Ikeja", "Deleted branch")
