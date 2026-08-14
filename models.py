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

    # Branch this customer belongs to (multi-branch isolation). NULL = business-wide.
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True, index=True)

    customer_phone = Column(String, nullable=True)

    # General-purpose tag: student class/grade, driver name, or other category
    category = Column(String, nullable=True)

    # Secondary contact: driver phone for truck customers, alternate contact otherwise
    secondary_phone = Column(String, nullable=True)

    # True when this customer record represents a registered truck/vehicle
    is_truck = Column(Boolean, nullable=True, default=False)

    # Structured per-business-type profile (JSON): tailor measurements,
    # mechanic vehicle details, phone-repair device info, or a generic note.
    profile_json = Column(String, nullable=True)

    # Denormalized outstanding balance (BUY − PAY, voided excluded), maintained
    # automatically by the Transaction event listeners at the bottom of this
    # file and reconciled by the proactive scheduler. Read this instead of
    # summing transactions when no staff-visibility filter is needed.
    balance = Column(Integer, nullable=True, default=0)

    # When this customer last had any transaction recorded (denormalized).
    last_transaction_at = Column(DateTime, nullable=True)

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

    # Session epoch for token revocation: every session token carries this
    # value; bumping it instantly invalidates all of the user's existing tokens
    # (log-out-everywhere, PIN reset, owner revoking a staff).
    token_version = Column(Integer, default=0, nullable=False)

    # Per-business running receipt counter — each sale gets the next number so
    # this business sees a clean 1, 2, 3… on receipts (not the global row id).
    receipt_counter = Column(Integer, default=0, nullable=False)

    # Staff assigned to a branch record their transactions into it.
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True, index=True)

    business_category = Column(String, nullable=True)

    business_type = Column(String, nullable=True)

    business_type_label = Column(String, nullable=True)

    # Business address — shown on receipts/invoices, editable in Profile.
    address = Column(String, nullable=True)

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

    referral_code = Column(String, unique=True, nullable=True, index=True)

    referred_by_code = Column(String, nullable=True)

    wallet_balance = Column(Integer, default=0)

    # Staff profile fields
    staff_position = Column(String, nullable=True)   # e.g. "Cashier", "Sales Rep", "Manager"
    staff_level = Column(String, nullable=True)      # e.g. "Junior", "Senior", "Supervisor"
    staff_salary = Column(Integer, nullable=True)    # monthly salary in naira
    staff_matric = Column(String, nullable=True)     # employee / matric ID

    created_at = Column(
        DateTime,
        default=utcnow
    )

    # Set when the user exercises their right to erasure (NDPR s.2.6).
    # PII fields are anonymised; this timestamp is kept for compliance records.
    deleted_at = Column(DateTime, nullable=True)


class Branch(Base):

    __tablename__ = "branches"

    id = Column(Integer, primary_key=True, autoincrement=True)

    owner_phone = Column(String, index=True)

    name = Column(String)

    # Branch location — shown on receipts/invoices for sales in this branch.
    address = Column(String, nullable=True)

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

    # Promised delivery / collection ("ready by") date for a job or order —
    # distinct from due_date (payment). Drives owner deliver-by reminders.
    service_date = Column(
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

    is_invoice = Column(Boolean, default=False, nullable=True)

    voided_at = Column(DateTime, nullable=True)

    # Per-business receipt number (1, 2, 3…), assigned when the sale is recorded.
    receipt_number = Column(Integer, nullable=True)

    # Formal invoice: per-business sequential number (INV-0001), assigned the
    # first time an invoice document is issued for this sale. Null until then.
    invoice_number = Column(Integer, nullable=True)

    invoiced_at = Column(DateTime, nullable=True)

    # When the invoice was last sent to the customer (WhatsApp). Null = not sent.
    invoice_sent_at = Column(DateTime, nullable=True)


class TransactionItem(Base):

    __tablename__ = "transaction_items"

    id = Column(Integer, primary_key=True, autoincrement=True)

    transaction_id = Column(Integer, ForeignKey("transactions.id"))

    product = Column(String)

    quantity = Column(Integer, default=1)

    unit = Column(String, nullable=True)

    unit_price = Column(Integer)

    total = Column(Integer)

    # Snapshot of the sold stock item's custom fields (e.g. car chassis/engine/
    # colour) at sale time, as a JSON object, so the receipt stays accurate even
    # after the item is edited or sold.
    attributes_json = Column(String, nullable=True)

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

    phone = Column(String, nullable=True)

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

    # Branch this item belongs to (multi-branch isolation). NULL = business-wide.
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True, index=True)

    name = Column(String)

    unit = Column(String, nullable=True)

    quantity = Column(Float, default=0.0)

    cost_price = Column(Integer, nullable=True)

    selling_price = Column(Integer, nullable=True)

    retail_unit = Column(String, nullable=True)      # smaller selling unit, e.g. "egg", "congo", "cup"

    retail_per_base = Column(Integer, nullable=True) # how many retail units = 1 base unit (e.g. 30)

    retail_price = Column(Integer, nullable=True)    # selling price per 1 retail unit

    # Wholesale (quantity-break) pricing on the BASE unit: when a sale's quantity
    # reaches wholesale_min_qty, each unit is priced at wholesale_price instead of
    # selling_price. Both NULL = no wholesale tier (behaves exactly as before).
    wholesale_price = Column(Integer, nullable=True)

    wholesale_min_qty = Column(Integer, nullable=True)

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

    # Per-business custom fields (e.g. car dealers: maker, model, year, colour,
    # chassis no, engine no). JSON keyed by the field definitions in
    # business_templates.INVENTORY_FIELDS. NULL for businesses with no extra set.
    attributes_json = Column(String, nullable=True)

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

    # "MONTHLY" (30-day) or "YEARLY" (365-day). Drives the activation window in
    # approve_subscription_payment.
    billing_period = Column(String, default="MONTHLY")

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


