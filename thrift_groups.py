"""
Thrift / Ajo groups — a real rotating savings engine (ROSCA).

A ThriftGroup has a fixed contribution amount and a set of members in a turn
order. Each round every active member contributes the amount; the pot rotates to
one member (the one whose turn_order == current_round). One user can run many
groups, each with its own name, amount and members. Members join by an invite
link; the group admin (creator) can promote a member to "approver" to share the
power to approve joiners and record contributions.
"""
import secrets
from datetime import datetime, timezone

from models import (
    ThriftGroup, ThriftMember, ThriftContribution, ThriftPayout, User,
)
from web_auth import phone_candidates


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_token():
    return secrets.token_urlsafe(20)


def _cap(name):
    return (name or "—").strip().title()


def _by_turn(members):
    return sorted(members, key=lambda m: (m.turn_order is None, m.turn_order or 0))


def active_members(db, group_id):
    rows = db.query(ThriftMember).filter(
        ThriftMember.group_id == group_id,
        ThriftMember.status == "active",
    ).all()
    return _by_turn(rows)


def _next_turn_order(db, group_id):
    rows = db.query(ThriftMember.turn_order).filter(
        ThriftMember.group_id == group_id,
        ThriftMember.status == "active",
        ThriftMember.turn_order != None,
    ).all()
    return (max((r[0] for r in rows), default=0) or 0) + 1


def member_for_user(db, group_id, user_phone):
    if not user_phone:
        return None
    return db.query(ThriftMember).filter(
        ThriftMember.group_id == group_id,
        ThriftMember.user_phone.in_(phone_candidates(user_phone)),
        ThriftMember.status != "removed",
    ).first()


def viewer_role(db, group, viewer_phone):
    """The viewer's role in this group: 'admin' | 'approver' | 'member' | None."""
    m = member_for_user(db, group.id, viewer_phone)
    if m and m.status == "active":
        return m.role
    if viewer_phone in phone_candidates(group.owner_phone):
        return "admin"
    if m:  # pending member
        return "pending"
    return None


def can_approve(role):
    return role in ("admin", "approver")


def create_group(db, owner_phone, name, contribution_amount, frequency="weekly",
                 admin_name=None, require_approval=True):
    group = ThriftGroup(
        owner_phone=owner_phone,
        name=(name or "").strip(),
        contribution_amount=int(contribution_amount or 0),
        frequency=frequency or "weekly",
        current_round=1,
        invite_token=new_token(),
        require_approval=bool(require_approval),
        status="active",
    )
    db.add(group)
    db.flush()
    # The creator is member #1 (admin), so they are part of the rotation too.
    db.add(ThriftMember(
        group_id=group.id, name=(admin_name or "Me").strip(),
        user_phone=owner_phone, role="admin", status="active",
        turn_order=1, joined_at=_utcnow(),
    ))
    db.commit()
    db.refresh(group)
    return group


def add_member(db, group, name, phone=None):
    m = ThriftMember(
        group_id=group.id, name=(name or "").strip(), phone=phone,
        role="member", status="active",
        turn_order=_next_turn_order(db, group.id), joined_at=_utcnow(),
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def join_via_link(db, group, user, name):
    """A logged-in user joins through the invite link. Duplicate → return existing.
    require_approval → 'pending' (needs an admin/approver), else immediately active."""
    existing = member_for_user(db, group.id, user.phone)
    if existing:
        return existing, False
    pending = group.require_approval
    m = ThriftMember(
        group_id=group.id,
        name=(name or getattr(user, "name", None) or user.phone).strip(),
        phone=user.phone, user_phone=user.phone,
        role="member",
        status="pending" if pending else "active",
        turn_order=None if pending else _next_turn_order(db, group.id),
        joined_at=None if pending else _utcnow(),
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m, True


def approve_member(db, member):
    member.status = "active"
    member.turn_order = _next_turn_order(db, member.group_id)
    member.joined_at = _utcnow()
    db.commit()


def record_contribution(db, group, member, amount=None, recorded_by_phone=None):
    amt = int(amount) if amount else int(group.contribution_amount or 0)
    c = ThriftContribution(
        group_id=group.id, member_id=member.id,
        round_number=group.current_round, amount=amt,
        recorded_by_phone=recorded_by_phone,
    )
    db.add(c)
    db.commit()
    return c


def record_payout(db, group, recorded_by_phone=None):
    """Pay the pot to the member whose turn it is (turn_order == current_round),
    then advance to the next round. Completes the group after the last member."""
    members = active_members(db, group.id)
    recipient = next((m for m in members if m.turn_order == group.current_round), None)
    if not recipient:
        return None
    pot = int(group.contribution_amount or 0) * len(members)
    payout = ThriftPayout(
        group_id=group.id, member_id=recipient.id,
        round_number=group.current_round, amount=pot,
        recorded_by_phone=recorded_by_phone,
    )
    db.add(payout)
    if group.current_round >= len(members):
        group.status = "completed"
    else:
        group.current_round += 1
    db.commit()
    return payout


def serialize_group(db, group, viewer_phone, detail=False):
    role = viewer_role(db, group, viewer_phone)
    is_admin = viewer_phone in phone_candidates(group.owner_phone)
    approver = can_approve(role)
    members = _by_turn(db.query(ThriftMember).filter(
        ThriftMember.group_id == group.id,
        ThriftMember.status != "removed",
    ).all())
    active = [m for m in members if m.status == "active"]
    pending = [m for m in members if m.status == "pending"]

    out = {
        "id": group.id,
        "name": group.name,
        "contribution_amount": group.contribution_amount,
        "frequency": group.frequency,
        "current_round": group.current_round,
        "status": group.status,
        "my_role": role,
        "is_admin": is_admin,
        "can_approve": approver,
        "active_count": len(active),
        "pending_count": len(pending),
        "pot": int(group.contribution_amount or 0) * len(active),
        "total_rounds": len(active),
        # The invite link is only handed to people who can bring members in.
        "invite_token": group.invite_token if approver else None,
    }
    if not detail:
        return out

    # Per-member totals + who has paid the current round.
    contribs = db.query(ThriftContribution).filter(
        ThriftContribution.group_id == group.id
    ).all()
    total_by = {}
    paid_this_round = set()
    for c in contribs:
        total_by[c.member_id] = total_by.get(c.member_id, 0) + (c.amount or 0)
        if c.round_number == group.current_round:
            paid_this_round.add(c.member_id)

    my_member = member_for_user(db, group.id, viewer_phone)
    my_id = my_member.id if my_member else None

    out["members"] = [{
        "id": m.id,
        "name": _cap(m.name),
        "role": m.role,
        "status": m.status,
        "turn_order": m.turn_order,
        "total_contributed": total_by.get(m.id, 0),
        "paid_current_round": m.id in paid_this_round,
        "is_me": m.id == my_id,
    } for m in members]

    turn = next((m for m in active if m.turn_order == group.current_round), None)
    out["current_turn"] = {"member_id": turn.id, "name": _cap(turn.name)} if turn else None
    out["paid_count"] = len(paid_this_round & {m.id for m in active})
    out["collected_this_round"] = sum(c.amount or 0 for c in contribs
                                      if c.round_number == group.current_round)

    payouts = db.query(ThriftPayout).filter(
        ThriftPayout.group_id == group.id
    ).order_by(ThriftPayout.round_number.desc()).all()
    id_to_name = {m.id: _cap(m.name) for m in members}
    out["payouts"] = [{
        "member_name": id_to_name.get(p.member_id, "—"),
        "round_number": p.round_number,
        "amount": p.amount,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    } for p in payouts]
    return out
