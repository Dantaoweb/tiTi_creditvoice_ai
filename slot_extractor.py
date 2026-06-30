"""
Slot-based intent extractor for incomplete transaction messages.

Extracts structured slots {person, tx_type, product, amount} from natural
language text using the business owner's own customer/product data — no LLM.

When all slots are filled the caller can reconstruct a canonical transaction
string and hand it back to parse_message().  When slots are missing the caller
knows exactly what to ask for next.
"""

import json
import re
from dataclasses import dataclass, asdict
from typing import Optional

from sqlalchemy import func
from models import Customer, Transaction, InventoryItem


# ── Transaction type detection ────────────────────────────────────────────────

_PAY_RE = re.compile(
    r"\b(pay|paid|payment|settle[ds]?|clear(?:ed)?|transfer(?:red)?|"
    r"remit(?:ted)?|refund(?:ed)?|repay|repaid|send|sent)\b", re.I
)
_SALE_RE = re.compile(
    r"\b(sell|sold|cash\s+sale|walk.?in|direct\s+sale|anonymous)\b", re.I
)
_BUY_RE = re.compile(
    r"\b(buy|bought|purchase[ds]?|took|take|got|owe[sd]?|owing|borrow(?:ed)?|"
    r"collect(?:ed)?|credit(?:ed)?|charge[ds]?|supply|supplied|"
    r"on\s+credit|buy\s+on\s+credit)\b", re.I
)


def _detect_tx_type(text: str) -> str:
    """Returns 'PAY', 'SALE', or 'BUY' (default)."""
    if _PAY_RE.search(text):
        return "PAY"
    if _SALE_RE.search(text):
        return "SALE"
    if _BUY_RE.search(text):
        return "BUY"
    return "BUY"   # default — most messages are credit sales


# ── Amount extraction ─────────────────────────────────────────────────────────

_AMOUNT_RE = re.compile(r"\b(\d[\d,]*(?:\.\d+)?)\s*([kKmM])?\b")


def _extract_amount(text: str) -> Optional[int]:
    for m in _AMOUNT_RE.finditer(text):
        try:
            val = float(m.group(1).replace(",", ""))
            suffix = (m.group(2) or "").lower()
            if suffix == "k":
                val *= 1_000
            elif suffix == "m":
                val *= 1_000_000
            if val >= 1:
                return int(val)
        except ValueError:
            continue
    return None


# ── Ambiguous product detection ───────────────────────────────────────────────
# Words that are clearly product-category placeholders needing a follow-up.

_VAGUE_WORDS = {
    "fees", "fee", "payment", "money", "cash", "stuff", "things",
    "goods", "item", "items", "something", "service", "services",
    "work", "job", "jobs", "repair", "charge", "charges",
    "transport", "delivery", "supply", "supplies",
}

# Hints per (business_group, vague_word) — specific beats generic
_BIZ_HINTS: dict[tuple, str] = {
    ("school",  "fees"):     "school fees, exam fees, term fees, uniform fees, registration fees",
    ("school",  "fee"):      "school fees, exam fees, registration fees, term fees",
    ("school",  "payment"):  "school fees, exam fees, books, uniform",
    ("school",  "goods"):    "books, stationery, uniform, school bag",
    ("school",  "supply"):   "books, stationery, uniform",
    ("school",  "supplies"): "books, stationery, uniform",
    ("service", "repair"):   "engine repair, brake repair, AC repair, body work, electrical fault",
    ("service", "work"):     "plumbing, electrical, painting, tiling, carpentry",
    ("service", "job"):      "sewing, alteration, embroidery, lace, style",
    ("service", "service"):  "haircut, braiding, weave, relaxer, nails, pedicure",
    ("service", "services"): "haircut, braiding, weave, relaxer, nails, pedicure",
    ("service", "charge"):   "service charge, call-out fee, parts",
    ("service", "delivery"): "delivery, dispatch, logistics",
    ("service", "goods"):    "specify the item(s) or job",
    ("food",    "goods"):    "rice, beans, yam, plantain, drink, protein",
    ("food",    "stuff"):    "specify the food items",
    ("food",    "order"):    "specify the order items",
    ("food",    "service"):  "delivery, table service, take-away",
    ("fee",     "fees"):     "monthly dues, annual dues, levy, fine",
    ("fee",     "fee"):      "registration fee, subscription fee, penalty",
    ("fee",     "dues"):     "monthly dues, annual dues, welfare levy",
    ("fee",     "payment"):  "dues, levy, fine, subscription",
    ("clinic",  "service"):  "consultation, lab test, drugs, dressing, injection",
    ("clinic",  "services"): "consultation, lab test, drugs, admission",
    ("clinic",  "visit"):    "consultation, checkup, dressing, injection",
    ("clinic",  "goods"):    "drugs, consumables, lab kit",
    ("thrift",  "payment"):  "monthly contribution, weekly contribution",
    ("thrift",  "fees"):     "joining fee, management fee, levy",
}

