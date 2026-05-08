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
    amount = Column(Integer)
    last_customer = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class CustomerMemory(Base):
    __tablename__ = "customer_memory"

    id = Column(Integer, primary_key=True)
    phone = Column(String, unique=True)
    last_customer = Column(String)
    
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

    if text == "today sales":
        return {"type": "TODAY_SALES"}

    if text == "weekly sales":
        return {"type": "WEEKLY_SALES"}

    
    if text == "monthly sales":
        return {"type": "MONTHLY_SALES"}  

  
    clean_text = text.replace(",", "")
    words = clean_text.split()
    
    amount = None
    
    for word in words:
        if word.isdigit():
            amount = int(word)
    
    if amount is None:
        return None


    if "paid" in clean_text or "pay" in clean_text:
        action = "PAY"
    elif "bought" in clean_text or "buy" in clean_text:
        action = "BUY"
    else:
        return None

    # Split message into words
    words = text.split()

    # Find transaction action position
    action_index = None

    for i, word in enumerate(words):
        if word in ["bought", "buy", "paid", "pay"]:
            action_index = i
            break

    # Stop if no valid action found
    if action_index is None:
        return None

    # Everything before action becomes customer name
    name = " ".join(words[:action_index]).lower()

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

        # Prevent duplicate processing
        existing_tx = db.query(Transaction).filter(
            Transaction.message_id == message_id
        ).first()

        if existing_tx:
            return {"status": "duplicate"}

        # =========================
        # CHECK PENDING ACTION
        # =========================

        pending = db.query(PendingAction).filter(
            PendingAction.phone == phone,
            PendingAction.action != None
        ).order_by(PendingAction.created_at.desc()
                  ).first()

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
                    create_at=datetime.utcnow()
                )

                db.add(tx)
                memory =db.query(CustomerMemory).filter(
                    CustomerMemory.phone == phone
                ).first()

                #if no memory exists yet
                if not memory:
                    memory = CustomerMemory(phone=phone,
                                            last_customer=customer.name
                                           )
                    db.add(memory)

                #update existing memory
                else:
                    memory.last_customer = customer.name

                   
                
                db.delete(pending)
                db.commit()

                balance = get_balance(db, customer.id)

                # CREDIT DISPLAY
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

        # =========================
        # PARSE MESSAGE
        # =========================

        parsed = parse_message(text)

        if not parsed:
            send_whatsapp_message(phone, "Invalid format.")
            return {"status": "invalid"}

        # =========================
        # BALANCE CHECK
        # =========================
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

        # =========================
        # HANDLE HE / SHE
        # =========================

        customer_name = parsed["name"].lower()

        if customer_name in ["he", "she"]:

            memory = db.query(CustomerMemory).filter(
                CustomerMemory.phone == phone
            ).first()

            
            #if memory exists
            if memory and memory.last_customer:

                customer_name = memory.last_customer.lower()

            else:

                send_whatsapp_message(
                    phone,
                    "No previous customer found."
                )

                return {"status": "no_memory"}

        # =========================
        # FIND OR CREATE CUSTOMER
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
        # SAVE PENDING ACTION
        # =========================

        db.query(PendingAction).filter(
            PendingAction.phone == phone
        ).delete()

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
