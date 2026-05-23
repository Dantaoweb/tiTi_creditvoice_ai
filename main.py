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
    func,
    inspect,
    text
)

from admin import (
    build_app_admin_dashboard_message,
    build_app_admin_selection_message,
    format_admin_roles,
    format_pending_subscriptions,
    format_user_list,
)
from database import Base, SessionLocal, engine
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

from business_templates import (
    build_business_category_menu,
    build_business_type_menu,
    business_category_by_key,
    make_custom_business_key,
    selected_business_category,
    selected_business_type,
)
from inventory_suppliers import (
    add_inventory_movement,
    build_inventory_list_message,
    build_supplier_due_message,
    build_supplier_list_message,
    deduct_inventory_for_items,
    find_or_create_supplier,
    get_supplier_balance,
)
from messages import (
    apply_voice_confirmation_options,
    balance_status_line,
    build_invalid_message,
    build_onboarding_start_message,
    build_owner_home_menu,
    build_plan_message,
    build_plan_payment_message,
    build_post_onboarding_menu,
    build_staff_home_menu,
    build_supported_formats_message,
    build_upgrade_message,
    edit_prompt_for_pending,
    pending_transaction_summary,
)
from parser import (
    add_transaction_items,
    build_customer_account_summary,
    build_reminder_text,
    format_invoice_items,
    interpret_text_with_openai,
    normalize_phone,
    parse_customer_account_request,
    parse_message,
    parse_slash_date,
    transcribe_whatsapp_voice,
)
from plans import (
    PLAN_BASIC,
    PLAN_GO,
    PLAN_PRO,
    normalize_plan,
)
from reports import (
    build_dashboard_menu_message,
    build_dashboard_selection_message,
    build_dashboard_summary_message,
    format_transaction_note_thread,
    get_balance,
    get_biggest_debtor,
    get_customer_count,
    get_customer_summary,
    get_debtor_leaderboard,
    get_due_in_2_days,
    get_due_today,
    get_monthly_sales,
    get_most_sold_product,
    get_new_customer_count,
    get_outstanding_balance,
    get_overdue_debtors,
    get_owner_transaction_query,
    get_paid_customer_count,
    get_product_sales_by_date,
    get_product_sales_by_period,
    get_today_sales,
    get_transaction_notes,
    get_transaction_stats,
    get_unpaid_debtors,
    get_visible_transaction,
    get_weekly_sales,
    get_yearly_sales,
    list_customers,
    search_customers,
    get_dashboard_summary,
)
from subscriptions import (
    approve_subscription_payment,
    check_customer_limit,
    check_staff_limit,
    create_subscription_payment_request,
    ensure_feature_allowed,
    get_business_owner_user,
    get_business_subscription,
    get_business_users_by_effective_plan,
    get_month_start,
)

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


def check_monthly_transaction_limit(db, owner_phone, subscription, planned_rows=1):
    limit = subscription["limits"].get("monthly_transactions")
    if limit is None:
        return True, None

    current_count = get_owner_transaction_query(
        db,
        owner_phone
    ).filter(
        Transaction.created_at >= get_month_start()
    ).count()
    if current_count + planned_rows <= limit:
        return True, None

    return False, (
        f"Basic plan monthly transaction limit reached ({limit}).\n\n"
        "Send UPGRADE to move to Go for unlimited transactions."
    )


def get_media_evidence_ref(message, message_type):
    payload = message.get(message_type) or {}
    return payload.get("id") or message.get("id")


def phone_list_from_env(name):
    return [
        normalize_phone(value.strip())
        for value in os.getenv(name, "").split(",")
        if value.strip()
    ]


def customer_support_phone():
    phone = os.getenv("CUSTOMER_SUPPORT_PHONE", "").strip()
    return normalize_phone(phone) if phone else None


def support_line():
    phone = customer_support_phone()
    return f"\n\nNeed help? Contact support: {phone}" if phone else ""


def subscription_admin_phones():
    return phone_list_from_env("SUBSCRIPTION_ADMIN_PHONES")


def app_admin_phones():
    return phone_list_from_env("APP_ADMIN_PHONES")


ROLE_CUSTOMER_SUPPORT = "CUSTOMER_SUPPORT"
ROLE_SUBSCRIPTION_ADMIN = "SUBSCRIPTION_ADMIN"
ROLE_APP_ADMIN = "APP_ADMIN"


def normalize_admin_role(role):
    role = (role or "").upper().replace(" ", "_").strip()
    aliases = {
        "SUPPORT": ROLE_CUSTOMER_SUPPORT,
        "CUSTOMER_SUPPORT": ROLE_CUSTOMER_SUPPORT,
        "SUBSCRIPTION": ROLE_SUBSCRIPTION_ADMIN,
        "SUBSCRIPTION_ADMIN": ROLE_SUBSCRIPTION_ADMIN,
        "APP": ROLE_APP_ADMIN,
        "APP_ADMIN": ROLE_APP_ADMIN
    }
    return aliases.get(role)


def get_admin_role_override(db, phone, role):
    return db.query(AppAdminRole).filter(
        AppAdminRole.phone == normalize_phone(phone),
        AppAdminRole.role == role
    ).order_by(
        AppAdminRole.created_at.desc()
    ).first()


def role_is_denied(db, phone, role):
    override = get_admin_role_override(db, phone, role)
    return bool(override and not override.is_active)


def has_db_admin_role(db, phone, role):
    override = get_admin_role_override(db, phone, role)
    return bool(override and override.is_active)


def has_admin_role(db, phone, role):
    phone = normalize_phone(phone)
    if role == ROLE_APP_ADMIN:
        if role_is_denied(db, phone, ROLE_APP_ADMIN):
            return False
        return phone in app_admin_phones() or has_db_admin_role(db, phone, ROLE_APP_ADMIN)

    if role == ROLE_SUBSCRIPTION_ADMIN:
        if role_is_denied(db, phone, ROLE_SUBSCRIPTION_ADMIN):
            return False
        return (
            has_admin_role(db, phone, ROLE_APP_ADMIN)
            or phone in subscription_admin_phones()
            or has_db_admin_role(db, phone, ROLE_SUBSCRIPTION_ADMIN)
        )

    if role == ROLE_CUSTOMER_SUPPORT:
        if role_is_denied(db, phone, ROLE_CUSTOMER_SUPPORT):
            return False
        return (
            has_admin_role(db, phone, ROLE_APP_ADMIN)
            or has_admin_role(db, phone, ROLE_SUBSCRIPTION_ADMIN)
            or phone == customer_support_phone()
            or has_db_admin_role(db, phone, ROLE_CUSTOMER_SUPPORT)
        )

    return False


def set_admin_role(db, target_phone, role, is_active, actor_user=None):
    target_phone = normalize_phone(target_phone)
    role = normalize_admin_role(role)
    override = get_admin_role_override(db, target_phone, role)

    if not override:
        override = AppAdminRole(
            phone=target_phone,
            role=role,
            is_active=is_active,
            created_by_user_id=actor_user.id if actor_user else None
        )
        db.add(override)
    else:
        override.is_active = is_active

    if is_active:
        override.deactivated_at = None
        override.deactivated_by_user_id = None
    else:
        override.deactivated_at = datetime.utcnow()
        override.deactivated_by_user_id = actor_user.id if actor_user else None

    return override


def is_subscription_admin(phone, db=None):
    if db is None:
        return normalize_phone(phone) in subscription_admin_phones()
    return has_admin_role(db, phone, ROLE_SUBSCRIPTION_ADMIN)


