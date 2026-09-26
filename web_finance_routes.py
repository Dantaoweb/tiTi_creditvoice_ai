"""
Finance-partner routes: the admin-editable partner directory and scorecard
rules, the business's own scorecard, and the offers it qualifies for.

CreditVoice introduces businesses to installment / asset-finance partners and is
paid per closed deal. It lends nothing and carries no credit risk — the partner
underwrites. These endpoints expose EVIDENCE about a business's trading record.

Register with register_finance_routes(app). Admin endpoints are app-admin only.
"""
import json
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from models import FinancePartner, FinanceApplication, ScorecardConfig, User, utcnow
from web_auth import require_web_auth
from web_common import _admin_rate_check, _session_owner_phone


class PartnerRequest(BaseModel):
    name: str = Field(max_length=120)
    contact_name: Optional[str] = Field(default=None, max_length=120)
    contact_phone: Optional[str] = Field(default=None, max_length=30)
    contact_email: Optional[str] = Field(default=None, max_length=200)
    logo_url: Optional[str] = Field(default=None, max_length=500)
    asset_types: list[str] = Field(default_factory=list)
    asset_value_min: Optional[int] = None
    asset_value_max: Optional[int] = None
    eligibility: dict = Field(default_factory=dict)
    commission_type: str = Field(default="PERCENT_OF_ASSET", max_length=32)
    commission_value: int = 0
    commission_due_on: str = Field(default="ON_DELIVERY", max_length=32)
    notes: Optional[str] = Field(default=None, max_length=2000)
    is_active: bool = True


class ScorecardConfigRequest(BaseModel):
    config: dict
    note: Optional[str] = Field(default=None, max_length=300)


class ApplicationUpdateRequest(BaseModel):
    status: Optional[str] = Field(default=None, max_length=20)
    asset_value: Optional[int] = None          # as finally quoted by the partner
    partner_ref: Optional[str] = Field(default=None, max_length=120)
    decline_reason: Optional[str] = Field(default=None, max_length=300)
    admin_notes: Optional[str] = Field(default=None, max_length=2000)


class CommissionRequest(BaseModel):
    status: str = Field(max_length=20)         # DUE | INVOICED | PAID | PENDING
    amount: Optional[int] = None               # override the calculated figure


class ApplyRequest(BaseModel):
    # Consent is explicit and per partner: sharing a business's trading record
    # is the owner's decision, not a side effect of tapping "apply".
    consent: bool = False
    asset_requested: Optional[str] = Field(default=None, max_length=120)
    asset_value: Optional[int] = None
    note: Optional[str] = Field(default=None, max_length=1000)


_COMMISSION_TYPES = {"FLAT_PER_DEAL", "PERCENT_OF_ASSET", "PERCENT_OF_REPAYMENTS"}
_COMMISSION_DUE = {"ON_DELIVERY", "ON_FIRST_REPAYMENT", "ON_COMPLETION"}


def _json_load(raw, fallback):
    try:
        return json.loads(raw) if raw else fallback
    except (ValueError, TypeError):
        return fallback


def _partner_dict(p, include_internal=True):
    """A partner as the admin sees it. `include_internal=False` drops commission
    and contact details — a business owner has no business seeing what
    CreditVoice earns on the introduction."""
    out = {
        "id": p.id,
        "name": p.name,
        "logo_url": p.logo_url,
        "asset_types": _json_load(p.asset_types, []),
        "asset_value_min": p.asset_value_min,
        "asset_value_max": p.asset_value_max,
        "is_active": bool(p.is_active),
    }
    if include_internal:
        out.update({
            "contact_name": p.contact_name,
            "contact_phone": p.contact_phone,
            "contact_email": p.contact_email,
            "eligibility": _json_load(p.eligibility_json, {}),
            "commission_type": p.commission_type,
            "commission_value": p.commission_value,
            "commission_due_on": p.commission_due_on,
            "notes": p.notes,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            "updated_by": p.updated_by,
        })
    return out


