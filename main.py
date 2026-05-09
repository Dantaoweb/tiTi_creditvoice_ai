import os
import re
import requests
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base

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
    customer_id = Column(Integer, ForeignKey("customers.id"))
    type = Column(String)
    amount = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    message_id = Column(String, unique=True)


class PendingAction(Base):
    __tablename__ = "pending_actions"

    id = Column(Integer, primary_key=True)
    phone = Column(String)
    customer_name = Column(String)
    action = Column(String)

    buy_amount = Column(Integer, default=0)
    paid_amount = Column(Integer, default=0)

    last_customer = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class CustomerMemory(Base):
    __tablename__ = "customer_memory"

    id = Column(Integer, primary_key=True)
    phone = Column(String, unique=True)
    last_customer = Column(String)


Base.metadata.create_all(engine)

# =========================
# 📤 WHATSAPP SEND
# =========================

def send_whatsapp_message(to, message):

    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
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

    response = requests.post(url, headers=headers, json=data)

    print("WhatsApp:", response.text)

# =========================
# 🧠 PARSER
# =========================

def parse_message(text):

    text = text.lower().strip()

    if "balance" in text:
        return {"type": "BALANCE"}

    if text == "today sales":
        return {"type": "TODAY_SALES"}

    if text == "weekly sales":
        return {"type": "WEEKLY_SALES"}

    if text == "monthly sales":
        return {"type": "MONTHLY_SALES"}

    if text == "yearly sales":
        return {"type": "YEARLY_SALES"}

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

    # =========================
    # 🧠 DETECT TRANSACTION TYPE
    # =========================

    has_buy = "bought" in clean_text or "buy" in clean_text
    has_pay = "paid" in clean_text or "pay" in clean_text

    # =========================
    # 🔄 COMBINED TRANSACTION
    # =========================

    if has_buy and has_pay:

        if len(amounts) < 2:
            return None

        buy_amount = amounts[0]
        paid_amount = amounts[1]

        action = "COMBINED"

    # =========================
    # 🛒 NORMAL BUY
    # =========================

    elif has_buy:

        buy_amount = amounts[0]

        action = "BUY"

    # =========================
    # 💵 NORMAL PAYMENT
    # =========================

    elif has_pay:

        paid_amount = amounts[0]

        action = "PAY"

    else:
        return None

    # =========================
    # 👤 FIND CUSTOMER NAME
    # =========================

    words = text.split()

    action_index = None

    for i, word in enumerate(words):

        if word in ["bought", "buy", "paid", "pay"]:
            action_index = i
            break

    if action_index is None:
        return None

    name = " ".join(words[:action_index]).lower()

    return {
        "type": "TRANSACTION",
        "name": name,
        "action": action,
        "buy_amount": buy_amount,
        "paid_amount": paid_amount
    }

# =========================
# 💰 BALANCE
# =========================

def get_balance(db, customer_id):

    from sqlalchemy import func

    total_buy = db.query(
        func.coalesce(func.sum(Transaction.amount), 0)
    ).filter(
        Transaction.customer_id == customer_id,
        Transaction.type == "BUY"
    ).scalar()

    total_pay = db.query(
        func.coalesce(func.sum(Transaction.amount), 0)
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
        func.coalesce(func.sum(Transaction.amount), 0)
    ).filter(
        Transaction.type == "BUY",
        func.date(Transaction.created_at) == today
    ).scalar()

    return total


def get_weekly_sales(db):

    from sqlalchemy import func

    seven_days_ago = datetime.utcnow() - timedelta(days=7)

    total = db.query(
        func.coalesce(func.sum(Transaction.amount), 0)
    ).filter(
        Transaction.type == "BUY",
        Transaction.created_at >= seven_days_ago
    ).scalar()

    return total


def get_monthly_sales(db):

    from sqlalchemy import func

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    total = db.query(
        func.coalesce(func.sum(Transaction.amount), 0)
    ).filter(
        Transaction.type == "BUY",
        Transaction.created_at >= thirty_days_ago
    ).scalar()

    return total


def get_yearly_sales(db):

    from sqlalchemy import func

    one_year_ago = datetime.utcnow() - timedelta(days=365)

    total = db.query(
        func.coalesce(func.sum(Transaction.amount), 0)
    ).filter(
        Transaction.type == "BUY",
        Transaction.created_at >= one_year_ago
    ).scalar()

    return total

# =========================
# 🌐 WEBHOOK
# =========================

