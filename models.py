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

    # Set when this "supplier" is a finance partner the business is repaying, so
    # trade credit and financing repayments can be told apart in reports and in
    # the scorecard (a ₦1.2m asset would otherwise swamp the supplier metric).
    finance_partner_id = Column(String, ForeignKey("finance_partners.id"), nullable=True, index=True)

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

    # A financed asset's repayment plan lives here as one row per installment —
    # each with its own due date, so punctuality is recorded rather than just a
    # running total, and the existing supplier-due reminders chase each one.
    finance_application_id = Column(String, ForeignKey("finance_applications.id"), nullable=True, index=True)
    installment_no    = Column(Integer, nullable=True)
    installments_total = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=utcnow)


class SupplierPayment(Base):

    __tablename__ = "supplier_payments"

    id = Column(Integer, primary_key=True, autoincrement=True)

    supplier_id = Column(Integer, ForeignKey("suppliers.id"))

    owner_phone = Column(String)

    amount = Column(Integer)

    product = Column(String, nullable=True)

    recorded_by_id = Column(String, ForeignKey("users.id"), nullable=True)

    # Which installment this settles (financing repayments only).
    purchase_id = Column(Integer, ForeignKey("supplier_purchases.id"), nullable=True, index=True)

    # How much this payment can be trusted as evidence:
    #   CLAIMED           — the owner says they paid
    #   PARTNER_CONFIRMED — the partner told us, or admin ticked it
    #   WALLET_CONFIRMED  — money seen landing in a CreditVoice virtual account
    # Only confirmed repayments feed the scorecard's repayment record.
    verification  = Column(String, default="CLAIMED")
    confirmed_at  = Column(DateTime, nullable=True)
    confirmed_by  = Column(String, nullable=True)

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
    # The code printed on the packet, or one the shop prints itself. Indexed
    # because a scan looks a product up by it at the till, and unique per
    # business so two products can never answer the same scan.
    barcode = Column(String, nullable=True, index=True)

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


class ItemPriceChange(Base):
    """Audit trail of manual price edits on a product: every time an owner/staff
    changes the selling price or cost price we record old -> new, when, and who,
    so the change can be tracked over time in the item history and reports."""

    __tablename__ = "item_price_changes"

    id = Column(Integer, primary_key=True, autoincrement=True)

    owner_phone = Column(String, index=True)

    item_id = Column(Integer, ForeignKey("inventory_items.id"), index=True)

    field = Column(String)  # "selling_price" or "cost_price"

    old_price = Column(Integer, nullable=True)

    new_price = Column(Integer, nullable=True)

    changed_by_id = Column(String, ForeignKey("users.id"), nullable=True)

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

    # Shareable single-invite token: the owner copies a link carrying this token
    # and sends it; whoever opens it (logged in) can accept and gets bound as the
    # partner. Null for legacy rows created before invite links existed.
    invite_token = Column(String, nullable=True, index=True)

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


class ThriftGroup(Base):
    """A rotating savings group (ajo / esusu). Members contribute a fixed amount
    each round and the pot rotates to one member per round in turn order."""

    __tablename__ = "thrift_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_phone = Column(String, index=True)         # creator / group admin
    name = Column(String)
    # rotating = classic ajo (pot rotates each round); target = shared-goal pool
    # (e.g. saving for Eid) — flexible amounts/dates toward one common goal.
    group_type = Column(String, default="rotating")
    contribution_amount = Column(Integer)            # rotating: fixed amount per round
    goal_amount = Column(Integer, nullable=True)     # target: the common goal
    target_date = Column(DateTime, nullable=True)    # target: when the goal is for
    frequency = Column(String, default="weekly")     # daily | weekly | monthly | custom
    current_round = Column(Integer, default=1)
    invite_token = Column(String, index=True)        # shareable join link
    require_approval = Column(Boolean, default=True)  # join via link needs approval
    max_members = Column(Integer, nullable=True)      # membership cap; null = unlimited
    locked = Column(Boolean, default=False)           # admin closed the group to new members
    # Auto-continue: when this group fills, the invite link routes new joiners to
    # the next open group in the same series, creating one if none has space.
    spillover = Column(Boolean, default=False)
    series_key = Column(String, nullable=True, index=True)  # shared across sibling groups
    # How the pot recipient each round is chosen: order (join/turn order) | choice
    # (admin picks). More methods (performance, referrals) can extend this later.
    payout_method = Column(String, default="order")
    # Collector (alajo) groups: the agent's fee kept when a customer is settled.
    #   one_day  = one day's contribution   | percent = % of the balance
    #   amount   = a fixed naira fee
    commission_type = Column(String, default="one_day")
    commission_value = Column(Integer, nullable=True)   # for percent/amount
    status = Column(String, default="active")        # active | completed
    created_at = Column(DateTime, default=utcnow)


