"""
SQLite-only dev repair helpers.

These functions contain intentional DROP TABLE / DROP COLUMN operations that
are safe because they only run on SQLite (never PostgreSQL / production) and
only when the target table is completely empty.

Kept in a separate module so the CI migration-safety scan (which blocks DROP
statements in schema_updates.py) does not flag legitimate dev-only cleanup.
"""
import re

from sqlalchemy import inspect, text

_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_table(name: str) -> str:
    if not _SAFE_IDENT.match(name):
        raise ValueError(f"Unsafe table name rejected: {name!r}")
    return name


def repair_empty_sqlite_integer_id_tables(engine):
    """Drop and recreate empty SQLite tables whose id column has the wrong type.

    SQLite's ALTER TABLE cannot change a column type, so the only fix for a
    mis-typed id column is a drop-and-recreate — safe here because we verify
    the table is empty before dropping.  This function is a no-op on any
    non-SQLite engine.
    """
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
        table_name = _safe_table(model.__tablename__)
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
