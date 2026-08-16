import re
from datetime import datetime, timezone

from sqlalchemy import inspect, text

_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ensure_schema_versions_table(engine) -> None:
    """Create the schema_versions tracking table if it doesn't exist.

    Records every migration that has been applied so ops can audit exactly
    what schema state production is in and when each change landed.
    """
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_versions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                migration  VARCHAR  NOT NULL UNIQUE,
                applied_at TIMESTAMP NOT NULL
            )
        """)) if engine.dialect.name == "sqlite" else conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_versions (
                id         SERIAL PRIMARY KEY,
                migration  VARCHAR  NOT NULL UNIQUE,
                applied_at TIMESTAMP NOT NULL
            )
        """))


def _migration_applied(engine, name: str) -> bool:
    """True if a named one-time migration has already been recorded."""
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT 1 FROM schema_versions WHERE migration = :m"), {"m": name}
        ).first()
    return bool(row)


def _mark_migration(engine, name: str) -> None:
    """Record that a named migration has been applied (idempotent)."""
    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            conn.execute(text(
                "INSERT OR IGNORE INTO schema_versions (migration, applied_at) VALUES (:m, :t)"
            ), {"m": name, "t": _utcnow()})
        else:
            conn.execute(text(
                "INSERT INTO schema_versions (migration, applied_at) VALUES (:m, :t) "
                "ON CONFLICT (migration) DO NOTHING"
            ), {"m": name, "t": _utcnow()})


def _safe_table(name: str) -> str:
    """Raise if name is not a plain SQL identifier (guards f-string raw SQL)."""
    if not _SAFE_IDENT.match(name):
        raise ValueError(f"Unsafe table name rejected: {name!r}")
    return name