class BusinessPartner(Base):
    """A person who co-owns or has invested in a business on tiTi."""

    __tablename__ = "business_partners"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_phone = Column(String, index=True)        # the business owner
    partner_phone = Column(String, index=True)      # the partner's tiTi phone

    # role: co_founder | partner | investor | silent
    role = Column(String, default="partner")

    # access_level mirrors role but can be customised independently:
    # "full" | "operations" | "financial" | "investment_only"
    access_level = Column(String, default="operations")

    equity_percent = Column(Float, nullable=True)   # e.g. 25.0 for 25%
    investment_amount = Column(Integer, nullable=True)  # capital in naira

    status = Column(String, default="pending")      # pending | active | suspended

    invited_at = Column(DateTime, default=utcnow)
    accepted_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)             # internal memo on this partnership


class BusinessNote(Base):
    """Shared memo / expense ledger entry visible to owner, partners, or investors."""

    __tablename__ = "business_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_phone = Column(String, index=True)

    title = Column(String, nullable=True)
    body = Column(Text)

    # category: expense | income | memo | agreement
    category = Column(String, default="memo")

    amount = Column(Integer, nullable=True)         # naira amount if financial

    # visibility: owner_only | partners | investors | all
    visibility = Column(String, default="owner_only")

    created_by_id = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow)


class ProactiveLog(Base):
    """Tracks proactive messages tiTi has sent so we don't spam users."""

    __tablename__ = "proactive_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_phone = Column(String, index=True)
    event_type = Column(String)   # "low_stock" | "overdue_debt" | "inactivity"
    sent_at = Column(DateTime, default=utcnow)


class AppNotification(Base):
    """In-app notification shown in the frontend and sent via WhatsApp."""

    __tablename__ = "app_notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_phone = Column(String, index=True)
    event_type = Column(String)        # "low_stock" | "overdue_debt" | "inactivity"
    title = Column(String)
    body = Column(Text)
    is_read = Column(Integer, default=0)   # 0 = unread, 1 = read
    created_at = Column(DateTime, default=utcnow)


class PushSubscription(Base):
    """A browser Web Push subscription for a device, so alerts can reach the
    phone while the app is closed. Keyed to the business (owner_phone) so a push
    reaches every subscribed device of that business (owner + staff)."""

    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_phone = Column(String, index=True)   # business the subscription belongs to
    user_id = Column(String, index=True)       # the user/device that subscribed
    endpoint = Column(String, unique=True)     # push service endpoint (unique per device)
    p256dh = Column(String)                     # subscription public key
    auth = Column(String)                       # subscription auth secret
    created_at = Column(DateTime, default=utcnow)


class SchoolTeacher(Base):
    """Teacher roster for school businesses — record only, no app access.
    Basic plan: max 3. Go/Pro: unlimited.
    App-access staff (bursar, accountant) use the normal User/staff model and require Pro.
    """

    __tablename__ = "school_teachers"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    owner_phone = Column(String, index=True)
    name        = Column(String)
    subject     = Column(String, nullable=True)
    class_name  = Column(String, nullable=True)   # e.g. "JSS 2A", "Primary 4"
    phone       = Column(String, nullable=True)
    employee_id = Column(String, nullable=True)   # school-assigned ID
    created_at  = Column(DateTime, default=utcnow)


