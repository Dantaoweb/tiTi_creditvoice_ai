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
    get_owner_transaction_query,
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


# ── Demo endpoint rate limiter ────────────────────────────────────────────────
_demo_lock = threading.Lock()
_demo_hits: dict = defaultdict(list)
_DEMO_LIMIT = 20   # requests per IP
_DEMO_WINDOW = 60  # per 60 seconds


def _demo_rate_check(ip: str) -> bool:
    now = time.time()
    cutoff = now - _DEMO_WINDOW
    with _demo_lock:
        hits = [t for t in _demo_hits[ip] if t > cutoff]
        if len(hits) >= _DEMO_LIMIT:
            _demo_hits[ip] = hits
            return False
        hits.append(now)
        _demo_hits[ip] = hits
        return True


# ── AI endpoint rate limiter (voice transcription + chat) ─────────────────────
# 30 AI calls per user per hour to cap OpenAI spend
_ai_lock = threading.Lock()
_ai_hits: dict = defaultdict(list)
_AI_LIMIT  = 30
_AI_WINDOW = 3600


def _ai_rate_check(user_id: str) -> bool:
    now = time.time()
    cutoff = now - _AI_WINDOW
    with _ai_lock:
        hits = [t for t in _ai_hits[user_id] if t > cutoff]
        if len(hits) >= _AI_LIMIT:
            _ai_hits[user_id] = hits
            return False
        hits.append(now)
        _ai_hits[user_id] = hits
        return True


_admin_lock = threading.Lock()
_admin_hits: dict = defaultdict(list)
_ADMIN_LIMIT  = 120   # requests per minute per admin
_ADMIN_WINDOW = 60

_export_lock = threading.Lock()
_export_hits: dict = defaultdict(list)
_EXPORT_LIMIT  = 3    # CSV exports per hour per admin
_EXPORT_WINDOW = 3600

_redeem_lock = threading.Lock()
_redeem_hits: dict = defaultdict(list)
_REDEEM_LIMIT  = 10   # token-code attempts per hour per user
_REDEEM_WINDOW = 3600


def _admin_rate_check(phone: str) -> bool:
    now = time.time()
    cutoff = now - _ADMIN_WINDOW
    with _admin_lock:
        hits = [t for t in _admin_hits[phone] if t > cutoff]
        if len(hits) >= _ADMIN_LIMIT:
            _admin_hits[phone] = hits
            return False
        hits.append(now)
        _admin_hits[phone] = hits
        return True


def _export_rate_check(phone: str) -> bool:
    now = time.time()
    cutoff = now - _EXPORT_WINDOW
    with _export_lock:
        hits = [t for t in _export_hits[phone] if t > cutoff]
        if len(hits) >= _EXPORT_LIMIT:
            _export_hits[phone] = hits
            return False
        hits.append(now)
        _export_hits[phone] = hits
        return True


def _redeem_rate_check(user_id: str) -> bool:
    now = time.time()
    cutoff = now - _REDEEM_WINDOW
    with _redeem_lock:
        hits = [t for t in _redeem_hits[user_id] if t > cutoff]
        if len(hits) >= _REDEEM_LIMIT:
            _redeem_hits[user_id] = hits
            return False
        hits.append(now)
        _redeem_hits[user_id] = hits
        return True


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

class StaffInviteRequest(BaseModel):
    name: str = Field(max_length=120)
    phone: str = Field(max_length=20)
    email: Optional[str] = Field(default=None, max_length=254)

class StaffAcceptRequest(BaseModel):
    phone: str = Field(max_length=20)
    code: str = Field(max_length=10)

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
    items: list[PosCartItem] = Field(max_length=200)  # max 200 line items per sale
    payment_amount: int = 0
    branch_id: Optional[int] = None
    due_date: Optional[datetime] = None


class AddInventoryRequest(BaseModel):
    owner_phone: str = Field(max_length=20)
    name: str = Field(max_length=120)
    unit: Optional[str] = Field(default=None, max_length=30)
    quantity: Optional[float] = 0.0
    cost_price: Optional[int] = None
    selling_price: Optional[int] = None
    low_stock_alert: Optional[int] = None
    is_service: bool = False
    retail_unit: Optional[str] = Field(default=None, max_length=30)
    retail_per_base: Optional[int] = None
    retail_price: Optional[int] = None


class EditInventoryRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    unit: Optional[str] = Field(default=None, max_length=30)
    cost_price: Optional[int] = None
    selling_price: Optional[int] = None
    low_stock_alert: Optional[int] = None
    is_available: Optional[bool] = None
    retail_unit: Optional[str] = Field(default=None, max_length=30)
    retail_per_base: Optional[int] = None
    retail_price: Optional[int] = None


class AdjustStockRequest(BaseModel):
    qty_delta: int
    note: Optional[str] = Field(default=None, max_length=500)


class BulkAddInventoryRequest(BaseModel):
    owner_phone: str = Field(max_length=20)
    names: list[str] = Field(max_length=100)  # max 100 items; each str validated below


