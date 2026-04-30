from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid
import requests
import os
import json
from openai import OpenAI

# ---------------- ENV ----------------
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
DATABASE_URL = os.getenv("DATABASE_URL")

# ---------------- DATABASE ----------------
from sqlalchemy import create_engine, Column, String, Float
from sqlalchemy.orm import sessionmaker, declarative_base

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
    status = Column(String)

Base.metadata.create_all(bind=engine)

# ---------------- APP ----------------
app = FastAPI()

# ---------------- GLOBAL ----------------
processed_messages = set()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = "creditvoice_verify_123"
# ---------------- WHATSAPP SEND ----------------
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
    print("WhatsApp response:", response.text)

# ---------------- AI ----------------
def titi_ai_process(user_text):

    prompt = f"""
    You are TiTi, a smart assistant for business credit tracking.

    Extract from the message:
    - action: "create_transaction" or "record_payment"
    - customer_name
    - amount

    Message: "{user_text}"

    Return ONLY JSON like:
    {{
      "action": "...",
      "customer_name": "...",
      "amount": number
    }}
    """

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content

# ---------------- MODELS ----------------
class TransactionCreate(BaseModel):
    customer_name: str
    item_name: str
    amount: float
    payment_type: str
    due_date: Optional[str] = None

class PaymentCreate(BaseModel):
    transaction_id: str
    amount: float

# ---------------- DATABASE FUNCTIONS ----------------
def create_transaction_internal(name, amount):
    db = SessionLocal()

    txn = Transaction(
        id=str(uuid.uuid4()),
        customer_name=name,
        amount_total=amount,
        amount_paid=0,
        amount_remaining=amount,
        status="pending"
    )

    db.add(txn)
    db.commit()
    db.refresh(txn)
    db.close()

    return txn


def record_payment_internal(name, amount):
    db = SessionLocal()

    txn = db.query(Transaction).filter(
        Transaction.customer_name.ilike(name)
    ).first()

    if not txn:
        db.close()
        return None

    txn.amount_paid += amount
    txn.amount_remaining -= amount

    if txn.amount_remaining <= 0:
        txn.amount_remaining = 0
        txn.status = "paid"
    else:
        txn.status = "partial"

    db.commit()
    db.refresh(txn)
    db.close()

    return txn

# ---------------- ROUTES ----------------
@app.get("/")
def home():
    return {"message": "CrediVoice TiTi is live 🚀"}

@app.get("/test-ai")
def test_ai(message: str):

    ai_response = titi_ai_process(message)
    parsed = json.loads(ai_response)

    action = parsed.get("action")
    name = parsed.get("customer_name")
    amount = parsed.get("amount")

    if action == "create_transaction":
        txn = create_transaction_internal(name, amount)
        return {"reply": f"{name} now owes ₦{txn.amount_remaining}"}

    elif action == "record_payment":
        txn = record_payment_internal(name, amount)

        if txn:
            return {"reply": f"{name} paid ₦{amount}. Remaining: ₦{int(txn.amount_remaining)}"}
        else:
            return {"reply": f"No record found for {name}"}

    return {"reply": "Didn't understand"}

# ---------------- WEBHOOK VERIFY ----------------
@app.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return int(challenge)

    return {"error": "Verification failed"}

# ---------------- WEBHOOK RECEIVE ----------------
@app.post("/webhook")
async def receive_message(request: Request):
    data = await request.json()

    try:
        message = data["entry"][0]["changes"][0]["value"]["messages"][0]

        message_id = message["id"]

        if message_id in processed_messages:
            return {"status": "duplicate ignored"}

        processed_messages.add(message_id)

        text = message["text"]["body"]
        sender = message["from"]

        ai_response = titi_ai_process(text)
        parsed = json.loads(ai_response)

        action = parsed.get("action")
        name = parsed.get("customer_name")
        amount = parsed.get("amount")

        if action == "create_transaction":
            txn = create_transaction_internal(name, amount)
            reply = f"{name} now owes ₦{txn.amount_remaining}"

        elif action == "record_payment":
            txn = record_payment_internal(name, amount)

            if txn:
                reply = f"{name} paid ₦{amount}. Remaining: ₦{int(txn.amount_remaining)}"
            else:
                reply = f"No record found for {name}"

        else:
            reply = "Sorry, I didn't understand."

        send_whatsapp_message(sender, reply)

    except Exception as e:
        print("Error:", e)

    return {"status": "ok"}