class FailedParse(Base):
    """Logs messages that tiTi could not understand — used for analytics and improvement."""

    __tablename__ = "failed_parses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone = Column(String, index=True)
    owner_phone = Column(String, nullable=True, index=True)
    text = Column(Text)                         # original message
    resolved_by = Column(String, nullable=True)  # "llm", "openai", None
    llm_reply = Column(Text, nullable=True)      # what tiTi said back
    created_at = Column(DateTime, default=utcnow)


class TokenCode(Base):

    __tablename__ = "token_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String, unique=True, index=True)
    plan = Column(String)                               # "GO" or "PRO"
    duration_days = Column(Integer)
    batch_label = Column(String, nullable=True)
    issued_by = Column(String, nullable=True)
    redeemed_at = Column(DateTime, nullable=True)
    redeemed_by_phone = Column(String, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class Referral(Base):

    __tablename__ = "referrals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    referral_code = Column(String, index=True)          # code that was used
    referrer_phone = Column(String, index=True)         # owner of the code
    referee_phone = Column(String)                      # new user who signed up
    referee_name = Column(String, nullable=True)
    status = Column(String, default="pending")          # "pending" | "rewarded"
    cashback_amount = Column(Integer, nullable=True)    # naira, set when rewarded
    rewarded_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class ReferralSettings(Base):

    __tablename__ = "referral_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cashback_amount = Column(Integer, default=500)
    updated_by = Column(String, nullable=True)
    updated_at = Column(DateTime, default=utcnow)


# ── Filling-station operations (fuel businesses) ─────────────────────────────
# A station is a branch. Fuel is tracked as tank level (deliveries in, meter
# sales out), not as counted stock. Attendant shifts reconcile pump meters to
# cash so shortfalls surface. All rows are branch-scoped by (owner_phone,
# branch_id).

class FuelTank(Base):
    __tablename__ = "fuel_tanks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_phone = Column(String, index=True)
    branch_id = Column(Integer, nullable=True)
    name = Column(String)                       # e.g. "Tank 1"
    product = Column(String)                    # PMS / AGO / DPK / LPG
    capacity_litres = Column(Float, default=0.0)
    current_level_litres = Column(Float, default=0.0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow)


class FuelPump(Base):
    __tablename__ = "fuel_pumps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_phone = Column(String, index=True)
    branch_id = Column(Integer, nullable=True)
    name = Column(String)                       # e.g. "Pump 3" / nozzle label
    tank_id = Column(Integer, ForeignKey("fuel_tanks.id"), nullable=True)
    product = Column(String)
    current_meter = Column(Float, default=0.0)  # last closing totalizer reading
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)


class FuelPrice(Base):
    __tablename__ = "fuel_prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_phone = Column(String, index=True)
    branch_id = Column(Integer, nullable=True)
    product = Column(String)                    # current price is the latest row
    price_per_litre = Column(Integer)           # naira
    updated_by_id = Column(String, nullable=True)
    updated_at = Column(DateTime, default=utcnow)


class FuelDelivery(Base):
    __tablename__ = "fuel_deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_phone = Column(String, index=True)
    branch_id = Column(Integer, nullable=True)
    tank_id = Column(Integer, ForeignKey("fuel_tanks.id"))
    product = Column(String)
    litres = Column(Float)                       # added to the tank level
    cost_per_litre = Column(Integer, nullable=True)
    supplier = Column(String, nullable=True)
    waybill = Column(String, nullable=True)
    delivered_at = Column(DateTime, default=utcnow)
    recorded_by_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class FuelShift(Base):
    __tablename__ = "fuel_shifts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_phone = Column(String, index=True)
    branch_id = Column(Integer, nullable=True)
    pump_id = Column(Integer, ForeignKey("fuel_pumps.id"))
    product = Column(String)
    attendant_id = Column(String, nullable=True)     # User.id of the attendant
    attendant_name = Column(String, nullable=True)
    shift_label = Column(String, nullable=True)      # "day" / "night" (optional)
    opening_meter = Column(Float)
    closing_meter = Column(Float, nullable=True)
    price_per_litre = Column(Integer)                # snapshot at open
    litres_sold = Column(Float, default=0.0)
    expected_amount = Column(Integer, default=0)     # litres_sold * price
    cash_amount = Column(Integer, default=0)
    pos_amount = Column(Integer, default=0)
    transfer_amount = Column(Integer, default=0)
    credit_amount = Column(Integer, default=0)
    shortfall = Column(Integer, default=0)           # expected - collected
    status = Column(String, default="open")          # open / closed
    opened_at = Column(DateTime, default=utcnow)
    closed_at = Column(DateTime, nullable=True)
    recorded_by_id = Column(String, nullable=True)


