import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text

from database import Base


def utcnow():
    """Timezone-aware UTC helper that returns a naive datetime for DB storage."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Customer(Base):

    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, autoincrement=True)

    name = Column(String)

    owner_phone = Column(String, index=True)

    customer_phone = Column(String, nullable=True)

    # General-purpose tag: student class/grade, driver name, or other category
    category = Column(String, nullable=True)

    # Secondary contact: driver phone for truck customers, alternate contact otherwise
    secondary_phone = Column(String, nullable=True)

    # True when this customer record represents a registered truck/vehicle
    is_truck = Column(Boolean, nullable=True, default=False)

    created_at = Column(
        DateTime,
        default=utcnow
    )


class User(Base):

    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    name = Column(String)

    phone = Column(String, unique=True)

    role = Column(String, default="user")

    parent_id = Column(String, ForeignKey("users.id"), nullable=True)

    can_view_all_transactions = Column(Boolean, default=False)

    business_category = Column(String, nullable=True)

    business_type = Column(String, nullable=True)

    business_type_label = Column(String, nullable=True)

    subscription_plan = Column(String, default="BASIC")

    subscription_status = Column(String, default="ACTIVE")

    subscription_expires_at = Column(DateTime, nullable=True)

    shop_tag = Column(String, unique=True, nullable=True)

    email = Column(String, unique=True, nullable=True)

    newsletter_consent = Column(Boolean, default=False, nullable=True)

    whatsapp_linked = Column(Boolean, default=False, nullable=True)

    recovery_pin_hash = Column(String, nullable=True)

    pin_attempts = Column(Integer, default=0)

    pin_locked_until = Column(DateTime, nullable=True)

    invite_code = Column(String, nullable=True)

    invite_code_attempts = Column(Integer, default=0)

    invite_expires_at = Column(DateTime, nullable=True)

    created_at = Column(
        DateTime,
        default=utcnow
    )


class Branch(Base):

    __tablename__ = "branches"

    id = Column(Integer, primary_key=True, autoincrement=True)

    owner_phone = Column(String, index=True)

    name = Column(String)

    is_default = Column(Boolean, default=False)

    created_at = Column(DateTime, default=utcnow)


class Transaction(Base):

    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)

    customer_id = Column(
        Integer,
        ForeignKey("customers.id"),
        nullable=True,
        index=True,
    )

    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True, index=True)

    type = Column(String)

    amount = Column(Integer)

    product = Column(String, nullable=True)

    quantity = Column(Integer, nullable=True)

    unit = Column(String, nullable=True)

    unit_price = Column(Integer, nullable=True)

    recorded_by_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)

    created_at = Column(
        DateTime,
        default=utcnow
    )

    due_date = Column(
        DateTime,
        nullable=True
    )

    message_id = Column(
        String,
        unique=True
    )

    is_voided = Column(Boolean, default=False, nullable=True)

    void_reason = Column(String, nullable=True)

    voided_by_id = Column(String, ForeignKey("users.id"), nullable=True)

    voided_at = Column(DateTime, nullable=True)


class TransactionItem(Base):

    __tablename__ = "transaction_items"

    id = Column(Integer, primary_key=True, autoincrement=True)

    transaction_id = Column(Integer, ForeignKey("transactions.id"))

    product = Column(String)

    quantity = Column(Integer, default=1)

    unit = Column(String, nullable=True)

    unit_price = Column(Integer)

    total = Column(Integer)

    created_at = Column(
        DateTime,
        default=utcnow
    )


class TransactionNote(Base):

    __tablename__ = "transaction_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)

    transaction_id = Column(Integer, ForeignKey("transactions.id"))

    author_user_id = Column(String, ForeignKey("users.id"))

    note = Column(String)

    created_at = Column(
        DateTime,
        default=utcnow
    )


class Supplier(Base):

    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, autoincrement=True)

    name = Column(String)

    owner_phone = Column(String, index=True)

    created_at = Column(DateTime, default=utcnow)


class SupplierPurchase(Base):

    __tablename__ = "supplier_purchases"

    id = Column(Integer, primary_key=True, autoincrement=True)

    supplier_id = Column(Integer, ForeignKey("suppliers.id"))

    owner_phone = Column(String, index=True)

    product = Column(String)

    quantity = Column(Integer, nullable=True)

    unit = Column(String, nullable=True)

    unit_price = Column(Integer, nullable=True)

    total = Column(Integer)

    paid_amount = Column(Integer, default=0)

    due_date = Column(DateTime, nullable=True)

    recorded_by_id = Column(String, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=utcnow)


class SupplierPayment(Base):

    __tablename__ = "supplier_payments"

    id = Column(Integer, primary_key=True, autoincrement=True)

    supplier_id = Column(Integer, ForeignKey("suppliers.id"))

    owner_phone = Column(String)

    amount = Column(Integer)

    product = Column(String, nullable=True)

    recorded_by_id = Column(String, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=utcnow)


class InventoryItem(Base):

    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True, autoincrement=True)

    owner_phone = Column(String, index=True)

    name = Column(String)

    unit = Column(String, nullable=True)

    quantity = Column(Float, default=0.0)

    cost_price = Column(Integer, nullable=True)

    selling_price = Column(Integer, nullable=True)

    retail_unit = Column(String, nullable=True)      # smaller selling unit, e.g. "egg", "congo", "cup"

    retail_per_base = Column(Integer, nullable=True) # how many retail units = 1 base unit (e.g. 30)

    retail_price = Column(Integer, nullable=True)    # selling price per 1 retail unit

    size = Column(String, nullable=True)

    color = Column(String, nullable=True)

    description = Column(String, nullable=True)

    media_url = Column(String, nullable=True)

    payment_modes = Column(String, nullable=True)

    delivery_options = Column(String, nullable=True)

    is_available = Column(Boolean, default=True)

    low_stock_alert = Column(Integer, nullable=True)

    category = Column(String, nullable=True)

    reorder_quantity = Column(Integer, nullable=True)

    expiry_date = Column(DateTime, nullable=True)   # medicine / perishable expiry date

    batch_no = Column(String, nullable=True)        # batch / NAFDAC / lot number

    created_at = Column(DateTime, default=utcnow)

    updated_at = Column(DateTime, default=utcnow)


class InventoryMovement(Base):

    __tablename__ = "inventory_movements"

    id = Column(Integer, primary_key=True, autoincrement=True)

    owner_phone = Column(String)

    item_id = Column(Integer, ForeignKey("inventory_items.id"))

    movement_type = Column(String)

    quantity = Column(Float)

    unit_price = Column(Integer, nullable=True)

    source_type = Column(String, nullable=True)

    source_id = Column(Integer, nullable=True)

    note = Column(String, nullable=True)

    recorded_by_id = Column(String, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=utcnow)


class AutomationSettings(Base):

    __tablename__ = "automation_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    owner_phone = Column(String, unique=True)

    bot_enabled = Column(Boolean, default=False)

    auto_reply_enabled = Column(Boolean, default=True)

    auto_order_enabled = Column(Boolean, default=False)

    allow_part_payment = Column(Boolean, default=True)

    min_deposit_percent = Column(Integer, default=0)

    payment_modes = Column(String, nullable=True)

    pickup_address = Column(String, nullable=True)

    delivery_note = Column(String, nullable=True)

    business_hours = Column(String, nullable=True)

    uncertainty_alerts_enabled = Column(Boolean, default=True)

    created_at = Column(DateTime, default=utcnow)

    updated_at = Column(DateTime, default=utcnow)


class CustomerConversation(Base):

    __tablename__ = "customer_conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)

    owner_phone = Column(String)

    customer_phone = Column(String)

    customer_name = Column(String, nullable=True)

    status = Column(String, default="AUTO")

    stage = Column(String, default="START")

    product_query = Column(String, nullable=True)

    matched_item_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=True)

    quantity = Column(Integer, nullable=True)

    last_customer_message = Column(String, nullable=True)

    last_bot_message = Column(String, nullable=True)

    created_at = Column(DateTime, default=utcnow)

    updated_at = Column(DateTime, default=utcnow)


class SalesOrder(Base):

    __tablename__ = "sales_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)

    owner_phone = Column(String)

    customer_phone = Column(String)

    customer_name = Column(String, nullable=True)

    status = Column(String, default="PENDING")

    total_amount = Column(Integer, default=0)

    paid_amount = Column(Integer, default=0)

    balance_amount = Column(Integer, default=0)

    payment_status = Column(String, default="UNPAID")

    payment_mode = Column(String, nullable=True)

    delivery_status = Column(String, default="NOT_STARTED")

    delivery_address = Column(String, nullable=True)

    due_date = Column(DateTime, nullable=True)

    notes = Column(String, nullable=True)

    created_at = Column(DateTime, default=utcnow)

    updated_at = Column(DateTime, default=utcnow)


class SalesOrderItem(Base):

    __tablename__ = "sales_order_items"

    id = Column(Integer, primary_key=True, autoincrement=True)

    order_id = Column(Integer, ForeignKey("sales_orders.id"))

    inventory_item_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=True)

    product = Column(String)

    quantity = Column(Integer, default=1)

    unit = Column(String, nullable=True)

    size = Column(String, nullable=True)

    color = Column(String, nullable=True)

    unit_price = Column(Integer)

    total = Column(Integer)

    created_at = Column(DateTime, default=utcnow)


class SalesOrderPayment(Base):

    __tablename__ = "sales_order_payments"

    id = Column(Integer, primary_key=True, autoincrement=True)

    order_id = Column(Integer, ForeignKey("sales_orders.id"))

    amount = Column(Integer)

    payment_mode = Column(String, nullable=True)

    status = Column(String, default="PENDING_CONFIRMATION")

    evidence_ref = Column(String, nullable=True)

    created_at = Column(DateTime, default=utcnow)


class SubscriptionPayment(Base):

    __tablename__ = "subscription_payments"

    id = Column(Integer, primary_key=True, autoincrement=True)

    user_id = Column(String, ForeignKey("users.id"))

    phone = Column(String)

    plan = Column(String)

    amount = Column(Integer)

    status = Column(String, default="PENDING")

    payment_method = Column(String, default="BANK_TRANSFER")

    evidence_type = Column(String, nullable=True)

    evidence_ref = Column(String, nullable=True)

    admin_note = Column(String, nullable=True)

    created_at = Column(
        DateTime,
        default=utcnow
    )

    approved_at = Column(DateTime, nullable=True)

    approved_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)


class AppAdminRole(Base):

    __tablename__ = "app_admin_roles"

    id = Column(Integer, primary_key=True, autoincrement=True)

    phone = Column(String)

    role = Column(String)

    is_active = Column(Boolean, default=True)

    created_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)

    deactivated_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=utcnow)

    deactivated_at = Column(DateTime, nullable=True)


class PendingAction(Base):

    __tablename__ = "pending_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)

    phone = Column(String, index=True)

    customer_name = Column(String)

    customer_phone = Column(String, nullable=True)

    action = Column(String)

    reminder_id = Column(Integer, nullable=True)

    buy_amount = Column(
        Integer,
        default=0
    )

    paid_amount = Column(
        Integer,
        default=0
    )

    product = Column(String, nullable=True)

    quantity = Column(Integer, nullable=True)

    unit = Column(String, nullable=True)

    unit_price = Column(Integer, nullable=True)

    items_json = Column(String, nullable=True)

    payload_json = Column(String, nullable=True)

    source_text = Column(String, nullable=True)

    last_customer = Column(String)

    due_date = Column(
        DateTime,
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=utcnow
    )


class ParseLog(Base):
    """Records every parsed transaction for tiTi training and quality feedback."""

    __tablename__ = "parse_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone = Column(String, index=True)
    owner_phone = Column(String, index=True, nullable=True)
    business_type = Column(String, nullable=True)
    business_category = Column(String, nullable=True)
    raw_input = Column(Text, nullable=True)
    parsed_type = Column(String, nullable=True)
    parsed_data = Column(Text, nullable=True)
    was_confirmed = Column(Boolean, nullable=True)  # True=YES, False=EDIT, None=unresolved
    correction_input = Column(Text, nullable=True)
    source = Column(String, default="text")          # text / voice
    created_at = Column(DateTime, default=utcnow)


class FastCaptureSettings(Base):
    """Per-business fast capture mode configuration."""

    __tablename__ = "fast_capture_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_phone = Column(String, unique=True, index=True)
    enabled = Column(Boolean, default=False)
    market_start_hour = Column(Integer, default=8)   # WAT hour, inclusive
    market_end_hour = Column(Integer, default=18)    # WAT hour, exclusive
    auto_close_hour = Column(Integer, default=21)    # WAT hour for nightly prompt
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, nullable=True)


class FastCaptureEntry(Base):
    """Individual entry captured during fast mode, pending end-of-day review."""

    __tablename__ = "fast_capture_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_phone = Column(String, index=True)
    recorded_by_id = Column(Integer, nullable=True)
    raw_input = Column(Text)
    parsed_type = Column(String, nullable=True)
    parsed_data = Column(Text, nullable=True)
    confidence = Column(String, default="medium")    # high / medium / low
    confidence_reason = Column(Text, nullable=True)  # plain language, never shown as score
    status = Column(String, default="pending")       # pending / approved / corrected / skipped
    correction_input = Column(Text, nullable=True)
    session_date = Column(String, index=True)        # YYYY-MM-DD WAT
    created_at = Column(DateTime, default=utcnow)
    reviewed_at = Column(DateTime, nullable=True)


class ProcessedMessage(Base):

    __tablename__ = "processed_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)

    message_id = Column(String, unique=True, index=True)

    created_at = Column(DateTime, default=utcnow)


class CustomerMemory(Base):

    __tablename__ = "customer_memory"

    id = Column(Integer, primary_key=True, autoincrement=True)

    phone = Column(String, unique=True)

    last_customer = Column(String)

    # Context memory — what the user was doing last
    last_menu = Column(String, nullable=True)       # e.g. "HOME_MENU", "DASHBOARD_MENU", "DUE_MENU"
    last_command = Column(String, nullable=True)    # e.g. "BUY", "PAY", "STOCK_ADD"
    last_topic = Column(String, nullable=True)      # e.g. "stock", "suppliers", "dashboard"
    last_amount = Column(Integer, nullable=True)    # last confirmed transaction amount
    session_expires_at = Column(DateTime, nullable=True)  # context valid until this time


class ReminderMemory(Base):

    __tablename__ = "reminder_memory"

    id = Column(Integer, primary_key=True, autoincrement=True)

    phone = Column(String)

    customer_id = Column(Integer, nullable=True)

    customer_name = Column(String)

    customer_phone = Column(String, nullable=True)

    balance = Column(Integer)

    due_date = Column(DateTime)

    reminder_type = Column(String)


class ReminderAutomationSettings(Base):

    __tablename__ = "reminder_automation_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    owner_phone = Column(String, unique=True)

    preview_enabled = Column(Boolean, default=True)

    auto_send_enabled = Column(Boolean, default=False)

    reminder_time = Column(String, default="08:00")

    created_at = Column(DateTime, default=utcnow)

    updated_at = Column(DateTime, default=utcnow)


class ReminderQueue(Base):

    __tablename__ = "reminder_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)

    owner_phone = Column(String)

    customer_phone = Column(String, nullable=True)

    customer_name = Column(String)

    balance = Column(Integer)

    due_date = Column(DateTime)

    reminder_type = Column(String)

    source_type = Column(String)

    source_id = Column(Integer, nullable=True)

    message_text = Column(String)

    status = Column(String, default="PENDING_OWNER_CONFIRMATION")

    created_at = Column(DateTime, default=utcnow)

    updated_at = Column(DateTime, default=utcnow)


class LinkedPhone(Base):

    __tablename__ = "linked_phones"

    id = Column(Integer, primary_key=True, autoincrement=True)

    owner_user_id = Column(String, ForeignKey("users.id"), nullable=False)

    linked_phone = Column(String, unique=True, nullable=False, index=True)

    link_code = Column(String, nullable=True)

    link_code_expires_at = Column(DateTime, nullable=True)

    is_active = Column(Boolean, default=False)

    created_at = Column(DateTime, default=utcnow)


class ProductAlias(Base):
    """Per-business product synonyms: alias → canonical name.
    e.g. eba → garri, panadol → paracetamol, para → paracetamol.
    """

    __tablename__ = "product_aliases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_phone = Column(String, index=True)
    alias = Column(String)          # what the user types
    canonical = Column(String)      # what it maps to (must match InventoryItem.name)
    created_at = Column(DateTime, default=utcnow)


class ReminderSendLog(Base):

    __tablename__ = "reminder_send_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    owner_phone = Column(String)

    customer_phone = Column(String, nullable=True)

    reminder_type = Column(String)

    source_type = Column(String)

    source_id = Column(Integer, nullable=True)

    sent_date = Column(String)

    created_at = Column(DateTime, default=utcnow)


# ── Wallet ─────────────────────────────────────────────────────────────────────

class Wallet(Base):
    """One wallet per business owner. Financial home when payments go live."""

    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_phone = Column(String, unique=True, index=True)

    # Running totals — updated on every settled transaction
    balance = Column(Integer, default=0)           # naira, current spendable balance
    total_received = Column(Integer, default=0)    # all-time inflows
    total_withdrawn = Column(Integer, default=0)   # all-time outflows

    # Virtual account — provisioned by fintech partner; null until integrated
    virtual_account_number = Column(String, nullable=True)
    virtual_account_bank = Column(String, nullable=True)
    virtual_account_name = Column(String, nullable=True)
    virtual_account_ref = Column(String, nullable=True)   # partner's internal ref

    # Shareable payment link slug (e.g. "balogunshop")
    payment_link_slug = Column(String, nullable=True, unique=True)

    # Interest flag — set when owner clicks "Notify me"
    waitlist = Column(Boolean, default=False)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, nullable=True)


class WalletTransaction(Base):
    """Every money movement in or out of a business wallet."""

    __tablename__ = "wallet_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_phone = Column(String, index=True)

    # References
    reference = Column(String, unique=True, index=True)  # our internal ref
    fintech_ref = Column(String, nullable=True)           # partner's reference

    amount = Column(Integer)                # naira
    direction = Column(String)             # "in" | "out"
    type = Column(String)                  # "collection" | "payout" | "adjustment"
    status = Column(String, default="pending")  # "pending" | "settled" | "failed"

    # Sender / recipient details (from bank statement)
    sender_name = Column(String, nullable=True)
    sender_account = Column(String, nullable=True)
    sender_bank = Column(String, nullable=True)
    narration = Column(String, nullable=True)

    # Customer matching
    matched_customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    matched_at = Column(DateTime, nullable=True)
    matched_by = Column(String, nullable=True)   # "auto" | "manual"

    created_at = Column(DateTime, default=utcnow)
    settled_at = Column(DateTime, nullable=True)
