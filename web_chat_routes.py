"""
Chat + Capture routes: the public demo parser, the authenticated conversational
assistant (/chat/send), and the transaction capture flow (preview / voice /
confirm) that mirrors the WhatsApp pipeline.

Split out of web_routes.py. Register with register_chat_routes(app); shared
helpers come from web_common.
"""
import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

from database import SessionLocal
from models import User, PendingAction, FastCaptureSettings
from parser import normalize_voice_transcript, parse_message, transcribe_audio_bytes
from subscriptions import get_business_subscription
from transaction_save import save_confirmed_pending_transaction
from transaction_setup import handle_transaction_setup
from webhook_context import load_webhook_user_context, visibility_recorded_by_id
from web_auth import require_web_auth
from web_common import _demo_rate_check, _ai_rate_check, _money, _iso


class DemoChatRequest(BaseModel):
    text: str = Field(max_length=500)


class ChatSendRequest(BaseModel):
    text: str = Field(max_length=2000)


class CapturePreviewRequest(BaseModel):
    phone: str = Field(max_length=20)
    text: str = Field(max_length=2000)


class CaptureConfirmRequest(BaseModel):
    phone: str = Field(max_length=20)


class CaptureVoiceRequest(BaseModel):
    phone: str = Field(max_length=20)
    audio_base64: str = Field(max_length=2_000_000)  # ~1.5 MB binary
    mime_type: Optional[str] = Field(default="audio/webm", max_length=50)


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


def register_chat_routes(app):

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
