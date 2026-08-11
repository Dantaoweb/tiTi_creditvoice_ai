"""
Bought-vs-Sold trading report PDF (business-wide).

For a commodity buyer: who supplied what and how much (the bought side, per
supplier), what was sold and for how much (the sold side, per product), and the
reconciliation between them over a period. Reuses the StatementPDF toolkit from
loan_statement.py so it sits in the same family as the loan + supplier
statements.
"""
from __future__ import annotations

import hashlib
from datetime import datetime

from loan_statement import (
    StatementPDF, _header_block, _section_title, _kv_row, _table_header,
    _table_row, _fmt, M,
)


def generate_bought_vs_sold(
    owner: dict,
    summary: dict,
    by_supplier: list[dict],
    by_product: list[dict],
    period_label: str,
) -> bytes:
    """
    owner:   {name, phone, business_type_label, business_category}
    summary: {total_spend, total_paid_suppliers, owed_suppliers,
              total_revenue, trading_margin}
    by_supplier: [{supplier, product, qty, unit, spend, owed}]
    by_product:  [{product, qty_bought, spend, qty_sold, revenue, margin}]
    """
    ref = "BVS-" + hashlib.sha1(
        f"{owner.get('phone')}{period_label}{datetime.now().date()}".encode()
    ).hexdigest()[:8].upper()

    pdf = StatementPDF("P", "mm", "A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(M, 12, M)
    pdf.add_page()

    _header_block(pdf, owner, period_label, ref, doc_title="BOUGHT vs SOLD REPORT")

    # ── Trading summary ───────────────────────────────────────────────────────
    _section_title(pdf, "TRADING SUMMARY")
    pdf.ln(1)
    _kv_row(pdf, "Total Purchased (spend)",     _fmt(summary.get("total_spend", 0)))
    _kv_row(pdf, "Paid to Suppliers",           _fmt(summary.get("total_paid_suppliers", 0)))
    _kv_row(pdf, "Still Owed to Suppliers",     _fmt(summary.get("owed_suppliers", 0)))
    _kv_row(pdf, "Total Sales Revenue",         _fmt(summary.get("total_revenue", 0)))
    _kv_row(pdf, "Trading Margin (Revenue - Spend)", _fmt(summary.get("trading_margin", 0)), highlight=True)
    pdf.ln(4)

    # ── Who supplied what ─────────────────────────────────────────────────────
    if by_supplier:
        _section_title(pdf, f"SUPPLIES BY SUPPLIER  ({len(by_supplier)} line{'s' if len(by_supplier) != 1 else ''})")
        pdf.ln(1)
        cols = [
            ("Supplier",  0.28, "L"),
            ("Product",   0.24, "L"),
            ("Qty",       0.14, "R"),
            ("Spend",     0.17, "R"),
            ("Owed",      0.17, "R"),
        ]
        _table_header(pdf, cols)
        for i, s in enumerate(by_supplier):
            qty = s.get("qty") or 0
            unit = f" {s.get('unit')}" if s.get("unit") else ""
            _table_row(pdf, [
                (f"  {(s.get('supplier') or '-')[:22]}", 0.28, "L"),
                (f"{(s.get('product') or '-')[:20]}",    0.24, "L"),
                (f"{qty:,}{unit}",                        0.14, "R"),
                (f"{(s.get('spend') or 0):,}",           0.17, "R"),
                (f"{(s.get('owed') or 0):,}",            0.17, "R"),
            ], striped=(i % 2 == 1))
        pdf.ln(4)

    # ── Bought vs sold, per product ───────────────────────────────────────────
    if by_product:
        _section_title(pdf, "BOUGHT vs SOLD  (by product)")
        pdf.ln(1)
        cols = [
            ("Product",     0.24, "L"),
            ("Bought Qty",  0.14, "R"),
            ("Spend",       0.17, "R"),
            ("Sold Qty",    0.13, "R"),
            ("Revenue",     0.16, "R"),
            ("Margin",      0.16, "R"),
        ]
        _table_header(pdf, cols)
        for i, p in enumerate(by_product):
            _table_row(pdf, [
                (f"  {(p.get('product') or '-')[:20]}", 0.24, "L"),
                (f"{(p.get('qty_bought') or 0):,}",     0.14, "R"),
                (f"{(p.get('spend') or 0):,}",          0.17, "R"),
                (f"{(p.get('qty_sold') or 0):,}",       0.13, "R"),
                (f"{(p.get('revenue') or 0):,}",        0.16, "R"),
                (f"{(p.get('margin') or 0):,}",         0.16, "R"),
            ], striped=(i % 2 == 1))
        pdf.ln(4)

    out = pdf.output()
    return bytes(out)
