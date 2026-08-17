"""
Thrift / Ajo groups: a user creates named rotating-savings groups (each with its
own contribution amount + members), shares an invite link, approves joiners
(admin or a promoted approver), records contributions and rotates the pot.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-thrift-00000000000000000")

import pytest
from fastapi.testclient import TestClient

from main import app
import web_auth
from database import SessionLocal
from models import ThriftGroup

client = TestClient(app)
_seq = iter(range(7500, 7999))


@pytest.fixture(autouse=True)
def _reset():
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()
    yield
    with web_auth._auth_lock:
        web_auth._auth_attempts.clear()


def _user(name):
    n = next(_seq)
    phone = f"234819{n:06d}"
    client.post("/app/api/auth/register", json={"name": name, "phone": phone, "pin": "1357"})
    cook = client.post("/app/api/auth/login", json={"phone": phone, "pin": "1357"}).cookies
    return phone, cook


def _make_group(cook, name="Market Women Ajo", amount=5000):
    return client.post("/app/api/thrift/groups", cookies=cook,
                       json={"name": name, "contribution_amount": amount, "frequency": "weekly"}).json()


def test_full_rotation_flow():
    _, admin = _user("Ada")
    g = _make_group(admin)
    gid = g["id"]
    assert g["contribution_amount"] == 5000
    assert g["active_count"] == 1                       # creator is member #1
    assert g["members"][0]["role"] == "admin"
    assert g["members"][0]["turn_order"] == 1

    # Add a participant directly.
    g = client.post(f"/app/api/thrift/groups/{gid}/members", cookies=admin,
                    json={"name": "Amina"}).json()
    assert g["active_count"] == 2
    assert g["pot"] == 10000                            # 5000 x 2
    token = g["invite_token"]
    assert token

    # A third person joins via the link → pending approval.
    _, tunde = _user("Tunde")
    info = client.get(f"/app/api/thrift/join/{token}", cookies=tunde).json()
    assert info["name"] == "Market Women Ajo"
    jr = client.post(f"/app/api/thrift/join/{token}", cookies=tunde, json={}).json()
    assert jr["status"] == "pending"

    g = client.get(f"/app/api/thrift/groups/{gid}", cookies=admin).json()
    assert g["pending_count"] == 1
    pending = next(m for m in g["members"] if m["status"] == "pending")

    g = client.post(f"/app/api/thrift/members/{pending['id']}/approve", cookies=admin).json()
    assert g["active_count"] == 3
    assert g["pending_count"] == 0

    # Everyone contributes for round 1.
    for m in [mm for mm in g["members"] if mm["status"] == "active"]:
        client.post(f"/app/api/thrift/groups/{gid}/contributions", cookies=admin,
                    json={"member_id": m["id"]})
    g = client.get(f"/app/api/thrift/groups/{gid}", cookies=admin).json()
    assert g["paid_count"] == 3
    assert g["collected_this_round"] == 15000
    assert g["current_turn"]["name"]                    # someone is due the pot

    # Pay out the pot and advance the round.
    g = client.post(f"/app/api/thrift/groups/{gid}/payout", cookies=admin).json()
    assert g["current_round"] == 2
    assert g["payouts"][0]["amount"] == 15000


def test_promoted_approver_can_add_and_approve():
    _, admin = _user("Owner")
    g = _make_group(admin, name="Office Ajo", amount=2000)
    gid = g["id"]
    token = g["invite_token"]

    # Member joins, admin approves, then promotes them to approver.
    _, bola = _user("Bola")
    client.post(f"/app/api/thrift/join/{token}", cookies=bola, json={})
    g = client.get(f"/app/api/thrift/groups/{gid}", cookies=admin).json()
    bola_m = next(m for m in g["members"] if m["status"] == "pending")
    client.post(f"/app/api/thrift/members/{bola_m['id']}/approve", cookies=admin)
    g = client.post(f"/app/api/thrift/members/{bola_m['id']}/promote", cookies=admin).json()
    assert next(m for m in g["members"] if m["id"] == bola_m["id"])["role"] == "approver"

    # The approver can now add a participant.
    r = client.post(f"/app/api/thrift/groups/{gid}/members", cookies=bola, json={"name": "Chidi"})
    assert r.status_code == 200, r.text
    assert r.json()["active_count"] == 3


def test_member_cap_blocks_extra_joins():
    _, admin = _user("Capped")
    g = client.post("/app/api/thrift/groups", cookies=admin,
                    json={"name": "Small Ajo", "contribution_amount": 1000, "max_members": 2}).json()
    gid = g["id"]
    assert g["max_members"] == 2
    # admin is member #1; add member #2 → full.
    g = client.post(f"/app/api/thrift/groups/{gid}/members", cookies=admin, json={"name": "Two"}).json()
    assert g["accepting"] is False
    token = g["invite_token"]
    _, third = _user("Third")
    r = client.post(f"/app/api/thrift/join/{token}", cookies=third, json={})
    assert r.status_code == 400


def test_admin_can_lock_and_unlock():
    _, admin = _user("Locker")
    g = _make_group(admin, name="Lockable", amount=1000)
    gid, token = g["id"], g["invite_token"]

    g = client.post(f"/app/api/thrift/groups/{gid}/settings", cookies=admin, json={"locked": True}).json()
    assert g["locked"] is True and g["accepting"] is False
    _, joiner = _user("Joiner")
    assert client.post(f"/app/api/thrift/join/{token}", cookies=joiner, json={}).status_code == 400

    g = client.post(f"/app/api/thrift/groups/{gid}/settings", cookies=admin, json={"locked": False}).json()
    assert g["locked"] is False
    assert client.post(f"/app/api/thrift/join/{token}", cookies=joiner, json={}).json()["status"] in ("pending", "active")


def test_capped_group_stays_open_until_full():
    """A 3-member cap must not 'complete' after one member pays out — it keeps
    accepting members until it is full (the reported bug)."""
    _, admin = _user("Boss")
    g = client.post("/app/api/thrift/groups", cookies=admin,
                    json={"name": "Cycle", "contribution_amount": 1000, "max_members": 3}).json()
    gid = g["id"]
    admin_id = g["members"][0]["id"]
    client.post(f"/app/api/thrift/groups/{gid}/contributions", cookies=admin, json={"member_id": admin_id})
    g = client.post(f"/app/api/thrift/groups/{gid}/payout", cookies=admin).json()
    assert g["status"] == "active"
    assert g["current_round"] == 2
    assert g["accepting"] is True


def test_payout_blocked_without_contributions():
    _, admin = _user("Boss2")
    g = _make_group(admin, name="NoPay", amount=1000)   # uncapped, admin only
    r = client.post(f"/app/api/thrift/groups/{g['id']}/payout", cookies=admin)
    assert r.status_code == 400


def test_prematurely_completed_group_self_heals():
    _, admin = _user("Heal")
    g = client.post("/app/api/thrift/groups", cookies=admin,
                    json={"name": "Stuck", "contribution_amount": 1000, "max_members": 3}).json()
    gid = g["id"]
    db = SessionLocal()
    try:  # simulate the old bug: completed while still below the cap
        grp = db.query(ThriftGroup).filter(ThriftGroup.id == gid).first()
        grp.status = "completed"
        db.commit()
    finally:
        db.close()
    g = client.get(f"/app/api/thrift/groups/{gid}", cookies=admin).json()
    assert g["status"] == "active"
    assert g["accepting"] is True


def test_spillover_creates_next_group_when_full():
    """One auto-continue link keeps recruiting: when the group fills, the same
    link starts and joins the next group in the series."""
    _, admin = _user("Chainer")
    g = client.post("/app/api/thrift/groups", cookies=admin, json={
        "name": "Chain", "contribution_amount": 1000, "max_members": 2,
        "spillover": True, "require_approval": False}).json()
    gid, token = g["id"], g["invite_token"]

    _, a = _user("A")
    ra = client.post(f"/app/api/thrift/join/{token}", cookies=a, json={}).json()
    assert ra["group_id"] == gid            # first group had room (admin + A = full)

    _, b = _user("B")
    rb = client.post(f"/app/api/thrift/join/{token}", cookies=b, json={}).json()
    assert rb["group_id"] != gid            # spilled into a brand-new group

    groups = client.get("/app/api/thrift/groups", cookies=admin).json()["groups"]
    assert len(groups) == 2
    assert any(gr["name"] == "Chain 2" for gr in groups)


def test_existing_member_is_not_spilled_by_the_link():
    _, admin = _user("Owner")
    g = client.post("/app/api/thrift/groups", cookies=admin, json={
        "name": "Chain", "contribution_amount": 1000, "max_members": 2,
        "spillover": True, "require_approval": False}).json()
    gid, token = g["id"], g["invite_token"]
    _, a = _user("A")
    client.post(f"/app/api/thrift/join/{token}", cookies=a, json={})   # A fills it
    # A re-opens the link → returns the same membership, no new group.
    again = client.post(f"/app/api/thrift/join/{token}", cookies=a, json={}).json()
    assert again["group_id"] == gid and again["already"] is True
    assert len(client.get("/app/api/thrift/groups", cookies=admin).json()["groups"]) == 1


def test_admin_choice_payout_and_recipient_confirmation():
    _, admin = _user("Boss")
    g = client.post("/app/api/thrift/groups", cookies=admin, json={
        "name": "Choice", "contribution_amount": 1000, "max_members": 3,
        "payout_method": "choice", "require_approval": False}).json()
    gid, token = g["id"], g["invite_token"]
    admin_id = g["members"][0]["id"]

    _, joiner = _user("Joiner")
    client.post(f"/app/api/thrift/join/{token}", cookies=joiner, json={})
    g = client.get(f"/app/api/thrift/groups/{gid}", cookies=admin).json()
    joiner_id = next(m["id"] for m in g["members"] if m["role"] == "member")

    # Everyone contributes this round.
    client.post(f"/app/api/thrift/groups/{gid}/contributions", cookies=admin, json={"member_id": admin_id})
    client.post(f"/app/api/thrift/groups/{gid}/contributions", cookies=admin, json={"member_id": joiner_id})

    # Choice payout requires picking a member.
    assert client.post(f"/app/api/thrift/groups/{gid}/payout", cookies=admin, json={}).status_code == 400

    g = client.post(f"/app/api/thrift/groups/{gid}/payout", cookies=admin,
                    json={"member_id": joiner_id}).json()
    assert next(m for m in g["members"] if m["id"] == joiner_id)["has_collected"] is True
    payout = g["payouts"][0]
    assert payout["status"] == "pending"
    pid = payout["id"]

    # Only the recipient can confirm — not the admin.
    assert client.post(f"/app/api/thrift/payouts/{pid}/confirm", cookies=admin).status_code == 403
    g = client.post(f"/app/api/thrift/payouts/{pid}/confirm", cookies=joiner).json()
    assert g["payouts"][0]["status"] == "confirmed"


def test_manual_partial_contribution_amount():
    _, admin = _user("Boss2")
    g = _make_group(admin, name="Manual", amount=5000)
    gid = g["id"]
    admin_id = g["members"][0]["id"]
    g = client.post(f"/app/api/thrift/groups/{gid}/contributions", cookies=admin,
                    json={"member_id": admin_id, "amount": 2000}).json()
    assert next(m for m in g["members"] if m["id"] == admin_id)["total_contributed"] == 2000
    assert g["collected_this_round"] == 2000


def test_many_groups_and_unique_names_and_access():
    _, cook = _user("Multi")
    _make_group(cook, name="Group A", amount=5000)
    _make_group(cook, name="Group B", amount=1000)
    groups = client.get("/app/api/thrift/groups", cookies=cook).json()["groups"]
    assert len(groups) == 2
    assert {g["name"] for g in groups} == {"Group A", "Group B"}

    # Duplicate active name is rejected.
    dup = client.post("/app/api/thrift/groups", cookies=cook,
                      json={"name": "Group A", "contribution_amount": 500})
    assert dup.status_code == 409

    # A non-member cannot view someone else's group.
    gid = groups[0]["id"]
    _, stranger = _user("Stranger")
    assert client.get(f"/app/api/thrift/groups/{gid}", cookies=stranger).status_code == 403
