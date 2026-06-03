from dataclasses import dataclass

from faq import detect_faq, get_faq_answer
from messages import build_invalid_message
from parser import interpret_text_with_openai, parse_message
from whatsapp_client import send_whatsapp_message


PLEASANTRIES = ["thanks", "thank you", "ok", "okay", "done", "bye", "good", "nice", "??"]


@dataclass
class FallbackParseResult:
    response: dict | None = None
    parsed: dict | None = None
    text: str | None = None
    is_command: bool = False


def handle_fallback_parse(phone, text, parsed, user):
    if parsed:
        return FallbackParseResult(parsed=parsed, text=text, is_command=parsed["type"] != "TRANSACTION")

    if text.lower().strip() in PLEASANTRIES or len(text) < 2:
        return FallbackParseResult(response={"status": "ignored_pleasantry"})

    faq_key = detect_faq(text)
    if faq_key:
        send_whatsapp_message(phone, get_faq_answer(faq_key))
        return FallbackParseResult(response={"status": f"faq_{faq_key}"})

    fallback = interpret_text_with_openai(text)
    if fallback:
        normalized_text = (fallback.get("normalized_text") or "").strip()
        clarification = (fallback.get("clarification_question") or "").strip()

        if fallback.get("understood") and normalized_text:
            fallback_parsed = parse_message(normalized_text)
            if fallback_parsed:
                print(f"OpenAI parser fallback normalized to: {normalized_text}", flush=True)
                return FallbackParseResult(
                    parsed=fallback_parsed,
                    text=normalized_text,
                    is_command=fallback_parsed["type"] != "TRANSACTION",
                )
            if clarification:
                send_whatsapp_message(phone, clarification)
                return FallbackParseResult(response={"status": "openai_parser_clarification"})

        elif clarification:
            send_whatsapp_message(phone, clarification)
            return FallbackParseResult(response={"status": "openai_parser_clarification"})

    send_whatsapp_message(phone, build_invalid_message(user))
    return FallbackParseResult(response={"status": "invalid"})
