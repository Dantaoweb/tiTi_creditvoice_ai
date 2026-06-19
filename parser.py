import json
import os
import re
import requests

from datetime import datetime, timedelta, timezone

from sqlalchemy import func

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from admin import normalize_admin_role
from constants import (
    BUY_KEYWORDS,
    DUE_TODAY_PHRASES,
    DUE_TOMORROW_PHRASES,
    NAME_SPLIT_KEYWORDS,
    PAY_KEYWORDS,
    SALE_KEYWORDS,
)
from item_normalizer import UNIT_PATTERN, UNIT_PHRASES, normalize_item
from models import Customer, Transaction, TransactionItem
from plans import PLAN_BASIC

if load_dotenv:
    load_dotenv()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
OPENAI_PARSE_MODEL = os.getenv("OPENAI_PARSE_MODEL", "gpt-4o-mini")

def get_whatsapp_media_info(media_id):
    if not WHATSAPP_TOKEN or not media_id:
        return None

    response = requests.get(
        f"https://graph.facebook.com/v18.0/{media_id}",
        headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
        timeout=30
    )
    if response.status_code >= 400:
        print("WhatsApp media info error:", response.text, flush=True)
        return None
    return response.json()


def download_whatsapp_media(media_id):
    media_info = get_whatsapp_media_info(media_id)
    if not media_info or not media_info.get("url"):
        return None, None

    response = requests.get(
        media_info["url"],
        headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
        timeout=60
    )
    if response.status_code >= 400:
        print("WhatsApp media download error:", response.text, flush=True)
        return None, None

    return response.content, media_info.get("mime_type")


def extension_for_mime_type(mime_type):
    mime_type = (mime_type or "").split(";")[0].strip().lower()
    return {
        "audio/ogg": "ogg",
        "audio/opus": "ogg",
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/mp4": "mp4",
        "audio/m4a": "m4a",
        "audio/wav": "wav",
        "audio/webm": "webm",
    }.get(mime_type, "ogg")


def transcribe_audio_bytes(audio_bytes, mime_type=None):
    if not OPENAI_API_KEY:
        return None, "OPENAI_API_KEY is not set."
    if not audio_bytes:
        return None, "No audio received."

    filename = f"voice.{extension_for_mime_type(mime_type)}"
    response = requests.post(
        "https://api.openai.com/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        data={
            "model": OPENAI_TRANSCRIBE_MODEL,
            "response_format": "json",
            "prompt": (
                "This is a WhatsApp business accounting command for CreditVoice. "
                "Common words include bought, buy, paid, pay, contributed, contribution, sold, sell, supply, "
                "rice, beans, cement, sand, naira, k for thousand, m for million."
            )
        },
        files={"file": (filename, audio_bytes, mime_type or "audio/ogg")},
        timeout=90
    )
    if response.status_code >= 400:
        print("OpenAI transcription error:", response.text, flush=True)
        return None, "Voice transcription failed."

    return response.json().get("text", "").strip(), None


NUMBER_WORDS = {
    "zero": 0, "one": 1, "a": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}


def parse_number_words(words):
    total = 0
    current = 0
    used = False
    for word in words:
        if word == "and":
            continue
        if word in NUMBER_WORDS:
            current += NUMBER_WORDS[word]
            used = True
        elif word == "hundred":
            current = max(current, 1) * 100
            used = True
        elif word == "thousand":
            total += max(current, 1) * 1000
            current = 0
            used = True
        elif word == "million":
            total += max(current, 1) * 1000000
            current = 0
            used = True
        else:
            return None
    return total + current if used else None


def normalize_voice_transcript(transcript):
    text_value = transcript.lower().replace("-", " ")
    number_word_pattern = (
        r"zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
        r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
        r"nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|"
        r"ninety|hundred|thousand|million|and|a"
    )
    token_pattern = re.compile(
        rf"\b(?:(?:{number_word_pattern})\s+){{0,8}}(?:{number_word_pattern})\b"
    )

    def replace_match(match):
        phrase = match.group(0).strip()
        amount = parse_number_words(phrase.split())
        return str(amount) if amount is not None else phrase

    text_value = token_pattern.sub(replace_match, text_value)
    text_value = re.sub(r"\bnaira\b", "", text_value)
    text_value = re.sub(
        r"(\d+)\s+and\s+(?!(?:paid|pay|contributed|contribute|contribution)\b)([a-z][a-z]*(?:\s+[a-z][a-z]*){0,4}\s+\d+)",
        r"\1, \2",
        text_value
    )
    item_body_match = re.search(
        r"\b(?:bought|buy|purchased)\b(?P<body>.+?)(?=\b(?:paid|pay|settled|gave)\b|$)",
        text_value
    )
    if item_body_match and "," not in item_body_match.group("body"):
        body = re.sub(
            r"(\d{3,})\s+([a-z][a-z]*(?:\s+[a-z][a-z]*){0,3}\s+\d+)",
            r"\1, \2",
            item_body_match.group("body")
        )
        text_value = (
            text_value[:item_body_match.start("body")]
            + body
            + text_value[item_body_match.end("body"):]
        )
    text_value = re.sub(r"\s+", " ", text_value).strip()
    return text_value


def transcribe_whatsapp_voice(message):
    audio_payload = message.get("voice") or message.get("audio") or {}
    media_id = audio_payload.get("id")
    audio_bytes, mime_type = download_whatsapp_media(media_id)
    transcript, error = transcribe_audio_bytes(
        audio_bytes,
        mime_type or audio_payload.get("mime_type")
    )
    if error:
        return None, error
    return normalize_voice_transcript(transcript), None


def extract_json_object(text_value):
    if not text_value:
        return None
    text_value = text_value.strip()
    try:
        return json.loads(text_value)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text_value, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def interpret_text_with_openai(text_value):
    if not OPENAI_API_KEY:
        return None
    text_value = (text_value or "").strip()
    if not text_value or len(text_value) > 600:
        return None

    system_prompt = (
        "You help normalize Nigerian WhatsApp business accounting messages for CreditVoice. "
        "Return only strict JSON. Do not explain. Do not save anything. "
        "Convert messy wording into one supported command sentence that the local parser can understand. "
        "Supported command styles include: "
        "'Ayo bought rice 5000', 'Ayo paid 3000', 'Amina contributed 5000', "
        "'Ayo bought rice 4000, beans 3000 paid 2000', "
        "'I sold phone 45k', 'I received 1000 for doing chair', "
        "'Ayo supply me 12kg cocoa at 5000', "
        "'I paid Ayo 14000 for egg', "
        "'Ayo paid 6000 for gate and balance is 5600', "
        "'add customer Ayo', 'Ayo phone 08012345678'. "
        "IMPORTANT: When a message says '[name] buy/bought [item] and paid [amount]' with only ONE number, "
        "it means the person bought the item AND fully paid for it. "
        "Normalize as '[name] bought [item] [amount] paid [amount]' — same amount twice, balance is zero. "
        "Example: 'Bayowa buy one basket of mangoes and paid 60000' → 'Bayowa bought 1 basket mango 60000 paid 60000'. "
        "Preserve customer names, products, amounts, paid amounts, balances, units, and due dates. "
        "If the message is not a business transaction/customer setup/reminder command, set understood false. "
        "If important money details are missing or ambiguous, set understood false and provide a short clarification_question."
    )
    user_prompt = (
        "Normalize this message for the local parser.\n\n"
        f"Message: {text_value}\n\n"
        "Return JSON with exactly these keys:\n"
        "{"
        "\"understood\": true|false, "
        "\"normalized_text\": \"\", "
        "\"confidence\": \"high|medium|low\", "
        "\"clarification_question\": \"\""
        "}"
    )

    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": OPENAI_PARSE_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"}
            },
            timeout=30
        )
    except requests.RequestException as exc:
        print("OpenAI parser fallback request error:", repr(exc), flush=True)
        return None

    if response.status_code >= 400:
        print("OpenAI parser fallback error:", response.text, flush=True)
        return None

    content = (
        response.json()
        .get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    result = extract_json_object(content)
    if not isinstance(result, dict):
        return None
    return result


def interpret_text_with_openai_followup(original_message, clarification_question, user_answer):
    if not OPENAI_API_KEY:
        return None
    original_message = (original_message or "").strip()
    user_answer = (user_answer or "").strip()
    if not original_message or not user_answer or len(original_message) > 600:
        return None

    system_prompt = (
        "You help normalize Nigerian WhatsApp business accounting messages for CreditVoice. "
        "Return only strict JSON. Do not explain. Do not save anything. "
        "Convert messy wording into one supported command sentence that the local parser can understand. "
        "Supported command styles include: "
        "'Ayo bought rice 5000', 'Ayo paid 3000', 'Amina contributed 5000', "
        "'Ayo bought 3 shirts at 500, 2 trousers at 1000', "
        "'Ayo bought rice at 4000, beans at 3000 paid 2000', "
        "'I sold phone 45k', 'I received 1000 for doing chair', "
        "'Ayo supply me 12kg cocoa at 5000', "
        "'I paid Ayo 14000 for egg', "
        "'Ayo paid 6000 for gate and balance is 5600', "
        "'add customer Ayo', 'Ayo phone 08012345678', "
        "'add stock rice cost 3000 sell 4000'. "
        "CRITICAL PRICING RULE: When a user gives prices in response to 'what are the amounts?', "
        "those prices are UNIT PRICES (price per single item), NOT totals. "
        "Always use 'at [price]' format for unit prices (e.g. '3 caps at 300'). "
        "NEVER use 'for [price]' when the price is per unit — 'for' means the total for that line. "
        "NUMBERING RULE: If the original message has numbered items like '1. Native 3, 2. Jalab 1', "
        "the numbers before the dot (1., 2.) are list indices, NOT quantities. "
        "The quantities are the numbers after the product name (e.g. 'Native 3' means qty=3). "
        "FULL-PAYMENT RULE: '[name] buy/bought [item] and paid [amount]' with ONE number means "
        "fully paid — normalize as '[name] bought [item] [amount] paid [amount]' (same amount twice). "
        "Preserve customer names, products, amounts, paid amounts, balances, units, and due dates. "
        "If still ambiguous after the user's answer, set understood false."
    )
    user_prompt = (
        "I received a message I could not parse. I asked the user for clarification and they answered.\n\n"
        f"Original message: {original_message}\n"
        f"I asked: {clarification_question}\n"
        f"User answered: {user_answer}\n\n"
        "Using the user's answer, normalize the original message into a tiTi command.\n"
        "Remember: prices given by the user are UNIT PRICES — use 'at [price]' not 'for [price]'.\n"
        "Remember: numbered prefixes like '1.' are list indices, not quantities.\n\n"
        "Return JSON with exactly these keys:\n"
        "{"
        "\"understood\": true|false, "
        "\"normalized_text\": \"\", "
        "\"confidence\": \"high|medium|low\", "
        "\"clarification_question\": \"\""
        "}"
    )

    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": OPENAI_PARSE_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"}
            },
            timeout=30
        )
    except requests.RequestException as exc:
        print("OpenAI followup parser error:", repr(exc), flush=True)
        return None

    if response.status_code >= 400:
        print("OpenAI followup parser error:", response.text, flush=True)
        return None

    content = (
        response.json()
        .get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    result = extract_json_object(content)
    if not isinstance(result, dict):
        return None
    return result


def normalize_phone(phone_str):
    """Converts local Nigerian numbers to international format for Meta API."""
    if not phone_str:
        return None
    clean = re.sub(r"\D", "", phone_str)
    if clean.startswith("0") and len(clean) == 11:
        return "234" + clean[1:]
    return clean


_NUMBER_WORDS_MAP = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}

def _normalize_text_for_parsing(text):
    """Strip currency symbols, normalize price markers and number words."""
    clean = text.lower().replace(",", "").replace("#", "").replace("₦", "")
    # "at the rate of" / "at a rate of" → "at"
    clean = re.sub(r"\bat\s+(?:a\s+)?rate\s+of\b", "at", clean)
    # "at the cost of" / "at a cost of" → "for"
    clean = re.sub(r"\bat\s+(?:a\s+)?cost\s+of\b", "for", clean)
    # number words → digits (only when isolated, so "twenty bags" → "20 bags")
    clean = re.sub(
        r"\b(" + "|".join(_NUMBER_WORDS_MAP) + r")\b",
        lambda m: str(_NUMBER_WORDS_MAP[m.group(0)]),
        clean,
    )
    return clean


def extract_item_details(text):
    # Matches numbers with optional k/m suffixes (e.g., 5000, 5k, 5.5m)
    amount_pattern = r"\d[\d,\.]*\s*[kKmM]?"

    clean = _normalize_text_for_parsing(text)

    _qty_pat = r"\d[\d,\.]*(?:[kKmM](?![a-zA-Z]))?"
    match = re.search(
        r"(?P<quantity>" + _qty_pat + r")\s*"
        r"(?P<container>[a-z/]+)\s+of\s+"
        r"(?P<product>[a-z ]+?)\s+(?:(?P<price_marker>at|for)\s+)?(?P<unit_price>" + amount_pattern + r")(?:\s+each)?",
        clean
    )
    compact_unit_match = None
    if not match:
        compact_unit_match = re.search(
            r"(?P<quantity>" + _qty_pat + r")\s*"
            r"(?P<unit>kg|g|ml|l)\s+(?:of\s+)?"
            r"(?P<product>[a-z ]+?)\s+(?:(?P<price_marker>at|for)\s+)?(?P<unit_price>" + amount_pattern + r")(?:\s+each)?",
            clean
        )
    no_of_match = None
    if not match and not compact_unit_match:
        no_of_match = re.search(
            r"(?P<quantity>" + _qty_pat + r")\s*"
            r"(?P<product>[a-z/]+(?:\s+[a-z/]+){0,3})\s+"
            r"(?:(?P<price_marker>at|for)\s+)?(?P<unit_price>" + amount_pattern + r")(?:\s+each)?",
            clean
        )

    active_match = match or compact_unit_match or no_of_match
    if not active_match:
        return None

    # Parse quantity and unit price safely, supporting k/m suffixes for the price
    quantity = parse_amount_token(active_match.group("quantity")) or 0
    unit = match.group("container") if match else None
    if compact_unit_match:
        unit = compact_unit_match.group("unit")
    product = active_match.group("product").strip()
    price_marker = active_match.groupdict().get("price_marker")
    trailing_marker = re.search(r"\b(at|for)$", product)
    if trailing_marker and not price_marker:
        price_marker = trailing_marker.group(1)
        product = product[:trailing_marker.start()].strip()
    product, unit = normalize_item(product, unit)
    price = parse_amount_token(active_match.group("unit_price")) or 0
    price_info = price_total_from_marker(
        quantity,
        price,
        price_marker,
        bool(
            re.match(
                r"\s*(?:each|per\s+unit|per\s+piece)\b",
                clean[active_match.end():],
            )
        ) or "each" in active_match.group(0).lower(),
    )

    return {
        "quantity": quantity,
        "unit": unit,
        "product": product,
        "unit_price": price_info["unit_price"],
        "total": price_info["total"]
    }


