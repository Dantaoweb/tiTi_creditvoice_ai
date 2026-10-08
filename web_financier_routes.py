"""
The financier portal: /financier.

A financier's own staff sign in here and work their queue — the applications
sent to them, the frozen evidence, and the stages of their own deal. They are
not CreditVoice businesses and they are not a user's business partner; they see
only their own applications, never CreditVoice's commission, another financier's
work, or any business's customer list.

Register with register_financier_routes(app).
"""
import json
from typing import Optional

from fastapi import Depends, HTTPException, Response
from pydantic import BaseModel, Field

from database import SessionLocal
from financier_auth import (
    clear_cookie, create_token, generate_invite_code, invite_expiry,
    load_financier, require_financier, set_cookie,
)
from models import AuditLog, FinanceApplication, FinancePartner, FinancierUser, User, utcnow
from recovery_commands import _hash_pin, _verify_pin
from web_auth import _rate_check, require_web_auth
from web_common import _admin_rate_check

# A financier drives its own deal, but cannot invent one or unwind history: the
# application is created by the business, and delivery is where our fee lands.
_FINANCIER_TRANSITIONS = {
    "SHARED":    {"IN_REVIEW", "APPROVED", "DECLINED"},
    "IN_REVIEW": {"APPROVED", "DECLINED"},
    "APPROVED":  {"DELIVERED", "DECLINED"},
}
_MAX_INVITE_ATTEMPTS = 5


class CreateFinancierUserRequest(BaseModel):
    finance_partner_id: str = Field(max_length=64)
    name: str = Field(max_length=120)
    phone: str = Field(max_length=30)
    email: Optional[str] = Field(default=None, max_length=200)


class AcceptInviteRequest(BaseModel):
    code: str = Field(max_length=32)
    pin: str = Field(min_length=4, max_length=12)


class FinancierLoginRequest(BaseModel):
    phone: str = Field(max_length=30)
    pin: str = Field(max_length=12)


class FinancierUpdateRequest(BaseModel):
    status: Optional[str] = Field(default=None, max_length=20)
    asset_value: Optional[int] = None
    partner_ref: Optional[str] = Field(default=None, max_length=120)
    decline_reason: Optional[str] = Field(default=None, max_length=300)


class ConfirmRequest(BaseModel):
    installment_no: Optional[int] = None


