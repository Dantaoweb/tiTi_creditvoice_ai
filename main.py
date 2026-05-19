import os
import re
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
    Integer,
    String,
    DateTime,
    ForeignKey,
    func,
    inspect
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

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


class Transaction(Base):

    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)

    customer_id = Column(
        Integer,
        ForeignKey("customers.id")
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
        r"(?P<quantity>\d+)\s+"
        r"(?P<unit>[a-z/]+)\s+(?:of\s+)?"
        r"(?P<product>[a-z ]+?)\s+at\s+(?P<unit_price>" + amount_pattern + ")",
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
    matches = re.findall(
        r"(?<![\d/])\d[\d,\.]*\s*(?:[kK](?![a-zA-Z])|[mM](?![a-zA-Z]))?(?![\d/])", 
        text
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

    # Matches "list customers", "customers today", "customer list this week", etc.
    if any(cmd in clean_text for cmd in ["list customers", "customer list"]) or clean_text.startswith("customers"):
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
    ):
        return {
            "type": "DASHBOARD_SUMMARY",
            "period": parse_period_phrase(clean_text)
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

    if clean_text.endswith("transactions"):
        candidate = clean_text.replace("transactions", "").replace("customer", "").strip()
        if candidate:
            return {
                "type": "CUSTOMER_TRANSACTIONS",
                "name": candidate
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

    clean_text = text.replace(",", "")

    words = clean_text.split()

    amounts = extract_amounts(clean_text)

    if len(amounts) == 0:
        return None

    item_details = extract_item_details(text)

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

    has_buy = bool(re.search(r"\b(" + "|".join(buy_keywords) + r")\b", clean_text))
    has_pay = bool(re.search(r"\b(" + "|".join(pay_keywords) + r")\b", clean_text))

    # =========================
    # 🔄 COMBINED
    # =========================

    if has_buy and has_pay:

        if item_details and len(amounts) >= 3:
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
        "total": total if total is not None else buy_amount,
        "due_date": due_date
    }


# =========================
# 💰 BALANCE
# =========================

def get_balance(db, customer_id):

    from sqlalchemy import func

    total_buy = db.query(
        func.coalesce(
            func.sum(Transaction.amount),
            0
        )
    ).filter(
        Transaction.customer_id == customer_id,
        Transaction.type == "BUY"
    ).scalar()

    total_pay = db.query(
        func.coalesce(
            func.sum(Transaction.amount),
            0
        )
    ).filter(
        Transaction.customer_id == customer_id,
        Transaction.type == "PAY"
    ).scalar()

    return total_buy - total_pay

# =========================
# 📊 SALES ANALYTICS
# =========================

def get_today_sales(db, owner_phone=None):
    stats = get_transaction_stats(db, owner_phone, "TODAY")
    return stats["total_buy"]


def get_weekly_sales(db, owner_phone=None):
    stats = get_transaction_stats(db, owner_phone, "WEEK")
    return stats["total_buy"]


def get_monthly_sales(db, owner_phone=None):
    stats = get_transaction_stats(db, owner_phone, "MONTH")
    return stats["total_buy"]


def get_yearly_sales(db, owner_phone=None):
    stats = get_transaction_stats(db, owner_phone, "YEAR")
    return stats["total_buy"]


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


def get_owner_transaction_query(db, owner_phone, period=None):
    query = db.query(Transaction).join(Customer, Transaction.customer_id == Customer.id).filter(
        Customer.owner_phone == owner_phone
    )
    if period:
        start, end = get_period_range(period)
        if start and end:
            query = query.filter(
                Transaction.created_at >= start,
                Transaction.created_at < end
            )
    return query


def get_transaction_stats(db, owner_phone, period=None):
    query = get_owner_transaction_query(db, owner_phone, period)
    total_buy = query.filter(Transaction.type == "BUY").with_entities(
        func.coalesce(func.sum(Transaction.amount), 0)
    ).scalar()
    total_pay = query.filter(Transaction.type == "PAY").with_entities(
        func.coalesce(func.sum(Transaction.amount), 0)
    ).scalar()
    transaction_count = query.count()
    return {
        "total_buy": total_buy,
        "total_pay": total_pay,
        "transaction_count": transaction_count
    }


def get_total_outstanding(db, owner_phone=None):
    debtors, total_outstanding = get_unpaid_debtors(db, owner_phone)
    return total_outstanding


def get_customer_count(db, owner_phone=None, period=None):
    query = db.query(Customer)
    if owner_phone:
        query = query.filter(Customer.owner_phone == owner_phone)
    if period:
        start, end = get_period_range(period)
        if start and end:
            query = query.filter(
                Customer.created_at >= start,
                Customer.created_at < end
            )
    return query.count()


def get_new_customer_count(db, owner_phone=None, period=None):
    return get_customer_count(db, owner_phone, period)


def get_paid_customer_count(db, owner_phone=None, period=None):
    query = db.query(Customer).join(
        Transaction,
        Transaction.customer_id == Customer.id
    ).filter(
        Transaction.type == "PAY"
    )
    if owner_phone:
        query = query.filter(Customer.owner_phone == owner_phone)
    if period:
        start, end = get_period_range(period)
        if start and end:
            query = query.filter(
                Transaction.created_at >= start,
                Transaction.created_at < end
            )
    return query.distinct(Customer.id).count()


def get_total_transaction_count(db, owner_phone=None, period=None):
    return get_owner_transaction_query(db, owner_phone, period).count()


def list_customers(db, owner_phone=None, period=None):
    query = db.query(Customer)
    if owner_phone:
        query = query.filter(Customer.owner_phone == owner_phone)

    if period:
        start, end = get_period_range(period)
        if start and end:
            query = query.filter(
                Customer.created_at >= start,
                Customer.created_at < end
            )

    customers = query.all()
    result = []
    for customer in customers:
        result.append({
            "name": customer.name,
            "phone": customer.customer_phone,
            "balance": get_balance(db, customer.id)
        })
    return result


def get_biggest_debtor(db, owner_phone=None):
    debtors, _ = get_unpaid_debtors(db, owner_phone)
    if not debtors:
        return None
    return max(debtors, key=lambda item: item["balance"])


def get_debtor_leaderboard(db, owner_phone=None, limit=10):
    debtors, _ = get_unpaid_debtors(db, owner_phone)
    return sorted(debtors, key=lambda item: item["balance"], reverse=True)[:limit]


def get_customer_summary(db, owner_phone, name):
    customer = db.query(Customer).filter(
        Customer.owner_phone == owner_phone,
        Customer.name == name
    ).first()
    if not customer:
        return None
    total_buy = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.customer_id == customer.id,
        Transaction.type == "BUY"
    ).scalar()
    total_pay = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.customer_id == customer.id,
        Transaction.type == "PAY"
    ).scalar()
    transaction_count = db.query(Transaction).filter(
        Transaction.customer_id == customer.id
    ).count()
    return {
        "name": customer.name,
        "balance": get_balance(db, customer.id),
        "total_buy": total_buy,
        "total_pay": total_pay,
        "transaction_count": transaction_count
    }