def extract_direct_sale_details(text):
    clean = text.lower().replace(",", "").strip()
    clean = re.sub(r"^(?:i\s+)?(?:sold|sell|supply|supplied|deliver|delivered)\s+", "", clean).strip()
    clean = re.sub(r"\b(per\s+unit|per\s+piece)\b", "each", clean).strip()

    amount_matches = list(re.finditer(
        r"(?<![\d/])\d[\d,\.]*\s*(?:[kK](?![a-zA-Z])|[mM](?![a-zA-Z]))?(?![a-zA-Z\d/])",
        clean
    ))
    if not amount_matches:
        return None

    amount_match = amount_matches[-1]
    price = parse_amount_token(amount_match.group())
    if price is None:
        return None

    item_text = clean[:amount_match.start()].strip()
    marker_match = re.search(r"\b(for|at)\s*$", item_text)
    price_marker = marker_match.group(1) if marker_match else None
    priced_each = bool(re.match(r"\s*each\b", clean[amount_match.end():]))
    item_text = re.sub(r"\b(for|at)\s*$", "", item_text).strip()
    item_text = re.sub(r"\beach\b", "", item_text).strip()
    if not item_text:
        return None

    quantity = 1
    unit = None
    product = item_text

    quantity_match = re.match(r"(?P<quantity>\d[\d,\.]*(?:[kKmM](?![a-zA-Z]))?)\s+(?P<rest>.+)$", item_text)
    if quantity_match:
        quantity = parse_quantity_token(quantity_match.group("quantity")) or 1
        rest = quantity_match.group("rest").strip()
        rest = re.sub(r"\s+of\s+", " ", rest, count=1)

        for unit_phrase in UNIT_PHRASES:
            if rest == unit_phrase or rest.startswith(f"{unit_phrase} "):
                unit = unit_phrase
                product = rest[len(unit_phrase):].strip()
                break

        if unit is None:
            product = rest

    product = product.strip()
    product, unit = normalize_item(product, unit)
    # "5 crates at 5000" → unit="crate", product="" — the unit IS the product
    # (crate sellers use "crates" as the product name).
    if not product and unit:
        product = unit
        unit = None
    if not product:
        return None

    price_info = price_total_from_marker(quantity, price, price_marker, priced_each)
    return {
        "quantity": quantity,
        "unit": unit,
        "product": product,
        "unit_price": price_info["unit_price"],
        "total": price_info["total"]
    }


def extract_due_date_from_text(text):
    clean_text = text.lower()

    if any(phrase in clean_text for phrase in DUE_TODAY_PHRASES):
        return datetime.now(timezone.utc).replace(tzinfo=None)

    if any(phrase in clean_text for phrase in DUE_TOMORROW_PHRASES):
        return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)

    date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", clean_text)
    if not date_match:
        return None

    try:
        date_text = date_match.group(1)
        date_format = "%d/%m/%y" if len(date_text.rsplit("/", 1)[-1]) == 2 else "%d/%m/%Y"
        return datetime.strptime(date_text, date_format)
    except ValueError:
        return None


def extract_artisan_transaction(text):
    clean = text.lower().replace(",", "").strip()
    amounts = extract_amounts(clean)
    if not amounts:
        return None
    due_date = extract_due_date_from_text(clean)

    balance_match = re.search(
        r"^(?P<name>[a-zA-Z'â€™\- ]+?)\s+(?:pay|paid|pays|pay\s+me|paid\s+me|give\s+me|gave\s+me|send|sent|transfer|transferred|transfered|deposit|deposited|settle|settled|clear|cleared)\s+"
        r"(?P<paid>\d[\d,\.]*\s*(?:[kKmM](?![a-zA-Z]))?)\s+"
        r"(?:balance|bal|remaining|remain)\s+"
        r"(?P<balance>\d[\d,\.]*\s*(?:[kKmM](?![a-zA-Z]))?)",
        clean
    )
    if balance_match:
        paid_amount = parse_amount_token(balance_match.group("paid"))
        balance_amount = parse_amount_token(balance_match.group("balance"))
        if paid_amount is None or balance_amount is None:
            return None
        total_amount = paid_amount + balance_amount
        return {
            "type": "TRANSACTION",
            "name": balance_match.group("name").strip(),
            "action": "COMBINED",
            "buy_amount": total_amount,
            "paid_amount": paid_amount,
            "quantity": None,
            "unit": None,
            "product": "service/job",
            "unit_price": total_amount,
            "invoice_items": None,
            "total": total_amount,
            "due_date": due_date,
            "artisan_note": f"Paid N{paid_amount:,}, balance N{balance_amount:,}"
        }

    paid_for_balance_match = re.search(
        r"^(?P<name>[a-zA-Z'Ã¢â‚¬â„¢\- ]+?)\s+(?:pay|paid|pays|give|gave|send|sent|transfer|transferred|transfered|deposit|deposited|settle|settled|clear|cleared)\s+(?:me\s+)?"
        r"(?P<paid>\d[\d,\.]*\s*(?:[kKmM](?![a-zA-Z]))?)\s+"
        r"(?:for\s+(?P<description>.+?)\s+)?(?:and\s+)?"
        r"(?:balance|bal|remaining|remain)\s+(?:is\s+)?"
        r"(?P<balance>\d[\d,\.]*\s*(?:[kKmM](?![a-zA-Z]))?)",
        clean
    )
    if paid_for_balance_match:
        paid_amount = parse_amount_token(paid_for_balance_match.group("paid"))
        balance_amount = parse_amount_token(paid_for_balance_match.group("balance"))
        if paid_amount is None or balance_amount is None:
            return None
        total_amount = paid_amount + balance_amount
        product = (paid_for_balance_match.group("description") or "service/job").strip()
        return {
            "type": "TRANSACTION",
            "name": paid_for_balance_match.group("name").strip(),
            "action": "COMBINED",
            "buy_amount": total_amount,
            "paid_amount": paid_amount,
            "quantity": None,
            "unit": None,
            "product": product,
            "unit_price": total_amount,
            "invoice_items": None,
            "total": total_amount,
            "due_date": due_date,
            "artisan_note": f"{product.title()}: paid N{paid_amount:,}, balance N{balance_amount:,}"
        }

    service_work_paid_match = re.search(
        r"^(?P<name>[a-zA-Z'Ã¢â‚¬â„¢\- ]+?)\s+"
        r"(?:did|done|do|sewed|sew|washed|wash|printed|print|made|make|fixed|fix|repaired|repair)\s+"
        r"(?P<description>.+?)\s+"
        r"(?P<total>\d[\d,\.]*\s*(?:[kKmM](?![a-zA-Z]))?)\s+"
        r"(?:paid|pay|pays|deposit|deposited)\s+"
        r"(?P<paid>\d[\d,\.]*\s*(?:[kKmM](?![a-zA-Z]))?)$",
        clean
    )
    if service_work_paid_match:
        total_amount = parse_amount_token(service_work_paid_match.group("total"))
        paid_amount = parse_amount_token(service_work_paid_match.group("paid"))
        if total_amount is None or paid_amount is None:
            return None
        product = service_work_paid_match.group("description").strip()
        return {
            "type": "TRANSACTION",
            "name": service_work_paid_match.group("name").strip(),
            "action": "COMBINED",
            "buy_amount": total_amount,
            "paid_amount": paid_amount,
            "quantity": None,
            "unit": None,
            "product": product,
            "unit_price": total_amount,
            "invoice_items": None,
            "total": total_amount,
            "due_date": due_date,
            "artisan_note": f"{product.title()}: paid N{paid_amount:,}, balance N{max(total_amount - paid_amount, 0):,}"
        }

    i_was_paid_match = re.search(
        r"^(?:i\s+)?(?:was\s+)?paid\s+"
        r"(?P<amount>\d[\d,\.]*\s*(?:[kKmM](?![a-zA-Z]))?)\s+for\s+(?P<description>.+)$",
        clean
    )
    if i_was_paid_match:
        amount = parse_amount_token(i_was_paid_match.group("amount"))
        if amount is None:
            return None
        return {
            "type": "TRANSACTION",
            "name": "",
            "action": "SALE",
            "buy_amount": amount,
            "paid_amount": 0,
            "quantity": 1,
            "unit": None,
            "product": i_was_paid_match.group("description").strip(),
            "unit_price": amount,
            "invoice_items": None,
            "total": amount,
            "due_date": None,
            "artisan_note": "Service income, no customer debt"
        }

    receive_match = re.search(
        r"^(?:i\s+)?(?:receive|received|collect|collected)\s+"
        r"(?P<amount>\d[\d,\.]*\s*(?:[kKmM](?![a-zA-Z]))?)"
        r"(?:\s+from\s+(?P<name>.+?))?"
        r"(?:\s+for\s+(?P<description>.+))?$",
        clean
    )
    if receive_match:
        amount = parse_amount_token(receive_match.group("amount"))
        if amount is None:
            return None
        description = (receive_match.group("description") or "service/work").strip()
        customer_name = (receive_match.group("name") or "").strip()
        product = description
        if customer_name:
            product = f"{description} - {customer_name}"
        return {
            "type": "TRANSACTION",
            "name": "",
            "action": "SALE",
            "buy_amount": amount,
            "paid_amount": 0,
            "quantity": 1,
            "unit": None,
            "product": product,
            "unit_price": amount,
            "invoice_items": None,
            "total": amount,
            "due_date": None,
            "artisan_note": "Service income, no customer debt"
        }

    paid_me_for_match = re.search(
        r"^(?P<name>[a-zA-Z'â€™\- ]+?)\s+(?:pay|paid|pays|give|gave|send|sent|transfer|transferred|transfered|deposit|deposited|settle|settled|clear|cleared)\s+(?:me\s+)?"
        r"(?P<amount>\d[\d,\.]*\s*(?:[kKmM](?![a-zA-Z]))?)\s+for\s+(?P<description>.+)$",
        clean
    )
    if paid_me_for_match:
        amount = parse_amount_token(paid_me_for_match.group("amount"))
        if amount is None:
            return None
        payer_name = paid_me_for_match.group("name").strip()
        description = paid_me_for_match.group("description").strip()
        product = description
        if payer_name not in ["customer", "client"]:
            product = f"{description} - {payer_name}"
        return {
            "type": "TRANSACTION",
            "name": "",
            "action": "SALE",
            "buy_amount": amount,
            "paid_amount": 0,
            "quantity": 1,
            "unit": None,
            "product": product,
            "unit_price": amount,
            "invoice_items": None,
            "total": amount,
            "due_date": None,
            "artisan_note": "Service income, no customer debt"
        }

    walk_in_match = re.search(
        r"^(?:walk[\-\s]in|cash\s+patient)\s+"
        r"(?:(?P<description>[a-zA-Z][a-zA-Z\s/\-]+?)\s+)?"
        r"(?P<amount>\d[\d,\.]*\s*(?:[kKmM](?![a-zA-Z]))?)(?:\s+naira)?$",
        clean
    )
    if walk_in_match:
        amount = parse_amount_token(walk_in_match.group("amount"))
        if amount is not None:
            description = (walk_in_match.group("description") or "").strip()
            product = description if description else "walk-in patient"
            return {
                "type": "TRANSACTION",
                "name": "",
                "action": "SALE",
                "buy_amount": amount,
                "paid_amount": 0,
                "quantity": 1,
                "unit": None,
                "product": product,
                "unit_price": amount,
                "invoice_items": None,
                "total": amount,
                "due_date": None,
                "artisan_note": "Walk-in / cash patient, no customer debt"
            }

    ambiguous_match = re.search(
        r"^(?P<name>[a-zA-Z'â€™\- ]+?)\s+(?:pay|paid|pays)\s+me\s+"
        r"(?P<amount>\d[\d,\.]*\s*(?:[kKmM](?![a-zA-Z]))?)$",
        clean
    )
    if ambiguous_match:
        amount = parse_amount_token(ambiguous_match.group("amount"))
        if amount is None:
            return None
        return {
            "type": "ARTISAN_PAYMENT_CHOICE",
            "name": ambiguous_match.group("name").strip(),
            "amount": amount,
            "description": "service/work"
        }

    return None


def parse_invoice_item(item_text):
    clean = item_text.lower().replace(",", "").replace("#", "").replace("₦", "").strip()
    clean = re.sub(r"\b(per\s+unit|per\s+piece)\b", "each", clean).strip()

    amount_matches = list(re.finditer(
        r"(?<![\d/])\d[\d,\.]*\s*(?:[kK](?![a-zA-Z])|[mM](?![a-zA-Z]))?(?![a-zA-Z\d/])",
        clean
    ))
    if not amount_matches:
        return None

    amount_match = amount_matches[-1]
    price = parse_amount_token(amount_match.group())
    if price is None:
        return None

    item_body = clean[:amount_match.start()].strip()
    marker_match = re.search(r"\b(for|at)\s*$", item_body)
    price_marker = marker_match.group(1) if marker_match else None
    priced_each = bool(re.match(r"\s*each\b", clean[amount_match.end():]))
    item_body = re.sub(r"\b(for|at)\s*$", "", item_body).strip()
    item_body = re.sub(r"\beach\b", "", item_body).strip()
    if not item_body:
        return None

    quantity = 1
    unit = None
    product = item_body

    quantity_match = re.match(r"(?P<quantity>\d[\d,\.]*(?:[kKmM](?![a-zA-Z]))?)\s+(?P<rest>.+)$", item_body)
    if quantity_match:
        quantity = parse_quantity_token(quantity_match.group("quantity")) or 1
        rest = re.sub(r"\s+of\s+", " ", quantity_match.group("rest").strip(), count=1)

        for unit_phrase in UNIT_PHRASES:
            if rest == unit_phrase or rest.startswith(f"{unit_phrase} "):
                unit = unit_phrase
                product = rest[len(unit_phrase):].strip()
                break

        if unit is None:
            product = rest

    product = product.strip()
    product, unit = normalize_item(product, unit)
    if not product and unit:
        product = unit
        unit = None
    if not product:
        return None

    price_info = price_total_from_marker(quantity, price, price_marker, priced_each)
    return {
        "product": product,
        "quantity": quantity,
        "unit": unit,
        "unit_price": price_info["unit_price"],
        "total": price_info["total"]
    }


def parse_invoice_items(items_text):
    parts = [
        part.strip()
        for part in re.split(r"\s*,\s*|\s*;\s*", items_text)
        if part.strip()
    ]
    if len(parts) < 2:
        return None

    items = []
    for part in parts:
        item = parse_invoice_item(part)
        if not item:
            return None
        items.append(item)

    return {
        "items": items,
        "total": sum(item["total"] for item in items)
    }


def format_invoice_items(items):
    lines = []
    for index, item in enumerate(items, start=1):
        if item.get("unit"):
            label = f"{item['quantity']} {item['unit']} of {item['product']}"
        elif item.get("quantity", 1) > 1:
            label = f"{item['quantity']} {item['product']}"
        else:
            label = item["product"]
        lines.append(
            f"{index}. {label.title()} - N{item['total']:,}"
        )
    return "\n".join(lines)


def add_transaction_items(db, transaction_id, items):
    for item in items or []:
        db.add(
            TransactionItem(
                transaction_id=transaction_id,
                product=item["product"],
                quantity=item.get("quantity") or 1,
                unit=item.get("unit"),
                unit_price=item.get("unit_price") or 0,
                total=item.get("total") or 0
            )
        )


def parse_amount_token(token):
    token = token.lower().replace(",", "").strip()
    if token.endswith("k"):
        multiplier = 1000
        token = token[:-1]
    elif token.endswith("m"):
        multiplier = 1000000
        token = token[:-1]
    else:
        multiplier = 1

    token = token.replace(" ", "")
    if token == "":
        return None

    try:
        if "." in token:
            return int(float(token) * multiplier)
        return int(token) * multiplier
    except ValueError:
        return None


def parse_quantity_token(token):
    """Like parse_amount_token but for quantities — handles 5m, 1.5k, 5,000,000."""
    if not token:
        return None
    token = str(token).lower().replace(",", "").strip()
    if token.endswith("k") and not token[:-1].isalpha():
        multiplier = 1000
        token = token[:-1]
    elif token.endswith("m") and not token[:-1].isalpha():
        multiplier = 1000000
        token = token[:-1]
    else:
        multiplier = 1
    try:
        if "." in token:
            return int(float(token) * multiplier)
        return int(token) * multiplier
    except ValueError:
        return None


