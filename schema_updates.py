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
    }
    with engine.begin() as connection:
        for column_name, column_type in inventory_updates.items():
            if column_name not in inventory_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE inventory_items ADD COLUMN {column_name} {column_type}"
                    )
                )

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
    }
    with engine.begin() as connection:
        for column_name, column_type in transaction_updates.items():
            if column_name not in transaction_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE transactions ADD COLUMN {column_name} {column_type}"
                    )
                )

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
        }
        with engine.begin() as connection:
            for col, typ in tx_item_updates.items():
                if col not in tx_item_columns:
                    connection.execute(text(
                        f"ALTER TABLE transaction_items ADD COLUMN {col} {typ}"
                    ))

    # Record that this full migration batch completed successfully.
    # The timestamp lets ops confirm exactly when each schema version
    # was applied to production.
    _mark_migration(engine, "baseline_schema_v1")
