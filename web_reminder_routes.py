"""
Reminder + automation routes: list reminders, send one, generate drafts, and
the reminder/bot automation settings (get + update).

Split out of web_routes.py. Register with register_reminder_routes(app);
shared helpers come from web_common.
"""
from typing import Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from database import SessionLocal
from models import User, ReminderQueue
from web_auth import require_web_auth
from web_common import _session_owner_phone, _owner_filter, _money, _iso


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


def register_reminder_routes(app):

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