def extract_amounts(text):
    # Improved regex to identify amounts with k/m suffixes.
    # Uses negative lookahead to ensure k/m aren't part of a larger unit word (like kg, ml, etc.)
    # or immediately followed by other letters that suggest a unit context (like meter).
    unit_pattern = r"kg|g|gram|grams|bag|bags|carton|cartons|unit|units|pcs|piece|pieces|litre|litres|liter|liters|l|ml|ton|tons"
    amount_text = re.sub(rf"\b\d+\s*(?:{unit_pattern})\b", "", text, flags=re.IGNORECASE)
    # Normalize naira prefix "N500" → "500" so we can use letter-boundary lookbehind safely
    amount_text = re.sub(r"\b[Nn](\d[\d,]*(?:\s*[kKmM](?![a-zA-Z]))?)\b", r"\1", amount_text)
    # Strip alphanumeric product codes like "a4", "b2" that are not standalone amounts
    amount_text = re.sub(r"\b(?![Nn]\d)[A-Za-z]+\d+\b", "", amount_text)
    matches = re.findall(
        r"(?<![a-zA-Z\d/])\d[\d,\.]*\s*(?:[kK](?![a-zA-Z])|[mM](?![a-zA-Z]))?(?![a-zA-Z\d/])",
        amount_text
    )
    amounts = []
    for match in matches:
        parsed = parse_amount_token(match)
        if parsed is not None:
            amounts.append(parsed)
    return amounts


def parse_stock_item_body(body):
    clean = re.sub(r"\b(each|per\s+unit|per\s+piece)\b", "", body.lower()).strip()
    clean = re.sub(r"\s+", " ", clean)

    # Strip dangling "cost N" / "sell N" / "selling price N" that got bundled with the product name
    # e.g. "fish cost 120000" → "fish", "garri cost 500 sell 700" → "garri" (handled upstream, but guard here)
    _amount_tok = r"\d[\d,\.]*(?:[kKmM](?![a-zA-Z]))?"
    clean = re.sub(
        rf"\s+(?:cost|selling\s+price|sell(?:ing)?)\s+(?:at\s+)?{_amount_tok}(?:\s+(?:each|per\s+unit))?",
        "",
        clean,
        flags=re.I,
    ).strip()

    # ── Fraction prefix: "half bag rice", "quarter crate eggs", "1/8 bag flour" ──
    _FRAC_PAT = r"(?P<frac>half|quarter|three[\s\-]?quarters?|1/8|3/4|eighth)"
    _frac_m = re.match(
        rf"^{_FRAC_PAT}\s+(?P<unit>\w+)\s+(?P<product>.+)$",
        clean, re.I,
    )
    if _frac_m:
        frac_word = re.sub(r"\s+", " ", _frac_m.group("frac").lower().strip())
        frac_unit = _frac_m.group("unit").lower()
        frac_product = _frac_m.group("product").strip()
        frac_product, frac_unit_n = normalize_item(frac_product, frac_unit)
        # Store the combined unit so deduction logic can strip the fraction prefix
        combined_unit = f"{frac_word} {frac_unit_n or frac_unit}"
        return {
            "quantity": 1,
            "unit": combined_unit,
            "product": frac_product,
        }

    quantity_match = re.match(
        rf"(?P<quantity>\d[\d,\.]*(?:[kKmM](?![a-zA-Z]))?)\s*(?P<unit>{UNIT_PATTERN})?\s*(?:of\s+)?(?P<product>.*)$",
        clean
    )
    if quantity_match:
        quantity = parse_quantity_token(quantity_match.group("quantity")) or 1
        unit = quantity_match.group("unit")
        product = quantity_match.group("product").strip()
        if not product:
            product = unit or "stock item"
            unit = None
        product, unit = normalize_item(product, unit)
        return {
            "quantity": quantity,
            "unit": unit,
            "product": product
        }

    product, unit = normalize_item(clean)
    return {
        "quantity": 1,
        "unit": unit,
        "product": product
    }


def extract_bulk_stock_conversion(text, product, bulk_quantity, total_cost):
    conversion_match = re.search(
        rf"\b(?:split\s+into|convert(?:ed)?\s+to|contains?|has|makes?)\s+"
        rf"(?P<quantity>\d+)\s*(?P<unit>{UNIT_PATTERN})?\b",
        text.lower()
    )
    if not conversion_match:
        return None

    retail_quantity_per_bulk = int(conversion_match.group("quantity"))
    retail_unit = conversion_match.group("unit") or "each"
    _, retail_unit = normalize_item(product, retail_unit)
    retail_quantity = (bulk_quantity or 1) * retail_quantity_per_bulk
    if retail_quantity <= 0:
        return None
    retail_unit_price = round((total_cost or 0) / retail_quantity)
    return {
        "product": product,
        "quantity": retail_quantity,
        "unit": retail_unit,
        "unit_price": retail_unit_price,
        "total": total_cost,
        "conversion_quantity_per_bulk": retail_quantity_per_bulk,
    }


def extract_supplier_transaction(text):
    clean = text.lower().replace(",", "").strip()
    if not extract_amounts(clean):
        return None

    amount_pattern = r"\d[\d,\.]*\s*(?:[kKmM](?![a-zA-Z]))?"
    due_date = extract_due_date_from_text(clean)

    supplier_payment_patterns = [
        re.search(
            rf"^i\s+(?:have\s+)?(?:paid|pay|sent|send|transfer(?:red|ed)?|deposit(?:ed)?)\s+"
            rf"(?P<amount>{amount_pattern})\s+to\s+(?P<supplier>[a-zA-Z'Ã¢â‚¬â„¢\- ]+?)"
            rf"(?:\s+for\s+(?P<product>.+?))?$",
            clean
        ),
        re.search(
            rf"^i\s+(?:have\s+)?(?:paid|pay)\s+(?P<amount>{amount_pattern})\s+for\s+"
            rf"(?P<product>.+?)\s+(?P<supplier>[a-zA-Z'Ã¢â‚¬â„¢\- ]+?)\s+"
            rf"(?:supply|supplied|deliver|delivered)$",
            clean
        ),
        re.search(
            rf"^i\s+(?:have\s+)?(?:paid|pay|sent|send|transfer(?:red|ed)?|deposit(?:ed)?)\s+"
            rf"(?P<supplier>[a-zA-Z'Ã¢â‚¬â„¢\- ]+?)\s+(?P<amount>{amount_pattern})"
            rf"(?:\s+for\s+(?P<product>.+?))?$",
            clean
        )
    ]
    for payment_match in supplier_payment_patterns:
        if not payment_match:
            continue
        amount = parse_amount_token(payment_match.group("amount"))
        if amount is None:
            return None
        supplier = payment_match.group("supplier").strip()
        product = (payment_match.groupdict().get("product") or "").strip()
        product = re.sub(r"\b(?:supply|supplied|deliver|delivered)$", "", product).strip() or None
        return {
            "type": "SUPPLIER_TRANSACTION",
            "action": "SUPPLIER_PAYMENT",
            "name": supplier,
            "product": product,
            "paid_amount": amount,
            "buy_amount": 0,
            "quantity": None,
            "unit": None,
            "unit_price": None,
            "total": 0,
            "due_date": None
        }

    purchase_patterns = [
        re.search(
            rf"^i\s+(?:buy|bought|purchase|purchased)\s+(?P<body>.+?)\s+from\s+"
            rf"(?P<supplier>[a-zA-Z'Ã¢â‚¬â„¢\- ]+?)\s+"
            rf"(?:split\s+into|convert(?:ed)?\s+to|contains?|has|makes?)\s+"
            rf"\d+\s*(?:{UNIT_PATTERN})?\s+(?P<price_marker>at|for)\s+"
            rf"(?P<price>{amount_pattern})(?:\s+each)?",
            clean
        ),
        re.search(
            rf"^(?P<supplier>[a-zA-Z'Ã¢â‚¬â„¢\- ]+?)\s+(?:supply|supplied|deliver|delivered)\s+me\s+"
            rf"(?P<body>.+?)\s+"
            rf"(?:split\s+into|convert(?:ed)?\s+to|contains?|has|makes?)\s+"
            rf"\d+\s*(?:{UNIT_PATTERN})?\s+(?P<price_marker>at|for)\s+"
            rf"(?P<price>{amount_pattern})(?:\s+each)?",
            clean
        ),
        re.search(
            rf"^i\s+(?:buy|bought|purchase|purchased)\s+(?P<body>.+?)\s+from\s+"
            rf"(?P<supplier>[a-zA-Z'Ã¢â‚¬â„¢\- ]+?)\s+(?P<price_marker>at|for)\s+"
            rf"(?P<price>{amount_pattern})(?:\s+each)?",
            clean
        ),
        re.search(
            rf"^(?P<supplier>[a-zA-Z'Ã¢â‚¬â„¢\- ]+?)\s+(?:supply|supplied|deliver|delivered)\s+me\s+"
            rf"(?P<body>.+?)\s+(?P<price_marker>at|for)\s+(?P<price>{amount_pattern})(?:\s+each)?",
            clean
        ),
        # "Emeka supply one pack paracetamol at 500" — no "me" required
        re.search(
            rf"^(?P<supplier>[a-zA-Z'Ã¢â‚¬â„¢\- ]+?)\s+(?:supply|supplied|deliver|delivered)\s+"
            rf"(?P<body>.+?)\s+(?P<price_marker>at|for)\s+(?P<price>{amount_pattern})(?:\s+each)?",
            clean
        ),
    ]
    for purchase_match in purchase_patterns:
        if not purchase_match:
            continue
        price = parse_amount_token(purchase_match.group("price"))
        if price is None:
            return None
        body = re.sub(
            rf"\b(?:split\s+into|convert(?:ed)?\s+to|contains?|has|makes?)\s+"
            rf"\d+\s*(?:{UNIT_PATTERN})?\b.*$",
            "",
            purchase_match.group("body").strip()
        ).strip()
        item = parse_stock_item_body(body)
        quantity = item["quantity"]
        price_info = price_total_from_marker(
            quantity,
            price,
            purchase_match.groupdict().get("price_marker"),
            "each" in purchase_match.group(0).lower(),
        )
        unit_price = price_info["unit_price"]
        total = price_info["total"]
        stock_item = extract_bulk_stock_conversion(clean, item["product"], quantity, total)
        paid_amount = 0
        paid_match = re.search(
            rf"\b(?:paid|pay|sent|send|transfer(?:red|ed)?|deposit(?:ed)?)\s+(?P<paid>{amount_pattern})",
            clean
        )
        if paid_match:
            paid_amount = parse_amount_token(paid_match.group("paid")) or 0
        selling_price = None
        sell_match = re.search(
            rf"\b(?:sell(?:ing)?(?:\s+price)?)\s+(?P<sell>{amount_pattern})",
            clean, re.I
        )
        if sell_match:
            selling_price = parse_amount_token(sell_match.group("sell"))
        # "with 15 sachets" → retail breakdown hint
        with_match = re.search(
            r"\bwith\s+(?P<per>\d+)\s+(?P<ret_unit>[a-z]+)\b",
            clean, re.I
        )
        retail_unit = with_match.group("ret_unit") if with_match else None
        retail_per_base = int(with_match.group("per")) if with_match else None
        return {
            "type": "SUPPLIER_TRANSACTION",
            "action": "SUPPLIER_PURCHASE",
            "name": purchase_match.group("supplier").strip(),
            "product": item["product"],
            "quantity": quantity,
            "unit": item["unit"],
            "unit_price": unit_price,
            "buy_amount": total,
            "paid_amount": paid_amount,
            "total": total,
            "stock_item": stock_item,
            "due_date": due_date,
            "selling_price": selling_price,
            "retail_unit": retail_unit,
            "retail_per_base": retail_per_base,
            "retail_price": None,
        }

    # ── Stock purchase with no named supplier ───────────────────────────────
    # "I buy 10 bags rice at 5000 each" — defaults to "Cash Purchase" supplier
    no_supplier_match = re.search(
        rf"^i\s+(?:buy|bought|purchase|purchased)\s+(?P<body>.+?)\s+(?P<price_marker>at|for)\s+"
        rf"(?P<price>{amount_pattern})(?:\s+each)?$",
        clean,
    )
    if no_supplier_match:
        price = parse_amount_token(no_supplier_match.group("price"))
        body = no_supplier_match.group("body").strip()
        if price is not None and body:
            item = parse_stock_item_body(body)
            price_info = price_total_from_marker(
                item["quantity"],
                price,
                no_supplier_match.group("price_marker"),
                "each" in no_supplier_match.group(0).lower(),
            )
            paid_match = re.search(
                rf"\b(?:paid|pay)\s+(?P<paid>{amount_pattern})", clean
            )
            paid_amount = parse_amount_token(paid_match.group("paid")) if paid_match else price_info["total"]
            sell_match = re.search(
                rf"\bselling\s+price\s+(?P<sell>{amount_pattern})", clean, re.I
            )
            selling_price = parse_amount_token(sell_match.group("sell")) if sell_match else None
            return {
                "type": "SUPPLIER_TRANSACTION",
                "action": "SUPPLIER_PURCHASE",
                "name": "cash purchase",
                "product": item["product"],
                "quantity": item["quantity"],
                "unit": item["unit"],
                "unit_price": price_info["unit_price"],
                "buy_amount": price_info["total"],
                "paid_amount": paid_amount,
                "total": price_info["total"],
                "stock_item": None,
                "due_date": due_date,
                "selling_price": selling_price,
            }

    return None


def build_reminder_text(reminder):
    due_date_text = reminder.due_date.strftime("%d/%m/%Y")

    if reminder.reminder_type == "DUE_TODAY":
        return (
            f"Hello {reminder.customer_name.title()},\n\n"
            f"This is a reminder that your outstanding balance of "
            f"₦{reminder.balance:,} is due today.\n\n"
            f"Thank you."
        )

    return (
        f"Hello {reminder.customer_name.title()},\n\n"
        f"This is a reminder that your outstanding balance of "
        f"₦{reminder.balance:,} will be due on {due_date_text}.\n\n"
        f"Thank you."
    )


def parse_period_phrase(text):
    text = text.lower()
    if "today" in text:
        return "TODAY"
    if "this week" in text or "week" in text:
        return "WEEK"
    if "this month" in text or "month" in text:
        return "MONTH"
    if "this year" in text or "year" in text:
        return "YEAR"
    return None


def parse_date_phrase(text):
    match = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", text)
    return match.group(1) if match else None


def parse_slash_date(text):
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", text)
    if not match:
        return None

    day, month, year = map(int, match.groups())
    if year < 100:
        year += 2000
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def price_total_from_marker(quantity, price, marker=None, priced_each=False):
    quantity = quantity or 1
    marker = (marker or "").lower()
    if marker == "for" and not priced_each:
        return {
            "unit_price": round(price / quantity) if quantity else price,
            "total": price,
        }
    return {
        "unit_price": price,
        "total": quantity * price,
    }


def get_customer_period_range(period, target_date=None):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today = datetime(now.year, now.month, now.day)

    if period == "TODAY":
        return today, today + timedelta(days=1), "Today"

    if period == "WEEK":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=7), "This Week"

    if period == "MONTH":
        start = datetime(today.year, today.month, 1)
        if today.month == 12:
            end = datetime(today.year + 1, 1, 1)
        else:
            end = datetime(today.year, today.month + 1, 1)
        return start, end, "This Month"

    if period == "YEAR":
        start = datetime(today.year, 1, 1)
        return start, datetime(today.year + 1, 1, 1), "This Year"

    if period == "DATE" and target_date:
        start = datetime(target_date.year, target_date.month, target_date.day)
        return start, start + timedelta(days=1), start.strftime("%d/%m/%Y")

    return None, None, "All Time"


def parse_customer_account_request(text):
    clean = text.lower().strip()
    if clean.startswith("customer summary") or clean.startswith("customer balance summary"):
        return None
    transaction_terms = [
        "bought", "buy", "paid", "pay", "collect", "collected",
        "receive", "received", "sold", "sell", "supply", "supplied"
    ]
    if any(re.search(rf"\b{term}\b", clean) for term in transaction_terms):
        return None

    for keyword in [" account", " balance", " summary"]:
        if keyword in clean:
            name, _, tail = clean.partition(keyword)
            name = name.strip()
            tail = tail.strip()
            if not name:
                return None
            if name in ["outstanding", "total outstanding", "total", "customer"]:
                return None

            target_date = parse_slash_date(tail)
            if target_date:
                return {
                    "name": name,
                    "period": "DATE",
                    "target_date": target_date
                }

            return {
                "name": name,
                "period": parse_period_phrase(tail),
                "target_date": None
            }

    return None


