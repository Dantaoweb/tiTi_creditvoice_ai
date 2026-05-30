import re


UNIT_ALIASES = {
    "bags": "bag",
    "bag": "bag",
    "cartons": "carton",
    "carton": "carton",
    "crates": "crate",
    "crate": "crate",
    "packs": "pack",
    "pack": "pack",
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
    clean = re.sub(r"\b(each|per\s+unit|per\s+piece)\b", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


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

    product = re.sub(r"^of\s+", "", product).strip()
    product = re.sub(r"\s+", " ", product).strip()
    return product, normalized_unit
