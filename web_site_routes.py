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
    "whatsapp_live": "WhatsApp approved by Meta and working (yes/no)",
    "show_stats": "Show the live usage numbers on the homepage (yes/no)",
}
DEFAULT_FEATURED = 3

# Bumped whenever an admin saves a setting. The landing page caches its blocks
# for a minute; this lets a change show up immediately instead.
_settings_version = 0


def settings_version():
    return _settings_version


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


def pending_review_count(db):
    """Reviews waiting on a decision. This is the number an admin is chasing —
    not "unread", which would clear itself by being glanced at."""
    return db.query(Testimonial).filter(Testimonial.status == "PENDING").count()


def _tell_admins_about(db, review):
    """A review nobody is told about sits unapproved for weeks.

    It goes to the bell and a push for every app admin, which is the quiet
    channel they already watch — the red count on the Admin menu is the loud
    one. Never fatal: a notification that fails must not lose the review.
    """
    try:
        from admin_alerts import notify_admins

        waiting = pending_review_count(db)
        title = "📝 A business wrote a review"
        body = (f"{review.business_name} wrote a review"
                + (f" ({review.location})" if review.location else "")
                + ".\n\n"
                + f"“{(review.quote or '')[:140]}”\n\n"
                + (f"{waiting} review(s) now waiting for approval."
                   if waiting > 1 else "Approve it to show it on the homepage."))

        notify_admins(db, "review", title, body, tab="Site")
    except Exception:
        _log.exception("could not tell the admins about a new review")


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
            # Any campaign that was asking for this has got what it wanted.
            from campaigns import mark_goal_done
            mark_goal_done(db, "review", user)
            _tell_admins_about(db, row)
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
    @app.get("/app/api/admin/pending-counts")
    def admin_pending_counts(session: dict = Depends(require_web_auth)):
        """What is waiting for an admin, for the red count on the menu.

        Deliberately cheap and quiet: no rate-limit error and no 403 noise for
        a non-admin, because the menu asks for this on every page change.
        """
        db = SessionLocal()
        try:
            from admin import is_app_admin
            from admin_alerts import (
                pending_opportunity_applications, pending_payments, pending_supplier_applications,
            )
            from finance_alerts import pending_finance_count
            from supplier_alerts import stale_supplier_requests
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user or not is_app_admin(user.phone, db):
                return {"reviews": 0, "suppliers": 0, "opportunities": 0, "finance": 0,
                        "payments": 0, "total": 0}
            # Keyed by what is waiting; each admin tab shows its own count.
            counts = {
                "reviews": pending_review_count(db),
                # Applications to decide, plus requests a supplier has left unanswered.
                "suppliers": pending_supplier_applications(db) + stale_supplier_requests(db),
                "opportunities": pending_opportunity_applications(db),
                "finance": pending_finance_count(db),
                "payments": pending_payments(db),
            }
            counts["total"] = sum(counts.values())
            return counts
        finally:
            db.close()

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
            # Turning WhatsApp on or off changes what the whole site may claim,
            # so it has to take effect now rather than when a cache expires.
            from feature_flags import clear_cache
            clear_cache()
            global _settings_version
            _settings_version += 1
            return {"settings": {k: all_settings(db).get(k, "") for k in SETTING_KEYS}}
        finally:
            db.close()


# ── Landing-page fragments ───────────────────────────────────────────────────
# The landing page is a static file with comment placeholders. These builders
# fill them, so prices, reviews and social links change from the admin screen or
# an env var — never by editing HTML.

_PLAN_BULLETS = {
    "BASIC":   ["Record sales and credit", "Who owes you, at a glance", "Receipts you can send"],
    "GO":      ["Unlimited records", "Stock and low-stock alerts", "Reminders sent for you", "Reports and profit"],
    "PRO":     ["Everything in Go", "Staff accounts", "One branch, partner and investor", "Business scorecard"],
    "PREMIUM": ["Everything in Pro", "Unlimited branches and staff", "Unlimited partners and investors", "Priority support"],
}
_PLAN_NAMES = {"BASIC": "Basic", "GO": "Go", "PRO": "Pro", "PREMIUM": "Premium"}

