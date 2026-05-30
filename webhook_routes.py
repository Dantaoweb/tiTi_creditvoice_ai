from fastapi import BackgroundTasks, Request

from webhook_message_flow import handle_webhook_body


def register_webhook_routes(app):
    @app.post("/webhook")
    async def webhook(req: Request, background_tasks: BackgroundTasks):
        print("Webhook received", flush=True)
        try:
            print("Webhook content-type:", req.headers.get("content-type"), flush=True)
        except Exception:
            pass

        body = await req.json()
        # Return 200 to WhatsApp immediately — they require a fast ack.
        # Processing happens after the response is sent.
        # For true queue-based async at very high scale, replace BackgroundTasks
        # with Celery + Redis or AWS SQS.
        background_tasks.add_task(handle_webhook_body, body)
        return {"status": "ok"}
