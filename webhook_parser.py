from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class IncomingWebhookMessage:
    body: dict[str, Any]
    value: dict[str, Any]
    message: Optional[dict[str, Any]]
    phone: Optional[str]
    text: str
    message_type: str
    message_id: Optional[str]

    @property
    def has_message(self) -> bool:
        return bool(self.message and self.phone and self.message_id)


def extract_webhook_value(body: dict[str, Any]) -> dict[str, Any]:
    return body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})


def parse_incoming_webhook_message(body: dict[str, Any]) -> IncomingWebhookMessage:
    value = extract_webhook_value(body)
    messages = value.get("messages") or []
    message = messages[0] if messages else None

    if not message:
        return IncomingWebhookMessage(
            body=body,
            value=value,
            message=None,
            phone=None,
            text="",
            message_type="text",
            message_id=None,
        )

    message_type = message.get("type", "text")
    text = (message.get("text") or {}).get("body", "").strip()

    return IncomingWebhookMessage(
        body=body,
        value=value,
        message=message,
        phone=message.get("from"),
        text=text,
        message_type=message_type,
        message_id=message.get("id"),
    )


def get_media_evidence_ref(message: dict[str, Any], message_type: str) -> Optional[str]:
    payload = message.get(message_type) or {}
    return payload.get("id") or message.get("id")
