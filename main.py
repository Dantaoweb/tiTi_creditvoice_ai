import os
import re
import json
import requests
from datetime import datetime, timedelta
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from sqlalchemy import (
    inspect,
    text
)

from admin import (
    build_app_admin_selection_message,
    is_app_admin,
    is_subscription_admin,
    support_line,
)
from admin_commands import handle_admin_subscription_command, notify_subscription_admins
from database import Base, SessionLocal, engine
from customer_commands import handle_customer_command
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
from schemas import CustomerCreate, UserCreate

from messages import (
    apply_voice_confirmation_options,
    build_invalid_message,
    build_owner_home_menu,
    build_plan_message,
    build_plan_payment_message,
    build_staff_home_menu,
    build_supported_formats_message,
    build_upgrade_message,
    edit_prompt_for_pending,
    pending_transaction_summary,
)
from parser import (
    build_customer_account_summary,
    interpret_text_with_openai,
    normalize_phone,
    parse_customer_account_request,
    parse_message,
    parse_slash_date,
    transcribe_whatsapp_voice,
)
from plans import (
    PLAN_GO,
    PLAN_PRO,
    normalize_plan,
)
from reports import (
    build_dashboard_menu_message,
    build_dashboard_selection_message,
    dashboard_period_label,
    get_balance,
    get_dashboard_summary,
    get_due_in_2_days,
    get_due_today,
    get_overdue_debtors,
)
from report_commands import handle_report_command
from reminder_commands import handle_reminder_command, handle_reminder_pending
from onboarding_commands import (
    handle_onboarding_pending,
    handle_post_onboarding_pending,
    handle_profile_command,
    start_onboarding,
)
from home_menu_commands import handle_home_menu_pending
from subscriptions import (
    create_subscription_payment_request,
    ensure_feature_allowed,
    get_business_owner_user,
    get_business_subscription,
)
from staff_commands import handle_staff_command
from supplier_commands import handle_supplier_command
from transaction_save import save_confirmed_pending_transaction
from transaction_setup import build_projected_balance_line, handle_transaction_setup

# =========================
# 🔐 ENV CONFIG
# =========================

if load_dotenv:
    load_dotenv()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

app = FastAPI()

# Models and request schemas are imported from models.py and schemas.py.

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


Base.metadata.create_all(engine)


def ensure_schema_updates():
    inspector = inspect(engine)
    user_columns = {
        column["name"]
        for column in inspector.get_columns("users")
    }

    if "can_view_all_transactions" not in user_columns:
        default_value = "FALSE" if engine.dialect.name == "postgresql" else "0"
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE users "
                    f"ADD COLUMN can_view_all_transactions BOOLEAN DEFAULT {default_value}"
                )
            )

    user_updates = {
        "business_category": "VARCHAR",
        "business_type": "VARCHAR",
        "business_type_label": "VARCHAR",
        "subscription_plan": "VARCHAR DEFAULT 'BASIC'",
        "subscription_status": "VARCHAR DEFAULT 'ACTIVE'",
        "subscription_expires_at": "TIMESTAMP"
    }
    with engine.begin() as connection:
        for column_name, column_type in user_updates.items():
            if column_name not in user_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE users ADD COLUMN {column_name} {column_type}"
                    )
                )

    pending_columns = {
        column["name"]
        for column in inspector.get_columns("pending_actions")
    }
    pending_updates = {
        "product": "VARCHAR",
        "quantity": "INTEGER",
        "unit": "VARCHAR",
        "unit_price": "INTEGER",
        "items_json": "VARCHAR",
        "source_text": "VARCHAR"
    }
    with engine.begin() as connection:
        for column_name, column_type in pending_updates.items():
            if column_name not in pending_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE pending_actions ADD COLUMN {column_name} {column_type}"
                    )
                )

    if engine.dialect.name == "postgresql":
        transaction_columns = {
            column["name"]: column
            for column in inspector.get_columns("transactions")
        }
        customer_id_column = transaction_columns.get("customer_id")
        if customer_id_column and not customer_id_column.get("nullable", True):
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE transactions ALTER COLUMN customer_id DROP NOT NULL")
                )


ensure_schema_updates()

# =========================
# 📤 WHATSAPP SEND
# =========================

