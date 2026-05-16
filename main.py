import os
import re
import requests

from datetime import datetime, timedelta

from fastapi import FastAPI, Request

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey
)

from sqlalchemy.orm import (
    sessionmaker,
    declarative_base
)

# =========================
# 🔐 ENV CONFIG
# =========================

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

    id = Column(Integer, primary_key=True)

    name = Column(String)

    owner_phone = Column(String)

    customer_phone = Column(String, nullable=True)

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


class Transaction(Base):

    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)

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

    id = Column(Integer, primary_key=True)

    phone = Column(String)

    customer_name = Column(String)

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


class CustomerMemory(Base):

    __tablename__ = "customer_memory"

    id = Column(Integer, primary_key=True)

    phone = Column(
        String,
        unique=True
    )

    last_customer = Column(String)


class ReminderMemory(Base):

    __tablename__ = "reminder_memory"

    id = Column(Integer, primary_key=True)

    phone = Column(String)

    customer_id = Column(Integer, nullable=True)

    customer_name = Column(String)

    customer_phone = Column(String, nullable=True)

    balance = Column(Integer)

    due_date = Column(DateTime)

    reminder_type = Column(String)


Base.metadata.create_all(engine)

# =========================
# 📤 WHATSAPP SEND
# =========================

def send_whatsapp_message(to, message):

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

    response = requests.post(
        url,
        headers=headers,
        json=data
    )

    print("WhatsApp:", response.text)

# =========================
# 🧠 HELPERS
# =========================


def extract_item_details(text):
    clean = text.lower().replace(",", "")

    match = re.search(
        r"(?P<quantity>\d+)\s+"
        r"(?P<unit>\w+)\s+(?:of\s+)?"
        r"(?P<product>[a-z ]+?)\s+at\s+(?P<unit_price>\d+)",
        clean
    )

    if not match:
        return None

    quantity = int(match.group("quantity"))
    unit = match.group("unit")
    product = match.group("product").strip()
    unit_price = int(match.group("unit_price"))
    total = quantity * unit_price

    return {
        "quantity": quantity,
        "unit": unit,
        "product": product,
        "unit_price": unit_price,
        "total": total
    }


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


# =========================
# 🧠 PARSER
# =========================

