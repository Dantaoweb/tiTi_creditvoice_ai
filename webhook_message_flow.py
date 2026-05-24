from admin_commands import notify_subscription_admins
from database import SessionLocal
from models import PendingAction
from parser import parse_message
from subscription_flow import handle_subscription_media_receipt
from subscriptions import get_business_subscription
from webhook_admin_handlers import (
    filter_unregistered_admin_command,
    handle_app_admin_dashboard_pending,
)
from webhook_context import load_webhook_user_context, visibility_recorded_by_id
from webhook_command_router import handle_parsed_command
from webhook_delegate_invitation import handle_delegate_invitation
from webhook_early_handlers import handle_early_webhook_message
from webhook_fallback_parser import handle_fallback_parse
from webhook_home_handler import handle_home_menu_request
from webhook_idempotency import record_processed_message
from webhook_parser import get_media_evidence_ref, parse_incoming_webhook_message
from webhook_pending_router import handle_pending_actions
from webhook_voice_handler import handle_voice_message
from whatsapp_client import send_whatsapp_message


def handle_webhook_body(body):
    print("Webhook body keys:", list(body.keys()), flush=True)
    incoming = parse_incoming_webhook_message(body)
    early_result = handle_early_webhook_message(incoming)
    if early_result:
        return early_result

    if not incoming.has_message:
        print("Webhook ignored before reply", flush=True)
        return {"status": "ignored"}

    message = incoming.message
    phone = incoming.phone
    message_type = incoming.message_type
    text = incoming.text
    message_id = incoming.message_id

    db = SessionLocal()

    try:
        duplicate_result = record_processed_message(db, message_id)
        if duplicate_result:
            return duplicate_result

        user_context = load_webhook_user_context(db, phone, message_type)
        user = user_context.user
        business_owner_phone = user_context.business_owner_phone
        business_name = user_context.business_name

        if user_context.is_unregistered_voice:
            send_whatsapp_message(
                phone,
                "Welcome to CreditVoice. Please register your business with a text message first, then you can use voice notes."
            )
            return {"status": "unregistered_voice"}

        voice_transcript_text = None

        # Parse early so unregistered app/subscription admins can use admin commands.
        parsed = parse_message(text) if message_type == "text" else None
        is_command = parsed and parsed["type"] != "TRANSACTION"
        parsed, is_command = filter_unregistered_admin_command(
            db,
            phone,
            user,
            parsed,
            is_command,
        )

        delegate_invitation_result = handle_delegate_invitation(
            db,
            phone,
            text,
            user,
            business_owner_phone,
            business_name,
        )
        if delegate_invitation_result:
            return delegate_invitation_result

        voice_result = handle_voice_message(db, phone, message, message_type, user)
        if voice_result.response:
            return voice_result.response
        if voice_result.text is not None:
            text = voice_result.text
        if voice_result.message_type is not None:
            message_type = voice_result.message_type
        voice_transcript_text = voice_result.voice_transcript_text

        # Parse message early to check if it's an explicit command
        if parsed is None:
            parsed = parse_message(text)
            is_command = parsed and parsed["type"] != "TRANSACTION"
        visible_recorded_by_id = visibility_recorded_by_id(user)
        subscription = get_business_subscription(db, user)

        home_result = handle_home_menu_request(
            db,
            phone,
            text,
            user,
            subscription,
            business_name,
        )
        if home_result:
            return home_result

        pending = db.query(PendingAction).filter(
            PendingAction.phone == phone,
            PendingAction.action != None
        ).order_by(
            PendingAction.created_at.desc()
        ).first()

        if not user and message_type == "text":
            app_admin_dashboard_result = handle_app_admin_dashboard_pending(
                db,
                phone,
                text,
                pending,
                require_app_admin=True,
            )
            if app_admin_dashboard_result:
                return app_admin_dashboard_result

        if message_type != "text":
            subscription_media_result = handle_subscription_media_receipt(
                db,
                phone,
                pending,
                user,
                message,
                message_type,
                get_media_evidence_ref,
                send_whatsapp_message,
                notify_subscription_admins
            )
            if subscription_media_result:
                return subscription_media_result

            return {"status": "ignored_non_text"}
        pending_result = handle_pending_actions(
            db,
            phone,
            text,
            pending,
            user,
            subscription,
            business_name,
            business_owner_phone,
            visible_recorded_by_id,
            message_id,
            parsed,
            is_command,
        )
        if isinstance(pending_result, dict):
            return pending_result
        if pending_result.response:
            return pending_result.response
        parsed = pending_result.parsed
        is_command = pending_result.is_command
        fallback_result = handle_fallback_parse(phone, text, parsed, user)
        if fallback_result.response:
            return fallback_result.response
        parsed = fallback_result.parsed
        text = fallback_result.text
        is_command = fallback_result.is_command
        command_result = handle_parsed_command(
            db,
            phone,
            text,
            parsed,
            pending,
            user,
            subscription,
            business_name,
            business_owner_phone,
            visible_recorded_by_id,
            voice_transcript_text,
        )
        if command_result:
            return command_result
    finally:
        db.close()