# What a bullet says while WhatsApp is not approved yet.
_WA_PLAN_BULLETS = {"Reminders sent for you": "Due dates and who to chase"}

_SOCIAL_ICONS = {
    # The official single-path marks (Simple Icons, CC0), inlined so the page
    # still fetches nothing from a third party. Hand-drawn approximations are a
    # false economy here: a logo that is nearly right reads as broken.
    "facebook_url": ("Facebook", "M9.101 23.691v-7.98H6.627v-3.667h2.474v-1.58c0-4.085 1.848-5.978 5.858-5.978.401 0 .955.042 1.468.103a8.68 8.68 0 0 1 1.141.195v3.325a8.623 8.623 0 0 0-.653-.036 26.805 26.805 0 0 0-.733-.009c-.707 0-1.259.096-1.675.309a1.686 1.686 0 0 0-.679.622c-.258.42-.374.995-.374 1.752v1.297h3.919l-.386 2.103-.287 1.564h-3.246v8.245C19.396 23.238 24 18.179 24 12.044c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.628 3.874 10.35 9.101 11.647Z"),
    "instagram_url": ("Instagram", "M7.0301.084c-1.2768.0602-2.1487.264-2.911.5634-.7888.3075-1.4575.72-2.1228 1.3877-.6652.6677-1.075 1.3368-1.3802 2.127-.2954.7638-.4956 1.6365-.552 2.914-.0564 1.2775-.0689 1.6882-.0626 4.947.0062 3.2586.0206 3.6671.0825 4.9473.061 1.2765.264 2.1482.5635 2.9107.308.7889.72 1.4573 1.388 2.1228.6679.6655 1.3365 1.0743 2.1285 1.38.7632.295 1.6361.4961 2.9134.552 1.2773.056 1.6884.069 4.9462.0627 3.2578-.0062 3.668-.0207 4.9478-.0814 1.28-.0607 2.147-.2652 2.9098-.5633.7889-.3086 1.4578-.72 2.1228-1.3881.665-.6682 1.0745-1.3378 1.3795-2.1284.2957-.7632.4966-1.636.552-2.9124.056-1.2809.0692-1.6898.063-4.948-.0063-3.2583-.021-3.6668-.0817-4.9465-.0607-1.2797-.264-2.1487-.5633-2.9117-.3084-.7889-.72-1.4568-1.3876-2.1228C21.2982 1.33 20.628.9208 19.8378.6165 19.074.321 18.2017.1197 16.9244.0645 15.6471.0093 15.236-.005 11.977.0014 8.718.0076 8.31.0215 7.0301.0839m.1402 21.6932c-1.17-.0509-1.8053-.2453-2.2287-.408-.5606-.216-.96-.4771-1.3819-.895-.422-.4178-.6811-.8186-.9-1.378-.1644-.4234-.3624-1.058-.4171-2.228-.0595-1.2645-.072-1.6442-.079-4.848-.007-3.2037.0053-3.583.0607-4.848.05-1.169.2456-1.805.408-2.2282.216-.5613.4762-.96.895-1.3816.4188-.4217.8184-.6814 1.3783-.9003.423-.1651 1.0575-.3614 2.227-.4171 1.2655-.06 1.6447-.072 4.848-.079 3.2033-.007 3.5835.005 4.8495.0608 1.169.0508 1.8053.2445 2.228.408.5608.216.96.4754 1.3816.895.4217.4194.6816.8176.9005 1.3787.1653.4217.3617 1.056.4169 2.2263.0602 1.2655.0739 1.645.0796 4.848.0058 3.203-.0055 3.5834-.061 4.848-.051 1.17-.245 1.8055-.408 2.2294-.216.5604-.4763.96-.8954 1.3814-.419.4215-.8181.6811-1.3783.9-.4224.1649-1.0577.3617-2.2262.4174-1.2656.0595-1.6448.072-4.8493.079-3.2045.007-3.5825-.006-4.848-.0608M16.953 5.5864A1.44 1.44 0 1 0 18.39 4.144a1.44 1.44 0 0 0-1.437 1.4424M5.8385 12.012c.0067 3.4032 2.7706 6.1557 6.173 6.1493 3.4026-.0065 6.157-2.7701 6.1506-6.1733-.0065-3.4032-2.771-6.1565-6.174-6.1498-3.403.0067-6.156 2.771-6.1496 6.1738M8 12.0077a4 4 0 1 1 4.008 3.9921A3.9996 3.9996 0 0 1 8 12.0077"),
    "tiktok_url": ("TikTok", "M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.15 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z"),
    "whatsapp_url": ("WhatsApp", "M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z"),
}


