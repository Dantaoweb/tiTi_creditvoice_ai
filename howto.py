"""
tiTi's exact answers: one question → the exact steps, in 2–5 lines.

The broad FAQ (faq.py) and app guides (messages.py) explain a whole feature.
These answer one task inside it ("how do I add bank details to my quotation"),
so tiTi says the real steps instead of the feature's general guide. They are
checked first; when none fits, the broad answers take over as before.

Each entry:  key: (groups, answer[, without])
  groups  — the question must have a word/phrase from EVERY group (matched at
            the start of a word, so "tin" never matches "setting").
  Loose groups (how / change / show…) must match but don't make an entry
  more specific. The entry with the most specific groups wins; ties go to
  the one listed first. without — words that rule the entry out.

Add a feature's exact answers here when it's built (rounds so far:
1 selling & paperwork).
"""
import re

# Common misspellings, fixed before any matching
_TYPOS = {
    r"\bq(?:o|ou|ua|ao)t(?:a|e)?tions?\b": "quotation",
    r"\bquatations?\b": "quotation",
    r"\bqoutes?\b": "quote",
    r"\bre(?:c|s)i(?:e|p)?pts?\b": "receipt",
    r"\breciepts?\b": "receipt",
    r"\brecipts?\b": "receipt",
    r"\binv(?:i|o)(?:o|i)ces?\b": "invoice",
    r"\binvioces?\b": "invoice",
    r"\binvoive?s?\b": "invoice",
    r"\binvent(?:ry|ery|ary)\b": "inventory",
    r"\bacc?ount?\b": "account",
    r"\bacct\b": "account",
    r"\bbnk\b": "bank",
    r"\bdetials?\b": "details",
    r"\bdetial\b": "details",
    r"\bsettins?\b": "settings",
    r"\bsetings?\b": "settings",
    r"\bstaffs\b": "staff",
    r"\bsuppliar?s?\b": "supplier",
    r"\bcostumers?\b": "customer",
    r"\bcustormers?\b": "customer",
    r"\bdiscout\b": "discount",
    r"\bdeposite\b": "deposit",
    r"\badress\b": "address",
    r"\bemial\b": "email",
}
_TYPO_RX = [(re.compile(k), v) for k, v in _TYPOS.items()]


def fix_typos(text):
    q = (text or "").lower()
    for rx, good in _TYPO_RX:
        q = rx.sub(good, q)
    return q


# Shared word groups
_BANK = ("bank", "account number", "account details", "account no", "acc no", "where to pay", "payment details",
         "transfer details")
_QUOTE_INV = ("quotation", "quote", "invoice", "estimate")
_QUOTE = ("quotation", "quote", "estimate")
_INVOICE = ("invoice",)
_RECEIPT = ("receipt",)
_DOCS = ("receipt", "invoice", "quotation", "quote", "waybill", "printout", "print out")
class Loose(tuple):
    """A group that must match but says little about the topic."""


_CHANGE = Loose(("change", "edit", "set", "put", "add", "remove", "hide", "show", "update", "write", "how", "where",
           "turn", "stop", "don't want", "dont want", "take off"))
# Parts of a paper: a question about these is not about editing the paper itself
_PARTS = ("logo", "bank", "account", "paper", "title", "closing", "footer", "email", "address", "phone",
          "vat", "tin", "size", "colour", "color", "heading", "status", "progress", "stage", "deposit")

_SETTINGS_PRINT = "Menu → More → *Settings* → *Receipts & printables* (under Selling & paperwork)"

