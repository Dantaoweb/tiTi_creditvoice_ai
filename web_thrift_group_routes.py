"""
Thrift / Ajo group routes: create & manage rotating savings groups, invite links,
member approval, contributions and payouts. Registered from web_routes.
"""
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from models import User, ThriftGroup, ThriftMember
from web_auth import require_web_auth, phone_candidates
import thrift_groups as tg


class CreateGroupRequest(BaseModel):
    name: str = Field(max_length=80)
    group_type: Optional[str] = "rotating"          # rotating | target
    contribution_amount: Optional[int] = 0
    goal_amount: Optional[int] = None               # target groups
    target_date: Optional[str] = None               # target groups (YYYY-MM-DD)
    frequency: Optional[str] = Field(default="weekly", max_length=20)
    require_approval: Optional[bool] = True
    max_members: Optional[int] = None
    spillover: Optional[bool] = False
    payout_method: Optional[str] = "order"


class GroupSettingsRequest(BaseModel):
    locked: Optional[bool] = None
    max_members: Optional[int] = None
    payout_method: Optional[str] = None


class PayoutRequest(BaseModel):
    member_id: Optional[int] = None   # required when payout_method == "choice"


class AddMemberRequest(BaseModel):
    name: str = Field(max_length=120)
    phone: Optional[str] = Field(default=None, max_length=20)


class ContributionRequest(BaseModel):
    member_id: int
    amount: Optional[int] = None


class JoinRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)


