import os
import re
import json
import requests
import traceback
import uuid

from datetime import datetime, timedelta
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from sqlalchemy import (
    create_engine,
    Column,
    Boolean,
    Integer,
    String,
    DateTime,
    ForeignKey,
    func,
    or_,
    inspect,
    text
)

from sqlalchemy.orm import (
    sessionmaker,
    declarative_base
)

# =========================
# 🔐 ENV CONFIG
# =========================

if load_dotenv:
    load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set")

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()

app = FastAPI()

# =========================
# 🧱 MODELS
# =========================

class Customer(Base):

    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, autoincrement=True)

    name = Column(String)

    owner_phone = Column(String)

    customer_phone = Column(String, nullable=True)

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


class User(Base):

    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    name = Column(String)

    phone = Column(String, unique=True)

    role = Column(String, default="user")

    parent_id = Column(String, ForeignKey("users.id"), nullable=True)

    can_view_all_transactions = Column(Boolean, default=False)

    subscription_plan = Column(String, default="BASIC")

    subscription_status = Column(String, default="ACTIVE")

    subscription_expires_at = Column(DateTime, nullable=True)

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


class Transaction(Base):

    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)

    customer_id = Column(
        Integer,
        ForeignKey("customers.id"),
        nullable=True
    )

    type = Column(String)

    amount = Column(Integer)

    product = Column(String, nullable=True)

    quantity = Column(Integer, nullable=True)

    unit = Column(String, nullable=True)

    unit_price = Column(Integer, nullable=True)

    recorded_by_id = Column(String, ForeignKey("users.id"), nullable=True)

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    due_date = Column(
        DateTime,
        nullable=True
    )

    message_id = Column(
        String,
        unique=True
    )


class TransactionItem(Base):

    __tablename__ = "transaction_items"

    id = Column(Integer, primary_key=True, autoincrement=True)

    transaction_id = Column(Integer, ForeignKey("transactions.id"))

    product = Column(String)

    quantity = Column(Integer, default=1)

    unit = Column(String, nullable=True)

    unit_price = Column(Integer)

    total = Column(Integer)

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


class TransactionNote(Base):

    __tablename__ = "transaction_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)

    transaction_id = Column(Integer, ForeignKey("transactions.id"))

    author_user_id = Column(String, ForeignKey("users.id"))

    note = Column(String)

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


class SubscriptionPayment(Base):

    __tablename__ = "subscription_payments"

    id = Column(Integer, primary_key=True, autoincrement=True)

    user_id = Column(String, ForeignKey("users.id"))

    phone = Column(String)

    plan = Column(String)

    amount = Column(Integer)

    status = Column(String, default="PENDING")

    payment_method = Column(String, default="BANK_TRANSFER")

    evidence_type = Column(String, nullable=True)

    evidence_ref = Column(String, nullable=True)

    admin_note = Column(String, nullable=True)

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    approved_at = Column(DateTime, nullable=True)

    approved_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)


class AppAdminRole(Base):

    __tablename__ = "app_admin_roles"

    id = Column(Integer, primary_key=True, autoincrement=True)

    phone = Column(String)

    role = Column(String)

    is_active = Column(Boolean, default=True)

    created_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)

    deactivated_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    deactivated_at = Column(DateTime, nullable=True)


class PendingAction(Base):

    __tablename__ = "pending_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)

    phone = Column(String)

    customer_name = Column(String)

    customer_phone = Column(String, nullable=True)

    action = Column(String)

    reminder_id = Column(Integer, nullable=True)

    buy_amount = Column(
        Integer,
        default=0
    )

    paid_amount = Column(
        Integer,
        default=0
    )

    product = Column(String, nullable=True)

    quantity = Column(Integer, nullable=True)

    unit = Column(String, nullable=True)

    unit_price = Column(Integer, nullable=True)

    items_json = Column(String, nullable=True)

    last_customer = Column(String)

    due_date = Column(
        DateTime,
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


class ProcessedMessage(Base):

    __tablename__ = "processed_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)

    message_id = Column(String, unique=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class CustomerMemory(Base):

    __tablename__ = "customer_memory"

    id = Column(Integer, primary_key=True, autoincrement=True)

    phone = Column(
        String,
        unique=True
    )

    last_customer = Column(String)


class ReminderMemory(Base):

    __tablename__ = "reminder_memory"

    id = Column(Integer, primary_key=True, autoincrement=True)

    phone = Column(String)

    customer_id = Column(Integer, nullable=True)

    customer_name = Column(String)

    customer_phone = Column(String, nullable=True)

    balance = Column(Integer)

    due_date = Column(DateTime)

    reminder_type = Column(String)


class UserCreate(BaseModel):
    name: str
    phone: str
    role: Optional[str] = "user"


class CustomerCreate(BaseModel):
    owner_phone: str
    name: str
    customer_phone: Optional[str] = None


@app.get("/debug/schema")
def debug_schema(token: str):
    expected_token = os.getenv("WEBHOOK_VERIFY_TOKEN")
    if not expected_token or token != expected_token:
        return {"status": "unauthorized"}

    inspector = inspect(engine)
    models = [
        Customer,
        User,
        Transaction,
        TransactionItem,
        TransactionNote,
        SubscriptionPayment,
        AppAdminRole,
        PendingAction,
        ProcessedMessage,
        CustomerMemory,
        ReminderMemory,
    ]

    result = {}
    for model in models:
        table_name = model.__tablename__
        db_columns = {
            column["name"]: str(column["type"])
            for column in inspector.get_columns(table_name)
        }
        model_columns = {
            column.name: str(column.type)
            for column in model.__table__.columns
        }
        mismatches = {}
        for column_name, model_type in model_columns.items():
            db_type = db_columns.get(column_name)
            if db_type and db_type.lower() != model_type.lower():
                mismatches[column_name] = {
                    "model": model_type,
                    "database": db_type,
                }

        result[table_name] = {
            "model": model_columns,
            "database": db_columns,
            "mismatches": mismatches,
        }

    return result


Base.metadata.create_all(engine)


def ensure_schema_updates():
    inspector = inspect(engine)
    user_columns = {
        column["name"]
        for column in inspector.get_columns("users")
    }

    if "can_view_all_transactions" not in user_columns:
        default_value = "FALSE" if engine.dialect.name == "postgresql" else "0"
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE users "
                    f"ADD COLUMN can_view_all_transactions BOOLEAN DEFAULT {default_value}"
                )
            )

    user_updates = {
        "subscription_plan": "VARCHAR DEFAULT 'BASIC'",
        "subscription_status": "VARCHAR DEFAULT 'ACTIVE'",
        "subscription_expires_at": "TIMESTAMP"
    }
    with engine.begin() as connection:
        for column_name, column_type in user_updates.items():
            if column_name not in user_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE users ADD COLUMN {column_name} {column_type}"
                    )
                )

    pending_columns = {
        column["name"]
        for column in inspector.get_columns("pending_actions")
    }
    pending_updates = {
        "product": "VARCHAR",
        "quantity": "INTEGER",
        "unit": "VARCHAR",
        "unit_price": "INTEGER",
        "items_json": "VARCHAR"
    }
    with engine.begin() as connection:
        for column_name, column_type in pending_updates.items():
            if column_name not in pending_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE pending_actions ADD COLUMN {column_name} {column_type}"
                    )
                )

    if engine.dialect.name == "postgresql":
        transaction_columns = {
            column["name"]: column
            for column in inspector.get_columns("transactions")
        }
        customer_id_column = transaction_columns.get("customer_id")
        if customer_id_column and not customer_id_column.get("nullable", True):
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE transactions ALTER COLUMN customer_id DROP NOT NULL")
                )


ensure_schema_updates()

# =========================
# 📤 WHATSAPP SEND
# =========================

def send_whatsapp_message(to, message):
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print(
            "WhatsApp send skipped: WHATSAPP_TOKEN or PHONE_NUMBER_ID is missing",
            flush=True
        )
        return False

    url = (
        f"https://graph.facebook.com/v18.0/"
        f"{PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": (
            f"Bearer {WHATSAPP_TOKEN}"
        ),
        "Content-Type": "application/json"
    }

    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": message
        }
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=data,
            timeout=15
        )
    except requests.RequestException as exc:
        print("WhatsApp send failed:", repr(exc), flush=True)
        return False

    print("WhatsApp:", response.status_code, response.text, flush=True)
    return response.ok

# =========================
# 🧠 HELPERS
# =========================

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
                "Common words include bought, buy, paid, pay, sold, sell, supply, "
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
        r"(\d+)\s+and\s+(?!(?:paid|pay)\b)([a-z][a-z]*(?:\s+[a-z][a-z]*){0,4}\s+\d+)",
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
        r"(?P<unit>[a-z/]+)\s+(?:of\s+)?"
        r"(?P<product>[a-z ]+?)\s+(?:at|for)\s+(?P<unit_price>" + amount_pattern + ")",
        clean
    )

    if not match:
        return None

    # Parse quantity and unit price safely, supporting k/m suffixes for the price
    quantity = parse_amount_token(match.group("quantity")) or 0
    unit = match.group("unit")
    product = match.group("product").strip()
    unit_price = parse_amount_token(match.group("unit_price")) or 0
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
    clean = re.sub(r"^(?:i\s+)?(?:sold|sell|supply|supplied)\s+", "", clean).strip()
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
    match = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", text)
    return match.group(1) if match else None


