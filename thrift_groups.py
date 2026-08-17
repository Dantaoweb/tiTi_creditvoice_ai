"""
Thrift / Ajo groups — a real rotating savings engine (ROSCA).

A ThriftGroup has a fixed contribution amount and a set of members in a turn
order. Each round every active member contributes the amount; the pot rotates to
one member (the one whose turn_order == current_round). One user can run many
groups, each with its own name, amount and members. Members join by an invite
link; the group admin (creator) can promote a member to "approver" to share the
power to approve joiners and record contributions.
"""
import re
import secrets
from datetime import datetime, timezone

from sqlalchemy import func

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


def can_record_contribution(db, group, viewer_phone, target_member_id):
    """Who may log a contribution: approvers always; in a target (shared-goal)
    group a member may also record their OWN saving."""
    role = viewer_role(db, group, viewer_phone)
    if can_approve(role):
        return True
    if getattr(group, "group_type", "rotating") == "target":
        m = member_for_user(db, group.id, viewer_phone)
        if m and m.status == "active" and m.id == target_member_id:
            return True
    return False


def member_slots(db, group_id):
    """Members that count against the cap: active + still-pending requests."""
    return db.query(ThriftMember).filter(
        ThriftMember.group_id == group_id,
        ThriftMember.status.in_(["active", "pending"]),
    ).count()


def can_accept_members(db, group):
    """(ok, reason) — whether the group can take another member right now."""
    if getattr(group, "locked", False):
        return False, "This group is locked — no new members can join."
    cap = getattr(group, "max_members", None)
    if cap and member_slots(db, group.id) >= cap:
        return False, "This group is full."
    return True, None


def member_in_series(db, group, user_phone):
    """The user's existing membership anywhere in this group's series (or just
    this group when it isn't a series) — so an existing member is never spilled
    into a second group by the same link."""
    if group.series_key:
        sibling_ids = [g.id for g in db.query(ThriftGroup).filter(
            ThriftGroup.series_key == group.series_key).all()]
    else:
        sibling_ids = [group.id]
    if not sibling_ids or not user_phone:
        return None
    return db.query(ThriftMember).filter(
        ThriftMember.group_id.in_(sibling_ids),
        ThriftMember.user_phone.in_(phone_candidates(user_phone)),
        ThriftMember.status != "removed",
    ).first()


def _at_group_limit(db, owner_phone):
    """True when the owner has hit their plan's active-group cap (so spillover
    must not auto-create another group)."""
    from models import User
    from subscriptions import get_business_subscription, check_thrift_group_limit
    owner = db.query(User).filter(User.phone == owner_phone).first()
    if not owner:
        return False
    sub = get_business_subscription(db, owner)
    within, _ = check_thrift_group_limit(db, owner_phone, sub)
    return not within


def _create_next_sibling(db, group):
    """Start the next group in a spillover series, copying its settings and
    numbering the name (e.g. 'Aje oloja' → 'Aje oloja 2'). Returns None when the
    owner is at their plan's group cap."""
    if _at_group_limit(db, group.owner_phone):
        return None
    base = re.sub(r"\s+\d+$", "", group.name or "").strip() or "Group"
    count = db.query(ThriftGroup).filter(ThriftGroup.series_key == group.series_key).count()
    owner = db.query(User).filter(User.phone == group.owner_phone).first()
    return create_group(
        db, group.owner_phone, f"{base} {count + 1}", group.contribution_amount,
        frequency=group.frequency, admin_name=getattr(owner, "name", None),
        require_approval=group.require_approval, max_members=group.max_members,
        spillover=True, series_key=group.series_key,
    )


def open_sibling(db, group):
    """An existing open sibling in the series (no creation), or None."""
    if not group.series_key:
        return None
    siblings = db.query(ThriftGroup).filter(
        ThriftGroup.series_key == group.series_key,
        ThriftGroup.status == "active",
    ).order_by(ThriftGroup.id.asc()).all()
    for s in siblings:
        if can_accept_members(db, s)[0]:
            return s
    return None