def is_app_admin(phone, db=None):
    if db is None:
        return normalize_phone(phone) in app_admin_phones()
    return has_admin_role(db, phone, ROLE_APP_ADMIN)


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
                    notify_subscription_admins(db, payment, owner, evidence_received=True)
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
                notify_subscription_admins(db, payment, owner, evidence_received=has_evidence)

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
                notify_subscription_admins(db, payment, owner, evidence_received=True)
                send_whatsapp_message(
                    phone,
                    "Payment evidence received. Your subscription request is waiting for admin confirmation."
                    f"{support_line()}"
                )
                return {"status": "subscription_text_evidence_received"}

        if pending and pending.action == "POST_ONBOARDING_MENU" and not is_command:
            normalized = text.lower().strip()
            if normalized in ["1", "formats", "format", "f"]:
                db.delete(pending)
                db.commit()
                send_whatsapp_message(phone, build_supported_formats_message(user))
                return {"status": "post_onboarding_formats"}

            if normalized in ["2", "add customer", "customer"]:
                send_whatsapp_message(
                    phone,
                    "To add a customer, send their name and phone number like:\n"
                    "John 08012345678\n\n"
                    "You can also save only the name:\n"
                    "add customer John"
                )
                return {"status": "post_onboarding_add_customer"}

            if normalized in ["3", "dashboard"]:
                pending.action = "DASHBOARD_MENU"
                db.commit()
                send_whatsapp_message(phone, build_dashboard_menu_message())
                return {"status": "post_onboarding_dashboard"}

            if normalized in ["4", "upgrade"]:
                pending.action = "UPGRADE_MENU"
                db.commit()
                send_whatsapp_message(phone, build_upgrade_message())
                return {"status": "post_onboarding_upgrade"}

            if normalized in ["cancel", "exit", "back", "done", "stop"]:
                db.delete(pending)
                db.commit()
                send_whatsapp_message(phone, "Closed. You can continue anytime.")
                return {"status": "post_onboarding_closed"}

            send_whatsapp_message(phone, build_post_onboarding_menu(pending.customer_name or business_name, user))
            return {"status": "post_onboarding_waiting"}

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

        if pending and pending.action == "OWNER_HOME_MENU" and not is_command:
            normalized = text.lower().strip()
            if normalized in ["1", "record", "record transaction", "transaction"]:
                db.delete(pending)
                db.commit()
                send_whatsapp_message(
                    phone,
                    "Send a transaction like:\nAde bought rice 5000\nAde paid 3000"
                )
                return {"status": "owner_home_record_help"}
            if normalized in ["2", "add customer", "customer"]:
                db.delete(pending)
                db.commit()
                send_whatsapp_message(
                    phone,
                    "To add a customer, send their name and phone number like:\nJohn 08012345678\n\nYou can also send:\nadd customer John"
                )
                return {"status": "owner_home_add_customer"}
            if normalized in ["3", "dashboard"]:
                pending.action = "DASHBOARD_MENU"
                db.commit()
                send_whatsapp_message(phone, build_dashboard_menu_message())
                return {"status": "owner_home_dashboard"}
            if normalized in ["4", "upgrade", "my plan", "plan"]:
                pending.action = "UPGRADE_MENU"
                db.commit()
                send_whatsapp_message(phone, build_upgrade_message())
                return {"status": "owner_home_upgrade"}
            if normalized in ["5", "staff", "staff menu"] and subscription["plan"] == PLAN_PRO:
                db.delete(pending)
                db.commit()
                parsed = {"type": "STAFF_MENU"}
                is_command = True
            elif normalized in ["5", "6", "formats", "help", "format"]:
                db.delete(pending)
                db.commit()
                parsed = {"type": "FORMATS"}
                is_command = True
            elif normalized in ["cancel", "exit", "back", "done", "stop"]:
                db.delete(pending)
                db.commit()
                send_whatsapp_message(phone, "Closed. You can continue anytime.")
                return {"status": "owner_home_closed"}
            else:
                send_whatsapp_message(phone, build_owner_home_menu(user, subscription))
                return {"status": "owner_home_waiting"}

        if pending and pending.action == "STAFF_HOME_MENU" and not is_command:
            normalized = text.lower().strip()
            if normalized in ["1", "record", "record transaction", "transaction"]:
                db.delete(pending)
                db.commit()
                send_whatsapp_message(
                    phone,
                    "Send a transaction like:\nAde bought rice 5000\nAde paid 3000"
                )
                return {"status": "staff_home_record_help"}
            if normalized in ["2", "customers", "customer list", "list customers"]:
                db.delete(pending)
                db.commit()
                parsed = {"type": "CUSTOMER_LIST", "period": None}
                is_command = True
            elif normalized in ["3", "dashboard"]:
                pending.action = "DASHBOARD_MENU"
                db.commit()
                send_whatsapp_message(phone, build_dashboard_menu_message())
                return {"status": "staff_home_dashboard"}
            elif normalized in ["4", "resign"]:
                db.delete(pending)
                db.commit()
                parsed = {"type": "RESIGN_REQUEST"}
                is_command = True
            elif normalized in ["cancel", "exit", "back", "done", "stop"]:
                db.delete(pending)
                db.commit()
                send_whatsapp_message(phone, "Closed. You can continue anytime.")
                return {"status": "staff_home_closed"}
            else:
                send_whatsapp_message(
                    phone,
                    build_staff_home_menu(
                        user,
                        business_name,
                        can_view_all_business_transactions(user)
                    )
                )
                return {"status": "staff_home_waiting"}

        # =========================
        # 👤 USER ONBOARDING / PROFILE UPDATE (CONFIRMATION)
        # =========================

        if pending and pending.action == "ONBOARD_USER" and not is_command:
            full_name = text.strip()
            if full_name == "" or full_name.lower() in ["continue", "start", "yes", "ok", "1"]:
                send_whatsapp_message(
                    phone,
                    "Please reply with the name you want to use."
                )
                return {"status": "onboarding_name_required"}

            # Save name temporarily in pending and move to confirmation step
            pending.action = "ONBOARD_USER_CONFIRM"
            pending.customer_name = full_name  # Reuse field for temporary storage
            db.commit()

            send_whatsapp_message(
                phone,
                f"Confirm name: *{full_name.title()}*?\n\n"
                "Reply YES or 1 to save, EDIT or 2 to change."
            )
            return {"status": "onboarding_confirm_sent"}

        if pending and pending.action == "ONBOARD_USER_CONFIRM" and not is_command:
            normalized = text.lower().strip()
            if normalized in ["yes", "1", "save"]:
                pending.action = "ONBOARD_USER_CATEGORY"
                db.commit()
                send_whatsapp_message(phone, build_business_category_menu())
                return {"status": "onboarding_category_prompt"}

            if normalized in ["edit", "2", "change"]:
                pending.action = "ONBOARD_USER"
                db.commit()
                send_whatsapp_message(
                    phone,
                    "No problem! Please reply with the name you want to use."
                )
                return {"status": "onboarding_restart"}

            send_whatsapp_message(
                phone,
                f"Confirm name: *{pending.customer_name}*?\n\n"
                "Reply YES or 1 to save, EDIT or 2 to change."
            )
            return {"status": "waiting_onboarding_confirmation"}

        if pending and pending.action == "ONBOARD_USER_CATEGORY" and not is_command:
            category = selected_business_category(text)
            if not category:
                send_whatsapp_message(phone, build_business_category_menu())
                return {"status": "onboarding_invalid_category"}

            pending.last_customer = category["key"]
            if category["key"] == "other":
                pending.action = "ONBOARD_USER_CUSTOM_TYPE"
                db.commit()
                send_whatsapp_message(
                    phone,
                    "Please type your business type.\nExample: Event Decoration"
                )
                return {"status": "onboarding_custom_type_prompt"}

            pending.action = "ONBOARD_USER_BUSINESS_TYPE"
            db.commit()
            send_whatsapp_message(phone, build_business_type_menu(category))
            return {"status": "onboarding_business_type_prompt"}

        if pending and pending.action == "ONBOARD_USER_BUSINESS_TYPE" and not is_command:
            category = business_category_by_key(pending.last_customer)
            if not category:
                pending.action = "ONBOARD_USER_CATEGORY"
                db.commit()
                send_whatsapp_message(phone, build_business_category_menu())
                return {"status": "onboarding_category_missing"}

            business_type_key, business_type_label = selected_business_type(category, text)
            if not business_type_key:
                send_whatsapp_message(phone, build_business_type_menu(category))
                return {"status": "onboarding_invalid_business_type"}

            if business_type_key.startswith("other_"):
                pending.action = "ONBOARD_USER_CUSTOM_TYPE"
                db.commit()
                send_whatsapp_message(
                    phone,
                    "Please type your business type.\nExample: Event Decoration"
                )
                return {"status": "onboarding_custom_type_prompt"}

            user, msg = complete_user_onboarding(
                db,
                user,
                phone,
                pending,
                category["key"],
                business_type_key,
                business_type_label
            )
            send_whatsapp_message(phone, msg)
            return {"status": "user_saved"}

        if pending and pending.action == "ONBOARD_USER_CUSTOM_TYPE" and not is_command:
            custom_label = text.strip()
            if custom_label == "" or custom_label.lower() in ["continue", "start", "yes", "ok", "1"]:
                send_whatsapp_message(
                    phone,
                    "Please type your business type.\nExample: Event Decoration"
                )
                return {"status": "onboarding_custom_type_required"}

            user, msg = complete_user_onboarding(
                db,
                user,
                phone,
                pending,
                pending.last_customer or "other",
                make_custom_business_key(custom_label),
                custom_label.title()
            )
            send_whatsapp_message(phone, msg)
            return {"status": "user_saved_custom_type"}

        if not user and not (admin_command_allowed or admin_command_requested):

            onboarding_actions = [
                "ONBOARD_USER",
                "ONBOARD_USER_CONFIRM",
                "ONBOARD_USER_CATEGORY",
                "ONBOARD_USER_BUSINESS_TYPE",
                "ONBOARD_USER_CUSTOM_TYPE"
            ]

            if pending and pending.action not in onboarding_actions:
                db.delete(pending)
                db.commit()

            if not pending or pending.action not in onboarding_actions:
                onboarding = PendingAction(
                    phone=phone,
                    action="ONBOARD_USER"
                )
                db.add(onboarding)
                db.commit()

            send_whatsapp_message(
                phone,
                build_onboarding_start_message()
            )
            return {"status": "onboarding_started"}

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

            if pending.action == "DUE_MENU":
                # Handle DUE_MENU responses (1, 2, 3)
                if text == "1":
                    # Due in 2 days logic
                    due_list = get_due_in_2_days(db, business_owner_phone, visible_recorded_by_id)
                    db.query(ReminderMemory).filter(
                        ReminderMemory.phone == phone
                    ).delete()
                    db.commit()

                    if len(due_list) == 0:
                        send_whatsapp_message(
                            phone,
                            "✅ No debts due in 2 days."
                        )
                    else:
                        msg = "📅 Due in 2 Days\n\n"
                        for i, debtor in enumerate(due_list, start=1):
                            memory = ReminderMemory(
                                phone=phone,
                                customer_id=debtor["customer_id"],
                                customer_name=debtor["name"],
                                customer_phone=debtor.get("customer_phone"),
                                balance=debtor["balance"],
                                due_date=debtor["due_date"],
                                reminder_type="DUE_2_DAYS"
                            )
                            db.add(memory)
                            msg += f"{i}. {debtor['name']} → ₦{debtor['balance']:,}\n"
                        db.commit()
                        reminder_pending = PendingAction(
                            phone=phone,
                            action="REMINDER_SELECTION"
                        )
                        db.add(reminder_pending)
                        db.commit()
                        numbers = ", ".join(str(i) for i in range(1, len(due_list) + 1))
                        msg += f"\nSend:\n{numbers} to preview the reminder before sending to customer."
                        send_whatsapp_message(phone, msg)

                    db.delete(pending)
                    db.commit()
                    return {"status": "due_2_days"}

                elif text == "2":
                    # Due today logic
                    due_today = get_due_today(db, business_owner_phone, visible_recorded_by_id)
                    db.query(ReminderMemory).filter(
                        ReminderMemory.phone == phone
                    ).delete()
                    db.commit()

                    if len(due_today) == 0:
                        send_whatsapp_message(
                            phone,
                            "✅ No debts due today."
                        )
                    else:
                        msg = "📅 Due Today\n\n"
                        for i, debtor in enumerate(due_today, start=1):
                            memory = ReminderMemory(
                                phone=phone,
                                customer_id=debtor["customer_id"],
                                customer_name=debtor["name"],
                                customer_phone=debtor.get("customer_phone"),
                                balance=debtor["balance"],
                                due_date=debtor["due_date"],
                                reminder_type="DUE_TODAY"
                            )
                            db.add(memory)
                            msg += f"{i}. {debtor['name']} → ₦{debtor['balance']:,}\n"
                        db.commit()
                        reminder_pending = PendingAction(
                            phone=phone,
                            action="REMINDER_SELECTION"
                        )
                        db.add(reminder_pending)
                        db.commit()
                        numbers = ", ".join(str(i) for i in range(1, len(due_today) + 1))
                        msg += f"\nSend:\n{numbers} to preview the reminder before sending to customer."
                        send_whatsapp_message(phone, msg)

                    db.delete(pending)
                    db.commit()
                    return {"status": "due_today"}

                elif text == "3":
                    # Overdue logic
                    db.query(ReminderMemory).filter(
                        ReminderMemory.phone == phone
                    ).delete()
                    db.commit()

                    overdue_list = get_overdue_debtors(db, business_owner_phone, visible_recorded_by_id)
                    if len(overdue_list) == 0:
                        send_whatsapp_message(
                            phone,
                            "✅ No overdue debtors."
                        )
                    else:
                        msg = "⚠️ Overdue Debtors\n\n"
                        for i, debtor in enumerate(overdue_list, start=1):
                            memory = ReminderMemory(
                                phone=phone,
                                customer_id=debtor["customer_id"],
                                customer_name=debtor["name"],
                                customer_phone=debtor.get("customer_phone"),
                                balance=debtor["balance"],
                                due_date=debtor["due_date"],
                                reminder_type="OVERDUE"
                            )
                            db.add(memory)
                            due_date_text = debtor["due_date"].strftime("%d/%m/%Y")
                            msg += (
                                f"{i}. {debtor['name']}\n"
                                f"Balance: ₦{debtor['balance']:,}\n"
                                f"Due: {due_date_text}\n"
                                f"Overdue: {debtor['overdue_days']} days\n\n"
                            )
                        db.commit()
                        reminder_pending = PendingAction(
                            phone=phone,
                            action="REMINDER_SELECTION"
                        )
                        db.add(reminder_pending)
                        db.commit()
                        numbers = ", ".join(str(i) for i in range(1, len(overdue_list) + 1))
                        msg += f"\nSend:\n{numbers} to preview the reminder before sending to customer."
                        send_whatsapp_message(phone, msg)

                    db.delete(pending)
                    db.commit()
                    return {"status": "overdue_menu"}

            elif pending.action == "REMINDER_SELECTION":
                if not text.isdigit():
                    send_whatsapp_message(
                        phone,
                        "Reply with reminder number.\nExample: 1"
                    )
                    return {"status": "invalid_reminder_selection"}

                index = int(text)
                reminders = db.query(ReminderMemory).filter(
                    ReminderMemory.phone == phone
                ).all()

                if index < 1 or index > len(reminders):
                    send_whatsapp_message(
                        phone,
                        "Reminder number not found."
                    )
                    return {"status": "reminder_not_found"}

                reminder = reminders[index - 1]
                
                # Show preview regardless of phone being set
                preview = build_reminder_text(reminder)
                
                # Build confirmation message based on whether phone is set
                if reminder.customer_phone:
                    confirm_msg = (
                        f"Preview reminder for {reminder.customer_name.title()}:\n\n"
                        f"{preview}\n\n"
                        f"Reply YES to send this reminder to {reminder.customer_name.title()} "
                        f"at {reminder.customer_phone}, or EDIT to cancel."
                    )
                else:
                    confirm_msg = (
                        f"Preview reminder for {reminder.customer_name.title()}:\n\n"
                        f"{preview}\n\n"
                        "Customer phone is not set yet.\n"
                        "To send this reminder, set the phone first:\n\n"
                        f"{reminder.customer_name} phone 08012345678\n\n"
                        "I will keep this reminder open. After setting the phone, reply YES to send."
                    )

                pending.action = "REMINDER_CONFIRM"
                pending.reminder_id = reminder.id
                db.commit()
                send_whatsapp_message(phone, confirm_msg)
                return {"status": "reminder_preview"}

            elif pending.action == "REMINDER_CONFIRM":
                if text.lower() == "yes":
                    reminder = db.query(ReminderMemory).filter(
                        ReminderMemory.id == pending.reminder_id
                    ).first()

                    if not reminder:
                        send_whatsapp_message(
                            phone,
                            "Reminder not found. Please select again."
                        )
                        db.delete(pending)
                        db.commit()
                        return {"status": "reminder_missing"}

                    if not reminder.customer_phone:
                        # Instead of failing, prompt user to set phone first
                        send_whatsapp_message(
                            phone,
                            f"Customer phone is not set for {reminder.customer_name.title()}.\n\n"
                            "Set it using:\n"
                            f"{reminder.customer_name} phone 08012345678\n\n"
                            "I will keep this reminder open. After setting the phone, reply YES again."
                        )
                        # Keep the pending action so they can retry after setting phone
                        return {"status": "waiting_for_phone"}

                    reminder_text = build_reminder_text(reminder)
                    send_whatsapp_message(reminder.customer_phone, reminder_text)
                    send_whatsapp_message(
                        phone,
                        f"✅ Reminder sent to {reminder.customer_name.title()} ({reminder.customer_phone})."
                    )
                    db.delete(pending)
                    db.commit()
                    return {"status": "reminder_sent"}

                if text.lower() == "edit":
                    db.delete(pending)
                    db.commit()
                    send_whatsapp_message(
                        phone,
                        "Reminder cancelled. Reply DUE to start again."
                    )
                    return {"status": "reminder_cancelled"}

                send_whatsapp_message(
                    phone,
                    "Reply YES to send the reminder to the customer or EDIT to cancel."
                )
                return {"status": "reminder_confirm_prompt"}

            normalized = text.lower().strip()
            if normalized in ["yes", "1", "save"]:
                pending_items = json.loads(pending.items_json or "[]")

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
                    db.flush()
                    if pending_items:
                        add_transaction_items(db, tx.id, pending_items)
                        stock_updates, stock_missing = deduct_inventory_for_items(
                            db,
                            business_owner_phone,
                            pending_items,
                            "SALE",
                            tx.id,
                            user.id
                        )
                    elif pending.product:
                        fallback_items = [{
                            "product": pending.product,
                            "quantity": pending.quantity or 1,
                            "unit": pending.unit,
                            "unit_price": pending.unit_price or pending.buy_amount,
                            "total": pending.buy_amount
                        }]
                        add_transaction_items(db, tx.id, fallback_items)
                        stock_updates, stock_missing = deduct_inventory_for_items(
                            db,
                            business_owner_phone,
                            fallback_items,
                            "SALE",
                            tx.id,
                            user.id
                        )
                    else:
                        stock_updates, stock_missing = [], []

                    db.delete(pending)
                    db.commit()

                    stock_msg = ""
                    if stock_updates:
                        stock_msg = "\n\nStock updated:\n" + "\n".join(stock_updates)
                    elif stock_missing:
                        stock_msg = "\n\nSale saved. Stock item not found yet. Send STOCK to check inventory."
                    send_whatsapp_message(phone, f"{sale_saved_msg}{stock_msg}")
                    return {"status": "direct_sale_saved"}

                if pending.action in ["SUPPLIER_PURCHASE", "SUPPLIER_PAYMENT"]:
                    supplier = find_or_create_supplier(db, business_owner_phone, pending.customer_name)
                    saved_summary = pending_transaction_summary(pending)

                    if pending.action == "SUPPLIER_PURCHASE":
                        purchase = SupplierPurchase(
                            supplier_id=supplier.id,
                            owner_phone=business_owner_phone,
                            product=pending.product,
                            quantity=pending.quantity,
                            unit=pending.unit,
                            unit_price=pending.unit_price,
                            total=pending.buy_amount,
                            paid_amount=pending.paid_amount,
                            due_date=pending.due_date,
                            recorded_by_id=user.id,
                            created_at=datetime.utcnow()
                        )
                        db.add(purchase)
                        db.flush()
                        add_inventory_movement(
                            db,
                            business_owner_phone,
                            pending.product,
                            pending.quantity or 1,
                            pending.unit,
                            pending.unit_price,
                            "IN",
                            "SUPPLIER_PURCHASE",
                            purchase.id,
                            user.id,
                            f"Supplied by {supplier.name.title()}"
                        )
                    else:
                        payment = SupplierPayment(
                            supplier_id=supplier.id,
                            owner_phone=business_owner_phone,
                            amount=pending.paid_amount,
                            product=pending.product,
                            recorded_by_id=user.id,
                            created_at=datetime.utcnow()
                        )
                        db.add(payment)

                    db.delete(pending)
                    db.commit()
                    balance = get_supplier_balance(db, supplier.id)
                    send_whatsapp_message(
                        phone,
                        f"{saved_summary}\nSupplier balance: N{balance:,}"
                    )
                    return {"status": "supplier_saved"}

                customer = db.query(Customer).filter(
                    Customer.name == pending.customer_name,
                    Customer.owner_phone == business_owner_phone
                ).first()

                # 2. Recent Transaction Guard (Prevents User Manual Retries)
                # Check if an identical transaction was saved in the last 2 minutes
                check_amount = pending.buy_amount if pending.action in ["BUY", "COMBINED"] else pending.paid_amount
                check_type = "BUY" if pending.action == "COMBINED" else pending.action
                
                recent_tx = db.query(Transaction).filter(
                    Transaction.customer_id == customer.id,
                    Transaction.type == check_type,
                    Transaction.amount == check_amount,
                    Transaction.created_at >= datetime.utcnow() - timedelta(minutes=2)
                ).first()

                if recent_tx:
                    send_whatsapp_message(
                        phone,
                        f"A similar transaction for {customer.name.title()} was already recorded just now.\n\n"
                        "If this was a mistake, ignore this message. If you truly need to add it again, "
                        "wait a minute or send it with a clear note."
                    )
                    db.delete(pending)
                    db.commit()
                    return {"status": "duplicate_manual_prevention"}

                # Proceed with saving
                saved_summary = pending_transaction_summary(pending, customer)
                stock_updates = []
                stock_missing = []
                if pending.action == "BUY":
                    tx = Transaction(
                        customer_id=customer.id,
                        type="BUY",
                        amount=pending.buy_amount,
                        product=pending.product,
                        quantity=pending.quantity,
                        unit=pending.unit,
                        unit_price=pending.unit_price,
                        due_date=pending.due_date,
                        recorded_by_id=user.id,
                        message_id=message_id,
                        created_at=datetime.utcnow()
                    )
                    db.add(tx)
                    db.flush()
                    if pending_items:
                        add_transaction_items(db, tx.id, pending_items)
                        stock_updates, stock_missing = deduct_inventory_for_items(
                            db,
                            business_owner_phone,
                            pending_items,
                            "CUSTOMER_SALE",
                            tx.id,
                            user.id
                        )
                    elif pending.product:
                        fallback_items = [{
                            "product": pending.product,
                            "quantity": pending.quantity or 1,
                            "unit": pending.unit,
                            "unit_price": pending.unit_price or pending.buy_amount,
                            "total": pending.buy_amount
                        }]
                        add_transaction_items(db, tx.id, fallback_items)
                        stock_updates, stock_missing = deduct_inventory_for_items(
                            db,
                            business_owner_phone,
                            fallback_items,
                            "CUSTOMER_SALE",
                            tx.id,
                            user.id
                        )

                elif pending.action == "PAY":
                    tx = Transaction(
                        customer_id=customer.id,
                        type="PAY",
                        amount=pending.paid_amount,
                        recorded_by_id=user.id,
                        message_id=message_id,
                        created_at=datetime.utcnow()
                    )
                    db.add(tx)
                    if pending.due_date:
                        latest_buy = db.query(Transaction).filter(
                            Transaction.customer_id == customer.id,
                            Transaction.type == "BUY"
                        ).order_by(
                            Transaction.created_at.desc()
                        ).first()
                        if latest_buy:
                            latest_buy.due_date = pending.due_date

                elif pending.action == "COMBINED":
                    buy_tx = Transaction(
                        customer_id=customer.id,
                        type="BUY",
                        amount=pending.buy_amount,
                        product=pending.product,
                        quantity=pending.quantity,
                        unit=pending.unit,
                        unit_price=pending.unit_price,
                        due_date=pending.due_date,
                        recorded_by_id=user.id,
                        message_id=f"{message_id}_buy",
                        created_at=datetime.utcnow()
                    )
                    db.add(buy_tx)
                    db.flush()
                    if pending_items:
                        add_transaction_items(db, buy_tx.id, pending_items)
                        stock_updates, stock_missing = deduct_inventory_for_items(
                            db,
                            business_owner_phone,
                            pending_items,
                            "CUSTOMER_SALE",
                            buy_tx.id,
                            user.id
                        )
                    elif pending.product:
                        fallback_items = [{
                            "product": pending.product,
                            "quantity": pending.quantity or 1,
                            "unit": pending.unit,
                            "unit_price": pending.unit_price or pending.buy_amount,
                            "total": pending.buy_amount
                        }]
                        add_transaction_items(db, buy_tx.id, fallback_items)
                        stock_updates, stock_missing = deduct_inventory_for_items(
                            db,
                            business_owner_phone,
                            fallback_items,
                            "CUSTOMER_SALE",
                            buy_tx.id,
                            user.id
                        )

                    pay_tx = Transaction(
                        customer_id=customer.id,
                        type="PAY",
                        amount=pending.paid_amount,
                        recorded_by_id=user.id,
                        message_id=f"{message_id}_pay",
                        created_at=datetime.utcnow()
                    )
                    db.add(pay_tx)

                memory = db.query(CustomerMemory).filter(
                    CustomerMemory.phone == phone
                ).first()

                if not memory:
                    memory = CustomerMemory(
                        phone=phone,
                        last_customer=customer.name
                    )
                    db.add(memory)
                else:
                    memory.last_customer = customer.name

                db.delete(pending)
                db.commit()

                balance = get_balance(db, customer.id, visible_recorded_by_id)
                msg = f"{saved_summary}\n{balance_status_line(balance)}"
                if stock_updates:
                    msg += "\n\nStock updated:\n" + "\n".join(stock_updates)
                elif stock_missing:
                    msg += "\n\nSale saved. Stock item not found yet. Send STOCK to check inventory."

                send_whatsapp_message(phone, msg)
                return {"status": "saved"}

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

        if parsed["type"] in ["INVENTORY_LIST", "INVENTORY_ITEM"]:
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "INVENTORY", "Inventory")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "inventory_plan_blocked"}
            msg = build_inventory_list_message(
                db,
                business_owner_phone,
                parsed.get("product")
            )
            send_whatsapp_message(phone, msg)
            return {"status": "inventory_list"}

        if parsed["type"] == "SUPPLIER_LIST":
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "SUPPLIERS", "Supplier records")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "supplier_plan_blocked"}
            send_whatsapp_message(phone, build_supplier_list_message(db, business_owner_phone))
            return {"status": "supplier_list"}

        if parsed["type"] == "SUPPLIER_DUE":
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "SUPPLIERS", "Supplier reminders")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "supplier_due_plan_blocked"}
            send_whatsapp_message(phone, build_supplier_due_message(db, business_owner_phone))
            return {"status": "supplier_due"}

        if parsed["type"] == "SUPPLIER_TRANSACTION":
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "SUPPLIERS", "Supplier and inventory records")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "supplier_transaction_plan_blocked"}

            db.query(PendingAction).filter(
                PendingAction.phone == phone
            ).delete()
            pending = PendingAction(
                phone=phone,
                customer_name=parsed["name"].lower(),
                last_customer=parsed["name"].lower(),
                action=parsed["action"],
                buy_amount=parsed.get("buy_amount") or 0,
                paid_amount=parsed.get("paid_amount") or 0,
                product=parsed.get("product"),
                quantity=parsed.get("quantity"),
                unit=parsed.get("unit"),
                unit_price=parsed.get("unit_price"),
                source_text=voice_transcript_text,
                due_date=parsed.get("due_date")
            )
            db.add(pending)
            db.commit()

            if parsed["action"] == "SUPPLIER_PURCHASE":
                unit_label = f" {parsed['unit']}" if parsed.get("unit") else ""
                balance = max((parsed.get("buy_amount") or 0) - (parsed.get("paid_amount") or 0), 0)
                due_line = ""
                if parsed.get("due_date"):
                    due_line = f"\nDue: {parsed['due_date'].strftime('%d/%m/%Y')}"
                confirm_msg = (
                    "Confirm stock from supplier:\n"
                    f"Supplier: {parsed['name'].title()}\n"
                    f"Item: {parsed['product'].title()}\n"
                    f"Qty: {parsed['quantity']:,}{unit_label}\n"
                    f"Cost each: N{parsed['unit_price']:,}\n"
                    f"Total: N{parsed['buy_amount']:,}\n"
                    f"Paid: N{parsed['paid_amount']:,}\n"
                    f"You owe: N{balance:,}"
                    f"{due_line}\n\n"
                    "Reply YES or 1 to save, EDIT or 2 to change."
                )
            else:
                product_line = f"\nFor: {parsed['product'].title()}" if parsed.get("product") else ""
                confirm_msg = (
                    "Confirm supplier payment:\n"
                    f"Supplier: {parsed['name'].title()}\n"
                    f"Paid: N{parsed['paid_amount']:,}"
                    f"{product_line}\n\n"
                    "Reply YES or 1 to save, EDIT or 2 to change."
                )
            confirm_msg = apply_voice_confirmation_options(confirm_msg, voice_transcript_text)
            send_whatsapp_message(phone, confirm_msg)
            return {"status": "confirm_supplier_transaction"}

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

        if parsed["type"] == "SUBSCRIPTION_PAID":
            payment = create_subscription_payment_request(db, user, parsed["plan"])
            db.query(PendingAction).filter(
                PendingAction.phone == phone
            ).delete()
            db.add(
                PendingAction(
                    phone=phone,
                    customer_name=parsed["plan"],
                    action="SUBSCRIPTION_PAYMENT_PENDING",
                    reminder_id=payment.id,
                    last_customer=""
                )
            )
            owner = get_business_owner_user(db, user)
            db.commit()
            notify_subscription_admins(db, payment, owner, evidence_received=False)
            send_whatsapp_message(
                phone,
                f"Thank you. Your {parsed['plan']} subscription request has been received.\n\n"
                "Please send your payment receipt screenshot here. An admin will confirm and activate your plan."
                f"{support_line()}"
            )
            return {"status": "subscription_payment_pending"}

        if parsed["type"] == "PENDING_SUBSCRIPTIONS":
            if not is_subscription_admin(phone, db):
                send_whatsapp_message(phone, "Only subscription admins can view pending subscriptions.")
                return {"status": "unauthorized_pending_subscriptions"}

            payments = db.query(SubscriptionPayment, User).outerjoin(
                User,
                SubscriptionPayment.user_id == User.id
            ).filter(
                SubscriptionPayment.status == "PENDING"
            ).order_by(
                SubscriptionPayment.created_at.asc()
            ).all()
            send_whatsapp_message(phone, format_pending_subscriptions(payments))
            return {"status": "pending_subscriptions"}

        if parsed["type"] == "APP_ADMIN_DASHBOARD":
            if not is_app_admin(phone, db):
                send_whatsapp_message(phone, "Only app admins can view the app admin dashboard.")
                return {"status": "unauthorized_app_admin_dashboard"}

            db.query(PendingAction).filter(
                PendingAction.phone == phone
            ).delete()
            db.add(
                PendingAction(
                    phone=phone,
                    customer_name="",
                    action="APP_ADMIN_DASHBOARD",
                    last_customer=""
                )
            )
            db.commit()
            send_whatsapp_message(phone, build_app_admin_dashboard_message(db))
            return {"status": "app_admin_dashboard"}

        if parsed["type"] == "APP_ADMIN_USERS_BY_PLAN":
            if not is_app_admin(phone, db):
                send_whatsapp_message(phone, "Only app admins can view app users.")
                return {"status": "unauthorized_app_admin_users"}

            users = get_business_users_by_effective_plan(db, parsed["plan"])
            title = "FREE/BASIC Users" if parsed["plan"] == PLAN_BASIC else f"{parsed['plan']} Users"
            send_whatsapp_message(phone, format_user_list(users, title))
            return {"status": "app_admin_users_by_plan"}

        if parsed["type"] == "MANAGE_APP_ADMIN_ROLE":
            if not is_app_admin(phone, db):
                send_whatsapp_message(phone, "Only app admins can manage admin roles.")
                return {"status": "unauthorized_admin_role_management"}

            if not parsed.get("role"):
                send_whatsapp_message(phone, "Unknown admin role.")
                return {"status": "unknown_admin_role"}

            if parsed["role"] == ROLE_APP_ADMIN and parsed["phone"] in app_admin_phones() and not parsed["active"]:
                send_whatsapp_message(
                    phone,
                    "Root app admins from Render APP_ADMIN_PHONES cannot be denied from WhatsApp."
                )
                return {"status": "cannot_deny_root_app_admin"}

            role_record = set_admin_role(
                db,
                parsed["phone"],
                parsed["role"],
                parsed["active"],
                actor_user=user
            )
            db.commit()
            status_text = "allowed" if role_record.is_active else "denied"
            send_whatsapp_message(
                phone,
                f"{role_record.phone} is now {status_text} for {role_record.role}."
            )
            return {"status": "admin_role_updated"}

        if parsed["type"] == "LIST_APP_ADMIN_ROLES":
            if not is_app_admin(phone, db):
                send_whatsapp_message(phone, "Only app admins can view admin roles.")
                return {"status": "unauthorized_admin_role_list"}

            send_whatsapp_message(phone, format_admin_roles(db))
            return {"status": "admin_roles"}

        if parsed["type"] == "APPROVE_SUBSCRIPTION":
            if not is_subscription_admin(phone, db):
                send_whatsapp_message(phone, "Only subscription admins can approve subscriptions.")
                return {"status": "unauthorized_subscription_approval"}

            payment = db.query(SubscriptionPayment).filter(
                SubscriptionPayment.phone == parsed["phone"],
                SubscriptionPayment.status == "PENDING"
            ).order_by(
                SubscriptionPayment.created_at.desc()
            ).first()
            if not payment:
                send_whatsapp_message(phone, "No pending subscription payment found for that phone.")
                return {"status": "subscription_payment_not_found"}

            owner = approve_subscription_payment(db, payment, user)
            db.query(PendingAction).filter(
                PendingAction.phone == owner.phone,
                PendingAction.action == "SUBSCRIPTION_PAYMENT_PENDING"
            ).delete()
            db.commit()
            send_whatsapp_message(
                phone,
                f"Approved {owner.name.title()} for {owner.subscription_plan}.\n"
                f"Expires: {owner.subscription_expires_at.strftime('%d/%m/%Y')}"
            )
            send_whatsapp_message(
                owner.phone,
                f"Your {owner.subscription_plan} plan is now active.\n"
                f"Expires: {owner.subscription_expires_at.strftime('%d/%m/%Y')}\n\n"
                "Send MY PLAN anytime to check your subscription."
            )
            return {"status": "subscription_approved"}

        if parsed["type"] == "REJECT_SUBSCRIPTION":
            if not is_subscription_admin(phone, db):
                send_whatsapp_message(phone, "Only subscription admins can reject subscriptions.")
                return {"status": "unauthorized_subscription_rejection"}

            payment = db.query(SubscriptionPayment).filter(
                SubscriptionPayment.phone == parsed["phone"],
                SubscriptionPayment.status == "PENDING"
            ).order_by(
                SubscriptionPayment.created_at.desc()
            ).first()
            if not payment:
                send_whatsapp_message(phone, "No pending subscription payment found for that phone.")
                return {"status": "subscription_payment_not_found"}

            payment.status = "REJECTED"
            owner = db.query(User).filter(User.id == payment.user_id).first()
            if owner:
                db.query(PendingAction).filter(
                    PendingAction.phone == owner.phone,
                    PendingAction.action == "SUBSCRIPTION_PAYMENT_PENDING"
                ).delete()
            db.commit()
            send_whatsapp_message(phone, "Subscription payment rejected.")
            if owner:
                send_whatsapp_message(
                    owner.phone,
                    "Your subscription payment could not be confirmed. Please send a clearer receipt."
                    f"{support_line()}"
                )
            return {"status": "subscription_rejected"}

        if parsed["type"] == "ACTIVATE_PLAN":
            if not is_subscription_admin(phone, db):
                send_whatsapp_message(phone, "Only subscription admins can activate plans.")
                return {"status": "unauthorized_plan_activation"}

            target_user = db.query(User).filter(
                User.phone == parsed["phone"]
            ).first()
            if not target_user:
                send_whatsapp_message(phone, "User not found for that phone number.")
                return {"status": "plan_target_not_found"}

            target_owner = get_business_owner_user(db, target_user)
            target_owner.subscription_plan = normalize_plan(parsed["plan"])
            target_owner.subscription_status = "ACTIVE"
            if parsed.get("days"):
                target_owner.subscription_expires_at = datetime.utcnow() + timedelta(days=parsed["days"])
            else:
                target_owner.subscription_expires_at = None
            db.commit()

            updated_subscription = get_business_subscription(db, target_owner)
            send_whatsapp_message(
                phone,
                f"Plan updated for {target_owner.name.title()}.\n\n"
                f"{build_plan_message(updated_subscription)}"
            )
            if target_owner.phone != phone:
                send_whatsapp_message(
                    target_owner.phone,
                    f"Your CreditVoice plan is now {target_owner.subscription_plan}."
                )
            return {"status": "plan_activated"}

        if parsed["type"] == "STAFF_MENU":
            # Only primary admins (business owners) should see this menu
            if user.role != "user" or user.parent_id is not None:
                send_whatsapp_message(phone, "❌ Only business owners can view the staff management menu.")
                return {"status": "unauthorized_staff_menu"}

            allowed, upgrade_msg = ensure_feature_allowed(db, user, "STAFF", "Staff management")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "staff_plan_blocked"}

            staff_members = db.query(User).filter(User.parent_id == user.id).all()
            
            if not staff_members:
                send_whatsapp_message(
                    phone, 
                    "You have no staff members registered yet.\n\n"
                    "To add staff, send:\n*ADD STAFF [phone] [name]*"
                )
                return {"status": "staff_menu_empty"}

            msg = "👥 Staff Management\n\n"
            for i, member in enumerate(staff_members, start=1):
                status = "✅ Active" if member.role == "delegate" else "⏳ Pending Invitation"
                access = "Can view all transactions" if member.can_view_all_transactions else "Own records only"
                
                # Calculate totals recorded by this specific staff member
                sales = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
                    Transaction.recorded_by_id == member.id,
                    Transaction.type == "BUY"
                ).scalar()
                
                payments = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
                    Transaction.recorded_by_id == member.id,
                    Transaction.type == "PAY"
                ).scalar()

                msg += (
                    f"{i}. *{member.name.title()}*\n"
                    f"   Status: {status}\n"
                    f"   Access: {access}\n"
                    f"   Recorded: ₦{sales:,} (Sales), ₦{payments:,} (Payments)\n\n"
                )

            msg += (
                "Permission commands:\n"
                "GRANT STAFF [phone] VIEW ALL\n"
                "REVOKE STAFF [phone] VIEW ALL"
            )
            
            send_whatsapp_message(phone, msg)
            return {"status": "staff_menu_sent"}

        if parsed["type"] in ["GRANT_STAFF_VIEW_ALL", "REVOKE_STAFF_VIEW_ALL"]:
            if user.role != "user" or user.parent_id is not None:
                send_whatsapp_message(phone, "Only business owners can change staff permissions.")
                return {"status": "unauthorized_staff_permission"}

            allowed, upgrade_msg = ensure_feature_allowed(db, user, "STAFF_PERMISSION", "Staff permissions")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "staff_permission_plan_blocked"}

            staff_phone = parsed["phone"]
            staff_user = db.query(User).filter(
                User.phone == staff_phone,
                User.parent_id == user.id
            ).first()

            if not staff_user:
                send_whatsapp_message(
                    phone,
                    f"Staff member with phone {staff_phone} not found in your business list."
                )
                return {"status": "staff_not_found"}

            grant_access = parsed["type"] == "GRANT_STAFF_VIEW_ALL"
            staff_user.can_view_all_transactions = grant_access
            db.commit()

            permission_text = "can now view all business transactions" if grant_access else "can now view only their own records"
            send_whatsapp_message(
                phone,
                f"Updated {staff_user.name.title()}: {permission_text}."
            )
            send_whatsapp_message(
                staff_phone,
                f"Your CreditVoice access for *{user.name.title()}* was updated. You {permission_text}."
            )
            return {"status": "staff_permission_updated"}

        if parsed["type"] == "REMOVE_STAFF":
            if user.role != "user" or user.parent_id is not None:
                 send_whatsapp_message(phone, "❌ Only business owners can remove staff.")
                 return {"status": "unauthorized_remove_staff"}

            allowed, upgrade_msg = ensure_feature_allowed(db, user, "STAFF", "Staff management")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "remove_staff_plan_blocked"}

            staff_phone = parsed["phone"]
            staff_user = db.query(User).filter(
                User.phone == staff_phone,
                User.parent_id == user.id
            ).first()

            if not staff_user:
                send_whatsapp_message(
                    phone, 
                    f"❌ Staff member with phone {staff_phone} not found in your business list."
                )
                return {"status": "staff_not_found"}

            staff_name = staff_user.name
            # Reset the staff member to a regular user
            staff_user.role = "user"
            staff_user.parent_id = None
            staff_user.can_view_all_transactions = False
            db.commit()

            send_whatsapp_message(phone, f"✅ Access revoked for {staff_name.title()} ({staff_phone}).")
            # Notify the removed staff member
            send_whatsapp_message(staff_phone, f"📢 Notification: Your access to *{user.name.title()}*'s business data has been revoked.")
            return {"status": "staff_removed"}

        if parsed["type"] == "ADD_STAFF":
            if user.role != "user" or user.parent_id is not None:
                 send_whatsapp_message(phone, "❌ Only business owners can add staff.")
                 return {"status": "unauthorized_add_staff"}

            allowed, upgrade_msg = ensure_feature_allowed(db, user, "STAFF", "Adding staff")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "add_staff_plan_blocked"}

            staff_allowed, staff_limit_msg = check_staff_limit(db, user, subscription)
            if not staff_allowed:
                send_whatsapp_message(phone, staff_limit_msg)
                return {"status": "staff_limit_reached"}

            staff_phone = parsed["phone"]
            staff_name = parsed["name"]
            
            # Check if staff user exists
            staff_user = db.query(User).filter(User.phone == staff_phone).first()
            if staff_user:
                staff_user.role = "delegate_pending"
                staff_user.parent_id = user.id
                staff_user.name = staff_name
                staff_user.can_view_all_transactions = False
            else:
                staff_user = User(
                    phone=staff_phone,
                    name=staff_name,
                    role="delegate_pending",
                    parent_id=user.id,
                    can_view_all_transactions=False
                )
                db.add(staff_user)
            
            db.commit()

            # Notify the Staff Member proactively
            send_whatsapp_message(
                staff_phone,
                f"Hello {staff_name.title()}! *{user.name.title()}* has added you as a staff member on CreditVoice.\n\n"
                "Please reply to this message to view and accept your invitation."
            )

            # Notify the Admin (Business Owner)
            send_whatsapp_message(
                phone,
                f"✅ Staff invitation for *{staff_name.title()}* ({staff_phone}) has been initiated.\n\n"
                f"I have sent an alert to them. We are now waiting for their interaction. You can continue with other tasks, and I will notify you once they accept."
            )
            return {"status": "staff_invited"}

        if parsed["type"] == "RESIGN_REQUEST":
            if user.role != "delegate":
                send_whatsapp_message(phone, "You are not currently registered as staff for any business.")
                return {"status": "resign_not_applicable"}
            
            # Setup confirmation
            res_pending = PendingAction(
                phone=phone,
                action="RESIGN_CONFIRM"
            )
            db.add(res_pending)
            db.commit()
            
            send_whatsapp_message(
                phone,
                f"I received your request to stop working with *{business_name.title()}*.\n\n"
                "Are you sure? This will remove your access to their records.\n\n1. Yes, Confirm\n2. No, Cancel"
            )
            return {"status": "resign_confirm_sent"}

        if parsed["type"] == "REONBOARD":
            # Clear any existing pending actions for this user
            db.query(PendingAction).filter(PendingAction.phone == phone).delete()
            
            # Create a new onboarding pending action
            onboarding = PendingAction(
                phone=phone,
                action="ONBOARD_USER"
            )
            db.add(onboarding)
            db.commit()

            send_whatsapp_message(
                phone,
                "No problem! Let's update your profile.\n\n"
                "Please reply with the *Business Name* you want to use. This name will appear on your reports and customer reminders."
            )
            return {"status": "onboarding_restarted"}

        if parsed["type"] == "SET_PHONE":
            target_name = parsed["name"].lower().strip()
            target_phone = parsed.get("customer_phone")
            target_phone = target_phone.strip() if target_phone else None

            existing_customer = db.query(Customer).filter(
                Customer.name == target_name,
                Customer.owner_phone == business_owner_phone
            ).first()

            if existing_customer and target_phone:
                # Update the phone number immediately
                existing_customer.customer_phone = target_phone
                
                # Update any ReminderMemory for this sender and customer
                db.query(ReminderMemory).filter(
                    ReminderMemory.phone == phone,
                    ReminderMemory.customer_name == target_name
                ).update({ReminderMemory.customer_phone: target_phone})
                
                db.commit()

                # If we were in a reminder flow, keep the current flow but inform user
                if pending and pending.action in ["REMINDER_SELECTION", "REMINDER_CONFIRM"]:
                    send_whatsapp_message(
                        phone,
                        f"✅ Saved phone for {existing_customer.name.title()}: {target_phone}\n\n"
                        "Phone set! Now reply *YES* to send the reminder."
                    )
                    return {"status": "reminder_phone_updated"}

            db.query(PendingAction).filter(
                PendingAction.phone == phone,
                PendingAction.action == "ONBOARD_CUSTOMER"
            ).delete()
            db.commit()

            pending_customer = PendingAction(
                phone=phone,
                customer_name=target_name,
                customer_phone=target_phone,
                action="ONBOARD_CUSTOMER"
            )
            db.add(pending_customer)
            db.commit()

            if existing_customer:
                phone_line = (
                    f" with phone {target_phone}" if target_phone else " without a phone number"
                )
                send_whatsapp_message(
                    phone,
                    f"I found an existing customer {target_name.title()}{phone_line}.\n"
                    "Reply YES or 1 to save, EDIT or 2 to send it again."
                )
            else:
                phone_line = (
                    f" with phone {target_phone}" if target_phone else " without a phone number"
                )
                send_whatsapp_message(
                    phone,
                    f"I found customer {target_name.title()}{phone_line}.\n"
                    "Reply YES or 1 to save, EDIT or 2 to send it again."
                )
            return {"status": "confirm_onboard_customer"}

        if parsed["type"] == "REMIND":
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "DUE_REMINDERS", "Debt reminders")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "reminder_plan_blocked"}

            parts = parsed["text"].split()
            if len(parts) != 2 or not parts[1].isdigit():
                send_whatsapp_message(phone, "Use:\nREMIND 1")
                return {"status": "invalid_remind"}

            index = int(parts[1])
            reminders = db.query(ReminderMemory).filter(
                ReminderMemory.phone == phone
            ).all()

            if index < 1 or index > len(reminders):
                send_whatsapp_message(phone, "Reminder number not found.")
                return {"status": "reminder_not_found"}

            reminder = reminders[index - 1]
            due_date_text = reminder.due_date.strftime("%d/%m/%Y")

            if reminder.reminder_type == "DUE_TODAY":
                msg = (
                    f"Hello {reminder.customer_name.title()},\n\n"
                    f"This is a reminder that your outstanding balance of "
                    f"₦{reminder.balance:,} is due today.\n\nThank you."
                )
            else:
                msg = (
                    f"Hello {reminder.customer_name.title()},\n\n"
                    f"This is a reminder that your outstanding balance of "
                    f"₦{reminder.balance:,} will be due on {due_date_text}.\n\n"
                    f"Thank you."
                )

            send_whatsapp_message(phone, msg)
            return {"status": "remind"}

        if parsed["type"] == "DUE_MENU":
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "DUE_REMINDERS", "Debt reminders")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "due_menu_plan_blocked"}

            db.query(PendingAction).filter(
                PendingAction.phone == phone
            ).delete()
            db.commit()

            menu_pending = PendingAction(
                phone=phone,
                action="DUE_MENU"
            )
            db.add(menu_pending)
            db.commit()

            send_whatsapp_message(
                phone,
                "📅 Debt Reminder Menu\n\n"
                "1. Due in 2 Days\n2. Due Today\n3. Overdue Debtors\n\n"
                "Reply with:\n1, 2, or 3"
            )
            return {"status": "due_menu"}

        if parsed["type"] == "TODAY_SALES":
            total = get_today_sales(db, business_owner_phone, visible_recorded_by_id)
            send_whatsapp_message(phone, f"📊 Today's sales: ₦{total:,}")
            return {"status": "today_sales"}

        if parsed["type"] == "WEEKLY_SALES":
            total = get_weekly_sales(db, business_owner_phone, visible_recorded_by_id)
            send_whatsapp_message(phone, f"📊 Weekly sales: ₦{total:,}")
            return {"status": "weekly_sales"}

        if parsed["type"] == "MONTHLY_SALES":
            total = get_monthly_sales(db, business_owner_phone, visible_recorded_by_id)
            send_whatsapp_message(phone, f"📊 Monthly sales: ₦{total:,}")
            return {"status": "monthly_sales"}

        if parsed["type"] == "YEARLY_SALES":
            total = get_yearly_sales(db, business_owner_phone, visible_recorded_by_id)
            send_whatsapp_message(phone, f"📊 Yearly sales: ₦{total:,}")
            return {"status": "yearly_sales"}

        if parsed["type"] == "PERIOD_TRANSACTIONS":
            stats = get_transaction_stats(db, business_owner_phone, parsed.get("period"), visible_recorded_by_id)
            period_name = parsed.get("period", "ALL TIME").title()
            send_whatsapp_message(
                phone,
                f"📊 {period_name} transactions: {stats['transaction_count']:,}\n"
                f"Credit sales: ₦{stats['credit_sales']:,}\n"
                f"Direct sales: ₦{stats['direct_sales']:,}\n"
                f"Total sales: ₦{stats['total_sales']:,}\n"
                f"Payments received: ₦{stats['total_pay']:,}"
            )
            return {"status": "period_transactions"}

        if parsed["type"] == "PERIOD_TOTAL_RECEIVED":
            stats = get_transaction_stats(db, business_owner_phone, parsed.get("period"), visible_recorded_by_id)
            label = parsed.get("period", "all time")
            send_whatsapp_message(phone, f"📥 Total received {label}: ₦{stats['total_pay']:,}")
            return {"status": "period_total_received"}

        if parsed["type"] == "PERIOD_TOTAL_PAID":
            stats = get_transaction_stats(db, business_owner_phone, parsed.get("period"), visible_recorded_by_id)
            label = parsed.get("period", "all time")
            send_whatsapp_message(phone, f"📤 Total paid {label}: ₦{stats['total_pay']:,}")
            return {"status": "period_total_paid"}

        if parsed["type"] == "OUTSTANDING_BALANCE":
            total = get_outstanding_balance(db, business_owner_phone, visible_recorded_by_id)
            send_whatsapp_message(phone, f"💰 Total outstanding balance: ₦{total:,}")
            return {"status": "outstanding_balance"}

        if parsed["type"] == "PERIOD_CASH_CREDIT":
            stats = get_transaction_stats(db, business_owner_phone, parsed.get("period"), visible_recorded_by_id)
            measure = parsed.get("measure")
            if measure == "CASH":
                send_whatsapp_message(
                    phone,
                    f"💵 Cash {parsed.get('period', 'all time').lower()}: ₦{stats['total_pay']:,}"
                )
            else:
                send_whatsapp_message(
                    phone,
                    f"💳 Credit {parsed.get('period', 'all time').lower()}: ₦{stats['total_buy']:,}"
                )
            return {"status": "period_cash_credit"}

        if parsed["type"] == "MOST_SOLD_PRODUCT":
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "ADVANCED_REPORTS", "Product reports")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "product_report_plan_blocked"}

            product = get_most_sold_product(db, business_owner_phone, recorded_by_id=visible_recorded_by_id)
            if not product:
                send_whatsapp_message(phone, "No product sales data available yet.")
                return {"status": "no_product_sales"}
            send_whatsapp_message(
                phone,
                f"🏆 Most sold product: {product.product.title()}\n"
                f"Quantity: {product.total_quantity:,}\n"
                f"Sales: ₦{product.total_amount:,}"
            )
            return {"status": "most_sold_product"}

        if parsed["type"] == "PRODUCT_LEADERBOARD":
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "ADVANCED_REPORTS", "Product reports")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "product_report_plan_blocked"}

            results = get_product_sales_by_period(db, business_owner_phone, recorded_by_id=visible_recorded_by_id)
            if not results:
                send_whatsapp_message(phone, "No product sales data available yet.")
                return {"status": "product_leaderboard_empty"}
            msg = "📊 Product Leaderboard\n\n"
            for i, row in enumerate(results[:10], start=1):
                msg += (
                    f"{i}. {row.product.title()} → {row.total_quantity:,} units, ₦{row.total_amount:,}\n"
                )
            send_whatsapp_message(phone, msg)
            return {"status": "product_leaderboard"}

        if parsed["type"] == "PRODUCT_SALES_BY_DATE":
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "ADVANCED_REPORTS", "Product reports")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "product_report_plan_blocked"}

            if not parsed.get("date"):
                send_whatsapp_message(phone, "Send product sales by date DD/MM/YYYY")
                return {"status": "product_sales_by_date_missing"}
            results = get_product_sales_by_date(db, business_owner_phone, parsed["date"], visible_recorded_by_id)
            if not results:
                send_whatsapp_message(phone, f"No product sales found for {parsed['date']}")
                return {"status": "product_sales_by_date_empty"}
            msg = f"📅 Product Sales on {parsed['date']}\n\n"
            for i, row in enumerate(results, start=1):
                msg += (
                    f"{i}. {row.product.title()} → {row.total_quantity:,} units, ₦{row.total_amount:,}\n"
                )
            send_whatsapp_message(phone, msg)
            return {"status": "product_sales_by_date"}

        if parsed["type"] == "CUSTOMER_LIST":
            period = parsed.get("period")
            customers = list_customers(db, business_owner_phone, period, visible_recorded_by_id)
            if not customers:
                label = f" for {period.lower()}" if period else ""
                send_whatsapp_message(phone, f"No customers found{label}.")
                return {"status": "customer_list_empty"}
            
            period_header = f" ({period.title()})" if period else ""
            msg = f"👥 Customers{period_header}\n\n"
            for i, customer in enumerate(customers, start=1):
                msg += (
                    f"{i}. {customer['name'].title()}"
                    f" ({customer['phone'] or 'no phone'}) → ₦{customer['balance']:,}\n"
                )
            send_whatsapp_message(phone, msg)
            return {"status": "customer_list"}

        if parsed["type"] == "CUSTOMER_COUNT":
            period = parsed.get("period")
            count = get_customer_count(db, business_owner_phone, period, visible_recorded_by_id)
            period_label = period.lower() if period else "all time"
            send_whatsapp_message(
                phone,
                f"👥 Customers {period_label}: {count:,}"
            )
            return {"status": "customer_count"}

        if parsed["type"] == "NEW_CUSTOMERS":
            period = parsed.get("period")
            count = get_new_customer_count(db, business_owner_phone, period, visible_recorded_by_id)
            period_label = period.lower() if period else "all time"
            send_whatsapp_message(
                phone,
                f"🆕 New customers {period_label}: {count:,}"
            )
            return {"status": "new_customers"}

        if parsed["type"] == "PAID_CUSTOMERS":
            period = parsed.get("period")
            count = get_paid_customer_count(db, business_owner_phone, period, visible_recorded_by_id)
            period_label = period.lower() if period else "all time"
            send_whatsapp_message(
                phone,
                f"✅ Paid customers {period_label}: {count:,}"
            )
            return {"status": "paid_customers"}

        if parsed["type"] == "DASHBOARD_SUMMARY":
            period = parsed.get("period")
            if period is None and text.lower().strip() in [
                "dashboard",
                "stats",
                "dashboard summary",
                "dashboard stats",
                "business summary",
                "business stats"
            ]:
                db.query(PendingAction).filter(
                    PendingAction.phone == phone
                ).delete()
                db.add(
                    PendingAction(
                        phone=phone,
                        customer_name="",
                        action="DASHBOARD_MENU",
                        last_customer=""
                    )
                )
                db.commit()
                send_whatsapp_message(phone, build_dashboard_menu_message())
                return {"status": "dashboard_menu"}

            summary = get_dashboard_summary(db, business_owner_phone, period, visible_recorded_by_id)
            send_whatsapp_message(phone, build_dashboard_summary_message(summary, period))
            return {"status": "dashboard_summary"}

            period_label = period.lower() if period else "all time"
            total_customers = get_customer_count(db, business_owner_phone, period)
            new_customers = get_new_customer_count(db, business_owner_phone, period)
            paid_customers = get_paid_customer_count(db, business_owner_phone, period)
            stats = get_transaction_stats(db, business_owner_phone, period)
            send_whatsapp_message(
                phone,
                f"📊 Dashboard {period_label}:\n"
                f"Total customers: {total_customers:,}\n"
                f"New customers: {new_customers:,}\n"
                f"Paid customers: {paid_customers:,}\n"
                f"Transactions: {stats['transaction_count']:,}\n"
                f"Sales: ₦{stats['total_buy']:,}\n"
                f"Received: ₦{stats['total_pay']:,}"
            )
            return {"status": "dashboard_summary"}

        if parsed["type"] == "BIGGEST_DEBTOR":
            debtor = get_biggest_debtor(db, business_owner_phone, visible_recorded_by_id)
            if not debtor:
                send_whatsapp_message(phone, "No debtors found.")
                return {"status": "biggest_debtor_empty"}
            send_whatsapp_message(
                phone,
                f"🔝 Biggest debtor: {debtor['name'].title()} → ₦{debtor['balance']:,}"
            )
            return {"status": "biggest_debtor"}

        if parsed["type"] == "DEBTOR_LEADERBOARD":
            leaderboard = get_debtor_leaderboard(db, business_owner_phone, recorded_by_id=visible_recorded_by_id)
            if not leaderboard:
                send_whatsapp_message(phone, "No debtors found.")
                return {"status": "debtor_leaderboard_empty"}
            msg = "📋 Debtor Leaderboard\n\n"
            for i, debtor in enumerate(leaderboard, start=1):
                msg += f"{i}. {debtor['name'].title()} → ₦{debtor['balance']:,}\n"
            send_whatsapp_message(phone, msg)
            return {"status": "debtor_leaderboard"}

        if parsed["type"] == "SEARCH_CUSTOMER":
            customers = search_customers(db, business_owner_phone, parsed.get("query", ""), visible_recorded_by_id)
            if not customers:
                send_whatsapp_message(phone, "Customer not found.")
                return {"status": "search_customer_empty"}
            msg = "🔍 Search results\n\n"
            for i, customer in enumerate(customers, start=1):
                msg += f"{i}. {customer.name.title()} → {customer.customer_phone or 'no phone'}\n"
            send_whatsapp_message(phone, msg)
            return {"status": "search_customer"}

        if parsed["type"] == "CUSTOMER_SUMMARY":
            summary = get_customer_summary(db, business_owner_phone, parsed.get("name", ""), visible_recorded_by_id)
            if not summary:
                send_whatsapp_message(phone, "Customer not found.")
                return {"status": "customer_summary_not_found"}
            balance_text = (
                f"credit: ₦{abs(summary['balance']):,}" if summary['balance'] < 0 else f"balance: ₦{summary['balance']:,}"
            )
            send_whatsapp_message(
                phone,
                f"📋 {summary['name'].title()} summary\n"
                f"{balance_text}\n"
                f"Bought: ₦{summary['total_buy']:,}\n"
                f"Paid: ₦{summary['total_pay']:,}\n"
                f"Transactions: {summary['transaction_count']:,}"
            )
            return {"status": "customer_summary"}

        if parsed["type"] == "ADD_TRANSACTION_NOTE":
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "TRANSACTION_NOTES", "Transaction notes")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "transaction_notes_plan_blocked"}

            visible_tx = get_visible_transaction(
                db,
                business_owner_phone,
                parsed["transaction_id"],
                visible_recorded_by_id
            )
            if not visible_tx:
                send_whatsapp_message(phone, "Transaction not found.")
                return {"status": "transaction_note_not_found"}

            transaction, customer = visible_tx
            note = TransactionNote(
                transaction_id=transaction.id,
                author_user_id=user.id,
                note=parsed["note"]
            )
            db.add(note)
            db.commit()
            transaction_name = customer.name.title() if customer else "direct sale"
            send_whatsapp_message(
                phone,
                f"Note added to transaction #{transaction.id} for {transaction_name}."
            )
            return {"status": "transaction_note_added"}

        if parsed["type"] == "TRANSACTION_NOTES":
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "TRANSACTION_NOTES", "Transaction notes")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "transaction_notes_plan_blocked"}

            visible_tx, notes = get_transaction_notes(
                db,
                business_owner_phone,
                parsed["transaction_id"],
                visible_recorded_by_id
            )
            if not visible_tx:
                send_whatsapp_message(phone, "Transaction not found.")
                return {"status": "transaction_notes_not_found"}

            transaction, customer = visible_tx
            send_whatsapp_message(
                phone,
                format_transaction_note_thread(transaction, customer, notes)
            )
            return {"status": "transaction_notes"}

        if parsed["type"] == "CUSTOMER_TRANSACTIONS":
            customer = db.query(Customer).filter(
                Customer.name == parsed.get("name", ""),
                Customer.owner_phone == business_owner_phone
            ).first()
            if not customer:
                send_whatsapp_message(phone, "Customer not found.")
                return {"status": "customer_transactions_not_found"}
            buy_query = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
                Transaction.customer_id == customer.id,
                Transaction.type == "BUY"
            )
            pay_query = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
                Transaction.customer_id == customer.id,
                Transaction.type == "PAY"
            )
            tx_query = db.query(Transaction).filter(
                Transaction.customer_id == customer.id
            )
            if visible_recorded_by_id:
                buy_query = buy_query.filter(Transaction.recorded_by_id == visible_recorded_by_id)
                pay_query = pay_query.filter(Transaction.recorded_by_id == visible_recorded_by_id)
                tx_query = tx_query.filter(Transaction.recorded_by_id == visible_recorded_by_id)
            tx_count = tx_query.count()
            if visible_recorded_by_id and tx_count == 0:
                send_whatsapp_message(phone, "Customer not found.")
                return {"status": "customer_transactions_not_found"}
            total_buy = buy_query.scalar()
            total_pay = pay_query.scalar()
            recent_transactions = tx_query.order_by(
                Transaction.created_at.desc()
            ).limit(5).all()
            recent_lines = ""
            if recent_transactions:
                recent_lines = "\n\nRecent transactions\n"
                for tx in recent_transactions:
                    tx_date = tx.created_at.strftime("%d/%m/%Y")
                    recent_lines += f"#{tx.id} {tx_date} {tx.type}: N{tx.amount:,}\n"
                recent_lines += "\nAdd note:\nnote transaction 12 customer promised Friday"
            send_whatsapp_message(
                phone,
                f"📊 {customer.name.title()} transactions\n"
                f"Total: {tx_count:,}\n"
                f"Bought: ₦{total_buy:,}\n"
                f"Paid: ₦{total_pay:,}"
                f"{recent_lines}"
            )
            return {"status": "customer_transactions"}

        if parsed["type"] == "OVERDUE_DEBTORS":
            overdue_list = get_overdue_debtors(db, business_owner_phone, visible_recorded_by_id)
            if len(overdue_list) == 0:
                send_whatsapp_message(phone, "✅ No overdue debtors.")
                return {"status": "no_overdue"}

            msg = "📋 Overdue Debtors\n\n"
            for i, debtor in enumerate(overdue_list, start=1):
                due_date_text = debtor["due_date"].strftime("%d/%m/%Y")
                msg += (
                    f"{i}. {debtor['name']}\n"
                    f"Balance: ₦{debtor['balance']:,}\n"
                    f"Due: {due_date_text}\n"
                    f"Overdue: {debtor['overdue_days']} days\n\n"
                )

            send_whatsapp_message(phone, msg)
            return {"status": "overdue_direct"}

        if parsed["type"] == "UNPAID_DEBTORS":
            debtors, total_outstanding = get_unpaid_debtors(db, business_owner_phone, visible_recorded_by_id)
            if len(debtors) == 0:
                send_whatsapp_message(phone, "✅ No unpaid debtors.")
                return {"status": "no_debtors"}

            msg = "📋 Unpaid Debtors\n\n"
            for i, debtor in enumerate(debtors, start=1):
                msg += f"{i}. {debtor['name']} → ₦{debtor['balance']:,}\n"

            msg += f"\n💰 Total Outstanding: ₦{total_outstanding:,}"
            send_whatsapp_message(phone, msg)
            return {"status": "unpaid_debtors"}

        if parsed["type"] == "BALANCE":
            name = text.replace("balance", "").strip().lower()
            customer = db.query(Customer).filter(
                Customer.name == name,
                Customer.owner_phone == business_owner_phone
            ).first()

            if not customer:
                send_whatsapp_message(phone, "Customer not found.")
                return {"status": "not_found"}

            balance = get_balance(db, customer.id, visible_recorded_by_id)
            if visible_recorded_by_id:
                has_customer_access = db.query(Transaction).filter(
                    Transaction.customer_id == customer.id,
                    Transaction.recorded_by_id == visible_recorded_by_id
                ).first()
                if not has_customer_access:
                    send_whatsapp_message(phone, "Customer not found.")
                    return {"status": "not_found"}
            if balance < 0:
                msg = f"{customer.name} credit: ₦{abs(balance):,}"
            else:
                msg = f"{customer.name} balance: ₦{balance:,}"

            send_whatsapp_message(phone, msg)
            return {"status": "balance"}

        # Handle pronoun references
        if parsed["action"] == "SALE":
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "DIRECT_SALE", "Direct sales")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "direct_sale_plan_blocked"}

            transaction_allowed, transaction_limit_msg = check_monthly_transaction_limit(
                db,
                business_owner_phone,
                subscription,
                planned_rows=1
            )
            if not transaction_allowed:
                send_whatsapp_message(phone, transaction_limit_msg)
                return {"status": "transaction_limit_reached"}

            db.query(PendingAction).filter(
                PendingAction.phone == phone
            ).delete()
            db.commit()

            pending = PendingAction(
                phone=phone,
                customer_name="",
                last_customer="",
                action="SALE",
                buy_amount=parsed["buy_amount"],
                product=parsed.get("product"),
                quantity=parsed.get("quantity"),
                unit=parsed.get("unit"),
                unit_price=parsed.get("unit_price"),
                items_json=json.dumps(parsed.get("invoice_items") or []),
                source_text=voice_transcript_text
            )
            db.add(pending)
            db.commit()

            if parsed.get("invoice_items"):
                item_line = (
                    f"{format_invoice_items(parsed['invoice_items'])}\n\n"
                    f"Total: ₦{parsed['total']:,}"
                )
            elif parsed.get("quantity") and parsed.get("unit"):
                item_line = (
                    f"{parsed['quantity']} {parsed['unit']} of {parsed['product']} "
                    f"at ₦{parsed['unit_price']:,}, total: ₦{parsed['total']:,}"
                )
            elif parsed.get("quantity") and parsed["quantity"] > 1:
                item_line = (
                    f"{parsed['quantity']} {parsed['product']} "
                    f"at ₦{parsed['unit_price']:,}, total: ₦{parsed['total']:,}"
                )
            else:
                item_line = f"{parsed['product']} - ₦{parsed['total']:,}"

            confirm_msg = (
                f"Confirm service/direct income:\n{item_line}\n"
                "No customer debt will be recorded.\n"
                "Reply YES or 1 to save, EDIT or 2 to change."
            )
            confirm_msg = apply_voice_confirmation_options(confirm_msg, voice_transcript_text)

            send_whatsapp_message(phone, confirm_msg)
            return {"status": "confirm_direct_sale"}

        customer_name = parsed["name"].lower()

        if customer_name in ["he", "she"]:
            memory = db.query(CustomerMemory).filter(
                CustomerMemory.phone == phone
            ).first()

            if memory and memory.last_customer:
                customer_name = memory.last_customer.lower()
            else:
                send_whatsapp_message(phone, "No previous customer found.")
                return {"status": "no_memory"}

        if parsed.get("invoice_items"):
            allowed, upgrade_msg = ensure_feature_allowed(db, user, "INVOICE", "Invoice-style multi-item sales")
            if not allowed:
                send_whatsapp_message(phone, upgrade_msg)
                return {"status": "invoice_plan_blocked"}

        # Get or create customer
        customer = db.query(Customer).filter(
            Customer.name == customer_name,
            Customer.owner_phone == business_owner_phone
        ).first()
        customer_was_created = False

        if not customer:
            customer_allowed, customer_limit_msg = check_customer_limit(
                db,
                business_owner_phone,
                subscription
            )
            if not customer_allowed:
                send_whatsapp_message(phone, customer_limit_msg)
                return {"status": "customer_limit_reached"}

            customer = Customer(
                name=customer_name,
                owner_phone=business_owner_phone
            )
            db.add(customer)
            db.commit()
            customer_was_created = True

        planned_rows = 2 if parsed["action"] == "COMBINED" else 1
        transaction_allowed, transaction_limit_msg = check_monthly_transaction_limit(
            db,
            business_owner_phone,
            subscription,
            planned_rows=planned_rows
        )
        if not transaction_allowed:
            send_whatsapp_message(phone, transaction_limit_msg)
            return {"status": "transaction_limit_reached"}

        # Clear pending and save new pending
        db.query(PendingAction).filter(
            PendingAction.phone == phone
        ).delete()
        db.commit()

        pending = PendingAction(
            phone=phone,
            customer_name=customer.name,
            last_customer=customer.name,
            action=parsed["action"],
            buy_amount=parsed["buy_amount"],
            paid_amount=parsed["paid_amount"],
            product=parsed.get("product"),
            quantity=parsed.get("quantity"),
            unit=parsed.get("unit"),
            unit_price=parsed.get("unit_price"),
            items_json=json.dumps(parsed.get("invoice_items") or []),
            source_text=voice_transcript_text,
            due_date=parsed["due_date"]
        )

        db.add(pending)
        db.commit()

        # Send confirmation
        balance_after_line = build_projected_balance_line(
            db,
            customer.id,
            parsed,
            visible_recorded_by_id
        )
        if parsed["action"] == "BUY":
            if parsed.get("invoice_items"):
                item_line = (
                    f"{format_invoice_items(parsed['invoice_items'])}\n\n"
                    f"Total: ₦{parsed['total']:,}"
                )
                if parsed["due_date"]:
                    due_date_text = parsed["due_date"].strftime("%d/%m/%Y")
                    confirm_msg = (
                        f"Confirm invoice for {customer.name}:\n{item_line}\n"
                        f"Due: {due_date_text}\nReply YES or 1 to save, EDIT or 2 to change."
                    )
                else:
                    confirm_msg = (
                        f"Confirm invoice for {customer.name}:\n{item_line}\n"
                        f"Reply YES or 1 to save, EDIT or 2 to change."
                    )
            elif parsed.get("quantity") and parsed.get("unit") and parsed.get("product") and parsed.get("unit_price"):
                item_line = (
                    f"{parsed['quantity']} {parsed['unit']} of {parsed['product']} "
                    f"at ₦{parsed['unit_price']:,} each, total: ₦{parsed['total']:,}"
                )
                if parsed["due_date"]:
                    due_date_text = parsed["due_date"].strftime("%d/%m/%Y")
                    confirm_msg = (
                        f"Confirm:\n{customer.name} bought {item_line}\n"
                        f"Due: {due_date_text}\nReply YES or 1 to save, EDIT or 2 to change."
                    )
                else:
                    confirm_msg = (
                        f"Confirm:\n{customer.name} bought {item_line}\n"
                        f"Reply YES or 1 to save, EDIT or 2 to change."
                    )
            elif parsed["due_date"]:
                due_date_text = parsed["due_date"].strftime("%d/%m/%Y")
                confirm_msg = (
                    f"Confirm:\n{customer.name} bought ₦{parsed['buy_amount']:,}\n"
                    f"Due: {due_date_text}\nReply YES or 1 to save, EDIT or 2 to change."
                )
            else:
                confirm_msg = (
                    f"Confirm:\n{customer.name} bought ₦{parsed['buy_amount']:,}?\n"
                    f"Reply YES or 1 to save, EDIT or 2 to change."
                )

        elif parsed["action"] == "PAY":
            confirm_msg = (
                f"Confirm:\n{customer.name} paid ₦{parsed['paid_amount']:,}?\n"
                f"Reply YES or 1 to save, EDIT or 2 to change."
            )

        elif parsed["action"] == "COMBINED":
            if parsed.get("invoice_items"):
                item_line = (
                    f"\n{format_invoice_items(parsed['invoice_items'])}\n\n"
                    f"Total bought: ₦{parsed['buy_amount']:,}"
                )
            elif parsed.get("quantity") and parsed.get("unit") and parsed.get("product") and parsed.get("unit_price"):
                item_line = (
                    f"{parsed['quantity']} {parsed['unit']} of {parsed['product']} at ₦{parsed['unit_price']:,} each, total: ₦{parsed['total']:,}"
                )
            else:
                item_line = f"₦{parsed['buy_amount']:,}"

            if parsed["due_date"]:
                due_date_text = parsed["due_date"].strftime("%d/%m/%Y")
                confirm_msg = (
                    f"Confirm:\n{customer.name} bought {item_line}\n"
                    f"and paid ₦{parsed['paid_amount']:,}\n"
                    f"Balance due on: {due_date_text}\nReply YES or 1 to save, EDIT or 2 to change."
                )
            else:
                confirm_msg = (
                    f"Confirm:\n{customer.name} bought {item_line}\n"
                    f"and paid ₦{parsed['paid_amount']:,}?\n"
                    f"Reply YES or 1 to save, EDIT or 2 to change."
                )

        phone_warning = ""
        if not customer.customer_phone:
            setup_hint = f"{customer.name} phone 08012345678"
            if customer_was_created:
                phone_warning = (
                    f"\nNew customer created: {customer.name.title()} with no phone number.\n"
                    "This transaction will still save. For reminders later, send:\n"
                    f"{setup_hint}"
                )
            else:
                phone_warning = (
                    f"\nCustomer phone is not set for {customer.name.title()}.\n"
                    "This transaction will still save. For reminders later, send:\n"
                    f"{setup_hint}"
                )

        confirm_msg = f"{confirm_msg}\n{balance_after_line}{phone_warning}"
        if parsed.get("artisan_note"):
            confirm_msg = (
                f"{confirm_msg}\n"
                "This will record customer debt and payment.\n"
                f"{parsed['artisan_note']}"
            )
        confirm_msg = apply_voice_confirmation_options(confirm_msg, voice_transcript_text)

        send_whatsapp_message(phone, confirm_msg)
        return {"status": "pending"}

    finally:
        db.close()