def parse_slash_date(text):
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if not match:
        return None

    day, month, year = map(int, match.groups())
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
        return None

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

    if clean_text in ["menu", "help", "start", "hi", "hello"]:
        return {"type": "FORMATS"}

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
        "pay tomorrow",
        "balance tomorrow",
        "will pay tomorrow",
        "will balance tomorrow"
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
              r'(\d{1,2}/\d{1,2}/\d{4})',
              clean_text
         )

    if due_date is None and date_match:

        try:

            due_date = datetime.strptime(
                date_match.group(1),
                "%d/%m/%Y"
            )

        except:
            return None

    # =========================
    # 🧠 DETECT TYPE
    # =========================

    buy_keywords = ["bought", "buy", "owes", "owe", "owing", "purchased"]
    pay_keywords = ["paid", "pay", "settled", "gave"]
    sale_keywords = ["sold", "sell", "supply", "supplied"]

    has_buy = bool(re.search(r"\b(" + "|".join(buy_keywords) + r")\b", clean_text))
    has_pay = bool(re.search(r"\b(" + "|".join(pay_keywords) + r")\b", clean_text))
    has_direct_sale = bool(re.match(r"^(?:i\s+)?(" + "|".join(sale_keywords) + r")\b", clean_text.lower()))

    if has_direct_sale:
        sale_body = re.sub(
            r"^(?:i\s+)?(?:sold|sell|supply|supplied)\s+",
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
        r"(?P<name>.+?)\s+(?:bought|buy|purchased)\s+(?P<items>.+)",
        invoice_clean_text
    )
    if customer_invoice_match and has_pay:
        payment_split = re.search(
            r"\b(?:paid|pay|settled|gave)\b(?P<payment>.+)$",
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

        if word in [
            "bought",
            "buy",
            "paid",
            "pay"
        ]:

            action_index = i

            break

    if action_index is None:
        return None

    name = " ".join(
        words[:action_index]
    ).lower()

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

def is_staff_user(user):
    return bool(user and user.role == "delegate" and user.parent_id)


def can_view_all_business_transactions(user):
    if not user:
        return False
    if user.role == "user" and not user.parent_id:
        return True
    return is_staff_user(user) and bool(user.can_view_all_transactions)


def visibility_recorded_by_id(user):
    if is_staff_user(user) and not can_view_all_business_transactions(user):
        return user.id
    return None


PLAN_BASIC = "BASIC"
PLAN_GO = "GO"
PLAN_PRO = "PRO"

PLAN_ORDER = {
    PLAN_BASIC: 1,
    PLAN_GO: 2,
    PLAN_PRO: 3
}

PLAN_LIMITS = {
    PLAN_BASIC: {
        "customers": 50,
        "monthly_transactions": 100,
        "staff": 0
    },
    PLAN_GO: {
        "customers": None,
        "monthly_transactions": None,
        "staff": 0
    },
    PLAN_PRO: {
        "customers": None,
        "monthly_transactions": None,
        "staff": 10
    }
}

FEATURE_MIN_PLAN = {
    "DIRECT_SALE": PLAN_GO,
    "INVOICE": PLAN_GO,
    "TRANSACTION_NOTES": PLAN_GO,
    "ADVANCED_REPORTS": PLAN_GO,
    "DUE_REMINDERS": PLAN_GO,
    "STAFF": PLAN_PRO,
    "STAFF_PERMISSION": PLAN_PRO,
    "VOICE_TEXT": PLAN_GO,
    "MULTILINGUAL_VOICE": PLAN_PRO,
    "VOICE_REPLY": PLAN_PRO
}


def normalize_plan(plan):
    plan = (plan or PLAN_BASIC).upper().strip()
    if plan in PLAN_ORDER:
        return plan
    return PLAN_BASIC


def get_business_owner_user(db, user):
    if not user:
        return None
    if user.parent_id:
        owner = db.query(User).filter(User.id == user.parent_id).first()
        if owner:
            return owner
    return user


def get_business_subscription(db, user):
    owner = get_business_owner_user(db, user)
    plan = normalize_plan(getattr(owner, "subscription_plan", PLAN_BASIC))
    status = (getattr(owner, "subscription_status", None) or "ACTIVE").upper()
    expires_at = getattr(owner, "subscription_expires_at", None)

    if expires_at and expires_at < datetime.utcnow():
        status = "EXPIRED"

    if status not in ["ACTIVE", "TRIAL"]:
        plan = PLAN_BASIC

    return {
        "owner": owner,
        "plan": plan,
        "status": status,
        "expires_at": expires_at,
        "limits": PLAN_LIMITS[plan]
    }


def plan_allows_feature(plan, feature):
    required_plan = FEATURE_MIN_PLAN.get(feature, PLAN_BASIC)
    return PLAN_ORDER[normalize_plan(plan)] >= PLAN_ORDER[required_plan]


def format_upgrade_message(current_plan, required_plan, feature_label):
    return (
        f"{feature_label} is available on {required_plan}.\n\n"
        f"Your current plan: {normalize_plan(current_plan)}\n\n"
        "Send UPGRADE to see plans."
    )


def ensure_feature_allowed(db, user, feature, feature_label):
    subscription = get_business_subscription(db, user)
    required_plan = FEATURE_MIN_PLAN.get(feature, PLAN_BASIC)
    if plan_allows_feature(subscription["plan"], feature):
        return True, None
    return False, format_upgrade_message(
        subscription["plan"],
        required_plan,
        feature_label
    )


def get_month_start():
    now = datetime.utcnow()
    return datetime(now.year, now.month, 1)


def check_customer_limit(db, owner_phone, subscription):
    limit = subscription["limits"].get("customers")
    if limit is None:
        return True, None

    count = db.query(Customer).filter(
        Customer.owner_phone == owner_phone
    ).count()
    if count < limit:
        return True, None

    return False, (
        f"Basic plan customer limit reached ({limit}).\n\n"
        "Send UPGRADE to move to Go for unlimited customers."
    )


def check_monthly_transaction_limit(db, owner_phone, subscription, planned_rows=1):
    limit = subscription["limits"].get("monthly_transactions")
    if limit is None:
        return True, None

    current_count = get_owner_transaction_query(
        db,
        owner_phone
    ).filter(
        Transaction.created_at >= get_month_start()
    ).count()
    if current_count + planned_rows <= limit:
        return True, None

    return False, (
        f"Basic plan monthly transaction limit reached ({limit}).\n\n"
        "Send UPGRADE to move to Go for unlimited transactions."
    )


def check_staff_limit(db, owner, subscription):
    limit = subscription["limits"].get("staff")
    if limit is None:
        return True, None

    count = db.query(User).filter(User.parent_id == owner.id).count()
    if count < limit:
        return True, None

    return False, (
        f"Your {subscription['plan']} plan allows {limit} staff.\n\n"
        "Send UPGRADE to see team options."
    )


def build_plan_message(subscription):
    plan = subscription["plan"]
    status = subscription["status"]
    expires_at = subscription["expires_at"]
    expiry_line = (
        f"Expires: {expires_at.strftime('%d/%m/%Y')}\n"
        if expires_at else
        "Expires: No expiry set\n"
    )
    limits = subscription["limits"]
    customer_limit = limits["customers"] if limits["customers"] is not None else "Unlimited"
    transaction_limit = limits["monthly_transactions"] if limits["monthly_transactions"] is not None else "Unlimited"
    staff_limit = limits["staff"] if limits["staff"] is not None else "Unlimited"

    return (
        "Your Subscription\n\n"
        f"Plan: {plan}\n"
        f"Status: {status}\n"
        f"{expiry_line}"
        f"Customers: {customer_limit}\n"
        f"Monthly transactions: {transaction_limit}\n"
        f"Staff: {staff_limit}"
    )


def build_upgrade_message():
    go_price = int(os.getenv("PLAN_GO_PRICE", "3000"))
    pro_price = int(os.getenv("PLAN_PRO_PRICE", "7000"))
    return (
        "CreditVoice Plans\n\n"
        "BASIC - Free\n"
        "1 user, 50 customers, 100 monthly transactions, basic debt tracking.\n\n"
        f"1. GO - N{go_price:,}/month\n"
        "For one-owner businesses. Unlimited customers, unlimited transactions, invoices, direct sales, reports, reminders, and notes.\n\n"
        f"2. PRO - N{pro_price:,}/month\n"
        "Everything in Go plus staff, staff permissions, team notes, and future multilingual voice.\n\n"
        "3. View my current plan\n"
        "4. Cancel\n\n"
        "Reply with 1, 2, 3, or 4."
    )


def get_plan_price(plan):
    plan = normalize_plan(plan)
    if plan == PLAN_GO:
        return int(os.getenv("PLAN_GO_PRICE", "3000"))
    if plan == PLAN_PRO:
        return int(os.getenv("PLAN_PRO_PRICE", "7000"))
    return 0


def get_payment_account_message():
    bank = os.getenv("SUBSCRIPTION_BANK_NAME", "your bank")
    account_name = os.getenv("SUBSCRIPTION_ACCOUNT_NAME", "your account name")
    account_number = os.getenv("SUBSCRIPTION_ACCOUNT_NUMBER", "your account number")
    return (
        f"Bank: {bank}\n"
        f"Account Name: {account_name}\n"
        f"Account Number: {account_number}"
    )


def build_plan_payment_message(plan):
    plan = normalize_plan(plan)
    amount = get_plan_price(plan)
    if plan == PLAN_PRO:
        benefits = (
            "Everything in Go plus:\n"
            "- Add staff\n"
            "- Staff permissions\n"
            "- Admin sees staff records\n"
            "- Future Yoruba, Pidgin, and Hausa voice"
        )
    else:
        benefits = (
            "- Unlimited customers\n"
            "- Unlimited transactions\n"
            "- Direct sales\n"
            "- Invoice sales\n"
            "- Product reports\n"
            "- Debt reminders\n"
            "- Transaction notes"
        )

    return (
        f"{plan} Plan - N{amount:,}/month\n\n"
        f"{benefits}\n\n"
        "Pay to:\n"
        f"{get_payment_account_message()}\n\n"
        f"After payment, send:\nPAID {plan}\n\n"
        "Then send your receipt screenshot or payment reference here."
    )


def create_subscription_payment_request(db, user, plan):
    owner = get_business_owner_user(db, user)
    plan = normalize_plan(plan)
    amount = get_plan_price(plan)

    existing = db.query(SubscriptionPayment).filter(
        SubscriptionPayment.user_id == owner.id,
        SubscriptionPayment.status == "PENDING"
    ).order_by(
        SubscriptionPayment.created_at.desc()
    ).first()

    if existing:
        existing.plan = plan
        existing.amount = amount
        existing.phone = owner.phone
        existing.payment_method = "BANK_TRANSFER"
        existing.evidence_type = None
        existing.evidence_ref = None
        existing.created_at = datetime.utcnow()
        return existing

    payment = SubscriptionPayment(
        user_id=owner.id,
        phone=owner.phone,
        plan=plan,
        amount=amount,
        status="PENDING",
        payment_method="BANK_TRANSFER"
    )
    db.add(payment)
    db.flush()
    return payment


def get_pending_subscription_payment(db, user):
    owner = get_business_owner_user(db, user)
    if not owner:
        return None
    return db.query(SubscriptionPayment).filter(
        SubscriptionPayment.user_id == owner.id,
        SubscriptionPayment.status == "PENDING"
    ).order_by(
        SubscriptionPayment.created_at.desc()
    ).first()


def get_media_evidence_ref(message, message_type):
    payload = message.get(message_type) or {}
    return payload.get("id") or message.get("id")


def phone_list_from_env(name):
    return [
        normalize_phone(value.strip())
        for value in os.getenv(name, "").split(",")
        if value.strip()
    ]


def customer_support_phone():
    phone = os.getenv("CUSTOMER_SUPPORT_PHONE", "").strip()
    return normalize_phone(phone) if phone else None


def support_line():
    phone = customer_support_phone()
    return f"\n\nNeed help? Contact support: {phone}" if phone else ""


def subscription_admin_phones():
    return phone_list_from_env("SUBSCRIPTION_ADMIN_PHONES")


def app_admin_phones():
    return phone_list_from_env("APP_ADMIN_PHONES")


ROLE_CUSTOMER_SUPPORT = "CUSTOMER_SUPPORT"
ROLE_SUBSCRIPTION_ADMIN = "SUBSCRIPTION_ADMIN"
ROLE_APP_ADMIN = "APP_ADMIN"


def normalize_admin_role(role):
    role = (role or "").upper().replace(" ", "_").strip()
    aliases = {
        "SUPPORT": ROLE_CUSTOMER_SUPPORT,
        "CUSTOMER_SUPPORT": ROLE_CUSTOMER_SUPPORT,
        "SUBSCRIPTION": ROLE_SUBSCRIPTION_ADMIN,
        "SUBSCRIPTION_ADMIN": ROLE_SUBSCRIPTION_ADMIN,
        "APP": ROLE_APP_ADMIN,
        "APP_ADMIN": ROLE_APP_ADMIN
    }
    return aliases.get(role)


def get_admin_role_override(db, phone, role):
    return db.query(AppAdminRole).filter(
        AppAdminRole.phone == normalize_phone(phone),
        AppAdminRole.role == role
    ).order_by(
        AppAdminRole.created_at.desc()
    ).first()


def role_is_denied(db, phone, role):
    override = get_admin_role_override(db, phone, role)
    return bool(override and not override.is_active)


def has_db_admin_role(db, phone, role):
    override = get_admin_role_override(db, phone, role)
    return bool(override and override.is_active)


def has_admin_role(db, phone, role):
    phone = normalize_phone(phone)
    if role == ROLE_APP_ADMIN:
        if role_is_denied(db, phone, ROLE_APP_ADMIN):
            return False
        return phone in app_admin_phones() or has_db_admin_role(db, phone, ROLE_APP_ADMIN)

    if role == ROLE_SUBSCRIPTION_ADMIN:
        if role_is_denied(db, phone, ROLE_SUBSCRIPTION_ADMIN):
            return False
        return (
            has_admin_role(db, phone, ROLE_APP_ADMIN)
            or phone in subscription_admin_phones()
            or has_db_admin_role(db, phone, ROLE_SUBSCRIPTION_ADMIN)
        )

    if role == ROLE_CUSTOMER_SUPPORT:
        if role_is_denied(db, phone, ROLE_CUSTOMER_SUPPORT):
            return False
        return (
            has_admin_role(db, phone, ROLE_APP_ADMIN)
            or has_admin_role(db, phone, ROLE_SUBSCRIPTION_ADMIN)
            or phone == customer_support_phone()
            or has_db_admin_role(db, phone, ROLE_CUSTOMER_SUPPORT)
        )

    return False


def set_admin_role(db, target_phone, role, is_active, actor_user=None):
    target_phone = normalize_phone(target_phone)
    role = normalize_admin_role(role)
    override = get_admin_role_override(db, target_phone, role)

    if not override:
        override = AppAdminRole(
            phone=target_phone,
            role=role,
            is_active=is_active,
            created_by_user_id=actor_user.id if actor_user else None
        )
        db.add(override)
    else:
        override.is_active = is_active

    if is_active:
        override.deactivated_at = None
        override.deactivated_by_user_id = None
    else:
        override.deactivated_at = datetime.utcnow()
        override.deactivated_by_user_id = actor_user.id if actor_user else None

    return override


def format_admin_roles(db):
    roles = db.query(AppAdminRole).order_by(
        AppAdminRole.role.asc(),
        AppAdminRole.created_at.desc()
    ).all()

    if not roles:
        return "No WhatsApp-managed admin roles yet."

    msg = "WhatsApp-Managed Admin Roles\n\n"
    for index, role in enumerate(roles[:30], start=1):
        status = "Active" if role.is_active else "Denied"
        msg += (
            f"{index}. {role.phone}\n"
            f"Role: {role.role}\n"
            f"Status: {status}\n\n"
        )
    if len(roles) > 30:
        msg += f"...and {len(roles) - 30:,} more."
    return msg.strip()


def build_post_onboarding_menu(business_name):
    return (
        f"Account created.\n\n"
        f"Business: {business_name.title()}\n"
        "Plan: BASIC\n\n"
        "What next?\n"
        "1. See formats\n"
        "2. Add customer\n"
        "3. View dashboard\n"
        "4. Upgrade"
    )


def build_onboarding_start_message():
    return (
        "Welcome to CreditVoice.\n\n"
        "Reply with your business name to create your free BASIC account.\n"
        "Example: Ayo Stores"
    )


def notify_subscription_admins(db, payment, owner, evidence_received=False):
    admins = [
        phone
        for phone in subscription_admin_phones()
        if has_admin_role(db, phone, ROLE_SUBSCRIPTION_ADMIN)
    ]
    db_admins = db.query(AppAdminRole).filter(
        AppAdminRole.role == ROLE_SUBSCRIPTION_ADMIN,
        AppAdminRole.is_active == True
    ).all()
    admins.extend([role.phone for role in db_admins])
    admins = sorted(set(admins))
    if not admins:
        return

    evidence_line = "Evidence: received" if evidence_received else "Evidence: not received yet"
    msg = (
        "Subscription payment request\n\n"
        f"Business: {owner.name.title()}\n"
        f"Phone: {owner.phone}\n"
        f"Plan: {payment.plan}\n"
        f"Amount: N{payment.amount:,}\n"
        f"{evidence_line}\n\n"
        f"Approve:\nAPPROVE SUB {owner.phone}\n\n"
        f"Reject:\nREJECT SUB {owner.phone}"
    )
    for admin_phone in admins:
        send_whatsapp_message(admin_phone, msg)


def approve_subscription_payment(db, payment, admin_user):
    owner = db.query(User).filter(User.id == payment.user_id).first()
    if not owner:
        return None

    owner.subscription_plan = normalize_plan(payment.plan)
    owner.subscription_status = "ACTIVE"
    owner.subscription_expires_at = datetime.utcnow() + timedelta(days=30)
    payment.status = "APPROVED"
    payment.approved_at = datetime.utcnow()
    payment.approved_by_user_id = admin_user.id if admin_user else None
    return owner


def format_pending_subscriptions(payments):
    if not payments:
        return "No pending subscription payments."

    msg = "Pending Subscription Payments\n\n"
    for index, (payment, owner) in enumerate(payments, start=1):
        evidence = "yes" if payment.evidence_ref else "no"
        owner_name = owner.name.title() if owner and owner.name else payment.phone
        msg += (
            f"{index}. {owner_name}\n"
            f"Phone: {payment.phone}\n"
            f"Plan: {payment.plan}\n"
            f"Amount: N{payment.amount:,}\n"
            f"Evidence: {evidence}\n\n"
        )
    return msg.strip()


def app_user_effective_plan(user):
    status = (getattr(user, "subscription_status", None) or "ACTIVE").upper()
    expires_at = getattr(user, "subscription_expires_at", None)
    if expires_at and expires_at < datetime.utcnow():
        return "EXPIRED"
    if status not in ["ACTIVE", "TRIAL"]:
        return status
    return normalize_plan(getattr(user, "subscription_plan", PLAN_BASIC))


def get_app_dashboard_summary(db):
    users = db.query(User).all()
    business_users = [user for user in users if not user.parent_id]
    staff_users = [user for user in users if user.parent_id]
    plan_counts = {
        PLAN_BASIC: 0,
        PLAN_GO: 0,
        PLAN_PRO: 0,
        "EXPIRED": 0,
        "PAST_DUE": 0
    }

    for user in business_users:
        effective_plan = app_user_effective_plan(user)
        if effective_plan not in plan_counts:
            plan_counts[effective_plan] = 0
        plan_counts[effective_plan] += 1

    pending_count = db.query(SubscriptionPayment).filter(
        SubscriptionPayment.status == "PENDING"
    ).count()
    pending_amount = db.query(func.coalesce(func.sum(SubscriptionPayment.amount), 0)).filter(
        SubscriptionPayment.status == "PENDING"
    ).scalar()

    month_start = get_month_start()
    approved_month_count = db.query(SubscriptionPayment).filter(
        SubscriptionPayment.status == "APPROVED",
        SubscriptionPayment.approved_at >= month_start
    ).count()
    approved_month_amount = db.query(func.coalesce(func.sum(SubscriptionPayment.amount), 0)).filter(
        SubscriptionPayment.status == "APPROVED",
        SubscriptionPayment.approved_at >= month_start
    ).scalar()

    return {
        "total_users": len(users),
        "business_users": len(business_users),
        "staff_users": len(staff_users),
        "active_staff": len([user for user in staff_users if user.role == "delegate"]),
        "pending_staff": len([user for user in staff_users if user.role == "delegate_pending"]),
        "plan_counts": plan_counts,
        "pending_count": pending_count,
        "pending_amount": pending_amount,
        "approved_month_count": approved_month_count,
        "approved_month_amount": approved_month_amount
    }


def build_app_admin_dashboard_message(db):
    summary = get_app_dashboard_summary(db)
    plan_counts = summary["plan_counts"]
    return (
        "CreditVoice App Admin Dashboard\n\n"
        f"Total users: {summary['total_users']:,}\n"
        f"Business accounts: {summary['business_users']:,}\n"
        f"Staff accounts: {summary['staff_users']:,}\n"
        f"Active staff: {summary['active_staff']:,}\n"
        f"Pending staff: {summary['pending_staff']:,}\n\n"
        f"FREE/BASIC users: {plan_counts.get(PLAN_BASIC, 0):,}\n"
        f"GO users: {plan_counts.get(PLAN_GO, 0):,}\n"
        f"PRO users: {plan_counts.get(PLAN_PRO, 0):,}\n"
        f"Expired users: {plan_counts.get('EXPIRED', 0):,}\n\n"
        f"Pending upgrades: {summary['pending_count']:,} (N{summary['pending_amount']:,})\n"
        f"Approved this month: {summary['approved_month_count']:,} (N{summary['approved_month_amount']:,})\n\n"
        "Reply with:\n"
        "1. Summary\n"
        "2. PRO users\n"
        "3. GO users\n"
        "4. FREE users\n"
        "5. Expired users\n"
        "6. Pending upgrades\n"
        "7. Approved this month\n"
        "8. Recent users\n"
        "9. Revenue summary\n\n"
        "Send exit or cancel to close."
    )


def format_user_list(users, title):
    if not users:
        return f"{title}\n\nNo users found."

    msg = f"{title}\n\n"
    for index, user in enumerate(users[:20], start=1):
        expires = user.subscription_expires_at.strftime("%d/%m/%Y") if user.subscription_expires_at else "No expiry"
        name = user.name.title() if user.name else "Unnamed"
        msg += (
            f"{index}. {name}\n"
            f"Phone: {user.phone}\n"
            f"Plan: {normalize_plan(user.subscription_plan)}\n"
            f"Status: {app_user_effective_plan(user)}\n"
            f"Expires: {expires}\n\n"
        )
    if len(users) > 20:
        msg += f"...and {len(users) - 20:,} more."
    return msg.strip()


def get_business_users_by_effective_plan(db, plan):
    users = db.query(User).filter(User.parent_id == None).order_by(
        User.created_at.desc()
    ).all()
    return [
        user
        for user in users
        if app_user_effective_plan(user) == plan
    ]


def build_app_admin_selection_message(db, selection):
    normalized = str(selection).lower().strip()
    if normalized in ["1", "summary"]:
        return "app_admin_summary", build_app_admin_dashboard_message(db)

    if normalized in ["2", "pro", "pro users"]:
        return "app_admin_pro_users", format_user_list(
            get_business_users_by_effective_plan(db, PLAN_PRO),
            "PRO Users"
        )

    if normalized in ["3", "go", "go users"]:
        return "app_admin_go_users", format_user_list(
            get_business_users_by_effective_plan(db, PLAN_GO),
            "GO Users"
        )

    if normalized in ["4", "free", "basic", "free users", "basic users"]:
        return "app_admin_free_users", format_user_list(
            get_business_users_by_effective_plan(db, PLAN_BASIC),
            "FREE/BASIC Users"
        )

    if normalized in ["5", "expired", "expired users"]:
        return "app_admin_expired_users", format_user_list(
            get_business_users_by_effective_plan(db, "EXPIRED"),
            "Expired Users"
        )

    if normalized in ["6", "pending", "pending upgrades"]:
        payments = db.query(SubscriptionPayment, User).outerjoin(
            User,
            SubscriptionPayment.user_id == User.id
        ).filter(
            SubscriptionPayment.status == "PENDING"
        ).order_by(
            SubscriptionPayment.created_at.asc()
        ).all()
        return "app_admin_pending_upgrades", format_pending_subscriptions(payments)

    if normalized in ["7", "approved", "approved this month"]:
        payments = db.query(SubscriptionPayment, User).outerjoin(
            User,
            SubscriptionPayment.user_id == User.id
        ).filter(
            SubscriptionPayment.status == "APPROVED",
            SubscriptionPayment.approved_at >= get_month_start()
        ).order_by(
            SubscriptionPayment.approved_at.desc()
        ).limit(20).all()
        if not payments:
            return "app_admin_approved_month", "No approved subscriptions this month."
        msg = "Approved This Month\n\n"
        for index, (payment, owner) in enumerate(payments, start=1):
            name = owner.name.title() if owner and owner.name else payment.phone
            approved_at = payment.approved_at.strftime("%d/%m/%Y") if payment.approved_at else "Unknown date"
            msg += (
                f"{index}. {name}\n"
                f"Phone: {payment.phone}\n"
                f"Plan: {payment.plan}\n"
                f"Amount: N{payment.amount:,}\n"
                f"Approved: {approved_at}\n\n"
            )
        return "app_admin_approved_month", msg.strip()

    if normalized in ["8", "recent", "recent users"]:
        users = db.query(User).filter(User.parent_id == None).order_by(
            User.created_at.desc()
        ).limit(20).all()
        return "app_admin_recent_users", format_user_list(users, "Recent Business Users")

    if normalized in ["9", "revenue", "revenue summary"]:
        total_approved = db.query(func.coalesce(func.sum(SubscriptionPayment.amount), 0)).filter(
            SubscriptionPayment.status == "APPROVED"
        ).scalar()
        month_approved = db.query(func.coalesce(func.sum(SubscriptionPayment.amount), 0)).filter(
            SubscriptionPayment.status == "APPROVED",
            SubscriptionPayment.approved_at >= get_month_start()
        ).scalar()
        pending_amount = db.query(func.coalesce(func.sum(SubscriptionPayment.amount), 0)).filter(
            SubscriptionPayment.status == "PENDING"
        ).scalar()
        return "app_admin_revenue", (
            "Revenue Summary\n\n"
            f"Approved all time: N{total_approved:,}\n"
            f"Approved this month: N{month_approved:,}\n"
            f"Pending upgrades: N{pending_amount:,}"
        )

    return "app_admin_unknown", build_app_admin_dashboard_message(db)


def is_subscription_admin(phone, db=None):
    if db is None:
        return normalize_phone(phone) in subscription_admin_phones()
    return has_admin_role(db, phone, ROLE_SUBSCRIPTION_ADMIN)


def is_app_admin(phone, db=None):
    if db is None:
        return normalize_phone(phone) in app_admin_phones()
    return has_admin_role(db, phone, ROLE_APP_ADMIN)


def get_visible_transaction(db, owner_phone, transaction_id, recorded_by_id=None):
    transaction = get_owner_transaction_query(
        db,
        owner_phone,
        recorded_by_id=recorded_by_id
    ).filter(
        Transaction.id == transaction_id
    ).first()
    if not transaction:
        return None

    customer = None
    if transaction.customer_id:
        customer = db.query(Customer).filter(Customer.id == transaction.customer_id).first()
    return transaction, customer


def get_transaction_notes(db, owner_phone, transaction_id, recorded_by_id=None):
    visible_tx = get_visible_transaction(db, owner_phone, transaction_id, recorded_by_id)
    if not visible_tx:
        return None, []

    notes = db.query(TransactionNote, User).outerjoin(
        User,
        TransactionNote.author_user_id == User.id
    ).filter(
        TransactionNote.transaction_id == transaction_id
    ).order_by(
        TransactionNote.created_at.asc()
    ).all()
    return visible_tx, notes


def format_transaction_note_thread(transaction, customer, notes):
    customer_name = customer.name.title() if customer else "Direct Sale"
    msg = (
        f"Transaction #{transaction.id} notes\n"
        f"{customer_name} {transaction.type}: N{transaction.amount:,}\n\n"
    )

    if not notes:
        return msg + "No notes yet."

    for i, (note, author) in enumerate(notes, start=1):
        author_name = author.name.title() if author and author.name else "Unknown"
        note_date = note.created_at.strftime("%d/%m/%Y %H:%M")
        msg += f"{i}. {author_name} ({note_date})\n{note.note}\n\n"
    return msg.strip()


def get_balance(db, customer_id, recorded_by_id=None):

    from sqlalchemy import func

    buy_query = db.query(
        func.coalesce(
            func.sum(Transaction.amount),
            0
        )
    ).filter(
        Transaction.customer_id == customer_id,
        Transaction.type == "BUY"
    )

    pay_query = db.query(
        func.coalesce(
            func.sum(Transaction.amount),
            0
        )
    ).filter(
        Transaction.customer_id == customer_id,
        Transaction.type == "PAY"
    )

    if recorded_by_id:
        buy_query = buy_query.filter(Transaction.recorded_by_id == recorded_by_id)
        pay_query = pay_query.filter(Transaction.recorded_by_id == recorded_by_id)

    total_buy = buy_query.scalar()
    total_pay = pay_query.scalar()

    return total_buy - total_pay

# =========================
# 📊 SALES ANALYTICS
# =========================

def get_today_sales(db, owner_phone=None, recorded_by_id=None):
    stats = get_transaction_stats(db, owner_phone, "TODAY", recorded_by_id)
    return stats["total_sales"]


def get_weekly_sales(db, owner_phone=None, recorded_by_id=None):
    stats = get_transaction_stats(db, owner_phone, "WEEK", recorded_by_id)
    return stats["total_sales"]


def get_monthly_sales(db, owner_phone=None, recorded_by_id=None):
    stats = get_transaction_stats(db, owner_phone, "MONTH", recorded_by_id)
    return stats["total_sales"]


def get_yearly_sales(db, owner_phone=None, recorded_by_id=None):
    stats = get_transaction_stats(db, owner_phone, "YEAR", recorded_by_id)
    return stats["total_sales"]


def get_period_range(period):
    now = datetime.utcnow()
    if period == "TODAY":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return start, end
    if period == "WEEK":
        start = now - timedelta(days=7)
        return start, now
    if period == "MONTH":
        start = now - timedelta(days=30)
        return start, now
    if period == "YEAR":
        start = now - timedelta(days=365)
        return start, now
    return None, None


def get_owner_transaction_query(db, owner_phone, period=None, recorded_by_id=None):
    query = db.query(Transaction).outerjoin(Customer, Transaction.customer_id == Customer.id)
    if owner_phone:
        business_user_ids = []
        admin_user = db.query(User).filter(User.phone == owner_phone).first()
        if admin_user:
            business_user_ids.append(admin_user.id)
            staff_ids = [
                row.id for row in db.query(User.id).filter(User.parent_id == admin_user.id).all()
            ]
            business_user_ids.extend(staff_ids)

        business_filter = Customer.owner_phone == owner_phone
        if business_user_ids:
            business_filter = or_(
                business_filter,
                Transaction.recorded_by_id.in_(business_user_ids)
            )
        query = query.filter(business_filter)
    if recorded_by_id:
        query = query.filter(Transaction.recorded_by_id == recorded_by_id)
    if period:
        start, end = get_period_range(period)
        if start and end:
            query = query.filter(
                Transaction.created_at >= start,
                Transaction.created_at < end
            )
    return query


def get_transaction_stats(db, owner_phone, period=None, recorded_by_id=None):
    query = get_owner_transaction_query(db, owner_phone, period, recorded_by_id)
    total_buy = query.filter(Transaction.type == "BUY").with_entities(
        func.coalesce(func.sum(Transaction.amount), 0)
    ).scalar()
    direct_sales = query.filter(Transaction.type == "SALE").with_entities(
        func.coalesce(func.sum(Transaction.amount), 0)
    ).scalar()
    total_pay = query.filter(Transaction.type == "PAY").with_entities(
        func.coalesce(func.sum(Transaction.amount), 0)
    ).scalar()
    transaction_count = query.count()
    return {
        "total_buy": total_buy,
        "credit_sales": total_buy,
        "direct_sales": direct_sales,
        "total_sales": total_buy + direct_sales,
        "total_pay": total_pay,
        "transaction_count": transaction_count
    }


def get_dashboard_summary(db, owner_phone=None, period=None, recorded_by_id=None):
    stats = get_transaction_stats(db, owner_phone, period, recorded_by_id)
    return {
        "total_customers": get_customer_count(db, owner_phone, None, recorded_by_id),
        "new_customers": get_new_customer_count(db, owner_phone, period, recorded_by_id),
        "paid_customers": get_paid_customer_count(db, owner_phone, period, recorded_by_id),
        "total_transactions": stats["transaction_count"],
        "credit_sales_amount": stats["credit_sales"],
        "direct_sales_amount": stats["direct_sales"],
        "total_sales_amount": stats["total_sales"],
        "total_buy_amount": stats["total_sales"],
        "total_pay_amount": stats["total_pay"]
    }


def dashboard_period_label(period):
    labels = {
        "TODAY": "today",
        "WEEK": "this week",
        "MONTH": "this month",
        "YEAR": "this year"
    }
    return labels.get(period, "all time")


def build_dashboard_summary_message(summary, period=None):
    period_label = dashboard_period_label(period)
    return (
        f"Dashboard {period_label}:\n"
        f"Total customers: {summary['total_customers']:,}\n"
        f"New customers: {summary['new_customers']:,}\n"
        f"Paid customers: {summary['paid_customers']:,}\n"
        f"Transactions: {summary['total_transactions']:,}\n"
        f"Credit sales: N{summary['credit_sales_amount']:,}\n"
        f"Direct sales: N{summary['direct_sales_amount']:,}\n"
        f"Total sales: N{summary['total_sales_amount']:,}\n"
        f"Payments received: N{summary['total_pay_amount']:,}"
    )


def build_dashboard_menu_message():
    return (
        "Dashboard Menu\n\n"
        "1. Today dashboard\n"
        "2. This week dashboard\n"
        "3. This month dashboard\n"
        "4. This year dashboard\n"
        "5. All-time dashboard\n"
        "6. Customer count\n"
        "7. Customer list\n"
        "8. Unpaid debtors\n"
        "9. Product leaderboard\n\n"
        "Reply with 1-9.\n"
        "You can also send commands like:\n"
        "dashboard today\n"
        "list customers\n"
        "unpaid debtors\n\n"
        "Send exit, back, done, or cancel to close."
    )


def build_dashboard_selection_message(db, owner_phone, selection, recorded_by_id=None):
    period_options = {
        "1": "TODAY",
        "2": "WEEK",
        "3": "MONTH",
        "4": "YEAR",
        "5": None
    }

    if selection in period_options:
        period = period_options[selection]
        summary = get_dashboard_summary(db, owner_phone, period, recorded_by_id)
        return "dashboard_summary", build_dashboard_summary_message(summary, period)

    if selection == "6":
        count = get_customer_count(db, owner_phone, None, recorded_by_id)
        return "dashboard_customer_count", f"Customers all time: {count:,}"

    if selection == "7":
        customers = list_customers(db, owner_phone, None, recorded_by_id)
        if not customers:
            return "dashboard_customer_list_empty", "No customers found."

        msg = "Customers\n\n"
        for i, customer in enumerate(customers, start=1):
            msg += (
                f"{i}. {customer['name'].title()}"
                f" ({customer['phone'] or 'no phone'}) -> N{customer['balance']:,}\n"
            )
        return "dashboard_customer_list", msg

    if selection == "8":
        debtors, total_outstanding = get_unpaid_debtors(db, owner_phone, recorded_by_id)
        if not debtors:
            return "dashboard_unpaid_empty", "No unpaid debtors found."

        msg = f"Unpaid Debtors\nTotal outstanding: N{total_outstanding:,}\n\n"
        for i, debtor in enumerate(debtors, start=1):
            msg += f"{i}. {debtor['name'].title()} -> N{debtor['balance']:,}\n"
        return "dashboard_unpaid_debtors", msg

    if selection == "9":
        results = get_product_sales_by_period(db, owner_phone, recorded_by_id=recorded_by_id)
        if not results:
            return "dashboard_products_empty", "No product sales data available yet."

        msg = "Product Leaderboard\n\n"
        for i, row in enumerate(results[:10], start=1):
            msg += (
                f"{i}. {row.product.title()} -> "
                f"{row.total_quantity:,} units, N{row.total_amount:,}\n"
            )
        return "dashboard_product_leaderboard", msg

    return None, None


def get_total_outstanding(db, owner_phone=None, recorded_by_id=None):
    debtors, total_outstanding = get_unpaid_debtors(db, owner_phone, recorded_by_id)
    return total_outstanding


def get_customer_count(db, owner_phone=None, period=None, recorded_by_id=None):
    query = db.query(Customer)
    if recorded_by_id:
        query = query.join(Transaction, Transaction.customer_id == Customer.id).filter(
            Transaction.recorded_by_id == recorded_by_id
        )
    if owner_phone:
        query = query.filter(Customer.owner_phone == owner_phone)
    if period:
        start, end = get_period_range(period)
        if start and end:
            if recorded_by_id:
                query = query.filter(
                    Transaction.created_at >= start,
                    Transaction.created_at < end
                )
            else:
                query = query.filter(
                    Customer.created_at >= start,
                    Customer.created_at < end
                )
    if recorded_by_id:
        return query.distinct(Customer.id).count()
    return query.count()


def get_new_customer_count(db, owner_phone=None, period=None, recorded_by_id=None):
    return get_customer_count(db, owner_phone, period, recorded_by_id)


def get_paid_customer_count(db, owner_phone=None, period=None, recorded_by_id=None):
    query = db.query(Customer).join(
        Transaction,
        Transaction.customer_id == Customer.id
    ).filter(
        Transaction.type == "PAY"
    )
    if owner_phone:
        query = query.filter(Customer.owner_phone == owner_phone)
    if recorded_by_id:
        query = query.filter(Transaction.recorded_by_id == recorded_by_id)
    if period:
        start, end = get_period_range(period)
        if start and end:
            query = query.filter(
                Transaction.created_at >= start,
                Transaction.created_at < end
            )
    return query.distinct(Customer.id).count()


def get_total_transaction_count(db, owner_phone=None, period=None, recorded_by_id=None):
    return get_owner_transaction_query(db, owner_phone, period, recorded_by_id).count()


def list_customers(db, owner_phone=None, period=None, recorded_by_id=None):
    query = db.query(Customer)
    if recorded_by_id:
        query = query.join(Transaction, Transaction.customer_id == Customer.id).filter(
            Transaction.recorded_by_id == recorded_by_id
        )
    if owner_phone:
        query = query.filter(Customer.owner_phone == owner_phone)

    if period:
        start, end = get_period_range(period)
        if start and end:
            if recorded_by_id:
                query = query.filter(
                    Transaction.created_at >= start,
                    Transaction.created_at < end
                )
            else:
                query = query.filter(
                    Customer.created_at >= start,
                    Customer.created_at < end
                )

    if recorded_by_id:
        query = query.distinct(Customer.id)

    customers = query.all()
    result = []
    for customer in customers:
        result.append({
            "name": customer.name,
            "phone": customer.customer_phone,
            "balance": get_balance(db, customer.id, recorded_by_id)
        })
    return result


def get_biggest_debtor(db, owner_phone=None, recorded_by_id=None):
    debtors, _ = get_unpaid_debtors(db, owner_phone, recorded_by_id)
    if not debtors:
        return None
    return max(debtors, key=lambda item: item["balance"])


def get_debtor_leaderboard(db, owner_phone=None, limit=10, recorded_by_id=None):
    debtors, _ = get_unpaid_debtors(db, owner_phone, recorded_by_id)
    return sorted(debtors, key=lambda item: item["balance"], reverse=True)[:limit]


def get_customer_summary(db, owner_phone, name, recorded_by_id=None):
    customer = db.query(Customer).filter(
        Customer.owner_phone == owner_phone,
        Customer.name == name
    ).first()
    if not customer:
        return None
    buy_query = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.customer_id == customer.id,
        Transaction.type == "BUY"
    )
    pay_query = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.customer_id == customer.id,
        Transaction.type == "PAY"
    )
    tx_query = db.query(Transaction).filter(
        Transaction.customer_id == customer.id
    )
    if recorded_by_id:
        buy_query = buy_query.filter(Transaction.recorded_by_id == recorded_by_id)
        pay_query = pay_query.filter(Transaction.recorded_by_id == recorded_by_id)
        tx_query = tx_query.filter(Transaction.recorded_by_id == recorded_by_id)

    transaction_count = tx_query.count()
    if recorded_by_id and transaction_count == 0:
        return None

    return {
        "name": customer.name,
        "balance": get_balance(db, customer.id, recorded_by_id),
        "total_buy": buy_query.scalar(),
        "total_pay": pay_query.scalar(),
        "transaction_count": transaction_count
    }


