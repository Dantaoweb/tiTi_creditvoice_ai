"""
Per-supplier statement PDF.

Reuses the StatementPDF toolkit from loan_statement.py so it looks like the same
family of documents (same banner, section bars, tables). Given a supplier, a
period, and that period's purchases/payments (see web_supplier_routes
_supplier_window), it renders a supplier account statement: opening balance,
every supply + payment in the period, closing balance, and the current amount
still owed.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from loan_statement import (
    StatementPDF, _header_block, _section_title, _kv_row, _table_header,
    _table_row, _fmt, _short_date, M, ROW, LIGHT,
)


def generate_supplier_statement(
    owner: dict,
    supplier: dict,
    summary: dict,
    purchases: list[dict],
    payments: list[dict],
    period_label: str,
) -> bytes:
    """
    owner:    {name, phone, business_type_label, business_category}
    supplier: {name, phone}
    summary:  {opening_balance, total_bought, total_paid, closing_balance, current_owed}
    purchases:[{created_at, product, quantity, unit, unit_price, total, paid_amount, due_date}]
    payments: [{created_at, amount, note}]
    """
    ref = "SUP-" + hashlib.sha1(
        f"{owner.get('phone')}{supplier.get('name')}{period_label}{datetime.now().date()}".encode()
    ).hexdigest()[:8].upper()

    pdf = StatementPDF("P", "mm", "A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(M, 12, M)
    pdf.add_page()

    _header_block(pdf, owner, period_label, ref, doc_title="SUPPLIER STATEMENT")

    # ── Supplier identity ─────────────────────────────────────────────────────
    _section_title(pdf, "SUPPLIER")
    pdf.ln(1)
    _kv_row(pdf, "Supplier", (supplier.get("name") or "").title())
    _kv_row(pdf, "Phone", supplier.get("phone") or "-")
    pdf.ln(3)

    # ── Account summary ───────────────────────────────────────────────────────
    _section_title(pdf, "ACCOUNT SUMMARY")
    pdf.ln(1)
    _kv_row(pdf, "Opening Balance (owed at start)", _fmt(summary.get("opening_balance", 0)))
    _kv_row(pdf, "Total Purchased (period)",        _fmt(summary.get("total_bought", 0)))
    _kv_row(pdf, "Total Paid (period)",             _fmt(summary.get("total_paid", 0)))
    _kv_row(pdf, "Closing Balance (owed at end)",   _fmt(summary.get("closing_balance", 0)), highlight=True)
    _kv_row(pdf, "Amount Owed Now (all-time)",      _fmt(summary.get("current_owed", 0)), highlight=True)
    pdf.ln(4)

    # ── Purchases ─────────────────────────────────────────────────────────────
    if purchases:
        _section_title(pdf, f"SUPPLIES  ({len(purchases)} record{'s' if len(purchases) != 1 else ''})")
        pdf.ln(1)
        cols = [
            ("Date",       0.15, "C"),
            ("Product",    0.27, "L"),
            ("Qty",        0.12, "R"),
            ("Unit Cost",  0.16, "R"),
            ("Total",      0.16, "R"),
            ("Paid",       0.14, "R"),
        ]
        _table_header(pdf, cols)
        for i, p in enumerate(purchases):
            qty = p.get("quantity") or 0
            unit = f" {p.get('unit')}" if p.get("unit") else ""
            _table_row(pdf, [
                (_short_date(p.get("created_at")),                    0.15, "C"),
                (f"  {(p.get('product') or '-')[:22]}",               0.27, "L"),
                (f"{qty:,}{unit}",                                     0.12, "R"),
                (f"{(p.get('unit_price') or 0):,}",                   0.16, "R"),
                (f"{(p.get('total') or 0):,}",                        0.16, "R"),
                (f"{(p.get('paid_amount') or 0):,}",                  0.14, "R"),
            ], striped=(i % 2 == 1))
        pdf.ln(4)

    # ── Payments ──────────────────────────────────────────────────────────────
    if payments:
        _section_title(pdf, f"PAYMENTS  ({len(payments)} record{'s' if len(payments) != 1 else ''})")
        pdf.ln(1)
        cols = [
            ("Date",   0.20, "C"),
            ("Note",   0.55, "L"),
            ("Amount", 0.25, "R"),
        ]
        _table_header(pdf, cols)
        for i, p in enumerate(payments):
            _table_row(pdf, [
                (_short_date(p.get("created_at")),        0.20, "C"),
                (f"  {(p.get('note') or '-')[:44]}",      0.55, "L"),
                (f"{(p.get('amount') or 0):,}",           0.25, "R"),
            ], striped=(i % 2 == 1))
        pdf.ln(4)

    out = pdf.output()
    return bytes(out)