class ThriftMember(Base):
    """A participant in a ThriftGroup."""

    __tablename__ = "thrift_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("thrift_groups.id"), index=True)
    name = Column(String)
    phone = Column(String, nullable=True)            # contact phone
    user_phone = Column(String, nullable=True, index=True)  # linked tiTi account (join link)
    role = Column(String, default="member")          # admin | approver | member
    status = Column(String, default="active")        # pending | active | declined | removed
    turn_order = Column(Integer, nullable=True)      # rotation position (assigned when active)
    daily_amount = Column(Integer, nullable=True)    # collector: this customer's agreed daily save
    joined_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class ThriftContribution(Base):
    """One member's contribution in one round."""

    __tablename__ = "thrift_contributions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("thrift_groups.id"), index=True)
    member_id = Column(Integer, ForeignKey("thrift_members.id"), index=True)
    round_number = Column(Integer, default=1)
    amount = Column(Integer)
    recorded_by_phone = Column(String, nullable=True)
    # Collector: contributions clear once the customer is settled (cashed out).
    settled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)


class ThriftPayout(Base):
    """The pot paid out to a member for one round."""

    __tablename__ = "thrift_payouts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("thrift_groups.id"), index=True)
    member_id = Column(Integer, ForeignKey("thrift_members.id"), index=True)
    round_number = Column(Integer)
    amount = Column(Integer)                          # net paid out (collector: after commission)
    commission = Column(Integer, nullable=True)       # collector: the agent's fee kept
    recorded_by_phone = Column(String, nullable=True)
    # Recipient confirms they received the pot — visible to every member.
    status = Column(String, default="pending")       # pending | confirmed
    confirmed_at = Column(DateTime, nullable=True)
    confirmed_by_phone = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class SavingsPlan(Base):
    """A personal-savings commitment: a frequency to stick to, an optional goal
    amount to reach, and the basis for save reminders."""

    __tablename__ = "savings_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_phone = Column(String, unique=True, index=True)
    frequency = Column(String, default="weekly")   # daily | weekly | monthly
    goal_amount = Column(Integer, nullable=True)
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
    # Where tapping it should take them, e.g. /inventory. A notification that
    # names a problem and then cannot take you to it wastes the tap.
    link = Column(String, nullable=True)
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


class AcademicSession(Base):
    """A school year, e.g. "2025/2026".

    Fees are owed per term within a session, which is why a school's books
    cannot be a flat list of debts: last session's unpaid fees are a different
    thing from this term's, and only the term they belong to can tell them
    apart.
    """

    __tablename__ = "academic_sessions"

    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_phone = Column(String, index=True)
    name        = Column(String, nullable=False)          # "2025/2026"
    is_current  = Column(Boolean, default=False)
    created_at  = Column(DateTime, default=utcnow)


class SchoolTerm(Base):
    """First, Second or Third term of a session."""

    __tablename__ = "school_terms"

    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_phone = Column(String, index=True)
    session_id  = Column(String, ForeignKey("academic_sessions.id"), index=True)
    name        = Column(String, nullable=False)          # "First Term"
    position    = Column(Integer, default=1)              # 1, 2, 3 — for ordering
    starts_on   = Column(DateTime, nullable=True)
    ends_on     = Column(DateTime, nullable=True)
    is_current  = Column(Boolean, default=False)
    invoiced_at = Column(DateTime, nullable=True)         # when fees were raised
    created_at  = Column(DateTime, default=utcnow)