def search_customers(db, owner_phone, query_text, recorded_by_id=None):
    query = db.query(Customer)
    if recorded_by_id:
        query = query.join(Transaction, Transaction.customer_id == Customer.id).filter(
            Transaction.recorded_by_id == recorded_by_id
        )
    return query.filter(
        Customer.owner_phone == owner_phone,
        Customer.name.ilike(f"%{query_text}%")
    ).distinct(Customer.id).all()


class ProductSalesRow:
    def __init__(self, product, total_quantity, total_amount):
        self.product = product
        self.total_quantity = total_quantity
        self.total_amount = total_amount


def build_product_sales_rows(transactions, item_rows):
    item_transaction_ids = {row.transaction_id for row in item_rows}
    totals = {}

    for row in item_rows:
        if row.product not in totals:
            totals[row.product] = {"quantity": 0, "amount": 0}
        totals[row.product]["quantity"] += row.quantity or 0
        totals[row.product]["amount"] += row.total or 0

    for tx in transactions:
        if tx.id in item_transaction_ids or not tx.product:
            continue
        if tx.product not in totals:
            totals[tx.product] = {"quantity": 0, "amount": 0}
        totals[tx.product]["quantity"] += tx.quantity or 1
        totals[tx.product]["amount"] += tx.amount or 0

    return sorted(
        [
            ProductSalesRow(product, values["quantity"], values["amount"])
            for product, values in totals.items()
        ],
        key=lambda row: row.total_quantity,
        reverse=True
    )


def get_product_sales_by_period(db, owner_phone=None, period=None, recorded_by_id=None):
    query = get_owner_transaction_query(db, owner_phone, period, recorded_by_id).filter(
        Transaction.type.in_(["BUY", "SALE"])
    )
    transactions = query.all()
    transaction_ids = [tx.id for tx in transactions]
    if not transaction_ids:
        return []

    item_rows = db.query(TransactionItem).filter(
        TransactionItem.transaction_id.in_(transaction_ids)
    ).all()
    return build_product_sales_rows(transactions, item_rows)


def get_most_sold_product(db, owner_phone=None, period=None, recorded_by_id=None):
    results = get_product_sales_by_period(db, owner_phone, period, recorded_by_id)
    if not results:
        return None
    return results[0]


def get_product_sales_by_date(db, owner_phone, date_text, recorded_by_id=None):
    try:
        report_date = datetime.strptime(date_text, "%d/%m/%Y").date()
    except ValueError:
        return None
    start = datetime(report_date.year, report_date.month, report_date.day)
    end = start + timedelta(days=1)

    query = get_owner_transaction_query(db, owner_phone, recorded_by_id=recorded_by_id).filter(
        Transaction.type.in_(["BUY", "SALE"]),
        Transaction.created_at >= start,
        Transaction.created_at < end
    )
    transactions = query.all()
    transaction_ids = [tx.id for tx in transactions]
    if not transaction_ids:
        return []

    item_rows = db.query(TransactionItem).filter(
        TransactionItem.transaction_id.in_(transaction_ids)
    ).all()
    return build_product_sales_rows(transactions, item_rows)


def get_total_paid_today(db, owner_phone=None, recorded_by_id=None):
    today = datetime.utcnow().date()
    query = db.query(func.coalesce(func.sum(Transaction.amount), 0)).join(Customer, Transaction.customer_id == Customer.id)
    if owner_phone:
        query = query.filter(Customer.owner_phone == owner_phone)
    if recorded_by_id:
        query = query.filter(Transaction.recorded_by_id == recorded_by_id)
    total = query.filter(
        Transaction.type == "PAY",
        func.date(Transaction.created_at) == today
    ).scalar()
    return total


def get_outstanding_balance(db, owner_phone=None, recorded_by_id=None):
    return get_total_outstanding(db, owner_phone, recorded_by_id)

# =========================
# 📋 UNPAID DEBTORS
# =========================

def get_unpaid_debtors(db, owner_phone=None, recorded_by_id=None):

    customers = db.query(Customer)
    if recorded_by_id:
        customers = customers.join(Transaction, Transaction.customer_id == Customer.id).filter(
            Transaction.recorded_by_id == recorded_by_id
        ).distinct(Customer.id)
    if owner_phone:
        customers = customers.filter(Customer.owner_phone == owner_phone)
    customers = customers.all()

    debtors = []

    total_outstanding = 0

    for customer in customers:

        balance = get_balance(db, customer.id, recorded_by_id)

        if balance > 0:
            debtors.append({
                "name": customer.name,
                "balance": balance
            })

            total_outstanding += balance

    return debtors, total_outstanding

# =========================
# ⚠️ OVERDUE DEBTORS
# =========================

def get_overdue_debtors(db, owner_phone=None, recorded_by_id=None):

    overdue_list = []

    customers = db.query(Customer)
    if recorded_by_id:
        customers = customers.join(Transaction, Transaction.customer_id == Customer.id).filter(
            Transaction.recorded_by_id == recorded_by_id
        ).distinct(Customer.id)
    if owner_phone:
        customers = customers.filter(Customer.owner_phone == owner_phone)
    customers = customers.all()

    today = datetime.utcnow()

    for customer in customers:

        balance = get_balance(db, customer.id, recorded_by_id)

        if balance <= 0:
            continue

        latest_tx = db.query(Transaction).filter(
            Transaction.customer_id == customer.id,
            Transaction.type == "BUY",
            Transaction.due_date.isnot(None)
        )
        if recorded_by_id:
            latest_tx = latest_tx.filter(Transaction.recorded_by_id == recorded_by_id)
        latest_tx = latest_tx.order_by(
            Transaction.due_date.desc()
        ).first()

        if not latest_tx:
            continue

        if latest_tx.due_date.date() < today.date():

            overdue_days = (
                today.date()
                - latest_tx.due_date.date()
            ).days

            overdue_list.append({
                "customer_id": customer.id,
                "customer_phone": customer.customer_phone,
                "name": customer.name,
                "balance": balance,
                "due_date": latest_tx.due_date,
                "overdue_days": overdue_days
            })

    return overdue_list

# =========================
# 📅 DUE TODAY
# =========================

def get_due_today(db, owner_phone=None, recorded_by_id=None):

    due_today = []

    customers = db.query(Customer)
    if recorded_by_id:
        customers = customers.join(Transaction, Transaction.customer_id == Customer.id).filter(
            Transaction.recorded_by_id == recorded_by_id
        ).distinct(Customer.id)
    if owner_phone:
        customers = customers.filter(Customer.owner_phone == owner_phone)
    customers = customers.all()

    today = datetime.utcnow().date()

    for customer in customers:

        balance = get_balance(db, customer.id, recorded_by_id)

        if balance <= 0:
            continue

        latest_tx = db.query(Transaction).filter(
            Transaction.customer_id == customer.id,
            Transaction.type == "BUY",
            Transaction.due_date.isnot(None)
        )
        if recorded_by_id:
            latest_tx = latest_tx.filter(Transaction.recorded_by_id == recorded_by_id)
        latest_tx = latest_tx.order_by(
            Transaction.due_date.desc()
        ).first()

        if not latest_tx:
            continue

        due_date = latest_tx.due_date.date()

        if due_date == today:

            due_today.append({
                "customer_id": customer.id,
                "customer_phone": customer.customer_phone,
                "name": customer.name,
                "balance": balance,
                "due_date": latest_tx.due_date
            })

    return due_today

# =========================
# 📅 DUE IN 2 DAYS
# =========================

