from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid

app = FastAPI()

# ---------------------------
# In-memory DB (for MVP)
# Replace with PostgreSQL later
# ---------------------------

transactions = {}
payments = {}

# ---------------------------
# Models
# ---------------------------

class TransactionCreate(BaseModel):
    customer_name: str
    item_name: str
    amount: float
    payment_type: str  # cash, transfer, credit
    due_date: Optional[str] = None

class PaymentCreate(BaseModel):
    transaction_id: str
    amount: float

# ---------------------------
# Health check
# ---------------------------

@app.get("/")
def home():
    return {"message": "CrediVoice TiTi is live 🚀"}

# ---------------------------
# Create transaction
# ---------------------------

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

    return {
        "message": "Transaction recorded",
        "data": transactions[transaction_id]
    }

# ---------------------------
# Record payment (partial/full)
# ---------------------------

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

    return {
        "message": "Payment recorded",
        "transaction": txn
    }

# ---------------------------
# Get all transactions
# ---------------------------

@app.get("/transactions")
def get_transactions():
    return list(transactions.values())

# ---------------------------
# Dashboard summary
# ---------------------------

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