HOWTO = {
    # ── Bank details ─────────────────────────────────────────────────────────
    "bank_on_invoice": (
        [_BANK, _QUOTE_INV],
        "🏦 *Bank details on invoices and quotations*\n\n"
        "1. *My Profile* → *Bank account for payments* → type the bank, account number and account name → *Save*.\n"
        f"2. {_SETTINGS_PRINT} → *Bank details on invoices & quotations* → *Show*.\n\n"
        "Every invoice and quotation then shows where to pay — printed, downloaded and sent on WhatsApp.",
    ),
    "bank_on_receipt": (
        [_BANK, _RECEIPT],
        "🏦 *Bank details on receipts*\n\n"
        "1. *My Profile* → *Bank account for payments* → type it → *Save*.\n"
        f"2. {_SETTINGS_PRINT} → *Bank details on receipts* → *Show*.\n\n"
        "Handy when customers pay their balance by transfer. Receipts don't show it unless you choose.",
    ),
    "bank_add": (
        [_BANK, Loose(("add", "where", "put", "set", "save", "change", "update", "enter", "my"))],
        "🏦 *Your bank account*\n\n"
        "*My Profile* → *Bank account for payments* → type the bank, account number and account name → *Save*. You can add two.\n\n"
        f"To print it on your papers: {_SETTINGS_PRINT} → *Bank details on invoices & quotations* "
        "and *Bank details on receipts*.\n"
        "Pay links use it too, so customers see where to transfer.",
    ),

    # ── Printing: paper, title, closing line, what shows ─────────────────────
    "paper_size": (
        [("paper", "a4", "58mm", "80mm", "58 mm", "80 mm", "thermal", "page size", "roll", "small printer",
          "pos printer", "receipt printer", "full page"),
         ("print", "receipt", "invoice", "size", "change", "paper", "use", "how")],
        "🖨️ *Paper size*\n\n"
        f"{_SETTINGS_PRINT} → *Paper size*:\n"
        "• *Thermal 80mm* — the small receipt printer most shops use\n"
        "• *Thermal 58mm* — the smallest handheld printers\n"
        "• *A4 page* — office printer, or to save as PDF and send\n\n"
        "The preview at the bottom shows how it will look. To print: open the receipt or invoice → "
        "*Download / Print*.",
    ),
    "receipt_title": (
        [("title", "heading", "word at the top", "top of my receipt", "top of the receipt", "name of the receipt",
          "call it", "header"), _DOCS],
        "🧾 *Receipt title* — the word at the top of a receipt\n\n"
        f"{_SETTINGS_PRINT} → *Receipt title* → type it (e.g. _Sales Receipt_, _Cash Bill_) → *Save*.\n"
        "Leave it empty to use your business type's own word (e.g. Receipt).",
    ),
    "closing_line": (
        [("closing", "footer", "bottom", "thank you", "message at the end", "end of the receipt",
          "end of my receipt", "last line", "note at the end", "goods sold", "no refund"), _DOCS],
        "🧾 *Closing line* — printed at the bottom of every receipt\n\n"
        f"{_SETTINGS_PRINT} → *Closing line* → type it (e.g. _Thank you for your business_ or "
        "_Goods sold are not returnable_) → *Save*.\n"
        "It also goes on receipts sent on WhatsApp.",
    ),
    "email_on_docs": (
        [("email", "e-mail", "mail address"), _DOCS],
        "📧 *Email on receipts and invoices*\n\n"
        "1. *My Profile* → *Business email* → type it → *Save*.\n"
        f"2. {_SETTINGS_PRINT} → *Email* → *Show* (or *Hide* to leave it off).",
    ),
    "address_on_docs": (
        [("address", "location"), _DOCS, _CHANGE],
        "📍 *Address on receipts and invoices*\n\n"
        "Your address is on *My Profile* (a branch's own address is on *Branches*).\n"
        f"To show or leave it off: {_SETTINGS_PRINT} → *Address* → *Show* / *Hide*.",
        ("email", "e-mail"),
    ),
    "phone_show_hide": (
        [("phone", "my number", "phone number"), _DOCS,
         Loose(("hide", "remove", "show", "don't want", "dont want", "take off", "leave off"))],
        "📞 *Phone number on your papers*\n\n"
        f"Show or leave it off: {_SETTINGS_PRINT} → *Phone number* → *Show* / *Hide*.\n"
        "To change which number prints (or print two): *My Profile* → *Phone on receipts* (up to two numbers, e.g. _0803… / 0812…_).",
    ),
    "logo_position": (
        [("logo",), ("left", "right", "top", "middle", "centre", "center", "position", "move", "hide", "remove",
                     "where the logo", "side")],
        "🖼️ *Where your logo sits*\n\n"
        f"{_SETTINGS_PRINT} → *Logo* → *On top*, *Left*, *Right* or *Hide*.\n"
        "Hide saves ink on thermal printers. To add or change the logo itself: *My Profile* → upload your logo.",
    ),
    "details_align": (
        [("centre", "center", "letterhead", "line up", "align", "left side"), _DOCS],
        "🧾 *How your name and details line up*\n\n"
        f"{_SETTINGS_PRINT} → *Business name and details* → *Centre* (like a shop receipt) "
        "or *Left* (like a letterhead).",
    ),
    "print_how": (
        [("print", "download", "pdf", "printer"), _DOCS, Loose(("how", "can i", "where", "connect", "want to"))],
        "🖨️ *Printing or downloading*\n\n"
        "Open the receipt, invoice, quotation or waybill → *Download / Print*. Your phone or computer's "
        "print window opens: pick your printer, or *Save as PDF* to send it.\n\n"
        f"Paper size (thermal 80mm, 58mm or A4) and what shows on it: {_SETTINGS_PRINT}.",
    ),

    # ── Receipts ─────────────────────────────────────────────────────────────
    "void_receipt": (
        [("void", "cancel", "delete", "remove", "wrong", "mistake", "undo"), _RECEIPT],
        "↩️ *Cancelling a wrong receipt*\n\n"
        "A receipt is the record of a sale or payment, so you cancel the sale itself:\n"
        "*Transactions* → find it → *Void* → type the reason. It stops counting in your balances and "
        "reports, and the stock goes back. It's kept, marked voided, for your records.\n\n"
        "Goods brought back (not a mistake)? Open the receipt → *Return goods*.",
        _PARTS,
    ),
    "resend_receipt": (
        [("send", "resend", "share", "whatsapp", "forward"), _RECEIPT],
        "📤 *Sending a receipt*\n\n"
        "*Receipts* → tap the receipt → *Share* (WhatsApp or anywhere) or *Download / Print*.\n"
        "Sales to a customer with a phone number get their receipt on WhatsApp by themselves.",
    ),

    # ── Invoices ─────────────────────────────────────────────────────────────
    "repeat_invoice": (
        [("repeat", "recurring", "every month", "monthly", "weekly", "every week", "automatically", "automatic",
          "same invoice", "rent", "tenant", "subscription fee"), ("invoice", "bill")],
        None,   # the full answer is the FAQ's "repeat_invoice"
    ),
    "edit_invoice": (
        [("edit", "change", "correct", "fix", "wrong", "update", "add item", "remove item"), _QUOTE_INV],
        "✏️ *Changing an invoice or quotation*\n\n"
        "Open it → *Edit* → change the items, prices or customer → save.\n"
        "*Edit* shows while nothing has been delivered or paid. After that, *Cancel* it and write a new one "
        "(a payment already recorded stays on the customer's account).",
        _PARTS,
    ),
    "cancel_invoice": (
        [("cancel", "delete", "remove", "void"), _QUOTE_INV],
        "🗑️ *Cancelling an invoice or quotation*\n\n"
        "Open it → *Cancel*. It's kept, marked *Cancelled*, so the number isn't reused — nothing is owed on it.\n"
        "Goods already delivered or money already paid? Use *Cancel / refund* for what's left.",
        _PARTS,
    ),
    "invoice_payment": (
        [("paid", "payment", "pay", "collect", "balance"), _INVOICE, Loose(("record", "how", "mark", "customer", "part", "half", "some"))],
        "💰 *Payment on an invoice*\n\n"
        "Open the invoice → *Record payment* → type what they paid → *Save payment*.\n"
        "Paid in full: it's done. Paid part: the rest goes on the customer's debts, with reminders like any debt.",
    ),
    "invoice_delivered": (
        [("deliver", "delivered", "delivery", "supplied", "collected"), _INVOICE],
        "🚚 *Delivering on an invoice*\n\n"
        "Open the invoice → *Mark delivered* when the goods go — that's when stock comes out.\n"
        "Only some went? Choose *Part delivered* and type what went; later tap *Mark the rest delivered*.",
    ),
    "invoice_send": (
        [("send", "resend", "share", "whatsapp", "forward"), _QUOTE_INV],
        "📤 *Sending an invoice or quotation*\n\n"
        "Open it → *Send to customer* (WhatsApp to the customer's number) — or *Download / Print* to share "
        "the PDF yourself. Bank details show on it if you chose that in "
        f"{_SETTINGS_PRINT}.",
    ),

    # ── Quotations ───────────────────────────────────────────────────────────
    "quote_show_hide": (
        [("show", "hide", "turn on", "turn off", "switch on", "switch off", "enable", "disable", "remove",
          "can't see", "cant see", "don't see", "dont see", "not showing", "where is", "missing", "no button"),
         _QUOTE],
        "📝 *Quotations on or off*\n\n"
        "Menu → More → *Settings* → *Invoices* (under Selling & paperwork) → *Quotations*:\n"
        "• *Automatic* — on for businesses that do jobs (tailor, mechanic, builder, printer…)\n"
        "• *Show* — always on: Invoices gets *New quotation*\n"
        "• *Hide* — off. Quotations already written are kept.",
    ),
    "quote_status": (
        [("status", "progress", "track", "stage", "completed", "complete", "where is my", "follow up"), _QUOTE],
        "📊 *Following a quotation*\n\n"
        "Every quotation shows its progress: *Quotation → Accepted → Paid → Delivered → Completed*, "
        "with the QT, INV and receipt numbers and dates. Open it from *Invoices*.\n"
        "It moves by itself: *Customer accepted* makes it an invoice; the balance collected turns it *Paid*; "
        "paid and delivered is *Completed*.",
    ),
    "quote_deposit": (
        [("deposit", "advance", "part payment", "half payment", "mobilization", "mobilisation", "before work",
          "upfront", "up front"), _QUOTE + ("job",)],
        "💵 *Deposit on a quotation*\n\n"
        "When you write the quotation (Invoices → *New quotation*) set *Deposit before work starts* — "
        "e.g. 60%. It shows the deposit and the *balance on completion*.\n"
        "When they pay: open it → *Record deposit / payment* → *Deposit*. The balance goes on their debts, "
        "due on the completion date.",
    ),
    "quote_to_invoice": (
        [("accept", "accepted", "agreed", "agree", "convert", "turn into", "become", "change to", "make it"),
         _QUOTE],
        "✅ *When the customer agrees*\n\n"
        "Open the quotation → *Customer accepted*. It becomes an invoice (INV number) with the same items — "
        "no retyping. Then record the deposit or payment on it.",
    ),

    # ── VAT ──────────────────────────────────────────────────────────────────
    "vat_number": (
        [("tin", "vat number", "tax number", "tax id", "tax identification"), Loose(_CHANGE + _DOCS)],
        "🧾 *TIN / VAT number*\n\n"
        "Menu → More → *Settings* → *VAT* → turn on *I charge VAT* → *TIN / VAT number* → type it → *Save*.\n"
        "It prints on receipts, invoices and quotations.",
    ),
    "vat_inclusive": (
        [("vat",), ("include", "inclusive", "inside", "on top", "already in", "added to", "add to the price",
                    "before vat", "after vat")],
        "🧾 *Are your prices with VAT or before VAT?*\n\n"
        "Menu → More → *Settings* → *VAT* → *My prices*:\n"
        "• *Add VAT on top* — ₦10,000 becomes ₦10,750 at the till (7.5%)\n"
        "• *Already include VAT* — ₦10,750 stays ₦10,750; the receipt shows the VAT inside it.",
    ),
    "vat_exempt": (
        [("vat",), ("some product", "some items", "one product", "a product", "exempt", "no vat", "without vat",
                    "not all", "certain product", "certain items", "food items")],
        "🧾 *Products without VAT*\n\n"
        "*Inventory* → tap the product → *Edit* → tick *No VAT* → save. That product is left out of VAT "
        "on every sale; the rest still have it.",
    ),
    "vat_report": (
        [("vat",), ("collected", "how much", "total", "report", "file", "filing", "remit", "pay to")],
        "🧾 *VAT you collected*\n\n"
        "Menu → More → *Settings* → *VAT* → *VAT collected* shows this month and last month — from sales "
        "and paid invoices. That's what you file.",
    ),
}