def get_due_in_2_days(db, owner_phone=None, recorded_by_id=None):

    due_list = []

    customers = db.query(Customer)
    if recorded_by_id:
        customers = customers.join(Transaction, Transaction.customer_id == Customer.id).filter(
            Transaction.recorded_by_id == recorded_by_id
        ).distinct(Customer.id)
    if owner_phone:
        customers = customers.filter(Customer.owner_phone == owner_phone)
    customers = customers.all()

    target_date = (
        datetime.utcnow().date()
        + timedelta(days=2)
    )

    for customer in customers:

        balance = get_balance(db, customer.id, recorded_by_id)

        if balance <= 0:
            continue

        latest_tx = db.query(Transaction).filter(
            Transaction.customer_id == customer.id,
            Transaction.type == "BUY",
            Transaction.due_date.isnot(None)
        )
        if recorded_by_id:
            latest_tx = latest_tx.filter(Transaction.recorded_by_id == recorded_by_id)
        latest_tx = latest_tx.order_by(
            Transaction.due_date.desc()
        ).first()

        if not latest_tx:
            continue

        due_date = latest_tx.due_date.date()

        if due_date == target_date:

            due_list.append({
                "customer_id": customer.id,
                "customer_phone": customer.customer_phone,
                "name": customer.name,
                "balance": balance,
                "due_date": latest_tx.due_date
            })

    return due_list

@app.get("/")
def home():
    return {"status": "CreditVoice running"}

# =========================
# 🧑‍💼 USER ONBOARDING
# =========================

@app.post("/onboard/user")
def onboard_user(user_data: UserCreate):
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.phone == user_data.phone).first()
        if existing:
            return {
                "status": "exists",
                "message": "User already onboarded",
                "user": {
                    "id": existing.id,
                    "name": existing.name,
                    "phone": existing.phone,
                    "role": existing.role,
                    "created_at": existing.created_at.isoformat()
                }
            }

        user = User(
            name=user_data.name,
            phone=user_data.phone,
            role=user_data.role
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        return {
            "status": "success",
            "user": {
                "id": user.id,
                "name": user.name,
                "phone": user.phone,
                "role": user.role,
                "created_at": user.created_at.isoformat()
            }
        }
    finally:
        db.close()


@app.post("/onboard/customer")
def onboard_customer(customer_data: CustomerCreate):
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.phone == customer_data.owner_phone).first()
        if not owner:
            return {
                "status": "owner_not_found",
                "message": "Owner phone is not registered. Please onboard the user first."
            }

        customer = db.query(Customer).filter(
            Customer.name == customer_data.name,
            Customer.owner_phone == customer_data.owner_phone
        ).first()

        if customer:
            if customer_data.customer_phone:
                customer.customer_phone = customer_data.customer_phone
                db.commit()
            return {
                "status": "exists",
                "message": "Customer already onboarded",
                "customer": {
                    "id": customer.id,
                    "name": customer.name,
                    "owner_phone": customer.owner_phone,
                    "customer_phone": customer.customer_phone,
                    "created_at": customer.created_at.isoformat()
                }
            }

        customer = Customer(
            name=customer_data.name,
            owner_phone=customer_data.owner_phone,
            customer_phone=customer_data.customer_phone
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)

        return {
            "status": "success",
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "owner_phone": customer.owner_phone,
                "customer_phone": customer.customer_phone,
                "created_at": customer.created_at.isoformat()
            }
        }
    finally:
        db.close()


@app.get("/dashboard")
def dashboard(owner_phone: Optional[str] = None, period: Optional[str] = None):
    db = SessionLocal()
    try:
        period_key = period.upper() if period else None
        return get_dashboard_summary(db, owner_phone, period_key)
    finally:
        db.close()


@app.get("/dashboard/ui", response_class=HTMLResponse)
def dashboard_ui(owner_phone: Optional[str] = None, period: Optional[str] = None):
    db = SessionLocal()
    try:
        period_key = period.upper() if period else None
        summary = get_dashboard_summary(db, owner_phone, period_key)
        period_label = dashboard_period_label(period_key)
        total_customers = summary["total_customers"]
        new_customers = summary["new_customers"]
        paid_customers = summary["paid_customers"]
        total_transactions = summary["total_transactions"]
        credit_sales = summary["credit_sales_amount"]
        direct_sales = summary["direct_sales_amount"]
        total_sales = summary["total_sales_amount"]
        stats = {
            "total_buy": summary["total_buy_amount"],
            "total_pay": summary["total_pay_amount"]
        }
        owner_label = owner_phone or "all owners"
        html = f"""
        <html>
            <head>
                <title>CreditVoice Dashboard</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 24px; }}
                    .card {{ border: 1px solid #ddd; border-radius: 10px; padding: 18px; margin-bottom: 16px; max-width: 600px; }}
                    .title {{ font-size: 24px; margin-bottom: 8px; }}
                    .metric {{ font-size: 20px; margin: 8px 0; }}
                    .label {{ color: #555; }}
                </style>
            </head>
            <body>
                <div class="card">
                    <div class="title">CreditVoice Dashboard</div>
                    <div class="metric"><span class="label">Owner:</span> {owner_label}</div>
                    <div class="metric"><span class="label">Period:</span> {period_label}</div>
                    <hr />
                    <div class="metric"><strong>Total customers:</strong> {total_customers:,}</div>
                    <div class="metric"><strong>New customers:</strong> {new_customers:,}</div>
                    <div class="metric"><strong>Paid customers:</strong> {paid_customers:,}</div>
                    <div class="metric"><strong>Total transactions:</strong> {total_transactions:,}</div>
                    <div class="metric"><strong>Credit sales:</strong> ₦{credit_sales:,}</div>
                    <div class="metric"><strong>Direct sales:</strong> ₦{direct_sales:,}</div>
                    <div class="metric"><strong>Total sales:</strong> ₦{total_sales:,}</div>
                    <div class="metric"><strong>Payments received:</strong> ₦{stats['total_pay']:,}</div>
                </div>
            </body>
        </html>
        """
        return html
    finally:
        db.close()


# =========================
# ✅ WEBHOOK VERIFICATION
# =========================

@app.get("/webhook")
def verify_webhook(request: Request):
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    
    verify_token = os.getenv("WEBHOOK_VERIFY_TOKEN", "your_verify_token_here")
    
    if token == verify_token:
        return int(challenge)
    
    return {"status": "error"}

# =========================
# 🌐 WEBHOOK
# =========================

