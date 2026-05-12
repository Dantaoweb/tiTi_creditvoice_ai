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


class Transaction(Base):

    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)

    customer_id = Column(
        Integer,
        ForeignKey("customers.id")
    )

    type = Column(String)

    amount = Column(Integer)

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

    customer_name = Column(String)

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

    if clean_text == "due":
        return {
            "type": "DUE_MENU"
        }

    if clean_text in [
        "formats",
        "format",
        "F"
    ]:
        return {
            "type": "FORMATS"
        }

    if clean_text.startswith("remind"):
        return {
            "type": "REMIND",
            "text": text
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

    buy_amount = 0

    paid_amount = 0

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

        if len(amounts) < 2:
            return None

        buy_amount = amounts[0]

        paid_amount = amounts[1]

        action = "COMBINED"

    # =========================
    # 🛒 BUY
    # =========================

    elif has_buy:

        buy_amount = amounts[0]

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

# =========================
# 📋 UNPAID DEBTORS
# =========================

def get_unpaid_debtors(db):

    customers = db.query(Customer).all()

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

def get_overdue_debtors(db):

    overdue_list = []

    customers = db.query(Customer).all()

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
                "name": customer.name,
                "balance": balance,
                "due_date": latest_tx.due_date,
                "overdue_days": overdue_days
            })

    return overdue_list

# =========================
# 📅 DUE TODAY
# =========================

def get_due_today(db):

    due_today = []

    customers = db.query(Customer).all()

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
                "name": customer.name,
                "balance": balance,
                "due_date": latest_tx.due_date
            })

    return due_today

# =========================
# 📅 DUE IN 2 DAYS
# =========================

def get_due_in_2_days(db):

    due_list = []

    customers = db.query(Customer).all()

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
                "name": customer.name,
                "balance": balance,
                "due_date": latest_tx.due_date
            })

    return due_list