class AddCustomerRequest(BaseModel):
    owner_phone: str = Field(max_length=20)
    name: str = Field(max_length=120)
    phone: Optional[str] = Field(default=None, max_length=20)


class RecordPaymentRequest(BaseModel):
    amount: int
    note: Optional[str] = Field(default=None, max_length=500)
    branch_id: Optional[int] = None


class CreateBranchRequest(BaseModel):
    name: str = Field(max_length=60)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _money(value):
    return int(value or 0)


def _iso(value):
    return value.isoformat() if value else None


def _safe_filename(name: str) -> str:
    """Strip characters that could break a Content-Disposition filename= field."""
    import re
    return re.sub(r'["\\\r\n;]', "_", name)


def _owner_filter(query, model, owner_phone):
    if owner_phone:
        return query.filter(model.owner_phone == owner_phone)
    return query


def _active_inventory_count(db, owner_phone: str) -> int:
    """Count inventory items that are 'active' — have a selling price set."""
    from models import InventoryItem
    return db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        InventoryItem.selling_price != None,
    ).count()


def _check_inventory_limit(db, owner_phone: str, subscription) -> str | None:
    """Return an error message if the owner is at their active inventory limit, else None."""
    from plans import plan_limit, normalize_plan
    plan = normalize_plan(getattr(subscription, "plan", "BASIC") if subscription else "BASIC")
    limit = plan_limit(plan, "active_inventory_items")
    if limit is None:
        return None
    count = _active_inventory_count(db, owner_phone)
    if count >= limit:
        return (
            f"You have reached the Basic plan limit of {limit} active products. "
            f"Draft items (no price set) are unlimited. "
            f"Upgrade to Go to add unlimited active products."
        )
    return None