def _social_links(db):
    """Link for each network: the admin setting first, then an env var, so a
    fresh deploy can carry links before anyone signs into the admin screen."""
    from feature_flags import whatsapp_live

    values = all_settings(db)
    live = whatsapp_live(db)
    out = []
    for key, (name, path) in _SOCIAL_ICONS.items():
        if key == "whatsapp_url" and not live:
            # An icon cannot say "coming soon", and a chat nobody can answer is
            # worse than no icon at all.
            continue
        url = (values.get(key) or os.getenv("SOCIAL_" + key.upper(), "")).strip()
        if key == "whatsapp_url" and not url:
            wa = os.getenv("TITI_WHATSAPP", "").strip().lstrip("+").replace(" ", "")
            url = f"https://wa.me/{wa}" if wa else ""
        if url.startswith(("http://", "https://")):
            out.append((name, path, url))
    return out


# What the page says while Meta has not approved the number: the truth about
# today, with WhatsApp named as coming rather than as something to press.
_WA_SOON = {
    "WA_BUTTON": '<span class="soon">💬 <b>tiTi on WhatsApp</b> — coming soon</span>',
    "WA_TRUST": "<span>✓ Works in any phone browser</span>",
    "WA_STEP": ("Open the web app in your browser — nothing to download, nothing to learn. "
                "Chatting with tiTi on WhatsApp is coming soon."),
    "WA_FAQ": ("No. CreditVoiceai runs in your browser and installs to your home screen like an app, "
               "so it works on any phone. Chatting with tiTi on WhatsApp is coming soon, and an "
               "Android app is on the way."),
    "WA_FAQ_JSONLD": ("No. CreditVoiceai runs in your browser and can be installed to your home "
                      "screen, so it works on any phone."),
    "WA_OS": "",
}


def _whatsapp_blocks(db):
    """Every line on the page that depends on WhatsApp being approved.

    While it is not, the page says what is true today and marks WhatsApp as
    coming — not as something a visitor can use now.
    """
    from feature_flags import whatsapp_live

    if whatsapp_live(db):
        wa = os.getenv("TITI_WHATSAPP", "").strip().lstrip("+").replace(" ", "")
        return {
            "WA_BUTTON": (f'<a class="btn ghost" href="https://wa.me/{_esc(wa)}">Message tiTi on WhatsApp</a>'
                          if wa else ""),
            "WA_TRUST": "<span>✓ Works on WhatsApp</span>",
            "WA_STEP": "Open the web app or message tiTi on WhatsApp. No download, no training.",
            "WA_FAQ": ("No. You can use CreditVoiceai on the web or by chatting with tiTi on WhatsApp. "
                       "You can install the web app to your home screen, and an Android app is coming."),
            "WA_FAQ_JSONLD": ("No. You can use CreditVoiceai on the web or by chatting with tiTi on "
                              "WhatsApp. You can also install the web app to your home screen."),
            "WA_OS": ", WhatsApp",
        }
    return dict(_WA_SOON)


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