class FuelDip(Base):
    __tablename__ = "fuel_dips"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_phone = Column(String, index=True)
    branch_id = Column(Integer, nullable=True)
    tank_id = Column(Integer, ForeignKey("fuel_tanks.id"))
    dipped_litres = Column(Float)                    # physical stick reading
    computed_litres = Column(Float)                  # book level at dip time
    variance_litres = Column(Float)                  # dipped - computed
    note = Column(String, nullable=True)
    dipped_at = Column(DateTime, default=utcnow)
    recorded_by_id = Column(String, nullable=True)


class VerifiedSupplier(Base):
    """A CreditVoice user who has applied to appear in the supplier directory."""

    __tablename__ = "verified_suppliers"

    id               = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_phone      = Column(String, ForeignKey("users.phone"), unique=True, nullable=False, index=True)
    supplier_type    = Column(String, nullable=False)  # producer/manufacturer/importer/authorized_distributor/wholesaler
    bio              = Column(Text, nullable=True)
    states_covered   = Column(Text, default="[]")      # JSON list of Nigerian states
    can_deliver      = Column(Boolean, default=False)
    delivery_notes   = Column(Text, nullable=True)
    cac_number       = Column(String, nullable=True)
    verification_status = Column(String, default="pending")  # pending/approved/rejected
    rejection_reason = Column(Text, nullable=True)
    reviewed_at      = Column(DateTime, nullable=True)
    created_at       = Column(DateTime, default=utcnow)
    updated_at       = Column(DateTime, nullable=True)


class VerifiedSupplierProduct(Base):
    """A product line listed by a verified supplier."""

    __tablename__ = "verified_supplier_products"

    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    supplier_id     = Column(String, ForeignKey("verified_suppliers.id"), nullable=False, index=True)
    product_name    = Column(String, nullable=False)
    category        = Column(String, nullable=True)
    available_sizes = Column(Text, default="[]")   # JSON list of size strings e.g. ["50kg bag","25kg bag"]
    min_order_qty   = Column(Float, nullable=True)
    min_order_unit  = Column(String, nullable=True)
    price_range     = Column(String, nullable=True) # descriptive e.g. "₦45,000–₦48,000 per bag"
    quality_notes   = Column(Text, nullable=True)


class SupplierContactMessage(Base):
    """An enquiry sent by a retailer to a verified supplier via the dashboard."""

    __tablename__ = "supplier_contact_messages"

    id                 = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    supplier_id        = Column(String, ForeignKey("verified_suppliers.id"), nullable=False, index=True)
    from_phone         = Column(String, nullable=False)
    from_business_name = Column(String, nullable=True)
    product_interest   = Column(String, nullable=True)
    message            = Column(Text, nullable=False)
    status             = Column(String, default="unread")  # unread/read (supplier's inbox read-tracking)
    # Handshake state: forwarded → accepted/declined, or blocked by admin.
    # Contacts are revealed and rating unlocked only once accepted.
    connection_status  = Column(String, default="forwarded")
    created_at         = Column(DateTime, default=utcnow)


class SupplierRating(Base):
    """A retailer's rating of a verified supplier they did business with."""

    __tablename__ = "supplier_ratings"

    id                 = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    supplier_id        = Column(String, ForeignKey("verified_suppliers.id"), nullable=False, index=True)
    from_phone         = Column(String, nullable=False)
    from_business_name = Column(String, nullable=True)
    rating             = Column(Integer, nullable=False)   # 1–5
    review             = Column(Text, nullable=True)
    created_at         = Column(DateTime, default=utcnow)


class Opportunity(Base):
    """An opportunity card created by admin and visible to all users."""

    __tablename__ = "opportunities"

    id                 = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title              = Column(String, nullable=False)
    partner_name       = Column(String, nullable=True)
    category           = Column(String, nullable=True)  # finance/equipment/trade/products
    description        = Column(Text, nullable=False)
    link_url           = Column(String, nullable=True)
    application_fields = Column(Text, default="[]")     # JSON array of custom intake fields
    is_active          = Column(Boolean, default=True)
    created_at         = Column(DateTime, default=utcnow)


class OpportunityApplication(Base):
    """A user's application for an opportunity, submitted through CreditVoice."""

    __tablename__ = "opportunity_applications"

    id               = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    opportunity_id   = Column(String, ForeignKey("opportunities.id"), nullable=False, index=True)
    applicant_phone  = Column(String, nullable=False)
    applicant_name   = Column(String, nullable=True)
    applicant_email  = Column(String, nullable=True)
    answers          = Column(Text, default="{}")   # JSON: {field_label: answer}
    status           = Column(String, default="submitted")  # submitted/reviewing/approved/declined
    admin_notes      = Column(Text, nullable=True)
    created_at       = Column(DateTime, default=utcnow)
    updated_at       = Column(DateTime, nullable=True)


