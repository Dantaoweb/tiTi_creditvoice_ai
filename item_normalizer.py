import re


# Maps plural (or alternate) product names to their canonical singular form.
# Keeps the same product unified in inventory regardless of how users type it.
# Only universal equivalences go here — business-specific aliases (eba=garri) go
# in the per-business ProductAlias table.
PRODUCT_CANONICALS = {
    "eggs": "egg",
    "tomatoes": "tomato",
    "onions": "onion",
    "peppers": "pepper",
    "chillies": "chilli",
    "chilies": "chilli",
    "bananas": "banana",
    "oranges": "orange",
    "plantains": "plantain",
    "yams": "yam",
    "potatoes": "potato",
    "mangoes": "mango",
    "mangos": "mango",
    "avocados": "avocado",
    "cucumbers": "cucumber",
    "carrots": "carrot",
    "groundnuts": "groundnut",
    "pineapples": "pineapple",
    "pawpaws": "pawpaw",
    "watermelons": "watermelon",
    "cabbages": "cabbage",
    "melons": "melon",
    "okras": "okra",
    "lemons": "lemon",
    "limes": "lime",
    "garlics": "garlic",
    "gingers": "ginger",
    "soaps": "soap",
    "batteries": "battery",
    "biscuits": "biscuit",
    "brooms": "broom",
    "mops": "mop",
    "buckets": "bucket",
    # Common misspellings / alternate spellings
    "maggie": "maggi",
    "maggies": "maggi",
    "indomee": "indomie",
    "nescafe": "nescafé",
}

UNIT_ALIASES = {
    "bags": "bag",
    "bag": "bag",
    "cartons": "carton",
    "carton": "carton",
    "crates": "crate",
    "crate": "crate",
    "packs": "pack",
    "pack": "pack",
    "packets": "pack",
    "packet": "pack",
    "boxes": "box",
    "box": "box",
    "tins": "tin",
    "tin": "tin",
    "jars": "jar",
    "jar": "jar",
    "strips": "strip",
    "strip": "strip",
    "tablets": "tablet",
    "tablet": "tablet",
    "capsules": "capsule",
    "capsule": "capsule",
    "sheets": "sheet",
    "sheet": "sheet",
    "cups": "cup",
    "cup": "cup",
    "buckets": "bucket",
    "bucket": "bucket",
    "sets": "set",
    "set": "set",
    "pairs": "pair",
    "pair": "pair",
    "bundles": "bundle",
    "bundle": "bundle",
    "wraps": "wrap",
    "wrap": "wrap",
    "plates": "plate",
    "plate": "plate",
    "pieces": "piece",
    "piece": "piece",
    "each": "piece",
    "bottles": "bottle",
    "bottle": "bottle",
    "sachets": "sachet",
    "sachet": "sachet",
    "units": "unit",
    "unit": "unit",
    "loads": "load",
    "load": "load",
    "truck loads": "truck load",
    "truck load": "truck load",
    "trucks": "truck",
    "truck": "truck",
    "tons": "ton",
    "ton": "ton",
    "litres": "litre",
    "litre": "litre",
    "liters": "litre",
    "liter": "litre",
    "dozens": "dozen",
    "dozen": "dozen",
    "rolls": "roll",
    "roll": "roll",
    "congos": "congo",
    "congo": "congo",
    "baskets": "basket",
    "basket": "basket",
    "trays": "tray",
    "tray": "tray",
    "creates": "crate",   # common typo for "crates"
    "trips": "trip",
    "trip": "trip",
    "tonnes": "tonne",
    "tonne": "tonne",
    "carats": "carat",
    "carat": "carat",
    "ounces": "ounce",
    "ounce": "ounce",
    "oz": "ounce",
    "cylinders": "cylinder",
    "cylinder": "cylinder",
    "drums": "drum",
    "drum": "drum",
    "slabs": "slab",
    "slab": "slab",
    "sqm": "sqm",
    "grams": "gram",
    "gram": "gram",
    "kg": "kg",
    "g": "g",
    "ml": "ml",
    "l": "l",
}

UNIT_PATTERN = "|".join(
    re.escape(unit)
    for unit in sorted(UNIT_ALIASES, key=len, reverse=True)
)

# Ordered list of unit strings (longest first) for greedy matching in parser.
# "each" excluded — parser strips it as a price modifier, not a container unit.
UNIT_PHRASES = sorted(
    (u for u in UNIT_ALIASES if u != "each"),
    key=len,
    reverse=True,
)


def normalize_unit(unit):
    if not unit:
        return None
    clean = re.sub(r"\s+", " ", str(unit).lower().strip())
    return UNIT_ALIASES.get(clean, clean)


def clean_product_name(product):
    clean = str(product or "").lower().strip()
    clean = re.sub(r"[,.;:]+$", "", clean)
    clean = re.sub(r"\b(each|per\s+unit|per\s+piece|per\s+kg|per\s+gram|per\s+tonne|per\s+ton|per\s+litre|per\s+liter|per\s+ounce|per\s+oz|per\s+carat)\b", "", clean)
    # Strip leading article "a"/"an" — "a bag of feed" → "bag of feed"
    clean = re.sub(r"^an?\s+", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def normalize_product_canonical(product):
    """Return canonical singular form for known plural/variant product names."""
    if not product:
        return product
    return PRODUCT_CANONICALS.get(product.lower(), product)


def normalize_item(product, unit=None):
    product = clean_product_name(product)
    normalized_unit = normalize_unit(unit)

    if not product:
        return product, normalized_unit

    unit_match = re.match(
        rf"^(?P<unit>{UNIT_PATTERN})(?:\s+of)?\s+(?P<product>.+)$",
        product,
    )
    if unit_match:
        detected_unit = normalize_unit(unit_match.group("unit"))
        if not normalized_unit:
            normalized_unit = detected_unit
        product = unit_match.group("product").strip()
    elif not normalized_unit:
        # Also recognise trailing unit: "honey liter" -> product="honey", unit="litre"
        suffix_match = re.match(
            rf"^(?P<product>.+?)\s+(?P<unit>{UNIT_PATTERN})$",
            product,
        )
        if suffix_match:
            normalized_unit = normalize_unit(suffix_match.group("unit"))
            product = suffix_match.group("product").strip()

    product = re.sub(r"^of\s+", "", product).strip()
    product = re.sub(r"\s+", " ", product).strip()
    product = normalize_product_canonical(product)
    return product, normalized_unit
