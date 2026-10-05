"""
In-app campaign cards: what the signed-in app asks for, and what an admin sets.

The app only ever asks for "the next card for me" and reports back what the
person did with it. Everything else — the copy, the artwork, who qualifies, how
often, when it stops — is set in the admin screen and lives in the database.
"""
from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

import campaigns as camp
from database import SessionLocal
from models import AuditLog, Campaign, CampaignView, User, utcnow
from web_auth import require_web_auth
from web_common import _admin_rate_check, _session_user

THEMES = ("navy", "amber", "green")
GOALS = ("", "review", "upgrade")


class CampaignRequest(BaseModel):
    key: Optional[str] = Field(default=None, max_length=60)
    title: str = Field(max_length=120)
    body: str = Field(max_length=600)
    image_url: Optional[str] = Field(default=None, max_length=500)
    theme: Optional[str] = Field(default="navy", max_length=20)
    cta_label: Optional[str] = Field(default=None, max_length=40)
    cta_link: Optional[str] = Field(default=None, max_length=300)
    goal: Optional[str] = Field(default=None, max_length=20)
    owners_only: bool = True
    plans: Optional[str] = Field(default=None, max_length=120)
    min_transactions: int = 0
    min_days_active: int = 0
    starts_at: Optional[str] = Field(default=None, max_length=40)
    ends_at: Optional[str] = Field(default=None, max_length=40)
    is_active: bool = False
    max_shows: int = 3
    snooze_days: int = 14
    priority: int = 0
    also_notify: bool = False
    also_whatsapp: bool = False


def _parse_dt(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "")).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must look like 2026-10-04 or 2026-10-04T09:00")


def _card(campaign):
    """Only what the card needs to draw itself — never the targeting rules."""
    return {
        "id": campaign.id,
        "key": campaign.key,
        "title": campaign.title,
        "body": campaign.body,
        "image_url": campaign.image_url,
        "theme": campaign.theme or "navy",
        "cta_label": campaign.cta_label,
        "cta_link": campaign.cta_link,
    }


def _admin_dict(db, campaign):
    out = {
        **_card(campaign),
        "goal": campaign.goal,
        "owners_only": bool(campaign.owners_only),
        "plans": campaign.plans or "",
        "min_transactions": campaign.min_transactions or 0,
        "min_days_active": campaign.min_days_active or 0,
        "starts_at": campaign.starts_at.isoformat() if campaign.starts_at else "",
        "ends_at": campaign.ends_at.isoformat() if campaign.ends_at else "",
        "is_active": bool(campaign.is_active),
        "max_shows": campaign.max_shows or 0,
        "snooze_days": campaign.snooze_days or 0,
        "priority": campaign.priority or 0,
        "also_notify": bool(campaign.also_notify),
        "also_whatsapp": bool(campaign.also_whatsapp),
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
    }
    out["stats"] = camp.stats(db, campaign)
    return out