def resolve_join_target(db, group):
    """The group a new joiner should actually land in: this group if it can take
    them, otherwise (for a spillover series) the next open sibling, creating one
    when all are full. Non-spillover groups resolve to themselves."""
    if group.status == "active" and can_accept_members(db, group)[0]:
        return group
    if not group.spillover or not group.series_key:
        return group
    # Falls back to the (full) original group when the plan cap blocks a new one.
    return open_sibling(db, group) or _create_next_sibling(db, group) or group


def create_group(db, owner_phone, name, contribution_amount, frequency="weekly",
                 admin_name=None, require_approval=True, max_members=None,
                 spillover=False, series_key=None, payout_method="order",
                 group_type="rotating", goal_amount=None, target_date=None):
    group = ThriftGroup(
        owner_phone=owner_phone,
        name=(name or "").strip(),
        group_type="target" if group_type == "target" else "rotating",
        contribution_amount=int(contribution_amount or 0),
        goal_amount=int(goal_amount) if goal_amount else None,
        target_date=target_date,
        frequency=frequency or "weekly",
        current_round=1,
        invite_token=new_token(),
        require_approval=bool(require_approval),
        max_members=int(max_members) if max_members else None,
        locked=False,
        spillover=bool(spillover),
        # A spillover group anchors a series (its own key) unless it inherits one.
        series_key=series_key or (new_token() if spillover else None),
        payout_method=payout_method if payout_method in ("order", "choice") else "order",
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


def _collected_member_ids(db, group_id):
    return {p.member_id for p in db.query(ThriftPayout).filter(
        ThriftPayout.group_id == group_id).all()}


def record_payout(db, group, recorded_by_phone=None, recipient_member_id=None):
    """Pay the pot to a member who hasn't collected yet, then advance. The
    recipient is chosen by the group's payout_method: 'order' uses turn order,
    'choice' lets the admin pass recipient_member_id. Requires the round to be
    fully contributed first. Completes once every member has collected (and the
    group is full, for capped groups). Raises ValueError with a clear message."""
    members = active_members(db, group.id)
    collected = _collected_member_ids(db, group.id)
    eligible = [m for m in members if m.id not in collected]
    if not eligible:
        raise ValueError("Every member has already collected the pot.")

    if group.payout_method == "choice":
        if not recipient_member_id:
            raise ValueError("Choose which member collects the pot this round.")
        recipient = next((m for m in eligible if m.id == recipient_member_id), None)
        if not recipient:
            raise ValueError("That member can't collect (not active, or already collected).")
    else:  # order
        recipient = next((m for m in eligible if m.turn_order == group.current_round), None)
        if not recipient:
            recipient = eligible[0]  # skip past anyone who already collected out of order

    # Everyone must have contributed for this round before the pot is paid out.
    paid_ids = {c.member_id for c in db.query(ThriftContribution).filter(
        ThriftContribution.group_id == group.id,
        ThriftContribution.round_number == group.current_round,
    ).all()}
    owing = [m for m in members if m.id not in paid_ids]
    if owing:
        raise ValueError(
            f"Record everyone's contribution for round {group.current_round} first "
            f"— {len(owing)} still owing."
        )

    pot = int(group.contribution_amount or 0) * len(members)
    db.add(ThriftPayout(
        group_id=group.id, member_id=recipient.id,
        round_number=group.current_round, amount=pot,
        recorded_by_phone=recorded_by_phone, status="pending",
    ))
    total_rounds = group.max_members or len(members)
    is_full = (not group.max_members) or (len(members) >= group.max_members)
    if (len(collected) + 1) >= total_rounds and is_full:
        group.status = "completed"
    else:
        group.current_round += 1
    db.commit()
    return True


def confirm_payout(db, payout, by_phone):
    payout.status = "confirmed"
    payout.confirmed_at = _utcnow()
    payout.confirmed_by_phone = by_phone
    db.commit()


def heal_group(db, group):
    """Repair a group wrongly marked 'completed' under the old rule: a capped
    group that still has open slots must stay active and keep accepting members."""
    if group.status == "completed" and group.max_members:
        active = db.query(ThriftMember).filter(
            ThriftMember.group_id == group.id,
            ThriftMember.status == "active",
        ).count()
        if active < group.max_members:
            group.status = "active"
            db.commit()
    return group


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

    gtype = getattr(group, "group_type", None) or "rotating"
    out = {
        "id": group.id,
        "name": group.name,
        "group_type": gtype,
        "contribution_amount": group.contribution_amount,
        "goal_amount": getattr(group, "goal_amount", None),
        "target_date": group.target_date.isoformat() if getattr(group, "target_date", None) else None,
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
        "max_members": getattr(group, "max_members", None),
        "locked": bool(getattr(group, "locked", False)),
        "spillover": bool(getattr(group, "spillover", False)),
        "payout_method": getattr(group, "payout_method", None) or "order",
        "slots_taken": member_slots(db, group.id),
        "accepting": can_accept_members(db, group)[0] and group.status == "active",
        # The invite link is only handed to people who can bring members in.
        "invite_token": group.invite_token if approver else None,
    }
    if gtype == "target":
        total = db.query(func.coalesce(func.sum(ThriftContribution.amount), 0)).filter(
            ThriftContribution.group_id == group.id).scalar() or 0
        goal = group.goal_amount or 0
        out["total_saved"] = int(total)
        out["goal_pct"] = min(100, round(total / goal * 100)) if goal else None
        out["goal_reached"] = bool(goal and total >= goal)
        out["days_to_target"] = ((group.target_date.date() - _utcnow().date()).days
                                 if group.target_date else None)
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
    collected = _collected_member_ids(db, group.id)

    out["members"] = [{
        "id": m.id,
        "name": _cap(m.name),
        "role": m.role,
        "status": m.status,
        "turn_order": m.turn_order,
        "total_contributed": total_by.get(m.id, 0),
        "paid_current_round": m.id in paid_this_round,
        "has_collected": m.id in collected,
        "is_me": m.id == my_id,
    } for m in members]
    # Members still eligible to collect the pot (for the admin's 'choice' picker).
    out["eligible_recipients"] = [
        {"id": m.id, "name": _cap(m.name)}
        for m in active if m.id not in collected
    ]

    if group.payout_method == "choice":
        out["current_turn"] = None
    else:
        turn = next((m for m in active if m.turn_order == group.current_round and m.id not in collected), None)
        out["current_turn"] = {"member_id": turn.id, "name": _cap(turn.name)} if turn else None
    out["paid_count"] = len(paid_this_round & {m.id for m in active})
    out["collected_this_round"] = sum(c.amount or 0 for c in contribs
                                      if c.round_number == group.current_round)

    payouts = db.query(ThriftPayout).filter(
        ThriftPayout.group_id == group.id
    ).order_by(ThriftPayout.round_number.desc()).all()
    id_to_member = {m.id: m for m in members}
    my_cands = phone_candidates(viewer_phone)
    out["payouts"] = [{
        "id": p.id,
        "member_name": _cap(id_to_member[p.member_id].name) if p.member_id in id_to_member else "—",
        "round_number": p.round_number,
        "amount": p.amount,
        # Legacy rows (status NULL) are treated as already confirmed.
        "status": p.status or "confirmed",
        "confirmed": (p.status or "confirmed") == "confirmed",
        # The recipient (if a linked account) can confirm they received it.
        "can_confirm": (p.status == "pending") and bool(
            p.member_id in id_to_member
            and id_to_member[p.member_id].user_phone in my_cands
        ),
        "created_at": p.created_at.isoformat() if p.created_at else None,
    } for p in payouts]
    return out
