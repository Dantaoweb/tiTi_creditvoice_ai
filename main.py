import os
import re
import requests
from datetime import datetime

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
    amount = Column(Integer)
    last_customer = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(engine)

# =========================
# 📤 WHATSAPP SEND (REAL)
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

    numbers = re.findall(r"\d+", text)
    if not numbers:
        return None

    amount = int(numbers[-1])

    if "paid" in text or "pay" in text:
        action = "PAY"
    elif "bought" in text or "buy" in text:
        action = "BUY"
    else:
        return None

    name = text.split()[0].lower()

    return {
        "type": "TRANSACTION",
        "name": name,
        "action": action,
        "amount": amount
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
# 🌐 WEBHOOK
# =========================

@app.post("/webhook")
async def webhook(req: Request):
    data = await req.json()

    try:
        message = data["entry"][0]["changes"][0]["value"]["messages"][0]
        text = message["text"]["body"]
        phone = message["from"]
        message_id = message["id"]
    except:
        return {"status": "ignored"}

    db = SessionLocal()

    try:
        if db.query(Transaction).filter(Transaction.message_id == message_id).first():
            return {"status": "duplicate"}

        pending = db.query(PendingAction).filter(PendingAction.phone == phone, PendingAction.action != None).first()

        if pending:
            if text.lower() == "yes":

                customer = db.query(Customer).filter(
                    Customer.name == pending.customer_name,
                    Customer.owner_phone == phone
                ).first()

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
                    f"✅ Saved.\n{customer.name} balance: ₦{balance:,}"
                )

                return {"status": "saved"}

            elif text.lower() == "edit":
                db.delete(pending)
                db.commit()

                send_whatsapp_message(phone, "Enter again (e.g. Ola paid 2000)")
                return {"status": "edit"}

        parsed = parse_message(text)

        # Handle "he paid" or "she paid"
        if parsed and parsed.get("name") in ["he", "she"]:
            memory = db.query(PendingAction).filter(
                PendingAction.phone == phone, PendingAction.last_customer !=None
            ).order_by(PendingAction.created_at.desc()).first()

            if memory and memory.last_customer:
                parsed["name"] = memory.last_customer

        if not parsed:
            send_whatsapp_message(phone, "Invalid format.")
            return {"status": "invalid"}

        if parsed.get("error"):
            send_whatsapp_message(phone, parsed["error"])
            return {"status": "error"}

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

            send_whatsapp_message(phone, f"{customer.name} balance: ₦{balance:,}")
            return {"status": "balance"}

        customer = db.query(Customer).filter(
            Customer.name == parsed["name"],
            Customer.owner_phone == phone
        ).first()

        if parsed["name"] in ["he", "she"]:
             send_whatsapp_message(phone, "Please specify customer name.")
             return {"status": "invalid_pronoun"}

        if not customer:
            customer = Customer(
                name=parsed["name"].lower(),
                owner_phone=phone
            )
            db.add(customer)
            db.commit()

        pending = PendingAction(
            phone=phone,
            customer_name=customer.name,
            last_customer=customer.name,
            action=parsed["action"],
            amount=parsed["amount"]
        )

        db.add(pending)
        db.commit()

        action_word = "bought" if parsed["action"] == "BUY" else "paid"

        send_whatsapp_message(
            phone,
            f"Confirm: {customer.name} {action_word} ₦{parsed['amount']:,}?\nReply YES or EDIT"
        )

        return {"status": "pending"}

    finally:
        db.close()