@app.get("/")
def home():
    return {"status": "CreditVoice running"}

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

        # =========================
        # 🚫 DUPLICATES
        # =========================

        existing_tx = db.query(Transaction).filter(
            Transaction.message_id == message_id
        ).first()

        if existing_tx:
            return {"status": "duplicate"}

        # =========================
        # ⏳ PENDING
        # =========================

        pending = db.query(PendingAction).filter(
            PendingAction.phone == phone,
            PendingAction.action != None
        ).order_by(
            PendingAction.created_at.desc()
        ).first()

        if pending:

            # =========================
            # 📅 DUE MENU
            # =========================

            if pending.action == "DUE_MENU":

                # =========================
                # 📅 DUE IN 2 DAYS
                # =========================

                if text == "1":

                    due_list = get_due_in_2_days(db)

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

                        msg = (
                            "📅 Due in 2 Days\n\n"
                        )

                        for i, debtor in enumerate(
                            due_list,
                            start=1
                        ):

                            memory = ReminderMemory(
                                phone=phone,
                                customer_name=debtor["name"],
                                balance=debtor["balance"],
                                due_date=debtor["due_date"],
                                reminder_type="DUE_2_DAYS"
                            )

                            db.add(memory)

                            msg += (
                                f"{i}. "
                                f"{debtor['name']} "
                                f"→ ₦{debtor['balance']:,}\n"
                            )

                        db.commit()

                        msg += (
                            "\nSend:\n"
                            "REMIND 1\n"
                            "or\n"
                            "REMIND 2\n"
                            "to generate customer reminder."
                        )

                        send_whatsapp_message(
                            phone,
                            msg
                        )

                    db.delete(pending)

                    db.commit()

                    return {
                        "status": "due_2_days"
                    }

                # =========================
                # 📅 DUE TODAY
                # =========================

                elif text == "2":

                    due_today = get_due_today(db)

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

                        for i, debtor in enumerate(
                            due_today,
                            start=1
                        ):

                            memory = ReminderMemory(
                                phone=phone,
                                customer_name=debtor["name"],
                                balance=debtor["balance"],
                                due_date=debtor["due_date"],
                                reminder_type="DUE_TODAY"
                            )

                            db.add(memory)

                            msg += (
                                f"{i}. "
                                f"{debtor['name']} "
                                f"→ ₦{debtor['balance']:,}\n"
                            )

                        db.commit()

                        msg += (
                            "\nSend:\n"
                            "REMIND 1\n"
                            "or\n"
                            "REMIND 2\n"
                            "to generate customer reminder."
                        )

                        send_whatsapp_message(
                            phone,
                            msg
                        )

                    db.delete(pending)

                    db.commit()

                    return {
                        "status": "due_today"
                    }

                # =========================
                # ⚠️ OVERDUE
                # =========================

                elif text == "3":

                    overdue_list = get_overdue_debtors(db)

                    if len(overdue_list) == 0:

                        send_whatsapp_message(
                            phone,
                            "✅ No overdue debtors."
                        )

                    else:

                        msg = (
                            "⚠️ Overdue Debtors\n\n"
                        )

                        for i, debtor in enumerate(
                            overdue_list,
                            start=1
                        ):

                            due_date_text = debtor[
                                "due_date"
                            ].strftime("%d/%m/%Y")

                            msg += (
                                f"{i}. "
                                f"{debtor['name']}\n"
                                f"Balance: "
                                f"₦{debtor['balance']:,}\n"
                                f"Due: "
                                f"{due_date_text}\n"
                                f"Overdue: "
                                f"{debtor['overdue_days']} days\n\n"
                            )

                        send_whatsapp_message(
                            phone,
                            msg
                        )

                    db.delete(pending)

                    db.commit()

                    return {
                        "status": "overdue_menu"
                    }

            # =========================
            # ✅ SAVE
            # =========================

            if text.lower() == "yes":

                customer = db.query(Customer).filter(
                    Customer.name == pending.customer_name,
                    Customer.owner_phone == phone
                ).first()

                # =========================
                # 🛒 BUY
                # =========================

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

                # =========================
                # 💵 PAY
                # =========================

                elif pending.action == "PAY":

                    tx = Transaction(
                        customer_id=customer.id,
                        type="PAY",
                        amount=pending.paid_amount,
                        message_id=message_id,
                        created_at=datetime.utcnow()
                    )

                    db.add(tx)
                    
                    # =========================
                    # UPDATE DUE DATE
                    # =========================
                    
                    if pending.due_date:
                        
                        latest_buy = db.query(Transaction).filter(
                            Transaction.customer_id ==
                            customer.id,
                            Transaction.type == "BUY"
                        ).order_by(
                        Transaction.created_at.desc()
                        ).first()
                        
                        if latest_buy:
                            latest_buy.due_date = (
                                pending.due_date
                            )

                # =========================
                # 🔄 COMBINED
                # =========================

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

                # =========================
                # 🧠 MEMORY
                # =========================

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

                balance = get_balance(
                    db,
                    customer.id
                )

                # =========================
                # 💬 FINAL MESSAGE
                # =========================

                if pending.action == "COMBINED":

                    if balance < 0:

                        msg = (
                            f"✅ Saved.\n"
                            f"{customer.name} bought "
                            f"₦{pending.buy_amount:,} "
                            f"and paid "
                            f"₦{pending.paid_amount:,}.\n"
                            f"Credit: ₦{abs(balance):,}"
                        )

                    else:

                        msg = (
                            f"✅ Saved.\n"
                            f"{customer.name} bought "
                            f"₦{pending.buy_amount:,} "
                            f"and paid "
                            f"₦{pending.paid_amount:,}.\n"
                            f"Balance: ₦{balance:,}"
                        )

                else:

                    if balance < 0:

                        msg = (
                            f"✅ Saved.\n"
                            f"{customer.name} credit: "
                            f"₦{abs(balance):,}"
                        )

                    else:

                        msg = (
                            f"✅ Saved.\n"
                            f"{customer.name} balance: "
                            f"₦{balance:,}"
                        )

                send_whatsapp_message(
                    phone,
                    msg
                )

                return {"status": "saved"}

            # =========================
            # ✏️ EDIT
            # =========================

            elif text.lower() == "edit":

                db.delete(pending)

                db.commit()

                send_whatsapp_message(
                    phone,
                    "Enter again "
                    "(e.g. Ola paid 2000)"
                )

                return {"status": "edit"}

        # =========================
        # 🧠 PARSE
        # =========================

        parsed = parse_message(text)

        if not parsed:

            send_whatsapp_message(
                phone,
                "❌ Message not understood.\n\n"
                "Type:\n"
                "FORMATS\n\n"
                "or send:\n"
                "F\n\n"
                "to see supported transaction examples."
            )

            return {"status": "invalid"}

        # =========================
        # 📘 FORMATS
        # =========================

        if parsed["type"] == "FORMATS":

            msg = (
                "📘 Supported Formats\n\n"
                "🛒 BUY ONLY\n"
                "Ade bought rice 5000\n\n"
                "💵 PAYMENT ONLY\n"
                "Ade paid 3000\n\n"
                "🔄 PART PAYMENT\n"
                "Ade bought rice 5000 paid 2000\n\n"
                "📅 DUE DATE\n"
                "Ade bought rice 5000 due 12/2/2026\n\n"
                "📅 PART PAYMENT + DUE DATE\n"
                "Ade bought rice 5000 "
                "paid 2000 due 12/2/2026\n\n"
                "📌 Date Format:\n"
                "Use D/M/YYYY\n\n"
                "Example:\n"
                "12/2/2026 = 12 February 2026"
            )

            send_whatsapp_message(
                phone,
                msg
            )

            return {"status": "formats"}

        # =========================
        # 📨 REMIND
        # =========================

        if parsed["type"] == "REMIND":

            parts = parsed["text"].split()

            if len(parts) != 2:

                send_whatsapp_message(
                    phone,
                    "Use:\nREMIND 1"
                )

                return {
                    "status": "invalid_remind"
                }

            if not parts[1].isdigit():

                send_whatsapp_message(
                    phone,
                    "Use:\nREMIND 1"
                )

                return {
                    "status": "invalid_remind"
                }

            index = int(parts[1])

            reminders = db.query(
                ReminderMemory
            ).filter(
                ReminderMemory.phone == phone
            ).all()

            if (
                index < 1
                or index > len(reminders)
            ):

                send_whatsapp_message(
                    phone,
                    "Reminder number not found."
                )

                return {
                    "status":
                    "reminder_not_found"
                }

            reminder = reminders[index - 1]

            due_date_text = reminder.due_date.strftime(
                "%d/%m/%Y"
            )

            if (
                reminder.reminder_type
                == "DUE_TODAY"
            ):

                msg = (
                    f"Hello "
                    f"{reminder.customer_name.title()},\n\n"
                    f"This is a reminder that your "
                    f"outstanding balance of "
                    f"₦{reminder.balance:,} "
                    f"is due today.\n\n"
                    f"Thank you."
                )

            else:

                msg = (
                    f"Hello "
                    f"{reminder.customer_name.title()},\n\n"
                    f"This is a reminder that your "
                    f"outstanding balance of "
                    f"₦{reminder.balance:,} "
                    f"will be due on "
                    f"{due_date_text}.\n\n"
                    f"Thank you."
                )

            send_whatsapp_message(
                phone,
                msg
            )

            return {"status": "remind"}

        # =========================
        # 📅 DUE MENU
        # =========================

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
                "1. Due in 2 Days\n"
                "2. Due Today\n"
                "3. Overdue Debtors\n\n"
                "Reply with:\n"
                "1, 2, or 3"
            )

            return {"status": "due_menu"}

        # =========================
        # 📊 SALES
        # =========================

        if parsed["type"] == "TODAY_SALES":

            total = get_today_sales(db)

            send_whatsapp_message(
                phone,
                f"📊 Today's sales: ₦{total:,}"
            )

            return {"status": "today_sales"}

        if parsed["type"] == "WEEKLY_SALES":

            total = get_weekly_sales(db)

            send_whatsapp_message(
                phone,
                f"📊 Weekly sales: ₦{total:,}"
            )

            return {"status": "weekly_sales"}

        if parsed["type"] == "MONTHLY_SALES":

            total = get_monthly_sales(db)

            send_whatsapp_message(
                phone,
                f"📊 Monthly sales: ₦{total:,}"
            )

            return {"status": "monthly_sales"}

        if parsed["type"] == "YEARLY_SALES":

            total = get_yearly_sales(db)

            send_whatsapp_message(
                phone,
                f"📊 Yearly sales: ₦{total:,}"
            )

            return {"status": "yearly_sales"}
            
        # =========================
        #   OVERDUE DIRECT
        # =========================
        
        if parsed["type"] == "OVERDUE_DEBTORS":

            overdue_list = get_overdue_debtors(db)
        

            if len(overdue_list) == 0:

                send_whatsapp_message(
                    phone,
                    "✅ No overdue debtors."
                )

                return {"status": "no_overdue"}

            msg = "📋 Overdue Debtors\n\n"

            for i, debtor in enumerate(
                overdue_list,
                start=1
            ):
                due_date_text = debtor["due_date"
                ].strftime("%d/%m/%Y")

                msg += (
                    f"{i}. "
                    f"{debtor['name']}\n "
                    f"Balance: "
                    f"₦{debtor['balance']:,}\n"
                    f"Due: "
                    f"{due_date_text}\n"
                    f"Overdue: "
                    f"{debtor['overdue_days']} days\n\n"
                )

            send_whatsapp_message(
                phone,
                msg
            )

            return {
                "status":
                "overdue_direct"
            }

        # =========================
        # 📋 UNPAID
        # =========================

        if parsed["type"] == "UNPAID_DEBTORS":

            debtors, total_outstanding = (
                get_unpaid_debtors(db)
            )

            if len(debtors) == 0:

                send_whatsapp_message(
                    phone,
                    "✅ No unpaid debtors."
                )

                return {"status": "no_debtors"}

            msg = "📋 Unpaid Debtors\n\n"

            for i, debtor in enumerate(
                debtors,
                start=1
            ):

                msg += (
                    f"{i}. "
                    f"{debtor['name']} "
                    f"→ ₦{debtor['balance']:,}\n"
                )

            msg += (
                f"\n💰 Total Outstanding: "
                f"₦{total_outstanding:,}"
            )

            send_whatsapp_message(
                phone,
                msg
            )

            return {
                "status":
                "unpaid_debtors"
            }

        # =========================
        # 💰 BALANCE
        # =========================

        if parsed["type"] == "BALANCE":

            name = text.replace(
                "balance",
                ""
            ).strip().lower()

            customer = db.query(Customer).filter(
                Customer.name == name,
                Customer.owner_phone == phone
            ).first()

            if not customer:

                send_whatsapp_message(
                    phone,
                    "Customer not found."
                )

                return {"status": "not_found"}

            balance = get_balance(
                db,
                customer.id
            )

            if balance < 0:

                msg = (
                    f"{customer.name} credit: "
                    f"₦{abs(balance):,}"
                )

            else:

                msg = (
                    f"{customer.name} balance: "
                    f"₦{balance:,}"
                )

            send_whatsapp_message(
                phone,
                msg
            )

            return {"status": "balance"}

        # =========================
        # 👤 MEMORY
        # =========================

        customer_name = (
            parsed["name"].lower()
        )

        if customer_name in [
            "he",
            "she"
        ]:

            memory = db.query(
                CustomerMemory
            ).filter(
                CustomerMemory.phone == phone
            ).first()

            if memory and memory.last_customer:

                customer_name = (
                    memory.last_customer.lower()
                )

            else:

                send_whatsapp_message(
                    phone,
                    "No previous customer found."
                )

                return {"status": "no_memory"}

        # =========================
        # 👥 CUSTOMER
        # =========================

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

        # =========================
        # 🧹 CLEAR PENDING
        # =========================

        db.query(PendingAction).filter(
            PendingAction.phone == phone
        ).delete()

        db.commit()

        # =========================
        # ⏳ SAVE PENDING
        # =========================

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

        # =========================
        # 🧾 CONFIRMATION
        # =========================

        if parsed["action"] == "BUY":

            if parsed["due_date"]:

                due_date_text = (
                    parsed["due_date"]
                    .strftime("%d/%m/%Y")
                )

                confirm_msg = (
                    f"Confirm:\n"
                    f"{customer.name} bought "
                    f"₦{parsed['buy_amount']:,}\n"
                    f"Due: {due_date_text}\n"
                    f"Reply YES or EDIT"
                )

            else:

                confirm_msg = (
                    f"Confirm:\n"
                    f"{customer.name} bought "
                    f"₦{parsed['buy_amount']:,}?\n"
                    f"Reply YES or EDIT"
                )

        elif parsed["action"] == "PAY":

            confirm_msg = (
                f"Confirm:\n"
                f"{customer.name} paid "
                f"₦{parsed['paid_amount']:,}?\n"
                f"Reply YES or EDIT"
            )

        elif parsed["action"] == "COMBINED":

            if parsed["due_date"]:

                due_date_text = (
                    parsed["due_date"]
                    .strftime("%d/%m/%Y")
                )

                confirm_msg = (
                    f"Confirm:\n"
                    f"{customer.name} bought "
                    f"₦{parsed['buy_amount']:,} "
                    f"and paid "
                    f"₦{parsed['paid_amount']:,}\n"
                    f"Balance due on: "
                    f"{due_date_text}\n"
                    f"Reply YES or EDIT"
                )

            else:

                confirm_msg = (
                    f"Confirm:\n"
                    f"{customer.name} bought "
                    f"₦{parsed['buy_amount']:,} "
                    f"and paid "
                    f"₦{parsed['paid_amount']:,}?\n"
                    f"Reply YES or EDIT"
                )

        send_whatsapp_message(
            phone,
            confirm_msg
        )

        return {"status": "pending"}

    finally:

        db.close()