# Generic fallback hints (used when no biz-specific entry matches)
_GENERIC_HINTS: dict[str, str] = {
    "fees":      "specify the type of fees",
    "fee":       "specify the type of fee",
    "repair":    "phone repair, car repair, generator repair, AC repair",
    "work":      "plumbing work, electrical work, painting, carpentry",
    "service":   "specify the type of service",
    "services":  "specify the type of service",
    "transport": "bus fare, delivery, logistics",
    "delivery":  "delivery fee, courier, dispatch",
    "goods":     "specify the item(s)",
    "stuff":     "specify the item(s)",
    "supply":    "specify what was supplied",
    "supplies":  "specify what was supplied",
    "charge":    "service charge, delivery charge, repair charge",
    "charges":   "service charges, delivery charges",
    "job":       "specify the job type",
    "jobs":      "specify the job types",
}

# Business-type-aware question templates
# Keys map to biz_language group names (stock, school, service, fee, food, clinic, thrift)
_BIZ_QUESTIONS: dict[str, dict] = {
    "school": {
        "product_buy":  "What fee for {name}?",
        "product_pay":  "What fee did {name} pay?",
        "amount_buy":   "How much is {name}'s {product}?",
        "amount_pay":   "How much did {name} pay for {product}?",
        "amount_buy_np": "How much is {name}'s fee?",
        "amount_pay_np": "How much did {name} pay?",
    },
    "service": {
        "product_buy":  "What job/service for {name}?",
        "product_pay":  "What did {name} pay for?",
        "amount_buy":   "How much for {name}'s {product}?",
        "amount_pay":   "How much did {name} pay for {product}?",
        "amount_buy_np": "How much for {name}'s job?",
        "amount_pay_np": "How much did {name} pay?",
    },
    "fee": {
        "product_buy":  "What dues/levy for {name}?",
        "product_pay":  "What did {name} pay?",
        "amount_buy":   "How much is {name}'s {product}?",
        "amount_pay":   "How much did {name} pay for {product}?",
        "amount_buy_np": "How much does {name} owe?",
        "amount_pay_np": "How much did {name} pay?",
    },
    "food": {
        "product_buy":  "What did {name} order?",
        "product_pay":  "What did {name} pay for?",
        "amount_buy":   "How much for {name}'s {product}?",
        "amount_pay":   "How much did {name} pay for {product}?",
        "amount_buy_np": "How much is {name}'s order?",
        "amount_pay_np": "How much did {name} pay?",
    },
    "clinic": {
        "product_buy":  "What was {name}'s visit for?",
        "product_pay":  "What did {name} pay for?",
        "amount_buy":   "How much for {name}'s {product}?",
        "amount_pay":   "How much did {name} pay for {product}?",
        "amount_buy_np": "How much is {name}'s bill?",
        "amount_pay_np": "How much did {name} pay?",
    },
    "thrift": {
        "product_buy":  "What contribution/levy for {name}?",
        "product_pay":  "What did {name} pay?",
        "amount_buy":   "How much is {name}'s {product}?",
        "amount_pay":   "How much did {name} contribute?",
        "amount_buy_np": "How much does {name} owe?",
        "amount_pay_np": "How much did {name} contribute?",
    },
    "_default": {
        "product_buy":  "What did {name} buy?",
        "product_pay":  "What did {name} pay for?",
        "amount_buy":   "How much did {name} owe for {product}?",
        "amount_pay":   "How much did {name} pay for {product}?",
        "amount_buy_np": "How much did {name} owe?",
        "amount_pay_np": "How much did {name} pay?",
    },
}