def find_customer_by_name(db, owner_phone, name):
    return db.query(Customer).filter(
        Customer.owner_phone == owner_phone,
        func.lower(Customer.name) == name.lower()
    ).first()


def build_customer_account_summary(db, owner_phone, customer_name, period=None, target_date=None, include_menu=False, recorded_by_id=None):
    customer = find_customer_by_name(db, owner_phone, customer_name)
    if not customer:
        return f"Customer not found: {customer_name.title()}"

    start, end, period_label = get_customer_period_range(period, target_date)

    tx_query = db.query(Transaction).filter(
        Transaction.customer_id == customer.id
    )
    if recorded_by_id:
        tx_query = tx_query.filter(Transaction.recorded_by_id == recorded_by_id)
    if start and end:
        tx_query = tx_query.filter(
            Transaction.created_at >= start,
            Transaction.created_at < end
        )

    total_buy = tx_query.filter(Transaction.type == "BUY").with_entities(
        func.coalesce(func.sum(Transaction.amount), 0)
    ).scalar()
    total_paid = tx_query.filter(Transaction.type == "PAY").with_entities(
        func.coalesce(func.sum(Transaction.amount), 0)
    ).scalar()

    balance = total_buy - total_paid
    tx_count = tx_query.count()
    if recorded_by_id and tx_count == 0:
        return f"Customer not found: {customer_name.title()}"

    if balance < 0:
        balance_line = f"Credit: ₦{abs(balance):,}"
    else:
        balance_line = f"Balance: ₦{balance:,}"

    phone_line = f"Phone: {customer.customer_phone or 'no phone'}\n"

    msg = (
        f"{customer.name.title()} Account Summary\n"
        f"{phone_line}"
        f"Period: {period_label}\n\n"
        f"Bought: ₦{total_buy:,}\n"
        f"Paid: ₦{total_paid:,}\n"
        f"{balance_line}\n"
        f"Transactions: {tx_count}"
    )

    recent_transactions = tx_query.order_by(
        Transaction.created_at.desc()
    ).limit(5).all()

    if recent_transactions:
        msg += "\n\nRecent Transactions\n"
        for tx in recent_transactions:
            tx_date = tx.created_at.strftime("%d/%m/%Y")
            item_line = ""
            if tx.type == "BUY" and tx.product:
                if tx.quantity and tx.unit:
                    item_line = f" - {tx.quantity} {tx.unit} of {tx.product}"
                elif tx.quantity and tx.quantity > 1:
                    item_line = f" - {tx.quantity} {tx.product}"
                else:
                    item_line = f" - {tx.product}"
            msg += f"{tx_date} - {tx.type}{item_line}: ₦{tx.amount:,}\n"

    if include_menu:
        msg += (
            "\nSend:\n"
            "1. Today\n"
            "2. This week\n"
            "3. This month\n"
            "4. This year\n"
            "5. All time\n"
            "6. By date\n\n"
            "Send exit, back, done, or cancel to close this view."
        )

    return msg.strip()


def extract_customer_onboarding(text):
    clean = text.lower().strip()

    # Reject transaction-like text unless there is an explicit onboarding cue.
    transaction_terms = ["bought", "buy", "paid", "pay", "due", "balance", "sale", "sales"]
    if any(term in clean for term in transaction_terms):
        if not re.search(r"\b(add|save|contact|customer|phone|number|shop|store)\b", clean):
            return None

    phone_match = re.search(r"(\+?\d[\d ]{7,14}\d)", clean)
    if not phone_match:
        if not re.search(r"^(?:add|save)\s+customer\s+", clean):
            return None
        name = re.sub(
            r"^(?:add|save)\s+customer\s+",
            "",
            clean
        ).strip()
        name = re.sub(r"\b(please|pls)\b", "", name).strip()
        if not name or len(name) < 2:
            return None
        return {
            "name": name,
            "customer_phone": None
        }

    phone = normalize_phone(phone_match.group(1))
    if len(re.sub(r"\D", "", phone)) < 7:
        return None

    before = clean[:phone_match.start()].strip()
    if not before:
        return None

    before = re.sub(
        r"\b(add|save|customer|contact|mobile|phone|number|my|as|to|for|please|pls|shop|store)\b",
        "",
        before
    ).strip()

    name_parts = [word for word in before.split() if word]
    if not name_parts:
        return None

    name = " ".join(name_parts)
    return {
        "name": name,
        "customer_phone": phone
    }


# =========================
# 🧠 PARSER
# =========================