def _user_dict(u, partner=None):
    return {
        "id": u.id,
        "name": u.name,
        "phone": u.phone,
        "email": u.email,
        "financier_id": u.finance_partner_id,
        "financier_name": partner.name if partner else None,
        "is_active": bool(u.is_active),
        "accepted": bool(u.pin_hash),
        "invite_code": u.invite_code if not u.pin_hash else None,
        "invite_expires_at": u.invite_expires_at.isoformat() if u.invite_expires_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


def register_financier_routes(app):

    def _require_admin(db, session):
        from admin import is_app_admin
        user = db.query(User).filter(User.id == session["user_id"]).first()
        if not user or not is_app_admin(user.phone, db):
            raise HTTPException(status_code=403, detail="Admin only")
        if not _admin_rate_check(user.phone):
            raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")
        return user

    def _audit(db, actor_id, actor_phone, action, resource):
        db.add(AuditLog(actor_id=actor_id, actor_phone=actor_phone,
                        action=action, resource=resource))

    # ── Admin: create and manage financier logins ─────────────────────────
    @app.get("/app/api/admin/financier-users")
    def admin_list_financier_users(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_admin(db, session)
            rows = (
                db.query(FinancierUser, FinancePartner)
                .outerjoin(FinancePartner, FinancierUser.finance_partner_id == FinancePartner.id)
                .order_by(FinancierUser.created_at.desc()).all()
            )
            return {"users": [_user_dict(u, p) for u, p in rows]}
        finally:
            db.close()

    @app.post("/app/api/admin/financier-users")
    def admin_create_financier_user(payload: CreateFinancierUserRequest,
                                    session: dict = Depends(require_web_auth)):
        """Create a login for a financier's staff and hand back a one-time code
        they exchange for their own PIN."""
        from parser import normalize_phone
        db = SessionLocal()
        try:
            actor = _require_admin(db, session)
            partner = db.query(FinancePartner).filter(
                FinancePartner.id == payload.finance_partner_id).first()
            if not partner:
                raise HTTPException(status_code=404, detail="Financier not found.")
            phone = normalize_phone(payload.phone) or payload.phone.strip()
            if not phone:
                raise HTTPException(status_code=400, detail="A phone number is required.")
            if db.query(FinancierUser).filter(FinancierUser.phone == phone).first():
                raise HTTPException(status_code=409, detail="That phone already has a financier login.")
            # A financier's staff must not also be a business on this phone —
            # one phone, one identity, or sessions get confusing fast.
            if db.query(User).filter(User.phone == phone).first():
                raise HTTPException(
                    status_code=409,
                    detail="That phone is already a CreditVoice business account. Use a different number.",
                )
            row = FinancierUser(
                finance_partner_id=partner.id,
                name=payload.name.strip(),
                phone=phone,
                email=(payload.email or "").strip() or None,
                invite_code=generate_invite_code(),
                invite_expires_at=invite_expiry(),
                created_by=actor.phone,
            )
            db.add(row)
            _audit(db, actor.id, actor.phone, "ADMIN_SETTINGS_CHANGE",
                   f"financier_user:create:{partner.name}:{phone}")
            db.commit()
            db.refresh(row)
            return {**_user_dict(row, partner), "portal_url": "/financier"}
        finally:
            db.close()

    @app.post("/app/api/admin/financier-users/{user_id}/reinvite")
    def admin_reinvite(user_id: str, session: dict = Depends(require_web_auth)):
        """Fresh code — for a lost invite, or to reset a forgotten PIN."""
        db = SessionLocal()
        try:
            actor = _require_admin(db, session)
            row = db.query(FinancierUser).filter(FinancierUser.id == user_id).first()
            if not row:
                raise HTTPException(status_code=404, detail="Login not found.")
            row.invite_code = generate_invite_code()
            row.invite_expires_at = invite_expiry()
            row.invite_attempts = 0
            row.pin_hash = None                     # they set a new PIN with the code
            row.token_version = int(row.token_version or 0) + 1   # log out old sessions
            _audit(db, actor.id, actor.phone, "ADMIN_SETTINGS_CHANGE", f"financier_user:reinvite:{row.phone}")
            db.commit()
            db.refresh(row)
            return _user_dict(row)
        finally:
            db.close()

    @app.post("/app/api/admin/financier-users/{user_id}/deactivate")
    def admin_deactivate(user_id: str, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            actor = _require_admin(db, session)
            row = db.query(FinancierUser).filter(FinancierUser.id == user_id).first()
            if not row:
                raise HTTPException(status_code=404, detail="Login not found.")
            row.is_active = False
            row.token_version = int(row.token_version or 0) + 1   # kill live sessions now
            _audit(db, actor.id, actor.phone, "ADMIN_SETTINGS_CHANGE", f"financier_user:deactivate:{row.phone}")
            db.commit()
            return {"deactivated": True}
        finally:
            db.close()

    # ── Portal: accept invite, sign in, sign out ──────────────────────────
    @app.post("/app/api/financier/accept-invite")
    def financier_accept_invite(payload: AcceptInviteRequest, response: Response):
        db = SessionLocal()
        try:
            code = payload.code.strip().upper()
            if not _rate_check(f"fin-invite:{code}", 10, 3600):
                raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
            row = db.query(FinancierUser).filter(FinancierUser.invite_code == code).first()
            invalid = HTTPException(status_code=400, detail="Invalid or expired invite code.")
            if not row or not row.is_active:
                raise invalid
            if row.invite_expires_at and row.invite_expires_at < utcnow():
                raise invalid
            if int(row.invite_attempts or 0) >= _MAX_INVITE_ATTEMPTS:
                raise invalid
            pin = payload.pin.strip()
            if not pin.isdigit() or len(pin) < 4:
                raise HTTPException(status_code=400, detail="Choose a PIN of at least 4 digits.")

            row.pin_hash = _hash_pin(pin)
            row.invite_code = None
            row.invite_expires_at = None
            row.invite_attempts = 0
            row.last_login_at = utcnow()
            db.commit()
            db.refresh(row)
            _user, partner = load_financier(db, {"user_id": row.id, "ver": row.token_version})
            set_cookie(response, create_token(row.id, partner.id, token_version=row.token_version))
            return {"ok": True, "name": row.name, "financier_name": partner.name}
        finally:
            db.close()

    @app.post("/app/api/financier/login")
    def financier_login(payload: FinancierLoginRequest, response: Response):
        from parser import normalize_phone
        db = SessionLocal()
        try:
            phone = normalize_phone(payload.phone) or payload.phone.strip()
            if not _rate_check(f"fin-login:{phone}", 10, 900):
                raise HTTPException(status_code=429, detail="Too many attempts. Try again in 15 minutes.")
            row = db.query(FinancierUser).filter(FinancierUser.phone == phone).first()
            # One message for every failure — no hints about which part was wrong.
            wrong = HTTPException(status_code=401, detail="Wrong phone number or PIN.")
            if not row or not row.is_active or not row.pin_hash:
                raise wrong
            if not _verify_pin(payload.pin.strip(), row.pin_hash):
                raise wrong
            partner = db.query(FinancePartner).filter(
                FinancePartner.id == row.finance_partner_id).first()
            if not partner:
                raise wrong
            row.last_login_at = utcnow()
            db.commit()
            set_cookie(response, create_token(row.id, partner.id, token_version=row.token_version))
            return {"ok": True, "name": row.name, "financier_name": partner.name}
        finally:
            db.close()

    @app.post("/app/api/financier/logout")
    def financier_logout(response: Response):
        clear_cookie(response)
        return {"ok": True}

    @app.get("/app/api/financier/me")
    def financier_me(session: dict = Depends(require_financier)):
        db = SessionLocal()
        try:
            user, partner = load_financier(db, session)
            return {
                "name": user.name,
                "financier_name": partner.name,
                "asset_types": json.loads(partner.asset_types or "[]"),
            }
        finally:
            db.close()

    # ── Portal: their own queue ───────────────────────────────────────────
    def _row_dict(a, full=False):
        """What a financier may see. Deliberately excludes CreditVoice's
        commission, and hides the applicant's phone until they have approved —
        so a browsing financier cannot harvest contacts."""
        out = {
            "id": a.id,
            "application_code": a.application_code,
            "business_name": a.business_name,
            "asset_requested": a.asset_requested,
            "asset_value": a.asset_value,
            "status": a.status,
            "score": a.snapshot_score,
            "tier": a.snapshot_tier,
            "confidence": a.snapshot_confidence,
            "partner_ref": a.partner_ref,
            "decline_reason": a.decline_reason,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "approved_at": a.approved_at.isoformat() if a.approved_at else None,
            "delivered_at": a.delivered_at.isoformat() if a.delivered_at else None,
            "next_statuses": sorted(_FINANCIER_TRANSITIONS.get(a.status, set())),
        }
        if full:
            out["note"] = a.note
            try:
                out["snapshot"] = json.loads(a.snapshot_json or "{}")
            except (ValueError, TypeError):
                out["snapshot"] = {}
            try:
                kyc = json.loads(a.kyc_json or "null")
            except (ValueError, TypeError):
                kyc = None
            if kyc and a.status not in ("APPROVED", "DELIVERED"):
                kyc = {k: v for k, v in kyc.items() if k != "id_number"}
            out["kyc"] = kyc
            out["contact_phone"] = a.contact_phone if a.status in ("APPROVED", "DELIVERED") else None
        return out

    def _their_application(db, partner, application_id):
        row = db.query(FinanceApplication).filter(
            FinanceApplication.id == application_id,
            FinanceApplication.partner_id == partner.id,
        ).first()
        # 404 rather than 403: another financier's application should not even
        # be confirmed to exist.
        if not row:
            raise HTTPException(status_code=404, detail="Application not found.")
        return row

    @app.get("/app/api/financier/applications")
    def financier_applications(session: dict = Depends(require_financier), status: str = ""):
        db = SessionLocal()
        try:
            _user, partner = load_financier(db, session)
            q = db.query(FinanceApplication).filter(
                FinanceApplication.partner_id == partner.id,
                # Nothing is visible until CreditVoice has shared it.
                FinanceApplication.status != "SUBMITTED",
            )
            if status:
                q = q.filter(FinanceApplication.status == status.upper())
            rows = q.order_by(FinanceApplication.created_at.desc()).limit(300).all()
            counts = {}
            for r in rows:
                counts[r.status] = counts.get(r.status, 0) + 1
            return {"applications": [_row_dict(r) for r in rows], "counts": counts}
        finally:
            db.close()

    @app.get("/app/api/financier/applications/{application_id}")
    def financier_application_detail(application_id: str,
                                     session: dict = Depends(require_financier)):
        db = SessionLocal()
        try:
            _user, partner = load_financier(db, session)
            row = _their_application(db, partner, application_id)
            if row.status == "SUBMITTED":
                raise HTTPException(status_code=404, detail="Application not found.")
            out = _row_dict(row, full=True)
            from finance_installments import schedule_summary
            out["schedule"] = schedule_summary(db, row.id)
            return out
        finally:
            db.close()

    @app.patch("/app/api/financier/applications/{application_id}")
    def financier_update_application(application_id: str, payload: FinancierUpdateRequest,
                                     session: dict = Depends(require_financier)):
        """The financier drives their own deal: reviewing, approved, declined
        with a reason, delivered — plus the asset value and their reference."""
        db = SessionLocal()
        try:
            user, partner = load_financier(db, session)
            row = _their_application(db, partner, application_id)
            now = utcnow()

            if payload.asset_value is not None:
                if payload.asset_value < 0:
                    raise HTTPException(status_code=400, detail="Asset value cannot be negative.")
                row.asset_value = payload.asset_value
            if payload.partner_ref is not None:
                row.partner_ref = payload.partner_ref.strip() or None
            if payload.decline_reason is not None:
                row.decline_reason = payload.decline_reason.strip() or None

            old_status = row.status
            if payload.status:
                new = payload.status.upper()
                allowed = _FINANCIER_TRANSITIONS.get(row.status, set())
                if new != row.status and new not in allowed:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot move from {row.status} to {new}. "
                               f"Allowed: {', '.join(sorted(allowed)) or 'none'}.",
                    )
                if new == "DECLINED" and not (row.decline_reason or "").strip():
                    raise HTTPException(status_code=400, detail="Give a reason when declining.")
                row.status = new
                if new == "APPROVED":
                    row.approved_at = row.approved_at or now
                if new == "DELIVERED":
                    row.delivered_at = row.delivered_at or now
                    # Our fee follows the financier's own action, not a phone call.
                    if row.commission_status == "PENDING":
                        from web_finance_routes import calculate_commission
                        amount, _reason = calculate_commission(partner, row)
                        if amount is not None and partner.commission_due_on == "ON_DELIVERY":
                            row.commission_amount = amount
                            row.commission_status = "DUE"
                            row.commission_marked_at = now

            row.updated_at = now
            _audit(db, user.id, user.phone, "FINANCIER_UPDATE",
                   f"application:{row.id}:{row.status}")
            db.commit()
            db.refresh(row)
            from finance_alerts import after_stage_change
            after_stage_change(db, row, partner, old_status, moved_by="financier")
            return _row_dict(row, full=True)
        finally:
            db.close()

    @app.post("/app/api/financier/applications/{application_id}/confirm-repayment")
    def financier_confirm_repayment(application_id: str, payload: ConfirmRequest,
                                    session: dict = Depends(require_financier)):
        """The financier confirms money they received — which is what turns a
        business's claimed repayment into verified evidence."""
        from finance_installments import PARTNER_CONFIRMED, confirm_repayments, schedule_summary
        db = SessionLocal()
        try:
            user, partner = load_financier(db, session)
            row = _their_application(db, partner, application_id)
            confirmed = confirm_repayments(db, row, payload.installment_no,
                                           PARTNER_CONFIRMED, confirmed_by=f"{partner.name}:{user.name}")
            _audit(db, user.id, user.phone, "FINANCIER_CONFIRM_REPAYMENT", f"application:{row.id}")
            db.commit()
            return {"confirmed": confirmed, "schedule": schedule_summary(db, row.id)}
        finally:
            db.close()