def _application_code(db):
    """Short, quotable code so a closed deal can be traced back to us."""
    import secrets
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no look-alikes
    for _ in range(20):
        code = "CV-" + "".join(secrets.choice(alphabet) for _ in range(5))
        if not db.query(FinanceApplication).filter(FinanceApplication.application_code == code).first():
            return code
    return "CV-" + secrets.token_hex(4).upper()


# Statuses the owner may still withdraw from — once a partner has approved or
# delivered, withdrawing would rewrite history the fee depends on.
_WITHDRAWABLE = {"SUBMITTED", "SHARED", "IN_REVIEW"}

# The pipeline, as a graph. Enforced so an application can't jump from SUBMITTED to
# DELIVERED (which would make a fee payable with no record of the steps), and so
# a finished application can't be quietly reopened.
_TRANSITIONS = {
    "SUBMITTED": {"SHARED", "DECLINED", "WITHDRAWN"},
    "SHARED":    {"IN_REVIEW", "APPROVED", "DECLINED", "WITHDRAWN"},
    "IN_REVIEW": {"APPROVED", "DECLINED", "WITHDRAWN"},
    "APPROVED":  {"DELIVERED", "DECLINED"},
    "DELIVERED": set(),
    "DECLINED":  set(),
    "WITHDRAWN": set(),
}

_COMMISSION_STATES = {"PENDING", "DUE", "INVOICED", "PAID"}


def calculate_commission(partner, application):
    """(amount, reason) for this deal under the partner's terms.

    A percentage of repayments can only be known once repayments are recorded,
    so it returns None with a reason rather than a misleading zero.
    """
    if not partner:
        return None, "Partner record is missing."
    kind = partner.commission_type
    value = int(partner.commission_value or 0)
    if kind == "FLAT_PER_DEAL":
        return value, None
    if kind == "PERCENT_OF_ASSET":
        if not application.asset_value:
            return None, "Enter the asset value the partner financed."
        # commission_value is basis points: 500 = 5%.
        return int(round(int(application.asset_value) * value / 10000)), None
    if kind == "PERCENT_OF_REPAYMENTS":
        return None, "Calculated from recorded repayments (not tracked yet)."
    return None, f"Unknown commission type: {kind}"


def _application_dict(r, partner=None):
    return {
        "id": r.id,
        "application_code": r.application_code,
        "partner_id": r.partner_id,
        "partner_name": partner.name if partner else None,
        "asset_requested": r.asset_requested,
        "asset_value": r.asset_value,
        "note": r.note,
        "status": r.status,
        "decline_reason": r.decline_reason,
        "score": r.snapshot_score,
        "tier": r.snapshot_tier,
        "confidence": r.snapshot_confidence,
        "config_version": r.config_version,
        "consent_given_at": r.consent_given_at.isoformat() if r.consent_given_at else None,
        "consent_revoked_at": r.consent_revoked_at.isoformat() if r.consent_revoked_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "approved_at": r.approved_at.isoformat() if r.approved_at else None,
        "delivered_at": r.delivered_at.isoformat() if r.delivered_at else None,
    }