class SchoolClass(Base):
    """A class or stream — "JSS 2A", "Primary 4", "Beginners"."""

    __tablename__ = "school_classes"

    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_phone = Column(String, index=True)
    name        = Column(String, nullable=False)
    level_order = Column(Integer, default=0)      # so classes list in school order
    teacher_id  = Column(Integer, ForeignKey("school_teachers.id"), nullable=True)
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=utcnow)


class FeeItem(Base):
    """Something a school charges for: tuition, PTA levy, uniform, a textbook.

    `is_optional` is what separates a textbook from tuition — every pupil is
    charged tuition when the term opens, but a book is only owed once the pupil
    takes it.
    """

    __tablename__ = "fee_items"

    id             = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_phone    = Column(String, index=True)
    name           = Column(String, nullable=False)
    kind           = Column(String, default="FEE")     # FEE | LEVY | BOOK | UNIFORM | OTHER
    default_amount = Column(Integer, nullable=True)
    is_optional    = Column(Boolean, default=False)
    is_active      = Column(Boolean, default=True)
    created_at     = Column(DateTime, default=utcnow)


class FeeSchedule(Base):
    """What one class owes for one item in one term.

    This is the part that makes "unpaid" mean something: until the school says
    what it expects, the app can only report what somebody remembered to type.
    """

    __tablename__ = "fee_schedules"

    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_phone = Column(String, index=True)
    term_id     = Column(String, ForeignKey("school_terms.id"), index=True)
    class_id    = Column(String, ForeignKey("school_classes.id"), index=True)
    fee_item_id = Column(String, ForeignKey("fee_items.id"), index=True)
    amount      = Column(Integer, default=0)
    created_at  = Column(DateTime, default=utcnow)


class StudentEnrolment(Base):
    """A pupil in a class for a session.

    The pupil themselves is a Customer, so every balance, receipt, reminder and
    debtor report already works for them. This records which class they sit in
    this session — a new row each session, which is what makes promotion a
    record rather than an overwrite.
    """

    __tablename__ = "student_enrolments"

    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_phone  = Column(String, index=True)
    customer_id  = Column(Integer, ForeignKey("customers.id"), index=True)
    class_id     = Column(String, ForeignKey("school_classes.id"), index=True)
    session_id   = Column(String, ForeignKey("academic_sessions.id"), index=True)
    admission_no = Column(String, nullable=True)
    parent_name  = Column(String, nullable=True)
    status       = Column(String, default="ACTIVE")   # ACTIVE | LEFT | GRADUATED
    enrolled_at  = Column(DateTime, default=utcnow)


class PupilField(Base):
    """A detail this particular school keeps about its pupils.

    Every school asks for name, sex and age; after that they diverge. One keeps
    blood group and allergies, another keeps the child's best colour for prize
    day, a creche keeps who is allowed to collect them. Rather than guess, each
    school builds its own list — picked from a library of common ones or typed
    in — and the registration form draws itself from it.

    The answers live on Customer.profile_json, the same place every other
    business keeps its customer details.
    """

    __tablename__ = "pupil_fields"

    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_phone = Column(String, index=True)
    key         = Column(String, nullable=False)       # stable: "best_colour"
    label       = Column(String, nullable=False)       # shown: "Best colour"
    field_type  = Column(String, default="text")       # text|number|date|choice|phone
    options     = Column(Text, nullable=True)          # JSON list, for choice
    is_required = Column(Boolean, default=False)
    is_standard = Column(Boolean, default=False)       # seeded, not invented here
    sort_order  = Column(Integer, default=0)
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=utcnow)


class FeeExemption(Base):
    """One child excused from part of what their class is charged.

    A class schedule is the default, not a rule: schools carry staff children,
    scholarship pupils, siblings on a discount, and families going through a
    hard term. Without this the only way to be fair is to leave them off the
    register, which loses the child from the school's own records.

    Scope widens as the fields are left empty — no fee_item_id means every
    charge, no term_id means every term until it is switched off.
    """

    __tablename__ = "fee_exemptions"

    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_phone = Column(String, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), index=True)
    fee_item_id = Column(String, ForeignKey("fee_items.id"), nullable=True)
    term_id     = Column(String, ForeignKey("school_terms.id"), nullable=True)
    # EXEMPT (pay nothing) | PERCENT (off) | AMOUNT (off) | FIXED (pay this instead)
    kind        = Column(String, default="EXEMPT")
    value       = Column(Integer, default=0)
    reason      = Column(String, nullable=True)      # "Staff child", "Scholarship"
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=utcnow)
    created_by  = Column(String, nullable=True)


