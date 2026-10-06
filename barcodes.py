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
    """Scanners pad with whitespace and sometimes a trailing newline."""
    return (code or "").strip()


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
        InventoryItem.barcode == code,
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
        InventoryItem.barcode == code,
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