def ensure_schema_updates(engine):
    from sqlite_dev_repair import repair_empty_sqlite_integer_id_tables
    _ensure_schema_versions_table(engine)
    repair_empty_sqlite_integer_id_tables(engine)
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
        "subscription_expires_at": "TIMESTAMP",
        "shop_tag": "VARCHAR",
        "recovery_pin_hash": "VARCHAR",
        "pin_attempts": "INTEGER DEFAULT 0",
        "pin_locked_until": "TIMESTAMP",
        "invite_code": "VARCHAR",
        "invite_code_attempts": "INTEGER DEFAULT 0",
        "invite_expires_at": "TIMESTAMP",
        "email": "VARCHAR",
        "newsletter_consent": "BOOLEAN DEFAULT FALSE",
        "whatsapp_linked": "BOOLEAN DEFAULT FALSE",
        "staff_position": "VARCHAR",
        "staff_level": "VARCHAR",
        "staff_salary": "INTEGER",
        "staff_matric": "VARCHAR",
        "deleted_at": "TIMESTAMP",
        "referral_code": "VARCHAR",
        "referred_by_code": "VARCHAR",
        "wallet_balance": "INTEGER DEFAULT 0",
        "branch_id": "INTEGER",
        "token_version": "INTEGER DEFAULT 0",
        "address": "VARCHAR",
        "receipt_counter": "INTEGER DEFAULT 0",
    }
    with engine.begin() as connection:
        for column_name, column_type in user_updates.items():
            if column_name not in user_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE users ADD COLUMN {column_name} {column_type}"
                    )
                )

    customer_columns = {
        column["name"]
        for column in inspector.get_columns("customers")
    }
    boolean_false_c = "FALSE" if engine.dialect.name == "postgresql" else "0"
    customer_updates = {
        "category": "VARCHAR",
        "secondary_phone": "VARCHAR",
        "is_truck": f"BOOLEAN DEFAULT {boolean_false_c}",
        "profile_json": "VARCHAR",
        "balance": "INTEGER DEFAULT 0",
        "last_transaction_at": "TIMESTAMP",
        "branch_id": "INTEGER",
    }
    with engine.begin() as connection:
        for column_name, column_type in customer_updates.items():
            if column_name not in customer_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE customers ADD COLUMN {column_name} {column_type}"
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
        "source_text": "VARCHAR",
    }
    with engine.begin() as connection:
        for column_name, column_type in pending_updates.items():
            if column_name not in pending_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE pending_actions ADD COLUMN {column_name} {column_type}"
                    )
                )

    inventory_columns = {
        column["name"]
        for column in inspector.get_columns("inventory_items")
    }
    boolean_true = "TRUE" if engine.dialect.name == "postgresql" else "1"
    inventory_updates = {
        "size": "VARCHAR",
        "color": "VARCHAR",
        "description": "VARCHAR",
        "media_url": "VARCHAR",
        "payment_modes": "VARCHAR",
        "delivery_options": "VARCHAR",
        "is_available": f"BOOLEAN DEFAULT {boolean_true}",
        "category": "VARCHAR",
        "reorder_quantity": "INTEGER",
        "expiry_date": "TIMESTAMP",
        "batch_no": "VARCHAR",
        "retail_unit": "VARCHAR",
        "retail_per_base": "INTEGER",
        "retail_price": "INTEGER",
        "wholesale_price": "INTEGER",
        "wholesale_min_qty": "INTEGER",
        "branch_id": "INTEGER",
        "attributes_json": "VARCHAR",
    }
    with engine.begin() as connection:
        for column_name, column_type in inventory_updates.items():
            if column_name not in inventory_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE inventory_items ADD COLUMN {column_name} {column_type}"
                    )
                )

    # Branch address (shown on receipts/invoices) — add to existing DBs.
    if "branches" in inspector.get_table_names():
        branch_columns = {c["name"] for c in inspector.get_columns("branches")}
        if "address" not in branch_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE branches ADD COLUMN address VARCHAR"))

    # ── Upgrade quantity columns from INTEGER → REAL for fractional stock ───────
    # SQLite uses dynamic typing so floats store correctly without ALTER.
    # PostgreSQL requires an explicit type change.
    if engine.dialect.name == "postgresql":
        _inv_col_types = {
            col["name"]: str(col["type"]).upper()
            for col in inspector.get_columns("inventory_items")
        }
        if _inv_col_types.get("quantity", "").startswith("INT"):
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE inventory_items ALTER COLUMN quantity TYPE REAL")
                )
        _mov_col_types = {
            col["name"]: str(col["type"]).upper()
            for col in inspector.get_columns("inventory_movements")
        }
        if _mov_col_types.get("quantity", "").startswith("INT"):
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE inventory_movements ALTER COLUMN quantity TYPE REAL")
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

        # audit_log.actor_id was created as INTEGER but User.id is a UUID
        # string — convert so login commits don't fail with a type error.
        audit_col_types = {
            col["name"]: str(col["type"]).upper()
            for col in inspector.get_columns("audit_log")
        }
        if audit_col_types.get("actor_id", "").startswith("INT"):
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE audit_log ALTER COLUMN actor_id TYPE VARCHAR USING actor_id::VARCHAR")
                )

    # ── payload_json column for PendingAction ───────────────────────────────
    # Gives flows a typed JSON payload slot so new state no longer requires
    # adding columns to the shared pending_actions table.
    pending_columns = {
        column["name"]
        for column in inspector.get_columns("pending_actions")
    }
    if "payload_json" not in pending_columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE pending_actions ADD COLUMN payload_json VARCHAR")
            )

    transaction_columns = {
        column["name"]
        for column in inspector.get_columns("transactions")
    }
    boolean_false = "FALSE" if engine.dialect.name == "postgresql" else "0"
    transaction_updates = {
        "branch_id":   "INTEGER",
        "quantity":    "INTEGER",
        "unit":        "VARCHAR",
        "unit_price":  "INTEGER",
        "is_voided":   f"BOOLEAN DEFAULT {boolean_false}",
        "void_reason": "VARCHAR",
        "voided_by_id": "VARCHAR",
        "voided_at":   "TIMESTAMP",
        "is_invoice":  f"BOOLEAN DEFAULT {boolean_false}",
        "service_date": "TIMESTAMP",
        "receipt_number": "INTEGER",
        "invoice_number": "INTEGER",
        "invoiced_at": "TIMESTAMP",
        "invoice_sent_at": "TIMESTAMP",
    }
    with engine.begin() as connection:
        for column_name, column_type in transaction_updates.items():
            if column_name not in transaction_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE transactions ADD COLUMN {column_name} {column_type}"
                    )
                )

    # ── Indexes for hot query paths (idempotent, both Postgres and SQLite) ───
    # get_balance() sums BUY/PAY per customer; deliveries/reminders filter by
    # service_date. Without these, those queries scan the transactions table.
    _indexes = [
        ("ix_transactions_customer_type", "transactions", "customer_id, type"),
        ("ix_transactions_service_date",  "transactions", "service_date"),
    ]
    for idx_name, table, cols in _indexes:
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({cols})")
                )
        except Exception as exc:
            print(f"[schema] index {idx_name} skipped: {exc}", flush=True)

    # ── One-time backfill of denormalized customer balance ───────────────────
    # Populates customers.balance (BUY − PAY, voided excluded) and
    # customers.last_transaction_at from history. From then on the Transaction
    # event listeners in models.py keep both columns current, and the
    # proactive scheduler reconciles any drift.
    _BALANCE_BACKFILL = "customer_balance_backfill_2026_07"
    if not _migration_applied(engine, _BALANCE_BACKFILL):
        not_voided = (
            "NOT COALESCE(t.is_voided, FALSE)"
            if engine.dialect.name == "postgresql"
            else "COALESCE(t.is_voided, 0) = 0"
        )
        with engine.begin() as connection:
            connection.execute(text(f"""
                UPDATE customers SET
                    balance = COALESCE((
                        SELECT SUM(CASE WHEN t.type = 'BUY' THEN t.amount
                                        WHEN t.type = 'PAY' THEN -t.amount
                                        ELSE 0 END)
                        FROM transactions t
                        WHERE t.customer_id = customers.id AND {not_voided}
                    ), 0),
                    last_transaction_at = (
                        SELECT MAX(t.created_at) FROM transactions t
                        WHERE t.customer_id = customers.id
                    )
            """))
        _mark_migration(engine, _BALANCE_BACKFILL)
        print("[schema] customer balance backfill applied", flush=True)

    # ── One-time backfill: attach existing customers & stock to the owner's
    # default branch, so multi-branch owners' legacy data lives in their main
    # branch. Single-location owners have no default branch → rows stay NULL
    # (business-wide), which is correct. New records are branch-stamped later.
    _BRANCH_BACKFILL = "customer_inventory_branch_backfill_2026_07"
    if not _migration_applied(engine, _BRANCH_BACKFILL):
        is_default_true = (
            "b.is_default = TRUE"
            if engine.dialect.name == "postgresql"
            else "COALESCE(b.is_default, 0) = 1"
        )
        with engine.begin() as connection:
            for tbl in ("customers", "inventory_items"):
                connection.execute(text(f"""
                    UPDATE {tbl} SET branch_id = (
                        SELECT b.id FROM branches b
                        WHERE b.owner_phone = {tbl}.owner_phone AND {is_default_true}
                        ORDER BY b.id LIMIT 1
                    )
                    WHERE branch_id IS NULL AND EXISTS (
                        SELECT 1 FROM branches b
                        WHERE b.owner_phone = {tbl}.owner_phone AND {is_default_true}
                    )
                """))
        _mark_migration(engine, _BRANCH_BACKFILL)
        print("[schema] customer/inventory branch backfill applied", flush=True)

    # ── Training data capture ────────────────────────────────────────────────
    existing_tables = inspector.get_table_names()

    if "parse_logs" not in existing_tables:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE parse_logs (
                    id SERIAL PRIMARY KEY,
                    phone VARCHAR,
                    owner_phone VARCHAR,
                    business_type VARCHAR,
                    business_category VARCHAR,
                    raw_input TEXT,
                    parsed_type VARCHAR,
                    parsed_data TEXT,
                    was_confirmed BOOLEAN,
                    correction_input TEXT,
                    source VARCHAR DEFAULT 'text',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """ if engine.dialect.name == "postgresql" else """
                CREATE TABLE parse_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone VARCHAR,
                    owner_phone VARCHAR,
                    business_type VARCHAR,
                    business_category VARCHAR,
                    raw_input TEXT,
                    parsed_type VARCHAR,
                    parsed_data TEXT,
                    was_confirmed BOOLEAN,
                    correction_input TEXT,
                    source VARCHAR DEFAULT 'text',
                    created_at TIMESTAMP
                )
            """))

    if "fast_capture_settings" not in existing_tables:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE fast_capture_settings (
                    id SERIAL PRIMARY KEY,
                    owner_phone VARCHAR UNIQUE,
                    enabled BOOLEAN DEFAULT FALSE,
                    market_start_hour INTEGER DEFAULT 8,
                    market_end_hour INTEGER DEFAULT 18,
                    auto_close_hour INTEGER DEFAULT 21,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP
                )
            """ if engine.dialect.name == "postgresql" else """
                CREATE TABLE fast_capture_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_phone VARCHAR UNIQUE,
                    enabled INTEGER DEFAULT 0,
                    market_start_hour INTEGER DEFAULT 8,
                    market_end_hour INTEGER DEFAULT 18,
                    auto_close_hour INTEGER DEFAULT 21,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
            """))

    if "fast_capture_entries" not in existing_tables:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE fast_capture_entries (
                    id SERIAL PRIMARY KEY,
                    owner_phone VARCHAR,
                    recorded_by_id INTEGER,
                    raw_input TEXT,
                    parsed_type VARCHAR,
                    parsed_data TEXT,
                    confidence VARCHAR DEFAULT 'medium',
                    confidence_reason TEXT,
                    status VARCHAR DEFAULT 'pending',
                    correction_input TEXT,
                    session_date VARCHAR,
                    created_at TIMESTAMP DEFAULT NOW(),
                    reviewed_at TIMESTAMP
                )
            """ if engine.dialect.name == "postgresql" else """
                CREATE TABLE fast_capture_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_phone VARCHAR,
                    recorded_by_id INTEGER,
                    raw_input TEXT,
                    parsed_type VARCHAR,
                    parsed_data TEXT,
                    confidence VARCHAR DEFAULT 'medium',
                    confidence_reason TEXT,
                    status VARCHAR DEFAULT 'pending',
                    correction_input TEXT,
                    session_date VARCHAR,
                    created_at TIMESTAMP,
                    reviewed_at TIMESTAMP
                )
            """))

    # ── Context memory columns on customer_memory ───────────────────────────
    customer_memory_columns = {
        column["name"]
        for column in inspector.get_columns("customer_memory")
    }
    customer_memory_updates = {
        "last_menu": "VARCHAR",
        "last_command": "VARCHAR",
        "last_topic": "VARCHAR",
        "last_amount": "INTEGER",
        "session_expires_at": "TIMESTAMP",
    }
    with engine.begin() as connection:
        for column_name, column_type in customer_memory_updates.items():
            if column_name not in customer_memory_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE customer_memory ADD COLUMN {column_name} {column_type}"
                    )
                )

    # ── Per-business product alias table ────────────────────────────────────
    if "product_aliases" not in existing_tables:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE product_aliases (
                    id SERIAL PRIMARY KEY,
                    owner_phone VARCHAR,
                    alias VARCHAR,
                    canonical VARCHAR,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """ if engine.dialect.name == "postgresql" else """
                CREATE TABLE product_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_phone VARCHAR,
                    alias VARCHAR,
                    canonical VARCHAR,
                    created_at TIMESTAMP
                )
            """))

    # ── Wallet tables ───────────────────────────────────────────────────────
    if "wallets" not in existing_tables:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE wallets (
                    id SERIAL PRIMARY KEY,
                    owner_phone VARCHAR UNIQUE,
                    balance INTEGER DEFAULT 0,
                    total_received INTEGER DEFAULT 0,
                    total_withdrawn INTEGER DEFAULT 0,
                    virtual_account_number VARCHAR,
                    virtual_account_bank VARCHAR,
                    virtual_account_name VARCHAR,
                    virtual_account_ref VARCHAR,
                    payment_link_slug VARCHAR UNIQUE,
                    waitlist BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP
                )
            """ if engine.dialect.name == "postgresql" else """
                CREATE TABLE wallets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_phone VARCHAR UNIQUE,
                    balance INTEGER DEFAULT 0,
                    total_received INTEGER DEFAULT 0,
                    total_withdrawn INTEGER DEFAULT 0,
                    virtual_account_number VARCHAR,
                    virtual_account_bank VARCHAR,
                    virtual_account_name VARCHAR,
                    virtual_account_ref VARCHAR,
                    payment_link_slug VARCHAR UNIQUE,
                    waitlist INTEGER DEFAULT 0,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
            """))

    if "wallet_transactions" not in existing_tables:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE wallet_transactions (
                    id SERIAL PRIMARY KEY,
                    owner_phone VARCHAR,
                    reference VARCHAR UNIQUE,
                    fintech_ref VARCHAR,
                    amount INTEGER,
                    direction VARCHAR,
                    type VARCHAR,
                    status VARCHAR DEFAULT 'pending',
                    sender_name VARCHAR,
                    sender_account VARCHAR,
                    sender_bank VARCHAR,
                    narration TEXT,
                    matched_customer_id INTEGER REFERENCES customers(id),
                    matched_at TIMESTAMP,
                    matched_by VARCHAR,
                    created_at TIMESTAMP DEFAULT NOW(),
                    settled_at TIMESTAMP
                )
            """ if engine.dialect.name == "postgresql" else """
                CREATE TABLE wallet_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_phone VARCHAR,
                    reference VARCHAR UNIQUE,
                    fintech_ref VARCHAR,
                    amount INTEGER,
                    direction VARCHAR,
                    type VARCHAR,
                    status VARCHAR DEFAULT 'pending',
                    sender_name VARCHAR,
                    sender_account VARCHAR,
                    sender_bank VARCHAR,
                    narration TEXT,
                    matched_customer_id INTEGER REFERENCES customers(id),
                    matched_at TIMESTAMP,
                    matched_by VARCHAR,
                    created_at TIMESTAMP,
                    settled_at TIMESTAMP
                )
            """))

    # ── Performance indexes for existing databases ───────────────────────────
    # SQLAlchemy index=True only creates indexes on CREATE TABLE.
    # For existing databases we run CREATE INDEX IF NOT EXISTS here.
    if engine.dialect.name == "postgresql":
        indexes = [
            ("ix_customers_owner_phone",       "customers",          "owner_phone"),
            ("ix_transactions_customer_id",    "transactions",       "customer_id"),
            ("ix_transactions_recorded_by_id", "transactions",       "recorded_by_id"),
            ("ix_pending_actions_phone",       "pending_actions",    "phone"),
            ("ix_suppliers_owner_phone",       "suppliers",          "owner_phone"),
            ("ix_supplier_purchases_owner",    "supplier_purchases", "owner_phone"),
            ("ix_inventory_items_owner_phone", "inventory_items",    "owner_phone"),
        ]
        with engine.begin() as connection:
            for index_name, table, column in indexes:
                connection.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {index_name} "
                        f"ON {table} ({column})"
                    )
                )

    # ── business_partners table ─────────────────────────────────────────────
    if "business_partners" not in inspector.get_table_names():
        _pk = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
        with engine.begin() as connection:
            connection.execute(text(f"""
                CREATE TABLE business_partners (
                    id {_pk},
                    owner_phone VARCHAR,
                    partner_phone VARCHAR,
                    role VARCHAR DEFAULT 'partner',
                    access_level VARCHAR DEFAULT 'operations',
                    equity_percent REAL,
                    investment_amount INTEGER,
                    status VARCHAR DEFAULT 'pending',
                    invite_token VARCHAR,
                    invited_at TIMESTAMP,
                    accepted_at TIMESTAMP,
                    notes TEXT
                )
            """))
    else:
        _bp_cols = {c["name"] for c in inspector.get_columns("business_partners")}
        _bp_updates = {
            "equity_percent": "REAL",
            "investment_amount": "INTEGER",
            "access_level": "VARCHAR DEFAULT 'operations'",
            "notes": "TEXT",
            "invite_token": "VARCHAR",
        }
        with engine.begin() as connection:
            for col, typ in _bp_updates.items():
                if col not in _bp_cols:
                    connection.execute(text(
                        f"ALTER TABLE business_partners ADD COLUMN {col} {typ}"
                    ))

    # ── business_notes table ────────────────────────────────────────────────
    if "business_notes" not in inspector.get_table_names():
        _pk = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
        with engine.begin() as connection:
            connection.execute(text(f"""
                CREATE TABLE business_notes (
                    id {_pk},
                    owner_phone VARCHAR,
                    title VARCHAR,
                    body TEXT,
                    category VARCHAR DEFAULT 'memo',
                    amount INTEGER,
                    visibility VARCHAR DEFAULT 'owner_only',
                    created_by_id VARCHAR,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
            """))
    else:
        _bn_cols = {c["name"] for c in inspector.get_columns("business_notes")}
        _bn_updates = {
            "title": "VARCHAR",
            "category": "VARCHAR DEFAULT 'memo'",
            "amount": "INTEGER",
            "visibility": "VARCHAR DEFAULT 'owner_only'",
            "created_by_id": "VARCHAR",
            "updated_at": "TIMESTAMP",
        }
        with engine.begin() as connection:
            for col, typ in _bn_updates.items():
                if col not in _bn_cols:
                    connection.execute(text(
                        f"ALTER TABLE business_notes ADD COLUMN {col} {typ}"
                    ))

    # ── app_notifications table ──────────────────────────────────────────────
    if "app_notifications" not in inspector.get_table_names():
        _pk = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
        with engine.begin() as connection:
            connection.execute(text(f"""
                CREATE TABLE app_notifications (
                    id {_pk},
                    owner_phone VARCHAR,
                    event_type VARCHAR,
                    title VARCHAR,
                    body TEXT,
                    is_read INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))

    # ── push_subscriptions table (Web Push) ──────────────────────────────────
    if "push_subscriptions" not in inspector.get_table_names():
        _pk = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
        with engine.begin() as connection:
            connection.execute(text(f"""
                CREATE TABLE push_subscriptions (
                    id {_pk},
                    owner_phone VARCHAR,
                    user_id VARCHAR,
                    endpoint VARCHAR UNIQUE,
                    p256dh VARCHAR,
                    auth VARCHAR,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))

    # ── proactive_log table ──────────────────────────────────────────────────
    if "proactive_log" not in inspector.get_table_names():
        _pk = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
        with engine.begin() as connection:
            connection.execute(text(f"""
                CREATE TABLE proactive_log (
                    id {_pk},
                    owner_phone VARCHAR,
                    event_type VARCHAR,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))

    # ── school_teachers table ────────────────────────────────────────────────
    if "school_teachers" not in inspector.get_table_names():
        _pk = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
        with engine.begin() as connection:
            connection.execute(text(f"""
                CREATE TABLE school_teachers (
                    id {_pk},
                    owner_phone VARCHAR,
                    name VARCHAR,
                    subject VARCHAR,
                    class_name VARCHAR,
                    phone VARCHAR,
                    employee_id VARCHAR,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))

    # ── failed_parses table ──────────────────────────────────────────────────
    if "failed_parses" not in inspector.get_table_names():
        _pk = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
        with engine.begin() as connection:
            connection.execute(text(f"""
                CREATE TABLE failed_parses (
                    id {_pk},
                    phone VARCHAR,
                    owner_phone VARCHAR,
                    text TEXT,
                    resolved_by VARCHAR,
                    llm_reply TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))

    # ── Verified supplier directory tables ──────────────────────────────────
    _pk_str = "VARCHAR PRIMARY KEY"
    _bool_f = "BOOLEAN DEFAULT FALSE" if engine.dialect.name == "postgresql" else "INTEGER DEFAULT 0"
    _now    = "DEFAULT NOW()" if engine.dialect.name == "postgresql" else ""

    if "verified_suppliers" not in existing_tables:
        with engine.begin() as connection:
            connection.execute(text(f"""
                CREATE TABLE verified_suppliers (
                    id               {_pk_str},
                    owner_phone      VARCHAR UNIQUE NOT NULL,
                    supplier_type    VARCHAR NOT NULL,
                    bio              TEXT,
                    states_covered   TEXT DEFAULT '[]',
                    can_deliver      {_bool_f},
                    delivery_notes   TEXT,
                    cac_number       VARCHAR,
                    verification_status VARCHAR DEFAULT 'pending',
                    rejection_reason TEXT,
                    reviewed_at      TIMESTAMP,
                    created_at       TIMESTAMP {_now},
                    updated_at       TIMESTAMP
                )
            """))

    if "verified_supplier_products" not in existing_tables:
        with engine.begin() as connection:
            connection.execute(text(f"""
                CREATE TABLE verified_supplier_products (
                    id              {_pk_str},
                    supplier_id     VARCHAR NOT NULL,
                    product_name    VARCHAR NOT NULL,
                    category        VARCHAR,
                    available_sizes TEXT DEFAULT '[]',
                    min_order_qty   REAL,
                    min_order_unit  VARCHAR,
                    price_range     VARCHAR,
                    quality_notes   TEXT
                )
            """))

    if "supplier_contact_messages" not in existing_tables:
        with engine.begin() as connection:
            connection.execute(text(f"""
                CREATE TABLE supplier_contact_messages (
                    id                 {_pk_str},
                    supplier_id        VARCHAR NOT NULL,
                    from_phone         VARCHAR NOT NULL,
                    from_business_name VARCHAR,
                    product_interest   VARCHAR,
                    message            TEXT NOT NULL,
                    status             VARCHAR DEFAULT 'unread',
                    created_at         TIMESTAMP {_now}
                )
            """))

    if "opportunities" not in existing_tables:
        with engine.begin() as connection:
            connection.execute(text(f"""
                CREATE TABLE opportunities (
                    id           {_pk_str},
                    title        VARCHAR NOT NULL,
                    partner_name VARCHAR,
                    category     VARCHAR,
                    description  TEXT NOT NULL,
                    link_url     VARCHAR,
                    is_active    {_bool_f.replace('FALSE','TRUE').replace('0','1')},
                    created_at   TIMESTAMP {_now}
                )
            """))

    # ── Supplier ratings ────────────────────────────────────────────────────
    if "supplier_ratings" not in existing_tables:
        with engine.begin() as connection:
            connection.execute(text(f"""
                CREATE TABLE supplier_ratings (
                    id                 {_pk_str},
                    supplier_id        VARCHAR NOT NULL,
                    from_phone         VARCHAR NOT NULL,
                    from_business_name VARCHAR,
                    rating             INTEGER NOT NULL,
                    review             TEXT,
                    created_at         TIMESTAMP {_now}
                )
            """))

    # ── Opportunity applications ─────────────────────────────────────────────
    if "opportunity_applications" not in existing_tables:
        with engine.begin() as connection:
            connection.execute(text(f"""
                CREATE TABLE opportunity_applications (
                    id               {_pk_str},
                    opportunity_id   VARCHAR NOT NULL,
                    applicant_phone  VARCHAR NOT NULL,
                    applicant_name   VARCHAR,
                    applicant_email  VARCHAR,
                    answers          TEXT DEFAULT '{{}}',
                    status           VARCHAR DEFAULT 'submitted',
                    admin_notes      TEXT,
                    created_at       TIMESTAMP {_now},
                    updated_at       TIMESTAMP
                )
            """))

    # ── application_fields column on opportunities ───────────────────────────
    opp_columns = {col["name"] for col in inspector.get_columns("opportunities")} \
        if "opportunities" in existing_tables else set()
    if "application_fields" not in opp_columns and "opportunities" in existing_tables:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE opportunities ADD COLUMN application_fields TEXT DEFAULT '[]'"))

    # ── transaction_items columns ────────────────────────────────────────────
    # 'unit' and other columns were added to the model after some databases
    # were already created. create_all does not ALTER existing tables, so we
    # do it here explicitly.
    if "transaction_items" in inspector.get_table_names():
        tx_item_columns = {col["name"] for col in inspector.get_columns("transaction_items")}
        tx_item_updates = {
            "unit": "VARCHAR",
            "branch_id": "INTEGER",
            "attributes_json": "VARCHAR",
        }
        with engine.begin() as connection:
            for col, typ in tx_item_updates.items():
                if col not in tx_item_columns:
                    connection.execute(text(
                        f"ALTER TABLE transaction_items ADD COLUMN {col} {typ}"
                    ))

    # ── Filling-station operations tables (fuel businesses) ──────────────────
    _pk = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    _bool_true = "BOOLEAN DEFAULT TRUE" if engine.dialect.name == "postgresql" else "INTEGER DEFAULT 1"
    _fuel_tables = {
        "fuel_tanks": f"""
            CREATE TABLE fuel_tanks (
                id {_pk},
                owner_phone VARCHAR,
                branch_id INTEGER,
                name VARCHAR,
                product VARCHAR,
                capacity_litres REAL DEFAULT 0,
                current_level_litres REAL DEFAULT 0,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
        """,
        "fuel_pumps": f"""
            CREATE TABLE fuel_pumps (
                id {_pk},
                owner_phone VARCHAR,
                branch_id INTEGER,
                name VARCHAR,
                tank_id INTEGER,
                product VARCHAR,
                current_meter REAL DEFAULT 0,
                is_active {_bool_true},
                created_at TIMESTAMP
            )
        """,
        "fuel_prices": f"""
            CREATE TABLE fuel_prices (
                id {_pk},
                owner_phone VARCHAR,
                branch_id INTEGER,
                product VARCHAR,
                price_per_litre INTEGER,
                updated_by_id VARCHAR,
                updated_at TIMESTAMP
            )
        """,
        "fuel_deliveries": f"""
            CREATE TABLE fuel_deliveries (
                id {_pk},
                owner_phone VARCHAR,
                branch_id INTEGER,
                tank_id INTEGER,
                product VARCHAR,
                litres REAL,
                cost_per_litre INTEGER,
                supplier VARCHAR,
                waybill VARCHAR,
                delivered_at TIMESTAMP,
                recorded_by_id VARCHAR,
                created_at TIMESTAMP
            )
        """,
        "fuel_shifts": f"""
            CREATE TABLE fuel_shifts (
                id {_pk},
                owner_phone VARCHAR,
                branch_id INTEGER,
                pump_id INTEGER,
                product VARCHAR,
                attendant_id VARCHAR,
                attendant_name VARCHAR,
                shift_label VARCHAR,
                opening_meter REAL,
                closing_meter REAL,
                price_per_litre INTEGER,
                litres_sold REAL DEFAULT 0,
                expected_amount INTEGER DEFAULT 0,
                cash_amount INTEGER DEFAULT 0,
                pos_amount INTEGER DEFAULT 0,
                transfer_amount INTEGER DEFAULT 0,
                credit_amount INTEGER DEFAULT 0,
                shortfall INTEGER DEFAULT 0,
                status VARCHAR DEFAULT 'open',
                opened_at TIMESTAMP,
                closed_at TIMESTAMP,
                recorded_by_id VARCHAR
            )
        """,
        "fuel_dips": f"""
            CREATE TABLE fuel_dips (
                id {_pk},
                owner_phone VARCHAR,
                branch_id INTEGER,
                tank_id INTEGER,
                dipped_litres REAL,
                computed_litres REAL,
                variance_litres REAL,
                note VARCHAR,
                dipped_at TIMESTAMP,
                recorded_by_id VARCHAR
            )
        """,
    }
    _existing_tables = set(inspector.get_table_names())
    for _tname, _ddl in _fuel_tables.items():
        if _tname not in _existing_tables:
            with engine.begin() as connection:
                connection.execute(text(_ddl))

    # ── phone on suppliers (so receipts can be sent to a supplier) ───────────
    if "suppliers" in inspector.get_table_names():
        _sup_cols = {c["name"] for c in inspector.get_columns("suppliers")}
        if "phone" not in _sup_cols:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE suppliers ADD COLUMN phone VARCHAR"))

    # ── connection_status on supplier_contact_messages (handshake state) ─────
    # Enquiries move forwarded → accepted/declined/blocked. Contacts are only
    # revealed (and rating unlocked) once a supplier accepts.
    if "supplier_contact_messages" in inspector.get_table_names():
        _scm_cols = {c["name"] for c in inspector.get_columns("supplier_contact_messages")}
        if "connection_status" not in _scm_cols:
            with engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE supplier_contact_messages "
                    "ADD COLUMN connection_status VARCHAR DEFAULT 'forwarded'"
                ))

    # ── billing_period on subscription_payments (monthly vs yearly) ──────────
    if "subscription_payments" in inspector.get_table_names():
        _sp_cols = {c["name"] for c in inspector.get_columns("subscription_payments")}
        if "billing_period" not in _sp_cols:
            with engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE subscription_payments "
                    "ADD COLUMN billing_period VARCHAR DEFAULT 'MONTHLY'"
                ))

    # ── One-time grandfather: existing PRO subscribers → PREMIUM ─────────────
    # The plan ladder gained a 4th tier (Premium). Today's PRO capabilities
    # (unlimited branches/partners/investors) moved up to PREMIUM, and PRO
    # became a capped tier (1 branch / 1 partner / 1 investor). To honour what
    # current PRO subscribers already paid for, move them to PREMIUM. Runs once,
    # idempotently, and only touches rows still on PRO.
    _PRO_TO_PREMIUM = "grandfather_pro_to_premium_2026_07"
    if not _migration_applied(engine, _PRO_TO_PREMIUM):
        with engine.begin() as connection:
            result = connection.execute(text(
                "UPDATE users SET subscription_plan = 'PREMIUM' "
                "WHERE subscription_plan = 'PRO'"
            ))
        moved = getattr(result, "rowcount", None)
        _mark_migration(engine, _PRO_TO_PREMIUM)
        print(f"[schema] grandfathered {moved} PRO account(s) to PREMIUM", flush=True)

    # Record that this full migration batch completed successfully.
    # The timestamp lets ops confirm exactly when each schema version
    # was applied to production.
    _mark_migration(engine, "baseline_schema_v1")
