from pathlib import Path
from typing import Optional
import base64
import json
import os
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from fastapi import Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from database import SessionLocal
from models import (
    AppNotification, AutomationSettings, Branch, Customer, FailedParse, FastCaptureSettings,
    InventoryItem, InventoryMovement, PendingAction, Referral, ReferralSettings,
    ReminderAutomationSettings, ReminderQueue,
    Supplier, SupplierPayment, SupplierPurchase, TokenCode, Transaction, TransactionItem, User, utcnow,
)
from parser import normalize_voice_transcript, parse_message, transcribe_audio_bytes
from reports import (
    dashboard_period_label,
    get_balance,
    get_dashboard_summary,
    get_margin_summary,
    get_owner_transaction_query,
    get_product_sales_by_period,
    get_staff_performance,
    get_unpaid_debtors,
)
from subscriptions import get_business_subscription
from transaction_save import save_confirmed_pending_transaction
from transaction_setup import handle_transaction_setup
from web_auth import (
    clear_auth_cookie, get_otp_channels, require_web_auth,
    set_auth_cookie, web_login, web_register, request_web_otp, verify_otp_and_set_pin,
)
from web_pos import get_pos_receipt, save_pos_sale
from webhook_context import load_webhook_user_context, visibility_recorded_by_id


# Rate limiters live in web_common now (shared across the web route modules).
from web_common import (
    _demo_rate_check, _ai_rate_check, _admin_rate_check,
    _export_rate_check, _redeem_rate_check,
)


WEB_ROOT = Path(__file__).parent / "web"
DIST_ROOT = WEB_ROOT / "dist"
DIST_INDEX = DIST_ROOT / "index.html"
LEGACY_INDEX = WEB_ROOT / "index.html"


def _read_index():
    if DIST_INDEX.exists():
        return DIST_INDEX.read_text(encoding="utf-8")
    if LEGACY_INDEX.exists():
        return LEGACY_INDEX.read_text(encoding="utf-8")
    return "<h1>Frontend not built. Run: cd frontend && npm run build</h1>"


# The whole SPA is served from one shell, so without this every /app/* URL would
# return byte-identical HTML — which is why Search Console flagged "Duplicate
# without user-selected canonical". _render_index makes the shell path-aware:
#   • a self-referencing <link rel="canonical"> on every page;
#   • a distinct <title>/<description> for the public legal pages (so they are
#     indexable and not seen as duplicates of each other);
#   • <meta robots="noindex,follow"> on every app screen (login/dashboard/etc.)
#     — those are an application, not content, and must not be indexed.
_SITE_ORIGIN = "https://creditvoiceai.com"

_SEO_PAGES = {
    "/app/terms": (
        "Terms of Service — CreditVoice",
        "The terms governing your use of CreditVoice and tiTi.",
    ),
    "/app/privacy": (
        "Privacy Policy — CreditVoice",
        "How CreditVoice collects, uses, and protects your data under the Nigeria Data Protection Act (NDPA).",
    ),
}


def _render_index(path="/app"):
    import re
    html = _read_index()
    clean = "/" + path.strip("/") if path.strip("/") else "/app"
    canonical = f'<link rel="canonical" href="{_SITE_ORIGIN}{clean}" />'
    seo = _SEO_PAGES.get(clean)
    head_extra = canonical
    if seo:
        title, desc = seo
        html = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", html, count=1, flags=re.S)
        html = re.sub(r'<meta name="description"[^>]*>',
                      f'<meta name="description" content="{desc}" />', html, count=1)
    else:
        head_extra += '\n    <meta name="robots" content="noindex,follow" />'
    return html.replace("</head>", f"    {head_extra}\n  </head>", 1)


# ── Pydantic request models ──────────────────────────────────────────────────

# Auth/account request models live in web_auth_routes now.

# StaffInviteRequest / StaffAcceptRequest live in web_staff_routes now.
# FastModeToggleRequest lives in web_dashboard_routes now.
# Chat/Capture request models live in web_chat_routes now.

# POS request models live in web_pos_routes now.
# Inventory request models + routes live in web_inventory_routes now.


# Customer/Delivery/Transaction request models live in web_customer_routes now.
# CreateBranchRequest lives in web_branch_routes now.