class FeeInvoice(Base):
    """What one pupil was charged for one term, and the transaction that carries it.

    The charge is an ordinary credit transaction, so the pupil's balance, their
    receipts and the debtors list all behave exactly as they do for any other
    customer. This row only records that the term was raised for them, so
    opening a term twice cannot charge anybody twice.
    """

    __tablename__ = "fee_invoices"

    id             = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_phone    = Column(String, index=True)
    customer_id    = Column(Integer, ForeignKey("customers.id"), index=True)
    term_id        = Column(String, ForeignKey("school_terms.id"), index=True)
    class_id       = Column(String, ForeignKey("school_classes.id"), nullable=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    total          = Column(Integer, default=0)
    kind           = Column(String, default="TERM")    # TERM | EXTRA (books taken later)
    created_at     = Column(DateTime, default=utcnow)


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


# ── Finance partners + business scorecard ────────────────────────────────────
# CreditVoice introduces businesses to installment/asset-finance partners (e.g.
# a motorcycle financier) and earns a fee per closed deal. The partner does its
# own underwriting; what CreditVoice supplies is EVIDENCE — a business's trading
# record turned into a report and a tier. Everything here is admin-editable so a
# new partner or a changed criterion never needs a code change.

class FinancePartner(Base):
    """An installment / asset-finance partner, editable by admin.

    `eligibility_json` holds the minimums this partner asks for (months of
    records, monthly sales floor, …) and `commission_*` how CreditVoice is paid
    for a closed deal. Both are per partner because no two agree the same terms.
    """

    __tablename__ = "finance_partners"

    id                = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name              = Column(String, nullable=False)
    contact_name      = Column(String, nullable=True)
    contact_phone     = Column(String, nullable=True)
    contact_email     = Column(String, nullable=True)
    logo_url          = Column(String, nullable=True)
    # What they finance, free text/JSON list: ["motorcycle", "freezer", …]
    asset_types       = Column(Text, default="[]")
    asset_value_min   = Column(Integer, nullable=True)
    asset_value_max   = Column(Integer, nullable=True)
    # {"min_months_recorded": 3, "min_avg_monthly_sales": 300000, …}
    eligibility_json  = Column(Text, default="{}")
    # This partner's own view of what matters, merged over the global scorecard
    # rules: businesses differ (some track suppliers, some never will) and so do
    # financiers. Empty = score this partner's applicants the standard way.
    scorecard_overrides_json = Column(Text, default="{}")
    # Where they operate. Nationwide, or the states they actually serve — a
    # business in Kano shouldn't be shown a partner that only covers Lagos.
    nationwide       = Column(Boolean, default=True)
    states_covered   = Column(Text, default="[]")      # JSON list of Nigerian states
    # FLAT_PER_DEAL | PERCENT_OF_ASSET | PERCENT_OF_REPAYMENTS
    commission_type   = Column(String, default="PERCENT_OF_ASSET")
    commission_value  = Column(Integer, default=0)      # naira, or basis points for percent
    # ON_DELIVERY | ON_FIRST_REPAYMENT | ON_COMPLETION
    commission_due_on = Column(String, default="ON_DELIVERY")
    notes             = Column(Text, nullable=True)
    is_active         = Column(Boolean, default=True)
    created_at        = Column(DateTime, default=utcnow)
    updated_at        = Column(DateTime, nullable=True)
    updated_by        = Column(String, nullable=True)


class ScorecardConfig(Base):
    """Admin-tuned scorecard rules, versioned.

    A report stores the version that produced it, so a score can still be
    explained months later after the weights have been re-tuned — and so a
    partner dispute can be settled from the record.
    """

    __tablename__ = "scorecard_configs"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    version      = Column(Integer, nullable=False, index=True)
    # {"weights": {...}, "tiers": [...], "min_months_recorded": 1, "window_months": 6, ...}
    config_json  = Column(Text, nullable=False)
    is_active    = Column(Boolean, default=True, index=True)
    note         = Column(String, nullable=True)      # why this change was made
    created_at   = Column(DateTime, default=utcnow)
    updated_by   = Column(String, nullable=True)


class FinanceApplication(Base):
    """A business asking to be introduced to a finance partner.

    Carries three things that make the introduction defensible months later:
      • consent — the owner decides when their record is shared, and can revoke
      • a FROZEN scorecard snapshot taken at application time, so neither a
        later re-tuning of the rules nor a sudden burst of recording can change
        what the partner was shown
      • a referral code, so a deal closed by the partner is attributable and
        the fee is calculable rather than negotiable

    Statuses are canonical because commission depends on them:
    SUBMITTED → SHARED → IN_REVIEW → APPROVED → DELIVERED, or DECLINED /
    WITHDRAWN at any point.
    """

    __tablename__ = "finance_applications"

    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    application_code   = Column(String, unique=True, index=True)   # e.g. CV-7F3K2
    partner_id      = Column(String, ForeignKey("finance_partners.id"), index=True)
    owner_phone     = Column(String, index=True)
    business_name   = Column(String, nullable=True)
    contact_phone   = Column(String, nullable=True)

    asset_requested = Column(String, nullable=True)    # "motorcycle", "freezer"
    asset_value     = Column(Integer, nullable=True)   # as quoted by the partner
    note            = Column(Text, nullable=True)      # what the owner told us

    # Consent to share the trading record with THIS partner.
    consent_given_at   = Column(DateTime, nullable=True)
    consent_revoked_at = Column(DateTime, nullable=True)

    # The evidence exactly as it stood when they applied.
    snapshot_json       = Column(Text, nullable=True)
    snapshot_score      = Column(Integer, nullable=True)
    snapshot_tier       = Column(String, nullable=True)
    snapshot_confidence = Column(Integer, nullable=True)
    config_version      = Column(Integer, nullable=True)

    status          = Column(String, default="SUBMITTED", index=True)
    decline_reason  = Column(String, nullable=True)
    partner_ref     = Column(String, nullable=True)    # the partner's own reference
    admin_notes     = Column(Text, nullable=True)

    approved_at     = Column(DateTime, nullable=True)
    delivered_at    = Column(DateTime, nullable=True)

    # The identity details as given when applying, frozen like the scorecard so
    # what the partner was shown can be produced later.
    kyc_json        = Column(Text, nullable=True)

    # Repayment plan as agreed with the partner, entered once when the asset is
    # delivered. The installments themselves live on the supplier rails.
    installment_count  = Column(Integer, nullable=True)
    installment_amount = Column(Integer, nullable=True)
    installment_every  = Column(String, nullable=True)    # WEEKLY | MONTHLY

    # Commission is calculated in a later step; kept here so the ledger has a home.
    commission_amount    = Column(Integer, nullable=True)
    commission_status    = Column(String, default="PENDING")   # PENDING/DUE/INVOICED/PAID
    commission_marked_at = Column(DateTime, nullable=True)

    created_at      = Column(DateTime, default=utcnow, index=True)
    updated_at      = Column(DateTime, nullable=True)


class Campaign(Base):
    """An in-app card — the one that appears over the dashboard with a picture,
    a line of copy and one button.

    Everything about who sees it lives here rather than in code: a campaign that
    asks for a review should only reach someone who has actually used the app
    for a while, and should stop the moment they write one. A card nobody can
    dismiss, or that returns forever, trains people to close the app.
    """

    __tablename__ = "campaigns"

    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    key         = Column(String, index=True)          # short slug, e.g. "review-ask"
    title       = Column(String, nullable=False)
    body        = Column(Text, nullable=False)
    image_url   = Column(String, nullable=True)       # optional artwork; themed card without it
    theme       = Column(String, default="navy")      # navy | amber | green
    cta_label   = Column(String, nullable=True)
    cta_link    = Column(String, nullable=True)       # in-app path, e.g. /profile
    # When the campaign has got what it asked for, it stops by itself.
    goal        = Column(String, nullable=True)       # review | upgrade | None

    # Who it reaches
    owners_only      = Column(Boolean, default=True)
    plans            = Column(String, nullable=True)  # CSV of plans; empty = every plan
    min_transactions = Column(Integer, default=0)     # asking a brand-new user is noise
    min_days_active  = Column(Integer, default=0)

    # When it runs
    starts_at   = Column(DateTime, nullable=True)
    ends_at     = Column(DateTime, nullable=True)
    is_active   = Column(Boolean, default=False)

    # How often one person may see it
    max_shows   = Column(Integer, default=3)
    snooze_days = Column(Integer, default=14)         # after they close it

    # The quiet channels. The card only reaches someone who opens the dashboard;
    # the bell and a push reach the rest, and survive a dismissal.
    also_notify   = Column(Boolean, default=False)
    also_whatsapp = Column(Boolean, default=False)    # still subject to whatsapp_live

    priority    = Column(Integer, default=0)          # highest wins when several fit
    created_at  = Column(DateTime, default=utcnow)
    created_by  = Column(String, nullable=True)


class CampaignView(Base):
    """What one person has seen and done with one campaign.

    Also what makes the admin screen honest: without clicks and dismissals you
    cannot tell a campaign that works from one everybody closes.
    """

    __tablename__ = "campaign_views"

    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    campaign_id   = Column(String, ForeignKey("campaigns.id"), index=True)
    user_phone    = Column(String, index=True)
    shown_count   = Column(Integer, default=0)
    first_shown_at = Column(DateTime, nullable=True)
    last_shown_at  = Column(DateTime, nullable=True)
    clicked_at    = Column(DateTime, nullable=True)
    dismissed_at  = Column(DateTime, nullable=True)
    snooze_until  = Column(DateTime, nullable=True)
    completed_at  = Column(DateTime, nullable=True)   # they did the thing it asked
    notified_at   = Column(DateTime, nullable=True)   # bell/push sent, so never twice


class Testimonial(Base):
    """A business's own words about CreditVoice, shown on the landing page.

    Written by the business, not by us — and it carries their name, town and
    contact, so being featured is a free advert for them rather than unpaid
    marketing copy. Nothing appears publicly until an admin approves it AND the
    owner ticked the consent box, because their phone number ends up on a page
    anyone can read.
    """

    __tablename__ = "testimonials"

    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_phone   = Column(String, index=True)       # who wrote it
    business_name = Column(String, nullable=False)   # as they want it shown
    business_type = Column(String, nullable=True)    # "Provisions shop", "Tailor"…
    location      = Column(String, nullable=True)    # town / state, their words
    quote         = Column(Text, nullable=False)
    contact_phone = Column(String, nullable=True)    # the "free ad" part
    contact_link  = Column(String, nullable=True)    # their page, if any
    consent_public = Column(Boolean, default=False)  # they understood it goes public
    status        = Column(String, default="PENDING", index=True)   # PENDING/APPROVED/REJECTED
    is_featured   = Column(Boolean, default=False)   # chosen for the landing page
    sort_order    = Column(Integer, default=0)
    admin_note    = Column(String, nullable=True)
    created_at    = Column(DateTime, default=utcnow)
    reviewed_at   = Column(DateTime, nullable=True)
    reviewed_by   = Column(String, nullable=True)


class SiteSetting(Base):
    """Small key/value settings for the public site — social links, the number of
    reviews to feature, and anything else that shouldn't need a code change."""

    __tablename__ = "site_settings"

    key        = Column(String, primary_key=True)
    value      = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=True)
    updated_by = Column(String, nullable=True)