def register_campaign_routes(app):

    def _require_admin(db, session):
        from admin import is_app_admin
        user = db.query(User).filter(User.id == session["user_id"]).first()
        if not user or not is_app_admin(user.phone, db):
            raise HTTPException(status_code=403, detail="Admin only")
        if not _admin_rate_check(user.phone):
            raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")
        return user

    def _apply(campaign, payload, actor=None):
        theme = (payload.theme or "navy").strip().lower()
        goal = (payload.goal or "").strip().lower()
        if theme not in THEMES:
            raise HTTPException(status_code=400, detail=f"Theme must be one of: {', '.join(THEMES)}")
        if goal not in GOALS:
            raise HTTPException(status_code=400, detail="Unknown goal.")
        link = (payload.cta_link or "").strip()
        if link and not (link.startswith("/") or link.startswith(("http://", "https://"))):
            raise HTTPException(status_code=400,
                                detail="The button link must be an in-app path like /profile, or a full https:// address.")
        image = (payload.image_url or "").strip()
        if image and not image.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="The image must be a full https:// address.")
        if not payload.title.strip() or not payload.body.strip():
            raise HTTPException(status_code=400, detail="A card needs a title and a line of text.")

        starts_at = _parse_dt(payload.starts_at)
        ends_at = _parse_dt(payload.ends_at)
        if starts_at and ends_at and ends_at < starts_at:
            raise HTTPException(status_code=400, detail="The end date is before the start date.")

        campaign.key = (payload.key or "").strip() or campaign.key
        campaign.title = payload.title.strip()
        campaign.body = payload.body.strip()
        campaign.image_url = image or None
        campaign.theme = theme
        campaign.cta_label = (payload.cta_label or "").strip() or None
        campaign.cta_link = link or None
        campaign.goal = goal or None
        campaign.owners_only = bool(payload.owners_only)
        campaign.plans = (payload.plans or "").strip().upper() or None
        campaign.min_transactions = max(0, int(payload.min_transactions or 0))
        campaign.min_days_active = max(0, int(payload.min_days_active or 0))
        campaign.starts_at = starts_at
        campaign.ends_at = ends_at
        campaign.is_active = bool(payload.is_active)
        campaign.max_shows = max(0, int(payload.max_shows or 0))
        campaign.snooze_days = max(0, int(payload.snooze_days or 0))
        campaign.priority = int(payload.priority or 0)
        campaign.also_notify = bool(payload.also_notify)
        campaign.also_whatsapp = bool(payload.also_whatsapp)
        if actor:
            campaign.created_by = campaign.created_by or actor.phone
        return campaign

    # ── The app asks for its next card ───────────────────────────────────────
    @app.get("/app/api/campaigns/next")
    def campaigns_next(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _session_user(db, session)
            if not user:
                return {"campaign": None}
            campaign = camp.next_for_user(db, user)
            if not campaign:
                return {"campaign": None}
            camp.mark_shown(db, campaign, user)
            return {"campaign": _card(campaign)}
        finally:
            db.close()

    @app.post("/app/api/campaigns/{campaign_id}/{action}")
    def campaigns_action(campaign_id: str, action: str,
                         session: dict = Depends(require_web_auth)):
        """clicked | dismissed — what the person did with the card."""
        if action not in ("clicked", "dismissed"):
            raise HTTPException(status_code=404, detail="Unknown action.")
        db = SessionLocal()
        try:
            user = _session_user(db, session)
            campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
            if not user or not campaign:
                raise HTTPException(status_code=404, detail="Campaign not found.")
            if action == "clicked":
                camp.mark_clicked(db, campaign, user)
            else:
                camp.mark_dismissed(db, campaign, user)
            return {"ok": True}
        finally:
            db.close()

    # ── Admin ────────────────────────────────────────────────────────────────
    @app.get("/app/api/admin/campaigns")
    def admin_campaigns(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_admin(db, session)
            rows = (db.query(Campaign)
                    .order_by(Campaign.priority.desc(), Campaign.created_at.desc())
                    .limit(200).all())
            return {"campaigns": [_admin_dict(db, c) for c in rows], "themes": list(THEMES)}
        finally:
            db.close()

    @app.post("/app/api/admin/campaigns")
    def admin_campaign_create(payload: CampaignRequest,
                              session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_admin(db, session)
            campaign = Campaign()
            _apply(campaign, payload, actor=user)
            if not campaign.key:
                campaign.key = payload.title.strip().lower().replace(" ", "-")[:60]
            db.add(campaign)
            db.add(AuditLog(actor_id=user.id, actor_phone=user.phone,
                            action="ADMIN_SETTINGS_CHANGE",
                            resource=f"campaign:create:{campaign.key}"))
            db.commit()
            db.refresh(campaign)
            return _admin_dict(db, campaign)
        finally:
            db.close()

    @app.put("/app/api/admin/campaigns/{campaign_id}")
    def admin_campaign_update(campaign_id: str, payload: CampaignRequest,
                              session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_admin(db, session)
            campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
            if not campaign:
                raise HTTPException(status_code=404, detail="Campaign not found.")
            _apply(campaign, payload, actor=user)
            db.add(AuditLog(actor_id=user.id, actor_phone=user.phone,
                            action="ADMIN_SETTINGS_CHANGE",
                            resource=f"campaign:update:{campaign.key}"))
            db.commit()
            db.refresh(campaign)
            return _admin_dict(db, campaign)
        finally:
            db.close()

    @app.delete("/app/api/admin/campaigns/{campaign_id}")
    def admin_campaign_delete(campaign_id: str, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_admin(db, session)
            campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
            if not campaign:
                raise HTTPException(status_code=404, detail="Campaign not found.")
            db.query(CampaignView).filter(CampaignView.campaign_id == campaign.id).delete()
            key = campaign.key
            db.delete(campaign)
            db.add(AuditLog(actor_id=user.id, actor_phone=user.phone,
                            action="ADMIN_SETTINGS_CHANGE", resource=f"campaign:delete:{key}"))
            db.commit()
            return {"deleted": True}
        finally:
            db.close()
