"""
Loyalty on the web (loyalty.py): a customer's stamps / points (the till shows
"Use reward"), and the best customers list.
"""
from fastapi import Depends, HTTPException, Query

from database import SessionLocal
from models import Customer
from web_auth import require_web_auth
from web_common import _scoped_read, _session_owner_phone


def register_loyalty_routes(app):
    from loyalty import best_customers, status

    @app.get("/app/api/loyalty/customer/{customer_id}")
    def web_loyalty_customer(customer_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            if not db.query(Customer).filter(Customer.id == customer_id, Customer.owner_phone == owner_phone).first():
                raise HTTPException(status_code=404, detail="Customer not found.")
            out = status(db, owner_phone, customer_id)
            db.commit()
            return out
        finally:
            db.close()

    @app.get("/app/api/loyalty/best")
    def web_loyalty_best(days: int = Query(default=90, ge=7, le=365), session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            branch, _rec = _scoped_read(db, session)
            out = best_customers(db, _session_owner_phone(db, session), days=days, branch_id=branch)
            db.commit()
            return out
        finally:
            db.close()