class AuditLog(Base):
    """Tamper-evident log of security-relevant actions.

    Fields:
      actor_id    — user.id of the person who took the action (None = unauthenticated)
      actor_phone — phone number at time of action (denormalised for durability)
      action      — verb: LOGIN_OK, LOGIN_FAIL, LOGOUT, OTP_REQUEST, PIN_RESET,
                          DELETE_BRANCH, DELETE_NOTE, DELETE_PARTNER, DELETE_TEACHER,
                          ADMIN_TOKEN_GENERATE, ADMIN_SETTINGS_CHANGE
      resource    — e.g. "branch:42", "note:7", "token_codes:GO×10"
      ip          — client IP address
      created_at  — UTC timestamp
    """

    __tablename__ = "audit_log"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    actor_id   = Column(String, nullable=True)
    actor_phone= Column(String,  nullable=True)
    action     = Column(String,  nullable=False, index=True)
    resource   = Column(String,  nullable=True)
    ip         = Column(String,  nullable=True)
    created_at = Column(DateTime, default=utcnow, index=True)



# ═══════════════════════════════════════════════════════════════════════════
# Denormalized Customer.balance maintenance
#
# Every code path that creates, voids, edits, or deletes a Transaction goes
# through the ORM (verified: no bulk query(...).update()/delete() on
# Transaction exists), so these listeners are the single authority that keeps
# Customer.balance and Customer.last_transaction_at correct. The UPDATE runs
# on the same connection as the flush, so it commits/rolls back atomically
# with the transaction row itself. A periodic reconciler in
# proactive_scheduler.py guards against any residual drift.
# ═══════════════════════════════════════════════════════════════════════════

from sqlalchemy import event, func as _sa_func, select as _sa_select


def _tx_balance_effect(tx_type, amount, is_voided, customer_id):
    """Signed effect of one transaction row on its customer's balance."""
    if not customer_id or is_voided:
        return 0
    if tx_type == "BUY":
        return int(amount or 0)
    if tx_type == "PAY":
        return -int(amount or 0)
    return 0


def _apply_customer_delta(connection, customer_id, delta, touch_last_tx=False):
    if not customer_id or (not delta and not touch_last_tx):
        return
    tbl = Customer.__table__
    values = {}
    if delta:
        values["balance"] = _sa_func.coalesce(tbl.c.balance, 0) + delta
    if touch_last_tx:
        values["last_transaction_at"] = utcnow()
    connection.execute(tbl.update().where(tbl.c.id == customer_id).values(**values))


@event.listens_for(Transaction, "after_insert")
def _tx_after_insert(mapper, connection, target):
    if not target.customer_id:
        return
    delta = _tx_balance_effect(target.type, target.amount, target.is_voided, target.customer_id)
    _apply_customer_delta(connection, target.customer_id, delta, touch_last_tx=True)


def _tx_db_row(connection, tx_id):
    """The row as it currently stands in the DB — i.e. the pre-update /
    pre-delete values. Reading from the connection (not Python attribute
    history) sidesteps the expired-instance trap where the old value of an
    attribute assigned after a commit() is unrecorded."""
    tbl = Transaction.__table__
    return connection.execute(
        _sa_select(tbl.c.type, tbl.c.amount, tbl.c.is_voided, tbl.c.customer_id)
        .where(tbl.c.id == tx_id)
    ).first()


@event.listens_for(Transaction, "before_update")
def _tx_before_update(mapper, connection, target):
    old = _tx_db_row(connection, target.id)
    if old is None:
        return
    old_effect = _tx_balance_effect(old.type, old.amount, old.is_voided, old.customer_id)
    new_effect = _tx_balance_effect(target.type, target.amount, target.is_voided, target.customer_id)

    if old.customer_id == target.customer_id:
        _apply_customer_delta(connection, target.customer_id, new_effect - old_effect)
    else:
        # Transaction moved between customers: reverse on the old, apply on the new
        _apply_customer_delta(connection, old.customer_id, -old_effect)
        _apply_customer_delta(connection, target.customer_id, new_effect)


@event.listens_for(Transaction, "before_delete")
def _tx_before_delete(mapper, connection, target):
    old = _tx_db_row(connection, target.id)
    if old is None:
        return
    delta = _tx_balance_effect(old.type, old.amount, old.is_voided, old.customer_id)
    _apply_customer_delta(connection, old.customer_id, -delta)
