from sqlalchemy import inspect, text


def repair_empty_sqlite_integer_id_tables(engine):
    if engine.dialect.name != "sqlite":
        return

    from models import Customer, CustomerMemory, PendingAction, ReminderMemory, Transaction, User

    models_to_repair = [
        User,
        Customer,
        Transaction,
        PendingAction,
        ReminderMemory,
        CustomerMemory,
    ]
    inspector = inspect(engine)

    for model in models_to_repair:
        table_name = model.__tablename__
        if table_name not in inspector.get_table_names():
            continue

        id_column = next(
            (
                column
                for column in inspector.get_columns(table_name)
                if column["name"] == "id"
            ),
            None,
        )
        if not id_column or str(id_column["type"]).upper().startswith("INTEGER"):
            continue

        with engine.begin() as connection:
            row_count = connection.execute(
                text(f"SELECT COUNT(*) FROM {table_name}")
            ).scalar()
            if row_count:
                continue

            connection.execute(text(f"DROP TABLE {table_name}"))
            model.__table__.create(bind=connection)


def ensure_schema_updates(engine):
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
    }
    with engine.begin() as connection:
        for column_name, column_type in inventory_updates.items():
            if column_name not in inventory_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE inventory_items ADD COLUMN {column_name} {column_type}"
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
        "is_voided": f"BOOLEAN DEFAULT {boolean_false}",
        "void_reason": "VARCHAR",
        "voided_by_id": "VARCHAR",
        "voided_at": "TIMESTAMP",
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
