from fastapi import FastAPI, Request
import os, re, requests, uuid
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base

app = FastAPI()

# ================= DATABASE =================
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise Exception("DATABASE_URL is not set")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# ================= MODELS =================
class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)
    phone = Column(String, unique=True)

class Customer(Base):
    __tablename__ = "customers"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"))
    name = Column(String)

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(String, primary_key=True)
    user_id = Column(String)
    customer_id = Column(String)
    type = Column(String)  # BUY / PAY
    amount = Column(Integer)  # ✅ FIXED (no float)
    description = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    source_message_id = Column(String, unique=True)  # ✅ idempotency

Base.metadata.create_all(bind=engine)

# ================= WHATSAPP =================
TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_ID = os.getenv("PHONE_NUMBER_ID")

def send(to, msg):
    url = f"https://graph.facebook.com/v18.0/{PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": msg}}
    r = requests.post(url, headers=headers, json=payload)
    print("WA:", r.text)

# ================= SESSION =================
sessions = {}

# ================= PARSER =================
def parse(text):
    text = text.lower().replace(",", "")

    amount_match = re.search(r"\d+", text)
    if not amount_match:
        return None

    amount = int(amount_match.group())  # ✅ integer

    action = None
    if "bought" in text:
        action = "BUY"
    elif "paid" in text:
        action = "PAY"

    if not action:
        return None

    words = text.split()
    name = words[0]

    return name, action, amount

# ================= HELPERS =================
def get_user(db, phone):
    user = db.query(User).filter_by(phone=phone).first()
    if not user:
        user = User(id=str(uuid.uuid4()), phone=phone)
        db.add(user)
        db.commit()
    return user

def get_customers(db, user_id, name):
    return db.query(Customer).filter(
        Customer.user_id == user_id,
        Customer.name.ilike(name)
    ).all()

def create_customer(db, user_id, name):
    c = Customer(id=str(uuid.uuid4()), user_id=user_id, name=name)
    db.add(c)
    db.commit()
    return c

def compute_balance(db, user_id, customer_id):
    txns = db.query(Transaction).filter_by(
        user_id=user_id,
        customer_id=customer_id
    ).all()

    balance = 0
    for t in txns:
        if t.type == "BUY":
            balance += t.amount
        else:
            balance -= t.amount

    return balance

# ================= WEBHOOK =================
@app.post("/webhook")
async def webhook(req: Request):
    data = await req.json()
    try:
        value = data["entry"][0]["changes"][0]["value"]

        if "messages" not in value:
            return {"ok": True}

        msg = value["messages"][0]
        sender = msg["from"]
        message_id = msg["id"]  # ✅ used for idempotency
        text = msg["text"]["body"].strip()

        db = SessionLocal()

        # ================= IDEMPOTENCY CHECK =================
        existing = db.query(Transaction).filter_by(source_message_id=message_id).first()
        if existing:
            print("Duplicate message ignored")
            db.close()
            return {"ok": True}

        user = get_user(db, sender)
        session = sessions.get(sender, {})

        # ================= DUPLICATE FLOW =================
        if session.get("state") == "duplicate":

            if text.isdigit():
                idx = int(text) - 1

                if idx < 0 or idx >= len(session["matches"]):  # ✅ FIXED
                    send(sender, "Invalid selection. Choose a valid number.")
                    db.close()
                    return {"ok": True}

                customer = session["matches"][idx]

                sessions[sender] = {
                    "state": "confirm",
                    "customer": customer,
                    "action": session["action"],
                    "amount": session["amount"]
                }

                send(sender, f"Confirm: {customer.name} {session['action']} ₦{session['amount']}\nYES or EDIT")
                db.close()
                return {"ok": True}

            elif text.lower() == "edit":
                session["state"] = "rename"
                send(sender, "Enter new customer name:")
                db.close()
                return {"ok": True}

            else:
                send(sender, "Reply 1, 2 or EDIT")
                db.close()
                return {"ok": True}

        # ================= RENAME =================
        if session.get("state") == "rename":
            new_name = text
            sessions[sender] = {
                "state": "confirm",
                "new_name": new_name,
                "action": session["action"],
                "amount": session["amount"]
            }
            send(sender, f"Confirm: {new_name} {session['action']} ₦{session['amount']}\nYES or EDIT")
            db.close()
            return {"ok": True}

        # ================= CONFIRM =================
        if text.lower() == "yes" and session.get("state") == "confirm":

            name = session.get("new_name") or session["customer"].name
            action = session["action"]
            amount = session["amount"]

            if session.get("new_name"):
                customer = create_customer(db, user.id, name)
            else:
                customer = session["customer"]

            txn = Transaction(
                id=str(uuid.uuid4()),
                user_id=user.id,
                customer_id=customer.id,
                type=action,
                amount=amount,
                description="",
                source_message_id=message_id  # ✅ idempotency saved
            )

            db.add(txn)
            db.commit()

            balance = compute_balance(db, user.id, customer.id)

            send(sender, f"Saved.\n{customer.name} balance: ₦{balance}")

            sessions[sender] = {"last_customer": customer}

            db.close()
            return {"ok": True}

        # ================= COMMAND =================
        if text.lower().startswith("balance"):
            name = text.split(" ")[1]
            customers = get_customers(db, user.id, name)

            if not customers:
                send(sender, "No customer found")
                db.close()
                return {"ok": True}

            c = customers[0]
            bal = compute_balance(db, user.id, c.id)
            send(sender, f"{c.name} balance: ₦{bal}")

            db.close()
            return {"ok": True}

        # ================= PARSE =================
        parsed = parse(text)

        if not parsed:
            send(sender, "Try:\nOla bought rice 5000\nOla paid 2000")
            db.close()
            return {"ok": True}

        name, action, amount = parsed

        matches = get_customers(db, user.id, name)

        if not matches:
            sessions[sender] = {
                "state": "confirm",
                "new_name": name,
                "action": action,
                "amount": amount
            }
            send(sender, f"Confirm: {name} {action} ₦{amount}\nYES or EDIT")
            db.close()
            return {"ok": True}

        if len(matches) == 1:
            sessions[sender] = {
                "state": "confirm",
                "customer": matches[0],
                "action": action,
                "amount": amount
            }
            send(sender, f"Confirm: {matches[0].name} {action} ₦{amount}\nYES or EDIT")
            db.close()
            return {"ok": True}

        msg_text = "Multiple customers found:\n"
        for i, c in enumerate(matches):
            bal = compute_balance(db, user.id, c.id)
            msg_text += f"{i+1}. {c.name} (₦{bal})\n"

        msg_text += "\nReply 1, 2 or EDIT"

        sessions[sender] = {
            "state": "duplicate",
            "matches": matches,
            "action": action,
            "amount": amount
        }

        send(sender, msg_text)
        db.close()
        return {"ok": True}

    except Exception as e:
        print("ERROR:", e)

    return {"ok": True}
