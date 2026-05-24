import os
from typing import Optional

from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy import inspect

from database import SessionLocal, engine
from models import (
    AppAdminRole,
    Customer,
    CustomerMemory,
    InventoryItem,
    InventoryMovement,
    PendingAction,
    ProcessedMessage,
    ReminderMemory,
    SubscriptionPayment,
    Supplier,
    SupplierPayment,
    SupplierPurchase,
    Transaction,
    TransactionItem,
    TransactionNote,
    User,
)
from reports import dashboard_period_label, get_dashboard_summary
from schemas import CustomerCreate, UserCreate


def register_http_routes(app):
    @app.get("/debug/schema")
    def debug_schema(token: str):
        expected_token = os.getenv("WEBHOOK_VERIFY_TOKEN")
        if not expected_token or token != expected_token:
            return {"status": "unauthorized"}

        inspector = inspect(engine)
        models = [
            Customer,
            User,
            Transaction,
            TransactionItem,
            TransactionNote,
            Supplier,
            SupplierPurchase,
            SupplierPayment,
            InventoryItem,
            InventoryMovement,
            SubscriptionPayment,
            AppAdminRole,
            PendingAction,
            ProcessedMessage,
            CustomerMemory,
            ReminderMemory,
        ]

        result = {}
        for model in models:
            table_name = model.__tablename__
            db_columns = {
                column["name"]: str(column["type"])
                for column in inspector.get_columns(table_name)
            }
            model_columns = {
                column.name: str(column.type)
                for column in model.__table__.columns
            }
            mismatches = {}
            for column_name, model_type in model_columns.items():
                db_type = db_columns.get(column_name)
                if db_type and db_type.lower() != model_type.lower():
                    mismatches[column_name] = {
                        "model": model_type,
                        "database": db_type,
                    }

            result[table_name] = {
                "model": model_columns,
                "database": db_columns,
                "mismatches": mismatches,
            }

        return result

    @app.get("/")
    def home():
        return {"status": "CreditVoice running"}

    @app.post("/onboard/user")
    def onboard_user(user_data: UserCreate):
        db = SessionLocal()
        try:
            existing = db.query(User).filter(User.phone == user_data.phone).first()
            if existing:
                return {
                    "status": "exists",
                    "message": "User already onboarded",
                    "user": {
                        "id": existing.id,
                        "name": existing.name,
                        "phone": existing.phone,
                        "role": existing.role,
                        "business_category": existing.business_category,
                        "business_type": existing.business_type,
                        "business_type_label": existing.business_type_label,
                        "created_at": existing.created_at.isoformat()
                    }
                }

            user = User(
                name=user_data.name,
                phone=user_data.phone,
                role=user_data.role,
                business_category=user_data.business_category,
                business_type=user_data.business_type,
                business_type_label=user_data.business_type_label
            )
            db.add(user)
            db.commit()
            db.refresh(user)

            return {
                "status": "success",
                "user": {
                    "id": user.id,
                    "name": user.name,
                    "phone": user.phone,
                    "role": user.role,
                    "business_category": user.business_category,
                    "business_type": user.business_type,
                    "business_type_label": user.business_type_label,
                    "created_at": user.created_at.isoformat()
                }
            }
        finally:
            db.close()

    @app.post("/onboard/customer")
    def onboard_customer(customer_data: CustomerCreate):
        db = SessionLocal()
        try:
            owner = db.query(User).filter(User.phone == customer_data.owner_phone).first()
            if not owner:
                return {
                    "status": "owner_not_found",
                    "message": "Owner phone is not registered. Please onboard the user first."
                }

            customer = db.query(Customer).filter(
                Customer.name == customer_data.name,
                Customer.owner_phone == customer_data.owner_phone
            ).first()

            if customer:
                if customer_data.customer_phone:
                    customer.customer_phone = customer_data.customer_phone
                    db.commit()
                return {
                    "status": "exists",
                    "message": "Customer already onboarded",
                    "customer": {
                        "id": customer.id,
                        "name": customer.name,
                        "owner_phone": customer.owner_phone,
                        "customer_phone": customer.customer_phone,
                        "created_at": customer.created_at.isoformat()
                    }
                }

            customer = Customer(
                name=customer_data.name,
                owner_phone=customer_data.owner_phone,
                customer_phone=customer_data.customer_phone
            )
            db.add(customer)
            db.commit()
            db.refresh(customer)

            return {
                "status": "success",
                "customer": {
                    "id": customer.id,
                    "name": customer.name,
                    "owner_phone": customer.owner_phone,
                    "customer_phone": customer.customer_phone,
                    "created_at": customer.created_at.isoformat()
                }
            }
        finally:
            db.close()

    @app.get("/dashboard")
    def dashboard(owner_phone: Optional[str] = None, period: Optional[str] = None):
        db = SessionLocal()
        try:
            period_key = period.upper() if period else None
            return get_dashboard_summary(db, owner_phone, period_key)
        finally:
            db.close()

    @app.get("/dashboard/ui", response_class=HTMLResponse)
    def dashboard_ui(owner_phone: Optional[str] = None, period: Optional[str] = None):
        db = SessionLocal()
        try:
            period_key = period.upper() if period else None
            summary = get_dashboard_summary(db, owner_phone, period_key)
            period_label = dashboard_period_label(period_key)
            owner_label = owner_phone or "all owners"
            html = f"""
            <html>
                <head>
                    <title>CreditVoice Dashboard</title>
                    <style>
                        body {{ font-family: Arial, sans-serif; margin: 24px; }}
                        .card {{ border: 1px solid #ddd; border-radius: 10px; padding: 18px; margin-bottom: 16px; max-width: 600px; }}
                        .title {{ font-size: 24px; margin-bottom: 8px; }}
                        .metric {{ font-size: 20px; margin: 8px 0; }}
                        .label {{ color: #555; }}
                    </style>
                </head>
                <body>
                    <div class="card">
                        <div class="title">CreditVoice Dashboard</div>
                        <div class="metric"><span class="label">Owner:</span> {owner_label}</div>
                        <div class="metric"><span class="label">Period:</span> {period_label}</div>
                        <hr />
                        <div class="metric"><strong>Total customers:</strong> {summary['total_customers']:,}</div>
                        <div class="metric"><strong>New customers:</strong> {summary['new_customers']:,}</div>
                        <div class="metric"><strong>Paid customers:</strong> {summary['paid_customers']:,}</div>
                        <div class="metric"><strong>Total transactions:</strong> {summary['total_transactions']:,}</div>
                        <div class="metric"><strong>Credit sales:</strong> N{summary['credit_sales_amount']:,}</div>
                        <div class="metric"><strong>Direct sales:</strong> N{summary['direct_sales_amount']:,}</div>
                        <div class="metric"><strong>Total sales:</strong> N{summary['total_sales_amount']:,}</div>
                        <div class="metric"><strong>Payments received:</strong> N{summary['total_pay_amount']:,}</div>
                    </div>
                </body>
            </html>
            """
            return html
        finally:
            db.close()

    @app.get("/webhook")
    def verify_webhook(request: Request):
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")

        verify_token = os.getenv("WEBHOOK_VERIFY_TOKEN", "your_verify_token_here")

        if token == verify_token:
            return int(challenge)

        return {"status": "error"}
