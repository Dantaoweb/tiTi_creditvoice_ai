import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String

from database import Base


class Customer(Base):

    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, autoincrement=True)

    name = Column(String)

    owner_phone = Column(String)

    customer_phone = Column(String, nullable=True)

    created_at = Column(
        DateTime,
        default=datetime.utcnow
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

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


class Transaction(Base):

    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)

    customer_id = Column(
        Integer,
        ForeignKey("customers.id"),
        nullable=True
    )

    type = Column(String)

    amount = Column(Integer)

    product = Column(String, nullable=True)

    quantity = Column(Integer, nullable=True)

    unit = Column(String, nullable=True)

    unit_price = Column(Integer, nullable=True)

    recorded_by_id = Column(String, ForeignKey("users.id"), nullable=True)

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    due_date = Column(
        DateTime,
        nullable=True
    )

    message_id = Column(
        String,
        unique=True
    )


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
        default=datetime.utcnow
    )


class TransactionNote(Base):

    __tablename__ = "transaction_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)

    transaction_id = Column(Integer, ForeignKey("transactions.id"))

    author_user_id = Column(String, ForeignKey("users.id"))

    note = Column(String)

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


class Supplier(Base):

    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, autoincrement=True)

    name = Column(String)

    owner_phone = Column(String)

    created_at = Column(DateTime, default=datetime.utcnow)


class SupplierPurchase(Base):

    __tablename__ = "supplier_purchases"

    id = Column(Integer, primary_key=True, autoincrement=True)

    supplier_id = Column(Integer, ForeignKey("suppliers.id"))

    owner_phone = Column(String)

    product = Column(String)

    quantity = Column(Integer, nullable=True)

    unit = Column(String, nullable=True)

    unit_price = Column(Integer, nullable=True)

    total = Column(Integer)

    paid_amount = Column(Integer, default=0)

    due_date = Column(DateTime, nullable=True)

    recorded_by_id = Column(String, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class SupplierPayment(Base):

    __tablename__ = "supplier_payments"

    id = Column(Integer, primary_key=True, autoincrement=True)

    supplier_id = Column(Integer, ForeignKey("suppliers.id"))

    owner_phone = Column(String)

    amount = Column(Integer)

    product = Column(String, nullable=True)

    recorded_by_id = Column(String, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class InventoryItem(Base):

    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True, autoincrement=True)

    owner_phone = Column(String)

    name = Column(String)

    unit = Column(String, nullable=True)

    quantity = Column(Integer, default=0)

    cost_price = Column(Integer, nullable=True)

    selling_price = Column(Integer, nullable=True)

    low_stock_alert = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    updated_at = Column(DateTime, default=datetime.utcnow)


class InventoryMovement(Base):

    __tablename__ = "inventory_movements"

    id = Column(Integer, primary_key=True, autoincrement=True)

    owner_phone = Column(String)

    item_id = Column(Integer, ForeignKey("inventory_items.id"))

    movement_type = Column(String)

    quantity = Column(Integer)

    unit_price = Column(Integer, nullable=True)

    source_type = Column(String, nullable=True)

    source_id = Column(Integer, nullable=True)

    note = Column(String, nullable=True)

    recorded_by_id = Column(String, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


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
        default=datetime.utcnow
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

    created_at = Column(DateTime, default=datetime.utcnow)

    deactivated_at = Column(DateTime, nullable=True)


class PendingAction(Base):

    __tablename__ = "pending_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)

    phone = Column(String)

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

    source_text = Column(String, nullable=True)

    last_customer = Column(String)

    due_date = Column(
        DateTime,
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


class ProcessedMessage(Base):

    __tablename__ = "processed_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)

    message_id = Column(String, unique=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class CustomerMemory(Base):

    __tablename__ = "customer_memory"

    id = Column(Integer, primary_key=True, autoincrement=True)

    phone = Column(
        String,
        unique=True
    )

    last_customer = Column(String)


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