def parse_message(text):

    clean_text = text.lower().strip()
    if clean_text in SELECT_PRODUCT_COMMANDS:
        return {"type": "SELECT_PRODUCT"}

    if clean_text in ["formats", "format", "f"]:
        return {"type": "FORMATS"}

    if clean_text in ["stock", "stocks", "my stock", "my stocks", "inventory", "my inventory"] or \
            re.match(r"^(?:show|check|view|see|display)\s+(?:my\s+)?(?:stocks?|inventory)$", clean_text):
        return {"type": "INVENTORY_LIST"}

    if re.match(r"^(?:i\s+am\s+adding|i\s+want\s+to\s+add|i\s+would\s+like\s+to\s+add|adding|want\s+to\s+add)\s+stock$", clean_text):
        return {"type": "STOCK_ADD", "body": ""}

    if clean_text in [
        "suppliers", "supplier", "supplier list", "list supplier",
        "list suppliers", "my suppliers", "my supplier",
        "supplier debts", "suppliers i owe",
    ] or re.match(r"^(?:show|check|view|see|list)\s+(?:my\s+)?suppliers?$", clean_text):
        return {"type": "SUPPLIER_LIST"}

    if clean_text in ["supplier due", "suppliers due", "supplier due today", "suppliers due today"]:
        return {"type": "SUPPLIER_DUE"}

    if clean_text in [
        "supplier due this week", "suppliers due this week",
        "supplier due week", "upcoming supplier payments",
        "supplier upcoming", "upcoming suppliers",
    ]:
        return {"type": "SUPPLIER_DUE_WEEK"}

    if clean_text.startswith("stock "):
        _stock_body = clean_text[6:].strip()
        # "stock detergent 60 bags cost 100000 selling price 120000" → add stock
        _has_cost = bool(re.search(r"\bcost\b\s*\d", _stock_body, re.I))
        _has_sell = bool(re.search(r"\b(?:selling\s+price|sell)\b\s*\d", _stock_body, re.I))
        if _has_cost and _has_sell:
            if re.search(r"\bselling\s+price\b", _stock_body, re.I):
                _full_item = _parse_stock_item_full(_stock_body)
                if _full_item:
                    return {"type": "STOCK_ADD_WITH_PRICES", "items": [_full_item]}
            _priced_items = _parse_stock_items_with_prices(_stock_body)
            if _priced_items:
                return {"type": "STOCK_ADD_WITH_PRICES", "items": _priced_items}
        return {
            "type": "INVENTORY_ITEM",
            "product": _stock_body,
        }

    # ── Add stock (new format with cost + sell prices) ──────────────────────
    # "add stock rice cost 3000 sell 4000"
    # "add stock rice cost 3000 sell 4000, beans cost 2000 sell 2500"
    # Body is optional — bare "add stock" shows the guide
    stock_add_match = (
        re.match(r"^(?:add\s+stock|stock\s+add)(?:\s+(?P<body>.+))?$", clean_text, re.DOTALL)
        or re.match(r"^add\s+(?P<body>.+?)\s+to\s+stock$", clean_text, re.DOTALL)
    )
    if stock_add_match:
        body = (stock_add_match.group("body") or "").strip()
        # Detect "product qty unit at cost, selling price sell" format
        if body and re.search(r"\bselling\s+price\b", body, re.I):
            item = _parse_stock_item_full(body)
            if item:
                return {"type": "STOCK_ADD_WITH_PRICES", "items": [item]}
        # Detect cost+sell / cost+selling price format
        if body and re.search(r"\bcost\b", body, re.I) and re.search(r"\bsell(?:ing\s+price)?\b", body, re.I):
            items = _parse_stock_items_with_prices(body)
            if items:
                return {"type": "STOCK_ADD_WITH_PRICES", "items": items}
        return {"type": "STOCK_ADD", "body": body}

    # ── Manual stock remove ─────────────────────────────────────────────────
    # "remove stock 5 bags rice"  |  "remove 5 bags rice from stock"
    stock_remove_match = (
        re.match(r"^(?:remove\s+stock|stock\s+remove)\s+(?P<body>.+)$", clean_text)
        or re.match(r"^remove\s+(?P<body>.+?)\s+from\s+stock$", clean_text)
    )
    if stock_remove_match:
        return {"type": "STOCK_REMOVE", "body": stock_remove_match.group("body").strip()}

    # ── Manual stock set (count correction) ────────────────────────────────
    # "set stock rice 50 bags"  |  "adjust stock rice 50 bags"  |  "correct stock rice 50"
    stock_set_match = re.match(
        r"^(?:set\s+stock|adjust\s+stock|correct\s+stock|stock\s+count)\s+(?P<body>.+)$",
        clean_text
    )
    if stock_set_match:
        return {"type": "STOCK_SET", "body": stock_set_match.group("body").strip()}

    # ── Low-stock alert threshold ───────────────────────────────────────────
    # "stock alert rice 10"  |  "set low stock alert rice 10"
    stock_alert_match = re.match(
        r"^(?:set\s+)?(?:low\s+)?stock\s+alert\s+(?P<product>.+?)\s+(?P<quantity>\d+)$",
        clean_text
    )
    if stock_alert_match:
        return {
            "type": "STOCK_ALERT_SET",
            "product": stock_alert_match.group("product").strip(),
            "quantity": int(stock_alert_match.group("quantity")),
        }

    # ── Product category ────────────────────────────────────────────────────
    # "set category eggs = dairy"  |  "category eggs grains"
    category_match = re.match(
        r"^(?:set\s+)?category\s+(?P<product>[a-z][a-z ]+?)\s*[=:]\s*(?P<category>[a-z][a-z ]+)$",
        clean_text,
    ) or re.match(
        r"^(?:set\s+)?category\s+(?P<product>[a-z][a-z ]+?)\s+(?P<category>[a-z][a-z]+)$",
        clean_text,
    )
    if category_match:
        return {
            "type": "SET_PRODUCT_CATEGORY",
            "product": category_match.group("product").strip(),
            "category": category_match.group("category").strip(),
        }

    # ── Reorder quantity ────────────────────────────────────────────────────
    # "reorder eggs 5 crates"  |  "set reorder eggs 5"  |  "reorder point rice 2 bags"
    _qty_reorder = r"\d[\d,\.]*(?:[kKmM](?![a-zA-Z]))?"
    reorder_match = re.match(
        rf"^(?:set\s+)?reorder(?:\s+point)?\s+(?P<product>[a-z][a-z ]+?)\s+(?P<quantity>{_qty_reorder})(?:\s+(?P<unit>[a-z]+))?$",
        clean_text,
    )
    if reorder_match:
        raw_qty = reorder_match.group("quantity").replace(",", "")
        return {
            "type": "SET_REORDER_QUANTITY",
            "product": reorder_match.group("product").strip(),
            "quantity": int(float(raw_qty)),
            "unit": reorder_match.group("unit"),
        }

    # ── Delete garbled stock item ───────────────────────────────────────────
    # "delete stock item egg cost 4700"  |  "remove item garri cost 4000 and selling price 5000"
    _del_match = re.match(
        r"^(?:delete|remove)\s+(?:stock\s+)?item\s+(?P<product>.+)$",
        clean_text,
    )
    if _del_match:
        return {"type": "DELETE_STOCK_ITEM", "product": _del_match.group("product").strip()}

    # ── Update business type ────────────────────────────────────────────────
    # "update business type"  |  "change my business type"  |  "change business"
    if re.match(r"^(?:update|change|set)\s+(?:my\s+)?business(?:\s+type)?$", clean_text):
        return {"type": "UPDATE_BUSINESS_TYPE"}

    # ── Service price list commands ─────────────────────────────────────────
    # "price list" / "my price list" / "service prices" → show/edit price list
    if clean_text in [
        "price list", "price lists", "my price list", "my price lists",
        "pricelist", "pricelists", "service prices", "service price list",
        "my services", "services", "view prices",
    ] or re.match(r"^(?:show|view|check|see|edit|update)\s+(?:my\s+)?(?:price\s*lists?|service\s+prices?)$", clean_text):
        return {"type": "PRICE_LIST"}

    # "price rice 3000 4000" / "update price garri 2500 3500" — two-number stock price (cost + sell)
    _stock_price_2 = re.match(
        r"^(?:set\s+|update\s+)?price\s+(?P<item>[a-z][a-z\s]+?)\s+(?P<cost>[Nn]?[\d,]+)\s+(?P<sell>[Nn]?[\d,]+)$",
        clean_text,
    )
    if _stock_price_2:
        _cost_str = _stock_price_2.group("cost").replace(",", "").replace("n", "").replace("N", "")
        _sell_str = _stock_price_2.group("sell").replace(",", "").replace("n", "").replace("N", "")
        if _cost_str.isdigit() and _sell_str.isdigit():
            return {
                "type": "UPDATE_STOCK_PRICE",
                "product": _stock_price_2.group("item").strip(),
                "cost": int(_cost_str),
                "sell": int(_sell_str),
            }

    # "set breakdown eggs: 30 per crate" / "breakdown rice 32 congo per bag"
    # "breakdown egg crate 30 70" (unit, base-unit, per-base, price)
    _breakdown_m = re.match(
        r"^(?:set\s+)?breakdown\s+(?P<product>[a-z][a-z\s]+?)\s*:?\s+"
        r"(?P<ret_unit>[a-z]+)\s+(?P<per>\d+)(?:\s+(?P<price>[Nn]?\d[\d,]*))?$",
        clean_text,
    )
    if _breakdown_m:
        _bd_price_raw = (_breakdown_m.group("price") or "").replace(",", "").lstrip("Nn")
        return {
            "type": "SET_RETAIL_BREAKDOWN",
            "product": _breakdown_m.group("product").strip(),
            "retail_unit": _breakdown_m.group("ret_unit").strip(),
            "retail_per_base": int(_breakdown_m.group("per")),
            "retail_price": int(_bd_price_raw) if _bd_price_raw.isdigit() else None,
        }

    # "price shirt 1000" / "set price trouser 800" / "update price curtain 1500"
    _set_svc_price = re.match(
        r"^(?:set\s+|update\s+)?price\s+(?P<item>[a-z][a-z\s]+?)\s+(?P<price>[Nn]?[\d,]+)$",
        clean_text,
    )
    if _set_svc_price:
        _price_str = _set_svc_price.group("price").replace(",", "").replace("n", "").replace("N", "")
        if _price_str.isdigit():
            return {
                "type": "SET_SERVICE_PRICE",
                "item": _set_svc_price.group("item").strip(),
                "price": int(_price_str),
            }

    # ── Service billed: business performed work for customer ─────────────────
    # "Adeola paint work at isale osun cost 12000 paid 3000"
    # "John AC repair cost 8000 paid 5000"
    # Must NOT have a BUY keyword (to avoid false-matching "bought paint cost 500")
    _svc_cost_m = re.search(
        r"^(.+?)\s+cost\s+([Nn]?[\d,]+)(?:\s+paid\s+([Nn]?[\d,]+))?\s*$",
        text.strip(),
        re.I,
    )
    if _svc_cost_m and not re.search(
        r"\b(" + "|".join(BUY_KEYWORDS) + r")\b", text, re.I
    ):
        _prefix = _svc_cost_m.group(1).strip()  # e.g. "Adeola paint work at isale osun"
        _total_raw = _svc_cost_m.group(2).replace(",", "").lstrip("Nn")
        _paid_raw = (_svc_cost_m.group(3) or "0").replace(",", "").lstrip("Nn")
        _total = int(_total_raw) if _total_raw.isdigit() else 0
        _paid = int(_paid_raw) if _paid_raw.isdigit() else 0
        if _total > 0 and _prefix:
            # Customer name: first capitalized word(s) — second word included only if also capitalized
            _pwords = _prefix.split()
            _cname_parts = [_pwords[0]]
            if len(_pwords) > 1 and _pwords[1][:1].isupper():
                _cname_parts.append(_pwords[1])
            return {
                "type": "BUY",
                "customer": " ".join(_cname_parts),
                "amount": _total,
                "paid": _paid,
            }

    # ── Service job: customer brought/dropped items ─────────────────────────
    # "John brought 10 shirts, 5 trousers"
    # "Bayo dropped car full wash"
    # "Ade came with 3 dresses, 1 suit for sewing"
    _svc_job_m = re.match(
        r"^(?P<customer>[A-Za-z][A-Za-z\s]{1,30}?)\s+"
        r"(?:brought|bring|dropped?\s*(?:off|in)?|came\s+with|carry\s+come)\s+"
        r"(?P<items>.+?)(?:\s+(?:and\s+)?paid\s+(?P<paid>[Nn]?[\d,]+))?\s*$",
        text.strip(),
        re.I,
    )
    if _svc_job_m:
        _customer = _svc_job_m.group("customer").strip()
        _items_text = _svc_job_m.group("items").strip()
        _paid_raw = _svc_job_m.group("paid") or "0"
        _paid = int(_paid_raw.replace(",", "").replace("n", "").replace("N", "") or "0")
        _raw_items = _parse_service_items(_items_text)
        if _raw_items:
            return {
                "type": "SERVICE_JOB",
                "customer": _customer,
                "raw_items": _raw_items,
                "paid": _paid,
            }

    # =========================
    # 📊 COMMANDS
    # =========================

    if clean_text.startswith("balance"):
        return {"type": "BALANCE"}

    if clean_text == "today sales":
        return {"type": "TODAY_SALES"}

    if clean_text == "weekly sales":
        return {"type": "WEEKLY_SALES"}

    if clean_text == "monthly sales":
        return {"type": "MONTHLY_SALES"}

    if clean_text == "yearly sales":
        return {"type": "YEARLY_SALES"}

    if clean_text in [
        "unpaid debtors", "unpaid", "debtor", "debtors",
        "who owes me", "who owe me", "who are owning me", "who are owing me",
        "who is owing me", "who dey owe me", "who still owe me",
        "customer owing", "customers owing", "who owe",
        "my debtors", "all debtors", "show debtors", "people owing me",
        "customers owing me", "all owing customers",
        "those who owe me", "those owing me",
    ] or re.match(
        r"^(?:show|check|list|see|view|all)\s+(?:my\s+)?(?:debtors?|unpaid(?:\s+debtors?)?)$",
        clean_text,
    ) or re.match(
        r"^(?:show|list|see|all)\s+(?:customers?\s+)?owing(?:\s+me)?$",
        clean_text,
    ) or re.match(
        r"^(?:people|customers?)\s+(?:still\s+)?ow(?:ing|e)\s+me$",
        clean_text,
    ):
        return {"type": "UNPAID_DEBTORS"}

    if clean_text in [
        "overdue debtors", "overdue", "over due",
        "overdue customer", "overdue customers",
        "overdue debts", "past due", "past due debtors",
    ]:
        return {"type": "OVERDUE_DEBTORS"}

    if clean_text == "due" or clean_text in [
        "reminders", "due reminders", "debt reminders", "payment reminders",
        "notify due customer", "notify due customers",
        "notify due", "send due reminders",
    ]:
        return {"type": "DUE_MENU"}

    _restock_m = re.match(
        r"^(?:restock|notify\s+buyers?(?:\s+of)?|alert\s+buyers?(?:\s+of)?|buyers?\s+notify)\s+(.+)$",
        clean_text,
    )
    if _restock_m:
        return {"type": "RESTOCK_NOTIFY", "product": _restock_m.group(1).strip()}

    _buyers_m = re.match(
        r"^(?:buyers?\s+(?:of\s+)?|who\s+bought\s+|who\s+buy\s+|who\s+buys?\s+|show\s+buyers?\s+(?:of\s+)?)(.+)$",
        clean_text,
    )
    if _buyers_m:
        return {"type": "PRODUCT_BUYERS", "product": _buyers_m.group(1).strip()}

    # Supplier product history: "what did ayo supply" / "ayo supply history" / "ayo supplies"
    _sup_hist_m = re.match(
        r"^(?:what\s+did\s+(.+?)\s+supply|(.+?)\s+supply\s+(?:history|list)|(.+?)\s+supplies$|show\s+(.+?)\s+supply(?:\s+history)?)$",
        clean_text,
    )
    if _sup_hist_m:
        sup_name = next(g for g in _sup_hist_m.groups() if g)
        return {"type": "SUPPLIER_HISTORY", "supplier": sup_name.strip()}

    # Product supplier lookup: "who supplies rice" / "rice supplier" / "supplier for rice"
    _prod_sup_m = re.match(
        r"^(?:who\s+suppl(?:y|ies)\s+(.+)|(.+?)\s+supplier(?:s)?$|supplier(?:s)?\s+(?:for|of)\s+(.+))$",
        clean_text,
    )
    if _prod_sup_m:
        prod_name = next(g for g in _prod_sup_m.groups() if g)
        return {"type": "PRODUCT_SUPPLIERS", "product": prod_name.strip()}

    if clean_text in [
        "daily transactions",
        "today transactions",
        "transactions today",
        "transactions for today",
        "total transactions today",
        "transactions total today"
    ]:
        return {
            "type": "PERIOD_TRANSACTIONS",
            "period": "TODAY"
        }

    if clean_text in [
        "total transactions",
        "transactions total"
    ]:
        return {
            "type": "PERIOD_TRANSACTIONS",
            "period": None
        }

    if clean_text in [
        "weekly transactions",
        "transactions this week",
        "this week transactions"
    ]:
        return {
            "type": "PERIOD_TRANSACTIONS",
            "period": "WEEK"
        }

    if clean_text in [
        "monthly transactions",
        "transactions this month",
        "this month transactions"
    ]:
        return {
            "type": "PERIOD_TRANSACTIONS",
            "period": "MONTH"
        }

    if clean_text in [
        "yearly transactions",
        "transactions this year",
        "this year transactions"
    ]:
        return {
            "type": "PERIOD_TRANSACTIONS",
            "period": "YEAR"
        }

    if clean_text in [
        "total amount received",
        "total received",
        "received today",
        "received this week",
        "received this month",
        "received this year"
    ]:
        return {
            "type": "PERIOD_TOTAL_RECEIVED",
            "period": parse_period_phrase(clean_text)
        }

    if clean_text in [
        "total amount paid",
        "total paid",
        "paid today",
        "paid this week",
        "paid this month",
        "paid this year"
    ]:
        return {
            "type": "PERIOD_TOTAL_PAID",
            "period": parse_period_phrase(clean_text)
        }

    if "total outstanding" in clean_text or "outstanding balance" in clean_text or "total debt own" in clean_text or "debt owed" in clean_text:
        return {
            "type": "OUTSTANDING_BALANCE"
        }

    if "cash" in clean_text and "today" in clean_text:
        return {
            "type": "PERIOD_CASH_CREDIT",
            "period": "TODAY",
            "measure": "CASH"
        }

    if "credit" in clean_text and "today" in clean_text:
        return {
            "type": "PERIOD_CASH_CREDIT",
            "period": "TODAY",
            "measure": "CREDIT"
        }

    if "cash" in clean_text and "week" in clean_text:
        return {
            "type": "PERIOD_CASH_CREDIT",
            "period": "WEEK",
            "measure": "CASH"
        }

    if "credit" in clean_text and "week" in clean_text:
        return {
            "type": "PERIOD_CASH_CREDIT",
            "period": "WEEK",
            "measure": "CREDIT"
        }

    if "cash" in clean_text and "month" in clean_text:
        return {
            "type": "PERIOD_CASH_CREDIT",
            "period": "MONTH",
            "measure": "CASH"
        }

    if "credit" in clean_text and "month" in clean_text:
        return {
            "type": "PERIOD_CASH_CREDIT",
            "period": "MONTH",
            "measure": "CREDIT"
        }

    if "cash" in clean_text and "year" in clean_text:
        return {
            "type": "PERIOD_CASH_CREDIT",
            "period": "YEAR",
            "measure": "CASH"
        }

    if "credit" in clean_text and "year" in clean_text:
        return {
            "type": "PERIOD_CASH_CREDIT",
            "period": "YEAR",
            "measure": "CREDIT"
        }

    if clean_text in [
        "most sold product",
        "top selling product",
        "best selling product"
    ]:
        return {
            "type": "MOST_SOLD_PRODUCT"
        }

    if clean_text in [
        "product leaderboard",
        "top products",
        "top selling products"
    ]:
        return {
            "type": "PRODUCT_LEADERBOARD"
        }

    if clean_text.startswith("product sales by date") or clean_text.startswith("products sales by date") or clean_text.startswith("sales by date"):
        return {
            "type": "PRODUCT_SALES_BY_DATE",
            "date": parse_date_phrase(clean_text)
        }

    # Matches "list customers", "my customers", "customer list this week",
    # "show my customers", "check customers", "all customers", etc.
    customer_list_phrases = [
        "list customers", "list customer", "list my customers", "list my customer",
        "list of customers", "customer list", "my customers", "all customers",
        "all my customers", "check customers", "check my customers",
        "show customers", "show my customers", "see customers", "see my customers",
        "view customers", "view my customers",
    ]
    if any(clean_text == cmd or clean_text.startswith(f"{cmd} ") for cmd in customer_list_phrases) or clean_text.startswith("customers"):
        # Ensure we don't accidentally catch "customers count" or "total customers"
        if "count" not in clean_text and "total" not in clean_text:
            return {
                "type": "CUSTOMER_LIST",
                "period": parse_period_phrase(clean_text)
            }

    if clean_text in [
        "total customers today",
        "customers today"
    ]:
        return {
            "type": "CUSTOMER_COUNT",
            "period": "TODAY"
        }

    if clean_text in [
        "total customers this week",
        "customers this week"
    ]:
        return {
            "type": "CUSTOMER_COUNT",
            "period": "WEEK"
        }

    if clean_text in [
        "paid users",
        "paid customers",
        "customers paid"
    ] or ("paid" in clean_text and "users" in clean_text):
        return {
            "type": "PAID_CUSTOMERS",
            "period": parse_period_phrase(clean_text)
        }

    if clean_text in [
        "new users",
        "new customers",
        "customers added"
    ] or ("new" in clean_text and "users" in clean_text):
        return {
            "type": "NEW_CUSTOMERS",
            "period": parse_period_phrase(clean_text)
        }

    if clean_text in [
        "dashboard summary",
        "dashboard stats",
        "business summary",
        "business stats",
        "stats",
        "dashboard"
    ] or ("dashboard" in clean_text and "summary" in clean_text) or (
        "dashboard" in clean_text and "stats" in clean_text
    ) or clean_text.startswith("dashboard ") or clean_text.startswith("stats ") or (
        clean_text.startswith("business summary ")
    ) or (
        clean_text.startswith("business stats ")
    ):
        return {
            "type": "DASHBOARD_SUMMARY",
            "period": parse_period_phrase(clean_text)
        }

    if clean_text in [
        "my plan",
        "plan",
        "subscription",
        "my subscription"
    ]:
        return {"type": "MY_PLAN"}

    if clean_text in ["my quota", "quota", "my limit", "transaction limit", "how many transactions"]:
        return {"type": "MY_QUOTA"}

    if clean_text in [
        "upgrade",
        "pricing",
        "plans",
        "subscription plans"
    ]:
        return {"type": "UPGRADE_MENU"}

    paid_plan_match = re.search(
        r"^(?:paid|pay|payment)\s+(go|pro)$",
        clean_text
    )
    if paid_plan_match:
        return {
            "type": "SUBSCRIPTION_PAID",
            "plan": paid_plan_match.group(1).upper()
        }

    if clean_text in [
        "pending subscriptions",
        "pending subscription",
        "subscription payments",
        "pending subs"
    ]:
        return {"type": "PENDING_SUBSCRIPTIONS"}

    if clean_text in [
        "app dashboard",
        "app admin dashboard",
        "admin dashboard",
        "app stats",
        "app admin",
        "platform dashboard"
    ]:
        return {"type": "APP_ADMIN_DASHBOARD"}

    app_admin_list_match = re.search(
        r"^app\s+(pro|go|free|basic|expired)\s+users$",
        clean_text
    )
    if app_admin_list_match:
        plan = app_admin_list_match.group(1).upper()
        if plan == "FREE":
            plan = PLAN_BASIC
        return {
            "type": "APP_ADMIN_USERS_BY_PLAN",
            "plan": plan
        }

    role_match = re.search(
        r"^(allow|approve|add|grant|deny|disable|remove|suspend)\s+"
        r"(subscription admin|sub admin|customer support|support|app admin)\s+"
        r"(\+?[\d ]{7,15})$",
        clean_text
    )
    if role_match:
        action_word = role_match.group(1)
        role_phrase = role_match.group(2)
        role = normalize_admin_role(role_phrase.replace("sub admin", "subscription admin"))
        return {
            "type": "MANAGE_APP_ADMIN_ROLE",
            "role": role,
            "phone": normalize_phone(role_match.group(3)),
            "active": action_word in ["allow", "approve", "add", "grant"]
        }

    if clean_text in [
        "list app roles",
        "list admin roles",
        "admin roles",
        "app roles"
    ]:
        return {"type": "LIST_APP_ADMIN_ROLES"}

    approve_match = re.search(
        r"^approve(?:\s+sub(?:scription)?)?\s+(\+?[\d ]{7,15})$",
        clean_text
    )
    if approve_match:
        return {
            "type": "APPROVE_SUBSCRIPTION",
            "phone": normalize_phone(approve_match.group(1))
        }

    reject_match = re.search(
        r"^reject(?:\s+sub(?:scription)?)?\s+(\+?[\d ]{7,15})$",
        clean_text
    )
    if reject_match:
        return {
            "type": "REJECT_SUBSCRIPTION",
            "phone": normalize_phone(reject_match.group(1))
        }

    activation_match = re.search(
        r"^(?:activate|set)\s+plan\s+(basic|go|pro)\s+(?:for\s+)?(\+?[\d ]{7,15})(?:\s+(\d+)\s+days?)?$",
        clean_text
    )
    if activation_match:
        return {
            "type": "ACTIVATE_PLAN",
            "plan": activation_match.group(1).upper(),
            "phone": normalize_phone(activation_match.group(2)),
            "days": int(activation_match.group(3)) if activation_match.group(3) else None
        }

    if clean_text in [
        "total customers this month",
        "customers this month"
    ]:
        return {
            "type": "CUSTOMER_COUNT",
            "period": "MONTH"
        }

    if clean_text in [
        "total customers this year",
        "customers this year"
    ]:
        return {
            "type": "CUSTOMER_COUNT",
            "period": "YEAR"
        }

    if clean_text in [
        "total customers",
        "customers total",
        "number of customers"
    ]:
        return {
            "type": "CUSTOMER_COUNT",
            "period": None
        }

    if clean_text in [
        "biggest debtor",
        "top debtor"
    ]:
        return {
            "type": "BIGGEST_DEBTOR"
        }

    if clean_text in [
        "debtor leaderboard",
        "debtors leaderboard",
        "top debtors"
    ]:
        return {
            "type": "DEBTOR_LEADERBOARD"
        }

    if clean_text.startswith("search customer "):
        return {
            "type": "SEARCH_CUSTOMER",
            "query": clean_text.replace("search customer ", "", 1).strip()
        }

    if clean_text.startswith("customer balance summary") or clean_text.startswith("customer summary"):
        name = clean_text.replace("customer balance summary", "").replace("customer summary", "").strip()
        return {
            "type": "CUSTOMER_SUMMARY",
            "name": name
        }

    if clean_text.endswith(" balance") or clean_text.endswith(" account"):
        name = clean_text.rsplit(" ", 1)[0].strip()
        if name and name not in ["outstanding", "total outstanding"]:
            return {
                "type": "CUSTOMER_SUMMARY",
                "name": name
            }

    _class_m = re.search(
        r"^(?:set\s+)?(?:class|grade)\s+(?P<name>[a-zA-Z][a-zA-Z\s']{1,30}?)\s+(?P<class_name>[a-zA-Z0-9][a-zA-Z0-9\s/\-]{0,30})$",
        clean_text
    ) or re.search(
        r"^(?P<name>[a-zA-Z][a-zA-Z\s']{1,30}?)\s+(?:class|grade)\s+(?P<class_name>[a-zA-Z0-9][a-zA-Z0-9\s/\-]{0,30})$",
        clean_text
    )
    if _class_m:
        _student = _class_m.group("name").strip()
        _cls = _class_m.group("class_name").strip()
        if _student and _cls and len(_student) >= 2:
            return {
                "type": "SET_STUDENT_CLASS",
                "name": _student,
                "class_name": _cls,
            }

    permission_match = re.search(
        r"^(grant|allow|give)\s+staff\s+(\+?[\d ]{7,15})\s+(?:view\s+all|view\s+all\s+transactions|all\s+transactions)$",
        clean_text
    )
    if permission_match:
        return {
            "type": "GRANT_STAFF_VIEW_ALL",
            "phone": normalize_phone(permission_match.group(2))
        }

    permission_match = re.search(
        r"^(revoke|remove|disable)\s+staff\s+(\+?[\d ]{7,15})\s+(?:view\s+all|view\s+all\s+transactions|all\s+transactions)$",
        clean_text
    )
    if permission_match:
        return {
            "type": "REVOKE_STAFF_VIEW_ALL",
            "phone": normalize_phone(permission_match.group(2))
        }

    if clean_text.endswith("transactions"):
        candidate = clean_text.replace("transactions", "").replace("customer", "").strip()
        if candidate:
            return {
                "type": "CUSTOMER_TRANSACTIONS",
                "name": candidate
            }

    note_match = re.search(
        r"^(?:add\s+)?note\s+(?:transaction|tx)\s+#?(?P<transaction_id>\d+)\s+(?P<note>.+)$",
        clean_text
    )
    if note_match:
        return {
            "type": "ADD_TRANSACTION_NOTE",
            "transaction_id": int(note_match.group("transaction_id")),
            "note": note_match.group("note").strip()
        }

    note_match = re.search(
        r"^(?:transaction|tx)\s+#?(?P<transaction_id>\d+)\s+notes?$",
        clean_text
    )
    if note_match:
        return {
            "type": "TRANSACTION_NOTES",
            "transaction_id": int(note_match.group("transaction_id"))
        }

    if "partial payment" in clean_text or "part payment" in clean_text:
        return {
            "type": "FORMATS"
        }

    if clean_text.startswith("add staff"):
        # Matches with or without brackets: "add staff [080...] [Name]" or "add staff 080... Name"
        match = re.search(r"add staff \[?(\+?[\d ]{7,15})\]?\s*\[?([^\]]+)\]?", clean_text)
        if match:
            return {
                "type": "ADD_STAFF",
                "phone": normalize_phone(match.group(1).strip()),
                "name": match.group(2).strip()
            }

    if clean_text.startswith("remove staff"):
        # Matches "remove staff 080..."
        match = re.search(r"remove staff (\+?\d+)", clean_text)
        if match:
            return {
                "type": "REMOVE_STAFF",
                "phone": normalize_phone(match.group(1))
            }

    if clean_text in [
        "staff menu",
        "admin menu",
        "list staff",
        "my staff"
    ]:
        return {"type": "STAFF_MENU"}

    _staff_report_patterns = [
        "staff report", "staff performance", "staff activity",
        "staff report today", "staff report this week", "staff report this month",
        "staff performance today", "staff performance this week", "staff performance this month",
    ]
    if clean_text in _staff_report_patterns:
        _period = None
        if "today" in clean_text:
            _period = "TODAY"
        elif "week" in clean_text:
            _period = "WEEK"
        elif "month" in clean_text:
            _period = "MONTH"
        return {"type": "STAFF_REPORT", "period": _period}

    if clean_text in [
        "what can you do", "what can titi do", "titi what can you do",
        "help", "commands", "command list", "capabilities",
        "what do you do", "how do you work", "titi help",
        "show commands", "list commands", "all commands",
        "how can you help", "how can titi help me",
        "how to use you", "how will i use you", "how do i use you",
        "how do i use titi", "how to use titi",
        "how do you operate", "how does titi work", "how does this work",
        "how do you help me", "what do you know", "what can i ask you",
        "what can i do here", "what can i say", "guide me",
        "titi guide me", "start guide", "how to start",
    ]:
        return {"type": "WHAT_CAN_DO"}

    # ── App navigation guide ─────────────────────────────────────────────────
    # Detects "how do i / where is / how to / show me how + topic" queries
    # and returns an APP_GUIDE type so the answer is pre-written (no LLM cost).
    _nav_intent = re.search(
        r"\b(how (do|can|to|will)|where (is|can|do|are)|show me|help me|i want to|take me to|find|locate|guide me to|download|install|get the)\b",
        clean_text,
    )
    if _nav_intent:
        _guide_topics = {
            "pdf":          ["pdf", "receipt", "download receipt", "print receipt", "export receipt", "download invoice"],
            "record_sale":  ["record a sale", "record sale", "add a sale", "add sale", "how to sell", "how to record", "enter a sale", "input sale"],
            "inventory":    ["add stock", "add product", "add item", "add goods", "update stock", "add to stock", "add to inventory", "update inventory", "my inventory", "my stock", "inventory", "stock"],
            "customers":    ["add customer", "new customer", "add client", "register customer", "save customer", "customer", "client"],
            "summary":      ["summary", "dashboard", "report", "overview", "check profit", "see profit", "today profit", "check today", "see report"],
            "reminder":     ["reminder", "send reminder", "debt reminder", "remind customer", "follow up", "chase customer"],
            "supplier":     ["add supplier", "supplier", "buy from supplier", "record purchase", "restock from supplier"],
            "staff":        ["add staff", "staff", "employee", "worker", "team member", "manage staff"],
            "partner":      ["partner", "investor", "add partner", "invite partner", "co-founder", "add investor"],
            "notes":        ["add note", "notes", "note", "memo", "business note", "write note"],
            "pos":          ["pos", "point of sale", "checkout", "sell in shop", "cashier", "process sale"],
            "bulk_add":     ["bulk add", "add multiple", "add many products", "add many items", "add products at once"],
            "branches":     ["branch", "branches", "add branch", "multiple shop", "new location", "shop location"],
            "automation":   ["automation", "automate", "automatic reminder", "auto send", "automated message"],
            "download_app": ["download app", "install app", "get the app", "play store", "app store", "mobile app", "download the app", "install the app"],
            "wallet":       ["wallet", "receive payment", "virtual account", "bank transfer", "pay me", "accept payment"],
            "transactions": ["transactions", "sales history", "see my sales", "view sales", "sales record", "transaction history"],
            "debt":         ["debt", "debtors", "who owes", "unpaid", "customer debt", "owe me"],
        }
        for _topic, _keywords in _guide_topics.items():
            if any(_kw in clean_text for _kw in _keywords):
                return {"type": "APP_GUIDE", "topic": _topic}

    # ── Bulk product name add ────────────────────────────────────────────────
    # "add paracetamol, sugar, tissue, milo" — comma/semicolon separated list
    # Must start with "add" and contain at least one separator (≥2 names)
    _bulk_add_m = re.match(
        r"^add\s+(?P<names>[a-z][a-z0-9 ,;\n&'\-]{3,})$",
        clean_text,
    )
    if _bulk_add_m:
        raw = _bulk_add_m.group("names")
        parts = [p.strip() for p in re.split(r"[,;\n]+", raw) if p.strip()]
        if len(parts) >= 2:
            return {"type": "BULK_ADD_PRODUCTS", "names": parts}

    if clean_text in [
        "reonboard",
        "change name",
        "update name",
        "update business name",
        "change my business name",
        "change business name",
        "change business",
    ]:
        return {"type": "REONBOARD"}

    # ── Staff profile ────────────────────────────────────────────────────────
    # "set staff profile Emeka position cashier level junior salary 50000 matric EMP001"
    _staff_set_m = re.match(
        r"^set\s+staff\s+profile\s+(?P<name>[a-z][a-z ]+?)(?:\s+position\s+(?P<position>[a-z][a-z ]+?))?(?:\s+level\s+(?P<level>[a-z]+))?(?:\s+salary\s+(?P<salary>[\d,]+))?(?:\s+matric\s+(?P<matric>[a-z0-9]+))?$",
        clean_text,
    )
    if _staff_set_m:
        return {
            "type": "SET_STAFF_PROFILE",
            "staff_name": _staff_set_m.group("name").strip(),
            "position": (_staff_set_m.group("position") or "").strip() or None,
            "level": (_staff_set_m.group("level") or "").strip() or None,
            "salary": int(_staff_set_m.group("salary").replace(",", "")) if _staff_set_m.group("salary") else None,
            "matric": (_staff_set_m.group("matric") or "").strip() or None,
        }

    # "view staff profile Emeka"  |  "view staff profiles"
    _staff_view_m = re.match(
        r"^view\s+staff\s+profiles?(?:\s+(?P<name>[a-z][a-z ]+))?$",
        clean_text,
    )
    if _staff_view_m:
        return {
            "type": "VIEW_STAFF_PROFILE",
            "staff_name": (_staff_view_m.group("name") or "").strip() or None,
        }

    # ── Partner management ───────────────────────────────────────────────────
    # "invite partner 08012345678 co_founder 30%"
    # "invite partner 08012345678 investor 500000"
    _invite_m = re.match(
        r"^invite\s+(?:partner|investor|co.?founder)\s+"
        r"(?P<phone>\+?[\d]{7,15})\s*"
        r"(?P<role>co.?founder|partner|investor|silent)?\s*"
        r"(?P<extra>[\d,.]+%?)?$",
        clean_text,
    )
    if _invite_m:
        extra = (_invite_m.group("extra") or "").replace(",", "").strip()
        equity = None
        investment = None
        if extra.endswith("%"):
            try:
                equity = float(extra[:-1])
            except ValueError:
                pass
        elif extra:
            try:
                investment = int(float(extra))
            except ValueError:
                pass
        role_raw = (_invite_m.group("role") or "partner").replace("-", "_").replace(" ", "_")
        role = "co_founder" if "founder" in role_raw else role_raw
        return {
            "type": "INVITE_PARTNER",
            "partner_phone": _invite_m.group("phone"),
            "role": role,
            "equity_percent": equity,
            "investment_amount": investment,
        }

    # "remove partner 08012345678"
    _rem_partner_m = re.match(
        r"^remove\s+(?:partner|investor)\s+(?P<phone>\+?[\d]{7,15})$",
        clean_text,
    )
    if _rem_partner_m:
        return {"type": "REMOVE_PARTNER", "partner_phone": _rem_partner_m.group("phone")}

    # "view partners"  |  "view investors"
    if clean_text in ("view partners", "view investors", "my partners", "partners list", "investors list"):
        return {"type": "VIEW_PARTNERS"}

    # "partner status"
    if clean_text in ("partner status", "my partnerships", "my investments", "businesses i joined"):
        return {"type": "PARTNER_STATUS"}

    # "ACCEPT PARTNER 0801..." | "DECLINE PARTNER 0801..."
    _accept_m = re.match(
        r"^(?P<action>accept|decline)\s+partner\s+(?P<phone>\+?[\d]{7,15})$",
        clean_text,
    )
    if _accept_m:
        return {
            "type": "ACCEPT_PARTNER",
            "action": _accept_m.group("action"),
            "owner_phone": _accept_m.group("phone"),
        }

    # "business overview [phone?]"
    _biz_overview_m = re.match(
        r"^business\s+(?:overview|summary|report)(?:\s+(?P<phone>\+?[\d]{7,15}))?$",
        clean_text,
    )
    if _biz_overview_m:
        return {
            "type": "PARTNER_BUSINESS_OVERVIEW",
            "owner_phone": (_biz_overview_m.group("phone") or "").strip() or None,
        }

    # ── Shared notes ─────────────────────────────────────────────────────────
    # "note rent paid 45000 partners"
    # "note agreement Emeka owns 30% signed today all"
    _note_m = re.match(
        r"^note\s+(?P<body>.+?)(?:\s+(?P<visibility>owner.only|partners|investors|all))?$",
        clean_text,
    )
    if _note_m:
        body = _note_m.group("body").strip()
        visibility = (_note_m.group("visibility") or "owner_only").replace("-", "_").replace(" ", "_")
        # Try to pull an amount out of the body
        _amt_m = re.search(r"\b(\d[\d,]*)\b", body)
        amount = int(_amt_m.group(1).replace(",", "")) if _amt_m else None
        # Detect category from keywords
        category = "memo"
        if any(w in body for w in ("paid", "pay", "expense", "rent", "salary", "fuel", "electricity", "buy", "bought")):
            category = "expense"
        elif any(w in body for w in ("received", "income", "revenue", "profit")):
            category = "income"
        elif any(w in body for w in ("agreement", "contract", "signed", "terms", "deal")):
            category = "agreement"
        return {
            "type": "ADD_NOTE",
            "body": body,
            "category": category,
            "amount": amount,
            "visibility": visibility,
        }

    # "view notes"  |  "view notes expenses"
    _view_notes_m = re.match(
        r"^view\s+notes?(?:\s+(?P<category>expenses?|income|memo|agreement))?$",
        clean_text,
    )
    if _view_notes_m:
        cat = (_view_notes_m.group("category") or "").rstrip("s")
        return {"type": "VIEW_NOTES", "category": cat or None}

    # ── Truck registration ───────────────────────────────────────────────────
    # "add truck KJA234AB driver Emeka 08012345678"
    # "register truck KJA 234 AB driver Bayo 0801..."
    _truck_m = re.match(
        r"^(?:add|register)\s+truck\s+"
        r"(?P<plate>[A-Za-z0-9][A-Za-z0-9\s\-]{1,15}?)"
        r"(?:\s+driver\s+(?P<driver>[A-Za-z][A-Za-z\s]{1,30}?))??"
        r"(?:\s+(?P<driver_phone>0\d{10}|\+234\d{10}))?$",
        clean_text,
    )
    if _truck_m:
        plate = _truck_m.group("plate").strip().upper()
        driver = (_truck_m.group("driver") or "").strip().title()
        driver_phone = (_truck_m.group("driver_phone") or "").strip()
        if plate:
            return {
                "type": "ADD_TRUCK",
                "plate": plate,
                "driver": driver,
                "driver_phone": driver_phone,
            }

    # ── Truck list ──────────────────────────────────────────────────────────
    if clean_text in ["my trucks", "trucks", "truck list", "all trucks", "registered trucks"]:
        return {"type": "MY_TRUCKS"}

    # ── Record trip (wizard entry) ───────────────────────────────────────────
    if clean_text in ["record trip", "trip", "new trip", "add trip"]:
        return {"type": "RECORD_TRIP_WIZARD"}

    # ── Add truck (wizard entry — bare command, no plate) ────────────────────
    if clean_text in ["add truck", "register truck", "new truck"]:
        return {"type": "ADD_TRUCK_WIZARD"}

    # ── Data export ───────────────────────────────────────────────────────────
    _export_m = re.match(
        r"^export"
        r"(?:\s+(?P<what>transactions?|debtors?|debt|customers?|clients?|stock|inventory))?"
        r"(?:\s+(?P<period>today|this week|this month|this year"
        r"|january|february|march|april|may|june"
        r"|july|august|september|october|november|december"
        r"|week|month|year))?$",
        clean_text,
    )
    if _export_m:
        what = (_export_m.group("what") or "").strip()
        period_raw = (_export_m.group("period") or "").strip()
        _period_map = {
            "today": "TODAY", "this week": "WEEK", "week": "WEEK",
            "this month": "MONTH", "month": "MONTH",
            "this year": "YEAR", "year": "YEAR",
            "january": "JANUARY", "february": "FEBRUARY", "march": "MARCH",
            "april": "APRIL", "may": "MAY", "june": "JUNE",
            "july": "JULY", "august": "AUGUST", "september": "SEPTEMBER",
            "october": "OCTOBER", "november": "NOVEMBER", "december": "DECEMBER",
        }
        period_key = _period_map.get(period_raw) if period_raw else None
        if what in ("debtors", "debtor", "debt"):
            return {"type": "EXPORT_DEBTORS", "period": period_key}
        if what in ("stock", "inventory"):
            return {"type": "EXPORT_STOCK", "period": period_key}
        if what in ("customers", "customer", "clients", "client"):
            return {"type": "EXPORT_CUSTOMERS", "period": period_key}
        return {"type": "EXPORT_TRANSACTIONS", "period": period_key}

    # ── Loan statement ───────────────────────────────────────────────────────
    if re.match(
        r"^(loan\s+)?statement|business\s+statement|my\s+statement|financial\s+statement$",
        clean_text,
    ):
        return {"type": "LOAN_STATEMENT"}

    # ── Product rename shortcut ──────────────────────────────────────────────
    # "rename rice to brown rice"  |  "correct paracetamol to paracetamol 500mg"
    _rename_prod_m = re.match(
        r"^(?:rename|correct|fix|edit)\s+(?P<old_name>.+?)\s+to\s+(?P<new_name>.+)$",
        clean_text,
    )
    if _rename_prod_m:
        _old = _rename_prod_m.group("old_name").strip()
        _new = _rename_prod_m.group("new_name").strip()
        if _old and _new and len(_new) >= 2:
            return {
                "type": "RENAME_PRODUCT",
                "old_name": _old,
                "new_name": _new,
            }

    # ── Transaction void / correction ────────────────────────────────────────
    # "void 42 wrong customer"  |  "void last wrong product"
    # "remove transaction 42"   — "remove" must come before "transaction"
    _void_match = re.match(
        r"^(?:void|cancel\s+transaction|correct\s+transaction|reverse\s+transaction"
        r"|remove\s+transaction)\s+"
        r"(?P<ref>last|\d+)"
        r"(?:\s+(?P<reason>.+))?$",
        clean_text,
    )
    if _void_match:
        ref = _void_match.group("ref")
        reason = (_void_match.group("reason") or "").strip()
        return {
            "type": "VOID_TRANSACTION",
            "ref": ref,
            "reason": reason,
        }

    # ── Conversational analytics ─────────────────────────────────────────────
    # "who owes me the most" / "who is my biggest debtor"
    if re.search(r"\b(who|which).*(ow(?:e|es|ed|ing)|debt|borrow|balance)\b", clean_text) or \
       re.search(r"\b(biggest|top|most|highest).*(debt|debtor|ow(?:e|es|ing)|balance)\b", clean_text):
        return {"type": "CONVO_TOP_DEBTORS"}

    # "why are my sales declining / dropping / down / slow"
    if re.search(r"\b(why|how|what).*(sales|revenue|income|money).*\b(declin|drop|fall|slow|down|low|less|decreas)", clean_text) or \
       re.search(r"\b(sales|revenue).*(declin|drop|slow|down|trend|compar|last month|this month)\b", clean_text) or \
       clean_text in ["sales trend", "sales comparison", "compare sales", "month comparison"]:
        return {"type": "CONVO_SALES_TREND"}

    # "what sells most / best product / top product this month"
    if re.search(r"\b(what|which).*(sell|selling|product|item).*(most|best|top|high)\b", clean_text) or \
       re.search(r"\b(best|top|most).*(sell|selling|product|item)\b", clean_text):
        period = None
        if "today" in clean_text:
            period = "TODAY"
        elif "week" in clean_text:
            period = "WEEK"
        elif "month" in clean_text:
            period = "MONTH"
        elif "year" in clean_text:
            period = "YEAR"
        return {"type": "CONVO_BEST_PRODUCT", "period": period}

    # "when am I busiest / my busy days / peak day"
    if re.search(r"\b(when|what day|which day).*(busy|busiest|peak|most sales|highest)\b", clean_text) or \
       re.search(r"\b(busiest|peak).*(day|time|period|hour)?\b", clean_text) or \
       re.search(r"\b(when).*(busiest|most)\b", clean_text) or \
       clean_text in ["busy days", "peak days", "busiest day", "my busy day", "busiest"]:
        return {"type": "CONVO_BUSIEST_PERIOD"}

    # "is rice profitable / how is rice doing / profit on rice"
    _profit_match = re.match(
        r"^(?:is\s+|how\s+is\s+|profit\s+on\s+|margin\s+on\s+|how\s+profitable\s+is\s+)(?P<product>.+?)(?:\s+profitable|\s+doing|\s+performing)?$",
        clean_text
    )
    if _profit_match and re.search(
        r"\b(profit(?:able)?|margin|cost|earn(?:ing)?|making|doing|performing|selling)\b",
        clean_text
    ):
        return {"type": "CONVO_PRODUCT_PROFIT", "product": _profit_match.group("product").strip()}

    # ── Linked phones ────────────────────────────────────────────────────────
    # "link phone 08012345678"
    _link_ph = re.match(r"^link\s+phone\s+(?P<phone>[\d\s\+\-]{7,15})$", clean_text)
    if _link_ph:
        return {"type": "LINK_PHONE", "phone": _link_ph.group("phone").strip()}

    # "link confirm 483920"
    _link_confirm = re.match(r"^link\s+confirm\s+(?P<code>\d{4,8})$", clean_text)
    if _link_confirm:
        return {"type": "LINK_CONFIRM", "code": _link_confirm.group("code")}

    # "link decline"
    if clean_text == "link decline":
        return {"type": "LINK_DECLINE"}

    # "unlink phone 08012345678"
    _unlink = re.match(r"^unlink\s+phone\s+(?P<phone>[\d\s\+\-]{7,15})$", clean_text)
    if _unlink:
        return {"type": "UNLINK_PHONE", "phone": _unlink.group("phone").strip()}

    # "my phones" | "linked phones"
    if clean_text in ["my phones", "linked phones", "my numbers", "linked numbers"]:
        return {"type": "MY_PHONES"}

    # ── Account recovery PIN ─────────────────────────────────────────────────
    # "set pin 1234"
    _set_pin = re.match(r"^(?:set|create|add)\s+pin\s+(?P<pin>\d{4,6})$", clean_text)
    if _set_pin:
        return {"type": "SET_PIN", "pin": _set_pin.group("pin")}

    # "change pin 1234 5678"
    _chg_pin = re.match(r"^change\s+pin\s+(?P<old>\d{4,6})\s+(?P<new>\d{4,6})$", clean_text)
    if _chg_pin:
        return {"type": "CHANGE_PIN", "old_pin": _chg_pin.group("old"), "new_pin": _chg_pin.group("new")}

    # "remove pin 1234"
    _rem_pin = re.match(r"^remove\s+pin\s+(?P<pin>\d{4,6})$", clean_text)
    if _rem_pin:
        return {"type": "REMOVE_PIN", "pin": _rem_pin.group("pin")}

    # "recover 08012345678 1234"  |  "recover account 08012345678 pin 1234"
    _recover = re.match(
        r"^recover(?:\s+account)?\s+(?P<phone>[\d\s\+\-]{7,15}?)\s+(?:pin\s+)?(?P<pin>\d{4,6})$",
        clean_text
    )
    if _recover:
        return {
            "type": "RECOVER_ACCOUNT",
            "old_phone": _recover.group("phone").strip(),
            "pin": _recover.group("pin"),
        }

    # ── Fast Capture Mode commands ───────────────────────────────────────────
    if clean_text in ["fast mode", "fast capture", "fast mode status"]:
        return {"type": "FAST_CAPTURE_STATUS"}

    if clean_text in ["fast mode off", "fast capture off", "stop fast mode", "normal mode"]:
        return {"type": "FAST_MODE_OFF"}

    if clean_text in ["close sales", "end of day", "review sales",
                      "review entries", "daily review", "close day"]:
        return {"type": "CLOSE_SALES"}

    # "fast mode on"  |  "fast mode on 8am to 6pm"
    fast_on_match = re.match(
        r"^(?:fast\s+mode|fast\s+capture)\s+on"
        r"(?:\s+(?P<start>\d{1,2})(?:am|pm)?\s+(?:to|-)\s+(?P<end>\d{1,2})(?:am|pm)?)?$",
        clean_text,
    )
    if fast_on_match:
        hours = {}
        if fast_on_match.group("start"):
            h = int(fast_on_match.group("start"))
            if "pm" in clean_text.split("to")[0] and h < 12:
                h += 12
            hours["start"] = h
        if fast_on_match.group("end"):
            h = int(fast_on_match.group("end"))
            if "pm" in clean_text.split("to")[-1] and h < 12:
                h += 12
            hours["end"] = h
        return {"type": "FAST_MODE_ON", "hours": hours}

    # ── Margin / profitability commands ─────────────────────────────────────
    if clean_text in [
        "margin", "margin report", "margin today", "margin this week",
        "margin this month", "profit", "profit today", "profit this week",
        "profit this month", "discount report", "margin summary",
    ]:
        period_map = {
            "today": "TODAY", "this week": "WEEK",
            "this month": "MONTH", "this year": "YEAR",
        }
        period = next(
            (v for k, v in period_map.items() if k in clean_text), None
        )
        return {"type": "MARGIN_REPORT", "period": period}

    if clean_text in [
        "products below cost", "below cost", "loss products",
        "selling below cost", "which products losing money",
    ]:
        return {"type": "BELOW_COST_PRODUCTS"}

    # "print receipt Mary"  |  "receipt Mary"  |  "receipt 42"  |  "Mary receipt"
    receipt_match = re.match(
        r"^(?:print\s+)?receipt\s+(?P<query>.+)$",
        clean_text,
    ) or re.match(
        r"^(?P<query>[a-z][a-z ]+?)\s+receipt$",
        clean_text,
    )
    if receipt_match:
        query = receipt_match.group("query").strip()
        if query.isdigit():
            return {"type": "PRINT_RECEIPT", "transaction_id": int(query)}
        return {"type": "PRINT_RECEIPT", "customer_name": query}

    # "product alias eba = garri" / "alias eba = garri" / "eba same as garri" / "eba means garri"
    # Intentionally exclude bare "X is Y" — too broad, catches plain English sentences.
    alias_match = re.match(
        r"^(?:product\s+)?alias\s+(?P<alias>[a-z][a-z ]+?)\s*=\s*(?P<canonical>[a-z][a-z ]+)$",
        clean_text,
    ) or re.match(
        r"^(?P<alias>[a-z][a-z ]+?)\s+(?:same\s+as|means)\s+(?P<canonical>[a-z][a-z ]+)$",
        clean_text,
    )
    if alias_match:
        return {
            "type": "PRODUCT_ALIAS",
            "alias": alias_match.group("alias").strip(),
            "canonical": alias_match.group("canonical").strip(),
        }

    if clean_text.startswith("remind"):
        return {
            "type": "REMIND",
            "text": text
        }

    supplier_transaction = extract_supplier_transaction(text)
    if supplier_transaction:
        return supplier_transaction

    if re.match(r"^i\s+(?:buy|bought|purchase|purchased)\b", clean_text):
        return {
            "type": "SELF_PURCHASE_NEEDS_SUPPLIER"
        }

    artisan = extract_artisan_transaction(text)
    if artisan:
        return artisan

    if clean_text in ["resign", "stop working", "leave staff", "leave business", "remove me as staff"]:
        return {
            "type": "RESIGN_REQUEST"
        }

    if "no longer working with" in clean_text:
        business = clean_text.split("working with")[-1].strip()
        return {
            "type": "RESIGN_REQUEST",
            "business_name": business
        }

    onboarding = extract_customer_onboarding(text)
    if onboarding:
        return {
            "type": "SET_PHONE",
            "name": onboarding["name"].strip().lower(),
            "customer_phone": normalize_phone(onboarding["customer_phone"])
        }

    phone_match = re.match(
        r"(?P<name>[a-zA-Z'’\- ]+?)\s+(?:phone|number)\s+(?P<phone>[+\d ]+)$",
        clean_text
    )

    if phone_match:
        return {
            "type": "SET_PHONE",
            "name": phone_match.group("name").strip().lower(),
            "customer_phone": normalize_phone(phone_match.group("phone"))
        }

    # =========================
    # 🧹 CLEAN TEXT
    # =========================

    invoice_clean_text = text.lower().strip()
    clean_text = _normalize_text_for_parsing(text)

    words = clean_text.split()

    amounts = extract_amounts(clean_text)

    if len(amounts) == 0:
        return None

    item_details = extract_item_details(text)
    direct_sale_details = extract_direct_sale_details(text)

    buy_amount = 0
    paid_amount = 0
    quantity = None
    unit = None
    product = None
    unit_price = None
    total = None
    due_date = None

    # =========================
    # 📅 DUE DATE
    # =========================
    due_date = extract_due_date_from_text(clean_text)

    due_clause_pattern = (
        r"\s*(?:,?\s+and)?\s+"
        r"(?:due\s+to\s+pay|due|will\s+pay|pay|balance|will\s+balance)"
        r"\s+\d{1,2}/\d{1,2}/\d{2,4}\b"
    )
    invoice_clean_text = re.sub(due_clause_pattern, "", invoice_clean_text).strip()
    clean_text = re.sub(due_clause_pattern, "", clean_text, flags=re.IGNORECASE).strip()

    # ── Cost-price update intercept ───────────────────────────────────────────
    # "egg cost price is 4700" / "garri cost 4000" with NO sell price.
    # Must come before transaction detection so it doesn't create a garbage item.
    if not re.search(r"\bsell(?:ing)?(?:\s+price)?\b", clean_text, re.I):
        _cp_match = re.match(
            r"^(?P<product>[a-z][a-z ]+?)\s+cost(?:\s+price)?\s+(?:is\s+)?(?P<price>\d[\d,]*)$",
            clean_text,
        )
        if _cp_match:
            _cp_price = parse_amount_token(_cp_match.group("price").replace(",", ""))
            if _cp_price:
                return {
                    "type": "SET_COST_PRICE",
                    "product": _cp_match.group("product").strip(),
                    "price": _cp_price,
                }

    # ── Early stock-add intercept ─────────────────────────────────────────────
    # "selling price" never appears in a normal customer transaction.
    # If the message has both "cost" and "selling price" it is inventory intent,
    # even if the user forgot to write "add stock" at the front.
    if (
        re.search(r"\bselling\s+price\b", clean_text, re.I)
        and re.search(r"\bcost\b", clean_text, re.I)
    ):
        _early_item = _parse_stock_item_full(clean_text)
        if _early_item:
            return {"type": "STOCK_ADD_WITH_PRICES", "items": [_early_item]}
        _early_items = _parse_stock_items_with_prices(clean_text)
        if _early_items:
            return {"type": "STOCK_ADD_WITH_PRICES", "items": _early_items}

    # =========================
    # 🧠 DETECT TYPE
    # =========================

    lowered_clean_text = clean_text.lower()
    has_buy = bool(re.search(r"\b(" + "|".join(BUY_KEYWORDS) + r")\b", lowered_clean_text))
    has_pay = bool(re.search(r"\b(" + "|".join(PAY_KEYWORDS) + r")\b", lowered_clean_text))
    has_direct_sale = bool(re.match(r"^(?:i\s+)?(" + "|".join(SALE_KEYWORDS) + r")\b", clean_text.lower()))

    if has_direct_sale:
        # If "to [name]" is present, this is a customer sale, not a direct SALE.
        # Reconstruct as "[name] bought ..." and re-parse through the BUY path.
        _sale_body_for_to = re.sub(
            r"^(?:i\s+)?(?:sold|sell|supply|supplied|deliver|delivered)\s+",
            "", clean_text, count=1, flags=re.I,
        ).strip()
        _to_match = re.search(
            r"\bto\s+(?P<name>[a-zA-Z][a-zA-Z'-]*"
            r"(?:\s+(?!at\b|for\b|paid\b|balance\b|\d)[a-zA-Z][a-zA-Z'-]*){0,2})"
            r"\s+(?=at\b|for\b|paid\b|balance\b|\d)",
            _sale_body_for_to, re.I,
        )
        if _to_match:
            _name = _to_match.group("name").strip()
            _item_part = _sale_body_for_to[:_to_match.start()].strip()
            _rest = _sale_body_for_to[_to_match.end():].strip()
            _rewritten = f"{_name} bought {_item_part} {_rest}".strip()
            _result = parse_message(_rewritten)
            if _result and _result.get("type") == "TRANSACTION" and _result.get("name"):
                return _result

        # Strip payment suffixes so commas in prices like "5,000" aren't split
        # and so the last number isn't misidentified as the sale price.
        # Handles: "and received payment of N", "paid N", "and paid N", "N paid", "and N paid"
        _amt_pat = r"\d[\d,\.]*\s*(?:[kK](?![a-zA-Z])|[mM](?![a-zA-Z]))?"
        _pay_sfx = re.search(
            rf"(?:"
            rf"\s+and\s+(?:received?|recieved?|got\s+(?:the\s+)?(?:paid|payment)|collected?)\s+"
            rf"(?:the\s+)?(?:payment\s+of\s+|cash\s+of\s+)?"
            rf"|(?:\s+(?:and\s+)?(?:each\s+)?paid\s+)"
            rf")(?P<paid_sfx>{_amt_pat})\s*$",
            invoice_clean_text, re.I,
        )
        if not _pay_sfx:
            # "N paid" / "and N paid" at end (reversed order)
            _pay_sfx = re.search(
                rf"(?:\s+and)?\s+(?P<paid_sfx>{_amt_pat})\s+paid\s*$",
                invoice_clean_text, re.I,
            )
        _direct_paid = 0
        _invoice_clean_stripped = invoice_clean_text
        if _pay_sfx:
            _direct_paid = parse_amount_token(_pay_sfx.group("paid_sfx")) or 0
            _invoice_clean_stripped = invoice_clean_text[:_pay_sfx.start()].strip()

        sale_body = re.sub(
            r"^(?:i\s+)?(?:sold|sell|supply|supplied|deliver|delivered)\s+",
            "",
            _invoice_clean_stripped,
            count=1
        ).strip()
        invoice = parse_invoice_items(sale_body)
        if invoice:
            return {
                "type": "TRANSACTION",
                "name": "",
                "action": "SALE",
                "buy_amount": invoice["total"],
                "paid_amount": _direct_paid,
                "quantity": None,
                "unit": None,
                "product": None,
                "unit_price": None,
                "invoice_items": invoice["items"],
                "total": invoice["total"],
                "due_date": None
            }

    if has_direct_sale:
        # Re-run detail extraction on the suffix-stripped text when applicable.
        _amt_pat = r"\d[\d,\.]*\s*(?:[kK](?![a-zA-Z])|[mM](?![a-zA-Z]))?"
        _pay_sfx2 = re.search(
            rf"(?:"
            rf"\s+and\s+(?:received?|recieved?|got\s+(?:the\s+)?(?:paid|payment)|collected?)\s+"
            rf"(?:the\s+)?(?:payment\s+of\s+|cash\s+of\s+)?"
            rf"|(?:\s+(?:and\s+)?(?:each\s+)?paid\s+)"
            rf")(?P<paid_sfx>{_amt_pat})\s*$",
            clean_text, re.I,
        )
        if not _pay_sfx2:
            _pay_sfx2 = re.search(
                rf"(?:\s+and)?\s+(?P<paid_sfx>{_amt_pat})\s+paid\s*$",
                clean_text, re.I,
            )
        _resolved_paid = 0
        _resolved_sale_details = direct_sale_details
        if _pay_sfx2:
            _resolved_paid = parse_amount_token(_pay_sfx2.group("paid_sfx")) or 0
            _resolved_sale_details = extract_direct_sale_details(
                text[:_pay_sfx2.start()].strip()
            )

        if not _resolved_sale_details:
            return None

        return {
            "type": "TRANSACTION",
            "name": "",
            "action": "SALE",
            "buy_amount": _resolved_sale_details["total"],
            "paid_amount": _resolved_paid,
            "quantity": _resolved_sale_details["quantity"],
            "unit": _resolved_sale_details["unit"],
            "product": _resolved_sale_details["product"],
            "unit_price": _resolved_sale_details["unit_price"],
            "invoice_items": None,
            "total": _resolved_sale_details["total"],
            "due_date": None
        }

    customer_invoice_match = re.match(
        r"(?P<name>.+?)\s+(?:bought|buy|purchase|purchased|collect|collected|took|take|carry|carried)\s+(?P<items>.+)",
        invoice_clean_text
    )
    if customer_invoice_match and has_pay:
        payment_split = re.search(
            r"\b(?:paid|pay|settle|settled|clear|cleared|gave|give|send|sent|transfer|transferred|transfered|deposit|deposited|contribute|contributed|contribution|contributions|save|saved|thrift|ajo|esusu)\b(?P<payment>.+)$",
            customer_invoice_match.group("items")
        )
        if payment_split:
            items_text = customer_invoice_match.group("items")[:payment_split.start()].strip()
            items_text = re.sub(r"[\s,;]+$", "", items_text).strip()
            payment_amounts = extract_amounts(payment_split.group("payment"))
            invoice = parse_invoice_items(items_text)
            # Single-item transactions (no comma) return None from parse_invoice_items.
            # Fall back to the singular parser so "a bag of feed at 15000 paid 10000"
            # doesn't leak into extract_item_details and produce a fantasy total.
            if not invoice:
                _single = parse_invoice_item(items_text)
                if _single:
                    invoice = {"items": [_single], "total": _single["total"]}
            if invoice and payment_amounts:
                return {
                    "type": "TRANSACTION",
                    "name": customer_invoice_match.group("name").strip(),
                    "action": "COMBINED",
                    "buy_amount": invoice["total"],
                    "paid_amount": payment_amounts[0],
                    "quantity": None,
                    "unit": None,
                    "product": None,
                    "unit_price": None,
                    "invoice_items": invoice["items"],
                    "total": invoice["total"],
                    "due_date": due_date
                }

    if customer_invoice_match and not has_pay:
        invoice = parse_invoice_items(customer_invoice_match.group("items"))
        if invoice:
            return {
                "type": "TRANSACTION",
                "name": customer_invoice_match.group("name").strip(),
                "action": "BUY",
                "buy_amount": invoice["total"],
                "paid_amount": 0,
                "quantity": None,
                "unit": None,
                "product": None,
                "unit_price": None,
                "invoice_items": invoice["items"],
                "total": invoice["total"],
                "due_date": due_date
            }

    # =========================
    # 🔄 COMBINED
    # =========================

    if has_buy and has_pay:

        if item_details and len(amounts) >= 2:
            buy_amount = item_details["total"]
            quantity = item_details["quantity"]
            unit = item_details["unit"]
            product = item_details["product"]
            unit_price = item_details["unit_price"]
            total = item_details["total"]
            paid_amount = amounts[-1]
        elif len(amounts) == 1:
            # "Bayowa buy one basket of mangoes and paid 60000"
            # Single amount with buy+paid: ambiguous — could be full price (fully paid) OR a part payment.
            # Flag for the handler to resolve via stock lookup. If not in stock, ask for clarification.
            buy_amount = None   # unknown until stock lookup
            paid_amount = amounts[0]
            total = None
            if item_details:
                quantity = item_details.get("quantity")
                unit = item_details.get("unit")
                product = item_details.get("product")
                unit_price = item_details.get("unit_price")
        elif not amounts:
            return None
        else:
            buy_amount = amounts[0]
            paid_amount = amounts[1]

        action = "COMBINED"

    # =========================
    # 🛒 BUY
    # =========================

    elif has_buy:

        if item_details:
            buy_amount = item_details["total"]
            quantity = item_details["quantity"]
            unit = item_details["unit"]
            product = item_details["product"]
            unit_price = item_details["unit_price"]
            total = item_details["total"]
        else:
            buy_amount = amounts[0]
            total = buy_amount

        action = "BUY"

    # =========================
    # 💵 PAY
    # =========================

    elif has_pay:

        if not amounts:
            return None

        paid_amount = amounts[0]

        action = "PAY"

    else:
        return None

    # =========================
    # 👤 CUSTOMER NAME
    # =========================

    words = text.split()

    action_index = None

    for i, word in enumerate(words):
        normalized_word = re.sub(r"[^a-zA-Z]", "", word).lower()

        if normalized_word in NAME_SPLIT_KEYWORDS:

            action_index = i

            break

    if action_index is None:
        return None

    name = " ".join(
        words[:action_index]
    ).lower()
    name = re.sub(r"\b(?:is|was)\s*$", "", name).strip()

    if name.strip() == "":
        return None

    stock_price_needed = (
        action == "COMBINED"
        and buy_amount is None
        and product is not None
    )

    return {
        "type": "TRANSACTION",
        "name": name,
        "action": action,
        "buy_amount": buy_amount,
        "paid_amount": paid_amount,
        "quantity": quantity,
        "unit": unit,
        "product": product,
        "unit_price": unit_price,
        "invoice_items": None,
        "total": total if total is not None else buy_amount,
        "due_date": due_date,
        "stock_price_needed": stock_price_needed,
    }