_RX_CACHE = {}


def _has(q, words):
    for w in words:
        rx = _RX_CACHE.get(w)
        if rx is None:
            rx = _RX_CACHE[w] = re.compile(r"(?<![a-z0-9])" + re.escape(w))
        if rx.search(q):
            return True
    return False


def match_howto(text):
    """The exact-answer key for this question, or None."""
    q = fix_typos(text)
    best, best_n = None, 0
    for key, entry in HOWTO.items():
        groups = entry[0]
        without = entry[2] if len(entry) > 2 else ()
        if without and _has(q, without):
            continue
        if all(_has(q, g) for g in groups):
            n = sum(0 if isinstance(g, Loose) else 1 for g in groups)
            if n > best_n:
                best, best_n = key, n
    return best


_DATA_QUESTION = re.compile(r"^\s*(?:how much|how many|who|when did|what did|did|which customer|list)\b")


def exact_for(text):
    """The exact answer for a how-to question — or for a plain statement with no
    numbers that clearly names one task ("remove bank details from my
    quotation"). Questions about the business's own figures ("how much did Ade
    pay on the invoice") are left to the commands that answer them."""
    from faq import _is_question
    q = fix_typos(text)
    if _DATA_QUESTION.match(q) and not re.search(r"\bvat\b", q):   # "how much VAT…" is answered here
        return None
    key = match_howto(q)
    if not key:
        return None
    if _is_question(text):
        return key
    if not re.search(r"\d", q) and _specific_count(key) >= 2:
        return key
    return None


def _specific_count(key):
    return sum(0 if isinstance(g, Loose) else 1 for g in HOWTO[key][0])


def topic_for(key):
    """The answer key tiTi sends: an entry with no answer of its own points
    at the full FAQ answer of the same name."""
    return key if HOWTO[key][1] is None else f"howto:{key}"


def howto_answer(key):
    entry = HOWTO.get(key)
    if not entry:
        return None
    answer = entry[1]
    if answer is None:                       # points at a full FAQ answer
        from faq import FAQ_ANSWERS
        return FAQ_ANSWERS.get(key)
    return answer


def howto_facts():
    """Every exact answer as plain lines — given to the AI so it answers from
    facts when no answer matches the question."""
    out = []
    for entry in HOWTO.values():
        answer = entry[1]
        if answer:
            out.append("- " + re.sub(r"\s+", " ", answer.replace("*", "")).strip())
    return "\n".join(out)
