import json
import os
import re
import requests

from datetime import datetime, timedelta

from sqlalchemy import func

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from models import Customer, Transaction, TransactionItem

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


def normalize_phone(phone_str):
    """Converts local Nigerian numbers to international format for Meta API."""
    if not phone_str:
        return None
    clean = re.sub(r"\D", "", phone_str)
    if clean.startswith("0") and len(clean) == 11:
        return "234" + clean[1:]
    return clean


def extract_item_details(text):
    # Matches numbers with optional k/m suffixes (e.g., 5000, 5k, 5.5m)
    amount_pattern = r"\d[\d,\.]*\s*[kKmM]?"

    clean = text.lower().replace(",", "")

    match = re.search(
        r"(?P<quantity>\d+)\s*"
        r"(?P<container>[a-z/]+)\s+of\s+"
        r"(?P<product>[a-z ]+?)\s+(?:at|for)\s+(?P<unit_price>" + amount_pattern + ")",
        clean
    )
    compact_unit_match = None
    if not match:
        compact_unit_match = re.search(
            r"(?P<quantity>\d+)\s*"
            r"(?P<unit>kg|g|ml|l)\s+(?:of\s+)?"
            r"(?P<product>[a-z ]+?)\s+(?:at|for)\s+(?P<unit_price>" + amount_pattern + ")",
            clean
        )
    no_of_match = None
    if not match and not compact_unit_match:
        no_of_match = re.search(
            r"(?P<quantity>\d+)\s*"
            r"(?P<product>[a-z/]+(?:\s+[a-z/]+){0,3})\s+"
            r"(?:at|for)\s+(?P<unit_price>" + amount_pattern + ")",
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
    unit_price = parse_amount_token(active_match.group("unit_price")) or 0
    total = quantity * unit_price

    return {
        "quantity": quantity,
        "unit": unit,
        "product": product,
        "unit_price": unit_price,
        "total": total
    }


def extract_direct_sale_details(text):
    clean = text.lower().replace(",", "").strip()
    clean = re.sub(r"^(?:i\s+)?(?:sold|sell|supply|supplied|deliver|delivered)\s+", "", clean).strip()
    clean = re.sub(r"\b(each|per\s+unit|per\s+piece)\b", "", clean).strip()

    amount_matches = list(re.finditer(
        r"(?<![\d/])\d[\d,\.]*\s*(?:[kK](?![a-zA-Z])|[mM](?![a-zA-Z]))?(?![a-zA-Z\d/])",
        clean
    ))
    if not amount_matches:
        return None

    amount_match = amount_matches[-1]
    unit_price = parse_amount_token(amount_match.group())
    if unit_price is None:
        return None

    item_text = clean[:amount_match.start()].strip()
    item_text = re.sub(r"\b(for|at)\s*$", "", item_text).strip()
    if not item_text:
        return None

    quantity = 1
    unit = None
    product = item_text

    quantity_match = re.match(r"(?P<quantity>\d+)\s+(?P<rest>.+)$", item_text)
    if quantity_match:
        quantity = int(quantity_match.group("quantity"))
        rest = quantity_match.group("rest").strip()
        rest = re.sub(r"\s+of\s+", " ", rest, count=1)

        unit_phrases = [
            "truck loads",
            "truck load",
            "trucks",
            "truck",
            "bags",
            "bag",
            "cartons",
            "carton",
            "pieces",
            "piece",
            "units",
            "unit",
            "loads",
            "load",
            "tons",
            "ton",
            "litres",
            "litre",
            "liters",
            "liter",
            "crates",
            "crate",
            "dozens",
            "dozen",
            "rolls",
            "roll",
            "kg",
            "g",
            "ml",
            "l",
        ]
        for unit_phrase in unit_phrases:
            if rest == unit_phrase or rest.startswith(f"{unit_phrase} "):
                unit = unit_phrase
                product = rest[len(unit_phrase):].strip()
                break

        if unit is None:
            product = rest

    product = product.strip()
    if not product:
        return None

    total = quantity * unit_price
    return {
        "quantity": quantity,
        "unit": unit,
        "product": product,
        "unit_price": unit_price,
        "total": total
    }


def extract_due_date_from_text(text):
    clean_text = text.lower()
    today_phrases = [
        "due today",
        "pay today",
        "balance today",
        "will pay today",
        "will balance today"
    ]
    tomorrow_phrases = [
        "due tomorrow",
        "due tommorrow",
        "pay tomorrow",
        "pay tommorrow",
        "balance tomorrow",
        "balance tommorrow",
        "will pay tomorrow",
        "will pay tommorrow",
        "will balance tomorrow",
        "will balance tommorrow"
    ]

    if any(phrase in clean_text for phrase in today_phrases):
        return datetime.utcnow()

    if any(phrase in clean_text for phrase in tomorrow_phrases):
        return datetime.utcnow() + timedelta(days=1)

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
    clean = item_text.lower().replace(",", "").strip()
    clean = re.sub(r"\b(each|per\s+unit|per\s+piece)\b", "", clean).strip()

    amount_matches = list(re.finditer(
        r"(?<![\d/])\d[\d,\.]*\s*(?:[kK](?![a-zA-Z])|[mM](?![a-zA-Z]))?(?![a-zA-Z\d/])",
        clean
    ))
    if not amount_matches:
        return None

    amount_match = amount_matches[-1]
    unit_price = parse_amount_token(amount_match.group())
    if unit_price is None:
        return None

    item_body = clean[:amount_match.start()].strip()
    item_body = re.sub(r"\b(for|at)\s*$", "", item_body).strip()
    if not item_body:
        return None

    quantity = 1
    unit = None
    product = item_body

    quantity_match = re.match(r"(?P<quantity>\d+)\s+(?P<rest>.+)$", item_body)
    if quantity_match:
        quantity = int(quantity_match.group("quantity"))
        rest = re.sub(r"\s+of\s+", " ", quantity_match.group("rest").strip(), count=1)

        unit_phrases = [
            "truck loads", "truck load", "bags", "bag", "cartons", "carton",
            "pieces", "piece", "units", "unit", "loads", "load", "tons", "ton",
            "litres", "litre", "liters", "liter", "crates", "crate",
            "dozens", "dozen", "rolls", "roll", "kg", "g", "ml", "l"
        ]
        for unit_phrase in unit_phrases:
            if rest == unit_phrase or rest.startswith(f"{unit_phrase} "):
                unit = unit_phrase
                product = rest[len(unit_phrase):].strip()
                break

        if unit is None:
            product = rest

    product = product.strip()
    if not product:
        return None

    total = quantity * unit_price
    return {
        "product": product,
        "quantity": quantity,
        "unit": unit,
        "unit_price": unit_price,
        "total": total
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


def extract_amounts(text):
    # Improved regex to identify amounts with k/m suffixes.
    # Uses negative lookahead to ensure k/m aren't part of a larger unit word (like kg, ml, etc.)
    # or immediately followed by other letters that suggest a unit context (like meter).
    unit_pattern = r"kg|g|gram|grams|bag|bags|carton|cartons|unit|units|pcs|piece|pieces|litre|litres|liter|liters|l|ml|ton|tons"
    amount_text = re.sub(rf"\b\d+\s*(?:{unit_pattern})\b", "", text, flags=re.IGNORECASE)
    matches = re.findall(
        r"(?<![\d/])\d[\d,\.]*\s*(?:[kK](?![a-zA-Z])|[mM](?![a-zA-Z]))?(?![a-zA-Z\d/])",
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
    unit_pattern = (
        r"truck loads?|bags?|cartons?|crates?|pieces?|units?|loads?|tons?|"
        r"litres?|liters?|dozens?|rolls?|kg|g|ml|l"
    )
    quantity_match = re.match(
        rf"(?P<quantity>\d+)\s*(?P<unit>{unit_pattern})?\s*(?:of\s+)?(?P<product>.*)$",
        clean
    )
    if quantity_match:
        quantity = int(quantity_match.group("quantity"))
        unit = quantity_match.group("unit")
        product = quantity_match.group("product").strip()
        if not product:
            product = unit or "stock item"
            unit = None
        return {
            "quantity": quantity,
            "unit": unit,
            "product": product
        }

    return {
        "quantity": 1,
        "unit": None,
        "product": clean
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
            rf"(?P<supplier>[a-zA-Z'Ã¢â‚¬â„¢\- ]+?)\s+(?:at|for)\s+"
            rf"(?P<price>{amount_pattern})(?:\s+each)?",
            clean
        ),
        re.search(
            rf"^(?P<supplier>[a-zA-Z'Ã¢â‚¬â„¢\- ]+?)\s+(?:supply|supplied|deliver|delivered)\s+me\s+"
            rf"(?P<body>.+?)\s+(?:at|for)\s+(?P<price>{amount_pattern})(?:\s+each)?",
            clean
        )
    ]
    for purchase_match in purchase_patterns:
        if not purchase_match:
            continue
        price = parse_amount_token(purchase_match.group("price"))
        if price is None:
            return None
        item = parse_stock_item_body(purchase_match.group("body"))
        quantity = item["quantity"]
        total = quantity * price
        paid_amount = 0
        paid_match = re.search(
            rf"\b(?:paid|pay|sent|send|transfer(?:red|ed)?|deposit(?:ed)?)\s+(?P<paid>{amount_pattern})",
            clean
        )
        if paid_match:
            paid_amount = parse_amount_token(paid_match.group("paid")) or 0
        return {
            "type": "SUPPLIER_TRANSACTION",
            "action": "SUPPLIER_PURCHASE",
            "name": purchase_match.group("supplier").strip(),
            "product": item["product"],
            "quantity": quantity,
            "unit": item["unit"],
            "unit_price": price,
            "buy_amount": total,
            "paid_amount": paid_amount,
            "total": total,
            "due_date": due_date
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


def get_customer_period_range(period, target_date=None):
    now = datetime.utcnow()
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

    msg = (
        f"{customer.name.title()} Account Summary\n"
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
            msg += f"{tx_date} - {tx.type}: ₦{tx.amount:,}\n"

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

    if clean_text in ["formats", "format", "f"]:
        return {"type": "FORMATS"}

    if clean_text in ["stock", "my stock", "inventory", "my inventory"]:
        return {"type": "INVENTORY_LIST"}

    if clean_text in ["suppliers", "my suppliers", "supplier debts", "suppliers i owe"]:
        return {"type": "SUPPLIER_LIST"}

    if clean_text in ["supplier due", "suppliers due", "supplier due today", "suppliers due today"]:
        return {"type": "SUPPLIER_DUE"}

    if clean_text.startswith("stock "):
        return {
            "type": "INVENTORY_ITEM",
            "product": clean_text.replace("stock", "", 1).strip()
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
        "unpaid debtors",
        "unpaid",
        "debtor",
        "debtors"
    ]:
        return {
            "type": "UNPAID_DEBTORS"
        }

    if clean_text in [
        "overdue debtors",
        "overdue",
        "over due"
    ]:
        return {
            "type": "OVERDUE_DEBTORS"
        }

    if clean_text == "due" or clean_text in [
        "notify due customer",
        "notify due customers",
        "notify due",
        "send due reminders"
    ]:
        return {
            "type": "DUE_MENU"
        }

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

    # Matches "list customers", "my customers", "customer list this week", etc.
    customer_list_phrases = [
        "list customers",
        "list customer",
        "list my customers",
        "list my customer",
        "list of customers",
        "customer list",
        "my customers",
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
        r"^approve\s+sub(?:scription)?\s+(\+?[\d ]{7,15})$",
        clean_text
    )
    if approve_match:
        return {
            "type": "APPROVE_SUBSCRIPTION",
            "phone": normalize_phone(approve_match.group(1))
        }

    reject_match = re.search(
        r"^reject\s+sub(?:scription)?\s+(\+?[\d ]{7,15})$",
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
        # Matches "add staff 080... Name" (allows spaces in phone)
        match = re.search(r"add staff (\+?[\d ]{7,15}) (.+)", clean_text)
        if match:
            return {
                "type": "ADD_STAFF",
                "phone": normalize_phone(match.group(1)),
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

    if clean_text in [
        "reonboard",
        "change name",
        "update name",
        "update business name"
    ]:
        return {"type": "REONBOARD"}

    if clean_text in [
        "formats",
        "format",
        "f"
    ]:
        return {
            "type": "FORMATS"
        }

    if clean_text.startswith("remind"):
        return {
            "type": "REMIND",
            "text": text
        }

    supplier_transaction = extract_supplier_transaction(text)
    if supplier_transaction:
        return supplier_transaction

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
    clean_text = text.replace(",", "")

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
    today_phrases = [
        "due today",
        "pay today",
        "balance today",
        "will pay today",
        "will balance today"
    ]

    tomorrow_phrases = [
        "due tomorrow",
        "due tommorrow",
        "pay tomorrow",
        "pay tommorrow",
        "balance tomorrow",
        "balance tommorrow",
        "will pay tomorrow",
        "will pay tommorrow",
        "will balance tomorrow",
        "will balance tommorrow"
    ]
    
    date_match = None
    
    if any(
        phrase in clean_text 
        for phrase in today_phrases):
            
        due_date = datetime.utcnow()

    elif any(
        phrase in clean_text
        for phrase in tomorrow_phrases):
            
        due_date = (
            datetime.utcnow() 
            + timedelta(days=1)
        )

    else:
         due_date = None

         date_match = re.search(
              r'(\d{1,2}/\d{1,2}/\d{2,4})',
              clean_text
         )

    if due_date is None and date_match:

        try:

            date_text = date_match.group(1)
            date_format = "%d/%m/%y" if len(date_text.rsplit("/", 1)[-1]) == 2 else "%d/%m/%Y"
            due_date = datetime.strptime(date_text, date_format)

        except:
            return None

    due_clause_pattern = (
        r"\s*(?:,?\s+and)?\s+"
        r"(?:due\s+to\s+pay|due|will\s+pay|pay|balance|will\s+balance)"
        r"\s+\d{1,2}/\d{1,2}/\d{2,4}\b"
    )
    invoice_clean_text = re.sub(due_clause_pattern, "", invoice_clean_text).strip()
    clean_text = re.sub(due_clause_pattern, "", clean_text, flags=re.IGNORECASE).strip()

    # =========================
    # 🧠 DETECT TYPE
    # =========================

    buy_keywords = [
        "bought", "buy", "purchase", "purchased", "collect", "collected",
        "took", "take", "carry", "carried", "owes", "owe", "owing"
    ]
    pay_keywords = [
        "paid", "pay", "settle", "settled", "clear", "cleared",
        "gave", "give", "send", "sent", "transfer", "transferred",
        "transfered", "deposit", "deposited", "contribute", "contributed",
        "contribution", "contributions", "save", "saved", "thrift", "ajo", "esusu"
    ]
    sale_keywords = ["sold", "sell", "supply", "supplied", "deliver", "delivered"]

    lowered_clean_text = clean_text.lower()
    has_buy = bool(re.search(r"\b(" + "|".join(buy_keywords) + r")\b", lowered_clean_text))
    has_pay = bool(re.search(r"\b(" + "|".join(pay_keywords) + r")\b", lowered_clean_text))
    has_direct_sale = bool(re.match(r"^(?:i\s+)?(" + "|".join(sale_keywords) + r")\b", clean_text.lower()))

    if has_direct_sale:
        sale_body = re.sub(
            r"^(?:i\s+)?(?:sold|sell|supply|supplied|deliver|delivered)\s+",
            "",
            invoice_clean_text,
            count=1
        ).strip()
        invoice = parse_invoice_items(sale_body)
        if invoice:
            return {
                "type": "TRANSACTION",
                "name": "",
                "action": "SALE",
                "buy_amount": invoice["total"],
                "paid_amount": 0,
                "quantity": None,
                "unit": None,
                "product": None,
                "unit_price": None,
                "invoice_items": invoice["items"],
                "total": invoice["total"],
                "due_date": None
            }

    if has_direct_sale:
        if not direct_sale_details:
            return None

        return {
            "type": "TRANSACTION",
            "name": "",
            "action": "SALE",
            "buy_amount": direct_sale_details["total"],
            "paid_amount": 0,
            "quantity": direct_sale_details["quantity"],
            "unit": direct_sale_details["unit"],
            "product": direct_sale_details["product"],
            "unit_price": direct_sale_details["unit_price"],
            "invoice_items": None,
            "total": direct_sale_details["total"],
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
        elif len(amounts) < 2:
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

        if normalized_word in [
            "bought",
            "buy",
            "purchase",
            "purchased",
            "collect",
            "collected",
            "took",
            "take",
            "carry",
            "carried",
            "owes",
            "owe",
            "owing",
            "paid",
            "pay",
            "settle",
            "settled",
            "clear",
            "cleared",
            "gave",
            "give",
            "send",
            "sent",
            "transfer",
            "transferred",
            "transfered",
            "deposit",
            "deposited",
            "contribute",
            "contributed",
            "contribution",
            "contributions",
            "save",
            "saved",
            "thrift",
            "ajo",
            "esusu"
        ]:

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
        "due_date": due_date
    }


# =========================
# 💰 BALANCE
# =========================