@app.post("/webhook")
async def webhook(req: Request):
    print("Webhook received", flush=True)
    try:
        print("Webhook content-type:", req.headers.get("content-type"), flush=True)
    except Exception:
        pass
    body = await req.json()
    print("Webhook body keys:", list(body.keys()), flush=True)
    try:
        value = body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})
        print("Webhook value keys:", list(value.keys()), flush=True)

        messages = value.get("messages") or []
        if not messages:
            print("Webhook contains no messages; likely status/delivery event", flush=True)
        else:
            message = messages[0]
            phone = message.get("from")
            text = (message.get("text") or {}).get("body", "").strip()
            print(f"Webhook parsed message from {phone}: {text}", flush=True)

            if phone and text.lower() in ["menu", "help", "start", "hi", "hello"]:
                send_whatsapp_message(
                    phone,
                    "CreditVoice Menu\n\n"
                    "Record sales and payments:\n"
                    "Ade bought rice 5000\n"
                    "Ade paid 3000\n"
                    "Ade bought rice 5000 paid 2000\n\n"
                    "Reports:\n"
                    "today sales\n"
                    "unpaid debtors\n"
                    "due\n"
                    "dashboard"
                )
                return {"status": "menu"}

            if phone and text:
                debug_db = SessionLocal()
                try:
                    sender_exists = debug_db.query(User).filter(
                        User.phone == phone
                    ).first()
                    print(
                        f"Webhook sender registered: {bool(sender_exists)}",
                        flush=True
                    )
                    if not sender_exists:
                        admin_preview = parse_message(text)
                        admin_allowed = False
                        if admin_preview:
                            admin_allowed = (
                                admin_preview["type"] in [
                                    "APP_ADMIN_DASHBOARD",
                                    "APP_ADMIN_USERS_BY_PLAN",
                                    "MANAGE_APP_ADMIN_ROLE",
                                    "LIST_APP_ADMIN_ROLES"
                                ] and is_app_admin(phone, debug_db)
                            ) or (
                                admin_preview["type"] in [
                                    "PENDING_SUBSCRIPTIONS",
                                    "APPROVE_SUBSCRIPTION",
                                    "REJECT_SUBSCRIPTION",
                                    "ACTIVATE_PLAN"
                                ] and is_subscription_admin(phone, debug_db)
                            )

                        if not admin_allowed:
                            print("Unregistered sender will continue to onboarding flow", flush=True)
                            raise LookupError("continue_to_onboarding")

                    early_visible_recorded_by_id = visibility_recorded_by_id(sender_exists)

                    pending = debug_db.query(PendingAction).filter(
                        PendingAction.phone == phone
                    ).order_by(
                        PendingAction.created_at.desc()
                    ).first()

                    if pending and text.lower().strip() in ["exit", "exist", "cancel", "done", "back", "stop", "close", "quit", "end"]:
                        debug_db.delete(pending)
                        debug_db.commit()
                        send_whatsapp_message(
                            phone,
                            "Closed. You can continue recording transactions."
                        )
                        return {"status": "pending_cancelled"}

                    if pending and pending.action in ["CUSTOMER_SUMMARY_MENU", "CUSTOMER_SUMMARY_DATE"]:
                        print(f"Customer summary follow-up reached: {text}", flush=True)

                        business_owner_phone = sender_exists.phone
                        if sender_exists.parent_id:
                            owner = debug_db.query(User).filter(
                                User.id == sender_exists.parent_id
                            ).first()
                            if owner:
                                business_owner_phone = owner.phone

                        replacement_account_request = parse_customer_account_request(text)
                        if replacement_account_request:
                            pending.customer_name = replacement_account_request["name"]
                            pending.action = "CUSTOMER_SUMMARY_MENU"
                            pending.last_customer = replacement_account_request["name"]
                            debug_db.commit()

                            msg = build_customer_account_summary(
                                debug_db,
                                business_owner_phone,
                                replacement_account_request["name"],
                                period=replacement_account_request["period"],
                                target_date=replacement_account_request["target_date"],
                                include_menu=True,
                                recorded_by_id=early_visible_recorded_by_id
                            )
                            send_whatsapp_message(phone, msg)
                            return {"status": "customer_summary_replaced"}

                        normalized = text.lower().strip()
                        period_map = {
                            "1": "TODAY",
                            "today": "TODAY",
                            "2": "WEEK",
                            "week": "WEEK",
                            "this week": "WEEK",
                            "3": "MONTH",
                            "month": "MONTH",
                            "this month": "MONTH",
                            "4": "YEAR",
                            "year": "YEAR",
                            "this year": "YEAR",
                            "5": None,
                            "all": None,
                            "all time": None,
                        }

                        if pending.action == "CUSTOMER_SUMMARY_MENU" and normalized in ["6", "date", "by date"]:
                            pending.action = "CUSTOMER_SUMMARY_DATE"
                            debug_db.commit()
                            send_whatsapp_message(
                                phone,
                                f"Send date for {pending.customer_name.title()} like:\n19/05/2026"
                            )
                            return {"status": "customer_summary_date_prompt"}

                        target_date = None
                        if pending.action == "CUSTOMER_SUMMARY_DATE":
                            target_date = parse_slash_date(normalized)
                            if not target_date:
                                send_whatsapp_message(
                                    phone,
                                    "Invalid date. Send date like:\n19/05/2026"
                                )
                                return {"status": "invalid_customer_summary_date"}
                            period = "DATE"
                        else:
                            if normalized not in period_map:
                                send_whatsapp_message(
                                    phone,
                                    "Choose an account view:\n"
                                    "1. Today\n"
                                    "2. This week\n"
                                    "3. This month\n"
                                    "4. This year\n"
                                    "5. All time\n"
                                    "6. By date\n\n"
                                    "You can also send another customer, like:\n"
                                    "Ade account\n\n"
                                    "Send exit, back, done, or cancel to close."
                                )
                                return {"status": "invalid_customer_summary_option"}
                            period = period_map[normalized]

                        msg = build_customer_account_summary(
                            debug_db,
                            business_owner_phone,
                            pending.customer_name,
                            period=period,
                            target_date=target_date,
                            include_menu=True,
                            recorded_by_id=early_visible_recorded_by_id
                        )
                        pending.action = "CUSTOMER_SUMMARY_MENU"
                        debug_db.commit()
                        send_whatsapp_message(phone, msg)
                        return {"status": "customer_summary_followup"}

                    account_request = parse_customer_account_request(text)
                    if account_request:
                        print("Customer account direct handler reached", flush=True)

                        business_owner_phone = sender_exists.phone
                        if sender_exists.parent_id:
                            owner = debug_db.query(User).filter(
                                User.id == sender_exists.parent_id
                            ).first()
                            if owner:
                                business_owner_phone = owner.phone

                        debug_db.query(PendingAction).filter(
                            PendingAction.phone == phone
                        ).delete()
                        debug_db.add(
                            PendingAction(
                                phone=phone,
                                customer_name=account_request["name"],
                                action="CUSTOMER_SUMMARY_MENU",
                                last_customer=account_request["name"]
                            )
                        )
                        debug_db.commit()

                        msg = build_customer_account_summary(
                            debug_db,
                            business_owner_phone,
                            account_request["name"],
                            period=account_request["period"],
                            target_date=account_request["target_date"],
                            include_menu=True,
                            recorded_by_id=early_visible_recorded_by_id
                        )
                        send_whatsapp_message(phone, msg)
                        return {"status": "customer_summary_menu"}

                    if text.lower().strip() == "due":
                        print("Due direct handler reached", flush=True)
                        allowed, upgrade_msg = ensure_feature_allowed(
                            debug_db,
                            sender_exists,
                            "DUE_REMINDERS",
                            "Debt reminders"
                        )
                        if not allowed:
                            send_whatsapp_message(phone, upgrade_msg)
                            return {"status": "due_menu_plan_blocked"}

                        try:
                            debug_db.query(PendingAction).filter(
                                PendingAction.phone == phone
                            ).delete()
                            debug_db.add(
                                PendingAction(
                                    phone=phone,
                                    customer_name="",
                                    action="DUE_MENU",
                                    last_customer=""
                                )
                            )
                            debug_db.commit()
                        except Exception as exc:
                            debug_db.rollback()
                            print("Due pending action failed:", repr(exc), flush=True)

                        send_whatsapp_message(
                            phone,
                            "Due Reminder Menu\n\n"
                            "1. Debts due in 2 days\n"
                            "2. Debts due today\n"
                            "3. Overdue debtors\n\n"
                            "Reply with 1, 2, or 3."
                        )
                        return {"status": "due_menu"}

                    if pending and pending.action == "DUE_MENU" and text.strip() in ["1", "2", "3"]:
                        print(f"Due menu selection reached: {text}", flush=True)

                        business_owner_phone = sender_exists.phone
                        if sender_exists.parent_id:
                            owner = debug_db.query(User).filter(
                                User.id == sender_exists.parent_id
                            ).first()
                            if owner:
                                business_owner_phone = owner.phone

                        debug_db.query(ReminderMemory).filter(
                            ReminderMemory.phone == phone
                        ).delete()
                        debug_db.delete(pending)

                        if text.strip() == "1":
                            due_list = get_due_in_2_days(debug_db, business_owner_phone, early_visible_recorded_by_id)
                            title = "Due in 2 Days"
                            empty_msg = "No debts due in 2 days."
                            reminder_type = "DUE_2_DAYS"
                        elif text.strip() == "2":
                            due_list = get_due_today(debug_db, business_owner_phone, early_visible_recorded_by_id)
                            title = "Due Today"
                            empty_msg = "No debts due today."
                            reminder_type = "DUE_TODAY"
                        else:
                            due_list = get_overdue_debtors(debug_db, business_owner_phone, early_visible_recorded_by_id)
                            title = "Overdue Debtors"
                            empty_msg = "No overdue debtors."
                            reminder_type = "OVERDUE"

                        if not due_list:
                            debug_db.commit()
                            send_whatsapp_message(phone, f"✅ {empty_msg}")
                            return {"status": "due_menu_empty"}

                        msg = f"{title}\n\n"
                        for i, debtor in enumerate(due_list, start=1):
                            memory = ReminderMemory(
                                phone=phone,
                                customer_id=debtor.get("customer_id"),
                                customer_name=debtor["name"],
                                customer_phone=debtor.get("customer_phone"),
                                balance=debtor["balance"],
                                due_date=debtor["due_date"],
                                reminder_type=reminder_type
                            )
                            debug_db.add(memory)

                            if text.strip() == "3":
                                due_date_text = debtor["due_date"].strftime("%d/%m/%Y")
                                msg += (
                                    f"{i}. {debtor['name']}\n"
                                    f"Balance: ₦{debtor['balance']:,}\n"
                                    f"Due: {due_date_text}\n"
                                    f"Overdue: {debtor.get('overdue_days', 0)} days\n\n"
                                )
                            else:
                                msg += f"{i}. {debtor['name']} → ₦{debtor['balance']:,}\n"

                        debug_db.add(
                            PendingAction(
                                phone=phone,
                                customer_name="",
                                action="REMINDER_SELECTION",
                                last_customer=""
                            )
                        )
                        debug_db.commit()

                        numbers = ", ".join(str(i) for i in range(1, len(due_list) + 1))
                        msg += f"\nSend:\n{numbers} to preview the reminder before sending to customer."
                        send_whatsapp_message(phone, msg)
                        return {"status": "due_menu_selection"}
                finally:
                    debug_db.close()
    except LookupError as exc:
        if str(exc) != "continue_to_onboarding":
            print("Webhook early parse lookup error:", repr(exc), flush=True)
    except Exception as exc:
        print("Webhook early parse error:", repr(exc), flush=True)

    data = await req.json()

    try:
        message = (
            data["entry"][0]
            ["changes"][0]
            ["value"]["messages"][0]
        )

        phone = message["from"]

        message_type = message.get("type", "text")
        text = (message.get("text") or {}).get("body", "").strip()
        message_id = message["id"]

    except:
        print("Webhook ignored before reply", flush=True)
        return {"status": "ignored"}

    db = SessionLocal()

    try:
        # 1. Global Idempotency Check (Prevents Meta Retries)
        already_processed = db.query(ProcessedMessage).filter(
            ProcessedMessage.message_id == message_id
        ).first()

        if already_processed:
            return {"status": "duplicate"}

        # Log this message ID immediately
        log_msg = ProcessedMessage(message_id=message_id)
        db.add(log_msg)
        try:
            db.commit()
        except:
            return {"status": "duplicate_race_condition"}

        # =========================
        # 🔍 USER & CONTEXT IDENTIFICATION
        # =========================
        user = db.query(User).filter(User.phone == phone).first()

        # Determine the "Business Owner Context"
        # This ensures delegates see the Admin's customers and data
        business_owner_phone = phone
        business_name = "your business"
        
        if user:
            if user.role in ["delegate", "delegate_pending"] and user.parent_id:
                admin = db.query(User).filter(User.id == user.parent_id).first()
                if admin:
                    business_owner_phone = admin.phone
                    business_name = admin.name
            else:
                business_name = user.name
        elif message_type in ["voice", "audio"]:
            send_whatsapp_message(
                phone,
                "Welcome to CreditVoice. Please register your business with a text message first, then you can use voice notes."
            )
            return {"status": "unregistered_voice"}

        # Parse early so unregistered app/subscription admins can use admin commands.
        parsed = parse_message(text) if message_type == "text" else None
        is_command = parsed and parsed["type"] != "TRANSACTION"

        if not user and parsed:
            admin_command_allowed = (
                parsed["type"] in [
                    "APP_ADMIN_DASHBOARD",
                    "APP_ADMIN_USERS_BY_PLAN",
                    "MANAGE_APP_ADMIN_ROLE",
                    "LIST_APP_ADMIN_ROLES"
                ] and is_app_admin(phone, db)
            ) or (
                parsed["type"] in [
                    "PENDING_SUBSCRIPTIONS",
                    "APPROVE_SUBSCRIPTION",
                    "REJECT_SUBSCRIPTION",
                    "ACTIVATE_PLAN"
                ] and is_subscription_admin(phone, db)
            )
            if not admin_command_allowed:
                parsed = None
                is_command = False

        # Logic for Pending Invitations
        if user and user.role == "delegate_pending":
            normalized = text.lower().strip()
            if normalized in ["1", "yes", "accept", "approve"]:
                user.role = "delegate"
                db.commit()
                send_whatsapp_message(
                    phone,
                    f"✅ Access Accepted!\n\nYou are now an authorized staff member for *{business_name.title()}*. You can start recording transactions immediately."
                )
                # Notify Admin
                send_whatsapp_message(
                    business_owner_phone,
                    f"📢 Notification: {user.name.title()} has ACCEPTED your staff invitation."
                )
                return {"status": "delegate_accepted"}
            elif normalized in ["2", "no", "decline", "reject"]:
                user.role = "user"
                user.parent_id = None
                user.can_view_all_transactions = False
                db.commit()
                send_whatsapp_message(
                    phone,
                    f"❌ Invitation Declined.\n\nYou are no longer associated with {business_name.title()}."
                )
                # Notify Admin
                send_whatsapp_message(
                    business_owner_phone,
                    f"📢 Notification: {user.name.title()} has DECLINED your staff invitation."
                )
                return {"status": "delegate_declined"}
            else:
                send_whatsapp_message(
                    phone,
                    f"Hello {user.name.title()}! *{business_name.title()}* has added you as a staff member.\n\n"
                    "Do you accept this invitation?\n\n1. Yes, Accept\n2. No, Decline"
                )
                return {"status": "delegate_invitation_pending"}

        # Use the business_owner_phone for all lookups instead of the raw sender 'phone'
        # From this point forward, use business_owner_phone for DB queries

        if message_type in ["voice", "audio"]:
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "VOICE_TEXT", "Voice notes")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "voice_plan_blocked"}

            transcribed_text, transcription_error = transcribe_whatsapp_voice(message)
            if transcription_error or not transcribed_text:
                send_whatsapp_message(
                    phone,
                    f"I could not understand that voice note. {transcription_error or ''}".strip()
                )
                return {"status": "voice_transcription_failed"}

            text = transcribed_text
            message_type = "text"
            print(f"Voice transcript for {phone}: {text}", flush=True)

        # Parse message early to check if it's an explicit command
        if parsed is None:
            parsed = parse_message(text)
            is_command = parsed and parsed["type"] != "TRANSACTION"
        visible_recorded_by_id = visibility_recorded_by_id(user)
        subscription = get_business_subscription(db, user)

        pending = db.query(PendingAction).filter(
            PendingAction.phone == phone,
            PendingAction.action != None
        ).order_by(
            PendingAction.created_at.desc()
        ).first()

        if message_type != "text":
            if message_type in ["image", "document"] and pending and pending.action == "SUBSCRIPTION_PAYMENT_PENDING":
                payment = db.query(SubscriptionPayment).filter(
                    SubscriptionPayment.id == pending.reminder_id,
                    SubscriptionPayment.status == "PENDING"
                ).first()
                if payment:
                    owner = get_business_owner_user(db, user)
                    payment.evidence_type = message_type.upper()
                    payment.evidence_ref = get_media_evidence_ref(message, message_type)
                    db.commit()
                    notify_subscription_admins(db, payment, owner, evidence_received=True)
                    send_whatsapp_message(
                        phone,
                        "Receipt received. Your subscription request is waiting for admin confirmation."
                        f"{support_line()}"
                    )
                    return {"status": "subscription_receipt_received"}

            return {"status": "ignored_non_text"}

        if pending and pending.action == "UPGRADE_MENU" and not is_command:
            normalized = text.lower().strip()
            if normalized in ["1", "go"]:
                pending.action = "UPGRADE_PLAN_SELECTED"
                pending.customer_name = PLAN_GO
                db.commit()
                send_whatsapp_message(phone, build_plan_payment_message(PLAN_GO))
                return {"status": "upgrade_go_selected"}

            if normalized in ["2", "pro"]:
                pending.action = "UPGRADE_PLAN_SELECTED"
                pending.customer_name = PLAN_PRO
                db.commit()
                send_whatsapp_message(phone, build_plan_payment_message(PLAN_PRO))
                return {"status": "upgrade_pro_selected"}

            if normalized in ["3", "my plan", "plan"]:
                send_whatsapp_message(phone, build_plan_message(subscription))
                return {"status": "upgrade_my_plan"}

            if normalized in ["4", "cancel", "exit", "back"]:
                db.delete(pending)
                db.add(
                    PendingAction(
                        phone=phone,
                        customer_name=name_to_save,
                        action="POST_ONBOARDING_MENU",
                        last_customer=name_to_save
                    )
                )
                db.commit()
                send_whatsapp_message(phone, "Upgrade cancelled.")
                return {"status": "upgrade_cancelled"}

            send_whatsapp_message(phone, build_upgrade_message())
            return {"status": "upgrade_menu_waiting"}

        evidence_text = bool(re.search(
            r"\b(receipt|ref|reference|transfer|payment|sent|paid)\b",
            text.lower()
        ))
        if pending and pending.action == "SUBSCRIPTION_PAYMENT_PENDING" and not is_command and (not parsed or evidence_text):
            normalized = text.lower().strip()
            if normalized in ["cancel", "exit", "back", "stop"]:
                db.delete(pending)
                db.commit()
                send_whatsapp_message(phone, "Subscription payment request closed.")
                return {"status": "subscription_payment_cancelled"}

            payment = db.query(SubscriptionPayment).filter(
                SubscriptionPayment.id == pending.reminder_id,
                SubscriptionPayment.status == "PENDING"
            ).first()
            if payment:
                owner = get_business_owner_user(db, user)
                payment.evidence_type = "TEXT"
                payment.evidence_ref = text[:500]
                db.commit()
                notify_subscription_admins(db, payment, owner, evidence_received=True)
                send_whatsapp_message(
                    phone,
                    "Payment evidence received. Your subscription request is waiting for admin confirmation."
                    f"{support_line()}"
                )
                return {"status": "subscription_text_evidence_received"}

        if pending and pending.action == "POST_ONBOARDING_MENU" and not is_command:
            normalized = text.lower().strip()
            if normalized in ["1", "formats", "format", "f"]:
                db.delete(pending)
                db.commit()
                send_whatsapp_message(
                    phone,
                    "Supported Formats\n\n"
                    "BUY ONLY\nAde bought rice 5000\n\n"
                    "PAYMENT ONLY\nAde paid 3000\n\n"
                    "PART PAYMENT\nAde bought rice 5000 paid 2000\n\n"
                    "INVOICE\nAde bought rice 4000, beans 3000 paid 2000"
                )
                return {"status": "post_onboarding_formats"}

            if normalized in ["2", "add customer", "customer"]:
                send_whatsapp_message(
                    phone,
                    "To add a customer, send their name and phone number like:\nJohn 08012345678"
                )
                return {"status": "post_onboarding_add_customer"}

            if normalized in ["3", "dashboard"]:
                pending.action = "DASHBOARD_MENU"
                db.commit()
                send_whatsapp_message(phone, build_dashboard_menu_message())
                return {"status": "post_onboarding_dashboard"}

            if normalized in ["4", "upgrade"]:
                pending.action = "UPGRADE_MENU"
                db.commit()
                send_whatsapp_message(phone, build_upgrade_message())
                return {"status": "post_onboarding_upgrade"}

            if normalized in ["cancel", "exit", "back", "done", "stop"]:
                db.delete(pending)
                db.commit()
                send_whatsapp_message(phone, "Closed. You can continue anytime.")
                return {"status": "post_onboarding_closed"}

            send_whatsapp_message(phone, build_post_onboarding_menu(pending.customer_name or business_name))
            return {"status": "post_onboarding_waiting"}

        # =========================
        # 👤 USER ONBOARDING / PROFILE UPDATE (CONFIRMATION)
        # =========================

        if pending and pending.action == "ONBOARD_USER" and not is_command:
            full_name = text.strip()
            if full_name == "" or full_name.lower() in ["continue", "start", "yes", "ok", "1"]:
                send_whatsapp_message(
                    phone,
                    "Please reply with the name you want to use."
                )
                return {"status": "onboarding_name_required"}

            # Save name temporarily in pending and move to confirmation step
            pending.action = "ONBOARD_USER_CONFIRM"
            pending.customer_name = full_name  # Reuse field for temporary storage
            db.commit()

            send_whatsapp_message(
                phone,
                f"Confirm name: *{full_name.title()}*?\n\n"
                "Reply YES or 1 to save, EDIT or 2 to change."
            )
            return {"status": "onboarding_confirm_sent"}

        if pending and pending.action == "ONBOARD_USER_CONFIRM" and not is_command:
            normalized = text.lower().strip()
            if normalized in ["yes", "1", "save"]:
                name_to_save = pending.customer_name
                
                if user:
                    # Update existing user (Business Name update)
                    user.name = name_to_save
                    msg = f"✅ Profile updated! Your business name is now *{name_to_save.title()}*."
                else:
                    # Register new user
                    new_user = User(
                        name=name_to_save,
                        phone=phone,
                        role="user"
                    )
                    db.add(new_user)
                    msg = build_post_onboarding_menu(name_to_save)

                db.delete(pending)
                db.commit()
                send_whatsapp_message(phone, msg)
                return {"status": "user_saved"}

            if normalized in ["edit", "2", "change"]:
                pending.action = "ONBOARD_USER"
                db.commit()
                send_whatsapp_message(
                    phone,
                    "No problem! Please reply with the name you want to use."
                )
                return {"status": "onboarding_restart"}

            send_whatsapp_message(
                phone,
                f"Confirm name: *{pending.customer_name}*?\n\n"
                "Reply YES or 1 to save, EDIT or 2 to change."
            )
            return {"status": "waiting_onboarding_confirmation"}

        if not user:

            if text.lower().strip() in ["continue", "start", "yes", "ok", "1", "hello", "hi", "hey", "onboard", "titi", "begin"]:
                if pending and pending.action != "ONBOARD_USER":
                    db.delete(pending)
                    db.commit()

                onboarding = PendingAction(
                    phone=phone,
                    action="ONBOARD_USER"
                )
                db.add(onboarding)
                db.commit()

                send_whatsapp_message(
                    phone,
                    build_onboarding_start_message()
                )
                return {"status": "onboarding_started"}

            # Only send the welcome message if the user actually tried to 
            # engage with a greeting or a start command.
            onboarding_triggers = ["hello", "hi", "hey", "start", "onboard", "titi", "begin", "1", "continue"]
            if text.lower().strip() in onboarding_triggers:
                send_whatsapp_message(
                    phone,
                    build_onboarding_start_message()
                )
                return {"status": "welcome_sent"}
            
            return {"status": "ignored_unrecognized_sender"}

        # Special Greeting for a Delegate's first time or on 'hello'
        if user.role == "delegate" and text.lower().strip() in ["hello", "hi", "titi"]:
            send_whatsapp_message(
                phone,
                f"Hello {user.name.title()}! 👋\n\n"
                f"You are logged in as a staff member for *{business_name.title()}*.\n\n"
                "You can record transactions or check balances for the business here."
            )
            return {"status": "delegate_greeted"}

        if pending and pending.action == "RESIGN_CONFIRM" and not is_command:
            normalized = text.strip()
            if normalized in ["1", "yes"]:
                # Save admin phone for notification before clearing association
                admin_notify_phone = business_owner_phone

                user.role = "user"
                user.parent_id = None
                user.can_view_all_transactions = False
                db.delete(pending)
                db.commit()
                send_whatsapp_message(
                    phone,
                    f"✅ You have successfully resigned. You no longer have access to {business_name.title()}'s data."
                )
                # Notify Admin
                if admin_notify_phone != phone:
                    send_whatsapp_message(
                        admin_notify_phone,
                        f"📢 Notification: {user.name.title()} has RESIGNED as your staff member."
                    )
                return {"status": "resigned_success"}
            
            if normalized in ["2", "no", "edit"]:
                db.delete(pending)
                db.commit()
                send_whatsapp_message(phone, "Resignation cancelled. You are still staff.")
                return {"status": "resigned_cancelled"}
            
            send_whatsapp_message(
                phone,
                f"Are you sure you want to stop working with *{business_name.title()}*?\n\n1. Yes, Confirm\n2. No, Cancel"
            )
            return {"status": "resigned_confirm_waiting"}

        if pending and pending.action == "ONBOARD_CUSTOMER" and not is_command:
            normalized = text.lower().strip()
            if normalized in ["yes", "1", "save"]:
                if pending.action == "SALE":
                    recent_tx = db.query(Transaction).filter(
                        Transaction.type == "SALE",
                        Transaction.amount == pending.buy_amount,
                        Transaction.product == pending.product,
                        Transaction.recorded_by_id == user.id,
                        Transaction.created_at >= datetime.utcnow() - timedelta(minutes=2)
                    ).first()

                    if recent_tx:
                        send_whatsapp_message(
                            phone,
                            "A similar direct sale was already recorded just a moment ago."
                        )
                        db.delete(pending)
                        db.commit()
                        return {"status": "duplicate_sale_prevention"}

                    tx = Transaction(
                        customer_id=None,
                        type="SALE",
                        amount=pending.buy_amount,
                        product=pending.product,
                        quantity=pending.quantity,
                        unit=pending.unit,
                        unit_price=pending.unit_price,
                        recorded_by_id=user.id,
                        message_id=message_id,
                        created_at=datetime.utcnow()
                    )
                    db.add(tx)
                    db.delete(pending)
                    db.commit()

                    send_whatsapp_message(
                        phone,
                        f"✅ Direct sale saved.\n"
                        f"{pending.product.title()}: ₦{pending.buy_amount:,}"
                    )
                    return {"status": "direct_sale_saved"}

                customer = db.query(Customer).filter(
                    Customer.name == pending.customer_name,
                    Customer.owner_phone == business_owner_phone
                ).first()

                if not customer:
                    customer = Customer(
                        name=pending.customer_name,
                        owner_phone=business_owner_phone,
                        customer_phone=pending.customer_phone
                    )
                    db.add(customer)
                else:
                    customer.customer_phone = pending.customer_phone

                db.delete(pending)
                db.commit()

                send_whatsapp_message(
                    phone,
                    f"✅ Customer saved: {customer.name.title()} → {customer.customer_phone}.\n"
                    "You can now record transactions for this customer."
                )
                return {"status": "customer_onboarded"}

            if normalized in ["edit", "2", "change"]:
                db.delete(pending)
                db.commit()

                send_whatsapp_message(
                    phone,
                    "Okay, please send the customer again like:\nJohn 08012345678"
                )
                return {"status": "customer_onboarded_edit"}

            send_whatsapp_message(
                phone,
                "I found a customer ready to save. Reply YES or 1 to confirm, EDIT or 2 to send it again."
            )
            return {"status": "customer_onboarded_confirm"}

        if pending and not is_command:
            if pending.action == "APP_ADMIN_DASHBOARD":
                normalized = text.strip().lower()
                status, msg = build_app_admin_selection_message(db, normalized)
                if status == "app_admin_unknown":
                    send_whatsapp_message(phone, msg)
                    return {"status": "invalid_app_admin_dashboard_option"}

                db.delete(pending)
                db.commit()
                send_whatsapp_message(phone, msg)
                return {"status": status}

            if pending.action == "DASHBOARD_MENU":
                normalized = text.strip().lower()
                dashboard_aliases = {
                    "today": "1",
                    "this week": "2",
                    "week": "2",
                    "this month": "3",
                    "month": "3",
                    "this year": "4",
                    "year": "4",
                    "all": "5",
                    "all time": "5",
                    "customers": "6",
                    "customer count": "6",
                    "customer list": "7",
                    "list customers": "7",
                    "debtors": "8",
                    "unpaid": "8",
                    "unpaid debtors": "8",
                    "products": "9",
                    "product leaderboard": "9"
                }
                selection = dashboard_aliases.get(normalized, normalized)
                status, msg = build_dashboard_selection_message(
                    db,
                    business_owner_phone,
                    selection,
                    visible_recorded_by_id
                )

                if not msg:
                    send_whatsapp_message(phone, build_dashboard_menu_message())
                    return {"status": "invalid_dashboard_menu_option"}

                db.delete(pending)
                db.commit()
                send_whatsapp_message(phone, msg)
                return {"status": status}

            if pending.action == "DUE_MENU":
                # Handle DUE_MENU responses (1, 2, 3)
                if text == "1":
                    # Due in 2 days logic
                    due_list = get_due_in_2_days(db, business_owner_phone, visible_recorded_by_id)
                    db.query(ReminderMemory).filter(
                        ReminderMemory.phone == phone
                    ).delete()
                    db.commit()

                    if len(due_list) == 0:
                        send_whatsapp_message(
                            phone,
                            "✅ No debts due in 2 days."
                        )
                    else:
                        msg = "📅 Due in 2 Days\n\n"
                        for i, debtor in enumerate(due_list, start=1):
                            memory = ReminderMemory(
                                phone=phone,
                                customer_id=debtor["customer_id"],
                                customer_name=debtor["name"],
                                customer_phone=debtor.get("customer_phone"),
                                balance=debtor["balance"],
                                due_date=debtor["due_date"],
                                reminder_type="DUE_2_DAYS"
                            )
                            db.add(memory)
                            msg += f"{i}. {debtor['name']} → ₦{debtor['balance']:,}\n"
                        db.commit()
                        reminder_pending = PendingAction(
                            phone=phone,
                            action="REMINDER_SELECTION"
                        )
                        db.add(reminder_pending)
                        db.commit()
                        numbers = ", ".join(str(i) for i in range(1, len(due_list) + 1))
                        msg += f"\nSend:\n{numbers} to preview the reminder before sending to customer."
                        send_whatsapp_message(phone, msg)

                    db.delete(pending)
                    db.commit()
                    return {"status": "due_2_days"}

                elif text == "2":
                    # Due today logic
                    due_today = get_due_today(db, business_owner_phone, visible_recorded_by_id)
                    db.query(ReminderMemory).filter(
                        ReminderMemory.phone == phone
                    ).delete()
                    db.commit()

                    if len(due_today) == 0:
                        send_whatsapp_message(
                            phone,
                            "✅ No debts due today."
                        )
                    else:
                        msg = "📅 Due Today\n\n"
                        for i, debtor in enumerate(due_today, start=1):
                            memory = ReminderMemory(
                                phone=phone,
                                customer_id=debtor["customer_id"],
                                customer_name=debtor["name"],
                                customer_phone=debtor.get("customer_phone"),
                                balance=debtor["balance"],
                                due_date=debtor["due_date"],
                                reminder_type="DUE_TODAY"
                            )
                            db.add(memory)
                            msg += f"{i}. {debtor['name']} → ₦{debtor['balance']:,}\n"
                        db.commit()
                        reminder_pending = PendingAction(
                            phone=phone,
                            action="REMINDER_SELECTION"
                        )
                        db.add(reminder_pending)
                        db.commit()
                        numbers = ", ".join(str(i) for i in range(1, len(due_today) + 1))
                        msg += f"\nSend:\n{numbers} to preview the reminder before sending to customer."
                        send_whatsapp_message(phone, msg)

                    db.delete(pending)
                    db.commit()
                    return {"status": "due_today"}

                elif text == "3":
                    # Overdue logic
                    db.query(ReminderMemory).filter(
                        ReminderMemory.phone == phone
                    ).delete()
                    db.commit()

                    overdue_list = get_overdue_debtors(db, business_owner_phone, visible_recorded_by_id)
                    if len(overdue_list) == 0:
                        send_whatsapp_message(
                            phone,
                            "✅ No overdue debtors."
                        )
                    else:
                        msg = "⚠️ Overdue Debtors\n\n"
                        for i, debtor in enumerate(overdue_list, start=1):
                            memory = ReminderMemory(
                                phone=phone,
                                customer_id=debtor["customer_id"],
                                customer_name=debtor["name"],
                                customer_phone=debtor.get("customer_phone"),
                                balance=debtor["balance"],
                                due_date=debtor["due_date"],
                                reminder_type="OVERDUE"
                            )
                            db.add(memory)
                            due_date_text = debtor["due_date"].strftime("%d/%m/%Y")
                            msg += (
                                f"{i}. {debtor['name']}\n"
                                f"Balance: ₦{debtor['balance']:,}\n"
                                f"Due: {due_date_text}\n"
                                f"Overdue: {debtor['overdue_days']} days\n\n"
                            )
                        db.commit()
                        reminder_pending = PendingAction(
                            phone=phone,
                            action="REMINDER_SELECTION"
                        )
                        db.add(reminder_pending)
                        db.commit()
                        numbers = ", ".join(str(i) for i in range(1, len(overdue_list) + 1))
                        msg += f"\nSend:\n{numbers} to preview the reminder before sending to customer."
                        send_whatsapp_message(phone, msg)

                    db.delete(pending)
                    db.commit()
                    return {"status": "overdue_menu"}

            elif pending.action == "REMINDER_SELECTION":
                if not text.isdigit():
                    send_whatsapp_message(
                        phone,
                        "Reply with reminder number.\nExample: 1"
                    )
                    return {"status": "invalid_reminder_selection"}

                index = int(text)
                reminders = db.query(ReminderMemory).filter(
                    ReminderMemory.phone == phone
                ).all()

                if index < 1 or index > len(reminders):
                    send_whatsapp_message(
                        phone,
                        "Reminder number not found."
                    )
                    return {"status": "reminder_not_found"}

                reminder = reminders[index - 1]
                
                # Show preview regardless of phone being set
                preview = build_reminder_text(reminder)
                
                # Build confirmation message based on whether phone is set
                if reminder.customer_phone:
                    confirm_msg = (
                        f"Preview reminder for {reminder.customer_name.title()}:\n\n"
                        f"{preview}\n\n"
                        f"Reply YES to send this reminder to {reminder.customer_name.title()} "
                        f"at {reminder.customer_phone}, or EDIT to cancel."
                    )
                else:
                    confirm_msg = (
                        f"Preview reminder for {reminder.customer_name.title()}:\n\n"
                        f"{preview}\n\n"
                        f"⚠️ Customer phone not set!\n"
                        f"To send this reminder, please set the phone first:\n\n"
                        f"{reminder.customer_name} phone 08012345678\n\n"
                        f"Then reply YES to send, or EDIT to cancel."
                    )

                pending.action = "REMINDER_CONFIRM"
                pending.reminder_id = reminder.id
                db.commit()
                send_whatsapp_message(phone, confirm_msg)
                return {"status": "reminder_preview"}

            elif pending.action == "REMINDER_CONFIRM":
                if text.lower() == "yes":
                    reminder = db.query(ReminderMemory).filter(
                        ReminderMemory.id == pending.reminder_id
                    ).first()

                    if not reminder:
                        send_whatsapp_message(
                            phone,
                            "Reminder not found. Please select again."
                        )
                        db.delete(pending)
                        db.commit()
                        return {"status": "reminder_missing"}

                    if not reminder.customer_phone:
                        # Instead of failing, prompt user to set phone first
                        send_whatsapp_message(
                            phone,
                            f"⚠️ Customer phone not set for {reminder.customer_name.title()}.\n\n"
                            f"Please set it using:\n"
                            f"{reminder.customer_name} phone 08012345678\n\n"
                            f"After setting, reply YES again to send the reminder."
                        )
                        # Keep the pending action so they can retry after setting phone
                        return {"status": "waiting_for_phone"}

                    reminder_text = build_reminder_text(reminder)
                    send_whatsapp_message(reminder.customer_phone, reminder_text)
                    send_whatsapp_message(
                        phone,
                        f"✅ Reminder sent to {reminder.customer_name.title()} ({reminder.customer_phone})."
                    )
                    db.delete(pending)
                    db.commit()
                    return {"status": "reminder_sent"}

                if text.lower() == "edit":
                    db.delete(pending)
                    db.commit()
                    send_whatsapp_message(
                        phone,
                        "Reminder cancelled. Reply DUE to start again."
                    )
                    return {"status": "reminder_cancelled"}

                send_whatsapp_message(
                    phone,
                    "Reply YES to send the reminder to the customer or EDIT to cancel."
                )
                return {"status": "reminder_confirm_prompt"}

            normalized = text.lower().strip()
            if normalized in ["yes", "1", "save"]:
                pending_items = json.loads(pending.items_json or "[]")

                if pending.action == "SALE":
                    recent_tx = db.query(Transaction).filter(
                        Transaction.type == "SALE",
                        Transaction.amount == pending.buy_amount,
                        Transaction.product == pending.product,
                        Transaction.recorded_by_id == user.id,
                        Transaction.created_at >= datetime.utcnow() - timedelta(minutes=2)
                    ).first()

                    if recent_tx:
                        send_whatsapp_message(
                            phone,
                            "A similar direct sale was already recorded just a moment ago."
                        )
                        db.delete(pending)
                        db.commit()
                        return {"status": "duplicate_sale_prevention"}

                    tx = Transaction(
                        customer_id=None,
                        type="SALE",
                        amount=pending.buy_amount,
                        product=pending.product,
                        quantity=pending.quantity,
                        unit=pending.unit,
                        unit_price=pending.unit_price,
                        recorded_by_id=user.id,
                        message_id=message_id,
                        created_at=datetime.utcnow()
                    )
                    db.add(tx)
                    db.flush()
                    if pending_items:
                        add_transaction_items(db, tx.id, pending_items)
                    elif pending.product:
                        add_transaction_items(db, tx.id, [{
                            "product": pending.product,
                            "quantity": pending.quantity or 1,
                            "unit": pending.unit,
                            "unit_price": pending.unit_price or pending.buy_amount,
                            "total": pending.buy_amount
                        }])

                    db.delete(pending)
                    db.commit()

                    send_whatsapp_message(
                        phone,
                        f"✅ Direct sale saved.\n"
                        f"Total: ₦{pending.buy_amount:,}"
                    )
                    return {"status": "direct_sale_saved"}

                customer = db.query(Customer).filter(
                    Customer.name == pending.customer_name,
                    Customer.owner_phone == business_owner_phone
                ).first()

                # 2. Recent Transaction Guard (Prevents User Manual Retries)
                # Check if an identical transaction was saved in the last 2 minutes
                check_amount = pending.buy_amount if pending.action in ["BUY", "COMBINED"] else pending.paid_amount
                check_type = "BUY" if pending.action == "COMBINED" else pending.action
                
                recent_tx = db.query(Transaction).filter(
                    Transaction.customer_id == customer.id,
                    Transaction.type == check_type,
                    Transaction.amount == check_amount,
                    Transaction.created_at >= datetime.utcnow() - timedelta(minutes=2)
                ).first()

                if recent_tx:
                    send_whatsapp_message(
                        phone,
                        f"⚠️ Hold on! A similar transaction for {customer.name.title()} "
                        f"was already recorded just a moment ago.\n\n"
                        f"If this was a mistake, you can ignore this. If you really want to "
                        f"add it again, please wait a minute or change the amount slightly."
                    )
                    db.delete(pending)
                    db.commit()
                    return {"status": "duplicate_manual_prevention"}

                # Proceed with saving
                if pending.action == "BUY":
                    tx = Transaction(
                        customer_id=customer.id,
                        type="BUY",
                        amount=pending.buy_amount,
                        product=pending.product,
                        quantity=pending.quantity,
                        unit=pending.unit,
                        unit_price=pending.unit_price,
                        due_date=pending.due_date,
                        recorded_by_id=user.id,
                        message_id=message_id,
                        created_at=datetime.utcnow()
                    )
                    db.add(tx)
                    db.flush()
                    if pending_items:
                        add_transaction_items(db, tx.id, pending_items)
                    elif pending.product:
                        add_transaction_items(db, tx.id, [{
                            "product": pending.product,
                            "quantity": pending.quantity or 1,
                            "unit": pending.unit,
                            "unit_price": pending.unit_price or pending.buy_amount,
                            "total": pending.buy_amount
                        }])

                elif pending.action == "PAY":
                    tx = Transaction(
                        customer_id=customer.id,
                        type="PAY",
                        amount=pending.paid_amount,
                        recorded_by_id=user.id,
                        message_id=message_id,
                        created_at=datetime.utcnow()
                    )
                    db.add(tx)
                    if pending.due_date:
                        latest_buy = db.query(Transaction).filter(
                            Transaction.customer_id == customer.id,
                            Transaction.type == "BUY"
                        ).order_by(
                            Transaction.created_at.desc()
                        ).first()
                        if latest_buy:
                            latest_buy.due_date = pending.due_date

                elif pending.action == "COMBINED":
                    buy_tx = Transaction(
                        customer_id=customer.id,
                        type="BUY",
                        amount=pending.buy_amount,
                        product=pending.product,
                        quantity=pending.quantity,
                        unit=pending.unit,
                        unit_price=pending.unit_price,
                        due_date=pending.due_date,
                        recorded_by_id=user.id,
                        message_id=f"{message_id}_buy",
                        created_at=datetime.utcnow()
                    )
                    db.add(buy_tx)
                    db.flush()
                    if pending_items:
                        add_transaction_items(db, buy_tx.id, pending_items)
                    elif pending.product:
                        add_transaction_items(db, buy_tx.id, [{
                            "product": pending.product,
                            "quantity": pending.quantity or 1,
                            "unit": pending.unit,
                            "unit_price": pending.unit_price or pending.buy_amount,
                            "total": pending.buy_amount
                        }])

                    pay_tx = Transaction(
                        customer_id=customer.id,
                        type="PAY",
                        amount=pending.paid_amount,
                        recorded_by_id=user.id,
                        message_id=f"{message_id}_pay",
                        created_at=datetime.utcnow()
                    )
                    db.add(pay_tx)

                memory = db.query(CustomerMemory).filter(
                    CustomerMemory.phone == phone
                ).first()

                if not memory:
                    memory = CustomerMemory(
                        phone=phone,
                        last_customer=customer.name
                    )
                    db.add(memory)
                else:
                    memory.last_customer = customer.name

                db.delete(pending)
                db.commit()

                balance = get_balance(db, customer.id, visible_recorded_by_id)

                if pending.action == "COMBINED":
                    if balance < 0:
                        msg = (
                            f"✅ Saved.\n"
                            f"{customer.name} bought ₦{pending.buy_amount:,} "
                            f"and paid ₦{pending.paid_amount:,}.\n"
                            f"Credit: ₦{abs(balance):,}"
                        )
                    else:
                        msg = (
                            f"✅ Saved.\n"
                            f"{customer.name} bought ₦{pending.buy_amount:,} "
                            f"and paid ₦{pending.paid_amount:,}.\n"
                            f"Balance: ₦{balance:,}"
                        )
                else:
                    if balance < 0:
                        msg = f"✅ Saved.\n{customer.name} credit: ₦{abs(balance):,}"
                    else:
                        msg = f"✅ Saved.\n{customer.name} balance: ₦{balance:,}"

                send_whatsapp_message(phone, msg)
                return {"status": "saved"}

            elif normalized in ["edit", "2", "change"]:
                db.delete(pending)
                db.commit()
                send_whatsapp_message(
                    phone,
                    "Enter again (e.g. Ola paid 2000)"
                )
                return {"status": "edit"}

        if not parsed:
            # Ignore simple pleasantries or short messages from registered users 
            # so we don't spam them with "Message not understood"
            pleasantries = ["thanks", "thank you", "ok", "okay", "done", "bye", "good", "nice", "👍"]
            if text.lower().strip() in pleasantries or len(text) < 2:
                return {"status": "ignored_pleasantry"}

            send_whatsapp_message(
                phone,
                "❌ Message not understood.\n\n"
                "Type:\nFORMATS\n\nor send:\nF\n\n"
                "to see supported transaction examples."
            )
            return {"status": "invalid"}

        if parsed["type"] == "FORMATS":
            msg = (
                "📘 Supported Formats\n\n"
                "🛒 BUY ONLY\nAde bought rice 5000\n\n"
                "💵 PAYMENT ONLY\nAde paid 3000\n\n"
                "🔄 PART PAYMENT\nAde bought rice 5000 paid 2000\n\n"
                "📅 DUE DATE\nAde bought rice 5000 due 12/2/2026\n\n"
                "📅 PART PAYMENT + DUE DATE\n"
                "Ade bought rice 5000 paid 2000 due 12/2/2026\n\n"
                "📌 Date Format:\nUse D/M/YYYY\n\nExample:\n"
                "12/2/2026 = 12 February 2026"
                "\n\n⚙️ SETTINGS\n"
                "To update your business name for better reports and branding, send:\n"
                "*CHANGE NAME*"
            )
            send_whatsapp_message(phone, msg)
            return {"status": "formats"}

        if parsed["type"] == "MY_PLAN":
            send_whatsapp_message(phone, build_plan_message(subscription))
            return {"status": "my_plan"}

        if parsed["type"] == "UPGRADE_MENU":
            db.query(PendingAction).filter(
                PendingAction.phone == phone
            ).delete()
            db.add(
                PendingAction(
                    phone=phone,
                    customer_name="",
                    action="UPGRADE_MENU",
                    last_customer=""
                )
            )
            db.commit()
            send_whatsapp_message(phone, build_upgrade_message())
            return {"status": "upgrade_menu"}

        if parsed["type"] == "SUBSCRIPTION_PAID":
            payment = create_subscription_payment_request(db, user, parsed["plan"])
            db.query(PendingAction).filter(
                PendingAction.phone == phone
            ).delete()
            db.add(
                PendingAction(
                    phone=phone,
                    customer_name=parsed["plan"],
                    action="SUBSCRIPTION_PAYMENT_PENDING",
                    reminder_id=payment.id,
                    last_customer=""
                )
            )
            owner = get_business_owner_user(db, user)
            db.commit()
            notify_subscription_admins(db, payment, owner, evidence_received=False)
            send_whatsapp_message(
                phone,
                f"Thank you. Your {parsed['plan']} subscription request has been received.\n\n"
                "Please send your payment receipt screenshot here. An admin will confirm and activate your plan."
                f"{support_line()}"
            )
            return {"status": "subscription_payment_pending"}

        if parsed["type"] == "PENDING_SUBSCRIPTIONS":
            if not is_subscription_admin(phone, db):
                send_whatsapp_message(phone, "Only subscription admins can view pending subscriptions.")
                return {"status": "unauthorized_pending_subscriptions"}

            payments = db.query(SubscriptionPayment, User).outerjoin(
                User,
                SubscriptionPayment.user_id == User.id
            ).filter(
                SubscriptionPayment.status == "PENDING"
            ).order_by(
                SubscriptionPayment.created_at.asc()
            ).all()
            send_whatsapp_message(phone, format_pending_subscriptions(payments))
            return {"status": "pending_subscriptions"}

        if parsed["type"] == "APP_ADMIN_DASHBOARD":
            if not is_app_admin(phone, db):
                send_whatsapp_message(phone, "Only app admins can view the app admin dashboard.")
                return {"status": "unauthorized_app_admin_dashboard"}

            db.query(PendingAction).filter(
                PendingAction.phone == phone
            ).delete()
            db.add(
                PendingAction(
                    phone=phone,
                    customer_name="",
                    action="APP_ADMIN_DASHBOARD",
                    last_customer=""
                )
            )
            db.commit()
            send_whatsapp_message(phone, build_app_admin_dashboard_message(db))
            return {"status": "app_admin_dashboard"}

        if parsed["type"] == "APP_ADMIN_USERS_BY_PLAN":
            if not is_app_admin(phone, db):
                send_whatsapp_message(phone, "Only app admins can view app users.")
                return {"status": "unauthorized_app_admin_users"}

            users = get_business_users_by_effective_plan(db, parsed["plan"])
            title = "FREE/BASIC Users" if parsed["plan"] == PLAN_BASIC else f"{parsed['plan']} Users"
            send_whatsapp_message(phone, format_user_list(users, title))
            return {"status": "app_admin_users_by_plan"}

        if parsed["type"] == "MANAGE_APP_ADMIN_ROLE":
            if not is_app_admin(phone, db):
                send_whatsapp_message(phone, "Only app admins can manage admin roles.")
                return {"status": "unauthorized_admin_role_management"}

            if not parsed.get("role"):
                send_whatsapp_message(phone, "Unknown admin role.")
                return {"status": "unknown_admin_role"}

            if parsed["role"] == ROLE_APP_ADMIN and parsed["phone"] in app_admin_phones() and not parsed["active"]:
                send_whatsapp_message(
                    phone,
                    "Root app admins from Render APP_ADMIN_PHONES cannot be denied from WhatsApp."
                )
                return {"status": "cannot_deny_root_app_admin"}

            role_record = set_admin_role(
                db,
                parsed["phone"],
                parsed["role"],
                parsed["active"],
                actor_user=user
            )
            db.commit()
            status_text = "allowed" if role_record.is_active else "denied"
            send_whatsapp_message(
                phone,
                f"{role_record.phone} is now {status_text} for {role_record.role}."
            )
            return {"status": "admin_role_updated"}

        if parsed["type"] == "LIST_APP_ADMIN_ROLES":
            if not is_app_admin(phone, db):
                send_whatsapp_message(phone, "Only app admins can view admin roles.")
                return {"status": "unauthorized_admin_role_list"}

            send_whatsapp_message(phone, format_admin_roles(db))
            return {"status": "admin_roles"}

        if parsed["type"] == "APPROVE_SUBSCRIPTION":
            if not is_subscription_admin(phone, db):
                send_whatsapp_message(phone, "Only subscription admins can approve subscriptions.")
                return {"status": "unauthorized_subscription_approval"}

            payment = db.query(SubscriptionPayment).filter(
                SubscriptionPayment.phone == parsed["phone"],
                SubscriptionPayment.status == "PENDING"
            ).order_by(
                SubscriptionPayment.created_at.desc()
            ).first()
            if not payment:
                send_whatsapp_message(phone, "No pending subscription payment found for that phone.")
                return {"status": "subscription_payment_not_found"}

            owner = approve_subscription_payment(db, payment, user)
            db.query(PendingAction).filter(
                PendingAction.phone == owner.phone,
                PendingAction.action == "SUBSCRIPTION_PAYMENT_PENDING"
            ).delete()
            db.commit()
            send_whatsapp_message(
                phone,
                f"Approved {owner.name.title()} for {owner.subscription_plan}.\n"
                f"Expires: {owner.subscription_expires_at.strftime('%d/%m/%Y')}"
            )
            send_whatsapp_message(
                owner.phone,
                f"Your {owner.subscription_plan} plan is now active.\n"
                f"Expires: {owner.subscription_expires_at.strftime('%d/%m/%Y')}\n\n"
                "Send MY PLAN anytime to check your subscription."
            )
            return {"status": "subscription_approved"}

        if parsed["type"] == "REJECT_SUBSCRIPTION":
            if not is_subscription_admin(phone, db):
                send_whatsapp_message(phone, "Only subscription admins can reject subscriptions.")
                return {"status": "unauthorized_subscription_rejection"}

            payment = db.query(SubscriptionPayment).filter(
                SubscriptionPayment.phone == parsed["phone"],
                SubscriptionPayment.status == "PENDING"
            ).order_by(
                SubscriptionPayment.created_at.desc()
            ).first()
            if not payment:
                send_whatsapp_message(phone, "No pending subscription payment found for that phone.")
                return {"status": "subscription_payment_not_found"}

            payment.status = "REJECTED"
            owner = db.query(User).filter(User.id == payment.user_id).first()
            if owner:
                db.query(PendingAction).filter(
                    PendingAction.phone == owner.phone,
                    PendingAction.action == "SUBSCRIPTION_PAYMENT_PENDING"
                ).delete()
            db.commit()
            send_whatsapp_message(phone, "Subscription payment rejected.")
            if owner:
                send_whatsapp_message(
                    owner.phone,
                    "Your subscription payment could not be confirmed. Please send a clearer receipt."
                    f"{support_line()}"
                )
            return {"status": "subscription_rejected"}

        if parsed["type"] == "ACTIVATE_PLAN":
            if not is_subscription_admin(phone, db):
                send_whatsapp_message(phone, "Only subscription admins can activate plans.")
                return {"status": "unauthorized_plan_activation"}

            target_user = db.query(User).filter(
                User.phone == parsed["phone"]
            ).first()
            if not target_user:
                send_whatsapp_message(phone, "User not found for that phone number.")
                return {"status": "plan_target_not_found"}

            target_owner = get_business_owner_user(db, target_user)
            target_owner.subscription_plan = normalize_plan(parsed["plan"])
            target_owner.subscription_status = "ACTIVE"
            if parsed.get("days"):
                target_owner.subscription_expires_at = datetime.utcnow() + timedelta(days=parsed["days"])
            else:
                target_owner.subscription_expires_at = None
            db.commit()

            updated_subscription = get_business_subscription(db, target_owner)
            send_whatsapp_message(
                phone,
                f"Plan updated for {target_owner.name.title()}.\n\n"
                f"{build_plan_message(updated_subscription)}"
            )
            if target_owner.phone != phone:
                send_whatsapp_message(
                    target_owner.phone,
                    f"Your CreditVoice plan is now {target_owner.subscription_plan}."
                )
            return {"status": "plan_activated"}

        if parsed["type"] == "STAFF_MENU":
            # Only primary admins (business owners) should see this menu
            if user.role != "user" or user.parent_id is not None:
                send_whatsapp_message(phone, "❌ Only business owners can view the staff management menu.")
                return {"status": "unauthorized_staff_menu"}

            allowed, upgrade_msg = ensure_feature_allowed(db, user, "STAFF", "Staff management")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "staff_plan_blocked"}

            staff_members = db.query(User).filter(User.parent_id == user.id).all()
            
            if not staff_members:
                send_whatsapp_message(
                    phone, 
                    "You have no staff members registered yet.\n\n"
                    "To add staff, send:\n*ADD STAFF [phone] [name]*"
                )
                return {"status": "staff_menu_empty"}

            msg = "👥 Staff Management\n\n"
            for i, member in enumerate(staff_members, start=1):
                status = "✅ Active" if member.role == "delegate" else "⏳ Pending Invitation"
                access = "Can view all transactions" if member.can_view_all_transactions else "Own records only"
                
                # Calculate totals recorded by this specific staff member
                sales = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
                    Transaction.recorded_by_id == member.id,
                    Transaction.type == "BUY"
                ).scalar()
                
                payments = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
                    Transaction.recorded_by_id == member.id,
                    Transaction.type == "PAY"
                ).scalar()

                msg += (
                    f"{i}. *{member.name.title()}*\n"
                    f"   Status: {status}\n"
                    f"   Access: {access}\n"
                    f"   Recorded: ₦{sales:,} (Sales), ₦{payments:,} (Payments)\n\n"
                )

            msg += (
                "Permission commands:\n"
                "GRANT STAFF [phone] VIEW ALL\n"
                "REVOKE STAFF [phone] VIEW ALL"
            )
            
            send_whatsapp_message(phone, msg)
            return {"status": "staff_menu_sent"}

        if parsed["type"] in ["GRANT_STAFF_VIEW_ALL", "REVOKE_STAFF_VIEW_ALL"]:
            if user.role != "user" or user.parent_id is not None:
                send_whatsapp_message(phone, "Only business owners can change staff permissions.")
                return {"status": "unauthorized_staff_permission"}

            allowed, upgrade_msg = ensure_feature_allowed(db, user, "STAFF_PERMISSION", "Staff permissions")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "staff_permission_plan_blocked"}

            staff_phone = parsed["phone"]
            staff_user = db.query(User).filter(
                User.phone == staff_phone,
                User.parent_id == user.id
            ).first()

            if not staff_user:
                send_whatsapp_message(
                    phone,
                    f"Staff member with phone {staff_phone} not found in your business list."
                )
                return {"status": "staff_not_found"}

            grant_access = parsed["type"] == "GRANT_STAFF_VIEW_ALL"
            staff_user.can_view_all_transactions = grant_access
            db.commit()

            permission_text = "can now view all business transactions" if grant_access else "can now view only their own records"
            send_whatsapp_message(
                phone,
                f"Updated {staff_user.name.title()}: {permission_text}."
            )
            send_whatsapp_message(
                staff_phone,
                f"Your CreditVoice access for *{user.name.title()}* was updated. You {permission_text}."
            )
            return {"status": "staff_permission_updated"}

        if parsed["type"] == "REMOVE_STAFF":
            if user.role != "user" or user.parent_id is not None:
                 send_whatsapp_message(phone, "❌ Only business owners can remove staff.")
                 return {"status": "unauthorized_remove_staff"}

            allowed, upgrade_msg = ensure_feature_allowed(db, user, "STAFF", "Staff management")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "remove_staff_plan_blocked"}

            staff_phone = parsed["phone"]
            staff_user = db.query(User).filter(
                User.phone == staff_phone,
                User.parent_id == user.id
            ).first()

            if not staff_user:
                send_whatsapp_message(
                    phone, 
                    f"❌ Staff member with phone {staff_phone} not found in your business list."
                )
                return {"status": "staff_not_found"}

            staff_name = staff_user.name
            # Reset the staff member to a regular user
            staff_user.role = "user"
            staff_user.parent_id = None
            staff_user.can_view_all_transactions = False
            db.commit()

            send_whatsapp_message(phone, f"✅ Access revoked for {staff_name.title()} ({staff_phone}).")
            # Notify the removed staff member
            send_whatsapp_message(staff_phone, f"📢 Notification: Your access to *{user.name.title()}*'s business data has been revoked.")
            return {"status": "staff_removed"}

        if parsed["type"] == "ADD_STAFF":
            if user.role != "user" or user.parent_id is not None:
                 send_whatsapp_message(phone, "❌ Only business owners can add staff.")
                 return {"status": "unauthorized_add_staff"}

            allowed, upgrade_msg = ensure_feature_allowed(db, user, "STAFF", "Adding staff")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "add_staff_plan_blocked"}

            staff_allowed, staff_limit_msg = check_staff_limit(db, user, subscription)
            if not staff_allowed:
                send_whatsapp_message(phone, staff_limit_msg)
                return {"status": "staff_limit_reached"}

            staff_phone = parsed["phone"]
            staff_name = parsed["name"]
            
            # Check if staff user exists
            staff_user = db.query(User).filter(User.phone == staff_phone).first()
            if staff_user:
                staff_user.role = "delegate_pending"
                staff_user.parent_id = user.id
                staff_user.name = staff_name
                staff_user.can_view_all_transactions = False
            else:
                staff_user = User(
                    phone=staff_phone,
                    name=staff_name,
                    role="delegate_pending",
                    parent_id=user.id,
                    can_view_all_transactions=False
                )
                db.add(staff_user)
            
            db.commit()

            # Notify the Staff Member proactively
            send_whatsapp_message(
                staff_phone,
                f"Hello {staff_name.title()}! *{user.name.title()}* has added you as a staff member on CreditVoice.\n\n"
                "Please reply to this message to view and accept your invitation."
            )

            # Notify the Admin (Business Owner)
            send_whatsapp_message(
                phone,
                f"✅ Staff invitation for *{staff_name.title()}* ({staff_phone}) has been initiated.\n\n"
                f"I have sent an alert to them. We are now waiting for their interaction. You can continue with other tasks, and I will notify you once they accept."
            )
            return {"status": "staff_invited"}

        if parsed["type"] == "RESIGN_REQUEST":
            if user.role != "delegate":
                send_whatsapp_message(phone, "You are not currently registered as staff for any business.")
                return {"status": "resign_not_applicable"}
            
            # Setup confirmation
            res_pending = PendingAction(
                phone=phone,
                action="RESIGN_CONFIRM"
            )
            db.add(res_pending)
            db.commit()
            
            send_whatsapp_message(
                phone,
                f"I received your request to stop working with *{business_name.title()}*.\n\n"
                "Are you sure? This will remove your access to their records.\n\n1. Yes, Confirm\n2. No, Cancel"
            )
            return {"status": "resign_confirm_sent"}

        if parsed["type"] == "REONBOARD":
            # Clear any existing pending actions for this user
            db.query(PendingAction).filter(PendingAction.phone == phone).delete()
            
            # Create a new onboarding pending action
            onboarding = PendingAction(
                phone=phone,
                action="ONBOARD_USER"
            )
            db.add(onboarding)
            db.commit()

            send_whatsapp_message(
                phone,
                "No problem! Let's update your profile.\n\n"
                "Please reply with the *Business Name* you want to use. This name will appear on your reports and customer reminders."
            )
            return {"status": "onboarding_restarted"}

        if parsed["type"] == "SET_PHONE":
            target_name = parsed["name"].lower().strip()
            target_phone = parsed["customer_phone"].strip()

            existing_customer = db.query(Customer).filter(
                Customer.name == target_name,
                Customer.owner_phone == business_owner_phone
            ).first()

            if existing_customer:
                # Update the phone number immediately
                existing_customer.customer_phone = target_phone
                
                # Update any ReminderMemory for this sender and customer
                db.query(ReminderMemory).filter(
                    ReminderMemory.phone == phone,
                    ReminderMemory.customer_name == target_name
                ).update({ReminderMemory.customer_phone: target_phone})
                
                db.commit()

                # If we were in a reminder flow, keep the current flow but inform user
                if pending and pending.action in ["REMINDER_SELECTION", "REMINDER_CONFIRM"]:
                    send_whatsapp_message(
                        phone,
                        f"✅ Saved phone for {existing_customer.name.title()}: {target_phone}\n\n"
                        "Phone set! Now reply *YES* to send the reminder."
                    )
                    return {"status": "reminder_phone_updated"}

            db.query(PendingAction).filter(
                PendingAction.phone == phone,
                PendingAction.action == "ONBOARD_CUSTOMER"
            ).delete()
            db.commit()

            pending_customer = PendingAction(
                phone=phone,
                customer_name=target_name,
                customer_phone=target_phone,
                action="ONBOARD_CUSTOMER"
            )
            db.add(pending_customer)
            db.commit()

            if existing_customer:
                send_whatsapp_message(
                    phone,
                    f"I found an existing customer {target_name.title()} with phone {target_phone}.\n"
                    f"Change the phone to {target_phone}? Reply YES or 1 to update, EDIT or 2 to send it again."
                )
            else:
                send_whatsapp_message(
                    phone,
                    f"I found customer {target_name.title()} with phone {target_phone}.\n"
                    "Reply YES or 1 to save, EDIT or 2 to send it again."
                )
            return {"status": "confirm_onboard_customer"}

        if parsed["type"] == "REMIND":
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "DUE_REMINDERS", "Debt reminders")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "reminder_plan_blocked"}

            parts = parsed["text"].split()
            if len(parts) != 2 or not parts[1].isdigit():
                send_whatsapp_message(phone, "Use:\nREMIND 1")
                return {"status": "invalid_remind"}

            index = int(parts[1])
            reminders = db.query(ReminderMemory).filter(
                ReminderMemory.phone == phone
            ).all()

            if index < 1 or index > len(reminders):
                send_whatsapp_message(phone, "Reminder number not found.")
                return {"status": "reminder_not_found"}

            reminder = reminders[index - 1]
            due_date_text = reminder.due_date.strftime("%d/%m/%Y")

            if reminder.reminder_type == "DUE_TODAY":
                msg = (
                    f"Hello {reminder.customer_name.title()},\n\n"
                    f"This is a reminder that your outstanding balance of "
                    f"₦{reminder.balance:,} is due today.\n\nThank you."
                )
            else:
                msg = (
                    f"Hello {reminder.customer_name.title()},\n\n"
                    f"This is a reminder that your outstanding balance of "
                    f"₦{reminder.balance:,} will be due on {due_date_text}.\n\n"
                    f"Thank you."
                )

            send_whatsapp_message(phone, msg)
            return {"status": "remind"}

        if parsed["type"] == "DUE_MENU":
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "DUE_REMINDERS", "Debt reminders")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "due_menu_plan_blocked"}

            db.query(PendingAction).filter(
                PendingAction.phone == phone
            ).delete()
            db.commit()

            menu_pending = PendingAction(
                phone=phone,
                action="DUE_MENU"
            )
            db.add(menu_pending)
            db.commit()

            send_whatsapp_message(
                phone,
                "📅 Debt Reminder Menu\n\n"
                "1. Due in 2 Days\n2. Due Today\n3. Overdue Debtors\n\n"
                "Reply with:\n1, 2, or 3"
            )
            return {"status": "due_menu"}

        if parsed["type"] == "TODAY_SALES":
            total = get_today_sales(db, business_owner_phone, visible_recorded_by_id)
            send_whatsapp_message(phone, f"📊 Today's sales: ₦{total:,}")
            return {"status": "today_sales"}

        if parsed["type"] == "WEEKLY_SALES":
            total = get_weekly_sales(db, business_owner_phone, visible_recorded_by_id)
            send_whatsapp_message(phone, f"📊 Weekly sales: ₦{total:,}")
            return {"status": "weekly_sales"}

        if parsed["type"] == "MONTHLY_SALES":
            total = get_monthly_sales(db, business_owner_phone, visible_recorded_by_id)
            send_whatsapp_message(phone, f"📊 Monthly sales: ₦{total:,}")
            return {"status": "monthly_sales"}

        if parsed["type"] == "YEARLY_SALES":
            total = get_yearly_sales(db, business_owner_phone, visible_recorded_by_id)
            send_whatsapp_message(phone, f"📊 Yearly sales: ₦{total:,}")
            return {"status": "yearly_sales"}

        if parsed["type"] == "PERIOD_TRANSACTIONS":
            stats = get_transaction_stats(db, business_owner_phone, parsed.get("period"), visible_recorded_by_id)
            period_name = parsed.get("period", "ALL TIME").title()
            send_whatsapp_message(
                phone,
                f"📊 {period_name} transactions: {stats['transaction_count']:,}\n"
                f"Credit sales: ₦{stats['credit_sales']:,}\n"
                f"Direct sales: ₦{stats['direct_sales']:,}\n"
                f"Total sales: ₦{stats['total_sales']:,}\n"
                f"Payments received: ₦{stats['total_pay']:,}"
            )
            return {"status": "period_transactions"}

        if parsed["type"] == "PERIOD_TOTAL_RECEIVED":
            stats = get_transaction_stats(db, business_owner_phone, parsed.get("period"), visible_recorded_by_id)
            label = parsed.get("period", "all time")
            send_whatsapp_message(phone, f"📥 Total received {label}: ₦{stats['total_pay']:,}")
            return {"status": "period_total_received"}

        if parsed["type"] == "PERIOD_TOTAL_PAID":
            stats = get_transaction_stats(db, business_owner_phone, parsed.get("period"), visible_recorded_by_id)
            label = parsed.get("period", "all time")
            send_whatsapp_message(phone, f"📤 Total paid {label}: ₦{stats['total_pay']:,}")
            return {"status": "period_total_paid"}

        if parsed["type"] == "OUTSTANDING_BALANCE":
            total = get_outstanding_balance(db, business_owner_phone, visible_recorded_by_id)
            send_whatsapp_message(phone, f"💰 Total outstanding balance: ₦{total:,}")
            return {"status": "outstanding_balance"}

        if parsed["type"] == "PERIOD_CASH_CREDIT":
            stats = get_transaction_stats(db, business_owner_phone, parsed.get("period"), visible_recorded_by_id)
            measure = parsed.get("measure")
            if measure == "CASH":
                send_whatsapp_message(
                    phone,
                    f"💵 Cash {parsed.get('period', 'all time').lower()}: ₦{stats['total_pay']:,}"
                )
            else:
                send_whatsapp_message(
                    phone,
                    f"💳 Credit {parsed.get('period', 'all time').lower()}: ₦{stats['total_buy']:,}"
                )
            return {"status": "period_cash_credit"}

        if parsed["type"] == "MOST_SOLD_PRODUCT":
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "ADVANCED_REPORTS", "Product reports")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "product_report_plan_blocked"}

            product = get_most_sold_product(db, business_owner_phone, recorded_by_id=visible_recorded_by_id)
            if not product:
                send_whatsapp_message(phone, "No product sales data available yet.")
                return {"status": "no_product_sales"}
            send_whatsapp_message(
                phone,
                f"🏆 Most sold product: {product.product.title()}\n"
                f"Quantity: {product.total_quantity:,}\n"
                f"Sales: ₦{product.total_amount:,}"
            )
            return {"status": "most_sold_product"}

        if parsed["type"] == "PRODUCT_LEADERBOARD":
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "ADVANCED_REPORTS", "Product reports")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "product_report_plan_blocked"}

            results = get_product_sales_by_period(db, business_owner_phone, recorded_by_id=visible_recorded_by_id)
            if not results:
                send_whatsapp_message(phone, "No product sales data available yet.")
                return {"status": "product_leaderboard_empty"}
            msg = "📊 Product Leaderboard\n\n"
            for i, row in enumerate(results[:10], start=1):
                msg += (
                    f"{i}. {row.product.title()} → {row.total_quantity:,} units, ₦{row.total_amount:,}\n"
                )
            send_whatsapp_message(phone, msg)
            return {"status": "product_leaderboard"}

        if parsed["type"] == "PRODUCT_SALES_BY_DATE":
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "ADVANCED_REPORTS", "Product reports")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "product_report_plan_blocked"}

            if not parsed.get("date"):
                send_whatsapp_message(phone, "Send product sales by date DD/MM/YYYY")
                return {"status": "product_sales_by_date_missing"}
            results = get_product_sales_by_date(db, business_owner_phone, parsed["date"], visible_recorded_by_id)
            if not results:
                send_whatsapp_message(phone, f"No product sales found for {parsed['date']}")
                return {"status": "product_sales_by_date_empty"}
            msg = f"📅 Product Sales on {parsed['date']}\n\n"
            for i, row in enumerate(results, start=1):
                msg += (
                    f"{i}. {row.product.title()} → {row.total_quantity:,} units, ₦{row.total_amount:,}\n"
                )
            send_whatsapp_message(phone, msg)
            return {"status": "product_sales_by_date"}

        if parsed["type"] == "CUSTOMER_LIST":
            period = parsed.get("period")
            customers = list_customers(db, business_owner_phone, period, visible_recorded_by_id)
            if not customers:
                label = f" for {period.lower()}" if period else ""
                send_whatsapp_message(phone, f"No customers found{label}.")
                return {"status": "customer_list_empty"}
            
            period_header = f" ({period.title()})" if period else ""
            msg = f"👥 Customers{period_header}\n\n"
            for i, customer in enumerate(customers, start=1):
                msg += (
                    f"{i}. {customer['name'].title()}"
                    f" ({customer['phone'] or 'no phone'}) → ₦{customer['balance']:,}\n"
                )
            send_whatsapp_message(phone, msg)
            return {"status": "customer_list"}

        if parsed["type"] == "CUSTOMER_COUNT":
            period = parsed.get("period")
            count = get_customer_count(db, business_owner_phone, period, visible_recorded_by_id)
            period_label = period.lower() if period else "all time"
            send_whatsapp_message(
                phone,
                f"👥 Customers {period_label}: {count:,}"
            )
            return {"status": "customer_count"}

        if parsed["type"] == "NEW_CUSTOMERS":
            period = parsed.get("period")
            count = get_new_customer_count(db, business_owner_phone, period, visible_recorded_by_id)
            period_label = period.lower() if period else "all time"
            send_whatsapp_message(
                phone,
                f"🆕 New customers {period_label}: {count:,}"
            )
            return {"status": "new_customers"}

        if parsed["type"] == "PAID_CUSTOMERS":
            period = parsed.get("period")
            count = get_paid_customer_count(db, business_owner_phone, period, visible_recorded_by_id)
            period_label = period.lower() if period else "all time"
            send_whatsapp_message(
                phone,
                f"✅ Paid customers {period_label}: {count:,}"
            )
            return {"status": "paid_customers"}

        if parsed["type"] == "DASHBOARD_SUMMARY":
            period = parsed.get("period")
            if period is None and text.lower().strip() in [
                "dashboard",
                "stats",
                "dashboard summary",
                "dashboard stats",
                "business summary",
                "business stats"
            ]:
                db.query(PendingAction).filter(
                    PendingAction.phone == phone
                ).delete()
                db.add(
                    PendingAction(
                        phone=phone,
                        customer_name="",
                        action="DASHBOARD_MENU",
                        last_customer=""
                    )
                )
                db.commit()
                send_whatsapp_message(phone, build_dashboard_menu_message())
                return {"status": "dashboard_menu"}

            summary = get_dashboard_summary(db, business_owner_phone, period, visible_recorded_by_id)
            send_whatsapp_message(phone, build_dashboard_summary_message(summary, period))
            return {"status": "dashboard_summary"}

            period_label = period.lower() if period else "all time"
            total_customers = get_customer_count(db, business_owner_phone, period)
            new_customers = get_new_customer_count(db, business_owner_phone, period)
            paid_customers = get_paid_customer_count(db, business_owner_phone, period)
            stats = get_transaction_stats(db, business_owner_phone, period)
            send_whatsapp_message(
                phone,
                f"📊 Dashboard {period_label}:\n"
                f"Total customers: {total_customers:,}\n"
                f"New customers: {new_customers:,}\n"
                f"Paid customers: {paid_customers:,}\n"
                f"Transactions: {stats['transaction_count']:,}\n"
                f"Sales: ₦{stats['total_buy']:,}\n"
                f"Received: ₦{stats['total_pay']:,}"
            )
            return {"status": "dashboard_summary"}

        if parsed["type"] == "BIGGEST_DEBTOR":
            debtor = get_biggest_debtor(db, business_owner_phone, visible_recorded_by_id)
            if not debtor:
                send_whatsapp_message(phone, "No debtors found.")
                return {"status": "biggest_debtor_empty"}
            send_whatsapp_message(
                phone,
                f"🔝 Biggest debtor: {debtor['name'].title()} → ₦{debtor['balance']:,}"
            )
            return {"status": "biggest_debtor"}

        if parsed["type"] == "DEBTOR_LEADERBOARD":
            leaderboard = get_debtor_leaderboard(db, business_owner_phone, recorded_by_id=visible_recorded_by_id)
            if not leaderboard:
                send_whatsapp_message(phone, "No debtors found.")
                return {"status": "debtor_leaderboard_empty"}
            msg = "📋 Debtor Leaderboard\n\n"
            for i, debtor in enumerate(leaderboard, start=1):
                msg += f"{i}. {debtor['name'].title()} → ₦{debtor['balance']:,}\n"
            send_whatsapp_message(phone, msg)
            return {"status": "debtor_leaderboard"}

        if parsed["type"] == "SEARCH_CUSTOMER":
            customers = search_customers(db, business_owner_phone, parsed.get("query", ""), visible_recorded_by_id)
            if not customers:
                send_whatsapp_message(phone, "Customer not found.")
                return {"status": "search_customer_empty"}
            msg = "🔍 Search results\n\n"
            for i, customer in enumerate(customers, start=1):
                msg += f"{i}. {customer.name.title()} → {customer.customer_phone or 'no phone'}\n"
            send_whatsapp_message(phone, msg)
            return {"status": "search_customer"}

        if parsed["type"] == "CUSTOMER_SUMMARY":
            summary = get_customer_summary(db, business_owner_phone, parsed.get("name", ""), visible_recorded_by_id)
            if not summary:
                send_whatsapp_message(phone, "Customer not found.")
                return {"status": "customer_summary_not_found"}
            balance_text = (
                f"credit: ₦{abs(summary['balance']):,}" if summary['balance'] < 0 else f"balance: ₦{summary['balance']:,}"
            )
            send_whatsapp_message(
                phone,
                f"📋 {summary['name'].title()} summary\n"
                f"{balance_text}\n"
                f"Bought: ₦{summary['total_buy']:,}\n"
                f"Paid: ₦{summary['total_pay']:,}\n"
                f"Transactions: {summary['transaction_count']:,}"
            )
            return {"status": "customer_summary"}

        if parsed["type"] == "ADD_TRANSACTION_NOTE":
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "TRANSACTION_NOTES", "Transaction notes")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "transaction_notes_plan_blocked"}

            visible_tx = get_visible_transaction(
                db,
                business_owner_phone,
                parsed["transaction_id"],
                visible_recorded_by_id
            )
            if not visible_tx:
                send_whatsapp_message(phone, "Transaction not found.")
                return {"status": "transaction_note_not_found"}

            transaction, customer = visible_tx
            note = TransactionNote(
                transaction_id=transaction.id,
                author_user_id=user.id,
                note=parsed["note"]
            )
            db.add(note)
            db.commit()
            transaction_name = customer.name.title() if customer else "direct sale"
            send_whatsapp_message(
                phone,
                f"Note added to transaction #{transaction.id} for {transaction_name}."
            )
            return {"status": "transaction_note_added"}

        if parsed["type"] == "TRANSACTION_NOTES":
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "TRANSACTION_NOTES", "Transaction notes")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "transaction_notes_plan_blocked"}

            visible_tx, notes = get_transaction_notes(
                db,
                business_owner_phone,
                parsed["transaction_id"],
                visible_recorded_by_id
            )
            if not visible_tx:
                send_whatsapp_message(phone, "Transaction not found.")
                return {"status": "transaction_notes_not_found"}

            transaction, customer = visible_tx
            send_whatsapp_message(
                phone,
                format_transaction_note_thread(transaction, customer, notes)
            )
            return {"status": "transaction_notes"}

        if parsed["type"] == "CUSTOMER_TRANSACTIONS":
            customer = db.query(Customer).filter(
                Customer.name == parsed.get("name", ""),
                Customer.owner_phone == business_owner_phone
            ).first()
            if not customer:
                send_whatsapp_message(phone, "Customer not found.")
                return {"status": "customer_transactions_not_found"}
            buy_query = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
                Transaction.customer_id == customer.id,
                Transaction.type == "BUY"
            )
            pay_query = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
                Transaction.customer_id == customer.id,
                Transaction.type == "PAY"
            )
            tx_query = db.query(Transaction).filter(
                Transaction.customer_id == customer.id
            )
            if visible_recorded_by_id:
                buy_query = buy_query.filter(Transaction.recorded_by_id == visible_recorded_by_id)
                pay_query = pay_query.filter(Transaction.recorded_by_id == visible_recorded_by_id)
                tx_query = tx_query.filter(Transaction.recorded_by_id == visible_recorded_by_id)
            tx_count = tx_query.count()
            if visible_recorded_by_id and tx_count == 0:
                send_whatsapp_message(phone, "Customer not found.")
                return {"status": "customer_transactions_not_found"}
            total_buy = buy_query.scalar()
            total_pay = pay_query.scalar()
            recent_transactions = tx_query.order_by(
                Transaction.created_at.desc()
            ).limit(5).all()
            recent_lines = ""
            if recent_transactions:
                recent_lines = "\n\nRecent transactions\n"
                for tx in recent_transactions:
                    tx_date = tx.created_at.strftime("%d/%m/%Y")
                    recent_lines += f"#{tx.id} {tx_date} {tx.type}: N{tx.amount:,}\n"
                recent_lines += "\nAdd note:\nnote transaction 12 customer promised Friday"
            send_whatsapp_message(
                phone,
                f"📊 {customer.name.title()} transactions\n"
                f"Total: {tx_count:,}\n"
                f"Bought: ₦{total_buy:,}\n"
                f"Paid: ₦{total_pay:,}"
                f"{recent_lines}"
            )
            return {"status": "customer_transactions"}

        if parsed["type"] == "OVERDUE_DEBTORS":
            overdue_list = get_overdue_debtors(db, business_owner_phone, visible_recorded_by_id)
            if len(overdue_list) == 0:
                send_whatsapp_message(phone, "✅ No overdue debtors.")
                return {"status": "no_overdue"}

            msg = "📋 Overdue Debtors\n\n"
            for i, debtor in enumerate(overdue_list, start=1):
                due_date_text = debtor["due_date"].strftime("%d/%m/%Y")
                msg += (
                    f"{i}. {debtor['name']}\n"
                    f"Balance: ₦{debtor['balance']:,}\n"
                    f"Due: {due_date_text}\n"
                    f"Overdue: {debtor['overdue_days']} days\n\n"
                )

            send_whatsapp_message(phone, msg)
            return {"status": "overdue_direct"}

        if parsed["type"] == "UNPAID_DEBTORS":
            debtors, total_outstanding = get_unpaid_debtors(db, business_owner_phone, visible_recorded_by_id)
            if len(debtors) == 0:
                send_whatsapp_message(phone, "✅ No unpaid debtors.")
                return {"status": "no_debtors"}

            msg = "📋 Unpaid Debtors\n\n"
            for i, debtor in enumerate(debtors, start=1):
                msg += f"{i}. {debtor['name']} → ₦{debtor['balance']:,}\n"

            msg += f"\n💰 Total Outstanding: ₦{total_outstanding:,}"
            send_whatsapp_message(phone, msg)
            return {"status": "unpaid_debtors"}

        if parsed["type"] == "BALANCE":
            name = text.replace("balance", "").strip().lower()
            customer = db.query(Customer).filter(
                Customer.name == name,
                Customer.owner_phone == business_owner_phone
            ).first()

            if not customer:
                send_whatsapp_message(phone, "Customer not found.")
                return {"status": "not_found"}

            balance = get_balance(db, customer.id, visible_recorded_by_id)
            if visible_recorded_by_id:
                has_customer_access = db.query(Transaction).filter(
                    Transaction.customer_id == customer.id,
                    Transaction.recorded_by_id == visible_recorded_by_id
                ).first()
                if not has_customer_access:
                    send_whatsapp_message(phone, "Customer not found.")
                    return {"status": "not_found"}
            if balance < 0:
                msg = f"{customer.name} credit: ₦{abs(balance):,}"
            else:
                msg = f"{customer.name} balance: ₦{balance:,}"

            send_whatsapp_message(phone, msg)
            return {"status": "balance"}

        # Handle pronoun references
        if parsed["action"] == "SALE":
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "DIRECT_SALE", "Direct sales")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "direct_sale_plan_blocked"}

            transaction_allowed, transaction_limit_msg = check_monthly_transaction_limit(
                db,
                business_owner_phone,
                subscription,
                planned_rows=1
            )
            if not transaction_allowed:
                send_whatsapp_message(phone, transaction_limit_msg)
                return {"status": "transaction_limit_reached"}

            db.query(PendingAction).filter(
                PendingAction.phone == phone
            ).delete()
            db.commit()

            pending = PendingAction(
                phone=phone,
                customer_name="",
                last_customer="",
                action="SALE",
                buy_amount=parsed["buy_amount"],
                product=parsed.get("product"),
                quantity=parsed.get("quantity"),
                unit=parsed.get("unit"),
                unit_price=parsed.get("unit_price"),
                items_json=json.dumps(parsed.get("invoice_items") or [])
            )
            db.add(pending)
            db.commit()

            if parsed.get("invoice_items"):
                item_line = (
                    f"{format_invoice_items(parsed['invoice_items'])}\n\n"
                    f"Total: ₦{parsed['total']:,}"
                )
            elif parsed.get("quantity") and parsed.get("unit"):
                item_line = (
                    f"{parsed['quantity']} {parsed['unit']} of {parsed['product']} "
                    f"at ₦{parsed['unit_price']:,}, total: ₦{parsed['total']:,}"
                )
            elif parsed.get("quantity") and parsed["quantity"] > 1:
                item_line = (
                    f"{parsed['quantity']} {parsed['product']} "
                    f"at ₦{parsed['unit_price']:,}, total: ₦{parsed['total']:,}"
                )
            else:
                item_line = f"{parsed['product']} - ₦{parsed['total']:,}"

            send_whatsapp_message(
                phone,
                f"Confirm direct sale:\n{item_line}\n"
                f"Reply YES or 1 to save, EDIT or 2 to change."
            )
            return {"status": "confirm_direct_sale"}

        customer_name = parsed["name"].lower()

        if customer_name in ["he", "she"]:
            memory = db.query(CustomerMemory).filter(
                CustomerMemory.phone == phone
            ).first()

            if memory and memory.last_customer:
                customer_name = memory.last_customer.lower()
            else:
                send_whatsapp_message(phone, "No previous customer found.")
                return {"status": "no_memory"}

        if parsed.get("invoice_items"):
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "INVOICE", "Invoice-style multi-item sales")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "invoice_plan_blocked"}

        # Get or create customer
        customer = db.query(Customer).filter(
            Customer.name == customer_name,
            Customer.owner_phone == business_owner_phone
        ).first()

        if not customer:
            customer_allowed, customer_limit_msg = check_customer_limit(
                db,
                business_owner_phone,
                subscription
            )
            if not customer_allowed:
                send_whatsapp_message(phone, customer_limit_msg)
                return {"status": "customer_limit_reached"}

            customer = Customer(
                name=customer_name,
                owner_phone=business_owner_phone
            )
            db.add(customer)
            db.commit()

        planned_rows = 2 if parsed["action"] == "COMBINED" else 1
        transaction_allowed, transaction_limit_msg = check_monthly_transaction_limit(
            db,
            business_owner_phone,
            subscription,
            planned_rows=planned_rows
        )
        if not transaction_allowed:
            send_whatsapp_message(phone, transaction_limit_msg)
            return {"status": "transaction_limit_reached"}

        # Clear pending and save new pending
        db.query(PendingAction).filter(
            PendingAction.phone == phone
        ).delete()
        db.commit()

        pending = PendingAction(
            phone=phone,
            customer_name=customer.name,
            last_customer=customer.name,
            action=parsed["action"],
            buy_amount=parsed["buy_amount"],
            paid_amount=parsed["paid_amount"],
            product=parsed.get("product"),
            quantity=parsed.get("quantity"),
            unit=parsed.get("unit"),
            unit_price=parsed.get("unit_price"),
            items_json=json.dumps(parsed.get("invoice_items") or []),
            due_date=parsed["due_date"]
        )

        db.add(pending)
        db.commit()

        # Send confirmation
        if parsed["action"] == "BUY":
            if parsed.get("invoice_items"):
                item_line = (
                    f"{format_invoice_items(parsed['invoice_items'])}\n\n"
                    f"Total: ₦{parsed['total']:,}"
                )
                if parsed["due_date"]:
                    due_date_text = parsed["due_date"].strftime("%d/%m/%Y")
                    confirm_msg = (
                        f"Confirm invoice for {customer.name}:\n{item_line}\n"
                        f"Due: {due_date_text}\nReply YES or 1 to save, EDIT or 2 to change."
                    )
                else:
                    confirm_msg = (
                        f"Confirm invoice for {customer.name}:\n{item_line}\n"
                        f"Reply YES or 1 to save, EDIT or 2 to change."
                    )
            elif parsed.get("quantity") and parsed.get("unit") and parsed.get("product") and parsed.get("unit_price"):
                item_line = (
                    f"{parsed['quantity']} {parsed['unit']} of {parsed['product']} "
                    f"at ₦{parsed['unit_price']:,} each, total: ₦{parsed['total']:,}"
                )
                if parsed["due_date"]:
                    due_date_text = parsed["due_date"].strftime("%d/%m/%Y")
                    confirm_msg = (
                        f"Confirm:\n{customer.name} bought {item_line}\n"
                        f"Due: {due_date_text}\nReply YES or 1 to save, EDIT or 2 to change."
                    )
                else:
                    confirm_msg = (
                        f"Confirm:\n{customer.name} bought {item_line}\n"
                        f"Reply YES or 1 to save, EDIT or 2 to change."
                    )
            elif parsed["due_date"]:
                due_date_text = parsed["due_date"].strftime("%d/%m/%Y")
                confirm_msg = (
                    f"Confirm:\n{customer.name} bought ₦{parsed['buy_amount']:,}\n"
                    f"Due: {due_date_text}\nReply YES or 1 to save, EDIT or 2 to change."
                )
            else:
                confirm_msg = (
                    f"Confirm:\n{customer.name} bought ₦{parsed['buy_amount']:,}?\n"
                    f"Reply YES or 1 to save, EDIT or 2 to change."
                )

        elif parsed["action"] == "PAY":
            confirm_msg = (
                f"Confirm:\n{customer.name} paid ₦{parsed['paid_amount']:,}?\n"
                f"Reply YES or 1 to save, EDIT or 2 to change."
            )

        elif parsed["action"] == "COMBINED":
            if parsed.get("invoice_items"):
                item_line = (
                    f"\n{format_invoice_items(parsed['invoice_items'])}\n\n"
                    f"Total bought: ₦{parsed['buy_amount']:,}"
                )
            elif parsed.get("quantity") and parsed.get("unit") and parsed.get("product") and parsed.get("unit_price"):
                item_line = (
                    f"{parsed['quantity']} {parsed['unit']} of {parsed['product']} at ₦{parsed['unit_price']:,} each, total: ₦{parsed['total']:,}"
                )
            else:
                item_line = f"₦{parsed['buy_amount']:,}"

            if parsed["due_date"]:
                due_date_text = parsed["due_date"].strftime("%d/%m/%Y")
                confirm_msg = (
                    f"Confirm:\n{customer.name} bought {item_line}\n"
                    f"and paid ₦{parsed['paid_amount']:,}\n"
                    f"Balance due on: {due_date_text}\nReply YES or 1 to save, EDIT or 2 to change."
                )
            else:
                confirm_msg = (
                    f"Confirm:\n{customer.name} bought {item_line}\n"
                    f"and paid ₦{parsed['paid_amount']:,}?\n"
                    f"Reply YES or 1 to save, EDIT or 2 to change."
                )

        send_whatsapp_message(phone, confirm_msg)
        return {"status": "pending"}

    finally:
        db.close()


