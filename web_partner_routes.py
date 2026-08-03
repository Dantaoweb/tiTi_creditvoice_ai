"""
Partners & investors routes: list, invite, remove, accept, decline.

Split out of web_routes.py. Register with register_partner_routes(app);
shared helpers come from web_common.
"""
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from models import User
from web_auth import require_web_auth, phone_candidates
from web_common import _iso


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
                invited_at=_utcnow(),
            )
            db.add(bp)
            db.commit()
            db.refresh(bp)
            return {"ok": True, "id": bp.id, "status": "pending"}
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
