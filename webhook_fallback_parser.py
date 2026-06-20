import re
from dataclasses import dataclass
from datetime import datetime, timezone

from constants import ACTION_AWAITING_CLARIFICATION
from faq import detect_faq, get_faq_answer
from llm_fallback import ask_llm_fallback
from messages import build_invalid_message
from models import FailedParse, PendingAction
from parser import interpret_text_with_openai, parse_message
from whatsapp_client import send_whatsapp_message


PLEASANTRIES = ["thanks", "thank you", "ok", "okay", "done", "bye", "good", "nice", "??"]

_GREETINGS = re.compile(
    r"^(?:hi|hello|hey|good\s+(?:morning|afternoon|evening|day)|howdy)"
    r"(?:\s+titi|\s+there|\s+everyone|\s+all)?[!.,]?\s*$",
    re.I,
)

# Keywords that are clearly off-topic — checked before hitting the LLM
_OFFTOPIC_PATTERNS = re.compile(
    r"\b("
    r"football|soccer|premier league|champions league|laliga|bundesliga|naija football|super eagles|"
    r"ballon d.or|world cup|fa cup|afcon|match today|who won|score|goal|fixture|"
    r"politics|president|governor|election|senate|aso rock|buhari|tinubu|peter obi|atiku|"
    r"weather|forecast|temperature|rain today|sun today|"
    r"movie|nollywood|netflix|series|episode|actor|actress|"
    r"music|song|artist|album|wizkid|burna|davido|afrobeats|"
    r"joke|funny|laugh|meme|"
    r"relationship|girlfriend|boyfriend|marriage|wedding|love|heartbreak|"
    r"celebrity|gossip|"
    r"who is the president|capital of|population of|history of"
    r")\b",
    re.I,
)

_OFFTOPIC_REPLY = (
    "I'm tiTi — your business assistant! 😊\n\n"
    "I can only help with things related to your business:\n"
    "• Record a sale or payment\n"
    "• Check who owes you\n"
    "• View your stock or inventory\n"
    "• Get a summary or report\n\n"
    "Send *menu* to see everything I can do."
)


@dataclass
class FallbackParseResult:
    response: dict | None = None
    parsed: dict | None = None
    text: str | None = None
    is_command: bool = False


def _save_clarification_pending(db, phone, original_text, clarification_question):
    db.query(PendingAction).filter(PendingAction.phone == phone).delete()
    db.add(PendingAction(
        phone=phone,
        customer_name="",
        last_customer="",
        action=ACTION_AWAITING_CLARIFICATION,
        source_text=original_text,
        product=clarification_question,
    ))
    db.commit()


def handle_fallback_parse(db, phone, text, parsed, user):
    if parsed:
        return FallbackParseResult(parsed=parsed, text=text, is_command=parsed["type"] != "TRANSACTION")

    if text.lower().strip() in PLEASANTRIES or len(text) < 2:
        return FallbackParseResult(response={"status": "ignored_pleasantry"})

    if _GREETINGS.match(text.strip()):
        send_whatsapp_message(phone, "Hi! Send MENU to see your options.")
        return FallbackParseResult(response={"status": "greeting"})

    faq_key = detect_faq(text)
    if faq_key:
        send_whatsapp_message(phone, get_faq_answer(faq_key))
        return FallbackParseResult(response={"status": f"faq_{faq_key}"})

    # Off-topic deflection — no LLM cost, instant response
    if _OFFTOPIC_PATTERNS.search(text):
        send_whatsapp_message(phone, _OFFTOPIC_REPLY)
        return FallbackParseResult(response={"status": "offtopic_deflected"})

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
                _save_clarification_pending(db, phone, text, clarification)
                send_whatsapp_message(phone, clarification)
                return FallbackParseResult(response={"status": "openai_parser_clarification"})

        elif clarification:
            _save_clarification_pending(db, phone, text, clarification)
            send_whatsapp_message(phone, clarification)
            return FallbackParseResult(response={"status": "openai_parser_clarification"})

    # ── LLM conversational fallback ──────────────────────────────────────────
    llm_reply = ask_llm_fallback(text, user=user)
    if llm_reply:
        # Log the failed parse with its LLM reply for later analysis
        try:
            owner_phone = getattr(user, "phone", None) if user else None
            db.add(FailedParse(
                phone=phone,
                owner_phone=owner_phone,
                text=text,
                resolved_by="llm",
                llm_reply=llm_reply,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ))
            db.commit()
        except Exception:
            pass
        send_whatsapp_message(phone, llm_reply)
        return FallbackParseResult(response={"status": "llm_fallback"})

    # ── Log unresolved messages for improvement analysis ─────────────────────
    try:
        owner_phone = getattr(user, "phone", None) if user else None
        db.add(FailedParse(
            phone=phone,
            owner_phone=owner_phone,
            text=text,
            resolved_by=None,
            llm_reply=None,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ))
        db.commit()
    except Exception:
        pass

    send_whatsapp_message(phone, build_invalid_message(user))
    return FallbackParseResult(response={"status": "invalid"})