def _pricing_html(whatsapp=False):
    """The plans, with the yearly saving shown rather than described.

    The switch is a checkbox the CSS reads, so the prices change with no
    JavaScript — the same reason every other number here is server-rendered.
    """
    from messages import get_plan_price
    from plans import PLAN_BASIC, PLAN_GO, PLAN_PREMIUM, PLAN_PRO

    cards = []
    for plan in (PLAN_BASIC, PLAN_GO, PLAN_PRO, PLAN_PREMIUM):
        price = get_plan_price(plan)
        yearly = get_plan_price(plan, "YEARLY")
        featured = ' featured' if plan == PLAN_PRO else ''
        if price:
            amount = (f'<span class="per-m">₦{price:,}<small> /month</small></span>'
                      f'<span class="per-y">₦{yearly:,}<small> /year</small></span>')
        else:
            amount = "Free"
        # Sending a reminder needs the approved WhatsApp number; listing it as a
        # paid-plan feature before then would be selling something undeliverable.
        lines = [b if whatsapp or b not in _WA_PLAN_BULLETS else _WA_PLAN_BULLETS[b]
                 for b in _PLAN_BULLETS.get(plan, [])]
        bullets = "".join(f"<li>{_esc(b)}</li>" for b in lines)
        cta = "Start free" if not price else f"Choose {_PLAN_NAMES[plan]}"
        note = ('<div class="plan-note per-y">Two months free</div>'
                if price and yearly else '')
        cards.append(
            f'<div class="plan{featured}">'
            f'<h3>{_PLAN_NAMES[plan]}</h3>'
            f'<div class="price">{amount}</div>'
            f'{note}'
            f'<ul>{bullets}</ul>'
            f'<a class="btn{"" if price else " ghost"}" href="/app">{cta}</a>'
            f'</div>'
        )
    return (
        '<div class="pricing-wrap">'
        '<input type="checkbox" id="yearly-toggle" class="pricing-toggle" />'
        '<label class="pricing-switch" for="yearly-toggle">'
        '<span class="opt m">Monthly</span>'
        '<span class="track"><span class="knob"></span></span>'
        '<span class="opt y">Yearly <b>save 2 months</b></span>'
        '</label>'
        f'<div class="plans">{"".join(cards)}</div>'
        '</div>'
    )


def _finance_html(db):
    """The one claim neither QuickBooks nor Bumpa can make.

    They sell bookkeeping and an online store. We turn the bookkeeping into
    evidence a financier will act on — so the page shows the actual scorecard
    components and what each is worth, read from the live config rather than
    typed in here, and says plainly who decides and who does not lend.
    """
    from business_scorecard import DEFAULT_CONFIG, config_for_partner
    from models import FinancePartner

    try:
        _version, config, _rules = config_for_partner(db, None)
    except Exception:
        _log.exception("landing finance block fell back to the default config")
        config = DEFAULT_CONFIG

    components = sorted(
        (c for c in (config.get("components") or {}).values() if c.get("weight")),
        key=lambda c: -int(c.get("weight") or 0),
    )[:5]
    top = max((int(c.get("weight") or 0) for c in components), default=1) or 1
    bars = "".join(
        f'<div class="bar"><span class="bar-l">{_esc(c.get("label") or "")}</span>'
        f'<span class="bar-t"><span class="bar-f" style="width:{round(100 * int(c["weight"]) / top)}%"></span></span>'
        f'<span class="bar-w">{int(c["weight"])}%</span></div>'
        for c in components
    )

    try:
        partners = (
            db.query(FinancePartner)
            .filter(FinancePartner.is_active == True)      # noqa: E712
            .count()
        )
    except Exception:
        partners = 0
    # Only a real count is worth printing; with none on board the proposition is
    # still true — the score is yours either way — so the line simply goes.
    partner_line = (
        f'<p class="fin-count">{partners} financing partner{"s" if partners != 1 else ""} '
        f'reviewing applications on CreditVoice</p>'
        if partners else ""
    )

    return f"""
    <div class="fin-grid">
      <div class="fin-copy">
        <p class="eyebrow light">What your records are worth</p>
        <h2>Records today. Financing tomorrow.</h2>
        <p class="fin-lead">
          Every sale, debt and repayment you record builds a business scorecard — proof
          that you trade, and how well. When you want a freezer, a generator, a bike or
          stock on installments, that record is what speaks for you.
        </p>
        <ol class="fin-steps">
          <li><b>You keep your records</b><span>Sales, credit, stock — the work you already do.</span></li>
          <li><b>tiTi scores your business</b><span>And tells you exactly which part to improve.</span></li>
          <li><b>A partner decides</b><span>They supply the asset; repayments are recorded here.</span></li>
        </ol>
        {partner_line}
        <div class="cta">
          <a class="btn yellow" href="/app">See your business score</a>
          <a class="btn light" href="/app">Browse offers</a>
        </div>
        <p class="fin-note">
          CreditVoice does not lend money and does not decide who is approved. Your records
          are only shared with a partner when you apply and agree to share them.
        </p>
      </div>

      <div class="fin-card" aria-hidden="true">
        <div class="fin-card-top">
          <span>Business score</span><span class="fin-tier">Strong</span>
        </div>
        <div class="fin-score"><b>72</b><span>/100</span></div>
        <div class="fin-bars">{bars}</div>
        <div class="fin-foot">What each part is worth, from the live scorecard</div>
      </div>
    </div>"""


