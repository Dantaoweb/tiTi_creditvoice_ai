"""
Partners & investors routes: list, invite, remove, accept, decline.

Split out of web_routes.py. Register with register_partner_routes(app);
shared helpers come from web_common.
"""
import secrets
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from models import User
from web_auth import require_web_auth, phone_candidates
from web_common import _iso


def _new_invite_token():
    return secrets.token_urlsafe(24)


def _mask_phone(phone):
    """Show only the last 4 digits so the invitee knows which number to use
    without exposing the full number to anyone holding the link."""
    p = str(phone or "")
    return ("•••• " + p[-4:]) if len(p) >= 4 else "••••"


def _phone_matches(target_phone, my_phone):
    """True when my_phone is the same number as target_phone, tolerant of the
    different stored formats (e.g. 0803… vs 234803…)."""
    if not target_phone or not my_phone:
        return False
    return target_phone in phone_candidates(my_phone) or my_phone in phone_candidates(target_phone)


class PartnerInviteRequest(BaseModel):
    partner_phone: str = Field(max_length=20)
    role: str = Field(default="partner", max_length=20)
    equity_percent: Optional[float] = None
    investment_amount: Optional[int] = None
    notes: Optional[str] = Field(default=None, max_length=1000)


def register_partner_routes(app):

    @app.get("/app/api/partners")
    def web_partners(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner = db.query(User).filter(User.phone == session["phone"]).first()
            if not owner:
                return {"partners": [], "as_partner": []}
            from models import BusinessPartner
            # Partners in MY business
            my_partners = db.query(BusinessPartner).filter(
                BusinessPartner.owner_phone == owner.phone
            ).all()
            # Backfill invite tokens for pending rows (incl. those created over
            # WhatsApp or before invite links existed) so every pending invite
            # has a copyable link.
            _dirty = False
            for p in my_partners:
                if p.status == "pending" and not p.invite_token:
                    p.invite_token = _new_invite_token()
                    _dirty = True
            if _dirty:
                db.commit()
            # Businesses I am a partner in (active + pending so they can accept).
            # Match both phone formats — the inviter may have stored my number in
            # a different format from the one on my account.
            my_roles = db.query(BusinessPartner).filter(
                BusinessPartner.partner_phone.in_(phone_candidates(owner.phone)),
                BusinessPartner.status.in_(["active", "pending"]),
            ).all()
            def _bp(p):
                pu = db.query(User).filter(User.phone == p.partner_phone).first()
                return {
                    "id": p.id,
                    "partner_phone": p.partner_phone,
                    "partner_name": pu.name if pu else p.partner_phone,
                    "role": p.role,
                    "access_level": p.access_level,
                    "equity_percent": p.equity_percent,
                    "investment_amount": p.investment_amount,
                    "status": p.status,
                    "invite_token": p.invite_token if p.status == "pending" else None,
                    "invited_at": _iso(p.invited_at),
                    "accepted_at": _iso(p.accepted_at),
                    "notes": p.notes,
                }
            def _role(p):
                biz_owner = db.query(User).filter(User.phone == p.owner_phone).first()
                return {
                    "id": p.id,
                    "owner_phone": p.owner_phone,
                    "business_name": (biz_owner.business_type_label or biz_owner.business_type or biz_owner.name) if biz_owner else p.owner_phone,
                    "owner_name": biz_owner.name if biz_owner else p.owner_phone,
                    "role": p.role,
                    "access_level": p.access_level,
                    "equity_percent": p.equity_percent,
                    "investment_amount": p.investment_amount,
                    "status": p.status,
                }
            return {
                "partners": [_bp(p) for p in my_partners],
                "as_partner": [_role(p) for p in my_roles],
            }
        finally:
            db.close()

    @app.post("/app/api/partners/invite")
    def web_partner_invite(payload: PartnerInviteRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            from models import BusinessPartner
            from partner_commands import ROLE_ACCESS, ROLE_LABELS, ACCESS_LABELS, _utcnow
            from parser import normalize_phone

            owner = db.query(User).filter(User.phone == session["phone"]).first()
            if not owner or owner.parent_id is not None:
                raise HTTPException(status_code=403, detail="Only business owners can invite partners.")

            partner_phone = normalize_phone(payload.partner_phone)
            if not partner_phone:
                raise HTTPException(status_code=400, detail="Invalid phone number.")
            if partner_phone == normalize_phone(owner.phone):
                raise HTTPException(status_code=400, detail="You cannot invite yourself.")

            role = payload.role if payload.role in ROLE_ACCESS else "partner"

            # Partners/investors are a Pro/Premium feature. Pro caps each bucket
            # at 1 (one partner AND one investor); Premium is unlimited.
            from subscriptions import (
                get_business_subscription, ensure_feature_allowed, check_partner_limit,
            )
            allowed, upgrade_msg = ensure_feature_allowed(db, owner, "PARTNERS", "Partners & investors")
            if not allowed:
                raise HTTPException(status_code=403, detail=upgrade_msg)
            subscription = get_business_subscription(db, owner)
            within, limit_msg = check_partner_limit(db, owner, subscription, role)
            if not within:
                raise HTTPException(status_code=403, detail=limit_msg)
            existing = db.query(BusinessPartner).filter(
                BusinessPartner.owner_phone == owner.phone,
                BusinessPartner.partner_phone == partner_phone,
            ).first()
            if existing and existing.status == "active":
                raise HTTPException(status_code=409, detail="This person is already an active partner.")
            if existing and existing.status == "pending":
                raise HTTPException(status_code=409, detail="An invitation is already pending for this person.")

            bp = BusinessPartner(
                owner_phone=owner.phone,
                partner_phone=partner_phone,
                role=role,
                access_level=ROLE_ACCESS[role],
                equity_percent=payload.equity_percent,
                investment_amount=payload.investment_amount,
                notes=payload.notes,
                status="pending",
                invite_token=_new_invite_token(),
                invited_at=_utcnow(),
            )
            db.add(bp)
            db.commit()
            db.refresh(bp)
            return {"ok": True, "id": bp.id, "status": "pending", "invite_token": bp.invite_token}
        finally:
            db.close()

    @app.delete("/app/api/partners/{partner_id}")
    def web_partner_remove(partner_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            from models import BusinessPartner
            owner = db.query(User).filter(User.phone == session["phone"]).first()
            bp = db.query(BusinessPartner).filter(
                BusinessPartner.id == partner_id,
                BusinessPartner.owner_phone == owner.phone,
            ).first()
            if not bp:
                raise HTTPException(status_code=404, detail="Partner not found.")
            from audit import audit
            audit(db, action="DELETE_PARTNER", actor_id=session["user_id"],
                  actor_phone=session["phone"], resource=f"partner:{partner_id}:{bp.partner_phone}")
            db.delete(bp)
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    @app.post("/app/api/partners/{partner_id}/accept")
    def web_partner_accept(partner_id: int, session: dict = Depends(require_web_auth)):
        """Partner accepts an invitation sent to their phone."""
        db = SessionLocal()
        try:
            from models import BusinessPartner
            from partner_commands import _utcnow
            me = db.query(User).filter(User.phone == session["phone"]).first()
            if not me:
                raise HTTPException(status_code=403, detail="Not found.")
            bp = db.query(BusinessPartner).filter(
                BusinessPartner.id == partner_id,
                BusinessPartner.partner_phone.in_(phone_candidates(me.phone)),
                BusinessPartner.status == "pending",
            ).first()
            if not bp:
                raise HTTPException(status_code=404, detail="Invitation not found or already actioned.")
            bp.status = "active"
            bp.accepted_at = _utcnow()
            db.commit()
            return {"ok": True, "status": "active"}
        finally:
            db.close()

    @app.post("/app/api/partners/{partner_id}/decline")
    def web_partner_decline(partner_id: int, session: dict = Depends(require_web_auth)):
        """Partner declines an invitation."""
        db = SessionLocal()
        try:
            from models import BusinessPartner
            me = db.query(User).filter(User.phone == session["phone"]).first()
            if not me:
                raise HTTPException(status_code=403, detail="Not found.")
            bp = db.query(BusinessPartner).filter(
                BusinessPartner.id == partner_id,
                BusinessPartner.partner_phone.in_(phone_candidates(me.phone)),
                BusinessPartner.status == "pending",
            ).first()
            if not bp:
                raise HTTPException(status_code=404, detail="Invitation not found or already actioned.")
            db.delete(bp)
            db.commit()
            return {"ok": True, "status": "declined"}
        finally:
            db.close()

    # ── Invite-link flow: open a shared token, then accept/decline ────────────
    @app.get("/app/api/partners/join/{token}")
    def web_partner_join_info(token: str, session: dict = Depends(require_web_auth)):
        """Details for an invite link so the invitee can review before accepting."""
        db = SessionLocal()
        try:
            from models import BusinessPartner
            from partner_commands import ROLE_LABELS, ACCESS_LABELS
            from business_templates import business_display_name
            bp = db.query(BusinessPartner).filter(
                BusinessPartner.invite_token == token
            ).first()
            if not bp:
                raise HTTPException(status_code=404, detail="This invitation link is no longer valid.")
            owner = db.query(User).filter(User.phone == bp.owner_phone).first()
            me = db.query(User).filter(User.phone == session["phone"]).first()
            return {
                "business_name": business_display_name(owner) if owner else bp.owner_phone,
                "owner_name": owner.name if owner else bp.owner_phone,
                "role": bp.role,
                "role_label": ROLE_LABELS.get(bp.role, bp.role),
                "access_level": bp.access_level,
                "access_label": ACCESS_LABELS.get(bp.access_level, bp.access_level),
                "equity_percent": bp.equity_percent,
                "investment_amount": bp.investment_amount,
                "status": bp.status,
                "is_own_invite": bool(me and me.phone == bp.owner_phone),
                "is_for_me": bool(me and _phone_matches(bp.partner_phone, me.phone)),
                "invited_phone_masked": _mask_phone(bp.partner_phone),
                "partner_id": bp.id,
            }
        finally:
            db.close()

    @app.post("/app/api/partners/join/{token}/accept")
    def web_partner_join_accept(token: str, session: dict = Depends(require_web_auth)):
        """Accept an invite link — only the account with the invited phone may."""
        db = SessionLocal()
        try:
            from models import BusinessPartner
            from partner_commands import _utcnow
            bp = db.query(BusinessPartner).filter(
                BusinessPartner.invite_token == token
            ).first()
            if not bp:
                raise HTTPException(status_code=404, detail="This invitation link is no longer valid.")
            me = db.query(User).filter(User.phone == session["phone"]).first()
            if not me:
                raise HTTPException(status_code=403, detail="Not found.")
            if me.phone == bp.owner_phone:
                raise HTTPException(status_code=400, detail="You cannot accept your own invitation.")
            # The link is locked to the invited number: only the account with the
            # phone the owner entered may accept it.
            if not _phone_matches(bp.partner_phone, me.phone):
                raise HTTPException(
                    status_code=403,
                    detail=(f"This invitation was sent to a different phone number "
                            f"({_mask_phone(bp.partner_phone)}). Please log in with that "
                            f"number to accept."),
                )
            if bp.status == "active":
                return {"ok": True, "status": "active", "id": bp.id, "already": True}
            bp.status = "active"
            bp.accepted_at = _utcnow()
            db.commit()
            return {"ok": True, "status": "active", "id": bp.id}
        finally:
            db.close()

    @app.post("/app/api/partners/join/{token}/decline")
    def web_partner_join_decline(token: str, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            from models import BusinessPartner
            bp = db.query(BusinessPartner).filter(
                BusinessPartner.invite_token == token,
                BusinessPartner.status == "pending",
            ).first()
            if not bp:
                raise HTTPException(status_code=404, detail="This invitation is no longer valid.")
            db.delete(bp)
            db.commit()
            return {"ok": True, "status": "declined"}
        finally:
            db.close()

    # ── Partner's scoped web view of a business they belong to ────────────────
    @app.get("/app/api/partners/overview/{partner_id}")
    def web_partner_overview(partner_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            from models import BusinessPartner
            from partner_commands import get_partner_overview
            me = db.query(User).filter(User.phone == session["phone"]).first()
            if not me:
                raise HTTPException(status_code=403, detail="Not found.")
            bp = db.query(BusinessPartner).filter(
                BusinessPartner.id == partner_id,
                BusinessPartner.partner_phone.in_(phone_candidates(me.phone)),
                BusinessPartner.status == "active",
            ).first()
            if not bp:
                raise HTTPException(status_code=404, detail="Not found.")
            return get_partner_overview(db, bp)
        finally:
            db.close()
