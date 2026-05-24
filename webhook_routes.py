from fastapi import Request

from webhook_message_flow import handle_webhook_body


def register_webhook_routes(app):
    @app.post("/webhook")
    async def webhook(req: Request):
        print("Webhook received", flush=True)
        try:
            print("Webhook content-type:", req.headers.get("content-type"), flush=True)
        except Exception:
            pass

        body = await req.json()
        return handle_webhook_body(body)
