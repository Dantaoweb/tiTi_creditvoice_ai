"""
Is this product already in my stock? — for shops with hundreds of products
and no barcodes, where "Paracetemol", "paracetamol 500 mg" and
"PARACETAMOL 500MG" are the same thing typed three ways.

Names are compared after:
- lower case, punctuation and brackets dropped, "&" read as "and";
- common shop shorthand expanded (g/nut → groundnut, pkt → packet, tabs → tablet);
- plurals folded (bags → bag, tomatoes → tomato);
- numbers glued to their unit ("500 mg" = "500mg");
- spaces ignored for the whole-name check ("ground nut oil" = "groundnut oil");
and small typos forgiven (one or two letters out on a longer word).

Used when adding a product (warn before a twin is made), when searching
(close matches instead of an empty list), by tiTi ("do I have panadol?") and
to list possible duplicates already in the list.
"""
import re
from difflib import SequenceMatcher

from models import InventoryItem, InventoryMovement, User

_SHORTHAND = {
    "g/nut": "groundnut", "g-nut": "groundnut", "gnut": "groundnut",
    "pkt": "packet", "pkts": "packet", "ctn": "carton", "ctns": "carton",
    "btl": "bottle", "btls": "bottle", "tab": "tablet", "tabs": "tablet",
    "syr": "syrup", "veg": "vegetable", "tbsp": "tablespoon", "sach": "sachet",
    "doz": "dozen", "pcs": "piece", "pc": "piece", "ltr": "litre", "ltrs": "litre",
    "liter": "litre", "liters": "litre", "lt": "litre", "kgs": "kg", "grams": "g",
    "gram": "g", "gm": "g", "gms": "g",
}
_STOP = {"of", "the", "a", "an"}


