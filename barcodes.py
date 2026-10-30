"""
Selling by scan.

A barcode scanner is a keyboard: it types the digits into whatever field has
focus and presses Enter. So nothing here talks to hardware — the work is making
one code mean exactly one product for a business, and finding it fast enough
that a queue does not notice.

Two rules shape everything:

A code must point at one product only. Two products answering the same scan
means the till charges the wrong price, and nobody notices until stock-take.

And scanning stays optional. Packaged goods carry a manufacturer's code and
scan on day one; rice by the congo and tomatoes by the basket never will. A
shop that scans nothing must be no worse off than it is today.
"""
import re

from models import InventoryItem

# Long enough to be a real code, short enough to reject a mistyped name.
# Covers EAN-8/13, UPC-A, and the shop's own printed labels.
_VALID = re.compile(r"^[0-9A-Za-z\-_.]{4,48}$")


def clean(code):
    """The one form a code is stored and compared in.

    Scanners pad with whitespace and sometimes a trailing newline. And a
    12-digit UPC-A is the same barcode as the 13-digit EAN-13 with a leading
    0: a phone camera reads the 12, a USB scanner or a person often types the
    13. Both become the 13-digit form, so one packet is one code.
    """
    code = (code or "").strip()
    if len(code) == 12 and code.isdigit():
        code = "0" + code
    return code


def forms(code):
    """Every stored form a code may have — codes saved before clean() made
    the 12-digit form 13 are still matched."""
    code = clean(code)
    out = [code] if code else []
    if len(code) == 13 and code.startswith("0") and code.isdigit():
        out.append(code[1:])
    return out


def is_plausible(code):
    return bool(_VALID.match(clean(code)))


def find(db, owner_phone, code, branch_id=None):
    """The product this scan means, or None.

    Matched exactly: a barcode is an identifier, not a search term, and a
    near-match at the till is a wrong price.
    """
    code = clean(code)
    if not code:
        return None
    query = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        InventoryItem.barcode.in_(forms(code)),
        InventoryItem.removed_at.is_(None),
    )
    if branch_id is not None:
        # A branch sells its own stock; the same code in another branch is that
        # branch's product.
        branch_match = query.filter(InventoryItem.branch_id == branch_id).first()
        if branch_match:
            return branch_match
    return query.first()


def assert_free(db, owner_phone, code, item_id=None):
    """Refuse a code already in use, naming the product that has it — the
    cashier needs to know which one, not that something went wrong."""
    code = clean(code)
    if not code:
        return None
    clash = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        InventoryItem.barcode.in_(forms(code)),
        InventoryItem.removed_at.is_(None),
    )
    if item_id is not None:
        clash = clash.filter(InventoryItem.id != item_id)
    found = clash.first()
    if found:
        raise ValueError(f"That barcode is already on {found.name}.")
    return code


def attach(db, owner_phone, item_id, code):
    """Teach a product the code that was just scanned.

    This is how a shop builds its barcode list — at the till, the first time an
    unknown code comes up, rather than in a data-entry session that never
    happens.
    """
    code = clean(code)
    if not is_plausible(code):
        raise ValueError("That does not look like a barcode.")
    item = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        InventoryItem.id == item_id,
    ).first()
    if not item:
        raise ValueError("Product not found.")
    assert_free(db, owner_phone, code, item_id=item.id)
    item.barcode = code
    db.commit()
    return item


# ── The shop's own barcodes ───────────────────────────────────────────────────
# For goods with no barcode (home-made, repacked, loose): an EAN-13 every
# scanner reads, starting with 2 — the range GS1 keeps for in-store use, so it
# can never be a manufacturer's code. Unique within the business only: another
# shop may make the same number for something else, which is why these are
# left out of the "what other shops call it" and fake-report checks.

def ean13_check(body12):
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body12)))
    return str((10 - total % 10) % 10)


def is_instore(code):
    code = clean(code)
    return len(code) == 13 and code.isdigit() and code[0] == "2"


def make_instore(db, owner_phone):
    """A new in-store code no product of this business has."""
    import secrets
    for _ in range(50):
        body = "2" + "".join(secrets.choice("0123456789") for _ in range(11))
        code = body + ean13_check(body)
        if not db.query(InventoryItem.id).filter(InventoryItem.owner_phone == owner_phone,
                                                 InventoryItem.barcode == code).first():
            return code
    raise ValueError("Couldn't make a new barcode — try again.")


def give_barcodes(db, owner_phone, item_ids):
    """Give each listed product (that has none) its own in-store code."""
    items = db.query(InventoryItem).filter(InventoryItem.owner_phone == owner_phone,
                                           InventoryItem.id.in_(list(item_ids))).all()
    done = {}
    for item in items:
        if (item.barcode or "").strip() or (item.category or "") == "service":
            continue
        item.barcode = make_instore(db, owner_phone)
        db.flush()
        done[item.id] = item.barcode
    return done