def search_customers(db, owner_phone, query_text):
    return db.query(Customer).filter(
        Customer.owner_phone == owner_phone,
        Customer.name.ilike(f"%{query_text}%")
    ).all()


def get_product_sales_by_period(db, owner_phone=None, period=None):
    query = db.query(
        Transaction.product,
        func.coalesce(func.sum(Transaction.quantity), 0).label("total_quantity"),
        func.coalesce(func.sum(Transaction.amount), 0).label("total_amount")
    ).join(Customer, Transaction.customer_id == Customer.id).filter(
        Transaction.type == "BUY",
        Transaction.product.isnot(None)
    )
    if owner_phone:
        query = query.filter(Customer.owner_phone == owner_phone)
    if period:
        start, end = get_period_range(period)
        query = query.filter(
            Transaction.created_at >= start,
            Transaction.created_at < end
        )
    query = query.group_by(Transaction.product).order_by(func.sum(Transaction.quantity).desc())
    return query.all()


def get_most_sold_product(db, owner_phone=None, period=None):
    results = get_product_sales_by_period(db, owner_phone, period)
    if not results:
        return None
    return results[0]


def get_product_sales_by_date(db, owner_phone, date_text):
    try:
        report_date = datetime.strptime(date_text, "%d/%m/%Y").date()
    except ValueError:
        return None
    start = datetime(report_date.year, report_date.month, report_date.day)
    end = start + timedelta(days=1)

    results = db.query(
        Transaction.product,
        func.coalesce(func.sum(Transaction.quantity), 0).label("total_quantity"),
        func.coalesce(func.sum(Transaction.amount), 0).label("total_amount")
    ).join(Customer, Transaction.customer_id == Customer.id).filter(
        Customer.owner_phone == owner_phone,
        Transaction.type == "BUY",
        Transaction.product.isnot(None),
        Transaction.created_at >= start,
        Transaction.created_at < end
    ).group_by(Transaction.product).order_by(func.sum(Transaction.quantity).desc()).all()

    return results


