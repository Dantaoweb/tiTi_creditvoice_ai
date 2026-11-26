"""
Stock per branch on the Inventory page: the owner (or a whole-business admin)
chooses which branch new stock goes into, can look at one branch, and can move a
product put in the wrong branch. Someone kept to their branch always works in it.
"""
from test_pos_branch_scope import client, _premium_owner, _stock, _two_branches, _reset, _seq  # noqa: F401
import web_auth
from database import SessionLocal
from models import User, InventoryItem


def _add(cook, phone, name, branch_id=None):
    body = {"owner_phone": phone, "name": name, "quantity": 5, "selling_price": 500}
    if branch_id is not None:
        body["branch_id"] = branch_id
    return client.post("/app/api/inventory", cookies=cook, json=body)


def _branch_of(phone, name):
    db = SessionLocal()
    try:
        return db.query(InventoryItem).filter_by(owner_phone=phone, name=name).one().branch_id
    finally:
        db.close()


def test_owner_chooses_the_branch_and_each_branch_has_its_own():
    phone, cook = _premium_owner()
    ikeja, lekki = _two_branches(cook)
    assert _add(cook, phone, "beans").status_code == 200            # no choice → default branch
    assert _branch_of(phone, "beans") == ikeja
    assert _add(cook, phone, "rice", ikeja).status_code == 200
    assert _add(cook, phone, "rice", lekki).status_code == 200      # Lekki's own rice — not a duplicate
    assert _add(cook, phone, "rice", lekki).status_code == 409      # twice in one branch is
    sim = client.get("/app/api/inventory/similar", cookies=cook, params={"name": "rice", "branch_id": lekki}).json()
    assert len(sim["exact"]) == 1
    # one branch at a time, and each row says its branch
    rows = client.get("/app/api/inventory", cookies=cook, params={"branch_id": lekki}).json()["items"]
    assert [(r["name"], r["branch_name"]) for r in rows] == [("rice", "Lekki")]
    assert client.get("/app/api/inventory/summary", cookies=cook, params={"branch_id": lekki}).json()["total"] == 1
    assert client.get("/app/api/inventory", cookies=cook).json()["total"] == 3


def test_quick_add_into_a_branch_and_someone_elses_branch_refused():
    phone, cook = _premium_owner()
    ikeja, lekki = _two_branches(cook)
    _add(cook, phone, "garri", ikeja)
    r = client.post("/app/api/inventory/bulk", cookies=cook,
                    json={"owner_phone": phone, "names": ["garri", "palm oil"], "branch_id": lekki}).json()
    assert r["saved"] == 2                                        # Ikeja's garri doesn't block Lekki's
    assert _branch_of(phone, "palm oil") == lekki
    other_phone, other_cook = _premium_owner()
    theirs, _ = _two_branches(other_cook)
    assert _add(cook, phone, "yam", theirs).status_code == 400


def test_move_a_product_to_another_branch():
    phone, cook = _premium_owner()
    ikeja, lekki = _two_branches(cook)
    _add(cook, phone, "sugar")                                     # landed in Ikeja by mistake
    item_id = client.get("/app/api/inventory", cookies=cook, params={"q": "sugar"}).json()["items"][0]["id"]
    assert client.put(f"/app/api/inventory/{item_id}", cookies=cook, json={"branch_id": lekki}).status_code == 200
    assert _branch_of(phone, "sugar") == lekki
    _add(cook, phone, "sugar", ikeja)
    again = client.get("/app/api/inventory", cookies=cook, params={"q": "sugar", "branch_id": ikeja}).json()["items"][0]["id"]
    assert client.put(f"/app/api/inventory/{again}", cookies=cook, json={"branch_id": lekki}).status_code == 409


def test_admin_kept_to_their_branch_works_only_there():
    phone, cook = _premium_owner()
    ikeja, lekki = _two_branches(cook)
    ikeja_item = _stock(phone, "flour", ikeja)
    db = SessionLocal()
    owner = db.query(User).filter(User.phone == phone).first()
    sp = f"234879{next(_seq):06d}1"[:13]
    db.add(User(phone=sp, name="B", role="delegate", parent_id=owner.id, branch_id=lekki,
                can_view_all_transactions=True, staff_limits='["own_branch"]',
                recovery_pin_hash=web_auth._hash_pin("1234"), subscription_status="ACTIVE"))
    db.commit(); db.close()
    c = client.post("/app/api/auth/login", json={"phone": sp, "pin": "1234"}).cookies
    assert _add(c, phone, "salt", ikeja).status_code == 200        # asked for Ikeja…
    assert _branch_of(phone, "salt") == lekki                       # …but it goes to their branch
    assert client.put(f"/app/api/inventory/{ikeja_item}", cookies=c, json={"selling_price": 1}).status_code == 404