class PublicListing(Base):
    """An entry on a public, crawlable page: a resource, a sponsor, or an event.

    These pages are rendered as real HTML on the server, NOT inside the React
    app — the app sits behind a login, so a link there is invisible to search
    engines and worthless to a partner who asked for one.

    `page` and `section` are plain text so new groupings can be added from the
    admin screen without a code change. `link_rel` decides how the link is
    marked: an editorial recommendation passes authority, anything paid for or
    exchanged is marked sponsored, as Google requires.
    """

    __tablename__ = "public_listings"

    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    page        = Column(String, default="resources", index=True)   # resources | events | …
    section     = Column(String, nullable=True)      # e.g. "Sponsors", "Tools we like"
    title       = Column(String, nullable=False)
    url         = Column(String, nullable=True)      # optional: an event may have none
    blurb       = Column(Text, nullable=True)        # the short write-up
    # EDITORIAL (dofollow) | SPONSORED | NOFOLLOW
    link_rel    = Column(String, default="EDITORIAL")
    logo_url    = Column(String, nullable=True)
    # Events only
    event_date  = Column(DateTime, nullable=True)
    event_venue = Column(String, nullable=True)
    sort_order  = Column(Integer, default=0)
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=utcnow)
    updated_at  = Column(DateTime, nullable=True)
    updated_by  = Column(String, nullable=True)


