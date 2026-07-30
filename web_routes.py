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
            tx = Transaction(
                customer_id=customer_id,
                type="PAY",
                amount=payload.amount,
                product=payload.note or "Payment",
                recorded_by_id=session["user_id"],
                message_id=f"web-pay-{uuid.uuid4()}",
                branch_id=payload.branch_id,
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

    # ── Wallet ───────────────────────────────────────────────────────────
    @app.get("/app/api/wallet")
    def web_wallet(session: dict = Depends(require_web_auth)):
        from wallet_service import get_wallet_summary
        db = SessionLocal()
        try:
            user_ctx = load_webhook_user_context(db, session["phone"], "text")
            owner_phone = user_ctx.business_owner_phone or session["phone"]
            return get_wallet_summary(db, owner_phone)
        finally:
            db.close()

    @app.post("/app/api/wallet/interest")
    def web_wallet_interest(session: dict = Depends(require_web_auth)):
        """Register owner as interested — shown on the coming-soon page."""
        from wallet_service import register_waitlist
        db = SessionLocal()
        try:
            user_ctx = load_webhook_user_context(db, session["phone"], "text")
            owner_phone = user_ctx.business_owner_phone or session["phone"]
            register_waitlist(db, owner_phone)
            return {"ok": True}
        finally:
            db.close()

    class WalletMatchRequest(BaseModel):
        wallet_tx_id: int
        customer_id: int

    @app.post("/app/api/wallet/match")
    def web_wallet_match(
        payload: WalletMatchRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Manually match an unmatched inbound payment to a customer."""
        from wallet_service import manually_match_payment
        db = SessionLocal()
        try:
            user_ctx = load_webhook_user_context(db, session["phone"], "text")
            owner_phone = user_ctx.business_owner_phone or session["phone"]
            tx, err = manually_match_payment(
                db,
                payload.wallet_tx_id,
                payload.customer_id,
                owner_phone,
            )
            if err:
                raise HTTPException(status_code=400, detail=err)
            return {"ok": True, "transaction_id": tx.id}
        finally:
            db.close()

    # ── School Teacher Roster — split into web_school_routes ──────────────────
    from web_school_routes import register_school_routes
    register_school_routes(app)

    # ── Partners & Business notes — split into their own modules ──────────────
    from web_partner_routes import register_partner_routes
    from web_notes_routes import register_notes_routes
    register_partner_routes(app)
    register_notes_routes(app)

    # ── Monnify payment webhook ───────────────────────────────────────────────
    @app.post("/webhook/payment-received")
    async def webhook_payment_received(request):
        """
        Monnify calls this on every SUCCESSFUL_TRANSACTION for a reserved account.
        Header: monnify-signature — HMAC-SHA512 of raw body using your Secret Key.
        """
        from wallet_service import process_incoming_payment, resolve_bank_name, verify_webhook_signature
        from whatsapp_client import send_whatsapp_message

        body = await request.body()
        sig  = request.headers.get("monnify-signature", "")

        if not verify_webhook_signature(body, sig):
            raise HTTPException(status_code=401, detail="Invalid webhook signature.")

        import json as _json
        data      = _json.loads(body)
        event     = data.get("eventType", "")
        event_data = data.get("eventData", {})

        # ── Settlement confirmation (Layer 3) ────────────────────────────────
        if event == "SETTLEMENT_COMPLETED":
            # Monnify fields: reservedAccountReference = owner_phone we set
            owner_phone = (
                event_data.get("reservedAccountReference")
                or event_data.get("accountReference")
                or ""
            )
            settled    = int(float(event_data.get("totalAmount") or event_data.get("settledAmount") or 0))
            dest_bank  = resolve_bank_name(event_data.get("destinationBankCode", "")) \
                         or event_data.get("destinationBankName", "your bank")
            dest_name  = event_data.get("destinationAccountName", "")

            if owner_phone and settled:
                send_whatsapp_message(
                    owner_phone,
                    f"✅ ₦{settled:,} has been sent to your {dest_bank} account"
                    + (f" ({dest_name})" if dest_name else "") + ".\n"
                    "This covers payments collected up to yesterday.\n"
                    "Check your bank for the credit alert."
                )
            return {"ok": True, "event": event}

        # ── Inbound payment (Layer 1) ─────────────────────────────────────────
        if event != "SUCCESSFUL_TRANSACTION":
            return {"ok": True, "skipped": event}
        if event_data.get("paymentStatus") != "PAID":
            return {"ok": True, "skipped": "not paid"}

        # Parse Monnify payload
        ref       = event_data.get("transactionReference", "")
        narration = event_data.get("paymentDescription", "")
        amount    = int(float(event_data.get("amountPaid", 0)))

        # Owner identified from the accountReference we set during provisioning
        owner_phone = event_data.get("product", {}).get("reference", "")

        # Sender details come from paymentSourceInformation array
        src       = (event_data.get("paymentSourceInformation") or [{}])[0]
        sender    = src.get("accountName", "")
        s_acct    = src.get("accountNumber", "")
        s_bank    = resolve_bank_name(src.get("bankCode", ""))

        # Destination account number (the business's reserved account)
        dest_info = event_data.get("destinationAccountInformation", {})
        va_number = dest_info.get("accountNumber", "")

        if not owner_phone or not amount or not ref:
            raise HTTPException(status_code=400, detail="Missing required fields.")

        db = SessionLocal()
        try:
            from models import Wallet
            # Prefer lookup by owner_phone (set as accountReference); fall back to VA number
            wallet = db.query(Wallet).filter(Wallet.owner_phone == owner_phone).first()
            if not wallet and va_number:
                wallet = db.query(Wallet).filter(Wallet.virtual_account_number == va_number).first()
            if not wallet:
                raise HTTPException(status_code=404, detail="Wallet not found.")

            tx = process_incoming_payment(
                db, wallet.owner_phone, amount, sender, s_bank, narration, ref, s_acct
            )

            match_note = ""
            unmatched_note = ""
            if tx.matched_customer_id:
                from models import Customer as _Customer
                from sqlalchemy import func as _func
                c = db.query(_Customer).filter(_Customer.id == tx.matched_customer_id).first()
                if c:
                    # Compute remaining balance for that customer
                    from models import Transaction as _Tx
                    total_owed = db.query(_func.coalesce(_func.sum(_Tx.amount), 0)).filter(
                        _Tx.customer_id == c.id, _Tx.type == "BUY", _Tx.is_voided != True
                    ).scalar() or 0
                    total_paid = db.query(_func.coalesce(_func.sum(_Tx.amount), 0)).filter(
                        _Tx.customer_id == c.id, _Tx.type == "PAY", _Tx.is_voided != True
                    ).scalar() or 0
                    balance = max(0, int(total_owed) - int(total_paid))
                    balance_line = f"\nBalance remaining: ₦{balance:,}" if balance > 0 else "\nAccount fully cleared ✅"
                    match_note = f"\nMatched to *{c.name.title()}* and recorded as payment.{balance_line}"
            else:
                unmatched_note = "\n\nNo customer matched — open the Wallet to assign this payment."

            send_whatsapp_message(
                wallet.owner_phone,
                f"💰 *Payment received: ₦{amount:,}*\n"
                f"From: {sender or 'Unknown'} ({s_bank})\n"
                f"Ref: {ref}"
                f"{match_note}{unmatched_note}"
            )
            return {"ok": True, "reference": tx.reference}
        finally:
            db.close()

    # ── Admin: provision a Monnify reserved account for an owner ─────────────
    @app.post("/app/api/wallet/provision")
    def web_wallet_provision(session: dict = Depends(require_web_auth)):
        """
        Owner calls this once to create their reserved account on Monnify.
        Safe to call again — returns existing details if already provisioned.
        """
        from wallet_service import provision_virtual_account
        db = SessionLocal()
        try:
            user_ctx = load_webhook_user_context(db, session["phone"], "text")
            owner_phone = user_ctx.business_owner_phone or session["phone"]
            owner = db.query(User).filter(User.phone == owner_phone).first()
            if not owner:
                raise HTTPException(status_code=404, detail="Owner not found.")
            result = provision_virtual_account(db, owner_phone, owner.name or owner_phone)
            return {"ok": True, **result}
        finally:
            db.close()

    # ── Thrift / Ajo ────────────────────────────────────────────────────────

    @app.get("/app/api/thrift/summary")
    def web_thrift_summary(
        period: Optional[str] = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        """Return thrift data split into group contributions and personal savings."""
        import sqlalchemy as _sa
        from collections import defaultdict
        import logging as _log
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            period_key = period.upper() if period else None
            base = get_owner_transaction_query(db, owner_phone, period_key)

            # Group thrift: customer-linked transactions with thrift/ajo/esusu/contribution keywords
            group_filter = _sa.and_(
                Transaction.customer_id != None,
                _sa.or_(
                    Transaction.product.ilike("%thrift%"),
                    Transaction.product.ilike("%ajo%"),
                    Transaction.product.ilike("%esusu%"),
                    Transaction.product.ilike("%contribut%"),
                ),
            )
            # Personal savings: DIRECT type with personal_savings product OR savings/thrift/ajo with no customer
            personal_filter = _sa.or_(
                _sa.and_(Transaction.type == "DIRECT", Transaction.product.ilike("%personal_saving%")),
                _sa.and_(Transaction.type == "DIRECT", Transaction.product.ilike("%personal saving%")),
                _sa.and_(
                    Transaction.customer_id == None,
                    Transaction.type == "DIRECT",
                    _sa.or_(
                        Transaction.product.ilike("%saving%"),
                        Transaction.product.ilike("%thrift%"),
                        Transaction.product.ilike("%ajo%"),
                    ),
                ),
            )

            group_rows    = base.filter(group_filter).order_by(Transaction.created_at.desc()).all()
            personal_rows = base.filter(personal_filter).order_by(Transaction.created_at.desc()).all()

            # Customer lookup for group rows
            cust_ids  = list({r.customer_id for r in group_rows if r.customer_id})
            customers: dict = {}
            if cust_ids:
                customers = {c.id: c for c in db.query(Customer).filter(Customer.id.in_(cust_ids)).all()}

            def _tx(tx, name):
                return {
                    "id": tx.id,
                    "customer_id": tx.customer_id,
                    "customer_name": name,
                    "amount": _money(tx.amount),
                    "product": (tx.product or "").replace("personal_savings", "").replace("personal savings", "").strip(": ") or None,
                    "created_at": _iso(tx.created_at),
                }

            group_tx_list    = [_tx(tx, customers[tx.customer_id].name if customers.get(tx.customer_id) else "Unknown") for tx in group_rows]
            personal_tx_list = [_tx(tx, "Me") for tx in personal_rows]

            # Participant totals (group)
            totals: dict = defaultdict(lambda: {"name": "Unknown", "count": 0, "total": 0})
            for tx in group_rows:
                key = tx.customer_id
                c = customers.get(key)
                totals[key]["name"]  = c.name if c else "Unknown"
                totals[key]["count"] += 1
                totals[key]["total"] += int(tx.amount or 0)
            participants = sorted(
                [{"id": k, **v} for k, v in totals.items()],
                key=lambda p: p["total"], reverse=True,
            )

            group_total    = sum(int(tx.amount or 0) for tx in group_rows)
            personal_total = sum(int(tx.amount or 0) for tx in personal_rows)
            return {
                "group": {
                    "transactions": group_tx_list,
                    "participants": participants,
                    "total": group_total,
                    "count": len(group_rows),
                },
                "personal": {
                    "transactions": personal_tx_list,
                    "total": personal_total,
                    "count": len(personal_rows),
                },
            }
        except Exception as _e:
            _log.getLogger("creditvoice.thrift").exception("thrift/summary error")
            raise HTTPException(status_code=500, detail=f"Thrift summary failed: {_e}")
        finally:
            db.close()

    class ThriftSaveRequest(BaseModel):
        amount: int
        note: Optional[str] = Field(default=None, max_length=500)

    @app.post("/app/api/thrift/save")
    def web_thrift_personal_save(
        payload: ThriftSaveRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Record a personal savings entry (no participant needed)."""
        db = SessionLocal()
        try:
            if payload.amount <= 0:
                from fastapi import HTTPException
                raise HTTPException(status_code=400, detail="Amount must be greater than zero.")
            note = f": {payload.note}" if payload.note else ""
            tx = Transaction(
                customer_id=None,
                type="DIRECT",
                amount=payload.amount,
                product=f"personal_savings{note}",
                recorded_by_id=session["user_id"],
                message_id=f"web-save-{uuid.uuid4()}",
            )
            db.add(tx)
            db.commit()
            return {"ok": True, "id": tx.id, "amount": _money(payload.amount)}
        finally:
            db.close()

    class ThriftParticipantRequest(BaseModel):
        name: str = Field(max_length=120)
        phone: Optional[str] = Field(default=None, max_length=20)

    @app.post("/app/api/thrift/participants")
    def web_thrift_add_participant(
        payload: ThriftParticipantRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Add a thrift participant (creates a customer record)."""
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            # Check for duplicate
            existing = db.query(Customer).filter(
                Customer.owner_phone == owner_phone,
                Customer.name == payload.name.strip().lower(),
            ).first()
            if existing:
                return {"id": existing.id, "name": existing.name, "existing": True}
            customer = Customer(
                owner_phone=owner_phone,
                name=payload.name.strip().lower(),
                customer_phone=payload.phone,
            )
            db.add(customer)
            db.commit()
            db.refresh(customer)
            return {"id": customer.id, "name": customer.name, "existing": False}
        finally:
            db.close()

    # ── Subscription / Upgrade ─────────────────────────────────────────────

    @app.get("/app/api/subscription/status")
    def web_subscription_status(session: dict = Depends(require_web_auth)):
        """Return current plan, expiry, and any pending payment request."""
        import requests as _req
        db = SessionLocal()
        try:
            from subscriptions import get_business_subscription, get_pending_subscription_payment
            from messages import get_plan_price, get_payment_account_message
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401, detail="User not found.")
            sub = get_business_subscription(db, user)
            pending = get_pending_subscription_payment(db, user)
            go_price  = get_plan_price("GO")
            pro_price = get_plan_price("PRO")
            bank_details = get_payment_account_message()
            is_test = "sandbox" in os.getenv("MONNIFY_BASE_URL", "sandbox")
            return {
                "plan":       sub["plan"],
                "status":     sub["status"],
                "expires_at": sub["expires_at"].isoformat() if sub["expires_at"] else None,
                "prices":     {"GO": go_price, "PRO": pro_price},
                "bank_details": bank_details,
                "monnify": {
                    "api_key":       os.getenv("MONNIFY_API_KEY", ""),
                    "contract_code": os.getenv("MONNIFY_CONTRACT_CODE", ""),
                    "is_test":       is_test,
                },
                "pending_payment": {
                    "id":     pending.id,
                    "plan":   pending.plan,
                    "amount": pending.amount,
                    "method": pending.payment_method,
                    "status": pending.status,
                } if pending else None,
                "user": {
                    "name":  user.name or "",
                    "email": user.email or f"{user.phone}@creditvoice.app",
                    "phone": user.phone or "",
                },
            }
        finally:
            db.close()

    class SubscriptionRequestBody(BaseModel):
        plan: str = Field(max_length=10)

    @app.post("/app/api/subscription/request")
    def web_subscription_bank_transfer(
        payload: SubscriptionRequestBody,
        session: dict = Depends(require_web_auth),
    ):
        """Create a pending bank-transfer subscription upgrade request."""
        from subscriptions import create_subscription_payment_request
        from messages import get_payment_account_message
        from plans import normalize_plan, PLAN_BASIC
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401, detail="User not found.")
            plan = normalize_plan(payload.plan)
            if plan == PLAN_BASIC:
                raise HTTPException(status_code=400, detail="Cannot request a downgrade to Basic.")
            payment = create_subscription_payment_request(db, user, plan)
            payment.payment_method = "BANK_TRANSFER"
            db.commit()
            return {
                "ok": True,
                "payment_id": payment.id,
                "plan": plan,
                "amount": payment.amount,
                "bank_details": get_payment_account_message(),
                "reference": user.phone,
            }
        finally:
            db.close()

    @app.post("/app/api/subscription/confirm-payment")
    def web_subscription_confirm_payment(
        payload: SubscriptionRequestBody,
        session: dict = Depends(require_web_auth),
    ):
        """User reports they've completed the bank transfer — alert admins
        (WhatsApp + email). This is the web equivalent of replying PAID on
        WhatsApp; it does NOT activate the plan (an admin still approves)."""
        from subscriptions import (
            create_subscription_payment_request,
            get_pending_subscription_payment,
            get_business_owner_user,
        )
        from admin_commands import notify_subscription_admins
        from whatsapp_client import send_whatsapp_message
        from plans import normalize_plan, PLAN_BASIC
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401, detail="User not found.")

            payment = get_pending_subscription_payment(db, user)
            if not payment:
                # Modal reopened / request expired — recreate so admins are still alerted
                plan = normalize_plan(payload.plan)
                if plan == PLAN_BASIC:
                    raise HTTPException(status_code=400, detail="Invalid plan.")
                payment = create_subscription_payment_request(db, user, plan)
                payment.payment_method = "BANK_TRANSFER"
                db.commit()

            owner = get_business_owner_user(db, user)
            try:
                notify_subscription_admins(db, payment, owner, send_whatsapp_message, evidence_received=False)
            except Exception:
                import traceback; traceback.print_exc()

            # In-app notification to app admins so it shows on the web dashboard.
            try:
                from admin import app_admin_phones
                from web_auth import phone_candidates
                cand = set()
                for p in app_admin_phones():
                    cand.update(phone_candidates(p))
                owner_name = (owner.name if owner else user.name) or user.phone
                admins = db.query(User).filter(User.phone.in_(list(cand))).all() if cand else []
                for a in admins:
                    _add_notification(
                        db, a.phone, "upgrade",
                        f"Upgrade payment: {payment.plan}",
                        f"{owner_name} ({user.phone}) reports paying for {payment.plan} by bank transfer — please verify and approve.",
                    )
                if admins:
                    db.commit()
            except Exception:
                import traceback; traceback.print_exc()
            return {"ok": True}
        finally:
            db.close()

    class MonnifyInitBody(BaseModel):
        plan: str = Field(max_length=10)

    @app.post("/app/api/subscription/monnify/init")
    def web_subscription_monnify_init(
        payload: MonnifyInitBody,
        session: dict = Depends(require_web_auth),
    ):
        """Create a Monnify payment reference for subscription upgrade."""
        from subscriptions import create_subscription_payment_request
        from plans import normalize_plan, PLAN_BASIC
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401, detail="User not found.")
            plan = normalize_plan(payload.plan)
            if plan == PLAN_BASIC:
                raise HTTPException(status_code=400, detail="Cannot request Basic via Monnify.")
            payment = create_subscription_payment_request(db, user, plan)
            payment.payment_method = "MONNIFY"
            # Use the DB payment ID as the unique reference for Monnify
            db.flush()
            ref = f"CV-SUB-{payment.id}-{uuid.uuid4().hex[:6].upper()}"
            payment.evidence_ref = ref
            db.commit()
            is_test = "sandbox" in os.getenv("MONNIFY_BASE_URL", "sandbox")
            return {
                "ok": True,
                "reference": ref,
                "amount": payment.amount,
                "plan": plan,
                "api_key": os.getenv("MONNIFY_API_KEY", ""),
                "contract_code": os.getenv("MONNIFY_CONTRACT_CODE", ""),
                "is_test": is_test,
                "customer_name": user.name or user.phone,
                "customer_email": user.email or f"{user.phone}@creditvoice.app",
                "description": f"CreditVoice {plan} Plan - 1 month",
            }
        finally:
            db.close()

    class MonnifyVerifyBody(BaseModel):
        reference: str = Field(max_length=80)
        transaction_reference: Optional[str] = Field(default=None, max_length=120)

    @app.post("/app/api/subscription/monnify/verify")
    def web_subscription_monnify_verify(
        payload: MonnifyVerifyBody,
        session: dict = Depends(require_web_auth),
    ):
        """Verify a Monnify payment and activate subscription if successful."""
        import requests as _req
        from subscriptions import approve_subscription_payment
        from plans import normalize_plan
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401, detail="User not found.")

            # Find the pending payment by evidence_ref (our reference)
            from models import SubscriptionPayment
            payment = db.query(SubscriptionPayment).filter(
                SubscriptionPayment.evidence_ref == payload.reference,
                SubscriptionPayment.payment_method == "MONNIFY",
            ).first()
            if not payment:
                raise HTTPException(status_code=404, detail="Payment reference not found.")
            if payment.status == "APPROVED":
                return {"ok": True, "plan": payment.plan, "already_active": True}

            # Verify with Monnify API
            from wallet_service import _get_monnify_token, MONNIFY_BASE_URL
            try:
                token = _get_monnify_token()
                tx_ref = payload.transaction_reference or payload.reference
                resp = _req.get(
                    f"{MONNIFY_BASE_URL}/api/v2/transactions/{tx_ref}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=15,
                )
                resp.raise_for_status()
                body = resp.json().get("responseBody", {})
                tx_status = body.get("paymentStatus") or body.get("transactionStatus", "")
                amount_paid = int(body.get("amountPaid", 0))
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Monnify verification failed: {e}")

            if tx_status.upper() != "PAID" and tx_status.upper() != "SUCCESS":
                raise HTTPException(status_code=400, detail=f"Payment not completed (status: {tx_status}).")
            if amount_paid < payment.amount:
                raise HTTPException(status_code=400, detail=f"Amount paid ({amount_paid}) less than required ({payment.amount}).")

            # Activate
            owner = approve_subscription_payment(db, payment, user)
            db.commit()
            return {
                "ok": True,
                "plan": normalize_plan(payment.plan),
                "expires_at": owner.subscription_expires_at.isoformat() if owner and owner.subscription_expires_at else None,
            }
        finally:
            db.close()

    # Public webhook — no auth required, verified by HMAC
    @app.post("/app/api/webhooks/monnify/subscription")
    async def web_monnify_subscription_webhook(request: Request):
        """Monnify webhook for subscription payments — auto-activates on PAID."""
        import requests as _req
        from subscriptions import approve_subscription_payment
        from models import SubscriptionPayment
        body_bytes = await request.body()
        sig_header = request.headers.get("monnify-signature", "")
        # Verify HMAC-SHA512
        secret = os.getenv("MONNIFY_SECRET_KEY", "")
        if secret and sig_header:
            import hmac as _hmac, hashlib as _hs
            expected = _hmac.new(secret.encode(), body_bytes, _hs.sha512).hexdigest()
            if not _hmac.compare_digest(expected, sig_header):
                raise HTTPException(status_code=401, detail="Invalid webhook signature.")
        try:
            data = json.loads(body_bytes)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON.")
        event_type   = data.get("eventType", "")
        event_data   = data.get("eventData", {})
        tx_status    = event_data.get("paymentStatus", "")
        pay_ref      = event_data.get("paymentReference", "")
        amount_paid  = int(event_data.get("amountPaid", 0))
        if "SUCCESSFUL" not in tx_status.upper() and "PAID" not in tx_status.upper():
            return {"ok": True, "ignored": True}
        db = SessionLocal()
        try:
            payment = db.query(SubscriptionPayment).filter(
                SubscriptionPayment.evidence_ref == pay_ref,
                SubscriptionPayment.payment_method == "MONNIFY",
                SubscriptionPayment.status == "PENDING",
            ).first()
            if not payment:
                return {"ok": True, "ignored": True, "reason": "unknown_ref"}
            if amount_paid < payment.amount:
                return {"ok": True, "ignored": True, "reason": "underpaid"}
            approve_subscription_payment(db, payment, admin_user=None)
            db.commit()
        finally:
            db.close()
        return {"ok": True}

    # ── Reminders ──────────────────────────────────────────────────────────
    @app.get("/app/api/reminders")
    def web_reminders(
        owner_phone: Optional[str] = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            from admin import is_app_admin
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401, detail="User not found.")
            # Admins may view any business; everyone else is bound to their own
            if owner_phone and is_app_admin(user.phone, db):
                phone = owner_phone
            else:
                phone = _session_owner_phone(db, session)
            query = _owner_filter(db.query(ReminderQueue), ReminderQueue, phone)
            rows = query.order_by(ReminderQueue.created_at.desc()).limit(200).all()
            return {
                "reminders": [
                    {
                        "id": r.id,
                        "customer_name": r.customer_name,
                        "customer_phone": r.customer_phone,
                        "balance": _money(r.balance),
                        "due_date": _iso(r.due_date),
                        "type": r.reminder_type,
                        "status": r.status,
                        "message_text": r.message_text,
                        "created_at": _iso(r.created_at),
                    }
                    for r in rows
                ]
            }
        finally:
            db.close()

    @app.post("/app/api/reminders/{reminder_id}/send")
    def web_send_reminder(reminder_id: int, session: dict = Depends(require_web_auth)):
        """Approve and send a single pending reminder from the web dashboard."""
        db = SessionLocal()
        try:
            from models import ReminderQueue
            from whatsapp_client import send_whatsapp_message
            owner_phone = _session_owner_phone(db, session)
            item = (
                db.query(ReminderQueue)
                .filter(ReminderQueue.id == reminder_id, ReminderQueue.owner_phone == owner_phone)
                .first()
            )
            if not item:
                raise HTTPException(status_code=404, detail="Reminder not found.")
            if item.status == "SENT":
                raise HTTPException(status_code=400, detail="Reminder already sent.")
            if not item.customer_phone:
                raise HTTPException(status_code=400, detail="No customer phone on this reminder.")

            delivered = send_whatsapp_message(item.customer_phone, item.message_text)

            # A WhatsApp link the owner can use to send it from their OWN phone —
            # the only way to reach a customer who never messaged the tiTi number
            # (WhatsApp blocks free-form messages outside the 24h window).
            from parser import normalize_phone
            from urllib.parse import quote
            digits = normalize_phone(item.customer_phone) or "".join(ch for ch in item.customer_phone if ch.isdigit())
            self_send_url = f"https://wa.me/{digits}?text={quote(item.message_text)}"

            if delivered:
                from reminder_automation import create_send_log
                item.status = "SENT"
                create_send_log(db, owner_phone, item)
                db.commit()
                return {"ok": True, "delivered": True, "sent_to": item.customer_name}

            # Not delivered (likely a customer who hasn't messaged tiTi). Leave it
            # pending and let the owner send it themselves.
            return {
                "ok": True, "delivered": False, "customer_name": item.customer_name,
                "message_text": item.message_text, "self_send_url": self_send_url,
            }
        except HTTPException:
            raise
        except Exception as exc:
            import traceback; traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            db.close()

    @app.post("/app/api/reminders/run")
    def web_run_reminder_automation(session: dict = Depends(require_web_auth)):
        """Generate reminder drafts for the owner's current unpaid debtors, ready
        for review/send on the Reminders page."""
        db = SessionLocal()
        try:
            from reminder_automation import queue_debtor_reminders
            owner_phone = _session_owner_phone(db, session)
            result = queue_debtor_reminders(db, owner_phone)
            # Keep the shape the page expects, plus friendly extras.
            return {"queued": result["queued"], "sent": 0,
                    "skipped": result.get("no_phone", 0),
                    "debtors": result.get("debtors", 0)}
        except Exception as exc:
            import traceback; traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            db.close()

    # ── Automation settings ───────────────────────────────────────────────────
    BOT_MENU_GROUPS = {"retail_trading", "pharmacy", "salon_beauty", "food_hospitality"}

    @app.get("/app/api/automation")
    def web_get_automation(
        owner_phone: Optional[str] = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            from admin import is_app_admin
            from customer_automation import get_or_create_automation_settings
            from reminder_automation import get_or_create_reminder_settings
            session_user = db.query(User).filter(User.id == session["user_id"]).first()
            if owner_phone and session_user and is_app_admin(session_user.phone, db):
                phone = owner_phone
            else:
                phone = _session_owner_phone(db, session)
            user = db.query(User).filter(User.phone == phone).first()
            bot = get_or_create_automation_settings(db, phone)
            rem = get_or_create_reminder_settings(db, phone)
            db.commit()
            from business_templates import template_key_for_user as _tku
            has_bot = _tku(user) in BOT_MENU_GROUPS if user else False
            return {
                "has_bot": has_bot,
                "reminder": {
                    "preview_enabled": bool(rem.preview_enabled),
                    "auto_send_enabled": bool(rem.auto_send_enabled),
                    "reminder_time": rem.reminder_time or "08:00",
                },
                "bot": {
                    "bot_enabled": bool(bot.bot_enabled),
                    "auto_reply_enabled": bool(bot.auto_reply_enabled),
                    "auto_order_enabled": bool(bot.auto_order_enabled),
                    "allow_part_payment": bool(bot.allow_part_payment),
                    "payment_modes": bot.payment_modes or "",
                    "delivery_note": bot.delivery_note or "",
                    "pickup_address": bot.pickup_address or "",
                } if has_bot else None,
            }
        finally:
            db.close()

    class AutomationUpdateRequest(BaseModel):
        owner_phone: Optional[str] = Field(default=None, max_length=20)
        # reminder fields
        reminder_preview_enabled: Optional[bool] = None
        reminder_auto_send_enabled: Optional[bool] = None
        reminder_time: Optional[str] = Field(default=None, max_length=10)
        # bot fields
        bot_enabled: Optional[bool] = None
        auto_reply_enabled: Optional[bool] = None
        auto_order_enabled: Optional[bool] = None
        allow_part_payment: Optional[bool] = None
        payment_modes: Optional[str] = Field(default=None, max_length=200)
        delivery_note: Optional[str] = Field(default=None, max_length=500)
        pickup_address: Optional[str] = Field(default=None, max_length=200)

    @app.post("/app/api/automation")
    def web_update_automation(
        payload: AutomationUpdateRequest,
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            from customer_automation import get_or_create_automation_settings
            from reminder_automation import get_or_create_reminder_settings
            phone = _session_owner_phone(db, session)
            rem = get_or_create_reminder_settings(db, phone)
            if payload.reminder_preview_enabled is not None:
                rem.preview_enabled = payload.reminder_preview_enabled
            if payload.reminder_auto_send_enabled is not None:
                rem.auto_send_enabled = payload.reminder_auto_send_enabled
            if payload.reminder_time is not None:
                rem.reminder_time = payload.reminder_time.strip()
            bot = get_or_create_automation_settings(db, phone)
            if payload.bot_enabled is not None:
                bot.bot_enabled = payload.bot_enabled
            if payload.auto_reply_enabled is not None:
                bot.auto_reply_enabled = payload.auto_reply_enabled
            if payload.auto_order_enabled is not None:
                bot.auto_order_enabled = payload.auto_order_enabled
            if payload.allow_part_payment is not None:
                bot.allow_part_payment = payload.allow_part_payment
            if payload.payment_modes is not None:
                bot.payment_modes = payload.payment_modes.strip() or None
            if payload.delivery_note is not None:
                bot.delivery_note = payload.delivery_note.strip() or None
            if payload.pickup_address is not None:
                bot.pickup_address = payload.pickup_address.strip() or None
            db.commit()
            return {"status": "ok"}
        finally:
            db.close()

    # ── Export ───────────────────────────────────────────────────────────────
    @app.get("/app/api/export/dl/{token}")
    def web_export_download(token: str):
        """Public token-based CSV download — for WhatsApp download links."""
        from export_utils import build_export_csv, verify_export_token
        info = verify_export_token(token)
        if not info:
            raise HTTPException(status_code=410, detail="This export link has expired or is invalid.")
        db = SessionLocal()
        try:
            filename, csv_bytes = build_export_csv(db, info["phone"], info["period"], info["type"])
            return StreamingResponse(
                iter([csv_bytes]),
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{_safe_filename(filename)}"'},
            )
        finally:
            db.close()

    @app.get("/app/api/export")
    def web_export_authenticated(
        export_type: str = Query(default="transactions"),
        owner_phone: Optional[str] = Query(default=None),
        period: Optional[str] = Query(default=None),
        branch_id: Optional[int] = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        """Authenticated CSV export for the web dashboard."""
        from admin import is_app_admin
        from export_utils import build_export_csv
        db = SessionLocal()
        try:
            session_phone = _session_owner_phone(db, session)
            user = db.query(User).filter(User.id == session["user_id"]).first()
            # Admins may export any phone; everyone else is bound to their own business
            if owner_phone and user and is_app_admin(user.phone, db):
                phone = owner_phone
            else:
                phone = session_phone
            period_key = period.upper() if period else None
            filename, csv_bytes = build_export_csv(db, phone, period_key, export_type, branch_id=branch_id)
            return StreamingResponse(
                iter([csv_bytes]),
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{_safe_filename(filename)}"'},
            )
        finally:
            db.close()

    @app.get("/app/api/loan-statement/dl/{token}")
    def web_statement_download(token: str):
        """Public token-based PDF download — used in WhatsApp download links."""
        from export_utils import verify_export_token
        from loan_statement import generate_loan_statement
        from reports import (
            get_dashboard_summary, get_unpaid_debtors,
            get_owner_transaction_query, dashboard_period_label,
        )
        payload = verify_export_token(token)
        if not payload or payload.get("type") != "loan_statement":
            raise HTTPException(status_code=403, detail="Invalid or expired statement link.")

        phone      = payload["phone"]
        period_key = payload.get("period") or None

        db = SessionLocal()
        try:
            owner_user = db.query(User).filter(User.phone == phone).first()
            if not owner_user:
                raise HTTPException(status_code=404, detail="Business not found.")

            owner = {
                "name":               owner_user.name or phone,
                "phone":              phone,
                "business_type_label": owner_user.business_type_label,
                "business_category":  owner_user.business_category,
            }
            summary        = get_dashboard_summary(db, owner_phone=phone, period=period_key)
            debtors_raw, _ = get_unpaid_debtors(db, owner_phone=phone)
            period_lbl     = dashboard_period_label(period_key) if period_key else "all time"

            tx_rows = (
                get_owner_transaction_query(db, phone, period_key)
                .order_by(Transaction.created_at.desc()).limit(100).all()
            )
            cids = [r.customer_id for r in tx_rows if r.customer_id]
            customer_map = (
                {c.id: c.name for c in db.query(Customer).filter(Customer.id.in_(cids)).all()}
                if cids else {}
            )
            transactions = [
                {
                    "type": t.type, "customer": customer_map.get(t.customer_id),
                    "product": t.product, "amount": _money(t.amount), "created_at": t.created_at,
                }
                for t in tx_rows if not t.is_voided
            ]
            stock_items = [
                {
                    "name": item.name, "unit": item.unit,
                    "quantity": item.quantity or 0,
                    "selling_price": _money(item.selling_price) if item.selling_price else 0,
                }
                for item in (
                    db.query(InventoryItem)
                    .filter(InventoryItem.owner_phone == phone, InventoryItem.is_available == True)
                    .order_by(InventoryItem.name).all()
                )
            ]
            pdf_bytes = generate_loan_statement(
                owner=owner, summary=summary, transactions=transactions,
                debtors=debtors_raw, stock_items=stock_items,
                period_label=period_lbl, period=period_key,
            )
            biz_slug = (owner_user.name or "business").replace(" ", "_")[:20]
            filename = f"CreditVoice_Statement_{biz_slug}.pdf"
            return StreamingResponse(
                iter([pdf_bytes]),
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{_safe_filename(filename)}"'},
            )
        finally:
            db.close()

    @app.get("/app/api/loan-statement")
    def web_loan_statement(
        owner_phone: Optional[str] = Query(default=None),
        period: Optional[str]      = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        """Generate and return a loan-ready business statement PDF."""
        from loan_statement import generate_loan_statement
        from reports import (
            get_dashboard_summary, get_unpaid_debtors, get_owner_transaction_query,
            dashboard_period_label,
        )
        db = SessionLocal()
        try:
            from admin import is_app_admin
            session_user = db.query(User).filter(User.id == session["user_id"]).first()
            if owner_phone and session_user and is_app_admin(session_user.phone, db):
                phone = owner_phone
            else:
                phone = _session_owner_phone(db, session)
            period_key = period.upper() if period else None

            owner_user = db.query(User).filter(User.phone == phone).first()
            if not owner_user:
                raise HTTPException(status_code=404, detail="Business not found.")

            owner = {
                "name":               owner_user.name or phone,
                "phone":              phone,
                "business_type_label": owner_user.business_type_label,
                "business_category":  owner_user.business_category,
            }

            summary          = get_dashboard_summary(db, owner_phone=phone, period=period_key)
            debtors_raw, _   = get_unpaid_debtors(db, owner_phone=phone)
            period_lbl  = dashboard_period_label(period_key) if period_key else "all time"

            tx_rows = (
                get_owner_transaction_query(db, phone, period_key)
                .order_by(Transaction.created_at.desc())
                .limit(100)
                .all()
            )
            customer_map = {}
            cids = [r.customer_id for r in tx_rows if r.customer_id]
            if cids:
                customer_map = {
                    c.id: c.name
                    for c in db.query(Customer).filter(Customer.id.in_(cids)).all()
                }

            transactions = [
                {
                    "type":       t.type,
                    "customer":   customer_map.get(t.customer_id),
                    "product":    t.product,
                    "amount":     _money(t.amount),
                    "created_at": t.created_at,
                }
                for t in tx_rows
                if not t.is_voided
            ]

            stock_items = [
                {
                    "name":          item.name,
                    "unit":          item.unit,
                    "quantity":      item.quantity or 0,
                    "selling_price": _money(item.selling_price) if item.selling_price else 0,
                }
                for item in (
                    db.query(InventoryItem)
                    .filter(InventoryItem.owner_phone == phone, InventoryItem.is_available == True)
                    .order_by(InventoryItem.name)
                    .all()
                )
            ]

            pdf_bytes = generate_loan_statement(
                owner        = owner,
                summary      = summary,
                transactions = transactions,
                debtors      = debtors_raw,
                stock_items  = stock_items,
                period_label = period_lbl,
                period       = period_key,
            )

            biz_slug = (owner_user.name or "business").replace(" ", "_")[:20]
            filename = f"CreditVoice_Statement_{biz_slug}_{period_lbl.replace(' ', '_')}.pdf"
            return StreamingResponse(
                iter([pdf_bytes]),
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{_safe_filename(filename)}"'},
            )
        finally:
            db.close()

    # ── Notifications (the bell) — split into web_notifications_routes ────────
    from web_notifications_routes import register_notification_routes
    register_notification_routes(app)

    class AdminNotifyRequest(BaseModel):
        title: str = Field(max_length=120)
        body: str = Field(max_length=1000)
        target: str = "all"                       # "all" business owners, or "phone"
        phone: Optional[str] = Field(default=None, max_length=20)
        also_whatsapp: bool = False

    @app.post("/app/api/admin/notifications")
    def web_admin_send_notification(payload: AdminNotifyRequest, session: dict = Depends(require_web_auth)):
        """App admin broadcasts an in-app notification to one user or all business
        owners (optionally also via WhatsApp)."""
        from admin import is_app_admin
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user or not is_app_admin(user.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(user.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")
            title = payload.title.strip()
            body = payload.body.strip()
            if not title or not body:
                raise HTTPException(status_code=400, detail="Title and message are required.")

            if payload.target == "phone":
                from parser import normalize_phone
                target = db.query(User).filter(
                    User.phone.in_([p for p in {(payload.phone or "").strip(), normalize_phone(payload.phone or "")} if p]),
                    User.parent_id.is_(None),
                ).first()
                if not target:
                    raise HTTPException(status_code=404, detail="No business owner with that phone.")
                phones = [target.phone]
            else:
                phones = [
                    r[0] for r in db.query(User.phone).filter(
                        User.parent_id.is_(None), User.deleted_at.is_(None)
                    ).all() if r[0]
                ]

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            for ph in phones:
                db.add(AppNotification(owner_phone=ph, event_type="admin",
                                       title=title, body=body, is_read=0, created_at=now))
            db.commit()

            sent_wa = 0
            if payload.also_whatsapp:
                from whatsapp_client import send_whatsapp_message
                for ph in phones:
                    try:
                        if send_whatsapp_message(ph, f"*{title}*\n\n{body}"):
                            sent_wa += 1
                    except Exception:
                        pass
            return {"ok": True, "recipients": len(phones), "whatsapp_sent": sent_wa}
        finally:
            db.close()

    # ── Admin: failed parse log ───────────────────────────────────────────────
    @app.get("/app/api/admin/failed-parses")
    def web_admin_failed_parses(
        limit: int = Query(default=200, le=1000),
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
            rows = (
                db.query(FailedParse)
                .order_by(FailedParse.created_at.desc())
                .limit(limit)
                .all()
            )
            return {"rows": [
                {
                    "id": r.id,
                    "phone": r.phone,
                    "text": r.text,
                    "resolved_by": r.resolved_by,
                    "llm_reply": r.llm_reply,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]}
        finally:
            db.close()

    @app.get("/app/api/admin/failed-parses/export")
    def web_admin_failed_parses_export(
        session: dict = Depends(require_web_auth),
    ):
        import csv, io
        from admin import is_app_admin
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user or not is_app_admin(user.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _export_rate_check(user.phone):
                raise HTTPException(status_code=429, detail="Export limit reached. Max 3 exports per hour.")
            from audit import audit
            audit(db, action="ADMIN_DATA_EXPORT", actor_id=user.id, actor_phone=user.phone,
                  resource="failed_parses.csv")
            db.commit()
            rows = db.query(FailedParse).order_by(FailedParse.created_at.desc()).limit(5000).all()
            from export_utils import _csv_safe
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["id", "phone", "text", "resolved_by", "llm_reply", "created_at"])
            for r in rows:
                writer.writerow([_csv_safe(v) for v in (
                    r.id, r.phone, r.text, r.resolved_by or "",
                    r.llm_reply or "",
                    r.created_at.isoformat() if r.created_at else "",
                )])
            output.seek(0)
            return StreamingResponse(
                iter([output.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=failed_parses.csv"},
            )
        finally:
            db.close()

    # ── Admin: overview stats ──────────────────────────────────────────────────
    @app.get("/app/api/admin/stats")
    def web_admin_stats(session: dict = Depends(require_web_auth)):
        from admin import is_app_admin
        from datetime import timedelta
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user or not is_app_admin(user.phone, db):
                raise HTTPException(status_code=403, detail="Admin only")
            if not _admin_rate_check(user.phone):
                raise HTTPException(status_code=429, detail="Too many admin requests. Slow down.")

            now = utcnow()
            today_start   = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start    = today_start - timedelta(days=7)
            month_start   = today_start - timedelta(days=30)

            total_users   = db.query(User).filter(User.parent_id == None).count()
            new_today     = db.query(User).filter(User.parent_id == None, User.created_at >= today_start).count()
            new_this_week = db.query(User).filter(User.parent_id == None, User.created_at >= week_start).count()
            new_this_month= db.query(User).filter(User.parent_id == None, User.created_at >= month_start).count()

            total_tx      = db.query(Transaction).count()
            tx_today      = db.query(Transaction).filter(Transaction.created_at >= today_start).count()
            tx_this_week  = db.query(Transaction).filter(Transaction.created_at >= week_start).count()

            failed_total  = db.query(FailedParse).count()
            failed_today  = db.query(FailedParse).filter(FailedParse.created_at >= today_start).count()
            llm_resolved  = db.query(FailedParse).filter(FailedParse.resolved_by == "llm").count()

            # Signup trend: last 14 days
            signup_trend = []
            for i in range(13, -1, -1):
                day_start = today_start - timedelta(days=i)
                day_end   = day_start + timedelta(days=1)
                count = db.query(User).filter(
                    User.parent_id == None,
                    User.created_at >= day_start,
                    User.created_at < day_end,
                ).count()
                signup_trend.append({
                    "date": day_start.strftime("%b %d"),
                    "signups": count,
                })

            # Tx trend: last 14 days
            tx_trend = []
            for i in range(13, -1, -1):
                day_start = today_start - timedelta(days=i)
                day_end   = day_start + timedelta(days=1)
                count = db.query(Transaction).filter(
                    Transaction.created_at >= day_start,
                    Transaction.created_at < day_end,
                ).count()
                tx_trend.append({
                    "date": day_start.strftime("%b %d"),
                    "transactions": count,
                })

            # Business type breakdown
            biz_types = {}
            for u in db.query(User).filter(User.parent_id == None).all():
                key = u.business_type_label or u.business_type or "Unknown"
                biz_types[key] = biz_types.get(key, 0) + 1

            biz_breakdown = sorted(
                [{"label": k, "count": v} for k, v in biz_types.items()],
                key=lambda x: -x["count"]
            )[:10]

            return {
                "users": {
                    "total": total_users,
                    "new_today": new_today,
                    "new_this_week": new_this_week,
                    "new_this_month": new_this_month,
                    "signup_trend": signup_trend,
                },
                "transactions": {
                    "total": total_tx,
                    "today": tx_today,
                    "this_week": tx_this_week,
                    "tx_trend": tx_trend,
                },
                "failed_parses": {
                    "total": failed_total,
                    "today": failed_today,
                    "llm_resolved": llm_resolved,
                },
                "business_breakdown": biz_breakdown,
            }
        finally:
            db.close()

    @app.get("/app/api/admin/users")
    def web_admin_users(
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=50, le=200),
        q: str = Query(default=""),
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

            query = db.query(User).filter(User.parent_id == None)
            if q:
                like = f"%{q}%"
                query = query.filter(
                    User.name.ilike(like) | User.phone.ilike(like) | User.email.ilike(like)
                )

            total = query.count()
            rows  = query.order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

            return {
                "total": total,
                "page": page,
                "per_page": per_page,
                "users": [
                    {
                        "id": u.id,
                        "name": u.name,
                        "phone": u.phone,
                        "email": u.email,
                        "business_type_label": u.business_type_label or u.business_type,
                        "subscription_plan": u.subscription_plan,
                        "subscription_status": u.subscription_status,
                        "created_at": u.created_at.isoformat() if u.created_at else None,
                    }
                    for u in rows
                ],
            }
        finally:
            db.close()

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