# =========================
# 💰 BALANCE
# =========================

def _parse_service_items(items_text):
    """
    Parse a comma-separated item list. Supported formats per item:
      "10 shirts"          — qty first, name second
      "shirts 10"          — name first, qty last
      "1. Native 3"        — numbered list prefix (1./2. etc.) then name then qty
      "shirts"             — name only, defaults to qty=1
    Returns list of {"qty": int, "name": str}.
    """
    parts = re.split(r",\s*|\s+and\s+(?=\d)", items_text.strip())
    results = []
    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Strip numbered list prefix: "1." / "2)" / "(3)"
        part = re.sub(r"^\d+[.)]\s*", "", part).strip()
        if not part:
            continue

        # Format 1: qty first — "10 shirts"
        m = re.match(r"^(\d+)\s+(.+)$", part)
        if m:
            qty = int(m.group(1))
            name = m.group(2).strip().lower()
            name = re.sub(r"\s+for\s+\w+(?:\s+\w+)?$", "", name).strip()
            if name:
                results.append({"qty": qty, "name": name})
            continue

        # Format 2: name first, qty last — "shirts 10" or "native 3"
        m2 = re.match(r"^(.+?)\s+(\d+)$", part)
        if m2:
            name = m2.group(1).strip().lower()
            qty = int(m2.group(2))
            name = re.sub(r"\s+for\s+\w+(?:\s+\w+)?$", "", name).strip()
            if name:
                results.append({"qty": qty, "name": name})
            continue

        # Format 3: name only — "shirts" → qty=1
        name = part.strip().lower()
        name = re.sub(r"\s+for\s+\w+(?:\s+\w+)?$", "", name).strip()
        if name and not name.isdigit():
            results.append({"qty": 1, "name": name})

    return results


