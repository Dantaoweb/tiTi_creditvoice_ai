"""
Reviews and public-site settings.

A review here is written by the business and shown with their name, town and
phone number — being featured on the landing page is a free advert for them,
which is why anyone would write one. Nothing goes public until an admin
approves it and the owner has ticked the consent box.

Social links and how many reviews to feature are settings, not code, so they can
change without a deploy.
"""
import logging
import os
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from models import AuditLog, SiteSetting, Testimonial, User, utcnow
from web_auth import require_web_auth
from web_common import _admin_rate_check, _session_owner_phone, _session_user
from web_public_pages import _esc

_log = logging.getLogger(__name__)

# Settings the landing page reads. Kept here so the admin screen and the page
# agree on what exists without either hardcoding a list.
SETTING_KEYS = {
    "facebook_url":  "Facebook page URL",
    "instagram_url": "Instagram profile URL",
    "tiktok_url":    "TikTok profile URL",
    "whatsapp_url":  "WhatsApp channel or chat link",
    "featured_reviews": "How many reviews to show on the landing page",
}
DEFAULT_FEATURED = 3


class TestimonialRequest(BaseModel):
    business_name: str = Field(max_length=120)
    business_type: Optional[str] = Field(default=None, max_length=80)
    location: Optional[str] = Field(default=None, max_length=120)
    quote: str = Field(max_length=600)
    contact_phone: Optional[str] = Field(default=None, max_length=30)
    contact_link: Optional[str] = Field(default=None, max_length=300)
    consent_public: bool = False


class TestimonialReviewRequest(BaseModel):
    status: Optional[str] = Field(default=None, max_length=20)   # APPROVED | REJECTED | PENDING
    is_featured: Optional[bool] = None
    sort_order: Optional[int] = None
    admin_note: Optional[str] = Field(default=None, max_length=300)


class SettingsRequest(BaseModel):
    settings: dict


def get_setting(db, key, default=None):
    row = db.query(SiteSetting).filter(SiteSetting.key == key).first()
    return row.value if row and row.value else default


def all_settings(db):
    return {row.key: row.value for row in db.query(SiteSetting).all()}


def featured_reviews(db, limit=None):
    """Approved, consented, featured reviews for the landing page."""
    if limit is None:
        try:
            limit = int(get_setting(db, "featured_reviews", DEFAULT_FEATURED))
        except (TypeError, ValueError):
            limit = DEFAULT_FEATURED
    return (
        db.query(Testimonial)
        .filter(
            Testimonial.status == "APPROVED",
            Testimonial.is_featured == True,       # noqa: E712
            Testimonial.consent_public == True,    # noqa: E712
        )
        .order_by(Testimonial.sort_order.asc(), Testimonial.created_at.desc())
        .limit(max(0, int(limit)))
        .all()
    )


def _dict(t, include_owner=False):
    out = {
        "id": t.id,
        "business_name": t.business_name,
        "business_type": t.business_type,
        "location": t.location,
        "quote": t.quote,
        "contact_phone": t.contact_phone,
        "contact_link": t.contact_link,
        "status": t.status,
        "is_featured": bool(t.is_featured),
        "sort_order": t.sort_order or 0,
        "consent_public": bool(t.consent_public),
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }
    if include_owner:
        out["owner_phone"] = t.owner_phone
        out["admin_note"] = t.admin_note
    return out