def send_whatsapp_message(to, message):
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print(
            "WhatsApp send skipped: WHATSAPP_TOKEN or PHONE_NUMBER_ID is missing",
            flush=True
        )
        return False

    url = (
        f"https://graph.facebook.com/v18.0/"
        f"{PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": (
            f"Bearer {WHATSAPP_TOKEN}"
        ),
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

    try:
        response = requests.post(
            url,
            headers=headers,
            json=data,
            timeout=15
        )
    except requests.RequestException as exc:
        print("WhatsApp send failed:", repr(exc), flush=True)
        return False

    print("WhatsApp:", response.status_code, response.text, flush=True)
    return response.ok

# =========================
# 🧠 HELPERS
# =========================

def is_staff_user(user):
    return bool(user and user.role == "delegate" and user.parent_id)


def can_view_all_business_transactions(user):
    if not user:
        return False
    if user.role == "user" and not user.parent_id:
        return True
    return is_staff_user(user) and bool(user.can_view_all_transactions)


def visibility_recorded_by_id(user):
    if is_staff_user(user) and not can_view_all_business_transactions(user):
        return user.id
    return None


def get_media_evidence_ref(message, message_type):
    payload = message.get(message_type) or {}
    return payload.get("id") or message.get("id")


@app.get("/")
def home():
    return {"status": "CreditVoice running"}

# =========================
# 🧑‍💼 USER ONBOARDING
# =========================

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
        total_customers = summary["total_customers"]
        new_customers = summary["new_customers"]
        paid_customers = summary["paid_customers"]
        total_transactions = summary["total_transactions"]
        credit_sales = summary["credit_sales_amount"]
        direct_sales = summary["direct_sales_amount"]
        total_sales = summary["total_sales_amount"]
        stats = {
            "total_buy": summary["total_buy_amount"],
            "total_pay": summary["total_pay_amount"]
        }
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
                    <div class="metric"><strong>Total customers:</strong> {total_customers:,}</div>
                    <div class="metric"><strong>New customers:</strong> {new_customers:,}</div>
                    <div class="metric"><strong>Paid customers:</strong> {paid_customers:,}</div>
                    <div class="metric"><strong>Total transactions:</strong> {total_transactions:,}</div>
                    <div class="metric"><strong>Credit sales:</strong> ₦{credit_sales:,}</div>
                    <div class="metric"><strong>Direct sales:</strong> ₦{direct_sales:,}</div>
                    <div class="metric"><strong>Total sales:</strong> ₦{total_sales:,}</div>
                    <div class="metric"><strong>Payments received:</strong> ₦{stats['total_pay']:,}</div>
                </div>
            </body>
        </html>
        """
        return html
    finally:
        db.close()


# =========================
# ✅ WEBHOOK VERIFICATION
# =========================

@app.get("/webhook")
def verify_webhook(request: Request):
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    
    verify_token = os.getenv("WEBHOOK_VERIFY_TOKEN", "your_verify_token_here")
    
    if token == verify_token:
        return int(challenge)
    
    return {"status": "error"}

# =========================
# 🌐 WEBHOOK
# =========================

@app.post("/webhook")
async def webhook(req: Request):
    print("Webhook received", flush=True)
    try:
        print("Webhook content-type:", req.headers.get("content-type"), flush=True)
    except Exception:
        pass
    body = await req.json()
    print("Webhook body keys:", list(body.keys()), flush=True)
    try:
        value = body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})
        print("Webhook value keys:", list(value.keys()), flush=True)

        messages = value.get("messages") or []
        if not messages:
            print("Webhook contains no messages; likely status/delivery event", flush=True)
        else:
            message = messages[0]
            phone = message.get("from")
            text = (message.get("text") or {}).get("body", "").strip()
            print(f"Webhook parsed message from {phone}: {text}", flush=True)

            if phone and text:
                debug_db = SessionLocal()
                try:
                    sender_exists = debug_db.query(User).filter(
                        User.phone == phone
                    ).first()
                    print(
                        f"Webhook sender registered: {bool(sender_exists)}",
                        flush=True
                    )
                    if not sender_exists:
                        admin_preview = parse_message(text)
                        admin_allowed = False
                        if admin_preview:
                            admin_allowed = (
                                admin_preview["type"] in [
                                    "APP_ADMIN_DASHBOARD",
                                    "APP_ADMIN_USERS_BY_PLAN",
                                    "MANAGE_APP_ADMIN_ROLE",
                                    "LIST_APP_ADMIN_ROLES"
                                ] and is_app_admin(phone, debug_db)
                            ) or (
                                admin_preview["type"] in [
                                    "PENDING_SUBSCRIPTIONS",
                                    "APPROVE_SUBSCRIPTION",
                                    "REJECT_SUBSCRIPTION",
                                    "ACTIVATE_PLAN"
                                ] and is_subscription_admin(phone, debug_db)
                            )

                        if not admin_allowed:
                            print("Unregistered sender will continue to onboarding flow", flush=True)
                            raise LookupError("continue_to_onboarding")

                    early_visible_recorded_by_id = visibility_recorded_by_id(sender_exists)

                    pending = debug_db.query(PendingAction).filter(
                        PendingAction.phone == phone
                    ).order_by(
                        PendingAction.created_at.desc()
                    ).first()

                    if pending and text.lower().strip() in ["exit", "exist", "cancel", "done", "back", "stop", "close", "quit", "end"]:
                        debug_db.delete(pending)
                        debug_db.commit()
                        send_whatsapp_message(
                            phone,
                            "Closed. You can continue recording transactions."
                        )
                        return {"status": "pending_cancelled"}

                    if pending and pending.action in ["CUSTOMER_SUMMARY_MENU", "CUSTOMER_SUMMARY_DATE"]:
                        print(f"Customer summary follow-up reached: {text}", flush=True)

                        business_owner_phone = sender_exists.phone
                        if sender_exists.parent_id:
                            owner = debug_db.query(User).filter(
                                User.id == sender_exists.parent_id
                            ).first()
                            if owner:
                                business_owner_phone = owner.phone

                        replacement_account_request = parse_customer_account_request(text)
                        if replacement_account_request:
                            pending.customer_name = replacement_account_request["name"]
                            pending.action = "CUSTOMER_SUMMARY_MENU"
                            pending.last_customer = replacement_account_request["name"]
                            debug_db.commit()

                            msg = build_customer_account_summary(
                                debug_db,
                                business_owner_phone,
                                replacement_account_request["name"],
                                period=replacement_account_request["period"],
                                target_date=replacement_account_request["target_date"],
                                include_menu=True,
                                recorded_by_id=early_visible_recorded_by_id
                            )
                            send_whatsapp_message(phone, msg)
                            return {"status": "customer_summary_replaced"}

                        normalized = text.lower().strip()
                        period_map = {
                            "1": "TODAY",
                            "today": "TODAY",
                            "2": "WEEK",
                            "week": "WEEK",
                            "this week": "WEEK",
                            "3": "MONTH",
                            "month": "MONTH",
                            "this month": "MONTH",
                            "4": "YEAR",
                            "year": "YEAR",
                            "this year": "YEAR",
                            "5": None,
                            "all": None,
                            "all time": None,
                        }

                        if pending.action == "CUSTOMER_SUMMARY_MENU" and normalized in ["6", "date", "by date"]:
                            pending.action = "CUSTOMER_SUMMARY_DATE"
                            debug_db.commit()
                            send_whatsapp_message(
                                phone,
                                f"Send date for {pending.customer_name.title()} like:\n19/05/2026"
                            )
                            return {"status": "customer_summary_date_prompt"}

                        target_date = None
                        if pending.action == "CUSTOMER_SUMMARY_DATE":
                            target_date = parse_slash_date(normalized)
                            if not target_date:
                                send_whatsapp_message(
                                    phone,
                                    "Invalid date. Send date like:\n19/05/2026"
                                )
                                return {"status": "invalid_customer_summary_date"}
                            period = "DATE"
                        else:
                            if normalized not in period_map:
                                send_whatsapp_message(
                                    phone,
                                    "Choose an account view:\n"
                                    "1. Today\n"
                                    "2. This week\n"
                                    "3. This month\n"
                                    "4. This year\n"
                                    "5. All time\n"
                                    "6. By date\n\n"
                                    "You can also send another customer, like:\n"
                                    "Ade account\n\n"
                                    "Send exit, back, done, or cancel to close."
                                )
                                return {"status": "invalid_customer_summary_option"}
                            period = period_map[normalized]

                        msg = build_customer_account_summary(
                            debug_db,
                            business_owner_phone,
                            pending.customer_name,
                            period=period,
                            target_date=target_date,
                            include_menu=True,
                            recorded_by_id=early_visible_recorded_by_id
                        )
                        pending.action = "CUSTOMER_SUMMARY_MENU"
                        debug_db.commit()
                        send_whatsapp_message(phone, msg)
                        return {"status": "customer_summary_followup"}

                    account_request = parse_customer_account_request(text)
                    if account_request:
                        print("Customer account direct handler reached", flush=True)

                        business_owner_phone = sender_exists.phone
                        if sender_exists.parent_id:
                            owner = debug_db.query(User).filter(
                                User.id == sender_exists.parent_id
                            ).first()
                            if owner:
                                business_owner_phone = owner.phone

                        debug_db.query(PendingAction).filter(
                            PendingAction.phone == phone
                        ).delete()
                        debug_db.add(
                            PendingAction(
                                phone=phone,
                                customer_name=account_request["name"],
                                action="CUSTOMER_SUMMARY_MENU",
                                last_customer=account_request["name"]
                            )
                        )
                        debug_db.commit()

                        msg = build_customer_account_summary(
                            debug_db,
                            business_owner_phone,
                            account_request["name"],
                            period=account_request["period"],
                            target_date=account_request["target_date"],
                            include_menu=True,
                            recorded_by_id=early_visible_recorded_by_id
                        )
                        send_whatsapp_message(phone, msg)
                        return {"status": "customer_summary_menu"}

                    if text.lower().strip() == "due":
                        print("Due direct handler reached", flush=True)
                        allowed, upgrade_msg = ensure_feature_allowed(
                            debug_db,
                            sender_exists,
                            "DUE_REMINDERS",
                            "Debt reminders"
                        )
                        if not allowed:
                            send_whatsapp_message(phone, upgrade_msg)
                            return {"status": "due_menu_plan_blocked"}

                        try:
                            debug_db.query(PendingAction).filter(
                                PendingAction.phone == phone
                            ).delete()
                            debug_db.add(
                                PendingAction(
                                    phone=phone,
                                    customer_name="",
                                    action="DUE_MENU",
                                    last_customer=""
                                )
                            )
                            debug_db.commit()
                        except Exception as exc:
                            debug_db.rollback()
                            print("Due pending action failed:", repr(exc), flush=True)

                        send_whatsapp_message(
                            phone,
                            "Due Reminder Menu\n\n"
                            "1. Debts due in 2 days\n"
                            "2. Debts due today\n"
                            "3. Overdue debtors\n\n"
                            "Reply with 1, 2, or 3."
                        )
                        return {"status": "due_menu"}

                    if pending and pending.action == "DUE_MENU" and text.strip() in ["1", "2", "3"]:
                        print(f"Due menu selection reached: {text}", flush=True)

                        business_owner_phone = sender_exists.phone
                        if sender_exists.parent_id:
                            owner = debug_db.query(User).filter(
                                User.id == sender_exists.parent_id
                            ).first()
                            if owner:
                                business_owner_phone = owner.phone

                        debug_db.query(ReminderMemory).filter(
                            ReminderMemory.phone == phone
                        ).delete()
                        debug_db.delete(pending)

                        if text.strip() == "1":
                            due_list = get_due_in_2_days(debug_db, business_owner_phone, early_visible_recorded_by_id)
                            title = "Due in 2 Days"
                            empty_msg = "No debts due in 2 days."
                            reminder_type = "DUE_2_DAYS"
                        elif text.strip() == "2":
                            due_list = get_due_today(debug_db, business_owner_phone, early_visible_recorded_by_id)
                            title = "Due Today"
                            empty_msg = "No debts due today."
                            reminder_type = "DUE_TODAY"
                        else:
                            due_list = get_overdue_debtors(debug_db, business_owner_phone, early_visible_recorded_by_id)
                            title = "Overdue Debtors"
                            empty_msg = "No overdue debtors."
                            reminder_type = "OVERDUE"

                        if not due_list:
                            debug_db.commit()
                            send_whatsapp_message(phone, f"✅ {empty_msg}")
                            return {"status": "due_menu_empty"}

                        msg = f"{title}\n\n"
                        for i, debtor in enumerate(due_list, start=1):
                            memory = ReminderMemory(
                                phone=phone,
                                customer_id=debtor.get("customer_id"),
                                customer_name=debtor["name"],
                                customer_phone=debtor.get("customer_phone"),
                                balance=debtor["balance"],
                                due_date=debtor["due_date"],
                                reminder_type=reminder_type
                            )
                            debug_db.add(memory)

                            if text.strip() == "3":
                                due_date_text = debtor["due_date"].strftime("%d/%m/%Y")
                                msg += (
                                    f"{i}. {debtor['name']}\n"
                                    f"Balance: ₦{debtor['balance']:,}\n"
                                    f"Due: {due_date_text}\n"
                                    f"Overdue: {debtor.get('overdue_days', 0)} days\n\n"
                                )
                            else:
                                msg += f"{i}. {debtor['name']} → ₦{debtor['balance']:,}\n"

                        debug_db.add(
                            PendingAction(
                                phone=phone,
                                customer_name="",
                                action="REMINDER_SELECTION",
                                last_customer=""
                            )
                        )
                        debug_db.commit()

                        numbers = ", ".join(str(i) for i in range(1, len(due_list) + 1))
                        msg += f"\nSend:\n{numbers} to preview the reminder before sending to customer."
                        send_whatsapp_message(phone, msg)
                        return {"status": "due_menu_selection"}
                finally:
                    debug_db.close()
    except LookupError as exc:
        if str(exc) != "continue_to_onboarding":
            print("Webhook early parse lookup error:", repr(exc), flush=True)
    except Exception as exc:
        print("Webhook early parse error:", repr(exc), flush=True)

    data = await req.json()

    try:
        message = (
            data["entry"][0]
            ["changes"][0]
            ["value"]["messages"][0]
        )

        phone = message["from"]

        message_type = message.get("type", "text")
        text = (message.get("text") or {}).get("body", "").strip()
        message_id = message["id"]

    except:
        print("Webhook ignored before reply", flush=True)
        return {"status": "ignored"}

    db = SessionLocal()

    try:
        # 1. Global Idempotency Check (Prevents Meta Retries)
        already_processed = db.query(ProcessedMessage).filter(
            ProcessedMessage.message_id == message_id
        ).first()

        if already_processed:
            return {"status": "duplicate"}

        # Log this message ID immediately
        log_msg = ProcessedMessage(message_id=message_id)
        db.add(log_msg)
        try:
            db.commit()
        except:
            return {"status": "duplicate_race_condition"}

        # =========================
        # 🔍 USER & CONTEXT IDENTIFICATION
        # =========================
        user = db.query(User).filter(User.phone == phone).first()

        # Determine the "Business Owner Context"
        # This ensures delegates see the Admin's customers and data
        business_owner_phone = phone
        business_name = "your business"
        
        if user:
            if user.role in ["delegate", "delegate_pending"] and user.parent_id:
                admin = db.query(User).filter(User.id == user.parent_id).first()
                if admin:
                    business_owner_phone = admin.phone
                    business_name = admin.name
            else:
                business_name = user.name
        elif message_type in ["voice", "audio"]:
            send_whatsapp_message(
                phone,
                "Welcome to CreditVoice. Please register your business with a text message first, then you can use voice notes."
            )
            return {"status": "unregistered_voice"}

        voice_transcript_text = None

        # Parse early so unregistered app/subscription admins can use admin commands.
        parsed = parse_message(text) if message_type == "text" else None
        is_command = parsed and parsed["type"] != "TRANSACTION"
        admin_command_allowed = False
        app_admin_command_types = [
            "APP_ADMIN_DASHBOARD",
            "APP_ADMIN_USERS_BY_PLAN",
            "MANAGE_APP_ADMIN_ROLE",
            "LIST_APP_ADMIN_ROLES"
        ]
        subscription_admin_command_types = [
            "PENDING_SUBSCRIPTIONS",
            "APPROVE_SUBSCRIPTION",
            "REJECT_SUBSCRIPTION",
            "ACTIVATE_PLAN"
        ]
        admin_command_requested = bool(
            parsed and parsed["type"] in app_admin_command_types + subscription_admin_command_types
        )

        if not user and parsed:
            admin_command_allowed = (
                parsed["type"] in app_admin_command_types and is_app_admin(phone, db)
            ) or (
                parsed["type"] in subscription_admin_command_types and is_subscription_admin(phone, db)
            )
            if not admin_command_allowed and not admin_command_requested:
                parsed = None
                is_command = False

        # Logic for Pending Invitations
        if user and user.role == "delegate_pending":
            normalized = text.lower().strip()
            if normalized in ["1", "yes", "accept", "approve"]:
                user.role = "delegate"
                db.commit()
                send_whatsapp_message(
                    phone,
                    f"✅ Access Accepted!\n\nYou are now an authorized staff member for *{business_name.title()}*. You can start recording transactions immediately."
                )
                # Notify Admin
                send_whatsapp_message(
                    business_owner_phone,
                    f"📢 Notification: {user.name.title()} has ACCEPTED your staff invitation."
                )
                return {"status": "delegate_accepted"}
            elif normalized in ["2", "no", "decline", "reject"]:
                user.role = "user"
                user.parent_id = None
                user.can_view_all_transactions = False
                db.commit()
                send_whatsapp_message(
                    phone,
                    f"❌ Invitation Declined.\n\nYou are no longer associated with {business_name.title()}."
                )
                # Notify Admin
                send_whatsapp_message(
                    business_owner_phone,
                    f"📢 Notification: {user.name.title()} has DECLINED your staff invitation."
                )
                return {"status": "delegate_declined"}
            else:
                send_whatsapp_message(
                    phone,
                    f"Hello {user.name.title()}! *{business_name.title()}* has added you as a staff member.\n\n"
                    "Do you accept this invitation?\n\n1. Yes, Accept\n2. No, Decline"
                )
                return {"status": "delegate_invitation_pending"}

        # Use the business_owner_phone for all lookups instead of the raw sender 'phone'
        # From this point forward, use business_owner_phone for DB queries

        if message_type in ["voice", "audio"]:
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "VOICE_TEXT", "Voice notes")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "voice_plan_blocked"}

            transcribed_text, transcription_error = transcribe_whatsapp_voice(message)
            if transcription_error or not transcribed_text:
                send_whatsapp_message(
                    phone,
                    f"I could not understand that voice note. {transcription_error or ''}".strip()
                )
                return {"status": "voice_transcription_failed"}

            text = transcribed_text
            voice_transcript_text = transcribed_text
            message_type = "text"
            print(f"Voice transcript for {phone}: {text}", flush=True)

        # Parse message early to check if it's an explicit command
        if parsed is None:
            parsed = parse_message(text)
            is_command = parsed and parsed["type"] != "TRANSACTION"
        visible_recorded_by_id = visibility_recorded_by_id(user)
        subscription = get_business_subscription(db, user)

        if user and text.lower().strip() in ["hello", "hi", "hey", "titi", "start", "menu", "home", "help"]:
            if user.role == "delegate":
                db.query(PendingAction).filter(PendingAction.phone == phone).delete()
                db.add(PendingAction(phone=phone, action="STAFF_HOME_MENU"))
                db.commit()
                send_whatsapp_message(
                    phone,
                    build_staff_home_menu(
                        user,
                        business_name,
                        can_view_all_business_transactions(user)
                    )
                )
                return {"status": "delegate_home_menu"}
            if user.role == "user" and user.parent_id is None:
                db.query(PendingAction).filter(PendingAction.phone == phone).delete()
                db.add(PendingAction(phone=phone, action="OWNER_HOME_MENU"))
                db.commit()
                send_whatsapp_message(phone, build_owner_home_menu(user, subscription))
                return {"status": "owner_home_menu"}

        pending = db.query(PendingAction).filter(
            PendingAction.phone == phone,
            PendingAction.action != None
        ).order_by(
            PendingAction.created_at.desc()
        ).first()

        if (
            not user
            and pending
            and pending.action == "APP_ADMIN_DASHBOARD"
            and message_type == "text"
            and is_app_admin(phone, db)
        ):
            normalized = text.strip().lower()
            status, msg = build_app_admin_selection_message(db, normalized)
            if status == "app_admin_unknown":
                send_whatsapp_message(phone, msg)
                return {"status": "invalid_app_admin_dashboard_option"}

            db.delete(pending)
            db.commit()
            send_whatsapp_message(phone, msg)
            return {"status": status}

        if message_type != "text":
            if message_type in ["image", "document"] and pending and pending.action == "SUBSCRIPTION_PAYMENT_PENDING":
                payment = db.query(SubscriptionPayment).filter(
                    SubscriptionPayment.id == pending.reminder_id,
                    SubscriptionPayment.status == "PENDING"
                ).first()
                if payment:
                    owner = get_business_owner_user(db, user)
                    payment.evidence_type = message_type.upper()
                    payment.evidence_ref = get_media_evidence_ref(message, message_type)
                    db.commit()
                    notify_subscription_admins(
                        db,
                        payment,
                        owner,
                        send_whatsapp_message,
                        evidence_received=True
                    )
                    send_whatsapp_message(
                        phone,
                        "Receipt received. Your subscription request is waiting for admin confirmation."
                        f"{support_line()}"
                    )
                    return {"status": "subscription_receipt_received"}

            return {"status": "ignored_non_text"}

        evidence_text = bool(re.search(
            r"\b(receipt|ref|reference|transfer|payment|sent|paid)\b",
            text.lower()
        ))

        if pending and pending.action == "UPGRADE_MENU" and not is_command:
            normalized = text.lower().strip()
            if normalized in ["1", "go"]:
                pending.action = "UPGRADE_PLAN_SELECTED"
                pending.customer_name = PLAN_GO
                db.commit()
                send_whatsapp_message(phone, build_plan_payment_message(PLAN_GO))
                return {"status": "upgrade_go_selected"}

            if normalized in ["2", "pro"]:
                pending.action = "UPGRADE_PLAN_SELECTED"
                pending.customer_name = PLAN_PRO
                db.commit()
                send_whatsapp_message(phone, build_plan_payment_message(PLAN_PRO))
                return {"status": "upgrade_pro_selected"}

            if normalized in ["3", "my plan", "plan"]:
                send_whatsapp_message(phone, build_plan_message(subscription))
                return {"status": "upgrade_my_plan"}

            if normalized in ["4", "cancel", "exit", "back"]:
                db.delete(pending)
                if not user:
                    pending_business_name = pending.customer_name or business_name
                    db.add(
                        PendingAction(
                            phone=phone,
                            customer_name=pending_business_name,
                            action="POST_ONBOARDING_MENU",
                            last_customer=pending_business_name
                        )
                    )
                db.commit()
                send_whatsapp_message(phone, "Upgrade cancelled.")
                return {"status": "upgrade_cancelled"}

            send_whatsapp_message(phone, build_upgrade_message())
            return {"status": "upgrade_menu_waiting"}

        if pending and pending.action == "UPGRADE_PLAN_SELECTED" and not is_command:
            normalized = text.lower().strip()
            if normalized in ["cancel", "exit", "back", "stop"]:
                db.delete(pending)
                db.commit()
                send_whatsapp_message(phone, "Upgrade request closed.")
                return {"status": "upgrade_plan_cancelled"}

            if evidence_text or normalized in ["paid", "done", "i have paid", "i paid"]:
                plan = normalize_plan(pending.customer_name)
                payment = create_subscription_payment_request(db, user, plan)
                pending.action = "SUBSCRIPTION_PAYMENT_PENDING"
                pending.customer_name = plan
                pending.reminder_id = payment.id
                pending.last_customer = plan

                owner = get_business_owner_user(db, user)
                has_evidence = evidence_text and normalized not in ["paid", f"paid {plan.lower()}"]
                if has_evidence:
                    payment.evidence_type = "TEXT"
                    payment.evidence_ref = text[:500]

                db.commit()
                notify_subscription_admins(
                    db,
                    payment,
                    owner,
                    send_whatsapp_message,
                    evidence_received=has_evidence
                )

                if has_evidence:
                    send_whatsapp_message(
                        phone,
                        "Payment evidence received. Your subscription request is waiting for admin confirmation."
                        f"{support_line()}"
                    )
                    return {"status": "subscription_text_evidence_received"}

                send_whatsapp_message(
                    phone,
                    f"Thank you. Your {plan} subscription request has been received.\n\n"
                    "Please send your payment receipt screenshot or payment reference here. An admin will confirm and activate your plan."
                    f"{support_line()}"
                )
                return {"status": "subscription_payment_pending"}

            send_whatsapp_message(
                phone,
                "After payment, send PAID GO or PAID PRO.\n"
                "You can also send your receipt screenshot or payment reference here."
            )
            return {"status": "upgrade_plan_waiting_for_payment"}

        evidence_text = bool(re.search(
            r"\b(receipt|ref|reference|transfer|payment|sent|paid)\b",
            text.lower()
        ))
        if pending and pending.action == "SUBSCRIPTION_PAYMENT_PENDING" and not is_command and (not parsed or evidence_text):
            normalized = text.lower().strip()
            if normalized in ["cancel", "exit", "back", "stop"]:
                db.delete(pending)
                db.commit()
                send_whatsapp_message(phone, "Subscription payment request closed.")
                return {"status": "subscription_payment_cancelled"}

            payment = db.query(SubscriptionPayment).filter(
                SubscriptionPayment.id == pending.reminder_id,
                SubscriptionPayment.status == "PENDING"
            ).first()
            if payment:
                owner = get_business_owner_user(db, user)
                payment.evidence_type = "TEXT"
                payment.evidence_ref = text[:500]
                db.commit()
                notify_subscription_admins(
                    db,
                    payment,
                    owner,
                    send_whatsapp_message,
                    evidence_received=True
                )
                send_whatsapp_message(
                    phone,
                    "Payment evidence received. Your subscription request is waiting for admin confirmation."
                    f"{support_line()}"
                )
                return {"status": "subscription_text_evidence_received"}

        if pending and not is_command:
            post_onboarding_result = handle_post_onboarding_pending(
                db,
                phone,
                text,
                pending,
                user,
                business_name,
                send_whatsapp_message
            )
            if post_onboarding_result:
                return post_onboarding_result
        if pending and pending.action == "ARTISAN_PAYMENT_CHOICE" and not is_command:
            normalized = text.lower().strip()
            if normalized in ["1", "service", "work", "income", "new work"]:
                pending.action = "SALE"
                pending.buy_amount = pending.paid_amount
                pending.product = pending.product or f"service/work - {pending.customer_name}"
                pending.quantity = 1
                pending.unit_price = pending.buy_amount
                db.commit()
                send_whatsapp_message(
                    phone,
                    f"Confirm service income, no customer debt:\n"
                    f"{pending.product.title()} - N{pending.buy_amount:,}\n"
                    "Reply YES or 1 to save, EDIT or 2 to change."
                )
                return {"status": "artisan_service_confirm"}

            if normalized in ["2", "debt", "debit", "old debt", "existing debt"]:
                customer = db.query(Customer).filter(
                    Customer.name == pending.customer_name,
                    Customer.owner_phone == business_owner_phone
                ).first()
                if not customer:
                    customer = Customer(
                        name=pending.customer_name,
                        owner_phone=business_owner_phone
                    )
                    db.add(customer)
                    db.flush()

                pending.action = "PAY"
                pending.last_customer = customer.name
                db.commit()
                balance_after_line = build_projected_balance_line(
                    db,
                    customer.id,
                    {"buy_amount": 0, "paid_amount": pending.paid_amount},
                    visible_recorded_by_id
                )
                send_whatsapp_message(
                    phone,
                    f"Confirm debt payment:\n"
                    f"{customer.name.title()} paid N{pending.paid_amount:,}\n"
                    f"{balance_after_line}\n"
                    "Reply YES or 1 to save, EDIT or 2 to change."
                )
                return {"status": "artisan_debt_payment_confirm"}

            if normalized in ["edit", "change", "cancel", "back", "exit"]:
                db.delete(pending)
                db.commit()
                send_whatsapp_message(
                    phone,
                    "Enter again. Example:\nI received 1000 for doing chair\nor\nAde paid 7000"
                )
                return {"status": "artisan_choice_cancelled"}

            send_whatsapp_message(
                phone,
                f"{pending.customer_name.title()} paid you N{pending.paid_amount:,}.\n\n"
                "What is this for?\n"
                "1. For the work/service you did, no customer debt\n"
                "2. He/she paid debt owed to you"
            )
            return {"status": "artisan_choice_waiting"}

        if pending and not is_command:
            home_menu_result = handle_home_menu_pending(
                db,
                phone,
                text,
                pending,
                user,
                subscription,
                business_name,
                can_view_all_business_transactions(user),
                send_whatsapp_message
            )
            if home_menu_result:
                if home_menu_result.get("parsed"):
                    parsed = home_menu_result["parsed"]
                    is_command = True
                else:
                    return home_menu_result
        # =========================
        # 👤 USER ONBOARDING / PROFILE UPDATE (CONFIRMATION)
        if pending and not is_command:
            onboarding_result = handle_onboarding_pending(
                db,
                phone,
                text,
                pending,
                user,
                send_whatsapp_message
            )
            if onboarding_result:
                return onboarding_result

        if not user and not (admin_command_allowed or admin_command_requested):
            return start_onboarding(db, phone, pending, send_whatsapp_message)
        # Special Greeting for a Delegate's first time or on 'hello'
        if user and user.role == "delegate" and text.lower().strip() in ["hello", "hi", "titi"]:
            send_whatsapp_message(
                phone,
                f"Hello {user.name.title()}! 👋\n\n"
                f"You are logged in as a staff member for *{business_name.title()}*.\n\n"
                "You can record transactions or check balances for the business here."
            )
            return {"status": "delegate_greeted"}

        if pending and pending.action == "RESIGN_CONFIRM" and not is_command:
            normalized = text.strip()
            if normalized in ["1", "yes"]:
                # Save admin phone for notification before clearing association
                admin_notify_phone = business_owner_phone

                user.role = "user"
                user.parent_id = None
                user.can_view_all_transactions = False
                db.delete(pending)
                db.commit()
                send_whatsapp_message(
                    phone,
                    f"✅ You have successfully resigned. You no longer have access to {business_name.title()}'s data."
                )
                # Notify Admin
                if admin_notify_phone != phone:
                    send_whatsapp_message(
                        admin_notify_phone,
                        f"📢 Notification: {user.name.title()} has RESIGNED as your staff member."
                    )
                return {"status": "resigned_success"}
            
            if normalized in ["2", "no", "edit"]:
                db.delete(pending)
                db.commit()
                send_whatsapp_message(phone, "Resignation cancelled. You are still staff.")
                return {"status": "resigned_cancelled"}
            
            send_whatsapp_message(
                phone,
                f"Are you sure you want to stop working with *{business_name.title()}*?\n\n1. Yes, Confirm\n2. No, Cancel"
            )
            return {"status": "resigned_confirm_waiting"}

        if pending and pending.action == "ONBOARD_CUSTOMER" and not is_command:
            normalized = text.lower().strip()
            if normalized in ["yes", "1", "save"]:
                if pending.action == "SALE":
                    sale_saved_msg = pending_transaction_summary(pending)
                    recent_tx = db.query(Transaction).filter(
                        Transaction.type == "SALE",
                        Transaction.amount == pending.buy_amount,
                        Transaction.product == pending.product,
                        Transaction.recorded_by_id == user.id,
                        Transaction.created_at >= datetime.utcnow() - timedelta(minutes=2)
                    ).first()

                    if recent_tx:
                        send_whatsapp_message(
                            phone,
                            "A similar direct sale was already recorded just a moment ago."
                        )
                        db.delete(pending)
                        db.commit()
                        return {"status": "duplicate_sale_prevention"}

                    tx = Transaction(
                        customer_id=None,
                        type="SALE",
                        amount=pending.buy_amount,
                        product=pending.product,
                        quantity=pending.quantity,
                        unit=pending.unit,
                        unit_price=pending.unit_price,
                        recorded_by_id=user.id,
                        message_id=message_id,
                        created_at=datetime.utcnow()
                    )
                    db.add(tx)
                    db.delete(pending)
                    db.commit()

                    send_whatsapp_message(
                        phone,
                        f"✅ Direct sale saved.\n"
                        f"{pending.product.title()}: ₦{pending.buy_amount:,}"
                    )
                    return {"status": "direct_sale_saved"}

                customer = db.query(Customer).filter(
                    Customer.name == pending.customer_name,
                    Customer.owner_phone == business_owner_phone
                ).first()

                if not customer:
                    customer = Customer(
                        name=pending.customer_name,
                        owner_phone=business_owner_phone,
                        customer_phone=pending.customer_phone
                    )
                    db.add(customer)
                else:
                    if pending.customer_phone:
                        customer.customer_phone = pending.customer_phone

                db.delete(pending)
                db.commit()

                phone_status = customer.customer_phone or "no phone added"
                send_whatsapp_message(
                    phone,
                    f"Customer saved: {customer.name.title()} -> {phone_status}.\n"
                    "You can now record transactions for this customer."
                )
                return {"status": "customer_onboarded"}

            if normalized in ["edit", "2", "change"]:
                db.delete(pending)
                db.commit()

                send_whatsapp_message(
                    phone,
                    "Okay, please send the customer again like:\nJohn 08012345678"
                )
                return {"status": "customer_onboarded_edit"}

            send_whatsapp_message(
                phone,
                "I found a customer ready to save. Reply YES or 1 to confirm, EDIT or 2 to send it again."
            )
            return {"status": "customer_onboarded_confirm"}

        if pending and not is_command:
            if pending.action == "APP_ADMIN_DASHBOARD":
                normalized = text.strip().lower()
                status, msg = build_app_admin_selection_message(db, normalized)
                if status == "app_admin_unknown":
                    send_whatsapp_message(phone, msg)
                    return {"status": "invalid_app_admin_dashboard_option"}

                db.delete(pending)
                db.commit()
                send_whatsapp_message(phone, msg)
                return {"status": status}

            if pending.action == "DASHBOARD_MENU":
                normalized = text.strip().lower()
                dashboard_aliases = {
                    "today": "1",
                    "this week": "2",
                    "week": "2",
                    "this month": "3",
                    "month": "3",
                    "this year": "4",
                    "year": "4",
                    "all": "5",
                    "all time": "5",
                    "customers": "6",
                    "customer count": "6",
                    "customer list": "7",
                    "list customers": "7",
                    "debtors": "8",
                    "unpaid": "8",
                    "unpaid debtors": "8",
                    "products": "9",
                    "product leaderboard": "9"
                }
                selection = dashboard_aliases.get(normalized, normalized)
                status, msg = build_dashboard_selection_message(
                    db,
                    business_owner_phone,
                    selection,
                    visible_recorded_by_id
                )

                if not msg:
                    send_whatsapp_message(phone, build_dashboard_menu_message())
                    return {"status": "invalid_dashboard_menu_option"}

                db.delete(pending)
                db.commit()
                send_whatsapp_message(phone, msg)
                return {"status": status}

            reminder_pending_result = handle_reminder_pending(
                db,
                phone,
                text,
                pending,
                business_owner_phone,
                visible_recorded_by_id,
                send_whatsapp_message
            )
            if reminder_pending_result:
                return reminder_pending_result
            normalized = text.lower().strip()
            if normalized in ["yes", "1", "save"]:
                pending_items = json.loads(pending.items_json or "[]")
                save_result = save_confirmed_pending_transaction(
                    db,
                    phone,
                    pending,
                    user,
                    business_owner_phone,
                    visible_recorded_by_id,
                    message_id,
                    pending_items,
                    send_whatsapp_message
                )
                if save_result:
                    return save_result
            elif normalized == "3" and pending.source_text:
                db.delete(pending)
                db.commit()
                send_whatsapp_message(phone, "Send the voice note again.")
                return {"status": "voice_retry_requested"}

            elif normalized in ["edit", "2", "change"]:
                is_voice_edit = bool(pending.source_text)
                edit_msg = edit_prompt_for_pending(pending)
                db.delete(pending)
                db.commit()
                send_whatsapp_message(phone, edit_msg)
                return {"status": "voice_text_edit" if is_voice_edit else "edit"}

        if not parsed:
            # Ignore simple pleasantries or short messages from registered users
            # so we do not spam them with "Message not understood"
            pleasantries = ["thanks", "thank you", "ok", "okay", "done", "bye", "good", "nice", "??"]
            if text.lower().strip() in pleasantries or len(text) < 2:
                return {"status": "ignored_pleasantry"}

            fallback = interpret_text_with_openai(text)
            if fallback:
                normalized_text = (fallback.get("normalized_text") or "").strip()
                clarification = (fallback.get("clarification_question") or "").strip()
                if fallback.get("understood") and normalized_text:
                    fallback_parsed = parse_message(normalized_text)
                    if fallback_parsed:
                        parsed = fallback_parsed
                        text = normalized_text
                        is_command = parsed and parsed["type"] != "TRANSACTION"
                        print(f"OpenAI parser fallback normalized to: {normalized_text}", flush=True)
                    elif clarification:
                        send_whatsapp_message(phone, clarification)
                        return {"status": "openai_parser_clarification"}
                elif clarification:
                    send_whatsapp_message(phone, clarification)
                    return {"status": "openai_parser_clarification"}

            if not parsed:
                send_whatsapp_message(phone, build_invalid_message(user))
                return {"status": "invalid"}
        if parsed["type"] == "FORMATS":
            msg = build_supported_formats_message(user)
            send_whatsapp_message(phone, msg)
            return {"status": "formats"}

        supplier_result = handle_supplier_command(
            db,
            phone,
            parsed,
            user,
            business_owner_phone,
            voice_transcript_text,
            send_whatsapp_message
        )
        if supplier_result:
            return supplier_result
        if parsed["type"] == "ARTISAN_PAYMENT_CHOICE":
            db.query(PendingAction).filter(
                PendingAction.phone == phone
            ).delete()
            db.add(
                PendingAction(
                    phone=phone,
                    customer_name=parsed["name"].lower(),
                    action="ARTISAN_PAYMENT_CHOICE",
                    paid_amount=parsed["amount"],
                    product=f"{parsed.get('description', 'service/work')} - {parsed['name'].lower()}",
                    last_customer=parsed["name"].lower()
                )
            )
            db.commit()
            send_whatsapp_message(
                phone,
                f"{parsed['name'].title()} paid you N{parsed['amount']:,}.\n\n"
                "What is this for?\n"
                "1. For the work/service you did, no customer debt\n"
                "2. He/she paid debt owed to you"
            )
            return {"status": "artisan_payment_choice"}

        if parsed["type"] == "MY_PLAN":
            send_whatsapp_message(phone, build_plan_message(subscription))
            return {"status": "my_plan"}

        if parsed["type"] == "UPGRADE_MENU":
            db.query(PendingAction).filter(
                PendingAction.phone == phone
            ).delete()
            db.add(
                PendingAction(
                    phone=phone,
                    customer_name="",
                    action="UPGRADE_MENU",
                    last_customer=""
                )
            )
            db.commit()
            send_whatsapp_message(phone, build_upgrade_message())
            return {"status": "upgrade_menu"}

        admin_subscription_result = handle_admin_subscription_command(
            db,
            phone,
            parsed,
            user,
            send_whatsapp_message,
            notify_subscription_admins
        )
        if admin_subscription_result:
            return admin_subscription_result

        staff_result = handle_staff_command(
            db,
            phone,
            parsed,
            user,
            subscription,
            business_name,
            send_whatsapp_message
        )
        if staff_result:
            return staff_result

        profile_result = handle_profile_command(
            db,
            phone,
            parsed,
            pending,
            business_owner_phone,
            send_whatsapp_message
        )
        if profile_result:
            return profile_result
        reminder_result = handle_reminder_command(
            db,
            phone,
            parsed,
            user,
            send_whatsapp_message
        )
        if reminder_result:
            return reminder_result
        report_result = handle_report_command(
            db,
            phone,
            text,
            parsed,
            user,
            business_owner_phone,
            visible_recorded_by_id,
            send_whatsapp_message
        )
        if report_result:
            return report_result
        customer_result = handle_customer_command(
            db,
            phone,
            text,
            parsed,
            user,
            business_owner_phone,
            visible_recorded_by_id,
            send_whatsapp_message
        )
        if customer_result:
            return customer_result
        transaction_setup_result = handle_transaction_setup(
            db,
            phone,
            parsed,
            user,
            business_owner_phone,
            subscription,
            visible_recorded_by_id,
            voice_transcript_text,
            send_whatsapp_message
        )
        if transaction_setup_result:
            return transaction_setup_result
    finally:
        db.close()


