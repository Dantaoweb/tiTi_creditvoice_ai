"""
What a barcode says about the packet it is printed on.

A barcode cannot prove a product is genuine — a counterfeiter copies the real
code exactly — so nothing here claims to. It catches the careless cases and
offers a name for a code the shop has never seen:

  • valid      — every retail code (EAN-13, UPC-A) ends in a check digit
                 computed from the others. One that does not add up was made
                 up or misprinted. The shop's own labels have no check digit
                 and are never judged.
  • suggestion — what the code is known as: first by other CreditVoice shops
                 (product NAME only, and only once two or more businesses
                 agree, so one shop's typo or private label never spreads),
                 then by Open Food Facts, a free public product database.
  • mismatch   — the code is known as something clearly different from the
                 product it is being attached to; fake packaging often carries
                 whatever barcode was to hand.

Open Food Facts answers are cached (a miss too), so a code is fetched at most
once a month and a scan never waits on the internet twice.
"""
import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import timedelta

from sqlalchemy import func

from models import BarcodeLookup, InventoryItem, utcnow

_log = logging.getLogger(__name__)

CROWD_MIN_SHOPS = 2
CACHE_DAYS = 30
OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json?fields=product_name,brands,quantity"
OFF_TIMEOUT = 4
USER_AGENT = "CreditVoice/1.0 (support@creditvoiceai.com)"

# Words that say nothing about which product it is.
_NOISE = {
    "the", "and", "with", "pack", "pcs", "piece", "pieces", "tin", "can", "bottle", "sachet",
    "carton", "bag", "box", "packet", "small", "big", "large", "medium", "mini", "new",
    "original", "nigeria", "ltd", "plc", "brand",
}


# ── Check digit ─────────────────────────────────────────────────────────────

def check_digit_ok(code):
    """True/False for a 12- or 13-digit retail code; None for anything else
    (a shop's own label, an 8-digit code that may be EAN-8 or UPC-E)."""
    code = (code or "").strip()
    if not code.isdigit() or len(code) not in (12, 13):
        return None
    digits = [int(c) for c in code]
    body, check = digits[:-1], digits[-1]
    # Weights 3,1,3,1… from the digit next to the check digit, leftwards.
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


# ── Names ───────────────────────────────────────────────────────────────────

def _words(name):
    return {w for w in re.findall(r"[a-z0-9]+", (name or "").lower())
            if len(w) >= 3 and w not in _NOISE and not re.fullmatch(r"\d+(g|kg|ml|cl|l|ltr)?", w)}


def names_differ(a, b):
    """Clearly different products: no meaningful word in common."""
    wa, wb = _words(a), _words(b)
    return bool(wa) and bool(wb) and not (wa & wb)


def _crowd_name(db, code, owner_phone):
    """The name most other businesses use for this code, if enough agree."""
    rows = (
        db.query(func.lower(InventoryItem.name), func.count(func.distinct(InventoryItem.owner_phone)))
        .filter(InventoryItem.barcode == code, InventoryItem.owner_phone != owner_phone)
        .group_by(func.lower(InventoryItem.name))
        .all()
    )
    rows = [(n, c) for n, c in rows if n and c >= CROWD_MIN_SHOPS]
    if not rows:
        return None
    name, shops = max(rows, key=lambda r: r[1])
    return {"name": name.title(), "source": "shops", "shops": shops}


def _fetch_off(code):
    """Open Food Facts: (name or None). Raises on network trouble."""
    if os.getenv("BARCODE_LOOKUP", "on").lower() == "off":
        raise RuntimeError("public lookups are switched off")
    req = urllib.request.Request(OFF_URL.format(code=code), headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=OFF_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:          # they don't have it: a miss, not an outage
            return None
        raise
    if data.get("status") != 1:
        return None
    p = data.get("product") or {}
    name = (p.get("product_name") or "").strip()
    if not name:
        return None
    brand = (p.get("brands") or "").split(",")[0].strip()
    qty = (p.get("quantity") or "").strip()
    # Add the brand only when the name doesn't already carry it ("Coca-Cola
    # Original", not "COCA-COLA SERVICES SA/NV Coca-Cola Original").
    if brand and not (set(re.findall(r"[a-z0-9]+", brand.lower())) & set(re.findall(r"[a-z0-9]+", name.lower()))):
        name = f"{brand} {name}"
    if qty and qty.lower() not in name.lower():
        name = f"{name} {qty}"
    return name[:120]


def _public_name(db, code):
    """Open Food Facts' name for a retail code, cached."""
    if check_digit_ok(code) is not True:
        return None, False          # only real retail codes are worth asking about
    row = db.query(BarcodeLookup).filter(BarcodeLookup.code == code).first()
    fresh = row and row.fetched_at and row.fetched_at > utcnow() - timedelta(days=CACHE_DAYS)
    if not fresh:
        try:
            name = _fetch_off(code)
        except Exception as exc:
            _log.info("Open Food Facts lookup failed for %s: %s", code, exc)
            return (row.name if row else None), bool(row)
        if row is None:
            row = BarcodeLookup(code=code)
            db.add(row)
        row.name = name
        row.source = "openfoodfacts"
        row.fetched_at = utcnow()
        db.commit()
    return row.name, True


# ── What the screen gets ────────────────────────────────────────────────────

def insight(db, owner_phone, code, product_name=None):
    """Everything the till or the stock form shows about a code."""
    code = (code or "").strip()
    valid = check_digit_ok(code)
    suggestion = _crowd_name(db, code, owner_phone)
    looked_up = False
    if not suggestion:
        name, looked_up = _public_name(db, code)
        if name:
            suggestion = {"name": name, "source": "openfoodfacts"}

    warnings = []
    from fake_reports import confirmed_reports_for
    reported = confirmed_reports_for(db, code)
    if reported:
        warnings.append({
            "kind": "reported",
            "text": f"Shops have reported suspected fakes carrying this barcode "
                    f"({reported} confirmed by CreditVoice). Check the packet carefully "
                    "and where it came from.",
        })
    if valid is False:
        warnings.append({
            "kind": "invalid",
            "text": "This barcode doesn't add up — it may be fake or misprinted packaging. Check the packet.",
        })
    if suggestion and product_name and names_differ(product_name, suggestion["name"]):
        who = ("Other shops" if suggestion["source"] == "shops" else "Public product records")
        warnings.append({
            "kind": "mismatch",
            "text": f"{who} know this barcode as “{suggestion['name']}”, not “{product_name.title()}”. "
                    "Check the packet before you save it.",
        })
    unknown = bool(valid and looked_up and not suggestion)
    return {
        "code": code,
        "valid": valid,
        "suggestion": suggestion,
        "warnings": warnings,
        # A real retail code nobody has recorded: worth a second look, no alarm.
        "unknown": unknown,
    }
