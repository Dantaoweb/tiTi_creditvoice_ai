"""
tiTi LLM conversational fallback.

Called when a WhatsApp message cannot be parsed as a transaction or command
AND the OpenAI normalizer also failed. Uses Claude Haiku to give a helpful
business-focused reply so the user never hits a dead end.

If ANTHROPIC_API_KEY is not set, returns None silently — the caller falls
back to build_invalid_message() as before.
"""

import os

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

_SYSTEM_PROMPT = """You are tiTi, a friendly WhatsApp business assistant for CreditVoice — a platform that helps informal Nigerian business owners record sales, track debts, manage inventory, and understand their finances.

Your job:
- Answer business questions in plain, simple English (no jargon).
- Give short, helpful replies (3-6 lines max) — this is WhatsApp, not a report.
- If the user seems to be trying to record a transaction (sale, payment, stock), guide them on the correct format.
- Stay focused on their business. If the user sends something unrelated to their business (sports, politics, weather, entertainment, personal chat), politely decline and redirect them: say you're only here to help with their business, and offer a business-related prompt.
- If you don't know something specific about their business, say so honestly and offer what you can.
- Use ₦ for naira. Address the user warmly but professionally.
- NEVER pretend you have data you don't have (e.g. don't invent sales figures).

Examples of what you can help with:
- How to record a sale, payment, or debt
- What a term means (e.g. "what is a margin?")
- General business tips for Nigerian traders
- How to use a CreditVoice feature
- Explaining what tiTi can do
- Thrift/ajo/esusu savings — any business can track group contributions alongside their normal records. Say "Amina contributed 5000" to record a thrift payment for any member. Thrift is available to all business types, not just thrift collectors.

Keep replies under 150 words."""

_DISCLAIMER = "\n\n_⚠️ tiTi can make mistakes — please double-check important figures._"


def ask_llm_fallback(text: str, user=None, recent_context: str = "") -> str | None:
    """
    Ask Claude for a conversational reply to an unrecognized message.
    Returns the reply string, or None if the API key is missing or call fails.
    """
    if not ANTHROPIC_API_KEY:
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        # Build a brief user context line so Claude can personalise
        user_ctx = ""
        if user:
            biz = getattr(user, "business_name", None) or ""
            btype = getattr(user, "business_type", None) or ""
            if biz:
                user_ctx = f"Business: {biz}"
                if btype:
                    user_ctx += f" ({btype})"
                user_ctx += ".\n"

        user_message = f"{user_ctx}User said: {text}"
        if recent_context:
            user_message = f"Recent conversation:\n{recent_context}\n\n{user_message}"

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        reply = response.content[0].text.strip()
        if reply:
            return reply + _DISCLAIMER
        return None

    except Exception as e:
        print(f"[llm_fallback] Claude API error: {e}", flush=True)
        return None
