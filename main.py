from fastapi import FastAPI, Request
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
from sqlalchemy import create_engine, Column, String, Float, DateTime
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
    customer_balance = Column(Float, default=0.0)  # ✅ NEW
    status = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# ---------------- APP ----------------
app = FastAPI()

# ---------------- GLOBAL ----------------
processed_messages = set()
pending_actions = {}

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

    requests.post(url, headers=headers, json=payload)

# ---------------- AI ----------------
def titi_ai_process(user_text):
    prompt = f"""
Return ONLY JSON:
{{
  "action": "create_transaction" OR "record_payment",
  "customer_name": "string",
  "amount": number
}}
Message: "{user_text}"
"""
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()

# ---------------- HELPERS ----------------
def format_money(amount):
    return f"₦{int(amount):,}"

def get_customer_latest(db, name):
    return db.query(Transaction).filter(
        Transaction.customer_name.ilike(name)
    ).order_by(Transaction.created_at.desc()).first()

# ---------------- CORE LOGIC ----------------
def create_transaction_internal(name, amount):
    db = SessionLocal()

    last = get_customer_latest(db, name)
    credit = last.customer_balance if last else 0

    # 🔥 USE CREDIT
    if credit >= amount:
        remaining = 0
        paid = amount
        credit -= amount
    else:
        remaining = amount - credit
        paid = amount - remaining
        credit = 0

    txn = Transaction(
        id=str(uuid.uuid4()),
        customer_name=name,
        amount_total=amount,
        amount_paid=paid,
        amount_remaining=remaining,
        customer_balance=credit,
        status="paid" if remaining == 0 else "pending"
    )

    db.add(txn)
    db.commit()
    db.refresh(txn)
    db.close()

    return txn


def record_payment_internal(name, amount):
    db = SessionLocal()

    txn = db.query(Transaction).filter(
        Transaction.customer_name.ilike(name),
        Transaction.amount_remaining > 0
    ).order_by(Transaction.created_at.desc()).first()

    if not txn:
        db.close()
        return None

    # 🔥 SMART PAYMENT
    if amount <= txn.amount_remaining:
        txn.amount_paid += amount
        txn.amount_remaining -= amount
    else:
        extra = amount - txn.amount_remaining
        txn.amount_paid += txn.amount_remaining
        txn.amount_remaining = 0
        txn.customer_balance += extra

    txn.status = "paid" if txn.amount_remaining == 0 else "partial"

    db.commit()
    db.refresh(txn)
    db.close()

    return txn

# ---------------- BALANCE ----------------
def get_balance(db, name):
    txn = get_customer_latest(db, name)
    if not txn:
        return None
    return txn

# ---------------- STATEMENT ----------------
def get_statement(db, name):
    txns = db.query(Transaction).filter(
        Transaction.customer_name.ilike(name)
    ).order_by(Transaction.created_at.asc()).all()

    return txns

# ---------------- ROUTES ----------------
@app.get("/")
def home():
    return {"message": "CrediVoice TiTi is live 🚀"}

# ---------------- WEBHOOK ----------------
@app.post("/webhook")
async def receive_message(request: Request):
    data = await request.json()

    try:
        message = data["entry"][0]["changes"][0]["value"]["messages"][0]

        message_id = message["id"]
        if message_id in processed_messages:
            return {"status": "duplicate"}
        processed_messages.add(message_id)

        sender = message["from"]
        text = message["text"]["body"].strip().lower()

        db = SessionLocal()

        # ---------------- BALANCE ----------------
        if "balance" in text:
            name = text.replace("balance", "").strip()
            txn = get_balance(db, name)

            if not txn:
                send_whatsapp_message(sender, "No record found")
            else:
                send_whatsapp_message(
                    sender,
                    f"{name.capitalize()} balance:\n"
                    f"Owes: {format_money(txn.amount_remaining)}\n"
                    f"Credit: {format_money(txn.customer_balance)}"
                )
            db.close()
            return {"status": "balance"}

        # ---------------- STATEMENT ----------------
        if "statement" in text:
            name = text.replace("statement", "").strip()
            txns = get_statement(db, name)

            if not txns:
                send_whatsapp_message(sender, "No record found")
            else:
                msg = f"{name.capitalize()} statement:\n\n"
                for t in txns:
                    msg += f"• Total: {format_money(t.amount_total)} | Paid: {format_money(t.amount_paid)} | Rem: {format_money(t.amount_remaining)}\n"

                msg += f"\nCredit: {format_money(txns[-1].customer_balance)}"

                send_whatsapp_message(sender, msg)

            db.close()
            return {"status": "statement"}

        # ---------------- CONFIRM ----------------
        if sender in pending_actions:

            if text == "yes":
                action_data = pending_actions.pop(sender)

                if action_data["action"] == "create_transaction":
                    txn = create_transaction_internal(
                        action_data["name"],
                        action_data["amount"]
                    )
                    reply = f"✅ Saved. {action_data['name']} owes {format_money(txn.amount_remaining)}"

                else:
                    txn = record_payment_internal(
                        action_data["name"],
                        action_data["amount"]
                    )
                    if txn.customer_balance > 0:
                        reply = (
                            f"✅ Payment recorded\n"
                            f"Remaining: {format_money(txn.amount_remaining)}\n"
                            f"💰 Credit: {format_money(txn.customer_balance)}"
                        )
                    else:
                        reply = f"✅ Payment recorded. Remaining: {format_money(txn.amount_remaining)}"

                send_whatsapp_message(sender, reply)
                return {"status": "confirmed"}

        # ---------------- AI ----------------
        ai = titi_ai_process(text)

        if ai.startswith("```"):
            ai = ai.split("```")[1]
        ai = ai.replace("json", "").strip()

        parsed = json.loads(ai)

        pending_actions[sender] = {
            "action": parsed["action"],
            "name": parsed["customer_name"],
            "amount": float(str(parsed["amount"]).replace(",", ""))
        }

        if parsed["action"] == "create_transaction":
            reply = f"Confirm: {parsed['customer_name']} bought {format_money(parsed['amount'])}?\nReply YES or EDIT"
        else:
            reply = f"Confirm: {parsed['customer_name']} paid {format_money(parsed['amount'])}?\nReply YES or EDIT"

        send_whatsapp_message(sender, reply)

    except Exception as e:
        print("Error:", e)

    return {"status": "ok"}