def get_total_paid_today(db, owner_phone=None):
    today = datetime.utcnow().date()
    query = db.query(func.coalesce(func.sum(Transaction.amount), 0)).join(Customer, Transaction.customer_id == Customer.id)
    if owner_phone:
        query = query.filter(Customer.owner_phone == owner_phone)
    total = query.filter(
        Transaction.type == "PAY",
        func.date(Transaction.created_at) == today
    ).scalar()
    return total


def get_outstanding_balance(db, owner_phone=None):
    return get_total_outstanding(db, owner_phone)

# =========================
# 📋 UNPAID DEBTORS
# =========================

def get_unpaid_debtors(db, owner_phone=None):

    customers = db.query(Customer)
    if owner_phone:
        customers = customers.filter(Customer.owner_phone == owner_phone)
    customers = customers.all()

    debtors = []

    total_outstanding = 0

    for customer in customers:

        balance = get_balance(db, customer.id)

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

def get_overdue_debtors(db, owner_phone=None):

    overdue_list = []

    customers = db.query(Customer)
    if owner_phone:
        customers = customers.filter(Customer.owner_phone == owner_phone)
    customers = customers.all()

    today = datetime.utcnow()

    for customer in customers:

        balance = get_balance(db, customer.id)

        if balance <= 0:
            continue

        latest_tx = db.query(Transaction).filter(
            Transaction.customer_id == customer.id,
            Transaction.type == "BUY",
            Transaction.due_date.isnot(None)
        ).order_by(
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

def get_due_today(db, owner_phone=None):

    due_today = []

    customers = db.query(Customer)
    if owner_phone:
        customers = customers.filter(Customer.owner_phone == owner_phone)
    customers = customers.all()

    today = datetime.utcnow().date()

    for customer in customers:

        balance = get_balance(db, customer.id)

        if balance <= 0:
            continue

        latest_tx = db.query(Transaction).filter(
            Transaction.customer_id == customer.id,
            Transaction.type == "BUY",
            Transaction.due_date.isnot(None)
        ).order_by(
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

def get_due_in_2_days(db, owner_phone=None):

    due_list = []

    customers = db.query(Customer)
    if owner_phone:
        customers = customers.filter(Customer.owner_phone == owner_phone)
    customers = customers.all()

    target_date = (
        datetime.utcnow().date()
        + timedelta(days=2)
    )

    for customer in customers:

        balance = get_balance(db, customer.id)

        if balance <= 0:
            continue

        latest_tx = db.query(Transaction).filter(
            Transaction.customer_id == customer.id,
            Transaction.type == "BUY",
            Transaction.due_date.isnot(None)
        ).order_by(
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
        stats = get_transaction_stats(db, owner_phone, period_key)
        return {
            "total_customers": get_customer_count(db, owner_phone, None),
            "new_customers": get_new_customer_count(db, owner_phone, period_key),
            "paid_customers": get_paid_customer_count(db, owner_phone, period_key),
            "total_transactions": get_total_transaction_count(db, owner_phone, period_key),
            "total_buy_amount": stats["total_buy"],
            "total_pay_amount": stats["total_pay"]
        }
    finally:
        db.close()


@app.get("/dashboard/ui", response_class=HTMLResponse)
def dashboard_ui(owner_phone: Optional[str] = None, period: Optional[str] = None):
    db = SessionLocal()
    try:
        period_key = period.upper() if period else None
        stats = get_transaction_stats(db, owner_phone, period_key)
        total_customers = get_customer_count(db, owner_phone, None)
        new_customers = get_new_customer_count(db, owner_phone, period_key)
        paid_customers = get_paid_customer_count(db, owner_phone, period_key)
        total_transactions = get_total_transaction_count(db, owner_phone, period_key)
        period_label = period_key.lower() if period_key else "all time"
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
                    <div class="metric"><strong>Total sales:</strong> ₦{stats['total_buy']:,}</div>
                    <div class="metric"><strong>Total received:</strong> ₦{stats['total_pay']:,}</div>
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
                        send_whatsapp_message(
                            phone,
                            "Welcome to CreditVoice.\n\n"
                            "This WhatsApp number is not registered yet. Please "
                            "onboard it as a business owner or add it as staff first."
                        )
                        return {"status": "unregistered"}

                    pending = debug_db.query(PendingAction).filter(
                        PendingAction.phone == phone
                    ).order_by(
                        PendingAction.created_at.desc()
                    ).first()

                    if text.lower().strip() == "due":
                        print("Due direct handler reached", flush=True)
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
                            due_list = get_due_in_2_days(debug_db, business_owner_phone)
                            title = "Due in 2 Days"
                            empty_msg = "No debts due in 2 days."
                            reminder_type = "DUE_2_DAYS"
                        elif text.strip() == "2":
                            due_list = get_due_today(debug_db, business_owner_phone)
                            title = "Due Today"
                            empty_msg = "No debts due today."
                            reminder_type = "DUE_TODAY"
                        else:
                            due_list = get_overdue_debtors(debug_db, business_owner_phone)
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
    except Exception as exc:
        print("Webhook early parse error:", repr(exc), flush=True)

    data = await req.json()

    try:
        message = (
            data["entry"][0]
            ["changes"][0]
            ["value"]["messages"][0]
        )

        text = message["text"]["body"].strip()

        phone = message["from"]

        message_type = message.get("type", "text")
        message_id = message["id"]

    except:
        print("Webhook ignored before reply", flush=True)
        return {"status": "ignored"}

    db = SessionLocal()

    try:
        # Only process actual text messages to avoid responding to 
        # reactions, locations, or media without context
        if message_type != "text":
            return {"status": "ignored_non_text"}

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

        # Logic for Pending Invitations
        if user and user.role == "delegate_pending":
            normalized = text.strip()
            if normalized == "1":
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
            elif normalized == "2":
                user.role = "user"
                user.parent_id = None
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

        # Parse message early to check if it's an explicit command
        parsed = parse_message(text)
        is_command = parsed and parsed["type"] != "TRANSACTION"

        pending = db.query(PendingAction).filter(
            PendingAction.phone == phone,
            PendingAction.action != None
        ).order_by(
            PendingAction.created_at.desc()
        ).first()

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
                    msg = (
                        f"✅ Registration Successful!\n\n"
                        f"Welcome {name_to_save.title()}, you are now set up on CreditVoice. I am TITI, your assistant.\n\n"
                        "You can now start managing your debts and payments. To add your first customer, send their name and phone number like this:\n\n"
                        "*John 08012345678*"
                    )

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

            if text.lower() in ["continue", "start", "yes", "ok", "1"]:
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
                    "Great! To finish your registration, please reply with your name or business name."
                )
                return {"status": "onboarding_started"}

            # Only send the welcome message if the user actually tried to 
            # engage with a greeting or a start command.
            onboarding_triggers = ["hello", "hi", "hey", "start", "onboard", "titi", "begin", "1", "continue"]
            if text.lower().strip() in onboarding_triggers:
                send_whatsapp_message(
                    phone,
                    "Welcome to CreditVoice! I am TITI.\n\n"
                    "Reply CONTINUE or 1 to begin onboarding."
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
            if pending.action == "DUE_MENU":
                # Handle DUE_MENU responses (1, 2, 3)
                if text == "1":
                    # Due in 2 days logic
                    due_list = get_due_in_2_days(db, business_owner_phone)
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
                    due_today = get_due_today(db, business_owner_phone)
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

                    overdue_list = get_overdue_debtors(db, business_owner_phone)
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
                customer = db.query(Customer).filter(
                    Customer.name == pending.customer_name,
                    Customer.owner_phone == phone
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
                        due_date=pending.due_date,
                        recorded_by_id=user.id,
                        message_id=message_id,
                        created_at=datetime.utcnow()
                    )
                    db.add(tx)

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
                        due_date=pending.due_date,
                        recorded_by_id=user.id,
                        message_id=f"{message_id}_buy",
                        created_at=datetime.utcnow()
                    )
                    db.add(buy_tx)

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

                balance = get_balance(db, customer.id)

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

        if parsed["type"] == "STAFF_MENU":
            # Only primary admins (business owners) should see this menu
            if user.role != "user" or user.parent_id is not None:
                send_whatsapp_message(phone, "❌ Only business owners can view the staff management menu.")
                return {"status": "unauthorized_staff_menu"}

            staff_members = db.query(User).filter(User.parent_id == user.id).all()
            
            if not staff_members:
                send_whatsapp_message(
                    phone, 
                    "You have no staff members registered yet.\n\n"
                    "To add staff, send:\n*ADD STAFF [phone] [name]*"
                )
                return {"status": "staff_menu_empty"}

            from sqlalchemy import func
            msg = "👥 Staff Management\n\n"
            for i, member in enumerate(staff_members, start=1):
                status = "✅ Active" if member.role == "delegate" else "⏳ Pending Invitation"
                
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
                    f"   Recorded: ₦{sales:,} (Sales), ₦{payments:,} (Payments)\n\n"
                )
            
            send_whatsapp_message(phone, msg)
            return {"status": "staff_menu_sent"}

        if parsed["type"] == "REMOVE_STAFF":
            if user.role != "user" and user.parent_id:
                 send_whatsapp_message(phone, "❌ Only business owners can remove staff.")
                 return {"status": "unauthorized_remove_staff"}
            
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
            db.commit()

            send_whatsapp_message(phone, f"✅ Access revoked for {staff_name.title()} ({staff_phone}).")
            # Notify the removed staff member
            send_whatsapp_message(staff_phone, f"📢 Notification: Your access to *{user.name.title()}*'s business data has been revoked.")
            return {"status": "staff_removed"}

        if parsed["type"] == "ADD_STAFF":
            if user.role != "user" and user.parent_id:
                 send_whatsapp_message(phone, "❌ Only business owners can add staff.")
                 return {"status": "unauthorized_add_staff"}
            
            staff_phone = parsed["phone"]
            staff_name = parsed["name"]
            
            # Check if staff user exists
            staff_user = db.query(User).filter(User.phone == staff_phone).first()
            if staff_user:
                staff_user.role = "delegate_pending"
                staff_user.parent_id = user.id
                staff_user.name = staff_name
            else:
                staff_user = User(
                    phone=staff_phone,
                    name=staff_name,
                    role="delegate_pending",
                    parent_id=user.id
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
            total = get_today_sales(db, business_owner_phone)
            send_whatsapp_message(phone, f"📊 Today's sales: ₦{total:,}")
            return {"status": "today_sales"}

        if parsed["type"] == "WEEKLY_SALES":
            total = get_weekly_sales(db, business_owner_phone)
            send_whatsapp_message(phone, f"📊 Weekly sales: ₦{total:,}")
            return {"status": "weekly_sales"}

        if parsed["type"] == "MONTHLY_SALES":
            total = get_monthly_sales(db, business_owner_phone)
            send_whatsapp_message(phone, f"📊 Monthly sales: ₦{total:,}")
            return {"status": "monthly_sales"}

        if parsed["type"] == "YEARLY_SALES":
            total = get_yearly_sales(db, business_owner_phone)
            send_whatsapp_message(phone, f"📊 Yearly sales: ₦{total:,}")
            return {"status": "yearly_sales"}

        if parsed["type"] == "PERIOD_TRANSACTIONS":
            stats = get_transaction_stats(db, business_owner_phone, parsed.get("period"))
            period_name = parsed.get("period", "ALL TIME").title()
            send_whatsapp_message(
                phone,
                f"📊 {period_name} transactions: {stats['transaction_count']:,}\n"
                f"Total sales: ₦{stats['total_buy']:,}\n"
                f"Total received: ₦{stats['total_pay']:,}"
            )
            return {"status": "period_transactions"}

        if parsed["type"] == "PERIOD_TOTAL_RECEIVED":
            stats = get_transaction_stats(db, business_owner_phone, parsed.get("period"))
            label = parsed.get("period", "all time")
            send_whatsapp_message(phone, f"📥 Total received {label}: ₦{stats['total_pay']:,}")
            return {"status": "period_total_received"}

        if parsed["type"] == "PERIOD_TOTAL_PAID":
            stats = get_transaction_stats(db, business_owner_phone, parsed.get("period"))
            label = parsed.get("period", "all time")
            send_whatsapp_message(phone, f"📤 Total paid {label}: ₦{stats['total_pay']:,}")
            return {"status": "period_total_paid"}

        if parsed["type"] == "OUTSTANDING_BALANCE":
            total = get_outstanding_balance(db, business_owner_phone)
            send_whatsapp_message(phone, f"💰 Total outstanding balance: ₦{total:,}")
            return {"status": "outstanding_balance"}

        if parsed["type"] == "PERIOD_CASH_CREDIT":
            stats = get_transaction_stats(db, business_owner_phone, parsed.get("period"))
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
            product = get_most_sold_product(db, business_owner_phone)
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
            results = get_product_sales_by_period(db, business_owner_phone)
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
            if not parsed.get("date"):
                send_whatsapp_message(phone, "Send product sales by date DD/MM/YYYY")
                return {"status": "product_sales_by_date_missing"}
            results = get_product_sales_by_date(db, business_owner_phone, parsed["date"])
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
            customers = list_customers(db, business_owner_phone, period)
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
            count = get_customer_count(db, business_owner_phone, period)
            period_label = period.lower() if period else "all time"
            send_whatsapp_message(
                phone,
                f"👥 Customers {period_label}: {count:,}"
            )
            return {"status": "customer_count"}

        if parsed["type"] == "NEW_CUSTOMERS":
            period = parsed.get("period")
            count = get_new_customer_count(db, business_owner_phone, period)
            period_label = period.lower() if period else "all time"
            send_whatsapp_message(
                phone,
                f"🆕 New customers {period_label}: {count:,}"
            )
            return {"status": "new_customers"}

        if parsed["type"] == "PAID_CUSTOMERS":
            period = parsed.get("period")
            count = get_paid_customer_count(db, business_owner_phone, period)
            period_label = period.lower() if period else "all time"
            send_whatsapp_message(
                phone,
                f"✅ Paid customers {period_label}: {count:,}"
            )
            return {"status": "paid_customers"}

        if parsed["type"] == "DASHBOARD_SUMMARY":
            period = parsed.get("period")
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
            debtor = get_biggest_debtor(db, business_owner_phone)
            if not debtor:
                send_whatsapp_message(phone, "No debtors found.")
                return {"status": "biggest_debtor_empty"}
            send_whatsapp_message(
                phone,
                f"🔝 Biggest debtor: {debtor['name'].title()} → ₦{debtor['balance']:,}"
            )
            return {"status": "biggest_debtor"}

        if parsed["type"] == "DEBTOR_LEADERBOARD":
            leaderboard = get_debtor_leaderboard(db, business_owner_phone)
            if not leaderboard:
                send_whatsapp_message(phone, "No debtors found.")
                return {"status": "debtor_leaderboard_empty"}
            msg = "📋 Debtor Leaderboard\n\n"
            for i, debtor in enumerate(leaderboard, start=1):
                msg += f"{i}. {debtor['name'].title()} → ₦{debtor['balance']:,}\n"
            send_whatsapp_message(phone, msg)
            return {"status": "debtor_leaderboard"}

        if parsed["type"] == "SEARCH_CUSTOMER":
            customers = search_customers(db, business_owner_phone, parsed.get("query", ""))
            if not customers:
                send_whatsapp_message(phone, "Customer not found.")
                return {"status": "search_customer_empty"}
            msg = "🔍 Search results\n\n"
            for i, customer in enumerate(customers, start=1):
                msg += f"{i}. {customer.name.title()} → {customer.customer_phone or 'no phone'}\n"
            send_whatsapp_message(phone, msg)
            return {"status": "search_customer"}

        if parsed["type"] == "CUSTOMER_SUMMARY":
            summary = get_customer_summary(db, business_owner_phone, parsed.get("name", ""))
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

        if parsed["type"] == "CUSTOMER_TRANSACTIONS":
            customer = db.query(Customer).filter(
                Customer.name == parsed.get("name", ""),
                Customer.owner_phone == business_owner_phone
            ).first()
            if not customer:
                send_whatsapp_message(phone, "Customer not found.")
                return {"status": "customer_transactions_not_found"}
            total_buy = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
                Transaction.customer_id == customer.id,
                Transaction.type == "BUY"
            ).scalar()
            total_pay = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
                Transaction.customer_id == customer.id,
                Transaction.type == "PAY"
            ).scalar()
            tx_count = db.query(Transaction).filter(
                Transaction.customer_id == customer.id
            ).count()
            send_whatsapp_message(
                phone,
                f"📊 {customer.name.title()} transactions\n"
                f"Total: {tx_count:,}\n"
                f"Bought: ₦{total_buy:,}\n"
                f"Paid: ₦{total_pay:,}"
            )
            return {"status": "customer_transactions"}

        if parsed["type"] == "OVERDUE_DEBTORS":
            overdue_list = get_overdue_debtors(db, business_owner_phone)
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
            debtors, total_outstanding = get_unpaid_debtors(db, business_owner_phone)
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

            balance = get_balance(db, customer.id)
            if balance < 0:
                msg = f"{customer.name} credit: ₦{abs(balance):,}"
            else:
                msg = f"{customer.name} balance: ₦{balance:,}"

            send_whatsapp_message(phone, msg)
            return {"status": "balance"}

        # Handle pronoun references
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

        # Get or create customer
        customer = db.query(Customer).filter(
            Customer.name == customer_name,
            Customer.owner_phone == business_owner_phone
        ).first()

        if not customer:
            customer = Customer(
                name=customer_name,
                owner_phone=business_owner_phone
            )
            db.add(customer)
            db.commit()

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
            due_date=parsed["due_date"]
        )

        db.add(pending)
        db.commit()

        # Send confirmation
        if parsed["action"] == "BUY":
            if parsed.get("quantity") and parsed.get("unit") and parsed.get("product") and parsed.get("unit_price"):
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
            if parsed.get("quantity") and parsed.get("unit") and parsed.get("product") and parsed.get("unit_price"):
                item_line = (
                    f"{parsed['quantity']} {parsed['unit']} of {parsed['product']} at ₦{parsed['unit_price']:,} each, total: ₦{parsed['total']:,}"
                )
            else:
                item_line = f"₦{parsed['buy_amount']:,}"

            if parsed["due_date"]:
                due_date_text = parsed["due_date"].strftime("%d/%m/%Y")
                confirm_msg = (
                    f"Confirm:\n{customer.name} bought {item_line} "
                    f"and paid ₦{parsed['paid_amount']:,}\n"
                    f"Balance due on: {due_date_text}\nReply YES or 1 to save, EDIT or 2 to change."
                )
            else:
                confirm_msg = (
                    f"Confirm:\n{customer.name} bought {item_line} "
                    f"and paid ₦{parsed['paid_amount']:,}?\n"
                    f"Reply YES or 1 to save, EDIT or 2 to change."
                )

        send_whatsapp_message(phone, confirm_msg)
        return {"status": "pending"}

    finally:
        db.close()