class FinancierUser(Base):
    """A login for someone who works AT a financier (e.g. Gigmile's ops staff).

    Not a CreditVoice business and not a BusinessPartner (which is a user's own
    partner/investor). These accounts live behind their own cookie and can only
    ever see applications sent to their own financier — never another
    financier's, never CreditVoice's commission, never any customer list.

    Created by an app admin, who hands over a one-time invite code the person
    exchanges for their own PIN — the same shape as the staff invite flow.
    """

    __tablename__ = "financier_users"

    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    finance_partner_id = Column(String, ForeignKey("finance_partners.id"), index=True)
    name          = Column(String, nullable=False)
    phone         = Column(String, unique=True, index=True)
    email         = Column(String, nullable=True)
    pin_hash      = Column(String, nullable=True)      # set when they accept the invite
    invite_code   = Column(String, nullable=True, index=True)
    invite_expires_at = Column(DateTime, nullable=True)
    invite_attempts   = Column(Integer, default=0)
    is_active     = Column(Boolean, default=True)
    # Bumping this invalidates their existing sessions (deactivation, PIN reset).
    token_version = Column(Integer, default=0, nullable=False)
    last_login_at = Column(DateTime, nullable=True)
    created_by    = Column(String, nullable=True)
    created_at    = Column(DateTime, default=utcnow)


