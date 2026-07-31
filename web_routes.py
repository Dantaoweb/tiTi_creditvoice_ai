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


# ── Pydantic request models ──────────────────────────────────────────────────

class LoginRequest(BaseModel):
    phone: str = Field(max_length=20)
    pin: str = Field(max_length=10)

class RegisterRequest(BaseModel):
    name: str = Field(max_length=120)
    phone: str = Field(max_length=20)
    pin: str = Field(max_length=10)
    email: Optional[str] = Field(default=None, max_length=254)
    newsletter_consent: bool = False
    business_category: Optional[str] = Field(default=None, max_length=60)
    business_type: Optional[str] = Field(default=None, max_length=60)
    business_type_label: Optional[str] = Field(default=None, max_length=120)
    ref_code: Optional[str] = Field(default=None, max_length=20)

class OtpRequest(BaseModel):
    phone: str = Field(max_length=20)
    channel: str = Field(default="auto", max_length=20)
    email: str = Field(default="", max_length=200)

class SetPinRequest(BaseModel):
    phone: str = Field(max_length=20)
    otp: str = Field(max_length=10)
    new_pin: str = Field(max_length=10)


class DemoChatRequest(BaseModel):
    text: str = Field(max_length=500)

class ChatSendRequest(BaseModel):
    text: str = Field(max_length=2000)

# StaffInviteRequest / StaffAcceptRequest live in web_staff_routes now.

class FastModeToggleRequest(BaseModel):
    enabled: bool
    start_hour: Optional[int] = None
    end_hour: Optional[int] = None

class CapturePreviewRequest(BaseModel):
    phone: str = Field(max_length=20)
    text: str = Field(max_length=2000)


class CaptureConfirmRequest(BaseModel):
    phone: str = Field(max_length=20)


class CaptureVoiceRequest(BaseModel):
    phone: str = Field(max_length=20)
    audio_base64: str = Field(max_length=2_000_000)  # ~1.5 MB binary
    mime_type: Optional[str] = Field(default="audio/webm", max_length=50)


class PosCartItem(BaseModel):
    inventory_item_id: Optional[int] = None
    name: str = Field(max_length=120)
    qty: float = 1.0
    unit: Optional[str] = Field(default=None, max_length=30)
    unit_price: int = 0
    sold_unit: Optional[str] = Field(default=None, max_length=30)
    fraction: Optional[float] = 1.0


class PosSaveRequest(BaseModel):
    owner_phone: str = Field(max_length=20)
    customer_id: Optional[int] = None
    customer_name: Optional[str] = Field(default=None, max_length=120)   # inline new/unlisted customer
    customer_phone: Optional[str] = Field(default=None, max_length=20)   # optional, not required
    items: list[PosCartItem] = Field(max_length=200)  # max 200 line items per sale
    payment_amount: int = 0
    branch_id: Optional[int] = None
    due_date: Optional[datetime] = None
    service_date: Optional[datetime] = None   # promised delivery / ready-by date


# Inventory request models + routes live in web_inventory_routes now.


class AddCustomerRequest(BaseModel):
    owner_phone: str = Field(max_length=20)
    name: str = Field(max_length=120)
    phone: Optional[str] = Field(default=None, max_length=20)


class RecordPaymentRequest(BaseModel):
    amount: int
    note: Optional[str] = Field(default=None, max_length=500)
    branch_id: Optional[int] = None


class SetTransactionDueDateRequest(BaseModel):
    due_date: Optional[str] = None  # ISO date string "YYYY-MM-DD" or null to clear


# CreateBranchRequest lives in web_branch_routes now.


# ── Helpers ──────────────────────────────────────────────────────────────────

# Shared session/scope/format/inventory-limit helpers now live in web_common,
# so the per-domain route modules can import them without importing this monolith.
from web_common import (
    _get_db, _money, _iso, _safe_filename, _owner_filter,
    _active_inventory_count, _check_inventory_limit,
    _session_user, _session_owner_phone, _session_branch_scope,
    _scoped_read, _require_tx_in_scope, _require_stock_manager,
    _session_subscription, _add_notification,
)


def _send_web_receipt(db, owner_phone, tx_id):
    """Best-effort: send the customer their receipt on WhatsApp after a web sale
    or payment (mirrors the WhatsApp flow). No-op if the customer has no phone."""
    if not tx_id:
        return
    try:
        from web_pos import get_pos_receipt, format_receipt_text
        from whatsapp_client import send_whatsapp_message
        owner_user = db.query(User).filter(User.phone == owner_phone).first()
        receipt = get_pos_receipt(db, tx_id, user=owner_user)
        if not receipt:
            return
        phone = (receipt.get("customer") or {}).get("phone")
        if not phone:
            return
        send_whatsapp_message(phone, format_receipt_text(receipt))
    except Exception:
        import traceback; traceback.print_exc()


def _pending_payload(pending):
    if not pending:
        return None
    try:
        items = json.loads(pending.items_json or "[]")
    except json.JSONDecodeError:
        items = []
    return {
        "id": pending.id,
        "action": pending.action,
        "customer_name": pending.customer_name,
        "customer_phone": pending.customer_phone,
        "buy_amount": _money(pending.buy_amount),
        "paid_amount": _money(pending.paid_amount),
        "product": pending.product,
        "quantity": pending.quantity,
        "unit": pending.unit,
        "unit_price": _money(pending.unit_price),
        "due_date": _iso(pending.due_date),
        "items": items,
    }


def _capture_messages():
    messages = []

    def send_message(_phone, message):
        messages.append(message)

    return messages, send_message


def _preview_capture(db, phone, text, voice_transcript_text=None):
    if not phone or not text:
        return {
            "status": "error",
            "message": "Enter a registered phone number and transaction text.",
        }

    context = load_webhook_user_context(db, phone, "text")
    if not context.user:
        return {
            "status": "unregistered",
            "message": "This phone is not registered yet. Onboard the user before recording transactions.",
        }

    parsed = parse_message(text)
    if not parsed or "action" not in parsed:
        return {
            "status": "unsupported",
            "message": "I could not read this as a sale, credit, or payment yet.",
            "parsed": parsed,
            "transcript": text if voice_transcript_text else None,
        }

    parsed["raw_text"] = text
    subscription = get_business_subscription(db, context.user)
    messages, send_message = _capture_messages()
    result = handle_transaction_setup(
        db,
        phone,
        parsed,
        context.user,
        context.business_owner_phone,
        subscription,
        visibility_recorded_by_id(context.user),
        voice_transcript_text,
        send_message,
    )
    pending = db.query(PendingAction).filter(
        PendingAction.phone == phone,
        PendingAction.action != None,
    ).order_by(PendingAction.created_at.desc()).first()
    return {
        "status": (result or {}).get("status", "preview"),
        "messages": messages,
        "parsed": parsed,
        "pending": _pending_payload(pending),
        "transcript": text if voice_transcript_text else None,
    }


# ── Demo chat response formatter ─────────────────────────────────────────────

