"""
Infer a business's category from what it records — keyword rules first, LLM
fallback when keywords are inconclusive.

Used by the web "get started" flow to suggest a business type so the right
template (price lists, custom stock fields, receipt layout) lights up.
"""
import os

from business_templates import BUSINESS_CATEGORIES

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Distinctive keyword → business_type key. Kept high-signal on purpose: a word
# here should strongly imply that business. Matched as case-insensitive
# substrings against the user's item / sale text.
KEYWORD_TO_TYPE = {
    "car_dealer": [
        "chassis", "engine number", "tokunbo", "toyota", "corolla", "camry",
        "honda", "accord", "lexus", "mercedes", "benz", "sienna", "highlander",
        "suv", "car for sale", "vehicle", "salon car", "pickup",
    ],
    "pharmacy": [
        "paracetamol", "tablet", "tablets", "capsule", "antibiotic", "syrup",
        "injection", "amoxicillin", "drugs", "flagyl", "ibuprofen", "vitamin c",
    ],
    "phone_accessories": [
        "iphone", "charger", "earpiece", "power bank", "screen guard", "pouch",
        "tecno", "infinix", "samsung", "airpod", "phone case", "usb cable",
    ],
    "spare_parts": [
        "brake pad", "clutch", "shock absorber", "bearing", "gasket", "spare part",
        "oil filter", "fan belt", "spark plug", "radiator",
    ],
    "boutique_clothing": [
        "gown", "ankara", "dress", "trouser", "shirt", "shoe", "handbag", "wig",
        "fabric", "senator", "jeans", "sneakers",
    ],
    "provision_store": [
        "indomie", "garri", "sachet", "milo", "peak milk", "spaghetti", "sugar",
        "groundnut oil", "beans", "rice", "seasoning", "provisions",
    ],
    "hardware_store": [
        "cement", "iron rod", "roofing", "plywood", "nails", "paint bucket",
        "tiles", "pop cement", "binding wire", "block",
    ],
    "electronics_shop": [
        "television", "fridge", "freezer", "generator", "blender", "home theatre",
        "washing machine", "microwave", "air conditioner", "standing fan",
    ],
    "cosmetics_shop": [
        "body cream", "lotion", "perfume", "lipstick", "body spray", "foundation",
        "makeup kit", "shea butter", "bleaching",
    ],
    "hair_salon": [
        "haircut", "weavon", "braids", "wig install", "pedicure", "manicure",
        "fixing", "retouch", "wash and set",
    ],
    "restaurant_food": [
        "jollof", "plate of rice", "pounded yam", "egusi", "suya", "amala",
        "fried rice", "pepper soup", "moi moi",
    ],
    "building_materials": [
        "granite", "sharp sand", "gravel", "trip of sand", "quarry dust",
    ],
}

# Some inferred keys aren't first-class business_type entries in the taxonomy;
# map them to the closest real one so we always suggest a valid type.
_ALIAS = {
    "restaurant_food": "restaurant",
}


def _type_meta(type_key):
    """Return (business_type_key, label, category_key) for a type, or (None,)*3."""
    key = _ALIAS.get(type_key, type_key)
    for cat in BUSINESS_CATEGORIES:
        for tkey, label in cat["businesses"]:
            if tkey == key:
                return key, label, cat["key"]
    return None, None, None


def _keyword_guess(text):
    t = (text or "").lower()
    scores = {}
    for type_key, words in KEYWORD_TO_TYPE.items():
        hits = sum(1 for w in words if w in t)
        if hits:
            scores[type_key] = hits
    if not scores:
        return None
    best = max(scores, key=scores.get)
    return best


def _valid_type_keys():
    keys = set()
    for cat in BUSINESS_CATEGORIES:
        for tkey, _label in cat["businesses"]:
            keys.add(tkey)
    return keys


def _llm_guess(text):
    """Ask the model to pick one business_type key from the taxonomy, or NONE."""
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        # Compact catalogue of key: label pairs (skip the "other_*" catch-alls).
        pairs = []
        for cat in BUSINESS_CATEGORIES:
            for tkey, label in cat["businesses"]:
                if tkey.startswith("other_"):
                    continue
                pairs.append(f"{tkey} = {label}")
        catalogue = "\n".join(pairs)
        system = (
            "You classify a small Nigerian business into ONE type from a fixed "
            "list, using the products/services they record. Reply with ONLY the "
            "type key (left of '='), exactly as written, or the single word NONE "
            "if unsure. No other text."
        )
        msg = f"Types:\n{catalogue}\n\nThey record:\n{text[:1500]}\n\nType key:"
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=16,
            system=system,
            messages=[{"role": "user", "content": msg}],
        )
        out = (resp.content[0].text or "").strip().split()[0] if resp.content else ""
        out = out.strip().strip(".").lower()
        if out and out != "none" and out in _valid_type_keys():
            return out
        return None
    except Exception as e:
        print(f"[business_inference] LLM error: {e}", flush=True)
        return None


def gather_signals(db, owner_phone, limit=40):
    """Item names + recent sale-line product names the business has recorded."""
    from models import InventoryItem, TransactionItem, Transaction, Customer
    signals = []
    names = (
        db.query(InventoryItem.name)
        .filter(InventoryItem.owner_phone == owner_phone)
        .limit(limit).all()
    )
    signals.extend(n[0] for n in names if n[0])
    # Sale-line products (skip the generic "POS Sale (n items)" summary rows).
    lines = (
        db.query(TransactionItem.product)
        .join(Transaction, TransactionItem.transaction_id == Transaction.id)
        .join(Customer, Transaction.customer_id == Customer.id)
        .filter(Customer.owner_phone == owner_phone)
        .limit(limit).all()
    )
    signals.extend(l[0] for l in lines if l[0])
    # De-dup preserving order.
    seen, out = set(), []
    for s in signals:
        k = s.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(s.strip())
    return out


def suggest_business_type(db, owner_phone, min_signals=3):
    """Suggest a business type from what the owner records, or None.

    Keyword rules first; LLM fallback only when keywords are inconclusive.
    Returns {"type", "label", "category", "reason"} or None."""
    signals = gather_signals(db, owner_phone)
    if len(signals) < min_signals:
        return None
    text = " ; ".join(signals)
    guess = _keyword_guess(text) or _llm_guess(text)
    if not guess:
        return None
    key, label, category = _type_meta(guess)
    if not key:
        return None
    return {
        "type": key,
        "label": label,
        "category": category,
        "reason": "Based on the products you've been recording",
    }
