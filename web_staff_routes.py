"""
Staff routes: performance, roster/members, invite, resend-invite, accept, and
staff profiles (position/level/salary), access level, session revocation, branch
assignment.

Split out of web_routes.py. Register with register_staff_routes(app); shared
helpers come from web_common. Most endpoints are owner-only.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from database import SessionLocal
from models import User, Branch
from reports import get_staff_performance
from subscriptions import get_business_subscription
from web_auth import require_web_auth, set_auth_cookie
from web_common import _session_owner_phone, _session_user


class StaffInviteRequest(BaseModel):
    name: str = Field(max_length=120)
    phone: str = Field(max_length=20)
    email: Optional[str] = Field(default=None, max_length=254)
    branch_id: Optional[int] = None          # pre-assign to this branch on accept
    as_branch_admin: bool = False            # grant "see all branch records" (needs a branch)


class StaffAcceptRequest(BaseModel):
    phone: str = Field(max_length=20)
    code: str = Field(max_length=10)
    new_pin: Optional[str] = Field(default=None, max_length=12)  # first-time staff set their PIN here


def register_staff_routes(app):

    # ── Staff performance ──────────────────────────────────────────────────
    @app.get("/app/api/staff")
    def web_staff(
        period: Optional[str] = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            period_key = period.upper() if period else None
            staff_data = get_staff_performance(db, owner_phone, period_key)
            return {"staff": staff_data or []}
        finally:
            db.close()

    @app.get("/app/api/staff/members")
    def web_staff_members(session: dict = Depends(require_web_auth)):
        """Return all staff (active + pending) for the authenticated owner."""
        db = SessionLocal()
        try:
            owner = db.query(User).filter(User.phone == session["phone"]).first()
            if not owner or owner.parent_id is not None:   # any top-level owner
                return {"members": []}
            members = db.query(User).filter(User.parent_id == owner.id).all()
            branch_names = {b.id: b.name for b in db.query(Branch).filter(Branch.owner_phone == owner.phone).all()}
            return {
                "members": [
                    {
                        "id": m.id,
                        "name": m.name,
                        "phone": m.phone,
                        "email": m.email,
                        "role": m.role,
                        "pending": m.role == "delegate_pending",
                        "full_access": bool(m.can_view_all_transactions),
                        "branch_id": m.branch_id,
                        "branch_name": branch_names.get(m.branch_id),
                        "invite_expires_at": m.invite_expires_at.isoformat() if m.invite_expires_at else None,
                    }
                    for m in members
                ]
            }
        finally:
            db.close()

    @app.post("/app/api/staff/invite")
    def web_staff_invite(payload: StaffInviteRequest, session: dict = Depends(require_web_auth)):
        """Owner invites a staff member by phone (and optionally email)."""
        from email_service import send_staff_invite_email, is_email_configured
        from staff_commands import _generate_invite_code
        from subscriptions import check_staff_limit, ensure_feature_allowed

        db = SessionLocal()
        try:
            owner = db.query(User).filter(User.phone == session["phone"]).first()
            # A business owner is any top-level account (no parent). Staff /
            # sub-accounts have parent_id set. The previous role == "user" check
            # wrongly rejected web-registered owners, whose role is "owner".
            if not owner or owner.parent_id is not None:
                raise HTTPException(status_code=403, detail="Only business owners can invite staff.")

            subscription = get_business_subscription(db, owner)
            allowed, upgrade_msg = ensure_feature_allowed(db, owner, "STAFF", "Staff management")
            if not allowed:
                raise HTTPException(status_code=403, detail=upgrade_msg)

            staff_allowed, staff_limit_msg = check_staff_limit(db, owner, subscription)
            if not staff_allowed:
                raise HTTPException(status_code=403, detail=staff_limit_msg)

            from parser import normalize_phone
            from web_auth import user_by_phone
            # Store the staff phone canonically so the number the owner typed and
            # the number the staff types on accept/login resolve to one account.
            staff_phone = normalize_phone(payload.phone) or payload.phone.strip()
            staff_name = payload.name.strip()
            staff_email = (payload.email or "").strip() or None

            # Optional: pre-assign a branch (and, if asked, branch-admin access).
            # Branch admin only takes effect with a branch, so require one.
            branch_id = payload.branch_id
            if branch_id is not None:
                branch = db.query(Branch).filter(
                    Branch.id == branch_id, Branch.owner_phone == owner.phone
                ).first()
                if not branch:
                    raise HTTPException(status_code=404, detail="Branch not found.")
            as_admin = bool(payload.as_branch_admin and branch_id is not None)

            staff_user = user_by_phone(db, payload.phone)
            if staff_user:
                staff_user.role = "delegate_pending"
                staff_user.parent_id = owner.id
                staff_user.name = staff_name
                if staff_email:
                    staff_user.email = staff_email
                staff_user.branch_id = branch_id
                staff_user.can_view_all_transactions = as_admin
            else:
                staff_user = User(
                    phone=staff_phone,
                    name=staff_name,
                    email=staff_email,
                    role="delegate_pending",
                    parent_id=owner.id,
                    branch_id=branch_id,
                    can_view_all_transactions=as_admin,
                )
                db.add(staff_user)

            invite_code = _generate_invite_code()
            from datetime import timezone as _tz
            staff_user.invite_code = invite_code
            staff_user.invite_code_attempts = 0
            staff_user.invite_expires_at = datetime.now(_tz.utc).replace(tzinfo=None) + timedelta(hours=24)
            db.commit()

            emailed = False
            email_hint = None
            if staff_email and is_email_configured():
                business_name = owner.business_type_label or owner.name
                emailed = send_staff_invite_email(staff_email, staff_name, owner.name, business_name)
                if emailed:
                    from email_service import mask_email
                    email_hint = mask_email(staff_email)

            return {
                "ok": True,
                "invite_code": invite_code,
                "emailed": emailed,
                "email_hint": email_hint,
            }
        finally:
            db.close()

    @app.post("/app/api/staff/{user_id}/resend-invite")
    def web_resend_staff_invite(user_id: str, session: dict = Depends(require_web_auth)):
        """Reissue the invite code for a pending staff member (owner-only), so an
        expired or lost code can be regenerated without re-entering their details."""
        from staff_commands import _generate_invite_code
        db = SessionLocal()
        try:
            owner = _session_user(db, session)
            if not owner or owner.parent_id is not None:
                raise HTTPException(status_code=403, detail="Only business owners can resend invitations.")
            member = db.query(User).filter(
                User.id == user_id, User.parent_id == owner.id, User.role == "delegate_pending",
            ).first()
            if not member:
                raise HTTPException(status_code=404, detail="No pending invitation for this staff member.")
            from datetime import timezone as _tz
            code = _generate_invite_code()
            member.invite_code = code
            member.invite_code_attempts = 0
            member.invite_expires_at = datetime.now(_tz.utc).replace(tzinfo=None) + timedelta(hours=24)
            db.commit()

            emailed, email_hint = False, None
            if member.email:
                from email_service import send_staff_invite_email, is_email_configured, mask_email
                if is_email_configured():
                    business_name = owner.business_type_label or owner.name
                    emailed = send_staff_invite_email(member.email, member.name, owner.name, business_name)
                    if emailed:
                        email_hint = mask_email(member.email)
            return {"ok": True, "invite_code": code, "phone": member.phone, "name": member.name,
                    "emailed": emailed, "email_hint": email_hint}
        finally:
            db.close()

    @app.post("/app/api/staff/accept")
    def web_staff_accept(payload: StaffAcceptRequest, response: Response):
        """Staff member accepts an invitation using their phone + the code the owner shared.
        They may set their PIN in the same step (see below)."""
        from datetime import timezone as _tz
        MAX_ATTEMPTS = 3

        db = SessionLocal()
        try:
            from web_auth import user_by_phone
            phone = payload.phone.strip()
            code = payload.code.strip()

            # Tolerant of local vs international format — the owner may have typed
            # the number differently from how the staff enters it here.
            staff_user = user_by_phone(db, phone)
            if not staff_user or staff_user.role != "delegate_pending":
                raise HTTPException(status_code=404, detail="No pending invitation found for this phone number.")

            # Expired — invalidate the old code but keep them pending in the
            # owner's roster (do NOT wipe parent_id/role) so the owner can just
            # hit "Resend invite" instead of the staff vanishing entirely.
            if staff_user.invite_expires_at and staff_user.invite_expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
                staff_user.invite_code = None
                db.commit()
                raise HTTPException(status_code=410, detail="This invitation has expired. Ask the owner to resend it.")

            # Too many attempts — burn the code but stay pending so the owner can
            # resend a fresh one (which resets the attempt count).
            attempts = staff_user.invite_code_attempts or 0
            if attempts >= MAX_ATTEMPTS:
                staff_user.invite_code = None
                staff_user.invite_code_attempts = 0
                db.commit()
                raise HTTPException(status_code=429, detail="Too many wrong attempts. Ask the owner to resend the invitation.")

            # Wrong code
            if not staff_user.invite_code or code != staff_user.invite_code:
                staff_user.invite_code_attempts = attempts + 1
                remaining = MAX_ATTEMPTS - staff_user.invite_code_attempts
                db.commit()
                raise HTTPException(status_code=400, detail=f"Wrong code. {remaining} attempt(s) remaining.")

            # Accept
            had_pin = bool(staff_user.recovery_pin_hash)
            staff_user.role = "delegate"
            staff_user.invite_code = None
            staff_user.invite_code_attempts = 0
            staff_user.invite_expires_at = None

            # Let a first-time staff set their PIN right here, proven by the
            # invite code (single-use, 24h, attempt-limited — already a strong
            # secret from the owner). Otherwise they can be stranded: the OTP
            # fallback needs WhatsApp's 24-hour window, which a brand-new staff
            # has never opened, or an email on file — and the invite code has
            # just been consumed, so there is no second route in.
            if payload.new_pin and not had_pin:
                pin = payload.new_pin.strip()
                if len(pin) < 4 or not pin.isdigit():
                    raise HTTPException(status_code=400, detail="PIN must be at least 4 digits.")
                from web_auth import _hash_pin
                staff_user.recovery_pin_hash = _hash_pin(pin)
                staff_user.pin_attempts = 0
                staff_user.pin_locked_until = None
                db.commit()
                # Sign them straight in — no OTP round trip needed.
                from web_auth import _build_auth_response
                result = _build_auth_response(staff_user, db=db)
                set_auth_cookie(response, result.pop("_token"))
                return {**result, "ok": True, "has_pin": True, "signed_in": True}

            db.commit()
            return {"ok": True, "name": staff_user.name, "has_pin": had_pin, "signed_in": False}
        finally:
            db.close()

    # ── Staff profiles ────────────────────────────────────────────────────────

    @app.get("/app/api/staff/profiles")
    def web_staff_profiles(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner = db.query(User).filter(User.phone == session["phone"]).first()
            if not owner or owner.parent_id is not None:
                return {"profiles": []}
            members = db.query(User).filter(User.parent_id == owner.id).all()
            return {
                "profiles": [
                    {
                        "id": m.id,
                        "name": m.name,
                        "phone": m.phone,
                        "role": m.role,
                        "staff_position": m.staff_position,
                        "staff_level": m.staff_level,
                        "staff_salary": m.staff_salary,
                        "staff_matric": m.staff_matric,
                    }
                    for m in members if m.role != "delegate_pending"
                ]
            }
        finally:
            db.close()

    class StaffProfileUpdateRequest(BaseModel):
        staff_position: Optional[str] = Field(default=None, max_length=60)
        staff_level: Optional[str] = Field(default=None, max_length=60)
        staff_salary: Optional[int] = None
        staff_matric: Optional[str] = Field(default=None, max_length=60)

    @app.put("/app/api/staff/{user_id}/profile")
    def web_update_staff_profile(
        user_id: str,
        payload: StaffProfileUpdateRequest,
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            owner = db.query(User).filter(User.phone == session["phone"]).first()
            if not owner or owner.parent_id is not None:
                raise HTTPException(status_code=403, detail="Only business owners can update staff profiles.")
            member = db.query(User).filter(User.id == user_id, User.parent_id == owner.id).first()
            if not member:
                raise HTTPException(status_code=404, detail="Staff member not found.")
            if payload.staff_position is not None:
                member.staff_position = payload.staff_position.strip() or None
            if payload.staff_level is not None:
                member.staff_level = payload.staff_level.strip() or None
            if payload.staff_salary is not None:
                member.staff_salary = payload.staff_salary or None
            if payload.staff_matric is not None:
                member.staff_matric = payload.staff_matric.strip().upper() or None
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    class StaffAccessRequest(BaseModel):
        full_access: bool

    @app.post("/app/api/staff/{user_id}/access")
    def web_set_staff_access(
        user_id: str,
        payload: StaffAccessRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Grant or revoke a staff member full access (see all business records,
        not just their own) — the app's "admin"-level staff permission."""
        from subscriptions import ensure_feature_allowed
        db = SessionLocal()
        try:
            owner = db.query(User).filter(User.phone == session["phone"]).first()
            if not owner or owner.parent_id is not None:
                raise HTTPException(status_code=403, detail="Only business owners can change staff access.")
            allowed, upgrade_msg = ensure_feature_allowed(db, owner, "STAFF_PERMISSION", "Staff permissions")
            if not allowed:
                raise HTTPException(status_code=403, detail=upgrade_msg)
            member = db.query(User).filter(User.id == user_id, User.parent_id == owner.id).first()
            if not member:
                raise HTTPException(status_code=404, detail="Staff member not found.")
            member.can_view_all_transactions = bool(payload.full_access)
            db.commit()
            return {"ok": True, "full_access": bool(member.can_view_all_transactions)}
        finally:
            db.close()

    @app.post("/app/api/staff/{user_id}/revoke-sessions")
    def web_revoke_staff_sessions(user_id: str, session: dict = Depends(require_web_auth)):
        """Owner signs a staff member out of all their devices (e.g. after they
        leave) by bumping that staff's session epoch."""
        db = SessionLocal()
        try:
            owner = db.query(User).filter(User.phone == session["phone"]).first()
            if not owner or owner.parent_id is not None:
                raise HTTPException(status_code=403, detail="Only business owners can revoke staff access.")
            member = db.query(User).filter(User.id == user_id, User.parent_id == owner.id).first()
            if not member:
                raise HTTPException(status_code=404, detail="Staff member not found.")
            member.token_version = (member.token_version or 0) + 1
            db.commit()
            return {"ok": True, "message": "Staff signed out of all devices."}
        finally:
            db.close()

    class StaffBranchRequest(BaseModel):
        branch_id: Optional[int] = None

    @app.post("/app/api/staff/{user_id}/branch")
    def web_set_staff_branch(
        user_id: str,
        payload: StaffBranchRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Assign a staff member to a branch (or clear it with null). Their
        recorded transactions are then tagged to that branch."""
        db = SessionLocal()
        try:
            owner = db.query(User).filter(User.phone == session["phone"]).first()
            if not owner or owner.parent_id is not None:
                raise HTTPException(status_code=403, detail="Only business owners can assign staff to branches.")
            member = db.query(User).filter(User.id == user_id, User.parent_id == owner.id).first()
            if not member:
                raise HTTPException(status_code=404, detail="Staff member not found.")
            if payload.branch_id is not None:
                branch = db.query(Branch).filter(
                    Branch.id == payload.branch_id, Branch.owner_phone == owner.phone
                ).first()
                if not branch:
                    raise HTTPException(status_code=404, detail="Branch not found.")
            member.branch_id = payload.branch_id
            db.commit()
            return {"ok": True, "branch_id": member.branch_id}
        finally:
            db.close()
