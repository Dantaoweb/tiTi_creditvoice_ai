import os
import re
from datetime import datetime

from fastapi import FastAPI, Request
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base

# =========================
# 🔐 CONFIG CHECK
# =========================
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set. Fix your environment variables.")

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
    name = Column(String, index=True)


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    type = Column(String)  # BUY or PAY
    amount = Column(Integer)  # stored as whole number (no float)
    created_at = Column(DateTime, default=datetime.utcnow)
    message_id = Column(String, unique=True)  # idempotency


class PendingAction(Base):
    __tablename__ = "pending_actions"

    id = Column(Integer, primary_key=True)
    phone = Column(String, index=True)
    customer_name = Column(String)
    action = Column(String)  # BUY or PAY
    amount = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(engine)

# =========================
# 🔧 UTILITIES
# =========================

def send_whatsapp_message(to, message):
    """Replace this with your WhatsApp API call"""
    print(f"TO {to}: {message}")


def parse_message(text):
    """
    Parses:
    - Ola bought rice 5000
    - Ola bought 5000
    - Ola paid 2000
    """

    text = text.lower()

    # Extract amount (last number in string)
    numbers = re.findall(r"\d+", text)
    if not numbers:
        return None

    amount = int(numbers[-1])

    # Detect action
    if "bought" in text or "buy" in text:
        action = "BUY"
    elif "paid" in text or "pay" in text:
        action = "PAY"
    elif "balance" in text:
        return {"type": "BALANCE"}
    else:
        return None

    # Extract name (first word)
    words = text.split()
    name = words[0]

    return {
        "type": "TRANSACTION",
        "name": name,
        "action": action,
        "amount": amount
    }


def get_balance(db, customer_id):
    """Compute balance (BUY increases debt, PAY reduces it)"""
    txs = db.query(Transaction).filter(Transaction.customer_id == customer_id).all()

    balance = 0
    for tx in txs:
        if tx.type == "BUY":
            balance += tx.amount
        else:
            balance -= tx.amount

    return balance


# =========================
# 🌐 WEBHOOK
# =========================

@app.post("/webhook")
async def webhook(req: Request):
    data = await req.json()

    try:
        entry = data["entry"][0]
        message = entry["changes"][0]["value"]["messages"][0]

        text = message["text"]["body"]
        phone = message["from"]
        message_id = message["id"]

    except:
        return {"status": "ignored"}

    db = SessionLocal()

    try:
        # =========================
        # 🛑 IDEMPOTENCY CHECK
        # =========================
        existing = db.query(Transaction).filter(Transaction.message_id == message_id).first()
        if existing:
            return {"status": "duplicate"}

        # =========================
        # 🔄 CHECK PENDING ACTION
        # =========================
        pending = db.query(PendingAction).filter(PendingAction.phone == phone).first()

        if pending:
            if text.lower() == "yes":
                # confirm transaction

                customer = db.query(Customer).filter(Customer.name == pending.customer_name).first()

                if not customer:
                    send_whatsapp_message(phone, "Customer not found.")
                    db.delete(pending)
                    db.commit()
                    return {"status": "error"}

                tx = Transaction(
                    customer_id=customer.id,
                    type=pending.action,
                    amount=pending.amount,
                    message_id=message_id
                )

                db.add(tx)
                db.delete(pending)
                db.commit()

                balance = get_balance(db, customer.id)

                send_whatsapp_message(
                    phone,
                    f"✅ Saved.\n{customer.name} balance: ₦{balance}"
                )

                return {"status": "saved"}

            elif text.lower() == "edit":
                send_whatsapp_message(phone, "Enter new transaction (e.g. Ola paid 2000)")
                db.delete(pending)
                db.commit()
                return {"status": "edit"}

        # =========================
        # 🧠 PARSE MESSAGE
        # =========================
        parsed = parse_message(text)

        if not parsed:
            send_whatsapp_message(phone, "Invalid format.")
            return {"status": "invalid"}

        # =========================
        # 📊 BALANCE REQUEST
        # =========================
        if parsed["type"] == "BALANCE":
            name = text.split()[0]
            customer = db.query(Customer).filter(Customer.name.ilike(f"%{name}%")).first()

            if not customer:
                send_whatsapp_message(phone, "Customer not found.")
                return {"status": "not found"}

            balance = get_balance(db, customer.id)

            send_whatsapp_message(phone, f"{customer.name} balance: ₦{balance}")
            return {"status": "balance"}

        # =========================
        # 👤 CUSTOMER RESOLVE
        # =========================
        customer = db.query(Customer).filter(Customer.name.ilike(parsed["name"])).first()

        if not customer:
            # create new customer
            customer = Customer(name=parsed["name"])
            db.add(customer)
            db.commit()

        # =========================
        # 📝 CREATE PENDING
        # =========================
        pending = PendingAction(
            phone=phone,
            customer_name=customer.name,
            action=parsed["action"],
            amount=parsed["amount"]
        )

        db.add(pending)
        db.commit()

        action_word = "bought" if parsed["action"] == "BUY" else "paid"

        send_whatsapp_message(
            phone,
            f"Confirm: {customer.name} {action_word} ₦{parsed['amount']}?\nReply YES or EDIT"
        )

        return {"status": "pending"}

    finally:
        db.close()