def _compact_money(amount):
    """₦2.4m / ₦340k / ₦5,200 — a figure a trader reads at a glance."""
    amount = int(amount or 0)
    if amount >= 1_000_000_000:
        return f"₦{amount / 1_000_000_000:.1f}b".replace(".0b", "b")
    if amount >= 1_000_000:
        return f"₦{amount / 1_000_000:.1f}m".replace(".0m", "m")
    if amount >= 100_000:
        return f"₦{amount // 1000:,}k"
    return f"₦{amount:,}"


def _compact_count(n):
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}m".replace(".0m", "m")
    if n >= 10_000:
        return f"{n // 1000:,}k"
    return f"{n:,}"


def _stats(db):
    """What the platform has actually done, counted — never typed in by hand.

    These are the numbers a visitor is owed: a stranger is being asked to trust
    us with their books. Bumpa's homepage ships "Trusted by over 0 SMEs" because
    their counter only runs in JavaScript; ours is counted here and printed into
    the HTML, so it is right for crawlers, link previews and slow phones too.
    """
    from sqlalchemy import func

    from models import Customer, Transaction, User

    businesses = (
        db.query(func.count(User.id))
        .filter(User.parent_id.is_(None))
        .scalar()
    ) or 0
    records = db.query(func.count(Transaction.id)).scalar() or 0
    credit_tracked = (
        db.query(func.coalesce(func.sum(Customer.balance), 0))
        .filter(Customer.balance > 0)
        .scalar()
    ) or 0
    return {
        "businesses": int(businesses),
        "records": int(records),
        "credit_tracked": int(credit_tracked),
    }


def _stats_html(db):
    """The band under the hero. Hidden only if an admin turns it off."""
    if str(get_setting(db, "show_stats", "yes")).strip().lower() in ("no", "off", "0", "false"):
        return ""
    try:
        s = _stats(db)
    except Exception:
        _log.exception("landing stats failed")
        return ""

    # A figure of zero is worse than no figure: it is the first thing a visitor
    # reads and it says nobody is here. Empty ones are left out, and if nothing
    # has happened yet the band does not appear at all.
    cells = [
        (s["businesses"], _compact_count(s["businesses"]), "businesses keeping their records"),
        (s["records"], _compact_count(s["records"]), "sales and payments recorded"),
        (s["credit_tracked"], _compact_money(s["credit_tracked"]), "in customer credit being tracked"),
    ]
    cells = [(value, label) for raw, value, label in cells if raw > 0]
    if not cells:
        return ""
    # data-to lets the number count up on arrival; the final figure is already in
    # the HTML, so it reads correctly with no JavaScript at all.
    items = "".join(
        f'<div class="stat"><span class="stat-n" data-to="{_esc(value)}">{_esc(value)}</span>'
        f'<span class="stat-l">{_esc(label)}</span></div>'
        for value, label in cells
    )
    return f'<div class="stats">{items}</div>'


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
    # The WhatsApp defaults are the cautious ones: if the database cannot be
    # read, the page must still not promise a channel that isn't approved.
    from feature_flags import whatsapp_live

    blocks = {"PRICING": "", "REVIEWS": "", "SOCIAL": "", "STATS": "", "FINANCE": ""}
    blocks.update(_WA_SOON)
    db = None
    live = False
    try:
        db = SessionLocal()
        live = whatsapp_live(db)
        blocks["STATS"] = _stats_html(db)
        blocks["FINANCE"] = _finance_html(db)
        blocks["REVIEWS"] = _reviews_html(db)
        blocks["SOCIAL"] = _social_html(db)
        blocks.update(_whatsapp_blocks(db))
    except Exception:
        _log.exception("landing reviews/social block failed")
    try:
        blocks["PRICING"] = _pricing_html(live)
    except Exception:
        _log.exception("landing pricing block failed")
    finally:
        if db is not None:
            db.close()
    return blocks