def _parse_stock_item_full(body):
    """
    Parse the combined qty + prices format (one item only):
      honey 10 liters at 10,000, selling price 12,000
      10 liters honey at 10000 selling price 12000
      garri 50 bags cost 4000 selling at 5000
      dangote 70g spaghetti cost at 400 selling at 430
    Returns {"product", "unit", "quantity", "cost", "sell"} or None.
    """
    # Normalise body: strip leading "and" before selling/sell keywords
    body = re.sub(r"\band\s+(?=selling|sell\b)", "", body.strip(), flags=re.I)
    # Match sell price — handles "selling price", "selling at", "sell at", "sell"
    selling_split = re.split(r"\bselling\s+(?:price\s+)?(?:at\s+)?|(?<!\w)sell\s+(?:at\s+)?", body, maxsplit=1, flags=re.I)
    if len(selling_split) != 2:
        return None

    sell = parse_amount_token(selling_split[1].strip().replace(",", ""))
    if sell is None:
        return None

    left = selling_split[0].strip().rstrip(",").strip()

    # Try "cost [at] N" then "at N" (honey 10 liters at 10000, selling price 12000)
    cost_split = re.split(r"\s+cost\s+(?:at\s+)?", left, maxsplit=1, flags=re.I)
    if len(cost_split) == 2:
        cost_str = cost_split[1].strip()
        item_part = cost_split[0].strip()
    else:
        at_split = re.split(r"\s+at\s+", left, maxsplit=1, flags=re.I)
        if len(at_split) == 2:
            cost_str = at_split[1].strip()
            item_part = at_split[0].strip()
        else:
            return None

    cost = parse_amount_token(cost_str.replace(",", ""))
    if cost is None:
        return None

    _qty_tok = r"\d[\d,\.]*(?:[kKmM](?![a-zA-Z]))?"
    pat_product_first = re.compile(
        rf"^(?P<product>.+?)\s+(?P<qty>{_qty_tok})\s*(?P<unit>{UNIT_PATTERN})$", re.I
    )
    pat_qty_first = re.compile(
        rf"^(?P<qty>{_qty_tok})\s*(?P<unit>{UNIT_PATTERN})\s+(?P<product>.+)$", re.I
    )

    for pat in (pat_product_first, pat_qty_first):
        m = pat.match(item_part)
        if m:
            qty = parse_quantity_token(m.group("qty")) or 1
            if qty < 1:
                continue
            product, unit = normalize_item(m.group("product").strip(), m.group("unit"))
            return {"product": product, "unit": unit, "quantity": qty, "cost": cost, "sell": sell}

    return None


