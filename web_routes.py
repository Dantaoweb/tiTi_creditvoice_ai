from pathlib import Path
from typing import Optional
import base64
import json
import uuid
from datetime import datetime, timezone

from fastapi import Depends, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from database import SessionLocal
from models import (
    Customer, InventoryItem, InventoryMovement, PendingAction, ReminderQueue,
    Supplier, SupplierPayment, SupplierPurchase,
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

    # ── Chat ─────────────────────────────────────────────────────────────
    @app.post("/app/api/chat/demo")
    def web_chat_demo(payload: DemoChatRequest):
        """Parse a message for the public demo — no auth, no database write."""
        parsed = parse_message(payload.text.strip()) if payload.text.strip() else None
        return {"reply": _format_demo_reply(parsed)}

    @app.post("/app/api/chat/send")
    def web_chat_send(payload: ChatSendRequest, session: dict = Depends(require_web_auth)):
        """One-shot: parse + auto-confirm in one step for the post-login chat."""
        db = SessionLocal()
        try:
            owner_phone = session["phone"]
            preview = _preview_capture(db, owner_phone, payload.text.strip())
            status = preview.get("status", "preview")

            if status in ("error", "unsupported", "unregistered"):
                msgs = preview.get("messages") or []
                return {
                    "reply": msgs[0] if msgs else "I didn't quite get that. Try: 'Sold 5 bags of rice to Emeka for ₦4,500'",
                    "ok": False,
                }

            context = load_webhook_user_context(db, owner_phone, "text")
            pending = db.query(PendingAction).filter(
                PendingAction.phone == owner_phone,
                PendingAction.action != None,
                PendingAction.action != "WEB_OTP",
            ).order_by(PendingAction.created_at.desc()).first()

            if not pending:
                msgs = preview.get("messages", [])
                return {"reply": msgs[0] if msgs else "Done! ✅", "ok": True}

            try:
                pending_items = json.loads(pending.items_json or "[]")
            except Exception:
                pending_items = []

            subscription = get_business_subscription(db, context.user)
            messages, send_message = _capture_messages()
            result = save_confirmed_pending_transaction(
                db, owner_phone, pending, context.user, context.business_owner_phone,
                visibility_recorded_by_id(context.user), f"web-{uuid.uuid4()}",
                pending_items, subscription, send_message,
            )
            reply = messages[0] if messages else "✅ Recorded!"
            return {"reply": reply, "ok": True}
        finally:
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