def _deplural(w):
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith(("oes", "ches", "shes", "sses", "xes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def tokens(name):
    s = (name or "").lower().replace("&", " and ")
    for short, full in _SHORTHAND.items():
        if "/" in short or "-" in short:
            s = s.replace(short, f" {full} ")
    s = re.sub(r"(\d)\s+(mg|g|kg|ml|cl|l|litre|cm|mm|m|inch|pcs?)\b", r"\1\2", s)
    words = re.split(r"[^a-z0-9]+", s)
    out = []
    for w in words:
        if not w or w in _STOP:
            continue
        w = _SHORTHAND.get(w, w)
        out.append(_deplural(w))
    return out


def squashed(name):
    return "".join(tokens(name))


def _word_close(a, b):
    """Two words are the same allowing for a slip of the finger."""
    if a == b:
        return True
    if a.isdigit() or b.isdigit() or re.search(r"\d", a + b):
        return a == b                      # 500mg is not 50mg
    shorter, longer = sorted((a, b), key=len)
    if len(shorter) >= 3 and longer.startswith(shorter):
        return True                        # "paracet" … "paracetamol"
    if min(len(a), len(b)) >= 4:
        return SequenceMatcher(None, a, b).ratio() >= 0.8
    return False


def _covered(query_words, name_words):
    """How many of the query's words appear (closely) in the name."""
    return sum(1 for q in query_words if any(_word_close(q, w) for w in name_words))


def search_score(query, name):
    """How well a product name answers what was searched (0–1). Every word
    searched must be there (allowing typos), or the whole thing must read the
    same with spaces ignored."""
    qw, nw = tokens(query), tokens(name)
    if not qw or not nw:
        return 0.0
    if "".join(qw) == "".join(nw):
        return 1.0
    covered = _covered(qw, nw) / len(qw)
    sq = "".join(qw)
    whole = SequenceMatcher(None, sq, "".join(nw)).ratio()
    if sq in "".join(nw) and len(sq) >= 4:
        whole = max(whole, 0.9)
    return max(covered if covered == 1.0 else covered * 0.7, whole if whole >= 0.8 else 0.0)


def same_product_score(a, b):
    """How likely two product names are the same product (0–1), symmetric."""
    aw, bw = tokens(a), tokens(b)
    if not aw or not bw:
        return 0.0
    if "".join(aw) == "".join(bw):
        return 1.0
    # Different sizes / strengths are different products
    nums_a = {w for w in aw if re.search(r"\d", w)}
    nums_b = {w for w in bw if re.search(r"\d", w)}
    if nums_a and nums_b and nums_a != nums_b:
        return 0.0
    both = (_covered(aw, bw) + _covered(bw, aw)) / (len(aw) + len(bw))
    whole = SequenceMatcher(None, "".join(aw), "".join(bw)).ratio()
    return max(both, whole)


def is_exact_twin(a, b):
    return bool(tokens(a)) and "".join(tokens(a)) == "".join(tokens(b))


def _added_info(db, items):
    """{item_id: (first-recorded date, who)} for 'added 12 Mar by Sade'."""
    if not items:
        return {}
    ids = [i.id for i in items]
    first = {}
    for m in (db.query(InventoryMovement).filter(InventoryMovement.item_id.in_(ids))
              .order_by(InventoryMovement.created_at.asc()).all()):
        first.setdefault(m.item_id, m)
    users = {}
    uids = {m.recorded_by_id for m in first.values() if m.recorded_by_id}
    if uids:
        users = {u.id: u for u in db.query(User).filter(User.id.in_(uids)).all()}
    out = {}
    for i in items:
        m = first.get(i.id)
        when = (i.created_at or (m.created_at if m else None))
        who = users.get(m.recorded_by_id).name if m and users.get(m.recorded_by_id) else None
        out[i.id] = (when, who)
    return out


def describe(db, items):
    info = _added_info(db, items)
    rows = []
    for i in items:
        when, who = info.get(i.id, (None, None))
        rows.append({
            "id": i.id, "name": (i.name or "").title(), "unit": i.unit,
            "quantity": i.quantity, "is_service": i.quantity is None or i.category == "service",
            "selling_price": i.selling_price,
            "added_at": when.isoformat() if when else None,
            "added_by": (who or "").title() or None,
        })
    return rows


def find_similar(db, owner_phone, name, limit=5, threshold=0.78, mode="search", items=None):
    """Products that may be what `name` means, best first, as (item, score)."""
    if items is None:
        items = db.query(InventoryItem).filter(InventoryItem.owner_phone == owner_phone).all()
    score = search_score if mode == "search" else same_product_score
    scored = [(i, score(name, i.name)) for i in items]
    scored = [(i, s) for i, s in scored if s >= threshold]
    scored.sort(key=lambda p: (-p[1], len(p[0].name or "")))
    return scored[:limit]


_ANY_BRANCH = object()


def check_new_product(db, owner_phone, name, unit=None, branch_id=_ANY_BRANCH, visible=None):
    """Before adding a product: is the exact same one there (same name read
    loosely, same unit — and the same branch, since each branch keeps its own
    stock), and what looks close? `visible` = the products this person may see
    (branch staff: their branch's); defaults to the whole business."""
    items = visible if visible is not None else \
        db.query(InventoryItem).filter(InventoryItem.owner_phone == owner_phone).all()
    unit = (unit or "").strip().lower()
    twins = [i for i in items if is_exact_twin(name, i.name)
             and (branch_id is _ANY_BRANCH or i.branch_id == branch_id)
             and (not unit or not i.unit or i.unit.strip().lower() == unit
                  or _deplural(i.unit.strip().lower()) == _deplural(unit))]
    close = [i for i, _s in find_similar(db, owner_phone, name, limit=6, threshold=0.8,
                                          mode="same", items=items) if i not in twins]
    close += [i for i, _s in find_similar(db, owner_phone, name, limit=6, threshold=0.85,
                                           mode="search", items=items)
              if i not in twins and i not in close]
    return {"exact": describe(db, twins), "similar": describe(db, close[:5])}


def possible_duplicates(db, owner_phone, threshold=0.85, limit=50, items=None):
    """Pairs of products that look like the same thing. Compared within
    buckets (shared first letters of a word) so 600+ products stay quick."""
    if items is None:
        items = db.query(InventoryItem).filter(InventoryItem.owner_phone == owner_phone).all()
    buckets = {}
    for i in items:
        for w in set(tokens(i.name)):
            if len(w) >= 3 and not w.isdigit():
                buckets.setdefault(w[:3], []).append(i)
        sq = squashed(i.name)
        if sq:
            buckets.setdefault("~" + sq[:4], []).append(i)
    seen, pairs = set(), []
    for group in buckets.values():
        if len(group) > 200:                       # a very common word — too broad to mean anything
            continue
        for x in range(len(group)):
            for y in range(x + 1, len(group)):
                a, b = group[x], group[y]
                key = (min(a.id, b.id), max(a.id, b.id))
                if key in seen:
                    continue
                seen.add(key)
                if (a.unit or "").lower() != (b.unit or "").lower() and a.unit and b.unit \
                        and not is_exact_twin(a.name, b.name):
                    continue
                s = same_product_score(a.name, b.name)
                if s >= threshold:
                    pairs.append((s, a, b))
    pairs.sort(key=lambda p: -p[0])
    out = []
    for s, a, b in pairs[:limit]:
        da, db_ = describe(db, [a, b])
        out.append({"score": round(s, 2), "a": da, "b": db_})
    return out
