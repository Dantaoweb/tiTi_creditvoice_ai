"""Shared CSV export and signed-token helpers used by web_routes and report_commands."""
import base64
import csv
import hashlib
import hmac
import io
import os
import time

_SECRET = os.getenv("WEB_SECRET_KEY", "cv-web-secret-change-in-production")
_TTL = 24 * 3600


def make_export_token(phone: str, period, export_type: str) -> str:
    exp = int(time.time()) + _TTL
    payload = f"{phone}|{period or ''}|{export_type}|{exp}"
    sig = hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload.encode()).decode() + "." + sig


def verify_export_token(token: str):
    try:
        dot = token.rfind(".")
        if dot == -1:
            return None
        data_b64, sig = token[:dot], token[dot + 1:]
        payload = base64.urlsafe_b64decode(data_b64 + "==").decode()
        expected = hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        parts = payload.split("|")
        if len(parts) != 4:
            return None
        phone, period, export_type, exp = parts
        if int(exp) < time.time():
            return None
        return {"phone": phone, "period": period or None, "type": export_type}
    except Exception:
        return None


def build_export_csv(db, owner_phone: str, period_key, export_type: str):
    """Returns (filename, csv_bytes_utf8bom) for the requested data set."""
    from reports import get_balance, get_owner_transaction_query, get_unpaid_debtors
    from models import Customer, InventoryItem, Transaction, User

    label = (period_key or "all").lower()

    if export_type == "debtors":
        debtors, _ = get_unpaid_debtors(db, owner_phone)
        headers = ["Customer", "Phone", "Balance (NGN)", "Due Date", "Status"]
        rows = []
        for d in sorted(debtors, key=lambda x: x["balance"], reverse=True):
            if d.get("overdue"):
                status = f"Overdue {d['overdue_days']}d"
            elif d.get("due_date"):
                status = d["due_date"].strftime("%d/%m/%Y")
            else:
                status = "No due date"
            rows.append([
                d["name"].title(),
                d.get("customer_phone") or "",
                d["balance"],
                d["due_date"].strftime("%d/%m/%Y") if d.get("due_date") else "",
                status,
            ])
        filename = f"creditvoice-debtors-{label}.csv"

    elif export_type == "stock":
        items = (
            db.query(InventoryItem)
            .filter(InventoryItem.owner_phone == owner_phone, InventoryItem.is_available == True)
            .order_by(InventoryItem.name)
            .all()
        )
        headers = ["Product", "Unit", "Stock Qty", "Cost Price (NGN)", "Selling Price (NGN)", "Low Stock Alert"]
        rows = [
            [
                i.name.title(), i.unit or "", i.quantity or 0,
                int(i.cost_price or 0), int(i.selling_price or 0),
                i.low_stock_alert if i.low_stock_alert is not None else "",
            ]
            for i in items
        ]
        filename = f"creditvoice-stock-{label}.csv"

    elif export_type == "customers":
        customers = (
            db.query(Customer)
            .filter(Customer.owner_phone == owner_phone)
            .order_by(Customer.name)
            .all()
        )
        headers = ["Customer", "Phone", "Balance (NGN)", "Since"]
        rows = [
            [
                c.name.title(),
                c.customer_phone or "",
                int(get_balance(db, c.id)),
                c.created_at.strftime("%d/%m/%Y") if c.created_at else "",
            ]
            for c in customers
        ]
        filename = f"creditvoice-customers-{label}.csv"

    else:  # transactions (default)
        query = get_owner_transaction_query(db, owner_phone, period_key, include_voided=True)
        txs = query.order_by(Transaction.created_at.desc()).all()

        c_ids = [t.customer_id for t in txs if t.customer_id]
        cmap = (
            {c.id: c for c in db.query(Customer).filter(Customer.id.in_(c_ids)).all()}
            if c_ids else {}
        )
        u_ids = [t.recorded_by_id for t in txs if t.recorded_by_id]
        umap = (
            {u.id: u for u in db.query(User).filter(User.id.in_(u_ids)).all()}
            if u_ids else {}
        )

        headers = ["#", "Type", "Customer", "Product", "Qty", "Unit",
                   "Amount (NGN)", "Recorded By", "Date", "Voided"]
        rows = [
            [
                tx.id, tx.type,
                cmap[tx.customer_id].name.title() if cmap.get(tx.customer_id) else "Direct Sale",
                tx.product or "", tx.quantity or "", tx.unit or "",
                int(tx.amount or 0),
                umap[tx.recorded_by_id].name if umap.get(tx.recorded_by_id) else "",
                tx.created_at.strftime("%d/%m/%Y %H:%M") if tx.created_at else "",
                "YES" if tx.is_voided else "",
            ]
            for tx in txs
        ]
        filename = f"creditvoice-transactions-{label}.csv"

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    # utf-8-sig = BOM prefix so Excel on Windows opens without garbling
    return filename, buf.getvalue().encode("utf-8-sig")
