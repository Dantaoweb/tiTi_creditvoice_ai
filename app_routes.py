import hmac
import logging
import os
import time
from datetime import datetime, timezone

from fastapi import Request
from fastapi.responses import JSONResponse

from database import engine, SessionLocal

_health_log = logging.getLogger("creditvoice.health")


def register_http_routes(app):
    @app.get("/health")
    def health_check():
        """Render health check — verifies the app and DB are reachable.

        Returns db_latency_ms so degraded DB performance is visible even
        when the DB is technically up.  Also reports scheduler_last_run so
        ops can confirm the proactive scheduler is cycling correctly.
        """
        import proactive_scheduler
        from main import _APP_START

        uptime_s = int(time.monotonic() - _APP_START)

        # Scheduler is considered healthy if it ran within the last 25 hours.
        # The cycle is every 6h; 25h allows one missed cycle before alerting.
        _SCHEDULER_STALE_HOURS = 25
        last_run = proactive_scheduler.last_run_at
        if last_run is None:
            # Not yet run — only flag as stale if the process has been up > 7h
            scheduler_ok = uptime_s < _SCHEDULER_STALE_HOURS * 3600
        else:
            age_h = (datetime.now(timezone.utc) - last_run).total_seconds() / 3600
            scheduler_ok = age_h < _SCHEDULER_STALE_HOURS
            if not scheduler_ok:
                _health_log.warning(
                    "Proactive scheduler last ran %.1fh ago — expected every 6h", age_h
                )

        db = SessionLocal()
        t0 = time.monotonic()
        try:
            db.execute(__import__("sqlalchemy").text("SELECT 1"))
            db_ms = round((time.monotonic() - t0) * 1000, 1)
            return {
                "status": "ok",
                "db": "ok",
                "db_latency_ms": db_ms,
                "uptime_seconds": uptime_s,
                "scheduler_last_run": last_run.isoformat() if last_run else None,
                "scheduler_ok": scheduler_ok,
            }
        except Exception as exc:
            db_ms = round((time.monotonic() - t0) * 1000, 1)
            _health_log.error("DB health check failed: %s", exc)
            return JSONResponse(
                status_code=503,
                content={
                    "status": "error",
                    "db": str(exc),
                    "db_latency_ms": db_ms,
                    "uptime_seconds": uptime_s,
                    "scheduler_ok": scheduler_ok,
                },
            )
        finally:
            db.close()

    @app.get("/debug/schema")
    def debug_schema(token: str):
        expected_token = os.getenv("WEBHOOK_VERIFY_TOKEN", "")
        # Disable entirely if no token configured, or in production without explicit opt-in
        if not expected_token:
            return {"status": "unauthorized"}
        if not hmac.compare_digest(token, expected_token):
            return {"status": "unauthorized"}
        # Only expose schema in non-production environments
        if os.getenv("ENVIRONMENT", "production") == "production":
            return {"status": "not available in production"}

        from sqlalchemy import inspect
        from models import (
            AppAdminRole, Customer, CustomerMemory, InventoryItem,
            InventoryMovement, PendingAction, ProcessedMessage,
            ReminderMemory, SubscriptionPayment, Supplier,
            SupplierPayment, SupplierPurchase, Transaction,
            TransactionItem, TransactionNote, User,
        )

        inspector = inspect(engine)
        models = [
            Customer, User, Transaction, TransactionItem, TransactionNote,
            Supplier, SupplierPurchase, SupplierPayment, InventoryItem,
            InventoryMovement, SubscriptionPayment, AppAdminRole,
            PendingAction, ProcessedMessage, CustomerMemory, ReminderMemory,
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

    @app.get("/webhook")
    def verify_webhook(request: Request):
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")

        verify_token = os.getenv("WEBHOOK_VERIFY_TOKEN", "your_verify_token_here")

        if token == verify_token:
            return int(challenge)

        return {"status": "error"}