def register_thrift_group_routes(app):

    def _me(db, session):
        return db.query(User).filter(User.phone == session["phone"]).first()

    def _load_group(db, group_id):
        g = db.query(ThriftGroup).filter(ThriftGroup.id == group_id).first()
        if not g:
            raise HTTPException(status_code=404, detail="Group not found.")
        return tg.heal_group(db, g)

    def _require(db, group, phone, approve=False, admin=False):
        role = tg.viewer_role(db, group, phone)
        if role is None:
            raise HTTPException(status_code=403, detail="You are not a member of this group.")
        # A pending member may view (read-only) but cannot act.
        if admin and phone not in phone_candidates(group.owner_phone):
            raise HTTPException(status_code=403, detail="Only the group admin can do this.")
        if approve and not tg.can_approve(role):
            raise HTTPException(status_code=403, detail="You do not have approval rights in this group.")
        return role

    @app.post("/app/api/thrift/groups")
    def create_group(payload: CreateGroupRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            me = _me(db, session)
            name = payload.name.strip()
            if not name:
                raise HTTPException(status_code=400, detail="Group name is required.")
            is_target = payload.group_type == "target"

            # ── Plan gating ──────────────────────────────────────────────────
            from subscriptions import (
                get_business_subscription, ensure_feature_allowed, check_thrift_group_limit,
            )
            sub = get_business_subscription(db, me) if me else None
            # Target/goal groups are a Pro+ feature.
            if is_target:
                allowed, upgrade = ensure_feature_allowed(db, me, "THRIFT_TARGET_GROUPS", "Target savings groups")
                if not allowed:
                    raise HTTPException(status_code=403, detail=upgrade)
            # Every group must be capped at creation (all plans).
            if not payload.max_members or payload.max_members < 2:
                raise HTTPException(status_code=400, detail="Set a member limit (at least 2) — every group must be capped.")
            # Limited number of groups per plan (Basic: 3).
            if sub:
                within, msg = check_thrift_group_limit(db, session["phone"], sub)
                if not within:
                    raise HTTPException(status_code=403, detail=msg)

            if is_target:
                if not payload.goal_amount or payload.goal_amount <= 0:
                    raise HTTPException(status_code=400, detail="Set a goal amount for the group.")
            elif (payload.contribution_amount or 0) <= 0:
                raise HTTPException(status_code=400, detail="Contribution amount must be greater than zero.")
            target_dt = None
            if payload.target_date:
                from datetime import datetime as _dt
                try:
                    target_dt = _dt.strptime(payload.target_date[:10], "%Y-%m-%d")
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid target date.")
            dup = db.query(ThriftGroup).filter(
                ThriftGroup.owner_phone == session["phone"],
                ThriftGroup.name == name,
                ThriftGroup.status == "active",
            ).first()
            if dup:
                raise HTTPException(status_code=409, detail="You already have a group with that name.")
            g = tg.create_group(
                db, session["phone"], name, payload.contribution_amount,
                frequency=payload.frequency, admin_name=getattr(me, "name", None),
                group_type=payload.group_type, goal_amount=payload.goal_amount, target_date=target_dt,
                require_approval=payload.require_approval,
                max_members=payload.max_members, spillover=payload.spillover,
                payout_method=payload.payout_method,
            )
            return tg.serialize_group(db, g, session["phone"], detail=True)
        finally:
            db.close()

    @app.get("/app/api/thrift/groups")
    def list_groups(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            phone = session["phone"]
            owned = db.query(ThriftGroup).filter(ThriftGroup.owner_phone == phone).all()
            member_rows = db.query(ThriftMember).filter(
                ThriftMember.user_phone.in_(phone_candidates(phone)),
                ThriftMember.status.in_(["active", "pending"]),
            ).all()
            joined_ids = {m.group_id for m in member_rows}
            owned_ids = {g.id for g in owned}
            joined = db.query(ThriftGroup).filter(
                ThriftGroup.id.in_(joined_ids - owned_ids)
            ).all() if (joined_ids - owned_ids) else []
            groups = owned + joined
            for g in groups:
                tg.heal_group(db, g)
            return {"groups": [tg.serialize_group(db, g, phone) for g in groups]}
        finally:
            db.close()

    @app.get("/app/api/thrift/groups/{group_id}")
    def group_detail(group_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            g = _load_group(db, group_id)
            _require(db, g, session["phone"])
            return tg.serialize_group(db, g, session["phone"], detail=True)
        finally:
            db.close()

    @app.post("/app/api/thrift/groups/{group_id}/members")
    def add_member(group_id: int, payload: AddMemberRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            g = _load_group(db, group_id)
            _require(db, g, session["phone"], approve=True)
            if not payload.name.strip():
                raise HTTPException(status_code=400, detail="Member name is required.")
            ok, reason = tg.can_accept_members(db, g)
            if not ok:
                raise HTTPException(status_code=400, detail=reason)
            tg.add_member(db, g, payload.name, payload.phone)
            return tg.serialize_group(db, g, session["phone"], detail=True)
        finally:
            db.close()

    @app.post("/app/api/thrift/groups/{group_id}/contributions")
    def record_contribution(group_id: int, payload: ContributionRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            g = _load_group(db, group_id)
            # Approvers can record for anyone; in a target group a member may
            # record their own saving.
            if not tg.can_record_contribution(db, g, session["phone"], payload.member_id):
                raise HTTPException(status_code=403, detail="You can't record this contribution.")
            m = db.query(ThriftMember).filter(
                ThriftMember.id == payload.member_id,
                ThriftMember.group_id == g.id,
                ThriftMember.status == "active",
            ).first()
            if not m:
                raise HTTPException(status_code=404, detail="Member not found.")
            tg.record_contribution(db, g, m, payload.amount, recorded_by_phone=session["phone"])
            return tg.serialize_group(db, g, session["phone"], detail=True)
        finally:
            db.close()

    @app.post("/app/api/thrift/groups/{group_id}/payout")
    def record_payout(group_id: int, payload: PayoutRequest = PayoutRequest(),
                      session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            g = _load_group(db, group_id)
            _require(db, g, session["phone"], approve=True)
            if getattr(g, "group_type", "rotating") == "target":
                raise HTTPException(status_code=400, detail="Target-savings groups don't rotate a pot.")
            try:
                tg.record_payout(db, g, recorded_by_phone=session["phone"],
                                 recipient_member_id=payload.member_id)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            return tg.serialize_group(db, g, session["phone"], detail=True)
        finally:
            db.close()

    @app.post("/app/api/thrift/payouts/{payout_id}/confirm")
    def confirm_payout(payout_id: int, session: dict = Depends(require_web_auth)):
        """The pot recipient confirms they received it — visible to all members."""
        db = SessionLocal()
        try:
            from models import ThriftPayout
            p = db.query(ThriftPayout).filter(ThriftPayout.id == payout_id).first()
            if not p:
                raise HTTPException(status_code=404, detail="Payout not found.")
            g = _load_group(db, p.group_id)
            member = db.query(ThriftMember).filter(ThriftMember.id == p.member_id).first()
            is_recipient = member and member.user_phone in phone_candidates(session["phone"])
            if not is_recipient:
                raise HTTPException(status_code=403, detail="Only the member who received the pot can confirm it.")
            if p.status != "confirmed":
                tg.confirm_payout(db, p, session["phone"])
            return tg.serialize_group(db, g, session["phone"], detail=True)
        finally:
            db.close()

    @app.post("/app/api/thrift/groups/{group_id}/settings")
    def group_settings(group_id: int, payload: GroupSettingsRequest, session: dict = Depends(require_web_auth)):
        """Admin locks/unlocks the group or adjusts the member cap."""
        db = SessionLocal()
        try:
            g = _load_group(db, group_id)
            _require(db, g, session["phone"], admin=True)
            if payload.locked is not None:
                g.locked = bool(payload.locked)
            if payload.max_members is not None:
                cap = int(payload.max_members)
                if cap and cap < tg.member_slots(db, g.id):
                    raise HTTPException(status_code=400, detail="The cap can't be below the current member count.")
                g.max_members = cap or None
            if payload.payout_method in ("order", "choice"):
                g.payout_method = payload.payout_method
            db.commit()
            return tg.serialize_group(db, g, session["phone"], detail=True)
        finally:
            db.close()

    # ── Member actions ────────────────────────────────────────────────────────
    def _member_and_group(db, member_id):
        m = db.query(ThriftMember).filter(ThriftMember.id == member_id).first()
        if not m:
            raise HTTPException(status_code=404, detail="Member not found.")
        return m, _load_group(db, m.group_id)

    @app.post("/app/api/thrift/members/{member_id}/approve")
    def approve_member(member_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            m, g = _member_and_group(db, member_id)
            _require(db, g, session["phone"], approve=True)
            if m.status == "pending":
                tg.approve_member(db, m)
            return tg.serialize_group(db, g, session["phone"], detail=True)
        finally:
            db.close()

    @app.post("/app/api/thrift/members/{member_id}/decline")
    def decline_member(member_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            m, g = _member_and_group(db, member_id)
            _require(db, g, session["phone"], approve=True)
            m.status = "declined"
            db.commit()
            return tg.serialize_group(db, g, session["phone"], detail=True)
        finally:
            db.close()

    @app.post("/app/api/thrift/members/{member_id}/promote")
    def promote_member(member_id: int, session: dict = Depends(require_web_auth)):
        """Admin grants a member approval power (approver)."""
        db = SessionLocal()
        try:
            m, g = _member_and_group(db, member_id)
            _require(db, g, session["phone"], admin=True)
            if m.role == "member" and m.status == "active":
                m.role = "approver"
                db.commit()
            return tg.serialize_group(db, g, session["phone"], detail=True)
        finally:
            db.close()

    @app.post("/app/api/thrift/members/{member_id}/demote")
    def demote_member(member_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            m, g = _member_and_group(db, member_id)
            _require(db, g, session["phone"], admin=True)
            if m.role == "approver":
                m.role = "member"
                db.commit()
            return tg.serialize_group(db, g, session["phone"], detail=True)
        finally:
            db.close()

    @app.delete("/app/api/thrift/members/{member_id}")
    def remove_member(member_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            m, g = _member_and_group(db, member_id)
            _require(db, g, session["phone"], admin=True)
            if m.role == "admin":
                raise HTTPException(status_code=400, detail="The admin cannot be removed.")
            m.status = "removed"
            db.commit()
            return tg.serialize_group(db, g, session["phone"], detail=True)
        finally:
            db.close()

    # ── Invite-link join ──────────────────────────────────────────────────────
    @app.get("/app/api/thrift/join/{token}")
    def join_info(token: str, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            link_group = db.query(ThriftGroup).filter(ThriftGroup.invite_token == token).first()
            if not link_group:
                raise HTTPException(status_code=404, detail="This group link is no longer valid.")
            tg.heal_group(db, link_group)
            # If already in the series, show that group; otherwise show the group
            # this link would route the viewer into (spillover-aware, no creation).
            mine = tg.member_in_series(db, link_group, session["phone"])
            if mine:
                g = db.query(ThriftGroup).filter(ThriftGroup.id == mine.group_id).first()
            elif link_group.spillover and (link_group.status != "active" or not tg.can_accept_members(db, link_group)[0]):
                g = tg.open_sibling(db, link_group) or link_group
            else:
                g = link_group
            admin = db.query(User).filter(User.phone == g.owner_phone).first()
            active = tg.active_members(db, g.id)
            accepting, reason = tg.can_accept_members(db, g)
            if g.status != "active":
                accepting, reason = False, "This ajo cycle has ended."
            # With spillover, a full group isn't really "closed" — a new one starts.
            spill_open = link_group.spillover and not (mine and mine.status)
            return {
                "id": g.id,
                "name": g.name,
                "group_type": getattr(g, "group_type", "rotating"),
                "contribution_amount": g.contribution_amount,
                "goal_amount": getattr(g, "goal_amount", None),
                "target_date": g.target_date.isoformat() if getattr(g, "target_date", None) else None,
                "frequency": g.frequency,
                "admin_name": (admin.name if admin else g.owner_phone),
                "member_count": len(active),
                "max_members": g.max_members,
                "require_approval": g.require_approval,
                "status": g.status,
                "spillover": link_group.spillover,
                "spilled": g.id != link_group.id,
                "accepting": (accepting and g.status == "active") or spill_open,
                "closed_reason": None if ((accepting and g.status == "active") or spill_open) else (reason or "This group is closed."),
                "my_status": mine.status if mine else None,
            }
        finally:
            db.close()

    @app.post("/app/api/thrift/join/{token}")
    def join_group(token: str, payload: JoinRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            g = db.query(ThriftGroup).filter(ThriftGroup.invite_token == token).first()
            if not g:
                raise HTTPException(status_code=404, detail="This group link is no longer valid.")
            me = _me(db, session)
            # Already in this group (or a sibling of a spillover series)? Pass through.
            existing = tg.member_in_series(db, g, me.phone)
            if existing:
                return {"ok": True, "group_id": existing.group_id, "status": existing.status, "already": True}
            # Route to the group that can actually take them (spillover picks the
            # next open sibling, or starts a new one when all are full).
            target = tg.resolve_join_target(db, g)
            ok, reason = tg.can_accept_members(db, target)
            if not ok or target.status != "active":
                raise HTTPException(status_code=400, detail=reason or "This group is no longer accepting members.")
            member, created = tg.join_via_link(db, target, me, payload.name)
            return {
                "ok": True,
                "group_id": target.id,
                "status": member.status,
                "already": not created,
            }
        finally:
            db.close()