class BusinessKyc(Base):
    """Who the business owner is, collected when they first apply for financing.

    Not asked at sign-up: nobody should have to prove their identity to start
    keeping records. It is asked once, at the point where a financier genuinely
    needs it, and shared only with the partner the owner applies to.

    `id_number` is the one genuinely sensitive field here; it is never returned
    to anyone but the owner and an app admin, and only the last digits are shown
    in lists. BVN is deliberately not collected.
    """

    __tablename__ = "business_kyc"

    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_phone   = Column(String, unique=True, index=True)
    legal_name    = Column(String, nullable=True)     # as written on the ID
    date_of_birth = Column(String, nullable=True)     # YYYY-MM-DD
    state         = Column(String, nullable=True)
    city          = Column(String, nullable=True)
    address       = Column(String, nullable=True)
    id_type       = Column(String, nullable=True)     # NIN / DRIVERS_LICENCE / …
    id_number     = Column(String, nullable=True)
    # Most businesses in this market are not CAC-registered, and that is fine —
    # but a financier needs to know which it is, and some require registration.
    is_registered = Column(Boolean, nullable=True)
    registered_name     = Column(String, nullable=True)   # name on the certificate
    registration_number = Column(String, nullable=True)   # RC / BN number
    guarantor_name  = Column(String, nullable=True)
    guarantor_phone = Column(String, nullable=True)
    years_in_business = Column(Integer, nullable=True)
    employees     = Column(Integer, nullable=True)
    completed_at  = Column(DateTime, nullable=True)   # set once nothing is missing
    created_at    = Column(DateTime, default=utcnow)
    updated_at    = Column(DateTime, nullable=True)


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
    # Set when this card IS a financier's offer. Users shouldn't have to look in
    # two places for an offer, so financing lives on this one noticeboard; the
    # card then shows that financier's requirements and applying runs the
    # consent + snapshot flow instead of the generic intake form.
    finance_partner_id = Column(String, ForeignKey("finance_partners.id"), nullable=True, index=True)
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
