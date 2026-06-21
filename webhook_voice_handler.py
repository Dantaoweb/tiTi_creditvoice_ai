from dataclasses import dataclass

from parser import transcribe_whatsapp_voice
from subscriptions import ensure_feature_allowed
from whatsapp_client import send_whatsapp_message


@dataclass
class VoiceHandleResult:
    response: dict | None = None
    text: str | None = None
    message_type: str | None = None
    voice_transcript_text: str | None = None


def handle_voice_message(db, phone, message, message_type, user):
    if message_type not in ["voice", "audio"]:
        return VoiceHandleResult(message_type=message_type)

    allowed, upgrade_msg = ensure_feature_allowed(db, user, "VOICE_TEXT", "Voice notes")
    if not allowed:
        send_whatsapp_message(phone, upgrade_msg)
        return VoiceHandleResult(response={"status": "voice_plan_blocked"})

    transcribed_text, transcription_error = transcribe_whatsapp_voice(message)
    if transcription_error or not transcribed_text:
        send_whatsapp_message(
            phone,
            f"I could not understand that voice note. {transcription_error or ''}".strip(),
        )
        return VoiceHandleResult(response={"status": "voice_transcription_failed"})

    _p = f"{phone[:4]}***" if phone and len(phone) > 4 else "***"
    print(f"Voice transcript received from {_p} [{len(transcribed_text)} chars]", flush=True)
    return VoiceHandleResult(
        text=transcribed_text,
        message_type="text",
        voice_transcript_text=transcribed_text,
    )
