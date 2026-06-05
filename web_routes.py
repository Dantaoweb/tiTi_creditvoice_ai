from pathlib import Path
from typing import Optional
import base64
import json
import uuid

from fastapi import Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from database import SessionLocal
from models import Customer, InventoryItem, PendingAction, ReminderQueue, Transaction, User
from parser import normalize_voice_transcript, parse_message, transcribe_audio_bytes
from reports import (
    dashboard_period_label,
    get_balance,
    get_dashboard_summary,
    get_owner_transaction_query,
    get_unpaid_debtors,
)
from subscriptions import get_business_subscription
from transaction_save import save_confirmed_pending_transaction
from transaction_setup import handle_transaction_setup
from webhook_context import load_webhook_user_context, visibility_recorded_by_id


WEB_ROOT = Path(__file__).parent / "web"


class CapturePreviewRequest(BaseModel):
    phone: str
    text: str


class CaptureConfirmRequest(BaseModel):
    phone: str


class CaptureVoiceRequest(BaseModel):
    phone: str
    audio_base64: str
    mime_type: Optional[str] = "audio/webm"


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


def register_web_routes(app):
    app.mount("/web/static", StaticFiles(directory=WEB_ROOT / "static"), name="web_static")

    @app.get("/app", response_class=HTMLResponse)
    def web_app():
        return (WEB_ROOT / "index.html").read_text(encoding="utf-8")

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
            return {
                "period": period_key,
                "period_label": dashboard_period_label(period_key),
                "owner_phone": owner_phone,
                "summary": summary,
                "top_debtors": sorted(
                    debtors,
                    key=lambda row: row["balance"],
                    reverse=True,
                )[:5],
            }
        finally:
            db.close()

    @app.post("/app/api/capture/preview")
    def web_capture_preview(payload: CapturePreviewRequest):
        db = SessionLocal()
        try:
            phone = payload.phone.strip()
            text = payload.text.strip()
            return _preview_capture(db, phone, text)
        finally:
            db.close()

    @app.post("/app/api/capture/voice")
    def web_capture_voice(payload: CaptureVoiceRequest):
        db = SessionLocal()
        try:
            phone = payload.phone.strip()
            if not phone or not payload.audio_base64:
                return {
                    "status": "error",
                    "message": "Record voice and enter the registered phone number.",
                }

            try:
                audio_bytes = base64.b64decode(payload.audio_base64)
            except ValueError:
                return {
                    "status": "error",
                    "message": "The voice recording could not be read.",
                }

            transcript, error = transcribe_audio_bytes(
                audio_bytes,
                payload.mime_type or "audio/webm",
            )
            if error:
                return {
                    "status": "transcription_failed",
                    "message": error,
                }

            normalized = normalize_voice_transcript(transcript)
            result = _preview_capture(
                db,
                phone,
                normalized,
                voice_transcript_text=normalized,
            )
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
                return {
                    "status": "unregistered",
                    "message": "This phone is not registered.",
                }

            pending = db.query(PendingAction).filter(
                PendingAction.phone == phone,
                PendingAction.action != None,
            ).order_by(PendingAction.created_at.desc()).first()
            if not pending:
                return {
                    "status": "empty",
                    "message": "No pending transaction found. Preview a transaction first.",
                }

            try:
                pending_items = json.loads(pending.items_json or "[]")
            except json.JSONDecodeError:
                pending_items = []

            subscription = get_business_subscription(db, context.user)
            messages, send_message = _capture_messages()
            result = save_confirmed_pending_transaction(
                db,
                phone,
                pending,
                context.user,
                context.business_owner_phone,
                visibility_recorded_by_id(context.user),
                f"web-{uuid.uuid4()}",
                pending_items,
                subscription,
                send_message,
            )
            return {
                "status": (result or {}).get("status", "saved"),
                "messages": messages,
            }
        finally:
            db.close()

    @app.get("/app/api/customers")
    def web_customers(owner_phone: Optional[str] = Query(default=None)):
        db = SessionLocal()
        try:
            query = _owner_filter(db.query(Customer), Customer, owner_phone)
            rows = query.order_by(Customer.created_at.desc()).limit(100).all()
            return {
                "customers": [
                    {
                        "id": customer.id,
                        "name": customer.name,
                        "phone": customer.customer_phone,
                        "owner_phone": customer.owner_phone,
                        "balance": _money(get_balance(db, customer.id)),
                        "created_at": _iso(customer.created_at),
                    }
                    for customer in rows
                ]
            }
        finally:
            db.close()

    @app.get("/app/api/transactions")
    def web_transactions(
        owner_phone: Optional[str] = Query(default=None),
        period: Optional[str] = Query(default=None),
    ):
        db = SessionLocal()
        try:
            period_key = period.upper() if period else None
            query = get_owner_transaction_query(db, owner_phone, period_key)
            rows = query.order_by(Transaction.created_at.desc()).limit(100).all()
            customer_ids = [row.customer_id for row in rows if row.customer_id]
            customers = {}
            if customer_ids:
                customers = {
                    customer.id: customer
                    for customer in db.query(Customer).filter(Customer.id.in_(customer_ids)).all()
                }
            user_ids = [row.recorded_by_id for row in rows if row.recorded_by_id]
            users = {}
            if user_ids:
                users = {
                    user.id: user
                    for user in db.query(User).filter(User.id.in_(user_ids)).all()
                }
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
                        "customer": customers.get(tx.customer_id).name if customers.get(tx.customer_id) else "Direct sale",
                        "recorded_by": users.get(tx.recorded_by_id).name if users.get(tx.recorded_by_id) else None,
                        "due_date": _iso(tx.due_date),
                        "created_at": _iso(tx.created_at),
                        "is_voided": bool(tx.is_voided),
                    }
                    for tx in rows
                ]
            }
        finally:
            db.close()

    @app.get("/app/api/inventory")
    def web_inventory(owner_phone: Optional[str] = Query(default=None)):
        db = SessionLocal()
        try:
            query = _owner_filter(db.query(InventoryItem), InventoryItem, owner_phone)
            rows = query.order_by(InventoryItem.updated_at.desc()).limit(100).all()
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

    @app.get("/app/api/reminders")
    def web_reminders(owner_phone: Optional[str] = Query(default=None)):
        db = SessionLocal()
        try:
            query = _owner_filter(db.query(ReminderQueue), ReminderQueue, owner_phone)
            rows = query.order_by(ReminderQueue.created_at.desc()).limit(100).all()
            return {
                "reminders": [
                    {
                        "id": reminder.id,
                        "customer_name": reminder.customer_name,
                        "customer_phone": reminder.customer_phone,
                        "balance": _money(reminder.balance),
                        "due_date": _iso(reminder.due_date),
                        "type": reminder.reminder_type,
                        "status": reminder.status,
                        "message_text": reminder.message_text,
                        "created_at": _iso(reminder.created_at),
                    }
                    for reminder in rows
                ]
            }
        finally:
            db.close()