def _parse_stock_items_with_prices(body):
    """
    Parse one or more comma/newline-separated stock items that include
    cost and sell prices.

    Accepted format per item:
        <product name> cost <amount> sell <amount>
    Example:
        dangote salt 50g cost 150 sell 200
        paracetamol 500mg cost 120 sell 180
    """
    amount_pat = r"\d[\d,\.]*(?:k|m)?"
    item_pat = re.compile(
        rf"^(?P<product>.+?)\s+cost\s+(?:at\s+)?(?P<cost>{amount_pat})\s+(?:selling\s+(?:price\s+)?(?:at\s+)?|sell\s+(?:at\s+)?)(?P<sell>{amount_pat})$",
        re.I,
    )
    parts = [p.strip() for p in re.split(r"[,\n]+", body) if p.strip()]
    items = []
    _lead_qty_pat = re.compile(
        rf"^(?P<lqty>\d[\d,\.]*)\s+(?P<lunit>{UNIT_PATTERN})\s+(?P<lproduct>.+)$", re.I
    )
    for part in parts:
        m = item_pat.match(part.strip())
        if not m:
            return None  # one bad item → fall back to STOCK_ADD
        cost = parse_amount_token(m.group("cost").replace(",", ""))
        sell = parse_amount_token(m.group("sell").replace(",", ""))
        if cost is None or sell is None:
            return None
        raw_product = m.group("product").strip()
        # Extract leading qty+unit if present: "10 bags rice" → qty=10, product="rice"
        lm = _lead_qty_pat.match(raw_product)
        if lm:
            quantity = parse_quantity_token(lm.group("lqty"))
            product, unit = normalize_item(lm.group("lproduct").strip(), lm.group("lunit"))
        else:
            quantity = None
            product, unit = normalize_item(raw_product)
        items.append({"product": product, "unit": unit, "quantity": quantity, "cost": cost, "sell": sell})
    return items if items else None


SELECT_PRODUCT_COMMANDS = {
    "select product",
    "select products",
    "sell product",
    "sell products",
    "sell",
    "product",
    "products",
}
