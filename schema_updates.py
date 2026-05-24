from sqlalchemy import inspect, text


def repair_empty_sqlite_integer_id_tables(engine):
    if engine.dialect.name != "sqlite":
        return

    from models import Customer, PendingAction, ReminderMemory, Transaction, User

    models_to_repair = [
        User,
        Customer,
        Transaction,
        PendingAction,
        ReminderMemory,
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