def _session_owner_phone(db, session: dict) -> str:
    """Resolve the business owner phone from a web session.
    Staff members' sessions resolve to their owner's phone automatically.
    Raises 401 if the user is not found.
    """
    from fastapi import HTTPException
    user = db.query(User).filter(User.id == session["user_id"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    if user.parent_id:
        owner = db.query(User).filter(User.id == user.parent_id).first()
        return owner.phone if owner else user.phone
    return user.phone


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
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                from fastapi import HTTPException
                raise HTTPException(status_code=401, detail="User not found.")

            # Enforce expiry: downgrade to BASIC if subscription has lapsed
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if (
                user.subscription_plan not in (None, "BASIC")
                and user.subscription_expires_at
                and user.subscription_expires_at < now
            ):
                user.subscription_plan = "BASIC"
                user.subscription_status = "EXPIRED"
                db.commit()

            from business_templates import menu_group_for_user
            return {
                "id": user.id,
                "name": user.name,
                "phone": user.phone,
                "email": user.email,
                "role": user.role,
                "plan": user.subscription_plan,
                "subscription_plan": user.subscription_plan,
                "subscription_expires_at": user.subscription_expires_at.isoformat() if user.subscription_expires_at else None,
                "business_category": user.business_category,
                "business_type": user.business_type,
                "business_type_label": user.business_type_label,
                "menu_group": menu_group_for_user(user),
                "whatsapp_linked": bool(user.whatsapp_linked),
                "newsletter_consent": bool(user.newsletter_consent),
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
            summary = get_dashboard_summary(db, owner_phone, period_key, branch_id=branch_id)
            debtors, _ = get_unpaid_debtors(db, owner_phone)
            low_stock_count = db.query(InventoryItem).filter(
                InventoryItem.owner_phone == owner_phone,
                InventoryItem.is_available == True,
                InventoryItem.low_stock_alert != None,
                InventoryItem.quantity <= InventoryItem.low_stock_alert,
            ).count()
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
                    send_whatsapp_message(
                        phone,
                        "Your previous session has expired.\n\nSend your message again to continue.",
                    )
                    return {"reply": "\n\n".join(collected) or "Session expired.", "ok": False}

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
        finally:
            db.close()

    @app.post("/app/api/capture/voice")
    def web_capture_voice(payload: CaptureVoiceRequest, session: dict = Depends(require_web_auth)):
        if not _ai_rate_check(str(session["user_id"])):
            raise HTTPException(status_code=429, detail="AI request limit reached. Try again in an hour.")
        db = SessionLocal()
        try:
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
            result = save_pos_sale(
                db,
                owner_phone,
                session["user_id"],
                payload.customer_id,
                items,
                payload.payment_amount,
                branch_id=payload.branch_id,
                due_date=payload.due_date,
            )
            return result
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

    # ── Customers ────────────────────────────────────────────────────────
    @app.get("/app/api/customers")
    def web_customers(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            query = _owner_filter(db.query(Customer), Customer, owner_phone)
            rows = query.order_by(Customer.created_at.desc()).limit(200).all()
            return {
                "customers": [
                    {
                        "id": c.id,
                        "name": c.name,
                        "phone": c.customer_phone,
                        "owner_phone": c.owner_phone,
                        "balance": _money(get_balance(db, c.id)),
                        "created_at": _iso(c.created_at),
                    }
                    for c in rows
                ]
            }
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
            c = Customer(
                owner_phone=owner_phone,
                name=payload.name.strip(),
                customer_phone=(payload.phone or "").strip() or None,
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
            return {"id": tx.id, "amount": payload.amount, "new_balance": new_balance}
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
            query = get_owner_transaction_query(db, owner_phone, period_key, include_voided=True)
            if branch_id is not None:
                query = query.filter(Transaction.branch_id == branch_id)
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

    # ── Inventory ─────────────────────────────────────────────────────────
    @app.get("/app/api/inventory")
    def web_inventory(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            query = _owner_filter(db.query(InventoryItem), InventoryItem, owner_phone)
            rows = query.order_by(InventoryItem.updated_at.desc()).limit(200).all()
            return {
                "items": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "unit": item.unit,
                        "quantity": item.quantity,
                        "cost_price": _money(item.cost_price),
                        "selling_price": _money(item.selling_price),
                        "low_stock_alert": item.low_stock_alert,
                        "is_available": bool(item.is_available),
                        "is_service": item.quantity is None or item.category == "service",
                        "retail_unit": item.retail_unit,
                        "retail_per_base": item.retail_per_base,
                        "retail_price": item.retail_price,
                        "updated_at": _iso(item.updated_at),
                    }
                    for item in rows
                ]
            }
        finally:
            db.close()

    @app.post("/app/api/inventory")
    def web_add_inventory(
        payload: AddInventoryRequest,
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)

            # Enforce active-inventory limit for Basic plan when a price is being set
            if payload.selling_price is not None:
                from subscriptions import get_business_subscription
                owner = db.query(User).filter(User.phone == owner_phone).first()
                sub = get_business_subscription(db, owner) if owner else None
                err = _check_inventory_limit(db, owner_phone, sub)
                if err:
                    from fastapi import HTTPException
                    raise HTTPException(status_code=403, detail=err)

            _qty = None if payload.is_service else (payload.quantity or 0.0)
            item = InventoryItem(
                owner_phone=owner_phone,
                name=payload.name.strip().lower(),
                unit=(payload.unit or "").strip() or None,
                quantity=_qty,
                cost_price=None if payload.is_service else payload.cost_price,
                selling_price=payload.selling_price,
                low_stock_alert=None if payload.is_service else payload.low_stock_alert,
                is_available=True,
                category="service" if payload.is_service else None,
                retail_unit=payload.retail_unit.strip().lower() if payload.retail_unit else None,
                retail_per_base=payload.retail_per_base,
                retail_price=payload.retail_price,
            )
            db.add(item)
            if not payload.is_service and _qty:
                db.flush()
                db.add(InventoryMovement(
                    owner_phone=owner_phone,
                    item_id=item.id,
                    movement_type="IN",
                    quantity=_qty,
                    unit_price=payload.cost_price,
                    source_type="WEB_ADD",
                    source_id=None,
                    recorded_by_id=session["user_id"],
                    note="Initial stock",
                ))
            db.commit()
            db.refresh(item)
            return {
                "id": item.id, "name": item.name, "unit": item.unit,
                "quantity": item.quantity or 0,
                "cost_price": _money(item.cost_price),
                "selling_price": _money(item.selling_price),
            }
        finally:
            db.close()

    @app.get("/app/api/inventory/catalog")
    def web_inventory_catalog(session: dict = Depends(require_web_auth)):
        from business_templates import INDUSTRY_PRODUCT_CATALOG, template_key_for_user
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            key = template_key_for_user(user) if user else None
            btype = getattr(user, "business_type", None) if user else None
            entries = (
                INDUSTRY_PRODUCT_CATALOG.get(btype)
                or (INDUSTRY_PRODUCT_CATALOG.get(key, []) if key else [])
                or INDUSTRY_PRODUCT_CATALOG.get("retail_trading", [])
            )
            categories = {}
            for name, cat in entries:
                categories.setdefault(cat, []).append(name)
            return {"catalog": categories}
        finally:
            db.close()

    @app.post("/app/api/inventory/bulk")
    def web_bulk_add_inventory(
        payload: BulkAddInventoryRequest,
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            saved, skipped = 0, 0
            for raw in payload.names:
                name_clean = str(raw).strip().lower()
                if not name_clean:
                    continue
                existing = db.query(InventoryItem).filter(
                    InventoryItem.owner_phone == owner_phone,
                    InventoryItem.name == name_clean,
                ).first()
                if existing:
                    skipped += 1
                else:
                    db.add(InventoryItem(
                        owner_phone=owner_phone,
                        name=name_clean,
                        is_available=True,
                        is_service=False,
                    ))
                    saved += 1
            if saved:
                db.commit()
            return {"saved": saved, "already_existed": skipped}
        finally:
            db.close()

    @app.put("/app/api/inventory/{item_id}")
    def web_edit_inventory(
        item_id: int,
        payload: EditInventoryRequest,
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            item = db.query(InventoryItem).filter(
                InventoryItem.id == item_id,
                InventoryItem.owner_phone == owner_phone,
            ).first()
            if not item:
                raise HTTPException(status_code=404, detail="Item not found.")
            if payload.name is not None:
                item.name = payload.name.strip().lower()
            if payload.unit is not None:
                item.unit = payload.unit.strip() or None
            if payload.cost_price is not None:
                item.cost_price = payload.cost_price
            if payload.selling_price is not None:
                # Only enforce limit when activating a previously draft item
                if item.selling_price is None:
                    from subscriptions import get_business_subscription
                    owner = db.query(User).filter(User.phone == owner_phone).first()
                    sub = get_business_subscription(db, owner) if owner else None
                    err = _check_inventory_limit(db, owner_phone, sub)
                    if err:
                        raise HTTPException(status_code=403, detail=err)
                item.selling_price = payload.selling_price
            if payload.low_stock_alert is not None:
                item.low_stock_alert = payload.low_stock_alert
            if payload.is_available is not None:
                item.is_available = payload.is_available
            if payload.retail_unit is not None:
                item.retail_unit = payload.retail_unit.strip().lower() or None
            if payload.retail_per_base is not None:
                item.retail_per_base = payload.retail_per_base or None
            if payload.retail_price is not None:
                item.retail_price = payload.retail_price or None
            item.updated_at = utcnow()
            db.commit()
            return {"id": item.id, "name": item.name, "selling_price": _money(item.selling_price)}
        finally:
            db.close()

    @app.post("/app/api/inventory/{item_id}/adjust")
    def web_adjust_stock(
        item_id: int,
        payload: AdjustStockRequest,
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            item = db.query(InventoryItem).filter(
                InventoryItem.id == item_id,
                InventoryItem.owner_phone == owner_phone,
            ).first()
            if not item:
                raise HTTPException(status_code=404, detail="Item not found.")
            delta = payload.qty_delta
            item.quantity = (item.quantity or 0) + delta
            item.updated_at = utcnow()
            db.add(InventoryMovement(
                owner_phone=item.owner_phone,
                item_id=item.id,
                movement_type="IN" if delta > 0 else "OUT",
                quantity=abs(delta),
                source_type="WEB_ADJUST",
                source_id=None,
                recorded_by_id=session["user_id"],
                note=payload.note or ("Stock added" if delta > 0 else "Stock removed"),
            ))
            db.commit()
            return {"id": item.id, "new_quantity": item.quantity}
        finally:
            db.close()

    # ── Suppliers ─────────────────────────────────────────────────────────
    @app.get("/app/api/suppliers")
    def web_suppliers(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            query = _owner_filter(db.query(Supplier), Supplier, owner_phone)
            suppliers = query.order_by(Supplier.name).all()

            result = []
            for sup in suppliers:
                purchases = db.query(SupplierPurchase).filter(
                    SupplierPurchase.supplier_id == sup.id
                ).all()
                payments = db.query(SupplierPayment).filter(
                    SupplierPayment.supplier_id == sup.id
                ).all()

                total_bought = sum(p.total or 0 for p in purchases)
                paid_via_purchase = sum(p.paid_amount or 0 for p in purchases)
                paid_via_payment = sum(p.amount or 0 for p in payments)
                total_paid = paid_via_purchase + paid_via_payment
                balance = max(0, total_bought - total_paid)

                now = datetime.now(timezone.utc)
                due_dates = [
                    p.due_date for p in purchases
                    if p.due_date and (p.total or 0) > (p.paid_amount or 0)
                ]
                has_overdue = any(d < now for d in due_dates)
                next_due = min(due_dates, default=None)

                result.append({
                    "id": sup.id,
                    "name": sup.name,
                    "purchases": len(purchases),
                    "total_bought": total_bought,
                    "total_paid": total_paid,
                    "balance": balance,
                    "has_overdue": has_overdue,
                    "next_due": _iso(next_due),
                    "created_at": _iso(sup.created_at),
                })

            recent_query = db.query(SupplierPurchase)
            if owner_phone:
                recent_query = recent_query.filter(SupplierPurchase.owner_phone == owner_phone)
            recent = recent_query.order_by(SupplierPurchase.created_at.desc()).limit(50).all()
            sup_names = {s.id: s.name for s in suppliers}

            return {
                "suppliers": sorted(result, key=lambda r: r["balance"], reverse=True),
                "recent_purchases": [
                    {
                        "id": p.id,
                        "supplier": sup_names.get(p.supplier_id, "Unknown"),
                        "product": p.product,
                        "quantity": p.quantity,
                        "unit": p.unit,
                        "total": _money(p.total),
                        "paid_amount": _money(p.paid_amount),
                        "due_date": _iso(p.due_date),
                        "created_at": _iso(p.created_at),
                    }
                    for p in recent
                ],
            }
        finally:
            db.close()

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
            if not owner or owner.role != "user" or owner.parent_id is not None:
                return {"members": []}
            members = db.query(User).filter(User.parent_id == owner.id).all()
            return {
                "members": [
                    {
                        "id": m.id,
                        "name": m.name,
                        "phone": m.phone,
                        "email": m.email,
                        "role": m.role,
                        "pending": m.role == "delegate_pending",
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
            if not owner or owner.role != "user" or owner.parent_id is not None:
                raise HTTPException(status_code=403, detail="Only business owners can invite staff.")

            subscription = get_business_subscription(db, owner)
            allowed, upgrade_msg = ensure_feature_allowed(db, owner, "STAFF", "Staff management")
            if not allowed:
                raise HTTPException(status_code=403, detail=upgrade_msg)

            staff_allowed, staff_limit_msg = check_staff_limit(db, owner, subscription)
            if not staff_allowed:
                raise HTTPException(status_code=403, detail=staff_limit_msg)

            staff_phone = payload.phone.strip()
            staff_name = payload.name.strip()
            staff_email = (payload.email or "").strip() or None

            staff_user = db.query(User).filter(User.phone == staff_phone).first()
            if staff_user:
                staff_user.role = "delegate_pending"
                staff_user.parent_id = owner.id
                staff_user.name = staff_name
                if staff_email:
                    staff_user.email = staff_email
                staff_user.can_view_all_transactions = False
            else:
                staff_user = User(
                    phone=staff_phone,
                    name=staff_name,
                    email=staff_email,
                    role="delegate_pending",
                    parent_id=owner.id,
                    can_view_all_transactions=False,
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

    @app.post("/app/api/staff/accept")
    def web_staff_accept(payload: StaffAcceptRequest):
        """Staff member accepts an invitation using their phone + the code the owner shared."""
        from datetime import timezone as _tz
        MAX_ATTEMPTS = 3

        db = SessionLocal()
        try:
            phone = payload.phone.strip()
            code = payload.code.strip()

            staff_user = db.query(User).filter(User.phone == phone).first()
            if not staff_user or staff_user.role != "delegate_pending":
                raise HTTPException(status_code=404, detail="No pending invitation found for this phone number.")

            # Expired
            if staff_user.invite_expires_at and staff_user.invite_expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
                staff_user.role = "user"
                staff_user.parent_id = None
                staff_user.invite_code = None
                staff_user.invite_code_attempts = 0
                staff_user.invite_expires_at = None
                db.commit()
                raise HTTPException(status_code=410, detail="This invitation has expired. Ask the owner to send a new one.")

            # Too many attempts
            attempts = staff_user.invite_code_attempts or 0
            if attempts >= MAX_ATTEMPTS:
                staff_user.role = "user"
                staff_user.parent_id = None
                staff_user.invite_code = None
                staff_user.invite_code_attempts = 0
                staff_user.invite_expires_at = None
                db.commit()
                raise HTTPException(status_code=429, detail="Too many wrong attempts. Ask the owner to send a new invitation.")

            # Wrong code
            if not staff_user.invite_code or code != staff_user.invite_code:
                staff_user.invite_code_attempts = attempts + 1
                remaining = MAX_ATTEMPTS - staff_user.invite_code_attempts
                db.commit()
                raise HTTPException(status_code=400, detail=f"Wrong code. {remaining} attempt(s) remaining.")

            # Accept
            staff_user.role = "delegate"
            staff_user.invite_code = None
            staff_user.invite_code_attempts = 0
            staff_user.invite_expires_at = None
            db.commit()

            has_pin = bool(staff_user.recovery_pin_hash)
            return {"ok": True, "name": staff_user.name, "has_pin": has_pin}
        finally:
            db.close()

    # ── Branches ─────────────────────────────────────────────────────────
    @app.get("/app/api/branches")
    def web_branches(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            owner_phone = session["phone"]
            if user and user.parent_id:
                owner = db.query(User).filter(User.id == user.parent_id).first()
                owner_phone = owner.phone if owner else owner_phone
            rows = db.query(Branch).filter(Branch.owner_phone == owner_phone).order_by(Branch.created_at).all()
            return {
                "branches": [
                    {"id": b.id, "name": b.name, "is_default": bool(b.is_default), "created_at": _iso(b.created_at)}
                    for b in rows
                ]
            }
        finally:
            db.close()

    @app.post("/app/api/branches")
    def web_create_branch(payload: CreateBranchRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            owner_phone = session["phone"]
            if user and user.parent_id:
                owner = db.query(User).filter(User.id == user.parent_id).first()
                owner_phone = owner.phone if owner else owner_phone
            name = payload.name.strip()
            if not name:
                raise HTTPException(status_code=400, detail="Branch name is required.")
            existing = db.query(Branch).filter(
                Branch.owner_phone == owner_phone,
                Branch.name == name,
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail="A branch with that name already exists.")
            is_first = db.query(Branch).filter(Branch.owner_phone == owner_phone).count() == 0
            branch = Branch(owner_phone=owner_phone, name=name, is_default=is_first)
            db.add(branch)
            db.commit()
            return {"id": branch.id, "name": branch.name, "is_default": bool(branch.is_default)}
        finally:
            db.close()

    @app.delete("/app/api/branches/{branch_id}")
    def web_delete_branch(branch_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            owner_phone = session["phone"]
            if user and user.parent_id:
                owner = db.query(User).filter(User.id == user.parent_id).first()
                owner_phone = owner.phone if owner else owner_phone
            branch = db.query(Branch).filter(Branch.id == branch_id, Branch.owner_phone == owner_phone).first()
            if not branch:
                raise HTTPException(status_code=404, detail="Branch not found.")
            was_default = branch.is_default
            from audit import audit
            audit(db, action="DELETE_BRANCH", actor_id=session["user_id"],
                  actor_phone=session["phone"], resource=f"branch:{branch_id}:{branch.name}")
            db.delete(branch)
            db.commit()
            if was_default:
                first = db.query(Branch).filter(Branch.owner_phone == owner_phone).order_by(Branch.created_at).first()
                if first:
                    first.is_default = True
                    db.commit()
            return {"ok": True}
        finally:
            db.close()

    @app.post("/app/api/branches/{branch_id}/default")
    def web_set_default_branch(branch_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            owner_phone = session["phone"]
            if user and user.parent_id:
                owner = db.query(User).filter(User.id == user.parent_id).first()
                owner_phone = owner.phone if owner else owner_phone
            db.query(Branch).filter(Branch.owner_phone == owner_phone).update({"is_default": False})
            branch = db.query(Branch).filter(Branch.id == branch_id, Branch.owner_phone == owner_phone).first()
            if not branch:
                raise HTTPException(status_code=404, detail="Branch not found.")
            branch.is_default = True
            db.commit()
            return {"ok": True, "default_branch_id": branch_id}
        finally:
            db.close()

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

    # ── School Teacher Roster ─────────────────────────────────────────────────

    class SchoolTeacherRequest(BaseModel):
        name: str = Field(max_length=120)
        subject: Optional[str] = Field(default=None, max_length=60)
        class_name: Optional[str] = Field(default=None, max_length=60)
        phone: Optional[str] = Field(default=None, max_length=20)
        employee_id: Optional[str] = Field(default=None, max_length=60)

    @app.get("/app/api/school/teachers")
    def web_school_teachers(session: dict = Depends(require_web_auth)):
        from models import SchoolTeacher
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            rows = db.query(SchoolTeacher).filter(
                SchoolTeacher.owner_phone == owner_phone
            ).order_by(SchoolTeacher.name).all()
            return {"teachers": [
                {"id": r.id, "name": r.name, "subject": r.subject,
                 "class_name": r.class_name, "phone": r.phone,
                 "employee_id": r.employee_id}
                for r in rows
            ]}
        finally:
            db.close()

    @app.post("/app/api/school/teachers")
    def web_add_school_teacher(
        payload: SchoolTeacherRequest,
        session: dict = Depends(require_web_auth),
    ):
        from models import SchoolTeacher
        from subscriptions import get_business_subscription
        from plans import plan_limit, normalize_plan
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            owner = db.query(User).filter(User.phone == owner_phone).first()
            sub = get_business_subscription(db, owner) if owner else None
            plan = normalize_plan(getattr(sub, "plan", "BASIC") if sub else "BASIC")
            limit = plan_limit(plan, "school_teachers")
            if limit is not None:
                count = db.query(SchoolTeacher).filter(
                    SchoolTeacher.owner_phone == owner_phone
                ).count()
                if count >= limit:
                    raise HTTPException(
                        status_code=403,
                        detail=(
                            f"You have reached the Basic limit of {limit} teacher records. "
                            "Upgrade to Go or Pro to add more teachers."
                        ),
                    )
            teacher = SchoolTeacher(
                owner_phone=owner_phone,
                name=payload.name.strip(),
                subject=payload.subject,
                class_name=payload.class_name,
                phone=payload.phone,
                employee_id=payload.employee_id,
            )
            db.add(teacher)
            db.commit()
            db.refresh(teacher)
            return {"id": teacher.id, "name": teacher.name}
        finally:
            db.close()

    @app.put("/app/api/school/teachers/{teacher_id}")
    def web_edit_school_teacher(
        teacher_id: int,
        payload: SchoolTeacherRequest,
        session: dict = Depends(require_web_auth),
    ):
        from models import SchoolTeacher
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            teacher = db.query(SchoolTeacher).filter(
                SchoolTeacher.id == teacher_id,
                SchoolTeacher.owner_phone == owner_phone,
            ).first()
            if not teacher:
                raise HTTPException(status_code=404, detail="Teacher not found.")
            teacher.name       = payload.name.strip()
            teacher.subject    = payload.subject
            teacher.class_name = payload.class_name
            teacher.phone      = payload.phone
            teacher.employee_id = payload.employee_id
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    @app.delete("/app/api/school/teachers/{teacher_id}")
    def web_delete_school_teacher(
        teacher_id: int,
        session: dict = Depends(require_web_auth),
    ):
        from models import SchoolTeacher
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            teacher = db.query(SchoolTeacher).filter(
                SchoolTeacher.id == teacher_id,
                SchoolTeacher.owner_phone == owner_phone,
            ).first()
            if not teacher:
                raise HTTPException(status_code=404, detail="Teacher not found.")
            from audit import audit
            audit(db, action="DELETE_TEACHER", actor_id=session["user_id"],
                  actor_phone=session["phone"], resource=f"teacher:{teacher_id}:{teacher.name}")
            db.delete(teacher)
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    # ── Partners & Investors ──────────────────────────────────────────────────

    class PartnerInviteRequest(BaseModel):
        partner_phone: str = Field(max_length=20)
        role: str = Field(default="partner", max_length=20)
        equity_percent: Optional[float] = None
        investment_amount: Optional[int] = None
        notes: Optional[str] = Field(default=None, max_length=1000)

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
            # Businesses I am a partner in (active + pending so they can accept)
            my_roles = db.query(BusinessPartner).filter(
                BusinessPartner.partner_phone == owner.phone,
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
            if partner_phone == owner.phone:
                raise HTTPException(status_code=400, detail="You cannot invite yourself.")

            role = payload.role if payload.role in ROLE_ACCESS else "partner"
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
                BusinessPartner.partner_phone == me.phone,
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
                BusinessPartner.partner_phone == me.phone,
                BusinessPartner.status == "pending",
            ).first()
            if not bp:
                raise HTTPException(status_code=404, detail="Invitation not found or already actioned.")
            db.delete(bp)
            db.commit()
            return {"ok": True, "status": "declined"}
        finally:
            db.close()

    # ── Business notes ────────────────────────────────────────────────────────

    class CreateNoteRequest(BaseModel):
        body: str = Field(max_length=2000)
        category: str = Field(default="memo", max_length=30)
        amount: Optional[int] = None
        visibility: str = Field(default="owner_only", max_length=30)
        owner_phone: Optional[str] = Field(default=None, max_length=20)

    @app.get("/app/api/notes")
    def web_notes(
        category: Optional[str] = Query(default=None),
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            from models import BusinessNote
            owner = db.query(User).filter(User.phone == session["phone"]).first()
            if not owner:
                return {"notes": []}
            owner_phone = owner.phone if owner.parent_id is None else (
                db.query(User).filter(User.id == owner.parent_id).first() or owner
            ).phone
            is_staff = owner.parent_id is not None
            query = db.query(BusinessNote).filter(BusinessNote.owner_phone == owner_phone)
            if is_staff:
                query = query.filter(BusinessNote.visibility == "all")
            if category:
                query = query.filter(BusinessNote.category == category)
            notes = query.order_by(BusinessNote.created_at.desc()).limit(100).all()
            return {
                "notes": [
                    {
                        "id": n.id,
                        "body": n.body,
                        "category": n.category,
                        "amount": n.amount,
                        "visibility": n.visibility,
                        "created_at": _iso(n.created_at),
                    }
                    for n in notes
                ]
            }
        finally:
            db.close()

    @app.post("/app/api/notes")
    def web_create_note(payload: CreateNoteRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            from models import BusinessNote
            from partner_commands import _utcnow
            owner = db.query(User).filter(User.phone == session["phone"]).first()
            if not owner:
                raise HTTPException(status_code=403, detail="Not authenticated.")
            owner_phone = _session_owner_phone(db, session)
            now = _utcnow()
            note = BusinessNote(
                owner_phone=owner_phone,
                body=payload.body.strip(),
                category=payload.category,
                amount=payload.amount,
                visibility=payload.visibility,
                created_by_id=owner.id,
                created_at=now,
                updated_at=now,
            )
            db.add(note)
            db.commit()
            db.refresh(note)
            return {"ok": True, "id": note.id}
        finally:
            db.close()

    @app.delete("/app/api/notes/{note_id}")
    def web_delete_note(note_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            from models import BusinessNote
            owner = db.query(User).filter(User.phone == session["phone"]).first()
            owner_phone = owner.phone if owner.parent_id is None else (
                db.query(User).filter(User.id == owner.parent_id).first() or owner
            ).phone
            note = db.query(BusinessNote).filter(
                BusinessNote.id == note_id,
                BusinessNote.owner_phone == owner_phone,
            ).first()
            if not note:
                raise HTTPException(status_code=404, detail="Note not found.")
            from audit import audit
            audit(db, action="DELETE_NOTE", actor_id=session["user_id"],
                  actor_phone=session["phone"], resource=f"note:{note_id}")
            db.delete(note)
            db.commit()
            return {"ok": True}
        finally:
            db.close()

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
            if tx.matched_customer_id:
                from models import Customer as _Customer
                c = db.query(_Customer).filter(_Customer.id == tx.matched_customer_id).first()
                if c:
                    match_note = f"\nMatched to {c.name.title()} and recorded as payment."

            send_whatsapp_message(
                wallet.owner_phone,
                f"💰 Payment received: ₦{amount:,}\n"
                f"From: {sender or 'Unknown'} ({s_bank})\n"
                f"Ref: {ref}{match_note}\n\n"
                "Open CreditVoice Wallet to review."
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
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            period_key = period.upper() if period else None
            base = get_owner_transaction_query(db, owner_phone, period_key)

            # Group thrift filter: customer-linked with thrift/ajo/esusu/contribution keywords
            group_filter = _sa.and_(
                Transaction.customer_id != None,
                _sa.or_(
                    Transaction.product.ilike("%thrift%"),
                    Transaction.product.ilike("%ajo%"),
                    Transaction.product.ilike("%esusu%"),
                    Transaction.product.ilike("%contribut%"),
                    Transaction.type.ilike("%thrift%"),
                ),
            )
            # Personal savings filter: no customer OR product = personal_savings
            personal_filter = _sa.or_(
                Transaction.product.ilike("%personal_saving%"),
                Transaction.product.ilike("%personal saving%"),
                _sa.and_(
                    Transaction.customer_id == None,
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
            cust_ids  = [r.customer_id for r in group_rows if r.customer_id]
            customers = {}
            if cust_ids:
                customers = {c.id: c for c in db.query(Customer).filter(Customer.id.in_(cust_ids)).all()}

            def _tx(tx, name):
                return {
                    "id": tx.id,
                    "customer_id": tx.customer_id,
                    "customer_name": name,
                    "amount": _money(tx.amount),
                    "product": tx.product,
                    "created_at": _iso(tx.created_at),
                }

            group_tx_list = [
                _tx(tx, customers[tx.customer_id].name if customers.get(tx.customer_id) else "Unknown")
                for tx in group_rows
            ]
            personal_tx_list = [_tx(tx, "Me") for tx in personal_rows]

            # Participant totals (group)
            totals: dict = defaultdict(lambda: {"name": "Unknown", "count": 0, "total": 0})
            for tx in group_rows:
                key = tx.customer_id
                totals[key]["name"] = customers[tx.customer_id].name if customers.get(tx.customer_id) else "Unknown"
                totals[key]["count"] += 1
                totals[key]["total"] += tx.amount or 0
            participants = sorted(
                [{"id": k, **v} for k, v in totals.items()],
                key=lambda p: p["total"], reverse=True,
            )

            group_total    = sum(tx.amount or 0 for tx in group_rows)
            personal_total = sum(tx.amount or 0 for tx in personal_rows)
            return {
                "group": {
                    "transactions": group_tx_list,
                    "participants": participants,
                    "total": _money(group_total),
                    "count": len(group_rows),
                },
                "personal": {
                    "transactions": personal_tx_list,
                    "total": _money(personal_total),
                    "count": len(personal_rows),
                },
            }
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

    # ── Notifications ─────────────────────────────────────────────────────────
    @app.get("/app/api/notifications")
    def web_get_notifications(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401)
            owner_phone = _session_owner_phone(db, session)
            rows = (
                db.query(AppNotification)
                .filter(AppNotification.owner_phone == owner_phone)
                .order_by(AppNotification.created_at.desc())
                .limit(50)
                .all()
            )
            return {"notifications": [
                {
                    "id": r.id, "event_type": r.event_type,
                    "title": r.title, "body": r.body,
                    "is_read": bool(r.is_read),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]}
        finally:
            db.close()

    @app.post("/app/api/notifications/{notif_id}/read")
    def web_mark_notification_read(notif_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401)
            owner_phone = _session_owner_phone(db, session)
            notif = db.query(AppNotification).filter(
                AppNotification.id == notif_id,
                AppNotification.owner_phone == owner_phone,
            ).first()
            if notif:
                notif.is_read = 1
                db.commit()
            return {"ok": True}
        finally:
            db.close()

    @app.post("/app/api/notifications/read-all")
    def web_mark_all_notifications_read(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401)
            owner_phone = _session_owner_phone(db, session)
            db.query(AppNotification).filter(
                AppNotification.owner_phone == owner_phone,
                AppNotification.is_read == 0,
            ).update({"is_read": 1})
            db.commit()
            return {"ok": True}
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
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["id", "phone", "text", "resolved_by", "llm_reply", "created_at"])
            for r in rows:
                writer.writerow([
                    r.id, r.phone, r.text, r.resolved_by or "",
                    r.llm_reply or "",
                    r.created_at.isoformat() if r.created_at else "",
                ])
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
            w.writerow(["Code", "Plan", "Duration (days)", "Batch", "Expires"])
            for c in codes:
                w.writerow([c, plan, payload.duration_days, payload.batch_label or "", expires_at or ""])
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
            tc = db.query(TokenCode).filter(TokenCode.code == payload.code.strip().upper()).first()
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

    # ── Root-level dist files (favicon, logo, icons, etc.) ──────────────────
    # These live in web/dist/ root but NOT under /app/assets/, so they would
    # otherwise fall through to the SPA catch-all and get served as HTML.
    _DIST_ROOT_STATIC = ["favicon.png", "favicon.svg", "logo.png", "icons.svg", "offline.html"]
    for _sf in _DIST_ROOT_STATIC:
        _fp = DIST_ROOT / _sf
        if _fp.exists():
            def _make_static_route(file_path):
                def _route():
                    return FileResponse(file_path)
                return _route
            app.add_api_route(f"/app/{_sf}", _make_static_route(_fp), methods=["GET"])

    # ── SPA catch-all (MUST be last — catches all /app/* client-side routes) ──
    @app.get("/app/{full_path:path}", response_class=HTMLResponse)
    def web_app_spa(full_path: str):
        return _read_index()