@app.post("/webhook")
async def webhook(req: Request):

    data = await req.json()

    try:

        message = data["entry"][0]["changes"][0]["value"]["messages"][0]

        text = message["text"]["body"].strip()
        phone = message["from"]
        message_id = message["id"]

    except:
        return {"status": "ignored"}

    db = SessionLocal()

    try:

        # =========================
        # 🚫 DUPLICATE PREVENTION
        # =========================

        existing_tx = db.query(Transaction).filter(
            Transaction.message_id == message_id
        ).first()

        if existing_tx:
            return {"status": "duplicate"}

        # =========================
        # ⏳ CHECK PENDING ACTION
        # =========================

        pending = db.query(PendingAction).filter(
            PendingAction.phone == phone,
            PendingAction.action != None
        ).order_by(
            PendingAction.created_at.desc()
        ).first()

        if pending:

            # =========================
            # ✅ CONFIRM SAVE
            # =========================

            if text.lower() == "yes":

                customer = db.query(Customer).filter(
                    Customer.name == pending.customer_name,
                    Customer.owner_phone == phone
                ).first()

                # =========================
                # 💰 NORMAL BUY
                # =========================

                if pending.action == "BUY":

                    tx = Transaction(
                        customer_id=customer.id,
                        type="BUY",
                        amount=pending.buy_amount,
                        message_id=message_id,
                        created_at=datetime.utcnow()
                    )

                    db.add(tx)

                # =========================
                # 💵 NORMAL PAYMENT
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
                # 🔄 COMBINED TRANSACTION
                # =========================

                elif pending.action == "COMBINED":

                    buy_tx = Transaction(
                        customer_id=customer.id,
                        type="BUY",
                        amount=pending.buy_amount,
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
                # 🧠 UPDATE MEMORY
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

                balance = get_balance(db, customer.id)

                # =========================
                # 💬 SUCCESS MESSAGE
                # =========================

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

            # =========================
            # ✏️ EDIT TRANSACTION
            # =========================

            elif text.lower() == "edit":

                db.delete(pending)

                db.commit()

                send_whatsapp_message(
                    phone,
                    "Enter again (e.g. Ola paid 2000)"
                )

                return {"status": "edit"}

        # =========================
        # 🧠 PARSE MESSAGE
        # =========================

        parsed = parse_message(text)

        if not parsed:

            send_whatsapp_message(
                phone,
                "Invalid format."
            )

            return {"status": "invalid"}

        # =========================
        # 📊 TODAY SALES
        # =========================

        if parsed["type"] == "TODAY_SALES":

            total = get_today_sales(db)

            send_whatsapp_message(
                phone,
                f"📊 Today's sales: ₦{total:,}"
            )

            return {"status": "today_sales"}

        # =========================
        # 📊 WEEKLY SALES
        # =========================

        if parsed["type"] == "WEEKLY_SALES":

            total = get_weekly_sales(db)

            send_whatsapp_message(
                phone,
                f"📊 Weekly sales: ₦{total:,}"
            )

            return {"status": "weekly_sales"}

        # =========================
        # 📊 MONTHLY SALES
        # =========================

        if parsed["type"] == "MONTHLY_SALES":

            total = get_monthly_sales(db)

            send_whatsapp_message(
                phone,
                f"📊 Monthly sales: ₦{total:,}"
            )

            return {"status": "monthly_sales"}

        # =========================
        # 📊 YEARLY SALES
        # =========================

        if parsed["type"] == "YEARLY_SALES":

            total = get_yearly_sales(db)

            send_whatsapp_message(
                phone,
                f"📊 Yearly sales: ₦{total:,}"
            )

            return {"status": "yearly_sales"}

        # =========================
        # 💰 BALANCE CHECK
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

            balance = get_balance(db, customer.id)

            if balance < 0:
                msg = f"{customer.name} credit: ₦{abs(balance):,}"
            else:
                msg = f"{customer.name} balance: ₦{balance:,}"

            send_whatsapp_message(phone, msg)

            return {"status": "balance"}

        # =========================
        # 👤 HANDLE HE / SHE
        # =========================

        customer_name = parsed["name"].lower()

        if customer_name in ["he", "she"]:

            memory = db.query(CustomerMemory).filter(
                CustomerMemory.phone == phone
            ).first()

            if memory and memory.last_customer:

                customer_name = memory.last_customer.lower()

            else:

                send_whatsapp_message(
                    phone,
                    "No previous customer found."
                )

                return {"status": "no_memory"}

        # =========================
        # 👥 FIND OR CREATE CUSTOMER
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
        # 🧹 CLEAR OLD PENDING
        # =========================

        db.query(PendingAction).filter(
            PendingAction.phone == phone
        ).delete()

        db.commit()

        # =========================
        # ⏳ SAVE PENDING ACTION
        # =========================

        pending = PendingAction(
            phone=phone,
            customer_name=customer.name,
            last_customer=customer.name,
            action=parsed["action"],
            buy_amount=parsed["buy_amount"],
            paid_amount=parsed["paid_amount"]
        )

        db.add(pending)

        db.commit()

        # =========================
        # 🧾 BUILD CONFIRMATION
        # =========================

        if parsed["action"] == "BUY":

            confirm_msg = (
                f"Confirm:\n"
                f"{customer.name} bought ₦{parsed['buy_amount']:,}?\n"
                f"Reply YES or EDIT"
            )

        elif parsed["action"] == "PAY":

            confirm_msg = (
                f"Confirm:\n"
                f"{customer.name} paid ₦{parsed['paid_amount']:,}?\n"
                f"Reply YES or EDIT"
            )

        elif parsed["action"] == "COMBINED":

            confirm_msg = (
                f"Confirm:\n"
                f"{customer.name} bought ₦{parsed['buy_amount']:,} "
                f"and paid ₦{parsed['paid_amount']:,}?\n"
                f"Reply YES or EDIT"
            )

        send_whatsapp_message(phone, confirm_msg)

        return {"status": "pending"}

    finally:
        db.close()
