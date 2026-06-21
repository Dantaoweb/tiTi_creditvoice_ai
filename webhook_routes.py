import hashlib
import hmac
import logging
import os

from fastapi import BackgroundTasks, Request, HTTPException

from webhook_message_flow import handle_webhook_body

_APP_SECRET = os.getenv("META_APP_SECRET", "")
_log = logging.getLogger("creditvoice.webhook")


def _verify_whatsapp_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """Verify Meta's X-Hub-Signature-256 header.

    Fails closed: rejects all requests when META_APP_SECRET is not set in
    production. Only permits unverified requests in development mode so that
    local testing without a real Meta app still works.
    """
    if not _APP_SECRET:
        if os.getenv("ENVIRONMENT", "production") == "development":
            return True  # dev mode — secret not configured
        _log.critical(
            "META_APP_SECRET not set — rejecting all WhatsApp webhook requests. "
            "Set this env var in the Render dashboard."
        )
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        _APP_SECRET.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def register_webhook_routes(app):
    @app.post("/webhook")
    async def webhook(req: Request, background_tasks: BackgroundTasks):
        raw_body = await req.body()

        signature = req.headers.get("X-Hub-Signature-256")
        if not _verify_whatsapp_signature(raw_body, signature):
            raise HTTPException(status_code=403, detail="Invalid webhook signature.")

        try:
            import json
            body = json.loads(raw_body)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body.")

        # Return 200 to WhatsApp immediately — they require a fast ack.
        background_tasks.add_task(handle_webhook_body, body)
        return {"status": "ok"}
