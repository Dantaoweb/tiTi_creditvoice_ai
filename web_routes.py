from pathlib import Path
from typing import Optional
import base64
import json
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from database import SessionLocal
from models import (
    Customer, FastCaptureSettings, InventoryItem, InventoryMovement, PendingAction,
    ReminderQueue, Supplier, SupplierPayment, SupplierPurchase,
    Transaction, TransactionItem, User, utcnow,
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
from web_auth import get_otp_channels, require_web_auth, web_login, web_register, request_web_otp, verify_otp_and_set_pin
from web_pos import get_pos_receipt, save_pos_sale
from webhook_context import load_webhook_user_context, visibility_recorded_by_id


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
    phone: str
    pin: str

class RegisterRequest(BaseModel):
    name: str
    phone: str
    pin: str
    email: Optional[str] = None
    newsletter_consent: bool = False
    business_category: Optional[str] = None
    business_type: Optional[str] = None
    business_type_label: Optional[str] = None

class OtpRequest(BaseModel):
    phone: str
    channel: str = "auto"  # "email", "whatsapp", or "auto"

class SetPinRequest(BaseModel):
    phone: str
    otp: str
    new_pin: str


class DemoChatRequest(BaseModel):
    text: str

class ChatSendRequest(BaseModel):
    text: str

class StaffInviteRequest(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None

class StaffAcceptRequest(BaseModel):
    phone: str
    code: str

class FastModeToggleRequest(BaseModel):
    enabled: bool
    start_hour: Optional[int] = None
    end_hour: Optional[int] = None

class CapturePreviewRequest(BaseModel):
    phone: str
    text: str


class CaptureConfirmRequest(BaseModel):
    phone: str


class CaptureVoiceRequest(BaseModel):
    phone: str
    audio_base64: str
    mime_type: Optional[str] = "audio/webm"


class PosCartItem(BaseModel):
    inventory_item_id: Optional[int] = None
    name: str
    qty: int = 1
    unit: Optional[str] = None
    unit_price: int = 0


class PosSaveRequest(BaseModel):
    owner_phone: str
    customer_id: Optional[int] = None
    items: list[PosCartItem]
    payment_amount: int = 0


class AddInventoryRequest(BaseModel):
    owner_phone: str
    name: str
    unit: Optional[str] = None
    quantity: int = 0
    cost_price: Optional[int] = None
    selling_price: Optional[int] = None
    low_stock_alert: Optional[int] = None


class EditInventoryRequest(BaseModel):
    name: Optional[str] = None
    unit: Optional[str] = None
    cost_price: Optional[int] = None
    selling_price: Optional[int] = None
    low_stock_alert: Optional[int] = None
    is_available: Optional[bool] = None


class AdjustStockRequest(BaseModel):
    qty_delta: int
    note: Optional[str] = None


class AddCustomerRequest(BaseModel):
    owner_phone: str
    name: str
    phone: Optional[str] = None


class RecordPaymentRequest(BaseModel):
    amount: int
    note: Optional[str] = None


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


def _owner_filter(query, model, owner_phone):
    if owner_phone:
        return query.filter(model.owner_phone == owner_phone)
    return query


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
        return (
            "I didn't catch that 🤔\n\n"
            "Try something like:\n"
            "• Sold 5 bags of rice to Emeka for ₦10,000\n"
            "• Emeka paid ₦2,000\n"
            "• Bought 10 cartons of malt from supplier for ₦15,000"
        )

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

def register_web_routes(app):
    # ── Static assets from React build ──────────────────────────────────
    if (DIST_ROOT / "assets").exists():
        app.mount("/app/assets", StaticFiles(directory=DIST_ROOT / "assets"), name="dist_assets")
    elif (WEB_ROOT / "static").exists():
        app.mount("/web/static", StaticFiles(directory=WEB_ROOT / "static"), name="web_static")

    # ── SPA root (exact) ─────────────────────────────────────────────────
    @app.get("/app", response_class=HTMLResponse)
    def web_app_root():
        return _read_index()

    # ── Auth ─────────────────────────────────────────────────────────────
    @app.post("/app/api/auth/login")
    def web_auth_login(payload: LoginRequest):
        db = SessionLocal()
        try:
            return web_login(db, payload.phone.strip(), payload.pin.strip())
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
    def web_auth_register(payload: RegisterRequest):
        db = SessionLocal()
        try:
            return web_register(
                db,
                payload.name.strip(),
                payload.phone.strip(),
                payload.pin.strip(),
                email=payload.email,
                newsletter_consent=payload.newsletter_consent,
                business_category=payload.business_category,
                business_type=payload.business_type,
                business_type_label=payload.business_type_label,
            )
        finally:
            db.close()

    @app.get("/app/api/auth/config")
    def web_auth_config():
        import os
        titi_number = os.getenv("TITI_WHATSAPP", "").strip()
        return {"titi_whatsapp": titi_number}

    @app.get("/app/api/auth/otp-channels")
    def web_otp_channels(phone: str = Query(...)):
        db = SessionLocal()
        try:
            return get_otp_channels(db, phone.strip())
        finally:
            db.close()

    @app.post("/app/api/auth/request-otp")
    def web_request_otp(payload: OtpRequest):
        db = SessionLocal()
        try:
            return request_web_otp(db, payload.phone.strip(), payload.channel)
        finally:
            db.close()

    @app.post("/app/api/auth/set-pin")
    def web_set_pin(payload: SetPinRequest):
        db = SessionLocal()
        try:
            return verify_otp_and_set_pin(db, payload.phone.strip(), payload.otp.strip(), payload.new_pin.strip())
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
            return {
                "id": user.id,
                "name": user.name,
                "phone": user.phone,
                "email": user.email,
                "role": user.role,
                "plan": user.subscription_plan,
                "business_category": user.business_category,
                "whatsapp_linked": bool(user.whatsapp_linked),
                "newsletter_consent": bool(user.newsletter_consent),
            }
        finally:
            db.close()

    # ── Dashboard ────────────────────────────────────────────────────────
    @app.get("/app/api/dashboard")
    def web_dashboard(
        owner_phone: Optional[str] = Query(default=None),
        period: Optional[str] = Query(default="TODAY"),
    ):
        db = SessionLocal()
        try:
            period_key = period.upper() if period else None
            summary = get_dashboard_summary(db, owner_phone, period_key)
            debtors, _ = get_unpaid_debtors(db, owner_phone)
            low_stock_count = 0
            if owner_phone:
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
    def web_chat_demo(payload: DemoChatRequest):
        """Parse a message for the public demo — no auth, no database write."""
        parsed = parse_message(payload.text.strip()) if payload.text.strip() else None
        return {"reply": _format_demo_reply(parsed)}

    @app.post("/app/api/chat/send")
    def web_chat_send(payload: ChatSendRequest, session: dict = Depends(require_web_auth)):
        """Route a web chat message through the full conversation flow."""
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
    def web_capture_preview(payload: CapturePreviewRequest):
        db = SessionLocal()
        try:
            return _preview_capture(db, payload.phone.strip(), payload.text.strip())
        finally:
            db.close()

    @app.post("/app/api/capture/voice")
    def web_capture_voice(payload: CaptureVoiceRequest):
        db = SessionLocal()
        try:
            phone = payload.phone.strip()
            if not phone or not payload.audio_base64:
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
    def web_capture_confirm(payload: CaptureConfirmRequest):
        db = SessionLocal()
        try:
            phone = payload.phone.strip()
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
        owner_phone: Optional[str] = Query(default=None),
        q: Optional[str] = Query(default=None),
    ):
        db = SessionLocal()
        try:
            query = db.query(InventoryItem).filter(
                InventoryItem.is_available == True,
            )
            if owner_phone:
                query = query.filter(InventoryItem.owner_phone == owner_phone)
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
            items = [it.model_dump() for it in payload.items]
            result = save_pos_sale(
                db,
                payload.owner_phone,
                session["user_id"],
                payload.customer_id,
                items,
                payload.payment_amount,
            )
            return result
        finally:
            db.close()

    @app.get("/app/api/pos/receipt/{tx_id}")
    def web_pos_receipt(tx_id: int):
        db = SessionLocal()
        try:
            receipt = get_pos_receipt(db, tx_id)
            if not receipt:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Receipt not found.")
            return receipt
        finally:
            db.close()

    # ── Customers ────────────────────────────────────────────────────────
    @app.get("/app/api/customers")
    def web_customers(owner_phone: Optional[str] = Query(default=None)):
        db = SessionLocal()
        try:
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
            existing = db.query(Customer).filter(
                Customer.owner_phone == payload.owner_phone,
                Customer.name == payload.name.strip(),
            ).first()
            if existing:
                from fastapi import HTTPException
                raise HTTPException(status_code=409, detail="A customer with this name already exists.")
            c = Customer(
                owner_phone=payload.owner_phone,
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
    def web_customer_history(customer_id: int):
        db = SessionLocal()
        try:
            customer = db.query(Customer).filter(Customer.id == customer_id).first()
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
            customer = db.query(Customer).filter(Customer.id == customer_id).first()
            if not customer:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Customer not found.")
            tx = Transaction(
                customer_id=customer_id,
                type="PAY",
                amount=payload.amount,
                product=payload.note or "Payment",
                recorded_by_id=session["user_id"],
                message_id=f"web-pay-{uuid.uuid4()}",
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
        owner_phone: Optional[str] = Query(default=None),
        period: Optional[str] = Query(default=None),
    ):
        db = SessionLocal()
        try:
            period_key = period.upper() if period else None
            query = get_owner_transaction_query(db, owner_phone, period_key, include_voided=True)
            rows = query.order_by(Transaction.created_at.desc()).limit(200).all()
            customer_ids = [r.customer_id for r in rows if r.customer_id]
            customers = {}
            if customer_ids:
                customers = {c.id: c for c in db.query(Customer).filter(Customer.id.in_(customer_ids)).all()}
            user_ids = list({uid for r in rows for uid in [r.recorded_by_id, r.voided_by_id] if uid})
            users = {}
            if user_ids:
                users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}
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
                    }
                    for tx in rows
                ]
            }
        finally:
            db.close()

    # ── Inventory ─────────────────────────────────────────────────────────
    @app.get("/app/api/inventory")
    def web_inventory(owner_phone: Optional[str] = Query(default=None)):
        db = SessionLocal()
        try:
            query = _owner_filter(db.query(InventoryItem), InventoryItem, owner_phone)
            rows = query.order_by(InventoryItem.updated_at.desc()).limit(200).all()
            return {
                "items": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "unit": item.unit,
                        "quantity": item.quantity or 0,
                        "cost_price": _money(item.cost_price),
                        "selling_price": _money(item.selling_price),
                        "low_stock_alert": item.low_stock_alert,
                        "is_available": bool(item.is_available),
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
            item = InventoryItem(
                owner_phone=payload.owner_phone,
                name=payload.name.strip().lower(),
                unit=(payload.unit or "").strip() or None,
                quantity=payload.quantity,
                cost_price=payload.cost_price,
                selling_price=payload.selling_price,
                low_stock_alert=payload.low_stock_alert,
                is_available=True,
            )
            db.add(item)
            if payload.quantity:
                db.flush()
                db.add(InventoryMovement(
                    owner_phone=payload.owner_phone,
                    item_id=item.id,
                    movement_type="IN",
                    quantity=payload.quantity,
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

    @app.put("/app/api/inventory/{item_id}")
    def web_edit_inventory(
        item_id: int,
        payload: EditInventoryRequest,
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            item = db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
            if not item:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Item not found.")
            if payload.name is not None:
                item.name = payload.name.strip().lower()
            if payload.unit is not None:
                item.unit = payload.unit.strip() or None
            if payload.cost_price is not None:
                item.cost_price = payload.cost_price
            if payload.selling_price is not None:
                item.selling_price = payload.selling_price
            if payload.low_stock_alert is not None:
                item.low_stock_alert = payload.low_stock_alert
            if payload.is_available is not None:
                item.is_available = payload.is_available
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
            item = db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
            if not item:
                from fastapi import HTTPException
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
    def web_suppliers(owner_phone: Optional[str] = Query(default=None)):
        db = SessionLocal()
        try:
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
        owner_phone: Optional[str] = Query(default=None),
        period: Optional[str] = Query(default=None),
    ):
        db = SessionLocal()
        try:
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

    @app.post("/app/api/wallet/match")
    def web_wallet_match(
        payload: dict,
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
                payload.get("wallet_tx_id"),
                payload.get("customer_id"),
                owner_phone,
            )
            if err:
                raise HTTPException(status_code=400, detail=err)
            return {"ok": True, "transaction_id": tx.id}
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

    # ── Reminders ──────────────────────────────────────────────────────────
    @app.get("/app/api/reminders")
    def web_reminders(owner_phone: Optional[str] = Query(default=None)):
        db = SessionLocal()
        try:
            query = _owner_filter(db.query(ReminderQueue), ReminderQueue, owner_phone)
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

    # ── SPA catch-all (MUST be last — catches all /app/* client-side routes) ──
    @app.get("/app/{full_path:path}", response_class=HTMLResponse)
    def web_app_spa(full_path: str):
        return _read_index()
