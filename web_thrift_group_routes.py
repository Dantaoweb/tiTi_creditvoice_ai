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
    contribution_amount: int
    frequency: Optional[str] = Field(default="weekly", max_length=20)
    require_approval: Optional[bool] = True
    max_members: Optional[int] = None


class GroupSettingsRequest(BaseModel):
    locked: Optional[bool] = None
    max_members: Optional[int] = None


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
        return g

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
            if payload.contribution_amount <= 0:
                raise HTTPException(status_code=400, detail="Contribution amount must be greater than zero.")
            dup = db.query(ThriftGroup).filter(
                ThriftGroup.owner_phone == session["phone"],
                ThriftGroup.name == name,
                ThriftGroup.status == "active",
            ).first()
            if dup:
                raise HTTPException(status_code=409, detail="You already have a group with that name.")
            if payload.max_members is not None and payload.max_members < 2:
                raise HTTPException(status_code=400, detail="A group needs room for at least 2 members.")
            g = tg.create_group(
                db, session["phone"], name, payload.contribution_amount,
                frequency=payload.frequency, admin_name=getattr(me, "name", None),
                require_approval=payload.require_approval,
                max_members=payload.max_members,
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
            _require(db, g, session["phone"], approve=True)
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
    def record_payout(group_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            g = _load_group(db, group_id)
            _require(db, g, session["phone"], approve=True)
            payout = tg.record_payout(db, g, recorded_by_phone=session["phone"])
            if not payout:
                raise HTTPException(status_code=400, detail="No member is due a payout this round.")
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
            g = db.query(ThriftGroup).filter(ThriftGroup.invite_token == token).first()
            if not g:
                raise HTTPException(status_code=404, detail="This group link is no longer valid.")
            admin = db.query(User).filter(User.phone == g.owner_phone).first()
            mine = tg.member_for_user(db, g.id, session["phone"])
            active = tg.active_members(db, g.id)
            accepting, reason = tg.can_accept_members(db, g)
            return {
                "id": g.id,
                "name": g.name,
                "contribution_amount": g.contribution_amount,
                "frequency": g.frequency,
                "admin_name": (admin.name if admin else g.owner_phone),
                "member_count": len(active),
                "max_members": g.max_members,
                "require_approval": g.require_approval,
                "status": g.status,
                "accepting": accepting and g.status == "active",
                "closed_reason": None if (accepting and g.status == "active") else (reason or "This group is closed."),
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
            if g.status != "active":
                raise HTTPException(status_code=400, detail="This group is no longer accepting members.")
            me = _me(db, session)
            # New joiners are gated by lock/cap; someone already in the group
            # (e.g. re-opening the link) always passes through.
            if not tg.member_for_user(db, g.id, me.phone):
                ok, reason = tg.can_accept_members(db, g)
                if not ok:
                    raise HTTPException(status_code=400, detail=reason)
            member, created = tg.join_via_link(db, g, me, payload.name)
            return {
                "ok": True,
                "group_id": g.id,
                "status": member.status,
                "already": not created,
            }
        finally:
            db.close()