def parse_message(text):

    clean_text = text.lower().strip()

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
        "transactions for today"
    ]:
        return {
            "type": "PERIOD_TRANSACTIONS",
            "period": "TODAY"
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

    if clean_text in [
        "list customers",
        "customer list",
        "customers"
    ]:
        return {
            "type": "CUSTOMER_LIST"
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

    phone_match = re.match(
        r"(?P<name>[a-zA-Z ]+?)\s+(?:phone|number)\s+(?P<phone>[+\d ]+)$",
        clean_text
    )

    if phone_match:
        return {
            "type": "SET_PHONE",
            "name": phone_match.group("name").strip().lower(),
            "customer_phone": phone_match.group("phone").strip()
        }

    # =========================
    # 🧹 CLEAN TEXT
    # =========================

    clean_text = text.replace(",", "")

    words = clean_text.split()

    amounts = []

    for word in words:

        if word.isdigit():
            amounts.append(int(word))

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

    has_buy = (
        "bought" in clean_text
        or "buy" in clean_text
    )

    has_pay = (
        "paid" in clean_text
        or "pay" in clean_text
    )

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

def get_today_sales(db):

    from sqlalchemy import func

    today = datetime.utcnow().date()

    total = db.query(
        func.coalesce(
            func.sum(Transaction.amount),
            0
        )
    ).filter(
        Transaction.type == "BUY"
    ).filter(
        func.date(Transaction.created_at) == today
    ).scalar()

    return total


def get_weekly_sales(db):

    from sqlalchemy import func

    seven_days_ago = (
        datetime.utcnow()
        - timedelta(days=7)
    )

    total = db.query(
        func.coalesce(
            func.sum(Transaction.amount),
            0
        )
    ).filter(
        Transaction.type == "BUY",
        Transaction.created_at >= seven_days_ago
    ).scalar()

    return total


def get_monthly_sales(db):

    from sqlalchemy import func

    thirty_days_ago = (
        datetime.utcnow()
        - timedelta(days=30)
    )

    total = db.query(
        func.coalesce(
            func.sum(Transaction.amount),
            0
        )
    ).filter(
        Transaction.type == "BUY",
        Transaction.created_at >= thirty_days_ago
    ).scalar()

    return total


def get_yearly_sales(db):

    from sqlalchemy import func

    one_year_ago = (
        datetime.utcnow()
        - timedelta(days=365)
    )

    total = db.query(
        func.coalesce(
            func.sum(Transaction.amount),
            0
        )
    ).filter(
        Transaction.type == "BUY",
        Transaction.created_at >= one_year_ago
    ).scalar()

    return total


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
    from sqlalchemy import func

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
        query = query.join(Transaction, Transaction.customer_id == Customer.id).filter(
            Transaction.created_at >= start,
            Transaction.created_at < end
        )
    return query.distinct(Customer.id).count()


def list_customers(db, owner_phone=None):
    query = db.query(Customer)
    if owner_phone:
        query = query.filter(Customer.owner_phone == owner_phone)
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
    from sqlalchemy import func

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
    from sqlalchemy import func

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
    from sqlalchemy import func

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
    from sqlalchemy import func

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

        balance = get_balance(
            db,
            customer.id
        )

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

        balance = get_balance(
            db,
            customer.id
        )

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

        balance = get_balance(
            db,
            customer.id
        )

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

        balance = get_balance(
            db,
            customer.id
        )

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

    data = await req.json()

    try:
        message = (
            data["entry"][0]
            ["changes"][0]
            ["value"]["messages"][0]
        )

        text = message["text"]["body"].strip()

        phone = message["from"]

        message_id = message["id"]

    except:
        return {"status": "ignored"}

    db = SessionLocal()

    try:

        # Duplicate check, pending action checks, and rest of webhook logic
        existing_tx = db.query(Transaction).filter(
            Transaction.message_id == message_id
        ).first()

        if existing_tx:
            return {"status": "duplicate"}

        pending = db.query(PendingAction).filter(
            PendingAction.phone == phone,
            PendingAction.action != None
        ).order_by(
            PendingAction.created_at.desc()
        ).first()

        if pending:
            if pending.action == "DUE_MENU":
                # Handle DUE_MENU responses (1, 2, 3)
                if text == "1":
                    # Due in 2 days logic
                    due_list = get_due_in_2_days(db, phone)
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
                    due_today = get_due_today(db, phone)
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

                    overdue_list = get_overdue_debtors(db, phone)
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

            elif text.lower() == "yes":
                customer = db.query(Customer).filter(
                    Customer.name == pending.customer_name,
                    Customer.owner_phone == phone
                ).first()

                if pending.action == "BUY":
                    tx = Transaction(
                        customer_id=customer.id,
                        type="BUY",
                        amount=pending.buy_amount,
                        due_date=pending.due_date,
                        message_id=message_id,
                        created_at=datetime.utcnow()
                    )
                    db.add(tx)

                elif pending.action == "PAY":
                    tx = Transaction(
                        customer_id=customer.id,
                        type="PAY",
                        amount=pending.paid_amount,
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
                        message_id=f"{message_id}_buy",
                        created_at=datetime.utcnow()
                    )
                    db.add(buy_tx)

                    pay_tx = Transaction(
                        customer_id=customer.id,
                        type="PAY",
                        amount=pending.paid_amount,
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

            elif text.lower() == "edit":
                db.delete(pending)
                db.commit()
                send_whatsapp_message(
                    phone,
                    "Enter again (e.g. Ola paid 2000)"
                )
                return {"status": "edit"}

        # Parse message
        parsed = parse_message(text)

        if not parsed:
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
            )
            send_whatsapp_message(phone, msg)
            return {"status": "formats"}

        if parsed["type"] == "SET_PHONE":
            customer = db.query(Customer).filter(
                Customer.name == parsed["name"],
                Customer.owner_phone == phone
            ).first()

            if not customer:
                customer = Customer(
                    name=parsed["name"],
                    owner_phone=phone,
                    customer_phone=parsed["customer_phone"]
                )
                db.add(customer)
            else:
                customer.customer_phone = parsed["customer_phone"]

            db.commit()
            
            # Also update phone in ReminderMemory if there's a pending reminder for this customer
            reminders_to_update = db.query(ReminderMemory).filter(
                ReminderMemory.phone == phone,
                ReminderMemory.customer_name == parsed["name"]
            ).all()
            
            for reminder in reminders_to_update:
                reminder.customer_phone = parsed["customer_phone"]
            
            db.commit()
            
            send_whatsapp_message(
                phone,
                f"Saved phone for {customer.name.title()}: {customer.customer_phone}"
            )
            
            # If there's a pending REMINDER_CONFIRM action, prompt them to retry
            pending_reminder = db.query(PendingAction).filter(
                PendingAction.phone == phone,
                PendingAction.action == "REMINDER_CONFIRM"
            ).first()
            
            if pending_reminder:
                send_whatsapp_message(
                    phone,
                    f"Phone set! Now reply YES to send the reminder to {customer.name.title()}."
                )
            
            return {"status": "set_phone"}

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
            total = get_today_sales(db)
            send_whatsapp_message(phone, f"📊 Today's sales: ₦{total:,}")
            return {"status": "today_sales"}

        if parsed["type"] == "WEEKLY_SALES":
            total = get_weekly_sales(db)
            send_whatsapp_message(phone, f"📊 Weekly sales: ₦{total:,}")
            return {"status": "weekly_sales"}

        if parsed["type"] == "MONTHLY_SALES":
            total = get_monthly_sales(db)
            send_whatsapp_message(phone, f"📊 Monthly sales: ₦{total:,}")
            return {"status": "monthly_sales"}

        if parsed["type"] == "YEARLY_SALES":
            total = get_yearly_sales(db)
            send_whatsapp_message(phone, f"📊 Yearly sales: ₦{total:,}")
            return {"status": "yearly_sales"}

        if parsed["type"] == "PERIOD_TRANSACTIONS":
            stats = get_transaction_stats(db, phone, parsed.get("period"))
            period_name = parsed.get("period", "ALL TIME").title()
            send_whatsapp_message(
                phone,
                f"📊 {period_name} transactions: {stats['transaction_count']:,}\n"
                f"Total sales: ₦{stats['total_buy']:,}\n"
                f"Total received: ₦{stats['total_pay']:,}"
            )
            return {"status": "period_transactions"}

        if parsed["type"] == "PERIOD_TOTAL_RECEIVED":
            stats = get_transaction_stats(db, phone, parsed.get("period"))
            label = parsed.get("period", "all time")
            send_whatsapp_message(phone, f"📥 Total received {label}: ₦{stats['total_pay']:,}")
            return {"status": "period_total_received"}

        if parsed["type"] == "PERIOD_TOTAL_PAID":
            stats = get_transaction_stats(db, phone, parsed.get("period"))
            label = parsed.get("period", "all time")
            send_whatsapp_message(phone, f"📤 Total paid {label}: ₦{stats['total_pay']:,}")
            return {"status": "period_total_paid"}

        if parsed["type"] == "OUTSTANDING_BALANCE":
            total = get_outstanding_balance(db, phone)
            send_whatsapp_message(phone, f"💰 Total outstanding balance: ₦{total:,}")
            return {"status": "outstanding_balance"}

        if parsed["type"] == "PERIOD_CASH_CREDIT":
            stats = get_transaction_stats(db, phone, parsed.get("period"))
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
            product = get_most_sold_product(db, phone)
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
            results = get_product_sales_by_period(db, phone)
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
            results = get_product_sales_by_date(db, phone, parsed["date"])
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
            customers = list_customers(db, phone)
            if not customers:
                send_whatsapp_message(phone, "No customers found.")
                return {"status": "customer_list_empty"}
            msg = "👥 Customers\n\n"
            for i, customer in enumerate(customers, start=1):
                msg += (
                    f"{i}. {customer['name'].title()}"
                    f" ({customer['phone'] or 'no phone'}) → ₦{customer['balance']:,}\n"
                )
            send_whatsapp_message(phone, msg)
            return {"status": "customer_list"}

        if parsed["type"] == "CUSTOMER_COUNT":
            period = parsed.get("period")
            count = get_customer_count(db, phone, period)
            period_label = period.lower() if period else "all time"
            send_whatsapp_message(
                phone,
                f"👥 Total customers {period_label}: {count:,}"
            )
            return {"status": "customer_count"}

        if parsed["type"] == "BIGGEST_DEBTOR":
            debtor = get_biggest_debtor(db, phone)
            if not debtor:
                send_whatsapp_message(phone, "No debtors found.")
                return {"status": "biggest_debtor_empty"}
            send_whatsapp_message(
                phone,
                f"🔝 Biggest debtor: {debtor['name'].title()} → ₦{debtor['balance']:,}"
            )
            return {"status": "biggest_debtor"}

        if parsed["type"] == "DEBTOR_LEADERBOARD":
            leaderboard = get_debtor_leaderboard(db, phone)
            if not leaderboard:
                send_whatsapp_message(phone, "No debtors found.")
                return {"status": "debtor_leaderboard_empty"}
            msg = "📋 Debtor Leaderboard\n\n"
            for i, debtor in enumerate(leaderboard, start=1):
                msg += f"{i}. {debtor['name'].title()} → ₦{debtor['balance']:,}\n"
            send_whatsapp_message(phone, msg)
            return {"status": "debtor_leaderboard"}

        if parsed["type"] == "SEARCH_CUSTOMER":
            customers = search_customers(db, phone, parsed.get("query", ""))
            if not customers:
                send_whatsapp_message(phone, "Customer not found.")
                return {"status": "search_customer_empty"}
            msg = "🔍 Search results\n\n"
            for i, customer in enumerate(customers, start=1):
                msg += f"{i}. {customer.name.title()} → {customer.customer_phone or 'no phone'}\n"
            send_whatsapp_message(phone, msg)
            return {"status": "search_customer"}

        if parsed["type"] == "CUSTOMER_SUMMARY":
            summary = get_customer_summary(db, phone, parsed.get("name", ""))
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
            from sqlalchemy import func

            customer = db.query(Customer).filter(
                Customer.name == parsed.get("name", ""),
                Customer.owner_phone == phone
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
            overdue_list = get_overdue_debtors(db, phone)
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
            debtors, total_outstanding = get_unpaid_debtors(db, phone)
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
                Customer.owner_phone == phone
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
            Customer.owner_phone == phone
        ).first()

        if not customer:
            customer = Customer(
                name=customer_name,
                owner_phone=phone
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
                        f"Due: {due_date_text}\nReply YES or EDIT"
                    )
                else:
                    confirm_msg = (
                        f"Confirm:\n{customer.name} bought {item_line}\n"
                        f"Reply YES or EDIT"
                    )
            elif parsed["due_date"]:
                due_date_text = parsed["due_date"].strftime("%d/%m/%Y")
                confirm_msg = (
                    f"Confirm:\n{customer.name} bought ₦{parsed['buy_amount']:,}\n"
                    f"Due: {due_date_text}\nReply YES or EDIT"
                )
            else:
                confirm_msg = (
                    f"Confirm:\n{customer.name} bought ₦{parsed['buy_amount']:,}?\n"
                    f"Reply YES or EDIT"
                )

        elif parsed["action"] == "PAY":
            confirm_msg = (
                f"Confirm:\n{customer.name} paid ₦{parsed['paid_amount']:,}?\n"
                f"Reply YES or EDIT"
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
                    f"Balance due on: {due_date_text}\nReply YES or EDIT"
                )
            else:
                confirm_msg = (
                    f"Confirm:\n{customer.name} bought {item_line} "
                    f"and paid ₦{parsed['paid_amount']:,}?\nReply YES or EDIT"
                )

        send_whatsapp_message(phone, confirm_msg)
        return {"status": "pending"}

    finally:
        db.close()