def register_finance_routes(app):

    def _require_admin(db, session):
        from admin import is_app_admin
        user = db.query(User).filter(User.id == session["user_id"]).first()
        if not user or not is_app_admin(user.phone, db):
            raise HTTPException(status_code=403, detail="Admin only")
        if not _admin_rate_check(user.phone):
            raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")
        return user

    def _audit(db, user, action, resource):
        from models import AuditLog
        db.add(AuditLog(actor_id=user.id, actor_phone=user.phone, action=action, resource=resource))

    # ── Admin: finance partners ───────────────────────────────────────────
    @app.get("/app/api/admin/finance-partners")
    def admin_list_partners(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_admin(db, session)
            rows = db.query(FinancePartner).order_by(FinancePartner.created_at.desc()).all()
            return {"partners": [_partner_dict(p) for p in rows]}
        finally:
            db.close()

    def _apply(p, payload, user):
        if payload.commission_type not in _COMMISSION_TYPES:
            raise HTTPException(status_code=400, detail=f"commission_type must be one of {sorted(_COMMISSION_TYPES)}")
        if payload.commission_due_on not in _COMMISSION_DUE:
            raise HTTPException(status_code=400, detail=f"commission_due_on must be one of {sorted(_COMMISSION_DUE)}")
        if payload.commission_value < 0:
            raise HTTPException(status_code=400, detail="commission_value cannot be negative.")
        p.name = payload.name.strip()
        p.contact_name = (payload.contact_name or "").strip() or None
        p.contact_phone = (payload.contact_phone or "").strip() or None
        p.contact_email = (payload.contact_email or "").strip() or None
        p.logo_url = (payload.logo_url or "").strip() or None
        p.asset_types = json.dumps([str(a).strip() for a in payload.asset_types if str(a).strip()])
        p.asset_value_min = payload.asset_value_min
        p.asset_value_max = payload.asset_value_max
        p.eligibility_json = json.dumps(payload.eligibility or {})
        p.commission_type = payload.commission_type
        p.commission_value = payload.commission_value
        p.commission_due_on = payload.commission_due_on
        p.notes = (payload.notes or "").strip() or None
        p.is_active = bool(payload.is_active)
        p.updated_at = utcnow()
        p.updated_by = user.phone
        return p

    @app.post("/app/api/admin/finance-partners")
    def admin_create_partner(payload: PartnerRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_admin(db, session)
            if not payload.name.strip():
                raise HTTPException(status_code=400, detail="Partner name is required.")
            p = FinancePartner()
            _apply(p, payload, user)
            db.add(p)
            db.flush()
            _audit(db, user, "ADMIN_SETTINGS_CHANGE", f"finance_partner:create:{p.id}")
            db.commit()
            db.refresh(p)
            return _partner_dict(p)
        finally:
            db.close()

    @app.put("/app/api/admin/finance-partners/{partner_id}")
    def admin_update_partner(partner_id: str, payload: PartnerRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_admin(db, session)
            p = db.query(FinancePartner).filter(FinancePartner.id == partner_id).first()
            if not p:
                raise HTTPException(status_code=404, detail="Partner not found.")
            _apply(p, payload, user)
            _audit(db, user, "ADMIN_SETTINGS_CHANGE", f"finance_partner:update:{p.id}")
            db.commit()
            db.refresh(p)
            return _partner_dict(p)
        finally:
            db.close()

    @app.delete("/app/api/admin/finance-partners/{partner_id}")
    def admin_delete_partner(partner_id: str, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_admin(db, session)
            p = db.query(FinancePartner).filter(FinancePartner.id == partner_id).first()
            if not p:
                raise HTTPException(status_code=404, detail="Partner not found.")
            db.delete(p)
            _audit(db, user, "ADMIN_SETTINGS_CHANGE", f"finance_partner:delete:{partner_id}")
            db.commit()
            return {"deleted": True}
        finally:
            db.close()

    # ── Admin: scorecard rules ────────────────────────────────────────────
    @app.get("/app/api/admin/scorecard-config")
    def admin_get_config(session: dict = Depends(require_web_auth)):
        """The live rules, the built-in defaults to reset to, and the edit history."""
        from business_scorecard import DEFAULT_CONFIG, active_config
        db = SessionLocal()
        try:
            _require_admin(db, session)
            version, cfg = active_config(db)
            history = (
                db.query(ScorecardConfig)
                .order_by(ScorecardConfig.version.desc())
                .limit(20).all()
            )
            return {
                "version": version,
                "config": cfg,
                "defaults": DEFAULT_CONFIG,
                "history": [
                    {"version": h.version, "note": h.note, "updated_by": h.updated_by,
                     "is_active": bool(h.is_active),
                     "created_at": h.created_at.isoformat() if h.created_at else None}
                    for h in history
                ],
            }
        finally:
            db.close()

    @app.post("/app/api/admin/scorecard-config")
    def admin_save_config(payload: ScorecardConfigRequest, session: dict = Depends(require_web_auth)):
        """Save a new version. The previous one is kept so old reports stay
        explainable."""
        from business_scorecard import save_config
        db = SessionLocal()
        try:
            user = _require_admin(db, session)
            cfg = payload.config or {}
            comps = cfg.get("components")
            if comps is not None:
                if not isinstance(comps, dict) or not comps:
                    raise HTTPException(status_code=400, detail="components must be a non-empty object.")
                total = sum(float(c.get("weight", 0) or 0) for c in comps.values())
                if total <= 0:
                    raise HTTPException(status_code=400, detail="Component weights must add up to more than 0.")
            row = save_config(db, cfg, updated_by=user.phone, note=(payload.note or "").strip() or None)
            _audit(db, user, "ADMIN_SETTINGS_CHANGE", f"scorecard_config:v{row.version}")
            db.commit()
            return {"version": row.version, "saved": True}
        finally:
            db.close()

    @app.post("/app/api/admin/scorecard-preview")
    def admin_preview_config(payload: ScorecardConfigRequest, session: dict = Depends(require_web_auth)):
        """What a proposed config would do to the businesses you actually have,
        against what the live one does — so a weight change isn't a guess."""
        from business_scorecard import DEFAULT_CONFIG, active_config, score_business
        db = SessionLocal()
        try:
            _require_admin(db, session)
            _version, live = active_config(db)
            proposed = dict(DEFAULT_CONFIG)
            proposed.update(payload.config or {})

            owners = [
                r[0] for r in db.query(User.phone)
                .filter(User.parent_id.is_(None), User.phone.isnot(None))
                .limit(500).all()
            ]

            def _run(cfg):
                tiers, scored, scores = {}, 0, []
                for phone in owners:
                    card = score_business(db, phone, config=cfg, version=None)
                    tiers[card["tier"]] = tiers.get(card["tier"], 0) + 1
                    if card["scored"]:
                        scored += 1
                        scores.append(card["score"])
                return {
                    "businesses": len(owners),
                    "scored": scored,
                    "unscored": len(owners) - scored,
                    "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
                    "tiers": tiers,
                }

            return {"live": _run(live), "proposed": _run(proposed)}
        finally:
            db.close()

    # ── Admin: application pipeline + commission ledger ──────────────────────
    def _admin_application_dict(r, partner, owner=None, commission_reason=None):
        out = _application_dict(r, partner)
        out.update({
            "business_name": r.business_name,
            "owner_phone": r.owner_phone,
            "owner_name": owner.name if owner else None,
            "partner_ref": r.partner_ref,
            "admin_notes": r.admin_notes,
            "commission_amount": r.commission_amount,
            "commission_status": r.commission_status,
            "commission_reason": commission_reason,
            "commission_marked_at": r.commission_marked_at.isoformat() if r.commission_marked_at else None,
            "next_statuses": sorted(_TRANSITIONS.get(r.status, set())),
        })
        return out

    @app.get("/app/api/admin/finance-applications")
    def admin_list_applications(
        session: dict = Depends(require_web_auth),
        status: str = "",
        partner_id: str = "",
    ):
        db = SessionLocal()
        try:
            _require_admin(db, session)
            q = (
                db.query(FinanceApplication, FinancePartner)
                .outerjoin(FinancePartner, FinanceApplication.partner_id == FinancePartner.id)
            )
            if status:
                q = q.filter(FinanceApplication.status == status.upper())
            if partner_id:
                q = q.filter(FinanceApplication.partner_id == partner_id)
            rows = q.order_by(FinanceApplication.created_at.desc()).limit(300).all()

            owners = {}
            phones = [r.owner_phone for r, _p in rows if r.owner_phone]
            if phones:
                owners = {u.phone: u for u in db.query(User).filter(User.phone.in_(phones)).all()}

            applications, totals = [], {"DUE": 0, "INVOICED": 0, "PAID": 0}
            for r, p in rows:
                amount, reason = calculate_commission(p, r)
                applications.append(_admin_application_dict(r, p, owners.get(r.owner_phone), reason))
                if r.commission_status in totals:
                    totals[r.commission_status] += int(r.commission_amount or 0)
            return {
                "applications": applications,
                "commission_totals": totals,
                "counts": {
                    s: sum(1 for r in applications if r["status"] == s)
                    for s in _TRANSITIONS
                },
            }
        finally:
            db.close()

    @app.get("/app/api/admin/finance-applications/{application_id}")
    def admin_application_detail(application_id: str, session: dict = Depends(require_web_auth)):
        """The full frozen snapshot — what this business's record looked like when
        they applied. This is what gets shared with the partner."""
        db = SessionLocal()
        try:
            _require_admin(db, session)
            r = db.query(FinanceApplication).filter(FinanceApplication.id == application_id).first()
            if not r:
                raise HTTPException(status_code=404, detail="Application not found.")
            partner = db.query(FinancePartner).filter(FinancePartner.id == r.partner_id).first()
            owner = db.query(User).filter(User.phone == r.owner_phone).first()
            amount, reason = calculate_commission(partner, r)
            out = _admin_application_dict(r, partner, owner, reason)
            out["commission_calculated"] = amount
            out["snapshot"] = _json_load(r.snapshot_json, {})
            return out
        finally:
            db.close()

    @app.patch("/app/api/admin/finance-applications/{application_id}")
    def admin_update_application(application_id: str, payload: ApplicationUpdateRequest,
                              session: dict = Depends(require_web_auth)):
        """Move an application along the pipeline and record the partner's numbers.

        Reaching the partner's commission trigger (e.g. DELIVERED) calculates the
        fee and marks it DUE, so the ledger follows the deal rather than memory.
        """
        db = SessionLocal()
        try:
            user = _require_admin(db, session)
            r = db.query(FinanceApplication).filter(FinanceApplication.id == application_id).first()
            if not r:
                raise HTTPException(status_code=404, detail="Application not found.")
            partner = db.query(FinancePartner).filter(FinancePartner.id == r.partner_id).first()
            now = utcnow()

            if payload.asset_value is not None:
                if payload.asset_value < 0:
                    raise HTTPException(status_code=400, detail="Asset value cannot be negative.")
                r.asset_value = payload.asset_value
            if payload.partner_ref is not None:
                r.partner_ref = payload.partner_ref.strip() or None
            if payload.admin_notes is not None:
                r.admin_notes = payload.admin_notes.strip() or None
            if payload.decline_reason is not None:
                r.decline_reason = payload.decline_reason.strip() or None

            if payload.status:
                new = payload.status.upper()
                if new not in _TRANSITIONS:
                    raise HTTPException(status_code=400, detail=f"Unknown status: {new}")
                if new != r.status and new not in _TRANSITIONS.get(r.status, set()):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot go from {r.status} to {new}. "
                               f"Allowed: {', '.join(sorted(_TRANSITIONS.get(r.status, set()))) or 'none'}.",
                    )
                if new == "DECLINED" and not (r.decline_reason or "").strip():
                    raise HTTPException(status_code=400, detail="Give a reason when declining.")
                r.status = new
                if new == "APPROVED":
                    r.approved_at = r.approved_at or now
                if new == "DELIVERED":
                    r.delivered_at = r.delivered_at or now

                # Commission becomes due at the trigger the partner agreed to.
                due_on = (partner.commission_due_on if partner else "ON_DELIVERY")
                triggered = (
                    (due_on == "ON_DELIVERY" and new == "DELIVERED")
                    # The later triggers need repayment records, which arrive with
                    # installment tracking; the ledger stays PENDING until then.
                )
                if triggered and r.commission_status == "PENDING":
                    amount, _reason = calculate_commission(partner, r)
                    if amount is not None:
                        r.commission_amount = amount
                        r.commission_status = "DUE"
                        r.commission_marked_at = now

            r.updated_at = now
            _audit(db, user, "ADMIN_SETTINGS_CHANGE", f"finance_application:{r.id}:{r.status}")
            db.commit()
            db.refresh(r)
            amount, reason = calculate_commission(partner, r)
            out = _admin_application_dict(r, partner, None, reason)
            out["commission_calculated"] = amount
            return out
        finally:
            db.close()

    @app.post("/app/api/admin/finance-applications/{application_id}/commission")
    def admin_set_commission(application_id: str, payload: CommissionRequest,
                             session: dict = Depends(require_web_auth)):
        """Move the fee through the ledger: DUE → INVOICED → PAID (or back to
        PENDING), optionally overriding the calculated amount for a deal that was
        agreed differently."""
        db = SessionLocal()
        try:
            user = _require_admin(db, session)
            r = db.query(FinanceApplication).filter(FinanceApplication.id == application_id).first()
            if not r:
                raise HTTPException(status_code=404, detail="Application not found.")
            state = payload.status.upper()
            if state not in _COMMISSION_STATES:
                raise HTTPException(status_code=400, detail=f"status must be one of {sorted(_COMMISSION_STATES)}")
            if payload.amount is not None:
                if payload.amount < 0:
                    raise HTTPException(status_code=400, detail="Amount cannot be negative.")
                r.commission_amount = payload.amount
            if state != "PENDING" and not r.commission_amount:
                partner = db.query(FinancePartner).filter(FinancePartner.id == r.partner_id).first()
                amount, reason = calculate_commission(partner, r)
                if amount is None:
                    raise HTTPException(status_code=400, detail=reason or "No commission amount to record.")
                r.commission_amount = amount
            r.commission_status = state
            r.commission_marked_at = utcnow()
            r.updated_at = utcnow()
            _audit(db, user, "ADMIN_SETTINGS_CHANGE", f"finance_commission:{r.id}:{state}")
            db.commit()
            db.refresh(r)
            return {
                "id": r.id, "commission_status": r.commission_status,
                "commission_amount": r.commission_amount,
                "commission_marked_at": r.commission_marked_at.isoformat() if r.commission_marked_at else None,
            }
        finally:
            db.close()

    # ── Business owner: my scorecard + what I qualify for ─────────────────
    @app.get("/app/api/scorecard")
    def my_scorecard(session: dict = Depends(require_web_auth)):
        """This business's own evidence: metrics, component scores, tier and how
        much of the picture is corroborated."""
        from business_scorecard import score_business
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            return score_business(db, owner_phone)
        finally:
            db.close()

    @app.get("/app/api/finance-offers")
    def my_finance_offers(session: dict = Depends(require_web_auth)):
        """Active partners, each with this business's standing against that
        partner's stated minimums. Eligibility here is a filter, never an
        approval — the partner decides."""
        from business_scorecard import check_eligibility, eligible, score_business
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            card = score_business(db, owner_phone)
            rows = db.query(FinancePartner).filter(
                FinancePartner.is_active == True  # noqa: E712
            ).order_by(FinancePartner.name).all()
            offers = []
            for p in rows:
                checks = check_eligibility(card, _json_load(p.eligibility_json, {}))
                offers.append({
                    **_partner_dict(p, include_internal=False),
                    "checks": checks,
                    "eligible": eligible(checks),
                })
            # So the page can show "applied" instead of offering again.
            applied = {
                r.partner_id: r.status
                for r in db.query(FinanceApplication).filter(
                    FinanceApplication.owner_phone == owner_phone
                ).all()
            }
            for offer in offers:
                offer["applied_status"] = applied.get(offer["id"])
            return {
                "score": card["score"], "tier": card["tier"],
                "confidence": card["confidence"], "scored": card["scored"],
                "offers": offers,
            }
        finally:
            db.close()

    # ── Business owner: ask to be introduced ──────────────────────────────
    @app.post("/app/api/finance-offers/{partner_id}/apply")
    def apply_to_partner(partner_id: str, payload: ApplyRequest,
                         session: dict = Depends(require_web_auth)):
        """Ask for an introduction to this partner.

        Requires explicit consent, and freezes the scorecard as it stands now —
        so what the partner is shown can't be changed later by re-tuning the
        rules or by a sudden burst of recording.
        """
        from business_scorecard import score_business
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            if not payload.consent:
                raise HTTPException(
                    status_code=400,
                    detail="Your consent is required before your business record can be shared.",
                )
            partner = db.query(FinancePartner).filter(
                FinancePartner.id == partner_id,
                FinancePartner.is_active == True,  # noqa: E712
            ).first()
            if not partner:
                raise HTTPException(status_code=404, detail="Partner not found.")

            open_already = db.query(FinanceApplication).filter(
                FinanceApplication.owner_phone == owner_phone,
                FinanceApplication.partner_id == partner_id,
                FinanceApplication.status.notin_(["DECLINED", "WITHDRAWN"]),
            ).first()
            if open_already:
                raise HTTPException(
                    status_code=400,
                    detail=f"You already have a request with {partner.name} ({open_already.application_code}).",
                )

            owner = db.query(User).filter(User.phone == owner_phone).first()
            card = score_business(db, owner_phone)
            now = utcnow()
            application = FinanceApplication(
                application_code=_application_code(db),
                partner_id=partner.id,
                owner_phone=owner_phone,
                business_name=(owner.business_type_label or owner.name) if owner else None,
                contact_phone=owner_phone,
                asset_requested=(payload.asset_requested or "").strip() or None,
                asset_value=payload.asset_value,
                note=(payload.note or "").strip() or None,
                consent_given_at=now,
                snapshot_json=json.dumps(card),
                snapshot_score=int(card["score"]) if card.get("score") is not None else None,
                snapshot_tier=card.get("tier"),
                snapshot_confidence=int(card.get("confidence") or 0),
                config_version=card.get("config_version"),
                status="SUBMITTED",
                created_at=now,
            )
            db.add(application)
            db.commit()
            db.refresh(application)
            return _application_dict(application, partner)
        finally:
            db.close()

    @app.get("/app/api/my-applications")
    def my_applications(session: dict = Depends(require_web_auth)):
        """This business's introduction requests and where each one stands."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            rows = (
                db.query(FinanceApplication, FinancePartner)
                .outerjoin(FinancePartner, FinanceApplication.partner_id == FinancePartner.id)
                .filter(FinanceApplication.owner_phone == owner_phone)
                .order_by(FinanceApplication.created_at.desc())
                .all()
            )
            return {"applications": [_application_dict(r, p) for r, p in rows]}
        finally:
            db.close()

    @app.post("/app/api/my-applications/{application_id}/withdraw")
    def withdraw_application(application_id: str, session: dict = Depends(require_web_auth)):
        """Withdraw the request and revoke consent to share the record."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            r = db.query(FinanceApplication).filter(
                FinanceApplication.id == application_id,
                FinanceApplication.owner_phone == owner_phone,
            ).first()
            if not r:
                raise HTTPException(status_code=404, detail="Request not found.")
            if r.status not in _WITHDRAWABLE:
                raise HTTPException(
                    status_code=400,
                    detail=f"This request is already {r.status.lower()} and can no longer be withdrawn.",
                )
            now = utcnow()
            r.status = "WITHDRAWN"
            r.consent_revoked_at = now
            r.updated_at = now
            db.commit()
            db.refresh(r)
            return _application_dict(r)
        finally:
            db.close()