# ── Helpers ──────────────────────────────────────────────────────────────────

# Shared session/scope/format/inventory-limit helpers now live in web_common,
# so the per-domain route modules can import them without importing this monolith.
from web_common import (
    _get_db, _money, _iso, _safe_filename, _owner_filter,
    _active_inventory_count, _check_inventory_limit,
    _session_user, _session_owner_phone, _session_branch_scope,
    _scoped_read, _require_tx_in_scope, _require_stock_manager,
    _session_subscription, _add_notification, _send_web_receipt,
)


# _send_web_receipt now lives in web_common; the capture/demo helpers
# (_pending_payload, _capture_messages, _preview_capture, _format_demo_reply)
# moved into web_chat_routes with the chat/capture endpoints.


# ── Route registration ───────────────────────────────────────────────────────

_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "media-src 'self' blob:; "
    "worker-src 'self' blob:; "
    "manifest-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def register_web_routes(app):
    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path

        # Cache-Control: API responses must never be cached (sensitive financial data)
        if path.startswith("/app/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        # Hashed Vite assets are immutable — cache aggressively for performance
        elif path.startswith("/app/assets/") or path.startswith("/web/static/"):
            response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
        # SPA HTML shell — never cache so deploys take effect immediately
        else:
            response.headers.setdefault("Cache-Control", "no-store")

        response.headers.setdefault("Content-Security-Policy", _CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if os.getenv("ENVIRONMENT", "production") != "development":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response

    # ── Static assets from React build ──────────────────────────────────
    if (DIST_ROOT / "assets").exists():
        app.mount("/app/assets", StaticFiles(directory=DIST_ROOT / "assets"), name="dist_assets")
    else:
        # Assets not built yet — return 404 so the browser shows an error
        # instead of falling through to the SPA catch-all (which would serve
        # index.html as JS/CSS, causing a silent blank page).
        @app.get("/app/assets/{file_path:path}")
        def dist_assets_not_built(file_path: str):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Frontend not built. Run: cd frontend && npm run build")

    if (WEB_ROOT / "static").exists():
        app.mount("/web/static", StaticFiles(directory=WEB_ROOT / "static"), name="web_static")

    # ── SPA root (exact) ─────────────────────────────────────────────────
    @app.get("/app", response_class=HTMLResponse)
    def web_app_root():
        return _render_index("/app")

    # ── Auth + account (NDPR, me) — split into web_auth_routes ────────────────
    from web_auth_routes import register_auth_routes
    register_auth_routes(app)

    # ── Dashboard + Fast Mode — split into web_dashboard_routes ───────────────
    from web_dashboard_routes import register_dashboard_routes
    register_dashboard_routes(app)

    # ── Chat + Capture — split into web_chat_routes ───────────────────────────
    from web_chat_routes import register_chat_routes
    register_chat_routes(app)

    # ── POS + invoices — split into web_pos_routes ────────────────────────────
    from web_pos_routes import register_pos_routes
    register_pos_routes(app)

    # ── Customers + Deliveries + Transactions — split into web_customer_routes ─
    from web_customer_routes import register_customer_routes
    register_customer_routes(app)

    # ── Inventory — split into web_inventory_routes ───────────────────────────
    from web_inventory_routes import register_inventory_routes
    register_inventory_routes(app)

    # ── Suppliers — split into web_supplier_routes ────────────────────────────
    from web_supplier_routes import register_supplier_routes
    register_supplier_routes(app)

    # ── Staff (performance, roster, invite/accept, profiles) — split out ──────
    from web_staff_routes import register_staff_routes
    register_staff_routes(app)

    # ── Branches — split into web_branch_routes ───────────────────────────────
    from web_branch_routes import register_branch_routes
    register_branch_routes(app)

    # ── Wallet (+ Monnify webhook & provision) — split into web_wallet_routes ─
    from web_wallet_routes import register_wallet_routes
    register_wallet_routes(app)

    # ── School Teacher Roster — split into web_school_routes ──────────────────
    from web_school_routes import register_school_routes
    register_school_routes(app)

    # ── Poultry farm (daily egg collection + feed usage) ──────────────────────
    from web_poultry_routes import register_poultry_routes
    register_poultry_routes(app)

    # ── Filling-station operations (fuel businesses) ──────────────────────────
    from web_fuel_routes import register_fuel_routes
    register_fuel_routes(app)

    # ── Partners & Business notes — split into their own modules ──────────────
    from web_partner_routes import register_partner_routes
    from web_notes_routes import register_notes_routes
    register_partner_routes(app)
    register_notes_routes(app)

    # ── Thrift / Ajo — split into web_thrift_routes ───────────────────────────
    from web_thrift_routes import register_thrift_routes
    register_thrift_routes(app)

    # ── Subscription / Upgrade — split into web_subscription_routes ───────────
    from web_subscription_routes import register_subscription_routes
    register_subscription_routes(app)

    # ── Reminders + Automation — split into web_reminder_routes ───────────────
    from web_reminder_routes import register_reminder_routes
    register_reminder_routes(app)

    # ── Export + loan-statement — split into web_export_routes ────────────────
    from web_export_routes import register_export_routes
    register_export_routes(app)

    # ── Notifications (the bell) — split into web_notifications_routes ────────
    from web_notifications_routes import register_notification_routes
    register_notification_routes(app)

    # ── Admin dashboard (notifications, failed-parses, stats, users) — split ──
    from web_admin_routes import register_admin_routes
    register_admin_routes(app)

    # ── Referral system — split into web_referral_routes ──────────────────────
    from web_referral_routes import register_referral_routes
    register_referral_routes(app)

    # ── Token codes — split into web_token_routes ─────────────────────────────
    from web_token_routes import register_token_routes
    register_token_routes(app)

    # ── TWA / Play Store: Digital Asset Links ────────────────────────────────
    @app.get("/.well-known/assetlinks.json")
    def assetlinks():
        """Required for Google Play Store TWA to verify domain ownership.
        Set TWA_PACKAGE_NAME and TWA_SHA256_FINGERPRINT in .env after generating
        your Android package via pwabuilder.com.
        """
        import json as _json, os
        package   = os.getenv("TWA_PACKAGE_NAME", "")
        sha256    = os.getenv("TWA_SHA256_FINGERPRINT", "")
        if not package or not sha256:
            return []          # returns empty array until configured — TWA will skip
        return _json.loads(f'''[{{
          "relation": ["delegate_permission/common.handle_all_urls"],
          "target": {{
            "namespace": "android_app",
            "package_name": "{package}",
            "sha256_cert_fingerprints": ["{sha256}"]
          }}
        }}]''')

    # ── Verified supplier directory + opportunities ───────────────────────
    from supplier_routes import register_supplier_routes
    register_supplier_routes(app)

    # ── Root-level dist files (favicon, logo, icons) ────────────────────────
    # These live in web/dist/ root but NOT under /app/assets/, so requests
    # would otherwise hit the SPA catch-all and be served as HTML.
    _STATIC_TYPES = {
        ".png": "image/png",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
        ".html": "text/html",
        ".webmanifest": "application/manifest+json",
        ".js": "application/javascript",
    }
    _DIST_ROOT_STATIC = [
        "favicon.png", "favicon.svg", "logo.png", "icons.svg", "offline.html",
        # PWA install support — must be served as real files, not the SPA shell.
        "manifest.webmanifest", "sw.js", "pwa-192.png", "pwa-512.png",
    ]
    for _sf in _DIST_ROOT_STATIC:
        _fp = DIST_ROOT / _sf
        if not _fp.exists():
            continue
        _mt = _STATIC_TYPES.get(_fp.suffix, "application/octet-stream")
        def _make_static_route(file_path, media_type):
            def _route():
                return FileResponse(str(file_path), media_type=media_type)
            return _route
        app.add_api_route(
            f"/app/{_sf}",
            _make_static_route(_fp, _mt),
            methods=["GET"],
            include_in_schema=False,
        )

    # ── SPA catch-all (MUST be last — catches all /app/* client-side routes) ──
    @app.get("/app/{full_path:path}", response_class=HTMLResponse)
    def web_app_spa(full_path: str):
        return _render_index(f"/app/{full_path}")
