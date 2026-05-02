from fastapi import FastAPI, Request
import requests
import os
import re
from sqlalchemy import create_engine, Column, String, Float
from sqlalchemy.orm import sessionmaker, declarative_base
from uuid import uuid4

app = FastAPI()

# ================= DATABASE =================
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String, primary_key=True)
    customer_name = Column(String)
    amount_total = Column(Float)
    amount_paid = Column(Float)
    amount_remaining = Column(Float)
    credit = Column(Float, default=0)
    status = Column(String)

Base.metadata.create_all(bind=engine)

# ================= WHATSAPP =================
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

def send_whatsapp_message(to, message):
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }

    response = requests.post(url, headers=headers, json=payload)
    print("WhatsApp:", response.text)

# ================= SESSION MEMORY =================
user_sessions = {}

# ================= HELPERS =================
def extract_amount(text):
    text = text.replace(",", "")
    match = re.search(r"\d+", text)
    return float(match.group()) if match else 0

def extract_name(text):
    return text.split()[0].lower()

# ================= WEBHOOK =================
@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    print("Incoming:", data)

    try:
        value = data["entry"][0]["changes"][0]["value"]

        if "messages" not in value:
            return {"status": "ok"}

        message = value["messages"][0]
        sender = message["from"]
        text = message["text"]["body"].lower().strip()

        db = SessionLocal()

        session = user_sessions.get(sender, {})

        # ================= YES =================
        if text == "yes":
            if not session:
                send_whatsapp_message(sender, "Nothing to confirm.")
                return {"status": "ok"}

            customer = session["customer"]
            amount = session["amount"]
            action = session["type"]

            record = db.query(Transaction).filter_by(customer_name=customer).first()

            if action == "buy":
                if not record:
                    record = Transaction(
                        id=str(uuid4()),
                        customer_name=customer,
                        amount_total=amount,
                        amount_paid=0,
                        amount_remaining=amount,
                        credit=0,
                        status="pending"
                    )
                else:
                    # apply credit first
                    if record.credit > 0:
                        if record.credit >= amount:
                            record.credit -= amount
                            amount = 0
                        else:
                            amount -= record.credit
                            record.credit = 0

                    record.amount_total += amount
                    record.amount_remaining += amount

                db.add(record)
                db.commit()

                send_whatsapp_message(
                    sender,
                    f"Saved. {customer} owes ₦{int(record.amount_remaining)}"
                )

            elif action == "pay":
                if not record:
                    send_whatsapp_message(sender, "Customer not found.")
                    return {"status": "ok"}

                record.amount_paid += amount

                if amount > record.amount_remaining:
                    extra = amount - record.amount_remaining
                    record.credit += extra
                    record.amount_remaining = 0
                else:
                    record.amount_remaining -= amount

                if record.amount_remaining == 0:
                    record.status = "paid"

                db.commit()

                msg = f"Payment recorded\nRemaining: ₦{int(record.amount_remaining)}"
                if record.credit > 0:
                    msg += f"\n💰 Credit: ₦{int(record.credit)}"

                send_whatsapp_message(sender, msg)

            user_sessions[sender] = {}

            return {"status": "ok"}

        # ================= EDIT =================
        if text == "edit":
            if not session:
                send_whatsapp_message(sender, "Nothing to edit.")
                return {"status": "ok"}

            session["editing"] = True
            send_whatsapp_message(sender, "Enter new amount:")
            return {"status": "ok"}

        # ================= HANDLE EDIT INPUT =================
        if session.get("editing"):
            amount = extract_amount(text)

            if amount <= 0:
                send_whatsapp_message(sender, "Enter valid amount.")
                return {"status": "ok"}

            session["amount"] = amount
            session["editing"] = False

            send_whatsapp_message(
                sender,
                f"Confirm: {session['customer']} {session['type']} ₦{int(amount)}?\nReply YES or EDIT"
            )
            return {"status": "ok"}

        # ================= BALANCE =================
        if text.startswith("balance"):
            parts = text.split()
            if len(parts) < 2:
                send_whatsapp_message(sender, "Use: balance name")
                return {"status": "ok"}

            customer = parts[1]

            record = db.query(Transaction).filter_by(customer_name=customer).first()

            if not record:
                send_whatsapp_message(sender, "No record found.")
                return {"status": "ok"}

            msg = f"{customer} owes ₦{int(record.amount_remaining)}"
            if record.credit > 0:
                msg += f"\n💰 Credit: ₦{int(record.credit)}"

            send_whatsapp_message(sender, msg)
            return {"status": "ok"}

        # ================= NORMAL INPUT =================
        words = text.split()

        if len(words) < 3:
            send_whatsapp_message(sender, "Invalid format.")
            return {"status": "ok"}

        customer = words[0]
        action_word = words[1]
        amount = extract_amount(text)

        if amount <= 0:
            send_whatsapp_message(sender, "Invalid amount.")
            return {"status": "ok"}

        if "buy" in action_word:
            action = "buy"
        elif "paid" in action_word or "pay" in action_word:
            action = "pay"
        else:
            send_whatsapp_message(sender, "Use 'bought' or 'paid'")
            return {"status": "ok"}

        user_sessions[sender] = {
            "customer": customer,
            "amount": amount,
            "type": action
        }

        send_whatsapp_message(
            sender,
            f"Confirm: {customer} {action} ₦{int(amount)}?\nReply YES or EDIT"
        )

        return {"status": "ok"}

    except Exception as e:
        print("Error:", str(e))
        return {"status": "error"}