def _format_demo_reply(parsed) -> str:
    if not parsed or "action" not in parsed:
        return "I get you! 😊 Register now to record real transactions in your own way. Just describe a sale, payment, or stock in your own words and I'll get it."

    action  = (parsed.get("action") or "").upper()
    product = (parsed.get("product") or "").strip()
    qty     = parsed.get("quantity")
    unit    = (parsed.get("unit") or "").strip()
    price   = int(parsed.get("total_price") or parsed.get("unit_price") or 0)
    customer = (parsed.get("customer_name") or "").strip()

    price_str = f"₦{price:,}" if price else ""
    if qty and unit and product:
        item = f"{qty} {unit} of {product}"
    elif qty and product:
        item = f"{qty} {product}"
    elif product:
        item = product
    else:
        item = "that item"

    if action in ("SELL", "SALE") and customer:
        msg = f"Sale of {item} to *{customer}*"
        if price_str: msg += f" — {price_str}"
    elif action in ("SELL", "SALE"):
        msg = f"Cash sale of {item}"
        if price_str: msg += f" — {price_str}"
    elif action == "BUY" and customer:
        msg = f"Credit sale of {item} to *{customer}*"
        if price_str: msg += f" — {price_str}"
        msg += f"\n{customer}'s balance would increase."
    elif action == "PAY" and customer:
        msg = f"Payment of {price_str} from *{customer}*" if price_str else f"Payment from *{customer}*"
        msg += "\nTheir balance reduces."
    elif action in ("SUPPLY", "RESTOCK", "BUY"):
        msg = f"Stock-in: {item}"
        if price_str: msg += f" — cost {price_str}"
        msg += "\nYour inventory would go up."
    else:
        msg = f"Transaction understood ({action.lower()})"

    return f"Got it! 👍\n\n{msg}\n\nSign up to record real transactions."


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
        return _read_index()

    # ── Auth ─────────────────────────────────────────────────────────────
    @app.post("/app/api/auth/login")
    def web_auth_login(payload: LoginRequest, response: Response, request: Request):
        db = SessionLocal()
        try:
            ip = request.client.host if request.client else None
            result = web_login(db, payload.phone.strip(), payload.pin.strip(), ip=ip)
            set_auth_cookie(response, result.pop("_token"))
            return result
        finally:
            db.close()

    @app.get("/app/api/auth/business-categories")
    def web_business_categories():
        from business_templates import BUSINESS_CATEGORIES
        return {
            "categories": [
                {
                    "key": c["key"],
                    "label": c["label"],
                    "businesses": [
                        {"key": b[0], "label": b[1]} for b in c["businesses"]
                    ],
                }
                for c in BUSINESS_CATEGORIES
            ]
        }

    @app.post("/app/api/auth/register")
    def web_auth_register(payload: RegisterRequest, response: Response, request: Request):
        db = SessionLocal()
        try:
            client_ip = request.client.host if request.client else "unknown"
            result = web_register(
                db,
                payload.name.strip(),
                payload.phone.strip(),
                payload.pin.strip(),
                email=payload.email,
                newsletter_consent=payload.newsletter_consent,
                business_category=payload.business_category,
                business_type=payload.business_type,
                business_type_label=payload.business_type_label,
                ref_code=payload.ref_code,
                client_ip=client_ip,
            )
            set_auth_cookie(response, result.pop("_token"))
            return result
        finally:
            db.close()

    @app.get("/app/api/auth/config")
    def web_auth_config():
        import os
        titi_number = os.getenv("TITI_WHATSAPP", "").strip()
        return {"titi_whatsapp": titi_number}

    @app.get("/app/api/auth/otp-channels")
    def web_otp_channels(phone: str = Query(...), request: Request = None):
        from web_auth import _rate_check, _PROBE_LIMIT, _PROBE_WINDOW
        client_ip = request.client.host if request and request.client else "unknown"
        if not _rate_check(f"probe:{client_ip}", _PROBE_LIMIT, _PROBE_WINDOW):
            raise HTTPException(status_code=429, detail="Too many requests. Please slow down.")
        db = SessionLocal()
        try:
            return get_otp_channels(db, phone.strip())
        finally:
            db.close()

    @app.post("/app/api/auth/request-otp")
    def web_request_otp(payload: OtpRequest):
        db = SessionLocal()
        try:
            return request_web_otp(db, payload.phone.strip(), payload.channel,
                                   email=payload.email.strip() if payload.email else None)
        finally:
            db.close()

    @app.post("/app/api/auth/set-pin")
    def web_set_pin(payload: SetPinRequest, response: Response):
        db = SessionLocal()
        try:
            result = verify_otp_and_set_pin(db, payload.phone.strip(), payload.otp.strip(), payload.new_pin.strip())
            set_auth_cookie(response, result.pop("_token"))
            return result
        finally:
            db.close()

    @app.post("/app/api/auth/logout")
    def web_auth_logout(response: Response):
        clear_auth_cookie(response)
        return {"ok": True}

    @app.post("/app/api/auth/logout-all")
    def web_auth_logout_all(response: Response, session: dict = Depends(require_web_auth)):
        """Sign out of every device: bump the user's session epoch so all tokens
        issued so far stop working immediately."""
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if user:
                user.token_version = (user.token_version or 0) + 1
                db.commit()
            clear_auth_cookie(response)
            return {"ok": True, "message": "Signed out of all devices."}
        finally:
            db.close()

    class ProfileUpdateRequest(BaseModel):
        name: Optional[str] = Field(default=None, max_length=120)
        business_type_label: Optional[str] = Field(default=None, max_length=120)
        address: Optional[str] = Field(default=None, max_length=300)

    @app.put("/app/api/auth/profile")
    def web_update_profile(payload: ProfileUpdateRequest, session: dict = Depends(require_web_auth)):
        """Edit the signed-in user's profile. Everyone may change their own
        display name; the business label/address (which appear on receipts) are
        the owner's, so only a business owner can change those."""
        db = SessionLocal()
        try:
            user = _session_user(db, session)
            if not user:
                raise HTTPException(status_code=401, detail="User not found.")
            if payload.name is not None and payload.name.strip():
                user.name = payload.name.strip()
            is_owner = user.parent_id is None
            if is_owner:
                if payload.business_type_label is not None:
                    user.business_type_label = payload.business_type_label.strip() or None
                if payload.address is not None:
                    user.address = payload.address.strip() or None
            db.commit()
            return {
                "ok": True,
                "name": user.name,
                "business_type_label": user.business_type_label,
                "address": user.address,
            }
        finally:
            db.close()

    # ── NDPR: right to erasure ────────────────────────────────────────────────
    class DeleteAccountRequest(BaseModel):
        pin: str

    @app.delete("/app/api/account")
    def web_delete_account(
        payload: DeleteAccountRequest,
        response: Response,
        session: dict = Depends(require_web_auth),
    ):
        """Permanently anonymise the caller's account (NDPR s.2.6 right to erasure).

        PII cleared: name, email, recovery_pin_hash, referral_code, shop_tag,
        newsletter_consent. Phone replaced with a non-reversible placeholder.
        Raw message logs (parse_logs, failed_parses) deleted. The User row is
        kept so that transaction foreign keys remain intact; deleted_at marks it
        as erased.  Logs the deletion in audit_log and clears the session cookie.
        """
        from recovery_commands import _verify_pin
        from audit import audit
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=404, detail="User not found.")
            if user.deleted_at:
                raise HTTPException(status_code=409, detail="Account already deleted.")
            if not user.recovery_pin_hash or not _verify_pin(payload.pin.strip(), user.recovery_pin_hash):
                raise HTTPException(status_code=401, detail="Incorrect PIN.")

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            anon_phone = f"DELETED_{user.id}"

            # Anonymise PII fields on the user record
            user.name               = "Deleted User"
            user.email              = None
            user.recovery_pin_hash  = None
            user.referral_code      = None
            user.shop_tag           = None
            user.newsletter_consent = False
            user.whatsapp_linked    = False
            user.pin_attempts       = 0
            user.pin_locked_until   = None
            user.deleted_at         = now

            # Replace phone with a non-reversible placeholder so the unique
            # constraint is freed and the original phone can re-register later
            from models import ParseLog, FailedParse
            db.query(ParseLog).filter(ParseLog.phone == user.phone).delete()
            db.query(ParseLog).filter(ParseLog.owner_phone == user.phone).delete()
            db.query(FailedParse).filter(FailedParse.phone == user.phone).delete()
            db.query(FailedParse).filter(FailedParse.owner_phone == user.phone).delete()

            audit(db, action="ACCOUNT_DELETION", actor_id=user.id,
                  actor_phone=user.phone, resource=f"user:{user.id}")

            user.phone = anon_phone
            db.commit()
            clear_auth_cookie(response)
            return {"ok": True, "message": "Your account and personal data have been deleted."}
        finally:
            db.close()

    # ── NDPR: data subject access request (DSAR) ─────────────────────────────
    @app.get("/app/api/account/personal-data")
    def web_personal_data(session: dict = Depends(require_web_auth)):
        """Return a copy of all personal data held for this user (NDPR s.2.5)."""
        from models import Customer, Transaction, ParseLog
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=404, detail="User not found.")

            tx_count  = db.query(Transaction).filter(Transaction.owner_phone == user.phone).count()
            cust_count= db.query(Customer).filter(Customer.owner_phone == user.phone).count()
            log_count = db.query(ParseLog).filter(ParseLog.phone == user.phone).count()

            return {
                "personal_data": {
                    "name":                user.name,
                    "phone":               user.phone,
                    "email":               user.email,
                    "created_at":          user.created_at.isoformat() if user.created_at else None,
                    "newsletter_consent":  bool(user.newsletter_consent),
                    "whatsapp_linked":     bool(user.whatsapp_linked),
                    "subscription_plan":   user.subscription_plan,
                    "wallet_balance_ngn":  (user.wallet_balance or 0) / 100,
                },
                "data_held": {
                    "transactions":        tx_count,
                    "customers":           cust_count,
                    "message_logs":        log_count,
                },
                "your_rights": (
                    "Under the Nigeria Data Protection Regulation (NDPR) you have the right "
                    "to access, correct, and erase your personal data. To delete your account "
                    "and all associated personal data, use DELETE /app/api/account with your PIN."
                ),
            }
        finally:
            db.close()

    @app.get("/app/api/auth/me")
    def web_auth_me(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = _session_user(db, session)
            if not user:
                from fastapi import HTTPException
                raise HTTPException(status_code=401, detail="User not found.")

            # Resolve the plan from the business owner (follows parent_id) and
            # apply expiry — the same source of truth as the WhatsApp side and
            # /subscription/status. This keeps web feature-gating in sync with
            # upgrades made on WhatsApp, and lets staff inherit the owner's plan.
            sub = _session_subscription(db, session)

            from business_templates import menu_group_for_user, template_examples_for_user
            from admin import is_app_admin
            try:
                examples = [str(e) for e in (template_examples_for_user(user) or [])][:4]
            except Exception:
                examples = []
            return {
                "id": user.id,
                "name": user.name,
                "phone": user.phone,
                "email": user.email,
                "role": user.role,
                # Admin-ness lives in APP_ADMIN_PHONES / AppAdminRole, not user.role —
                # the frontend gates the Admin menu on this flag.
                "is_app_admin": bool(is_app_admin(user.phone, db)),
                "plan": sub["plan"],
                "subscription_plan": sub["plan"],
                "subscription_expires_at": sub["expires_at"].isoformat() if sub["expires_at"] else None,
                "examples": examples,
                "business_category": user.business_category,
                "business_type": user.business_type,
                "business_type_label": user.business_type_label,
                "address": user.address,
                "menu_group": menu_group_for_user(user),
                "whatsapp_linked": bool(user.whatsapp_linked),
                "newsletter_consent": bool(user.newsletter_consent),
                # A staff/sub-account has a parent; owners don't. The Staff page
                # gates the invite UI on this.
                "parent_id": user.parent_id,
                # Owner or branch admin — may manage stock, branches, etc.
                "full_access": user.parent_id is None or bool(user.can_view_all_transactions),
            }
        finally:
            db.close()

    # ── Dashboard ────────────────────────────────────────────────────────
    @app.get("/app/api/dashboard")
    def web_dashboard(
        period: Optional[str] = Query(default="TODAY"),
        branch_id: Optional[int] = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            period_key = period.upper() if period else None
            # Enforce branch isolation: a branch staff is locked to their branch,
            # an unassigned staff to their own records; an owner may filter by the
            # branch they picked. eff_branch/rec flow into every figure below.
            eff_branch, rec = _scoped_read(db, session, branch_id)
            summary = get_dashboard_summary(db, owner_phone, period_key, recorded_by_id=rec, branch_id=eff_branch)
            debtors, _ = get_unpaid_debtors(db, owner_phone, recorded_by_id=rec, branch_id=eff_branch)
            low_stock_q = db.query(InventoryItem).filter(
                InventoryItem.owner_phone == owner_phone,
                InventoryItem.is_available == True,
                InventoryItem.low_stock_alert != None,
                InventoryItem.quantity <= InventoryItem.low_stock_alert,
            )
            if eff_branch is not None:
                low_stock_q = low_stock_q.filter(InventoryItem.branch_id == eff_branch)
            low_stock_count = low_stock_q.count()
            top_products_raw = get_product_sales_by_period(db, owner_phone, period_key, recorded_by_id=rec, branch_id=eff_branch)[:8]
            margin = get_margin_summary(db, owner_phone, period_key, recorded_by_id=rec, branch_id=eff_branch)
            return {
                "period": period_key,
                "period_label": dashboard_period_label(period_key),
                "owner_phone": owner_phone,
                "summary": summary,
                "low_stock_count": low_stock_count,
                "top_debtors": sorted(
                    debtors,
                    key=lambda row: row["balance"],
                    reverse=True,
                )[:5],
                "top_products": [
                    {
                        "name": r.product,
                        "qty": r.total_quantity,
                        "amount": r.total_amount,
                    }
                    for r in top_products_raw
                ],
                "margin": {
                    "expected": margin["expected"],
                    "actual": margin["actual"],
                    "discount_gap": margin["discount_gap"],
                    "below_cost_products": margin["below_cost_products"],
                },
            }
        finally:
            db.close()

    # ── Fast Mode ────────────────────────────────────────────────────────
    @app.get("/app/api/fast-mode")
    def web_fast_mode_get(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.phone == session["phone"]).first()
            if not user:
                return {"enabled": False, "start_hour": 8, "end_hour": 18}
            owner_phone = session["phone"]
            if user.parent_id:
                owner = db.query(User).filter(User.id == user.parent_id).first()
                owner_phone = owner.phone if owner else session["phone"]
            settings = db.query(FastCaptureSettings).filter(
                FastCaptureSettings.owner_phone == owner_phone
            ).first()
            if not settings:
                return {"enabled": False, "start_hour": 8, "end_hour": 18}
            return {
                "enabled": settings.enabled,
                "start_hour": settings.market_start_hour,
                "end_hour": settings.market_end_hour,
            }
        finally:
            db.close()

    @app.post("/app/api/fast-mode")
    def web_fast_mode_toggle(payload: FastModeToggleRequest, session: dict = Depends(require_web_auth)):
        from fast_capture_commands import get_or_create_fast_capture_settings
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.phone == session["phone"]).first()
            if not user:
                raise HTTPException(status_code=404, detail="User not found.")
            owner_phone = session["phone"]
            if user.parent_id:
                owner = db.query(User).filter(User.id == user.parent_id).first()
                owner_phone = owner.phone if owner else session["phone"]
            settings = get_or_create_fast_capture_settings(db, owner_phone)
            settings.enabled = payload.enabled
            if payload.start_hour is not None:
                settings.market_start_hour = payload.start_hour
            if payload.end_hour is not None:
                settings.market_end_hour = payload.end_hour
            db.commit()
            return {"ok": True, "enabled": settings.enabled}
        finally:
            db.close()

    # ── Chat ─────────────────────────────────────────────────────────────
    @app.post("/app/api/chat/demo")
    def web_chat_demo(payload: DemoChatRequest, request: Request):
        """Parse a message for the public demo — no auth, no database write."""
        client_ip = request.client.host if request.client else "unknown"
        if not _demo_rate_check(client_ip):
            raise HTTPException(status_code=429, detail="Too many requests. Please slow down.")
        parsed = parse_message(payload.text.strip()) if payload.text.strip() else None
        return {"reply": _format_demo_reply(parsed)}

    @app.post("/app/api/chat/send")
    def web_chat_send(payload: ChatSendRequest, session: dict = Depends(require_web_auth)):
        if not _ai_rate_check(str(session["user_id"])):
            raise HTTPException(status_code=429, detail="AI request limit reached. Try again in an hour.")
        from whatsapp_client import send_whatsapp_message, web_collect_start, web_collect_stop
        from webhook_home_handler import handle_home_menu_request
        from webhook_pending_router import handle_pending_actions
        from webhook_fallback_parser import handle_fallback_parse
        from webhook_command_router import handle_parsed_command
        from reminder_automation import handle_reminder_automation_command
        from customer_automation import handle_automation_owner_command

        phone = session["phone"]
        text = payload.text.strip()
        if not text:
            return {"reply": "Please type something.", "ok": False}

        collected = web_collect_start()
        db = SessionLocal()
        try:
            user_context = load_webhook_user_context(db, phone, "text")
            user = user_context.user
            business_owner_phone = user_context.business_owner_phone
            business_name = user_context.business_name

            if not user:
                return {"reply": "Account not found. Please sign out and sign in again.", "ok": False}

            subscription = get_business_subscription(db, user)
            visible_recorded_by_id_val = visibility_recorded_by_id(user)

            # Natural language query handler — runs before the transaction parser
            # so queries like "how much does Bankole owe?" are answered directly
            # instead of being misclassified as incomplete transactions.
            from query_handler import handle_natural_language_query
            _query_reply = handle_natural_language_query(
                db, business_owner_phone, text, visible_recorded_by_id_val
            )
            if _query_reply:
                return {"reply": _query_reply, "ok": True}

            parsed = parse_message(text)
            is_command = bool(parsed and parsed["type"] != "TRANSACTION")

            # Reminder automation commands
            if handle_reminder_automation_command(db, phone, text, user, send_whatsapp_message):
                return {"reply": "\n\n".join(collected) or "Done!", "ok": True}

            # Automation owner commands
            if handle_automation_owner_command(db, phone, text, user, send_whatsapp_message):
                return {"reply": "\n\n".join(collected) or "Done!", "ok": True}

            # Home menu (menu / home / help / hello)
            if handle_home_menu_request(db, phone, text, user, subscription, business_name):
                return {"reply": "\n\n".join(collected) or "Done!", "ok": True}

            # Fast capture — commands always route; transactions bypass confirm when enabled
            from fast_capture_commands import (
                handle_fast_capture_command, save_fast_entry,
                _ack_message as _fc_ack,
            )
            if parsed and parsed.get("type") in (
                "FAST_MODE_ON", "FAST_MODE_OFF", "FAST_CAPTURE_STATUS", "CLOSE_SALES",
            ):
                handle_fast_capture_command(db, phone, parsed, user, business_owner_phone, send_whatsapp_message)
                return {"reply": "\n\n".join(collected) or "Done!", "ok": True}

            fc_settings = db.query(FastCaptureSettings).filter(
                FastCaptureSettings.owner_phone == business_owner_phone
            ).first()
            if fc_settings and fc_settings.enabled and parsed and parsed.get("type") == "TRANSACTION" and not is_command:
                entry = save_fast_entry(db, business_owner_phone, user.id, text, parsed)
                db.commit()
                return {"reply": _fc_ack(entry, parsed), "ok": True}

            # Pending action lookup (skip WEB_OTP which is for login flow)
            pending = db.query(PendingAction).filter(
                PendingAction.phone == phone,
                PendingAction.action != None,
                PendingAction.action != "WEB_OTP",
            ).order_by(PendingAction.created_at.desc()).first()

            # TTL expiry
            if pending and pending.created_at:
                _PENDING_TTL = {
                    "RESIGN_CONFIRM": 1,
                    "STOCK_ADD_CONFIRM": 4,
                    "ARTISAN_PAYMENT_CHOICE": 2,
                    "DASHBOARD_MENU": 1,
                    "UNPAID_DEBTORS_MENU": 1,
                    "DEBTOR_MANAGE_MENU": 1,
                    "CHANGE_DUE_DATE": 4,
                    "PRODUCT_BUYERS_MENU": 1,
                    "RESTOCK_ALERT_SELECT": 1,
                    "RESTOCK_ALERT_CONFIRM": 4,
                    "STOCK_ITEM_SET_CATEGORY": 4,
                    "STOCK_ITEM_SET_EXPIRY": 4,
                }
                _ttl_hours = _PENDING_TTL.get(pending.action, 4)
                _age_hours = (
                    datetime.now(timezone.utc).replace(tzinfo=None) - pending.created_at
                ).total_seconds() / 3600
                if _age_hours > _ttl_hours:
                    db.delete(pending)
                    db.commit()
                    pending = None
                    # Silent expiry — no message sent, spinner just stops on the client

            # Pending actions router (yes/no, onboarding, confirmations, etc.)
            pending_result = handle_pending_actions(
                db, phone, text, pending, user, subscription, business_name,
                business_owner_phone, visible_recorded_by_id_val,
                f"web-{uuid.uuid4()}", parsed, is_command,
            )
            if pending_result.response:
                return {"reply": "\n\n".join(collected) or "Done!", "ok": True}
            parsed = pending_result.parsed
            is_command = pending_result.is_command

            # Fallback parse (AI rephrase for ambiguous text, FAQ, pleasantries)
            fallback_result = handle_fallback_parse(db, phone, text, parsed, user)
            if fallback_result.response:
                return {"reply": "\n\n".join(collected) or "Done!", "ok": bool(collected)}
            parsed = fallback_result.parsed
            text = fallback_result.text
            is_command = fallback_result.is_command

            # Command router (all named commands: customers, reports, stock, etc.)
            if handle_parsed_command(
                db, phone, text, parsed, pending, user, subscription,
                business_name, business_owner_phone, visible_recorded_by_id_val, None,
            ):
                return {"reply": "\n\n".join(collected) or "Done!", "ok": True}

            if collected:
                return {"reply": "\n\n".join(collected), "ok": True}
            return {
                "reply": "I didn't quite understand that. Try a transaction like 'Ade paid ₦5,000' or type 'menu' for options.",
                "ok": False,
            }
        finally:
            web_collect_stop()
            db.close()

    # ── Capture ──────────────────────────────────────────────────────────
    @app.post("/app/api/capture/preview")
    def web_capture_preview(payload: CapturePreviewRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            phone = session["phone"]
            return _preview_capture(db, phone, payload.text.strip())
        except HTTPException:
            raise
        except Exception as exc:
            import traceback; traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Preview failed: {exc}")
        finally:
            db.close()

    @app.post("/app/api/capture/voice")
    def web_capture_voice(payload: CaptureVoiceRequest, session: dict = Depends(require_web_auth)):
        if not _ai_rate_check(str(session["user_id"])):
            raise HTTPException(status_code=429, detail="AI request limit reached. Try again in an hour.")
        db = SessionLocal()
        try:
            # Voice notes are a Go-plan feature — same gate as WhatsApp
            from subscriptions import ensure_feature_allowed
            _voice_user = db.query(User).filter(User.id == session["user_id"]).first()
            _allowed, _ = ensure_feature_allowed(db, _voice_user, "VOICE_TEXT", "Voice notes")
            if not _allowed:
                raise HTTPException(
                    status_code=403,
                    detail="Voice notes are a Go plan feature. Upgrade to Go to record by voice.",
                )
            phone = session["phone"]
            if not payload.audio_base64:
                return {"status": "error", "message": "Record voice and enter the registered phone number."}
            try:
                audio_bytes = base64.b64decode(payload.audio_base64)
            except ValueError:
                return {"status": "error", "message": "The voice recording could not be read."}
            transcript, error = transcribe_audio_bytes(audio_bytes, payload.mime_type or "audio/webm")
            if error:
                return {"status": "transcription_failed", "message": error}
            normalized = normalize_voice_transcript(transcript)
            result = _preview_capture(db, phone, normalized, voice_transcript_text=normalized)
            result["raw_transcript"] = transcript
            result["transcript"] = normalized
            return result
        finally:
            db.close()

    @app.post("/app/api/capture/confirm")
    def web_capture_confirm(payload: CaptureConfirmRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            phone = session["phone"]
            context = load_webhook_user_context(db, phone, "text")
            if not context.user:
                return {"status": "unregistered", "message": "This phone is not registered."}
            pending = db.query(PendingAction).filter(
                PendingAction.phone == phone,
                PendingAction.action != None,
            ).order_by(PendingAction.created_at.desc()).first()
            if not pending:
                return {"status": "empty", "message": "No pending transaction. Preview a transaction first."}
            try:
                pending_items = json.loads(pending.items_json or "[]")
            except json.JSONDecodeError:
                pending_items = []
            subscription = get_business_subscription(db, context.user)
            messages, send_message = _capture_messages()
            result = save_confirmed_pending_transaction(
                db, phone, pending, context.user, context.business_owner_phone,
                visibility_recorded_by_id(context.user), f"web-{uuid.uuid4()}",
                pending_items, subscription, send_message,
            )
            return {"status": (result or {}).get("status", "saved"), "messages": messages}
        except HTTPException:
            raise
        except Exception as exc:
            import traceback; traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Could not save transaction: {exc}")
        finally:
            db.close()

    # ── POS ──────────────────────────────────────────────────────────────
    @app.get("/app/api/pos/products")
    def web_pos_products(
        q: Optional[str] = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            query = db.query(InventoryItem).filter(
                InventoryItem.is_available == True,
                InventoryItem.owner_phone == owner_phone,
                InventoryItem.selling_price != None,
            )
            if q:
                query = query.filter(InventoryItem.name.ilike(f"%{q}%"))
            rows = query.order_by(InventoryItem.name).limit(50).all()
            return {
                "products": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "unit": item.unit,
                        "quantity": item.quantity or 0,
                        "selling_price": _money(item.selling_price),
                        "cost_price": _money(item.cost_price),
                        "is_service": item.quantity is None or item.category == "service",
                        "retail_unit": item.retail_unit,
                        "retail_per_base": item.retail_per_base,
                        "retail_price": _money(item.retail_price) if item.retail_price else None,
                    }
                    for item in rows
                ]
            }
        finally:
            db.close()

    @app.post("/app/api/pos/save")
    def web_pos_save(
        payload: PosSaveRequest,
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            items = [it.model_dump() for it in payload.items]
            # Don't trust a client-supplied branch: a branch staff records into
            # THEIR branch; an owner may pick a branch but only one of their own.
            scope_branch, _rec = _scoped_read(db, session)
            if scope_branch is not None:
                eff_branch = scope_branch
            elif payload.branch_id is not None:
                _b = db.query(Branch).filter(
                    Branch.id == payload.branch_id, Branch.owner_phone == owner_phone
                ).first()
                eff_branch = _b.id if _b else None
            else:
                from transaction_save import _get_recording_branch_id
                eff_branch = _get_recording_branch_id(db, owner_phone, _session_user(db, session))
            result = save_pos_sale(
                db,
                owner_phone,
                session["user_id"],
                payload.customer_id,
                items,
                payload.payment_amount,
                branch_id=eff_branch,
                due_date=payload.due_date,
                customer_name=payload.customer_name,
                customer_phone=payload.customer_phone,
                service_date=payload.service_date,
            )
            # Send the customer their receipt on WhatsApp (like the WhatsApp flow)
            _send_web_receipt(db, owner_phone, result.get("receipt_id"))
            return result
        except HTTPException:
            raise
        except Exception:
            # Log the detail server-side; don't leak internals to the client.
            import traceback; traceback.print_exc()
            raise HTTPException(status_code=400, detail="Could not save the sale. Please check the items and try again.")
        finally:
            db.close()

    @app.get("/app/api/pos/receipts")
    def web_pos_receipts(session: dict = Depends(require_web_auth)):
        """List past receipts (SALE / credit BUY) for this business, newest first."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            q = get_owner_transaction_query(db, owner_phone, None, include_voided=False)
            rows = q.filter(Transaction.type.in_(["SALE", "BUY"])).order_by(
                Transaction.created_at.desc()
            ).limit(100).all()
            cust_ids = [r.customer_id for r in rows if r.customer_id]
            customers = {}
            if cust_ids:
                customers = {c.id: c for c in db.query(Customer).filter(Customer.id.in_(cust_ids)).all()}
            return {
                "receipts": [
                    {
                        "id": r.id,
                        "created_at": _iso(r.created_at),
                        "customer": customers[r.customer_id].name if customers.get(r.customer_id) else None,
                        "total": _money(r.amount),
                        "type": r.type,
                        "due_date": _iso(r.due_date),
                    }
                    for r in rows
                ]
            }
        finally:
            db.close()

    @app.get("/app/api/pos/receipt/{tx_id}")
    def web_pos_receipt(tx_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
            if not tx:
                raise HTTPException(status_code=404, detail="Receipt not found.")
            # Verify the transaction belongs to this business
            recorder = db.query(User).filter(User.id == tx.recorded_by_id).first() if tx.recorded_by_id else None
            recorder_phone = recorder.phone if recorder else None
            if recorder and recorder.parent_id:
                parent = db.query(User).filter(User.id == recorder.parent_id).first()
                recorder_phone = parent.phone if parent else recorder_phone
            if recorder_phone != owner_phone:
                raise HTTPException(status_code=404, detail="Receipt not found.")
            session_user = db.query(User).filter(User.id == session["user_id"]).first()
            owner_user = db.query(User).filter(User.phone == owner_phone).first()
            receipt = get_pos_receipt(db, tx_id, user=owner_user or session_user)
            if not receipt:
                raise HTTPException(status_code=404, detail="Receipt not found.")
            return receipt
        finally:
            db.close()

    @app.get("/app/api/invoices")
    def web_list_invoices(status: str = None, session: dict = Depends(require_web_auth)):
        """List this business's issued invoices with a derived status.
        Optional ?status=open|overdue|paid filter."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            from invoices import list_business_invoices
            status_filter = status.lower() if status else None
            if status_filter and status_filter not in ("open", "overdue", "paid"):
                status_filter = None
            invoices = list_business_invoices(db, owner_phone, status_filter)
            summary = {"open": 0, "overdue": 0, "paid": 0, "total_due": 0}
            # Summary is computed over all invoices, independent of the filter.
            for row in (list_business_invoices(db, owner_phone) if status_filter else invoices):
                summary[row["status"]] += 1
                summary["total_due"] += row["outstanding"]
            return {"invoices": invoices, "summary": summary}
        finally:
            db.close()

    @app.post("/app/api/invoices/{tx_id}/issue")
    def web_issue_invoice(tx_id: int, session: dict = Depends(require_web_auth)):
        """Assign a sale its formal invoice number (once) and return the invoice
        document. The number is system-generated per business — never typed by a
        user — so two invoices can never collide."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
            if not tx:
                raise HTTPException(status_code=404, detail="Sale not found.")
            # Verify the sale belongs to this business (mirrors web_pos_receipt)
            recorder = db.query(User).filter(User.id == tx.recorded_by_id).first() if tx.recorded_by_id else None
            recorder_phone = recorder.phone if recorder else None
            if recorder and recorder.parent_id:
                parent = db.query(User).filter(User.id == recorder.parent_id).first()
                recorder_phone = parent.phone if parent else recorder_phone
            if recorder_phone != owner_phone:
                raise HTTPException(status_code=404, detail="Sale not found.")
            # A limited staff may only invoice sales within their own scope.
            _require_tx_in_scope(db, session, tx)

            from invoices import issue_invoice_number
            issue_invoice_number(db, tx, owner_phone)
            db.commit()

            session_user = db.query(User).filter(User.id == session["user_id"]).first()
            owner_user = db.query(User).filter(User.phone == owner_phone).first()
            receipt = get_pos_receipt(db, tx_id, user=owner_user or session_user)
            if not receipt:
                raise HTTPException(status_code=404, detail="Sale not found.")
            return receipt
        finally:
            db.close()

    @app.post("/app/api/invoices/{tx_id}/send")
    def web_send_invoice(tx_id: int, session: dict = Depends(require_web_auth)):
        """Send the invoice to the customer's WhatsApp and record it as sent.
        Assigns the invoice number first if needed."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
            if not tx:
                raise HTTPException(status_code=404, detail="Sale not found.")
            recorder = db.query(User).filter(User.id == tx.recorded_by_id).first() if tx.recorded_by_id else None
            recorder_phone = recorder.phone if recorder else None
            if recorder and recorder.parent_id:
                parent = db.query(User).filter(User.id == recorder.parent_id).first()
                recorder_phone = parent.phone if parent else recorder_phone
            if recorder_phone != owner_phone:
                raise HTTPException(status_code=404, detail="Sale not found.")
            # A limited staff may only send invoices for sales within their scope.
            _require_tx_in_scope(db, session, tx)

            customer = db.query(Customer).filter(Customer.id == tx.customer_id).first() if tx.customer_id else None
            if not customer or not customer.customer_phone:
                raise HTTPException(
                    status_code=400,
                    detail="No phone on file for this customer. You can still print or download the invoice.",
                )

            from invoices import issue_invoice_number, format_invoice_text
            issue_invoice_number(db, tx, owner_phone)
            db.commit()

            owner_user = db.query(User).filter(User.phone == owner_phone).first()
            session_user = db.query(User).filter(User.id == session["user_id"]).first()
            receipt = get_pos_receipt(db, tx_id, user=owner_user or session_user)
            if not receipt:
                raise HTTPException(status_code=404, detail="Sale not found.")

            from whatsapp_client import send_whatsapp_message
            send_whatsapp_message(customer.customer_phone, format_invoice_text(receipt))

            tx.invoice_sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
            return {
                "id": tx.id,
                "invoice_number": tx.invoice_number,
                "sent_at": tx.invoice_sent_at.isoformat(),
            }
        finally:
            db.close()

    # ── Customers ────────────────────────────────────────────────────────
    @app.get("/app/api/customers")
    def web_customers(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC to match DB
            owner_phone = _session_owner_phone(db, session)
            query = _owner_filter(db.query(Customer), Customer, owner_phone)
            # Branch isolation: a branch staff sees their branch's customers; an
            # unassigned staff sees only customers they've recorded a sale for.
            eff_branch, rec = _scoped_read(db, session)
            if eff_branch is not None:
                query = query.filter(Customer.branch_id == eff_branch)
            elif rec is not None:
                query = query.filter(Customer.id.in_(
                    db.query(Transaction.customer_id).filter(Transaction.recorded_by_id == rec)
                ))
            rows = query.order_by(Customer.created_at.desc()).limit(200).all()

            def _customer_due(customer_id):
                due_dates = [
                    tx.due_date
                    for tx in db.query(Transaction).filter(
                        Transaction.customer_id == customer_id,
                        Transaction.type == "BUY",
                        Transaction.due_date.isnot(None),
                        Transaction.is_voided.isnot(True),
                    ).all()
                    if tx.due_date
                ]
                if not due_dates:
                    return None, False
                next_due = min(due_dates)
                has_overdue = any(d < now for d in due_dates)
                return next_due, has_overdue

            result = []
            for c in rows:
                # Denormalized column — already on the row; NULL falls back to the sum
                bal = _money(c.balance if c.balance is not None else get_balance(db, c.id))
                next_due, has_overdue = _customer_due(c.id) if bal > 0 else (None, False)
                result.append({
                    "id": c.id,
                    "name": c.name,
                    "phone": c.customer_phone,
                    "owner_phone": c.owner_phone,
                    "balance": bal,
                    "has_overdue": has_overdue,
                    "next_due": _iso(next_due),
                    "created_at": _iso(c.created_at),
                })
            return {"customers": result}
        finally:
            db.close()

    @app.post("/app/api/customers")
    def web_add_customer(
        payload: AddCustomerRequest,
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            existing = db.query(Customer).filter(
                Customer.owner_phone == owner_phone,
                Customer.name == payload.name.strip(),
            ).first()
            if existing:
                from fastapi import HTTPException
                raise HTTPException(status_code=409, detail="A customer with this name already exists.")
            from transaction_save import _get_recording_branch_id
            c = Customer(
                owner_phone=owner_phone,
                name=payload.name.strip(),
                customer_phone=(payload.phone or "").strip() or None,
                # Tag to the creator's branch (or the business default) so it
                # lands in the right branch under isolation.
                branch_id=_get_recording_branch_id(db, owner_phone, _session_user(db, session)),
            )
            db.add(c)
            db.commit()
            db.refresh(c)
            return {"id": c.id, "name": c.name, "phone": c.customer_phone, "balance": 0}
        finally:
            db.close()

    @app.get("/app/api/customers/{customer_id}/history")
    def web_customer_history(customer_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            customer = db.query(Customer).filter(
                Customer.id == customer_id,
                Customer.owner_phone == owner_phone,
            ).first()
            if not customer:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Customer not found.")
            txs = (
                db.query(Transaction)
                .filter(
                    Transaction.customer_id == customer_id,
                    Transaction.is_voided != True,
                )
                .order_by(Transaction.created_at.desc())
                .limit(100)
                .all()
            )
            user_ids = [tx.recorded_by_id for tx in txs if tx.recorded_by_id]
            users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
            return {
                "customer": {
                    "id": customer.id,
                    "name": customer.name,
                    "phone": customer.customer_phone,
                    "balance": _money(get_balance(db, customer_id)),
                },
                "transactions": [
                    {
                        "id": tx.id,
                        "type": tx.type,
                        "amount": _money(tx.amount),
                        "product": tx.product,
                        "created_at": _iso(tx.created_at),
                        "due_date": _iso(tx.due_date),
                        "recorded_by": users[tx.recorded_by_id].name if users.get(tx.recorded_by_id) else None,
                    }
                    for tx in txs
                ],
            }
        finally:
            db.close()

    @app.post("/app/api/customers/{customer_id}/pay")
    def web_customer_pay(
        customer_id: int,
        payload: RecordPaymentRequest,
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            customer = db.query(Customer).filter(
                Customer.id == customer_id,
                Customer.owner_phone == owner_phone,
            ).first()
            if not customer:
                raise HTTPException(status_code=404, detail="Customer not found.")
            from web_pos import next_receipt_number
            tx = Transaction(
                customer_id=customer_id,
                type="PAY",
                amount=payload.amount,
                product=payload.note or "Payment",
                recorded_by_id=session["user_id"],
                message_id=f"web-pay-{uuid.uuid4()}",
                branch_id=payload.branch_id,
                # Debt payments get their own per-business receipt number too, so
                # the payment receipt reads "Receipt #4" like sales — not the raw
                # global transaction id the per-business feature exists to hide.
                receipt_number=next_receipt_number(db, owner_phone),
            )
            db.add(tx)
            db.commit()
            new_balance = _money(get_balance(db, customer_id))
            # Send the customer their payment receipt on WhatsApp
            _send_web_receipt(db, owner_phone, tx.id)
            return {"id": tx.id, "amount": payload.amount, "new_balance": new_balance}
        except HTTPException:
            raise
        except Exception as exc:
            import traceback; traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Could not record payment: {exc}")
        finally:
            db.close()

    @app.get("/app/api/customers/{customer_id}/profile")
    def web_customer_profile(customer_id: int, session: dict = Depends(require_web_auth)):
        """Return the structured profile field definitions (per business type)
        and the customer's saved values."""
        import json as _json
        from business_templates import customer_profile_fields_for_user
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            customer = db.query(Customer).filter(
                Customer.id == customer_id,
                Customer.owner_phone == owner_phone,
            ).first()
            if not customer:
                raise HTTPException(status_code=404, detail="Customer not found.")
            owner_user = db.query(User).filter(User.phone == owner_phone).first()
            fields = customer_profile_fields_for_user(owner_user)
            try:
                values = _json.loads(customer.profile_json) if customer.profile_json else {}
            except (ValueError, TypeError):
                values = {}
            return {"customer_id": customer.id, "name": customer.name, "fields": fields, "values": values}
        finally:
            db.close()

    class CustomerProfileRequest(BaseModel):
        values: dict = Field(default_factory=dict)

    @app.post("/app/api/customers/{customer_id}/profile")
    def web_save_customer_profile(
        customer_id: int,
        payload: CustomerProfileRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Save the customer's structured profile values (validated against the
        business-type field set; unknown keys are dropped)."""
        import json as _json
        from business_templates import customer_profile_fields_for_user
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            customer = db.query(Customer).filter(
                Customer.id == customer_id,
                Customer.owner_phone == owner_phone,
            ).first()
            if not customer:
                raise HTTPException(status_code=404, detail="Customer not found.")
            owner_user = db.query(User).filter(User.phone == owner_phone).first()
            allowed = {f["key"] for f in customer_profile_fields_for_user(owner_user)}
            clean = {
                k: str(v).strip()
                for k, v in (payload.values or {}).items()
                if k in allowed and str(v).strip()
            }
            customer.profile_json = _json.dumps(clean) if clean else None
            db.commit()
            return {"customer_id": customer.id, "values": clean}
        finally:
            db.close()

    @app.put("/app/api/transactions/{tx_id}/due-date")
    def web_set_transaction_due_date(
        tx_id: int,
        payload: SetTransactionDueDateRequest,
        session: dict = Depends(require_web_auth),
    ):
        from datetime import datetime as _dt
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
            if not tx or not tx.customer_id:
                raise HTTPException(status_code=404, detail="Transaction not found.")
            customer = db.query(Customer).filter(
                Customer.id == tx.customer_id,
                Customer.owner_phone == owner_phone,
            ).first()
            if not customer:
                raise HTTPException(status_code=403, detail="Not authorized.")
            tx.due_date = _dt.fromisoformat(payload.due_date) if payload.due_date else None
            db.commit()
            return {"id": tx.id, "due_date": _iso(tx.due_date)}
        except HTTPException:
            raise
        except Exception as exc:
            import traceback; traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Could not update due date: {exc}")
        finally:
            db.close()

    class SetServiceDateRequest(BaseModel):
        service_date: Optional[str] = None

    @app.put("/app/api/transactions/{tx_id}/service-date")
    def web_set_transaction_service_date(
        tx_id: int,
        payload: SetServiceDateRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Edit the promised delivery / ready-by date on a sale."""
        from datetime import datetime as _dt
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
            if not tx:
                raise HTTPException(status_code=404, detail="Transaction not found.")
            recorder = db.query(User).filter(User.id == tx.recorded_by_id).first() if tx.recorded_by_id else None
            recorder_phone = recorder.phone if recorder else None
            if recorder and recorder.parent_id:
                parent = db.query(User).filter(User.id == recorder.parent_id).first()
                recorder_phone = parent.phone if parent else recorder_phone
            if recorder_phone != owner_phone:
                raise HTTPException(status_code=403, detail="Not authorized.")
            tx.service_date = _dt.fromisoformat(payload.service_date) if payload.service_date else None
            db.commit()
            return {"id": tx.id, "service_date": _iso(tx.service_date)}
        except HTTPException:
            raise
        except Exception as exc:
            import traceback; traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Could not update delivery date: {exc}")
        finally:
            db.close()

    # ── Deliveries (jobs/orders with a promised ready date) ───────────────
    @app.get("/app/api/deliveries")
    def web_deliveries(session: dict = Depends(require_web_auth)):
        from datetime import datetime as _dt, timedelta as _td
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            cutoff = _dt.now().replace(hour=0, minute=0, second=0, microsecond=0) - _td(days=14)
            rows = (
                db.query(Transaction, Customer)
                .join(Customer, Transaction.customer_id == Customer.id)
                .filter(
                    Customer.owner_phone == owner_phone,
                    Transaction.service_date.isnot(None),
                    Transaction.is_voided.isnot(True),
                    Transaction.service_date >= cutoff,
                )
                .order_by(Transaction.service_date.asc())
                .limit(100)
                .all()
            )
            return {
                "deliveries": [
                    {
                        "id": tx.id,
                        "service_date": _iso(tx.service_date),
                        "customer": cust.name,
                        "customer_phone": cust.customer_phone,
                        "product": tx.product,
                        "created_at": _iso(tx.created_at),
                    }
                    for tx, cust in rows
                ]
            }
        finally:
            db.close()

    class DeliveryNotifyRequest(BaseModel):
        message: str = Field(max_length=1000)

    @app.post("/app/api/deliveries/{tx_id}/notify")
    def web_notify_delivery(
        tx_id: int,
        payload: DeliveryNotifyRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Send the owner-composed message to the customer's WhatsApp."""
        from whatsapp_client import send_whatsapp_message
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
            if not tx or not tx.customer_id:
                raise HTTPException(status_code=404, detail="Delivery not found.")
            customer = db.query(Customer).filter(
                Customer.id == tx.customer_id,
                Customer.owner_phone == owner_phone,
            ).first()
            if not customer:
                raise HTTPException(status_code=403, detail="Not authorized.")
            if not customer.customer_phone:
                raise HTTPException(status_code=400, detail="This customer has no phone number saved.")
            msg = (payload.message or "").strip()
            if not msg:
                raise HTTPException(status_code=400, detail="Enter a message to send.")
            try:
                send_whatsapp_message(customer.customer_phone, msg)
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Could not send message: {exc}")
            return {"ok": True}
        except HTTPException:
            raise
        finally:
            db.close()

    # ── Transactions ──────────────────────────────────────────────────────
    @app.get("/app/api/transactions")
    def web_transactions(
        period: Optional[str] = Query(default=None),
        branch_id: Optional[int] = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            period_key = period.upper() if period else None
            # Branch isolation: staff are scoped to their branch (or own records);
            # an owner may filter by the branch they picked.
            eff_branch, rec = _scoped_read(db, session, branch_id)
            query = get_owner_transaction_query(
                db, owner_phone, period_key, recorded_by_id=rec, include_voided=True, branch_id=eff_branch,
            )
            rows = query.order_by(Transaction.created_at.desc()).limit(200).all()
            customer_ids = [r.customer_id for r in rows if r.customer_id]
            customers = {}
            if customer_ids:
                customers = {c.id: c for c in db.query(Customer).filter(Customer.id.in_(customer_ids)).all()}
            user_ids = list({uid for r in rows for uid in [r.recorded_by_id, r.voided_by_id] if uid})
            users = {}
            if user_ids:
                users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}
            branch_ids = [r.branch_id for r in rows if r.branch_id]
            branches = {}
            if branch_ids:
                branches = {b.id: b for b in db.query(Branch).filter(Branch.id.in_(branch_ids)).all()}
            return {
                "transactions": [
                    {
                        "id": tx.id,
                        "type": tx.type,
                        "amount": _money(tx.amount),
                        "product": tx.product,
                        "quantity": tx.quantity,
                        "unit": tx.unit,
                        "unit_price": _money(tx.unit_price),
                        "customer": customers[tx.customer_id].name if customers.get(tx.customer_id) else "Direct sale",
                        "recorded_by": users[tx.recorded_by_id].name if users.get(tx.recorded_by_id) else None,
                        "due_date": _iso(tx.due_date),
                        "created_at": _iso(tx.created_at),
                        "is_voided": bool(tx.is_voided),
                        "void_reason": tx.void_reason,
                        "voided_by": users[tx.voided_by_id].name if tx.voided_by_id and users.get(tx.voided_by_id) else None,
                        "voided_at": _iso(tx.voided_at),
                        "branch_id": tx.branch_id,
                        "branch_name": branches[tx.branch_id].name if tx.branch_id and branches.get(tx.branch_id) else None,
                    }
                    for tx in rows
                ]
            }
        finally:
            db.close()

    class VoidTxRequest(BaseModel):
        reason: str = Field(default="", max_length=300)

    @app.post("/app/api/transactions/{tx_id}/void")
    def web_void_transaction(
        tx_id: int,
        payload: VoidTxRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Void a transaction from the web (mirrors the WhatsApp 'void' command):
        marks it voided so it drops out of balances/reports, records who/why, and
        alerts the owner when a staff member does it."""
        from reports import get_owner_transaction_query
        from models import TransactionNote
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            owner_phone = _session_owner_phone(db, session)
            if not user:
                raise HTTPException(status_code=401, detail="Not authenticated.")
            is_owner = user.phone == owner_phone
            # Staff may only see/void their own records unless granted full view.
            staff_filter = None if (is_owner or user.can_view_all_transactions) else user.id
            base = get_owner_transaction_query(db, owner_phone, recorded_by_id=staff_filter)
            tx = base.filter(Transaction.id == tx_id).first()
            if not tx:
                raise HTTPException(status_code=404, detail="Transaction not found or already voided.")
            # Full-view staff can see all, but may still only void what they recorded.
            if not is_owner and tx.recorded_by_id != user.id:
                raise HTTPException(status_code=403, detail="You can only void transactions you recorded yourself.")

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            reason = payload.reason.strip() or "No reason given"
            tx.is_voided = True
            tx.void_reason = reason
            tx.voided_by_id = user.id
            tx.voided_at = now
            db.add(TransactionNote(
                transaction_id=tx.id,
                author_user_id=user.id,
                note=f"VOIDED by {(user.name or '').title()} on {now.strftime('%d/%m/%Y %H:%M')}. Reason: {reason}",
            ))
            # In-app notification so the owner sees every void (theirs or staff's).
            _add_notification(
                db, owner_phone, "void",
                f"Transaction #{tx.id} voided",
                f"{(user.name or 'Someone').title()} voided a ₦{tx.amount:,} transaction — reason: {reason}",
            )
            db.commit()

            if not is_owner:
                try:
                    from whatsapp_client import send_whatsapp_message
                    send_whatsapp_message(
                        owner_phone,
                        f"*VOID ALERT* - Staff action\n\n"
                        f"*{(user.name or '').title()}* voided transaction #{tx.id} "
                        f"(N{tx.amount:,}).\nReason: {reason}\n\n"
                        "Check your dashboard if this looks suspicious."
                    )
                except Exception:
                    pass

            return {"ok": True, "id": tx.id, "is_voided": True, "void_reason": reason}
        finally:
            db.close()

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

    # ── Referral system ──────────────────────────────────────────────────────

    def _get_cashback_amount(db) -> int:
        cfg = db.query(ReferralSettings).order_by(ReferralSettings.id.desc()).first()
        return cfg.cashback_amount if cfg else 500

    def _count_active_go_invitees(db, referral_code: str) -> int:
        """Count how many of a referrer's invitees currently have an active GO/PRO subscription."""
        if not referral_code:
            return 0
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        referee_phones = [
            r.referee_phone
            for r in db.query(Referral).filter(Referral.referral_code == referral_code).all()
        ]
        if not referee_phones:
            return 0
        return db.query(User).filter(
            User.phone.in_(referee_phones),
            User.subscription_plan.in_(["GO", "PRO"]),
            User.subscription_status == "ACTIVE",
            (User.subscription_expires_at == None) | (User.subscription_expires_at > now),
        ).count()

    class SetReferralCodeRequest(BaseModel):
        code: str = Field(max_length=20)

    @app.get("/app/api/referral")
    def web_referral_get(session: dict = Depends(require_web_auth)):
        import os
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401)

            plan = (user.subscription_plan or "BASIC").upper()
            referrals = db.query(Referral).filter(
                Referral.referral_code == user.referral_code
            ).all() if user.referral_code else []

            invite_limit = None if plan in ("GO", "PRO") else 2
            invite_used = len(referrals)
            cashback_per_referral = _get_cashback_amount(db)

            # Live active count — invitees currently on an active GO/PRO subscription
            active_go = _count_active_go_invitees(db, user.referral_code)
            not_yet_go = invite_used - active_go
            credit_this_month = active_go * cashback_per_referral if plan in ("GO", "PRO") else 0

            base_url = os.getenv("APP_BASE_URL", "").rstrip("/") or ""
            titi_wa = os.getenv("TITI_WHATSAPP", "").strip()
            link = f"{base_url}/app/login?mode=register&ref={user.referral_code}" if user.referral_code else None
            wa_link = f"https://wa.me/{titi_wa}?text=join%20{user.referral_code}" if user.referral_code and titi_wa else None

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            referee_phones = {r.referee_phone for r in referrals}
            referee_users = {u.phone: u for u in db.query(User).filter(User.phone.in_(referee_phones)).all()} if referee_phones else {}

            return {
                "referral_code": user.referral_code,
                "link": link,
                "wa_link": wa_link,
                "plan": plan,
                "invite_limit": invite_limit,
                "invite_used": invite_used,
                "active_go": active_go,
                "not_yet_go": not_yet_go,
                "cashback_per_referral": cashback_per_referral,
                "credit_this_month": credit_this_month,
                "referrals": [
                    {
                        "referee_name": r.referee_name,
                        "referee_phone": r.referee_phone,
                        "active": (
                            referee_users.get(r.referee_phone) is not None
                            and (referee_users[r.referee_phone].subscription_plan or "").upper() in ("GO", "PRO")
                            and referee_users[r.referee_phone].subscription_status == "ACTIVE"
                            and (
                                referee_users[r.referee_phone].subscription_expires_at is None
                                or referee_users[r.referee_phone].subscription_expires_at > now
                            )
                        ),
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in referrals
                ],
            }
        finally:
            db.close()

    @app.post("/app/api/referral/set-code")
    def web_referral_set_code(
        payload: SetReferralCodeRequest,
        session: dict = Depends(require_web_auth),
    ):
        import re
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401)
            clean = payload.code.strip().upper()
            if not re.match(r"^[A-Z0-9]{3,20}$", clean):
                raise HTTPException(status_code=400, detail="Code must be 3–20 letters and numbers only, no spaces.")
            existing = db.query(User).filter(User.referral_code == clean, User.id != user.id).first()
            if existing:
                raise HTTPException(status_code=409, detail="That code is already taken. Try another.")
            user.referral_code = clean
            db.commit()
            return {"referral_code": clean}
        finally:
            db.close()

    class ReferralSettingsRequest(BaseModel):
        cashback_amount: int

    @app.get("/app/api/admin/referral-settings")
    def web_admin_referral_settings_get(session: dict = Depends(require_web_auth)):
        from admin import is_app_admin
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user or not is_app_admin(user.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(user.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")
            amount = _get_cashback_amount(db)
            return {"cashback_amount": amount}
        finally:
            db.close()

    @app.post("/app/api/admin/referral-settings")
    def web_admin_referral_settings_set(
        payload: ReferralSettingsRequest,
        session: dict = Depends(require_web_auth),
    ):
        from admin import is_app_admin
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user or not is_app_admin(user.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(user.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")
            if payload.cashback_amount < 0:
                raise HTTPException(status_code=400, detail="Amount must be >= 0")
            cfg = ReferralSettings(
                cashback_amount=payload.cashback_amount,
                updated_by=user.phone,
                updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db.add(cfg)
            from audit import audit
            audit(db, action="ADMIN_SETTINGS_CHANGE", actor_id=user.id,
                  actor_phone=user.phone,
                  resource=f"referral_cashback:{payload.cashback_amount}")
            db.commit()
            return {"cashback_amount": payload.cashback_amount}
        finally:
            db.close()

    @app.get("/app/api/admin/referrals")
    def web_admin_referrals(session: dict = Depends(require_web_auth)):
        """Per-referrer summary for the admin dashboard: who referred how many,
        how many are active GO/PRO, and the bonus each has earned."""
        from admin import is_app_admin
        from collections import defaultdict
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user or not is_app_admin(user.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(user.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")

            rate = _get_cashback_amount(db)
            by_code = defaultdict(list)
            for r in db.query(Referral).all():
                by_code[r.referral_code].append(r)

            rows = []
            for code, rs in by_code.items():
                referrer = db.query(User).filter(User.referral_code == code).first()
                referrer_plan = (referrer.subscription_plan or "BASIC").upper() if referrer else "—"
                active_go = _count_active_go_invitees(db, code)
                # Bonus mirrors the user-facing credit: active GO/PRO invitees ×
                # rate, credited only while the referrer is on GO/PRO.
                bonus = active_go * rate if referrer_plan in ("GO", "PRO") else 0
                rows.append({
                    "referral_code": code,
                    "referrer_phone": referrer.phone if referrer else (rs[0].referrer_phone if rs else None),
                    "referrer_name": referrer.name if referrer else None,
                    "referrer_plan": referrer_plan,
                    "total_invited": len(rs),
                    "active_go": active_go,
                    "bonus": bonus,
                })
            rows.sort(key=lambda x: (x["bonus"], x["total_invited"]), reverse=True)
            return {
                "referrers": rows,
                "cashback_per_referral": rate,
                "total_bonus": sum(r["bonus"] for r in rows),
                "total_referrals": sum(r["total_invited"] for r in rows),
            }
        finally:
            db.close()

    # ── Token codes ──────────────────────────────────────────────────────────

    class TokenGenerateRequest(BaseModel):
        plan: str = Field(max_length=10)
        duration_days: int
        count: int
        batch_label: str = Field(default="", max_length=60)
        expires_in_days: Optional[int] = None

    @app.post("/app/api/admin/token-codes/generate")
    def web_admin_token_generate(
        payload: TokenGenerateRequest,
        session: dict = Depends(require_web_auth),
    ):
        import secrets, io, csv as _csv
        from admin import is_app_admin
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user or not is_app_admin(user.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(user.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")

            plan = payload.plan.upper()
            if plan not in ("GO", "PRO"):
                raise HTTPException(status_code=400, detail="plan must be GO or PRO")
            if not (1 <= payload.count <= 1000):
                raise HTTPException(status_code=400, detail="count must be 1–1000")
            if payload.duration_days < 1:
                raise HTTPException(status_code=400, detail="duration_days must be >= 1")

            expires_at = None
            if payload.expires_in_days:
                expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=payload.expires_in_days)

            codes = []
            for _ in range(payload.count):
                while True:
                    raw = secrets.token_urlsafe(6).upper().replace("-", "").replace("_", "")[:8]
                    code_str = f"{plan}-{raw}"
                    if not db.query(TokenCode).filter(TokenCode.code == code_str).first():
                        break
                tc = TokenCode(
                    code=code_str,
                    plan=plan,
                    duration_days=payload.duration_days,
                    batch_label=payload.batch_label or None,
                    issued_by=user.phone,
                    expires_at=expires_at,
                )
                db.add(tc)
                codes.append(code_str)
            from audit import audit
            audit(db, action="ADMIN_TOKEN_GENERATE", actor_id=user.id,
                  actor_phone=user.phone,
                  resource=f"{plan}×{payload.count} {payload.duration_days}d")
            db.commit()

            buf = io.StringIO()
            w = _csv.writer(buf)
            from export_utils import _csv_safe
            w.writerow(["Code", "Plan", "Duration (days)", "Batch", "Expires"])
            for c in codes:
                w.writerow([_csv_safe(v) for v in (c, plan, payload.duration_days, payload.batch_label or "", expires_at or "")])
            buf.seek(0)
            filename = f"tokens_{plan}_{payload.batch_label or 'batch'}.csv"
            return StreamingResponse(
                iter([buf.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{_safe_filename(filename)}"'},
            )
        finally:
            db.close()

    @app.get("/app/api/admin/token-codes")
    def web_admin_token_list(
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=50, le=200),
        batch: str = Query(default=""),
        session: dict = Depends(require_web_auth),
    ):
        from admin import is_app_admin
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user or not is_app_admin(user.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(user.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")

            q = db.query(TokenCode)
            if batch:
                q = q.filter(TokenCode.batch_label.ilike(f"%{batch}%"))
            total = q.count()
            rows = q.order_by(TokenCode.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
            return {
                "total": total,
                "page": page,
                "rows": [
                    {
                        "id": r.id,
                        "code": r.code,
                        "plan": r.plan,
                        "duration_days": r.duration_days,
                        "batch_label": r.batch_label,
                        "redeemed": r.redeemed_at is not None,
                        "redeemed_by": r.redeemed_by_phone,
                        "redeemed_at": r.redeemed_at.isoformat() if r.redeemed_at else None,
                        "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in rows
                ],
            }
        finally:
            db.close()

    class TokenRedeemRequest(BaseModel):
        code: str = Field(max_length=20)

    @app.post("/app/api/token-codes/redeem")
    def web_token_redeem(
        payload: TokenRedeemRequest,
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401, detail="Not authenticated")

            if not _redeem_rate_check(str(session["user_id"])):
                raise HTTPException(status_code=429, detail="Too many attempts. Try again in an hour.")

            _INVALID = HTTPException(status_code=400, detail="Invalid or expired code.")

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            import re as _re
            from sqlalchemy import func as _func
            # Normalise the typed code (drop hyphens/spaces, uppercase) and match it
            # against the stored code with its hyphen removed, so a code entered
            # without the hyphen ("GOAB12CD34") still activates.
            _code_norm = _re.sub(r"[^A-Z0-9]", "", payload.code.upper())
            tc = db.query(TokenCode).filter(
                _func.upper(_func.replace(TokenCode.code, "-", "")) == _code_norm
            ).first()
            # Collapse all failure states into one generic error to prevent enumeration.
            if not tc or tc.redeemed_at or (tc.expires_at and tc.expires_at < now):
                raise _INVALID

            tc.redeemed_at = now
            tc.redeemed_by_phone = user.phone

            # Extend or set plan expiry
            current_expiry = user.subscription_expires_at
            if current_expiry and current_expiry > now:
                new_expiry = current_expiry + timedelta(days=tc.duration_days)
            else:
                new_expiry = now + timedelta(days=tc.duration_days)

            user.subscription_plan = tc.plan
            user.subscription_status = "ACTIVE"
            user.subscription_expires_at = new_expiry
            db.commit()

            return {
                "plan": tc.plan,
                "duration_days": tc.duration_days,
                "expires_at": new_expiry.isoformat(),
                "message": f"Activated! Your plan is now {tc.plan} for {tc.duration_days} days.",
            }
        finally:
            db.close()

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
    }
    _DIST_ROOT_STATIC = ["favicon.png", "favicon.svg", "logo.png", "icons.svg", "offline.html"]
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
        return _read_index()