def _get_group(user) -> str:
    if not user:
        return "_default"
    try:
        from business_templates import menu_group_for_user
        return menu_group_for_user(user) or "_default"
    except Exception:
        return "_default"


def _is_vague(product: str) -> bool:
    if not product:
        return False
    return product.strip().lower() in _VAGUE_WORDS


def _hints_for(product: str, user=None) -> str:
    key = product.strip().lower()
    group = _get_group(user)
    biz_hit = _BIZ_HINTS.get((group, key))
    if biz_hit:
        return biz_hit
    return _GENERIC_HINTS.get(key, "")


# ── Customer name extraction from DB ─────────────────────────────────────────

_DROP = {
    "buy", "bought", "pay", "paid", "sell", "sold", "owe", "owes", "owing",
    "fees", "fee", "repair", "work", "goods", "payment", "credit", "cash",
    "today", "this", "that", "my", "me", "please", "kindly", "can", "you",
    "i", "the", "a", "an", "for", "to", "from", "of", "in", "on", "at",
    "with", "and", "or", "is", "was", "has", "have", "had", "will", "would",
    "how", "much", "many", "when", "where", "what", "who", "which", "titi",
    "hello", "hi", "hey", "check", "show", "see", "view", "record", "save",
    "supply", "supplies", "service", "services", "item", "items", "stuff",
    "things", "charge", "charges",
}


def _name_candidates(text: str):
    """Yield 1- and 2-word candidate name strings from the text."""
    words = re.sub(r"[^a-zA-Z\s]", " ", text).split()
    for i, w in enumerate(words):
        if not w or w.lower() in _DROP:
            continue
        yield w
        if i + 1 < len(words):
            nxt = words[i + 1]
            if nxt and nxt.lower() not in _DROP:
                yield f"{w} {nxt}"


def find_customer(db, owner_phone: str, text: str, recorded_by_id=None):
    """
    Return the first Customer whose name is found in text, or None.
    Prefers an exact (case-insensitive) match; falls back to ilike substring.
    """
    seen = set()
    for candidate in _name_candidates(text):
        key = candidate.lower()
        if key in seen or len(key) < 2:
            continue
        seen.add(key)

        q = db.query(Customer).filter(
            Customer.owner_phone == owner_phone,
            Customer.name.ilike(f"%{candidate}%"),
        )
        if recorded_by_id:
            q = (q.join(Transaction, Transaction.customer_id == Customer.id)
                  .filter(Transaction.recorded_by_id == recorded_by_id)
                  .distinct(Customer.id))
        hits = q.all()

        if not hits:
            continue
        # Prefer exact name match
        for h in hits:
            if h.name.lower() == key:
                return h
        # Otherwise return shortest name match (most specific)
        return min(hits, key=lambda h: len(h.name))

    return None


# ── Product extraction ────────────────────────────────────────────────────────

_TX_WORDS = re.compile(
    r"\b(buy|bought|pay|paid|sell|sold|owe[sd]?|owing|borrow(?:ed)?|"
    r"collect(?:ed)?|credit(?:ed)?|supply|supplied|purchase[ds]?|"
    r"took|take|got|record|save|please|kindly|can|you|for|to|from|of|"
    r"in|on|at|with|and|or|is|was|has|have|had|will|would)\b",
    re.I,
)