def register_site_routes(app):

    def _require_admin(db, session):
        from admin import is_app_admin
        user = db.query(User).filter(User.id == session["user_id"]).first()
        if not user or not is_app_admin(user.phone, db):
            raise HTTPException(status_code=403, detail="Admin only")
        if not _admin_rate_check(user.phone):
            raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")
        return user

    # ── The business writes its own review ────────────────────────────────
    @app.get("/app/api/my-review")
    def my_review(session: dict = Depends(require_web_auth)):
        """Their review, if they have written one, and where it stands."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            row = (
                db.query(Testimonial)
                .filter(Testimonial.owner_phone == owner_phone)
                .order_by(Testimonial.created_at.desc())
                .first()
            )
            return {"review": _dict(row) if row else None}
        finally:
            db.close()

    @app.post("/app/api/my-review")
    def save_my_review(payload: TestimonialRequest, session: dict = Depends(require_web_auth)):
        """Write or rewrite it. Editing sends it back for approval, because the
        words on a public page must be the words an admin actually read."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            user = _session_user(db, session)
            if not payload.consent_public:
                raise HTTPException(
                    status_code=400,
                    detail="Tick the box to agree your business name, town and contact can be shown publicly.",
                )
            if not payload.quote.strip() or not payload.business_name.strip():
                raise HTTPException(status_code=400, detail="Your business name and a few words are required.")
            link = (payload.contact_link or "").strip()
            if link and not link.startswith(("http://", "https://")):
                raise HTTPException(status_code=400, detail="A link must start with http:// or https://")

            row = db.query(Testimonial).filter(Testimonial.owner_phone == owner_phone).first()
            if row is None:
                row = Testimonial(owner_phone=owner_phone)
                db.add(row)
            row.business_name = payload.business_name.strip()
            row.business_type = (payload.business_type or getattr(user, "business_type_label", None) or "").strip() or None
            row.location = (payload.location or "").strip() or None
            row.quote = payload.quote.strip()
            row.contact_phone = (payload.contact_phone or "").strip() or None
            row.contact_link = link or None
            row.consent_public = True
            row.status = "PENDING"        # re-approved after every edit
            row.is_featured = False
            row.reviewed_at = None
            row.reviewed_by = None
            db.commit()
            db.refresh(row)
            return {"review": _dict(row), "message": "Thank you — we'll review it shortly."}
        finally:
            db.close()

    @app.delete("/app/api/my-review")
    def delete_my_review(session: dict = Depends(require_web_auth)):
        """Withdraw it — including from the landing page."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            rows = db.query(Testimonial).filter(Testimonial.owner_phone == owner_phone).all()
            for row in rows:
                db.delete(row)
            db.commit()
            return {"deleted": len(rows)}
        finally:
            db.close()

    # ── Admin: moderate, feature, and set the site settings ───────────────
    @app.get("/app/api/admin/reviews")
    def admin_reviews(session: dict = Depends(require_web_auth), status: str = ""):
        db = SessionLocal()
        try:
            _require_admin(db, session)
            q = db.query(Testimonial)
            if status:
                q = q.filter(Testimonial.status == status.upper())
            rows = q.order_by(Testimonial.created_at.desc()).limit(300).all()
            counts = {}
            for r in db.query(Testimonial).all():
                counts[r.status] = counts.get(r.status, 0) + 1
            return {"reviews": [_dict(r, include_owner=True) for r in rows], "counts": counts}
        finally:
            db.close()

    @app.patch("/app/api/admin/reviews/{review_id}")
    def admin_review_update(review_id: str, payload: TestimonialReviewRequest,
                            session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_admin(db, session)
            row = db.query(Testimonial).filter(Testimonial.id == review_id).first()
            if not row:
                raise HTTPException(status_code=404, detail="Review not found.")
            if payload.status:
                status = payload.status.upper()
                if status not in ("PENDING", "APPROVED", "REJECTED"):
                    raise HTTPException(status_code=400, detail="Unknown status.")
                row.status = status
                if status != "APPROVED":
                    row.is_featured = False
            if payload.is_featured is not None:
                if payload.is_featured and row.status != "APPROVED":
                    raise HTTPException(status_code=400, detail="Approve the review before featuring it.")
                row.is_featured = payload.is_featured
            if payload.sort_order is not None:
                row.sort_order = payload.sort_order
            if payload.admin_note is not None:
                row.admin_note = payload.admin_note.strip() or None
            row.reviewed_at = utcnow()
            row.reviewed_by = user.phone
            db.add(AuditLog(actor_id=user.id, actor_phone=user.phone,
                            action="ADMIN_SETTINGS_CHANGE",
                            resource=f"review:{row.id}:{row.status}:featured={row.is_featured}"))
            db.commit()
            db.refresh(row)
            return _dict(row, include_owner=True)
        finally:
            db.close()

    @app.get("/app/api/admin/site-settings")
    def admin_get_settings(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_admin(db, session)
            values = all_settings(db)
            return {
                "settings": {k: values.get(k, "") for k in SETTING_KEYS},
                "labels": SETTING_KEYS,
            }
        finally:
            db.close()

    @app.post("/app/api/admin/site-settings")
    def admin_save_settings(payload: SettingsRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _require_admin(db, session)
            for key, value in (payload.settings or {}).items():
                if key not in SETTING_KEYS:
                    continue      # ignore anything the page doesn't use
                value = (str(value or "")).strip()
                if key.endswith("_url") and value and not value.startswith(("http://", "https://")):
                    raise HTTPException(status_code=400,
                                        detail=f"{SETTING_KEYS[key]} must start with http:// or https://")
                row = db.query(SiteSetting).filter(SiteSetting.key == key).first()
                if row is None:
                    row = SiteSetting(key=key)
                    db.add(row)
                row.value = value or None
                row.updated_at = utcnow()
                row.updated_by = user.phone
            db.add(AuditLog(actor_id=user.id, actor_phone=user.phone,
                            action="ADMIN_SETTINGS_CHANGE", resource="site_settings"))
            db.commit()
            return {"settings": {k: all_settings(db).get(k, "") for k in SETTING_KEYS}}
        finally:
            db.close()


# ── Landing-page fragments ───────────────────────────────────────────────────
# The landing page is a static file with comment placeholders. These builders
# fill them, so prices, reviews and social links change from the admin screen or
# an env var — never by editing HTML.

_PLAN_BULLETS = {
    "BASIC":   ["Record sales and credit", "Who owes you, at a glance", "Receipts on WhatsApp"],
    "GO":      ["Unlimited records", "Stock and low-stock alerts", "Reminders sent for you", "Reports and profit"],
    "PRO":     ["Everything in Go", "Staff accounts", "One branch, partner and investor", "Business scorecard"],
    "PREMIUM": ["Everything in Pro", "Unlimited branches and staff", "Unlimited partners and investors", "Priority support"],
}
_PLAN_NAMES = {"BASIC": "Basic", "GO": "Go", "PRO": "Pro", "PREMIUM": "Premium"}

_SOCIAL_ICONS = {
    # Simple single-path marks, inline so the page pulls in no third-party asset.
    "facebook_url": ("Facebook", "M14 9h2V6h-2c-2.2 0-3.5 1.3-3.5 3.6V11H8.5v3H10.5v7h3.5v-7h2.3l.4-3H14V9.8c0-.6.2-.8.8-.8z"),
    "instagram_url": ("Instagram", "M12 7.6A4.4 4.4 0 1 0 16.4 12A4.4 4.4 0 0 0 12 7.6zm0 7.2A2.8 2.8 0 1 1 14.8 12A2.8 2.8 0 0 1 12 14.8zM17.8 5.4H6.2A2.8 2.8 0 0 0 3.4 8.2v7.6a2.8 2.8 0 0 0 2.8 2.8h11.6a2.8 2.8 0 0 0 2.8-2.8V8.2a2.8 2.8 0 0 0-2.8-2.8zm1.2 10.4a1.2 1.2 0 0 1-1.2 1.2H6.2A1.2 1.2 0 0 1 5 15.8V8.2A1.2 1.2 0 0 1 6.2 7h11.6A1.2 1.2 0 0 1 19 8.2zM17.2 7.9a.95.95 0 1 1-.95.95a.95.95 0 0 1 .95-.95z"),
    "tiktok_url": ("TikTok", "M16.6 3h-2.7v11.2a2.1 2.1 0 1 1-2.1-2.1c.2 0 .4 0 .6.1V9.4a4.9 4.9 0 1 0 4.2 4.8V8.6a5 5 0 0 0 3 1V7a3 3 0 0 1-3-3z"),
    "whatsapp_url": ("WhatsApp", "M12 3a9 9 0 0 0-7.7 13.6L3 21l4.5-1.2A9 9 0 1 0 12 3zm4.6 12.3c-.2.6-1.1 1.1-1.8 1.2c-.5 0-1.1 0-3-.9a10.6 10.6 0 0 1-4.3-4.3c-.8-1.6-.6-2.4-.4-2.9c.2-.4.6-.9 1-1c.2 0 .4-.1.6 0c.2 0 .3 0 .5.4l.7 1.6c.1.2 0 .4-.1.5l-.4.5c-.1.2-.2.3 0 .6a8 8 0 0 0 3 2.6c.3.1.4 0 .6-.1l.6-.7c.2-.2.3-.1.5-.1l1.5.8c.2.1.3.2.4.3s0 .7-.1 1z"),
}


def _social_links(db):
    """Link for each network: the admin setting first, then an env var, so a
    fresh deploy can carry links before anyone signs into the admin screen."""
    values = all_settings(db)
    out = []
    for key, (name, path) in _SOCIAL_ICONS.items():
        url = (values.get(key) or os.getenv("SOCIAL_" + key.upper(), "")).strip()
        if key == "whatsapp_url" and not url:
            wa = os.getenv("TITI_WHATSAPP", "").strip().lstrip("+").replace(" ", "")
            url = f"https://wa.me/{wa}" if wa else ""
        if url.startswith(("http://", "https://")):
            out.append((name, path, url))
    return out


def _social_html(db):
    links = _social_links(db)
    if not links:
        return ""
    icons = "".join(
        f'<a href="{_esc(url)}" aria-label="{_esc(name)}" title="{_esc(name)}" '
        f'target="_blank" rel="noopener">'
        f'<svg width="20" height="20" viewBox="0 0 24 24" fill="#fff" aria-hidden="true">'
        f'<path d="{path}"/></svg></a>'
        for name, path, url in links
    )
    return f'<div class="social">{icons}</div>'


def _pricing_html():
    from messages import get_plan_price
    from plans import PLAN_BASIC, PLAN_GO, PLAN_PREMIUM, PLAN_PRO

    cards = []
    for plan in (PLAN_BASIC, PLAN_GO, PLAN_PRO, PLAN_PREMIUM):
        price = get_plan_price(plan)
        featured = ' featured' if plan == PLAN_PRO else ''
        amount = "Free" if not price else f"₦{price:,}"
        per = "" if not price else "<small> /month</small>"
        bullets = "".join(f"<li>{_esc(b)}</li>" for b in _PLAN_BULLETS.get(plan, []))
        cta = "Start free" if not price else f"Choose {_PLAN_NAMES[plan]}"
        cards.append(
            f'<div class="plan{featured}">'
            f'<h3>{_PLAN_NAMES[plan]}</h3>'
            f'<div class="price">{amount}{per}</div>'
            f'<ul>{bullets}</ul>'
            f'<a class="btn{"" if price else " ghost"}" href="/app">{cta}</a>'
            f'</div>'
        )
    return f'<div class="plans">{"".join(cards)}</div>'


def _reviews_html(db):
    rows = featured_reviews(db)
    if not rows:
        # No approved review yet: invite one instead of showing an empty section
        # or, worse, words we wrote ourselves.
        return (
            '<div class="empty-quotes">'
            "<strong>Using CreditVoice?</strong> Write a review from your dashboard. "
            "Approved reviews appear here with your business name, town and phone "
            "number — a free advert on our homepage."
            ' <a href="/app">Write yours</a></div>'
        )
    cards = []
    for r in rows:
        where = " · ".join(x for x in [r.business_type, r.location] if x)
        contact = []
        if r.contact_phone:
            digits = "".join(c for c in r.contact_phone if c.isdigit() or c == "+")
            contact.append(f'<a href="tel:{_esc(digits)}">{_esc(r.contact_phone)}</a>')
        if r.contact_link:
            contact.append(
                f'<a href="{_esc(r.contact_link)}" target="_blank" rel="noopener nofollow">Visit</a>'
            )
        contact_html = (
            f'<div class="contact">{" · ".join(contact)}</div>' if contact else ""
        )
        cards.append(
            '<div class="quote">'
            f'<p>&ldquo;{_esc(r.quote)}&rdquo;</p>'
            f'<div class="who">{_esc(r.business_name)}</div>'
            f'<div class="where">{_esc(where)}</div>'
            f'{contact_html}</div>'
        )
    return f'<div class="quotes">{"".join(cards)}</div>'


def landing_fragments():
    """{placeholder: html} for the landing page. Never raises — a broken
    database must not take the homepage down with it."""
    blocks = {"PRICING": "", "REVIEWS": "", "SOCIAL": ""}
    try:
        blocks["PRICING"] = _pricing_html()
    except Exception:
        _log.exception("landing pricing block failed")
    db = None
    try:
        db = SessionLocal()
        blocks["REVIEWS"] = _reviews_html(db)
        blocks["SOCIAL"] = _social_html(db)
    except Exception:
        _log.exception("landing reviews/social block failed")
    finally:
        if db is not None:
            db.close()
    return blocks
