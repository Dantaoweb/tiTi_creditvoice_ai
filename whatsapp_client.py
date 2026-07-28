import os
import threading

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


if load_dotenv:
    load_dotenv()


WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

# Thread-local collector for web chat — set by web_collect_start()
_web_ctx = threading.local()


def web_collect_start():
    """Start intercepting send_whatsapp_message calls for the current thread."""
    _web_ctx.messages = []
    return _web_ctx.messages


def web_collect_stop():
    """Stop intercepting and clear the collector."""
    _web_ctx.messages = None


def send_whatsapp_message(to, message):
    # Web chat interception: capture instead of sending to WhatsApp
    _msgs = getattr(_web_ctx, "messages", None)
    if _msgs is not None:
        _msgs.append(message)
        return True

    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print(
            "WhatsApp send skipped: WHATSAPP_TOKEN or PHONE_NUMBER_ID is missing",
            flush=True,
        )
        return None

    url = (
        f"https://graph.facebook.com/v18.0/"
        f"{PHONE_NUMBER_ID}/messages"
    )
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": message
        },
    }
    try:
        response = requests.post(
            url,
            headers=headers,
            json=data,
            timeout=15,
        )
    except requests.RequestException as exc:
        print("WhatsApp send failed:", repr(exc), flush=True)
        return False

    print("WhatsApp:", response.status_code, response.text, flush=True)
    return response.ok


def send_whatsapp_template(to, template_name, language="en", components=None):
    """Send a pre-approved WhatsApp *template* message.

    Unlike send_whatsapp_message (free-form, only allowed inside the 24-hour
    customer-service window), an approved template can be delivered to a customer
    who has never messaged the business — the only compliant way to send cold
    reminders. Register utility templates in Meta Business Manager first, then
    pass the approved template_name and its variable `components`, e.g.:
        components=[{"type": "body", "parameters": [
            {"type": "text", "text": "Ada"}, {"type": "text", "text": "5,000"}]}]
    """
    _msgs = getattr(_web_ctx, "messages", None)
    if _msgs is not None:
        _msgs.append(f"[template:{template_name}]")
        return True
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("WhatsApp template skipped: token/phone id missing", flush=True)
        return None
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    template = {"name": template_name, "language": {"code": language}}
    if components:
        template["components"] = components
    data = {"messaging_product": "whatsapp", "to": to, "type": "template", "template": template}
    try:
        response = requests.post(url, headers=headers, json=data, timeout=15)
    except requests.RequestException as exc:
        print("WhatsApp template send failed:", repr(exc), flush=True)
        return False
    print("WhatsApp template:", response.status_code, response.text, flush=True)
    return response.ok