def _extract_product(text: str, customer_name: Optional[str]) -> Optional[str]:
    """Strip customer name, tx words, and amounts from text; what's left is the product."""
    t = text
    if customer_name:
        t = re.sub(re.escape(customer_name), " ", t, flags=re.I)
    t = _TX_WORDS.sub(" ", t)
    t = re.sub(r"\b\d[\d,]*\s*[kKmM]?\b", " ", t)
    t = re.sub(r"[?!.,;:\"'()\[\]]+", " ", t)
    t = " ".join(t.split()).strip()
    return t if t else None


# ── Slot state ────────────────────────────────────────────────────────────────

@dataclass
class SlotState:
    customer_name: Optional[str]  = None
    customer_id:   Optional[int]  = None
    customer_phone: Optional[str] = None
    tx_type:       str            = "BUY"
    product:       Optional[str]  = None
    amount:        Optional[int]  = None
    # What tiTi needs to ask for next: "product" | "amount" | None (= complete)
    ask_for:       Optional[str]  = None

    @property
    def is_complete(self) -> bool:
        return bool(self.customer_name and self.amount is not None)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, s: str) -> "SlotState":
        try:
            d = json.loads(s or "{}")
            return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})
        except Exception:
            return cls()


# ── Ask-message builder ───────────────────────────────────────────────────────

def build_ask_message(state: SlotState, user=None) -> str:
    name    = state.customer_name or "the customer"
    product = state.product or ""
    group   = _get_group(user)
    q       = _BIZ_QUESTIONS.get(group) or _BIZ_QUESTIONS["_default"]

    if state.ask_for == "product":
        template = q["product_pay"] if state.tx_type == "PAY" else q["product_buy"]
        base = template.format(name=name, product=product)
        hints = _hints_for(product, user) if product else ""
        if hints:
            base += f"\ne.g. {hints}"
        return base

    if state.ask_for == "amount":
        if product:
            template = q["amount_pay"] if state.tx_type == "PAY" else q["amount_buy"]
            question = template.format(name=name, product=product)
        else:
            template = q["amount_pay_np"] if state.tx_type == "PAY" else q["amount_buy_np"]
            question = template.format(name=name)
        return f"{question}\ne.g. 5000 or 15k"

    return ""   # should not reach here


# ── Canonical text builder (slots → parseable sentence) ──────────────────────

def slots_to_text(state: SlotState) -> Optional[str]:
    """Convert complete slots into a canonical sentence parse_message() can handle."""
    if not state.is_complete:
        return None
    name    = state.customer_name
    product = state.product or "goods"
    amount  = state.amount

    if state.tx_type == "PAY":
        return f"{name} paid {amount}" + (f" for {product}" if state.product else "")
    if state.tx_type == "SALE":
        return f"I sold {product} {amount}"
    return f"{name} bought {product} {amount}"    # BUY default


# ── Main entry point ──────────────────────────────────────────────────────────

def extract_transaction_slots(
    text: str,
    db,
    owner_phone: str,
    recorded_by_id=None,
) -> Optional[SlotState]:
    """
    Try to extract structured transaction slots from a message that the main
    parser could not fully parse.

    Returns a SlotState if a known customer is detected in the text, else None.
    The SlotState.ask_for field tells the caller what question to ask next.
    If ask_for is None the transaction is complete and slots_to_text() can be
    used to build the canonical parseable sentence.
    """
    customer = find_customer(db, owner_phone, text, recorded_by_id)
    if not customer:
        return None   # no known customer found — can't slot-fill

    tx_type  = _detect_tx_type(text)
    amount   = _extract_amount(text)
    product  = _extract_product(text, customer_name=customer.name)

    state = SlotState(
        customer_name  = customer.name,
        customer_id    = customer.id,
        customer_phone = customer.customer_phone,
        tx_type        = tx_type,
        product        = product,
        amount         = amount,
    )

    if state.is_complete:
        state.ask_for = None
        return state

    # Determine what to ask for next.
    # If the product exists but is vague (single generic word), ask to clarify
    # the product BEFORE asking for amount.
    if product and _is_vague(product):
        state.ask_for = "product"
    elif not product:
        state.ask_for = "product"
    else:
        state.ask_for = "amount"

    return state
