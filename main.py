from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid

app = FastAPI()

# In-memory storage (for now)
transactions = {}
payments = {}

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

# ---------------- ROUTES ----------------

@app.get("/")
def home():
    return {"message": "CrediVoice TiTi is live 🚀"}

# CREATE TRANSACTION
@app.post("/transactions")
def create_transaction(data: TransactionCreate):

    transaction_id = str(uuid.uuid4())

    amount_remaining = data.amount if data.payment_type == "credit" else 0
    status = "pending" if data.payment_type == "credit" else "paid"

    transactions[transaction_id] = {
        "id": transaction_id,
        "customer_name": data.customer_name,
        "item_name": data.item_name,
        "amount_total": data.amount,
        "amount_paid": 0,
        "amount_remaining": amount_remaining,
        "payment_type": data.payment_type,
        "due_date": data.due_date,
        "status": status,
        "created_at": str(datetime.now())
    }

    return {"message": "Transaction recorded", "data": transactions[transaction_id]}

# RECORD PAYMENT
@app.post("/payments")
def record_payment(data: PaymentCreate):

    if data.transaction_id not in transactions:
        raise HTTPException(status_code=404, detail="Transaction not found")

    txn = transactions[data.transaction_id]

    if txn["status"] == "paid":
        return {"message": "Already fully paid"}

    txn["amount_paid"] += data.amount
    txn["amount_remaining"] -= data.amount

    if txn["amount_remaining"] <= 0:
        txn["amount_remaining"] = 0
        txn["status"] = "paid"
    else:
        txn["status"] = "partial"

    payment_id = str(uuid.uuid4())

    payments[payment_id] = {
        "id": payment_id,
        "transaction_id": data.transaction_id,
        "amount": data.amount,
        "date": str(datetime.now())
    }

    return {"message": "Payment recorded", "transaction": txn}

# GET ALL TRANSACTIONS
@app.get("/transactions")
def get_transactions():
    return list(transactions.values())

# DASHBOARD
@app.get("/dashboard")
def dashboard():

    total_sales = sum(t["amount_total"] for t in transactions.values())
    total_paid = sum(t["amount_paid"] for t in transactions.values())
    total_outstanding = sum(t["amount_remaining"] for t in transactions.values())

    return {
        "total_sales": total_sales,
        "total_paid": total_paid,
        "total_outstanding": total_outstanding,
        "total_transactions": len(transactions)
    }
from fastapi import Request

VERIFY_TOKEN = "creditvoice_verify_123"

@app.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return int(challenge)

    return {"error": "Verification failed"}

@app.post("/webhook")
async def receive_message(request: Request):
    data = await request.json()

    try:
        message = data["entry"][0]["changes"][0]["value"]["messages"][0]
        text = message["text"]["body"]

        print("User said:", text)

        # SIMPLE LOGIC (temporary)
        if "paid" in text.lower():
            response = "Payment recorded. Thank you."
        elif "bought" in text.lower():
            response = "Transaction recorded successfully."
        else:
            response = "Hello, I am TiTi. Tell me your sales or payments."

        print("TiTi response:", response)

    except Exception as e:
        print("Error:", e)

    return {"status": "ok"}
