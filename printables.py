"""
How the business's printables look — receipts, invoices / quotations,
waybills and supplier receipts share one header, laid out the way the owner
chose in Settings → Receipts & printables:

- paper: small thermal printer (80mm, the default), extra small (58mm), or A4;
- logo: on top (centred), left or right of the name, or hidden;
- text centred or on the left; phone / address / email shown or not;
- bank details (Profile) on invoices and quotations, and on receipts if
  switched on — never on waybills (no prices or money on them);
- the receipt's title and closing line in the owner's own words.
"""
import json
import re

from app_settings import get_business_settings

PRINT_KINDS = ("receipt", "invoice", "waybill", "supplier")
MAX_BANK_ACCOUNTS = 2


def bank_accounts(owner):
    try:
        rows = json.loads(getattr(owner, "bank_accounts_json", None) or "[]")
    except (TypeError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("number")][:MAX_BANK_ACCOUNTS]


def clean_bank_accounts(rows):
    """[{bank, number, name}] from the Profile form; blank rows are dropped."""
    out = []
    for r in rows or []:
        bank = str((r or {}).get("bank") or "").strip()[:60]
        number = re.sub(r"\s+", "", str((r or {}).get("number") or ""))
        name = str((r or {}).get("name") or "").strip()[:100]
        if not (bank or number or name):
            continue
        if not re.fullmatch(r"\d{6,20}", number):
            raise ValueError("Enter the account number in digits (usually 10).")
        if not bank:
            raise ValueError("Enter the bank's name for each account.")
        out.append({"bank": bank, "number": number, "name": name or None})
    if len(out) > MAX_BANK_ACCOUNTS:
        raise ValueError(f"Up to {MAX_BANK_ACCOUNTS} bank accounts.")
    return out


def clean_business_email(email):
    email = (email or "").strip()[:200]
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("That email address doesn't look right.")
    return email or None


def print_choices(settings):
    return {
        "paper": settings.get("print_paper") or "80mm",
        "logo": settings.get("print_logo") or "top",
        "align": settings.get("print_align") or "center",
        "show_phone": bool(settings.get("print_show_phone", True)),
        "show_address": bool(settings.get("print_show_address", True)),
        "show_email": bool(settings.get("print_show_email", True)),
    }


def print_profile(db, owner, kind):
    """What a printable of this kind adds to its business header."""
    settings = get_business_settings(db, owner.phone) if owner else {}
    show_bank = (kind == "invoice" and settings.get("print_bank_invoices", True)) or \
                (kind == "receipt" and settings.get("print_bank_receipts", False))
    return {
        "biz_email": getattr(owner, "business_email", None) if owner else None,
        "bank_accounts": bank_accounts(owner) if (owner and show_bank) else [],
        "print": print_choices(settings),
    }


def with_own_words(db, owner, cfg):
    """The receipt config with the owner's own title / closing line, if set."""
    if not owner:
        return cfg
    settings = get_business_settings(db, owner.phone)
    title = (settings.get("receipt_title") or "").strip()
    footer = (settings.get("receipt_footer") or "").strip()
    if not (title or footer):
        return cfg
    cfg = dict(cfg or {})
    if title:
        cfg["title"] = title
    if footer:
        cfg["footer"] = footer
    return cfg


def bank_lines_text(accounts):
    """'Pay to: GTBank 0123456789 (Bello Cement)' lines for WhatsApp texts."""
    return [f"Pay to: {a['bank']} {a['number']}" + (f" ({a['name']})" if a.get("name") else "")
            for a in accounts or []]
