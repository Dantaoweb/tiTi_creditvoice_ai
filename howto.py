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
1 selling & paperwork, 2 staff, 3 stock & categories, 4 customers,
5a production & distributors).
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
    r"\bstafs?\b": "staff",
    r"\bsuppliar?s?\b": "supplier",
    r"\bcostumers?\b": "customer",
    r"\bcustormers?\b": "customer",
    r"\bcus(?:to|t|o)m(?:e|a)?rs?\b": "customer",
    r"\bcustomr?s?\b": "customer",
    r"\bap+oi?n(?:t)?ments?\b": "appointment",
    r"\bloyal(?:i|e)ty\b": "loyalty",
    r"\bdebitors?\b": "debtor",
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

# Round 2 — staff
_STAFF = ("staff", "worker", "employee", "cashier", "sales girl", "salesgirl", "sales boy", "salesboy",
          "salesperson", "sales person", "attendant", "assistant", "my boy", "my girl", "apprentice",
          "admin", "manager", "supervisor")
_STAFF_NOUN = tuple(w for w in _STAFF if w not in ("admin", "manager", "supervisor"))
_STAFF_PAGE = "Menu → *Staff*"
_ON_CARD = f"{_STAFF_PAGE} → find them under the staff list"

# Round 3 — stock & categories
_PRODUCT = ("product", "item", "goods", "stock", "inventory", "drug", "drugs")
_EDIT_PRODUCT = "*Inventory* → tap the product → *Edit details*"
_SETTINGS_STOCK = "Menu → More → *Settings* → *Stock*"
_SETTINGS_CATS = "Menu → More → *Settings* → *Manage categories* (under Stock)"
_SETTINGS_PRINT = "Menu → More → *Settings* → *Receipts & printables* (under Selling & paperwork)"
_CUSTOMER = ("customer", "client", "patient", "buyer", "debtor")
_SETTINGS_LOYALTY = "Menu → More → *Settings* → *Loyalty*"
_SETTINGS_APPT = "Menu → More → *Settings* → *Appointments*"
_OPEN_CUSTOMER = "*Customers* → tap their name"
_SETTINGS_PROD = "Menu → More → *Settings* → *Production*"
_SELLER = ("seller", "distributor", "sales rep", "salesrep", "van", "hawker", "salesman", "sales man", "rep")

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
        "*Inventory* → tap the product → *Edit details* → tick *No VAT on this product* → *Save Changes*. "
        "That product is left out of VAT "
        "on every sale; the rest still have it.",
    ),
    "vat_report": (
        [("vat",), ("collected", "how much", "total", "report", "file", "filing", "remit", "pay to")],
        "🧾 *VAT you collected*\n\n"
        "Menu → More → *Settings* → *VAT* → *VAT collected* shows this month and last month — from sales "
        "and paid invoices. That's what you file.",
    ),

    # ── Staff (round 2) ──────────────────────────────────────────────────────
    "staff_number_taken": (
        [("already", "own business", "has an account", "registered", "using creditvoice", "has creditvoice",
          "can't invite", "cant invite", "won't invite", "wont invite", "refused", "not allowed"),
         _STAFF_NOUN + ("invite", "number")],
        "📵 *That number already runs a business*\n\n"
        "A phone number that runs its own business on CreditVoice can't be your staff — it would mix the two "
        "businesses. Ask them for another number (a second SIM is fine) and invite that one.",
        ("pin", "password", "receipt", "invoice"),
    ),
    "staff_accept": (
        [("accept", "join", "code", "invitation", "invite link", "invite code"),
         ("my boss", "my employer", "my oga", "my madam", "invited me", "i was invited", "i got invite",
          "i got an invite", "i got the code", "i have the code", "i received", "as staff", "staff invitation",
          "accept the invite", "accept invite", "accept invitation", "join code", "accept code")],
        "🔑 *Joining as staff*\n\n"
        "1. Open the link you were sent — or go to creditvoiceai.com and tap *Accept a staff invitation*.\n"
        "2. Type *Your Phone Number* and the 6-digit *Accept Code*.\n"
        "3. *Create your PIN* (at least 4 digits). You're in — log in with your phone and PIN from then on.\n\n"
        "Code expired? Ask your employer to tap *Resend invite* (a new code lasts 24 hours).",
        ("cancel", "withdraw", "delete", "remove", "resend", "expired", "not working", "didn't get", "did not get",
         "didnt get", "already"),
    ),
    "staff_code_expired": (
        [("expired", "expire", "not working", "invalid", "wrong code", "didn't get", "didnt get", "did not get",
          "lost", "resend", "new code", "another code", "fresh code", "24 hours"),
         ("code", "invite", "invitation", "join link", "staff link")],
        "🔁 *A fresh invite code*\n\n"
        f"{_STAFF_PAGE} → *Pending Invitations* → *Resend invite*. They get a new code and link, good for 24 hours. "
        "Send it with *Send on WhatsApp* or *Copy link*.",
        ("pin", "password", "loyalty", "discount", "coupon", "redeem", "plan"),
    ),
    "staff_cancel_invite": (
        [("cancel", "withdraw", "delete", "remove", "take back", "stop"), ("invite", "invitation")],
        "🗑️ *Cancelling an invitation*\n\n"
        f"{_STAFF_PAGE} → *Pending Invitations* → *Cancel* next to their name. The code stops working.",
        ("partner", "investor", "friend", "referral"),
    ),
    "staff_invite": (
        [_STAFF_NOUN, ("add", "invite", "join", "register", "create", "bring", "new", "employ", "hire", "onboard",
                       "set up", "access")],
        "👷 *Adding staff* (Pro and Premium)\n\n"
        f"1. {_STAFF_PAGE} → *Invite a staff member* → *Full Name* and *Phone Number* (with country code, no +, "
        "e.g. _2348031234567_). Email and branch are optional.\n"
        "2. Choose: tick *Join as admin* to let them see the whole business, or leave it for ordinary staff "
        "(they can see the business's customers to serve them — untick to keep them to their own).\n"
        "3. *Send Invitation* → *Send on WhatsApp* or *Copy link*. The code lasts 24 hours.\n"
        "They open it → enter the code → set a PIN, and you get a notice when they join.",
        ("partner", "investor", "customer", "supplier", "teacher", "pupil", "student"),
    ),
    "staff_make_admin": (
        [("admin", "manager", "supervisor", "full access", "see everything", "everything", "in charge",
          "run the business", "run the shop", "when i'm away", "when i am away", "when i travel", "not around"),
         _STAFF_NOUN + ("make", "give", "turn", "change", "promote")],
        "⭐ *Making someone admin*\n\n"
        f"{_ON_CARD} → *Make admin*. An admin sees everything about the business — all customers, sales, debts "
        "and stock — so they can run it when you're away.\n"
        "Inviting someone new? Tick *Join as admin* on the invite.\n"
        "Keep some things from them: tick them under *This admin can't see…*. "
        "Changed your mind: *Make ordinary staff*.",
        ("pin", "password", "app admin", "creditvoice admin", "difference", "what can", "what does"),
    ),
    "staff_limits": (
        [_STAFF,
         ("can't see", "cant see", "cannot see", "not see", "not to see", "stop", "hide", "block", "prevent",
          "restrict", "limit", "keep from", "don't want", "dont want", "shouldn't see", "shouldnt see", "should not see",
          "away from", "without seeing"),
         ("profit", "dashboard", "insight", "expense", "supplier", "cost", "stock", "branch", "total", "report",
          "margin", "money", "chart")],
        "🔒 *What staff can't see*\n\n"
        "*Ordinary staff* never see cost prices or profit, and see only their own sales — nothing to switch.\n"
        f"*Admins* see everything, unless you choose: {_ON_CARD} → *This admin can't see…* → tick "
        "*Dashboard & Insights*, *Profit & cost prices*, *Expenses*, *What we owe suppliers*, "
        "*Changing stock (add, adjust, remove)* or *Other branches*. It works at once.",
    ),
    "staff_customers": (
        [_STAFF, ("customer", "debtor", "client")],
        "👥 *Which customers staff see*\n\n"
        "*Ordinary staff* see the business's customers so they can serve them (sell, take payments) — "
        f"unless you choose otherwise: {_ON_CARD} → untick *Can see the business's customers*. "
        "Then they see only the customers they added or sold to. You can choose this on the invite too.\n"
        "*Admins* see all customers.",
        ("partner", "investor", "supplier"),
    ),
    "staff_remove": (
        [_STAFF, ("remove", "delete", "sack", "fire", "fired", "left", "leave", "leaving", "resign", "resigned",
                  "quit", "stopped working", "stop working", "no longer", "disable", "deactivate", "block",
                  "kick out", "take away access", "revoke")],
        "🚪 *Someone leaves*\n\n"
        f"{_ON_CARD} → *Remove from business*. They're signed out at once and can't record any more. "
        "Everything they recorded stays in your records.",
        ("invite", "invitation", "profit", "cost", "dashboard", "expense", "customer", "admin"),
    ),
    "staff_sign_out": (
        [_STAFF, ("lost", "stolen", "sign out", "signed out", "log out", "logout", "logged in", "signed in",
                  "new phone", "changed phone", "change phone", "another phone", "someone else", "phone missing")],
        "📱 *A staff phone lost or in the wrong hands*\n\n"
        f"{_ON_CARD} → *Sign out their phone*. They're signed out on every phone and log in again with their PIN.\n"
        "Leaving for good? Use *Remove from business* instead.",
    ),
    "staff_branch": (
        [_STAFF, ("branch", "shop", "outlet", "location", "store")],
        "🏬 *A staff member's branch*\n\n"
        f"{_ON_CARD} → *Branch* → pick it. Or choose the branch on the invite — they're attached when they join.\n"
        "An admin can be kept to their own branch: tick *Other branches* under *This admin can't see…*.",
        ("customer", "profit", "cost", "remove", "sack", "fire", "add branch", "new branch", "create branch"),
    ),
    "staff_performance": (
        [_STAFF, ("performance", "leaderboard", "best", "top", "compare", "each", "sales by", "who sold",
                  "how is my", "doing", "sold the most", "sell the most", "record")],
        "🏆 *How each staff member is doing*\n\n"
        f"{_STAFF_PAGE} → *Performance* → the *Staff Leaderboard*: each one's sales, payments taken, transactions, "
        "customers served and top products. Pick the period at the top (e.g. *All time*).",
        ("salary", "pin", "customer", "invite", "add", "remove"),
    ),
    "staff_profile": (
        [_STAFF, ("salary", "position", "level", "employee id", "hr", "job title", "role", "pay my")],
        "🗂️ *Staff details — position, level, salary*\n\n"
        f"{_STAFF_PAGE} → *HR Profiles* → their name → *Position*, *Level*, *Monthly Salary (₦)*, "
        "*Employee ID* → *Save*. Only you see these.",
        ("admin", "expense", "record salary", "paid salary", "pay salary"),
    ),
    "staff_pin": (
        [_STAFF, ("pin", "password", "can't log in", "cant log in", "cannot log in", "can't login", "cant login",
                  "locked out")],
        "🔑 *Staff who forgot their PIN*\n\n"
        "They reset it themselves: login page → *Forgot PIN* → their phone number → the code sent to them → a new PIN.\n"
        "Phone in the wrong hands? You can also "
        f"{_ON_CARD[0].lower() + _ON_CARD[1:]} → *Sign out their phone*.",
    ),
    "staff_what_they_see": (
        [_STAFF, ("what can", "what does", "what do", "what will", "what they see", "permission", "allowed",
                  "able to", "can they", "can he", "can she", "difference")],
        "👀 *What staff can do*\n\n"
        "*Ordinary staff* record sales and payments, see their own sales, and see the business's customers to serve "
        "them (you can keep them to their own). They see only their own sales and never see cost prices or profit.\n"
        "*Admins* see everything about the business — all branches, customers, sales, debts, stock, the Dashboard "
        "and profit — except what you tick under *This admin can't see…*. Only you manage staff.\n"
        f"Change it any time: {_ON_CARD}.",
    ),

    # ── Stock & categories (round 3) ─────────────────────────────────────────
    "purchase_order": (
        [("order", "reorder", "re-order", "purchase order"), ("supplier", "stock", "goods", "more")],
        None,   # the full answer is the FAQ's "purchase_order"
        ("customer", "status", "categor", "sale", "sell"),
    ),
    "stock_add_more": (
        [("restock", "add more", "more stock", "new delivery", "new stock", "goods came", "goods arrived",
          "goods have arrived", "received goods", "received stock", "received new", "top up", "add stock",
          "add to stock", "add to my stock", "stock came", "increase the stock", "increase stock", "increase quantity",
          "supplier brought", "supplier delivered", "new supply")],
        "📦 *More stock came in*\n\n"
        "*Inventory* → tap the product → *Adjust stock* (or *±* on its row) → *Quantity* → *Add Stock*.\n"
        "Optional, when adding: *Supplier*, *Cost per unit*, *Amount paid now* (the rest goes on what you owe the "
        "supplier), *Expiry date* and *Batch no.*\n"
        "Don't add the product again — that makes a duplicate.",
        ("new product", "barcode", "categor", "price list", "catalog", "purchase order"),
    ),
    "many_products": (
        [("many", "several", "all my", "list of", "bulk", "at once", "plenty", "hundreds", "fast", "quick"),
         ("product", "item", "goods", "names", "drugs")],
        "⚡ *Adding many products at once*\n\n"
        "*Inventory* → *Quick Add* → type the names, one per line → add them all. Then set prices and stock on each.\n"
        "Or *Catalog* → pick from the ready-made list for your business type, with suggested prices.",
        ("sell", "sale", "sold", "remove", "delete", "categor"),
    ),
    "low_stock_alert": (
        [("alert", "warn", "notif", "remind", "tell me when", "let me know", "know when"),
         ("low", "finish", "running out", "run out", "running low", "remaining", "left")],
        "🔔 *Low-stock alert*\n\n"
        f"*One product:* {_EDIT_PRODUCT} → *Low-stock alert* → the number to warn at → *Save Changes*.\n"
        f"*Every new product:* {_SETTINGS_STOCK} → *Low-stock alert for new products* → a number → *Save*.\n"
        "tiTi then tells you when it falls to that number, and *Order stock* lists what to buy.",
        ("expir",),
    ),
    "expiry_warn": (
        [("expir",), ("warn", "alert", "notify", "remind", "days before", "how many days", "before it", "early")],
        "⏳ *Warning before goods expire*\n\n"
        f"{_SETTINGS_STOCK} → *Warn me before goods expire* → the number of days (food sellers often use 7) → *Save*.\n"
        "tiTi tells you about goods expiring within that time, and *Inventory* → *Expiry* lists them.",
    ),
    "expiry_add_date": (
        [("expir",), ("add", "enter", "put", "record", "set", "write", "date")],
        "📅 *Adding an expiry date*\n\n"
        "When the stock comes in: *Inventory* → the product → *Adjust stock* → *Quantity* → *Expiry date* "
        "(and *Batch no.* if you like) → *Add Stock*. Each delivery keeps its own date.",
        ("warn", "alert", "notify", "remind", "days before", "subscription", "plan", "code", "invite"),
    ),
    "expiry_list": (
        [("expir",), ("see", "check", "list", "which", "show", "find", "what", "throw", "write off", "remove",
                      "do with", "get rid")],
        "⏳ *Expired and expiring goods*\n\n"
        "*Inventory* → *Expiry*: what has expired and what expires soon, by product.\n"
        "To throw expired goods away: tap *Write off expired* beside it — they leave stock and count as a loss.\n"
        "Selling a product with expired stock shows a warning at the till.",
        ("subscription", "plan", "code", "invite"),
    ),
    "count_blind": (
        [("count",), ("hide", "blind", "see the numbers", "show the numbers", "copy", "copying", "app's number",
                     "apps number")],
        "📋 *Hiding the app's numbers while counting*\n\n"
        f"{_SETTINGS_STOCK} → *Stock count: hide the app's numbers while counting* → *Hide (blind)* or *Show*.\n"
        "Blind means counters see only empty boxes, so they count what's really there.",
    ),
    "count_approve": (
        [("count",), ("approve", "approval", "accept the count", "confirm the count", "fix my stock")],
        "✅ *Approving a stock count*\n\n"
        "Staff count, then tap *Send for approval*. You open it from *Inventory* → *Count stock* → the count "
        "*Waiting for approval* → check each *Difference* → *Approve — fix my stock*. Stock changes by each "
        "difference, with the reason recorded.",
    ),
    "duplicates": (
        [("duplicate", "twice", "two times", "same product", "double", "entered it again", "added it again",
          "same thing"), _PRODUCT + ("same product", "same thing")],
        "👯 *The same product entered twice*\n\n"
        "*Inventory* → *Check duplicates* — it lists products that look like the same thing.\n"
        "To keep one: open the other → *Adjust stock* → *Remove Stock* (reason *Counting correction*), add that "
        "quantity to the one you keep with *Add Stock*, then *Remove product* on the extra one.",
        ("receipt", "invoice", "quotation", "sale", "payment", "customer", "sync"),
    ),
    "price_change": (
        [("price", "selling price", "how much i sell"), ("change", "update", "edit", "increase", "reduce",
                                                         "new", "adjust", "correct", "wrong", "set")],
        "💲 *Changing a price*\n\n"
        f"{_EDIT_PRODUCT} → *Selling price* → *Save Changes*. New sales use it at once; old sales keep their price.\n"
        "The product's *Price changes* list shows every change and when.",
        ("wholesale", "bulk", "sub-unit", "sub unit", "sachet", "piece", "cost", "quotation", "invoice", "receipt",
         "plan", "subscription", "paper", "vat") + _SELLER,
    ),
    "wholesale_price": (
        [("wholesale", "bulk price", "carton price", "price for many", "buy many", "buys many", "buy plenty",
          "big buyer", "bulk buyer", "price for bulk", "cheaper for")],
        "📦 *Wholesale price*\n\n"
        f"{_EDIT_PRODUCT} → *Wholesale price (₦)* and *From qty (buy ≥)* — e.g. ₦180 each from 12. "
        "At the till, a sale of that many or more uses the wholesale price → *Save Changes*.",
    ),
    "sub_unit": (
        [("sub-unit", "sub unit", "subunit", "sachet", "sachets", "piece", "pieces", "by the cup", "derica",
          "loose", "break bulk", "single", "singles", "one one", "retail breakdown", "tablet", "tablets", "strip"),
         ("sell", "price", "unit", "carton", "pack", "packet", "box", "bag")],
        "✂️ *Selling in smaller units* (sachets from a pack)\n\n"
        f"{_EDIT_PRODUCT} → *Retail Breakdown*: *Sub-unit name* (e.g. sachet), *Per …* (how many in one pack, e.g. 15) "
        "and *Sub-unit price (₦)* → *Save Changes*. You can then sell either the pack or single sachets.",
        ("receipt", "invoice"),
    ),
    "cost_price": (
        [("cost price", "cost", "buying price", "bought at", "bought it for", "purchase price", "how much i buy"),
         ("change", "update", "edit", "set", "add", "put", "enter", "correct", "wrong", "new")],
        "💰 *Cost price* (what you paid for it)\n\n"
        f"{_EDIT_PRODUCT} → *Cost price (₦)* → *Save Changes*.\n"
        "Bought new stock at a different cost? Put it in *Cost per unit* when you *Add Stock* — each delivery keeps "
        "its own cost. Ordinary staff never see cost prices.",
        ("staff", "worker", "employee", "hide", "expense", "delivery cost", "transport"),
    ),
    "product_rename": (
        [("rename", "change the name", "change name", "edit name", "edit the name", "wrong name", "spelling", "spelt",
          "spelled", "misspelt", "misspelled", "name is wrong", "correct the name"), _PRODUCT],
        "✏️ *Renaming a product*\n\n"
        f"{_EDIT_PRODUCT} → *Product name* → *Save Changes*. Its stock, sales and history stay with it.",
        ("business", "shop name", "company", "categor", "customer"),
    ),
    "stock_history": (
        [("history", "movement", "movements", "where did", "what happened", "trail", "track", "who added",
          "who removed", "when did"), ("stock", "product", "item", "goods", "quantity")],
        "📜 *What happened to a product's stock*\n\n"
        "*Inventory* → tap the product → *Stock movements*: every sale, delivery, removal and count, with the date "
        "and who did it. *Price changes* is just under it.\n"
        "Stock that left without a sale: *Inventory* → *Removed stock*.",
        ("expir", "count"),
    ),
    "removed_stock_report": (
        [("removed", "damaged", "stolen", "lost", "written off", "write off", "wasted", "spoilt", "spoiled",
          "missing"), ("report", "list", "see", "total", "how much", "value", "check", "show")],
        "🗑️ *Stock that left without being sold*\n\n"
        "*Inventory* → *Removed stock*: date, product, quantity, reason (damaged, expired, stolen…), note and value.",
        ("staff", "phone", "customer"),
    ),
    "keep_aside": (
        [("keep aside", "kept aside", "keep goods aside", "keep it aside", "reserve", "reserved", "not collected",
          "haven't collected", "havent collected", "yet to collect", "left the goods", "left their goods",
          "left his goods", "left her goods", "come back for")],
        "🧺 *Goods customers paid for but haven't collected*\n\n"
        f"{_SETTINGS_STOCK} → *Keep goods aside for customers who have not collected*:\n"
        "• *Yes* — they're kept aside, so no one else can buy them\n"
        "• *No* — they stay free to sell until you keep them aside yourself (*Deliveries* or *Add stock*)\n"
        "Inventory shows *Kept aside for customers* on each product.",
        ("loyalty", "points"),
    ),
    "part_delivery_switch": (
        [("not all goods delivered", "part delivery", "partial delivery", "deliver later", "collect later",
          "part delivered"), ("show", "hide", "remove", "button", "option", "setting", "turn", "don't see",
                              "dont see", "can't see", "cant see", "where is")],
        "🚚 *The \"Not all goods delivered now\" option at the till*\n\n"
        f"{_SETTINGS_STOCK} → *Show \"Not all goods delivered now\" when selling* → *Yes* or *No*.",
    ),
    "category_create": (
        [("categor",), ("add", "create", "new", "make", "set up", "start")],
        "🗂️ *Adding categories*\n\n"
        f"{_SETTINGS_CATS} → type them, separated by commas (e.g. _Drinks, Provisions, Toiletries_) → *+ Add*.\n"
        "They show on *Add product* straight away, even before any product is in them.",
        ("move", "put", "assign", "into", "under", "group", "suggest", "rename"),
    ),
    "category_move": (
        [("categor",), ("move", "put", "assign", "change", "into", "under", "place", "transfer")],
        "🗂️ *Putting products into a category*\n\n"
        f"{_SETTINGS_CATS} → *Put products into a category*: *Find products…* → tick them → type the category → "
        "*Move*.\n"
        f"One product: {_EDIT_PRODUCT} → *Category* → *Save Changes*.",
        ("rename", "delete", "order", "arrange", "suggest", "business"),
    ),
    "category_rename": (
        [("categor",), ("rename", "delete", "remove", "change the name", "wrong name", "spelling")],
        "🗂️ *Renaming or deleting a category*\n\n"
        f"{_SETTINGS_CATS} → *Rename* next to it — its products move with it.\n"
        "Delete: the *✕* shows once the category has no products (move them out first).",
    ),
    "category_group_view": (
        [("categor",), ("group", "show", "see", "inventory", "till", "pos", "sell", "view", "display", "by category")],
        "🗂️ *Showing stock in categories*\n\n"
        f"{_SETTINGS_STOCK} → *Group stock by category* → *On*. Then *Where grouping shows* → *Inventory only* "
        "or *Inventory and POS* (at the till: tap a category, then the product).",
        ("staff", "only", "suggest", "move", "put", "assign", "add", "create", "rename", "delete"),
    ),
    "category_only_list": (
        [("categor",), ("staff", "only", "lock", "restrict", "stop", "from my list", "creating", "making new")],
        "🗂️ *Only your categories*\n\n"
        f"{_SETTINGS_CATS} → *Only categories from my list* → *On*: staff pick from your list when they add a "
        "product; only you make new ones. *Off*: anyone can type a new one.",
    ),
    "category_suggest": (
        [("categor",), ("suggest", "automatic", "automatically", "auto", "titi", "by itself", "for me")],
        "🗂️ *Let tiTi pick categories*\n\n"
        f"*New products:* {_SETTINGS_STOCK} → *New categories come from* → *tiTi suggests*.\n"
        f"*Products with none yet:* {_SETTINGS_CATS} → *Let tiTi suggest categories* → untick any that are wrong → "
        "*Apply*.",
    ),
    "category_order": (
        [("categor",), ("order", "arrange", "sort", "first", "top", "rearrange", "sequence", "up and down")],
        "🗂️ *Order of categories*\n\n"
        f"{_SETTINGS_CATS} → the ↑ ↓ arrows beside each one. That order is used on Inventory and at the till.",
    ),

    # ── Customers (round 4) ──────────────────────────────────────────────────
    "customer_add": (
        [("add", "create", "register", "new", "save", "enter", "record", "put"), _CUSTOMER],
        "👤 *Adding a customer*\n\n"
        "*Customers* → *Add Customer* → their *Name* (and *Phone number* for WhatsApp reminders) → *Add Customer*.\n"
        "Or just type their name at the till when you sell — tiTi adds them. Same name again? tiTi uses the "
        "one already saved, capitals and spaces ignored.",
        ("staff", "pay", "paid", "phone", "number", "loyal", "appointment", "book", "invoice", "receipt",
         "quotation", "duplicate", "twice", "merge", "debt", "remind", "balance", "thrift", "group", "categor",
         "field", "detail", "supplier", "waybill", "deliver"),
    ),
    "customer_edit": (
        [("change", "edit", "rename", "correct", "update", "fix", "wrong", "add", "put", "spell"), _CUSTOMER,
         ("name", "phone", "number", "spelling", "spelt", "contact")],
        "✏️ *Changing a customer's name or phone*\n\n"
        f"{_OPEN_CUSTOMER} → *Edit* → change *Name* or *Phone* → *Save*.\n"
        "Their sales, payments and debt stay with them.",
        ("staff", "invoice", "receipt", "quotation", "due", "supplier", "my phone", "business"),
    ),
    "customer_delete": (
        [("delete", "remove", "erase", "clear", "get rid"), _CUSTOMER],
        "🗑️ *Removing a customer*\n\n"
        "There's no delete for customers — their sales and payments stay on your records.\n"
        "*Saved twice?* Join them: *Customers* → *Duplicates* → tick the one to keep → *Merge into the ticked one*.\n"
        f"*Wrong name?* {_OPEN_CUSTOMER} → *Edit*.",
        ("staff", "invoice", "receipt", "sale", "transaction", "payment", "loyal", "appointment", "supplier",
         "debt from", "from the debt"),
    ),
    "customer_duplicate": (
        [("duplicate", "twice", "two times", "double", "merge", "join", "combine", "same customer", "same person",
          "same name", "two records", "appears two", "showing two", "entered two"), _CUSTOMER],
        "👥 *Same customer saved twice*\n\n"
        "*Customers* → *Duplicates* → for each pair, tick the record to keep → *Merge into the ticked one*.\n"
        "Their sales, payments and debts move to the one kept and the balances add up. Only the owner or an admin "
        "who sees the whole business can merge. Two different people with one name? Leave them, or give one a "
        "fuller name.",
        ("product", "item", "stock", "staff", "supplier"),
    ),
    "customer_send_balance": (
        [("send", "share", "tell", "message", "whatsapp", "show"), _CUSTOMER, ("balance", "owe", "debt", "statement")],
        "📲 *Sending a customer their balance*\n\n"
        "*Customers* → the ✈️ send button on their row (or tap their name → *Send balance*) → change the "
        "message if you like → send. It goes on WhatsApp with a pay link, so they need a phone number saved.",
        ("staff", "supplier", "remind"),
    ),
    "due_date_change": (
        [("due", "pay by", "deadline", "when to pay", "payment date"),
         ("change", "edit", "set", "put", "add", "extend", "move", "shift", "give")],
        "📅 *Changing when a debt is due*\n\n"
        f"{_OPEN_CUSTOMER} → *Transaction history* → the ✏️ beside *Due Date* on that sale → pick the date → ✓.\n"
        "Reminders follow the new date.",
        ("invoice", "subscription", "plan", "supplier", "expir", "rent"),
    ),
    "debtors_list": (
        [("debtor", "owing", "owe", "credit", "overdue", "unpaid", "haven't paid", "have not paid", "outstanding"),
         ("see", "list", "find", "check", "view", "where", "show", "all")],
        "📋 *Seeing who owes you*\n\n"
        "*Customers* → *Debtors* tab — everyone with a balance, *Total Outstanding*, *Next Due* and *Days Overdue*. "
        "Tap a name to see what they bought and record a payment.",
        ("supplier", "i owe", "staff", "remind", "send") + _SELLER,
    ),
    "reminder_mode": (
        [("remind",), ("automatic", "auto", "review", "mode", "turn on", "turn off", "turn it", "switch", "stop",
                       "by itself", "themselves", "before sending", "before they go")],
        "🔔 *Debt reminders*\n\n"
        "*Customers* → *Debtors* tab → *Reminder mode*:\n"
        "• *Review* — tiTi prepares them, you check and send: *Generate Reminders* → *Review*.\n"
        "• *Automatic* — they go out by themselves; *Send Reminders* sends today's now.\n"
        "Only customers with a phone number get them.",
        ("stock", "low", "expir", "appointment", "staff", "subscription", "plan", "supplier", "rent", "fee"),
    ),
    "best_customers": (
        [("best", "top", "most", "biggest", "regular", "loyal customer", "highest"),
         ("customer", "client", "buyer", "spend", "spender")],
        "🏆 *Your best customers*\n\n"
        "*Customers* → *Best* → *Last 30 days*, *Last 90 days* or *Last year*. It lists who spent most and how "
        "often they came, with their loyalty reward if that's on.",
        ("product", "item", "staff", "supplier", "reward", "stamp", "point", "how to keep", "attract"),
    ),
    "loyalty_setup": (
        [("loyalty", "reward", "stamp", "points", "free one"),
         ("set up", "setup", "set it", "start", "switch", "turn on", "turn off", "turn it", "stop", "create",
          "change", "where do i", "where can i", "how many stamps", "expire", "products that count")],
        "🎁 *Rewarding customers who come back*\n\n"
        f"{_SETTINGS_LOYALTY} → *Reward customers who come back* → *Stamp card* (buy a number, next one free) or "
        "*Points* (money back on what they spend); *Off* to stop.\n"
        "Then: *Stamps for a free one* or *Points for every ₦100 spent*, *Rewards expire*, and *Products that "
        "count* (leave empty for everything).",
        ("staff", "redeem", "use their", "use reward", "use points", "at the till", "claim", "spend their", "pin"),
    ),
    "loyalty_use": (
        [("loyalty", "reward", "stamp", "points", "free one"),
         ("redeem", "use their", "use the", "use a", "use his", "use her", "claim", "spend their", "collect their",
          "apply")],
        "🎁 *Using a customer's reward at the till*\n\n"
        "At the till, pick the customer. Their stamps or points show — when there's enough, tap *Use reward* "
        "(stamp card: the free one comes off) or *Use points* (the points come off the total), then save the sale.",
        ("staff", "set", "switch", "turn on", "start"),
    ),
    "appointment_book": (
        [("appointment", "booking", "book", "schedule", "slot"),
         ("add", "make", "create", "new", "book", "enter", "record", "fix", "set")],
        "📆 *Booking an appointment*\n\n"
        "*Appointments* → *Book* → customer, date, time, service(s), who does it → *Book*.\n"
        f"Don't see *Appointments* in the menu? {_SETTINGS_APPT} → *Show Appointments in the menu*.",
        ("link", "online", "customers book", "customer book", "themselves", "hours", "done", "finish", "arrived",
         "no-show", "no show", "cancel"),
    ),
    "booking_link": (
        [("appointment", "booking", "book"),
         ("link", "online", "themselves", "by themselves", "customers book", "customer book", "share", "website")],
        "🔗 *Letting customers book from a link*\n\n"
        f"1. {_SETTINGS_APPT} → *Customers can book from a link* → on, and set *Opening hours* → *Save hours*.\n"
        "2. *Appointments* → *Booking link* → copy it or *Send on WhatsApp*.\n"
        "New bookings wait for you — *Confirm* or *Decline* them on *Appointments* "
        "(or let them confirm by themselves under *When a customer books from the link*).",
    ),
    "appointment_status": (
        [("appointment", "booking"),
         ("done", "finish", "complete", "arrived", "came", "no-show", "no show", "didn't come", "did not come",
          "cancel", "decline", "confirm")],
        "✅ *Updating an appointment*\n\n"
        "*Appointments* → the booking → *Arrived* when they come, *Done* when finished (then *What was done* and "
        "*Paid now* → *Record sale*), or *No-show* if they didn't come. Booked from your link? *Confirm* or "
        "*Decline* first.",
        ("invoice", "quotation", "staff", "stock", "count", "delivery", "waybill", "payment", "paid", "pay"),
    ),
    "pay_link_copy": (
        [("pay link", "payment link", "link"), ("copy", "send", "share", "get", "find", "where")],
        "💳 *Getting a pay link to send*\n\n"
        "Open the invoice → *Copy pay link* → paste it to the customer. Balance messages and receipts with a "
        "balance carry the link by themselves.\n"
        "The customer sees your bank account, transfers, then taps *I've paid* — you confirm on "
        "*Payments to confirm*.",
        ("booking", "appointment", "invite", "staff", "business page", "partner", "thrift", "investor", "join"),
    ),
    "payment_claim_confirm": (
        [("paid", "pay", "transfer", "payment"),
         ("confirm", "approve", "check", "verify", "accept", "said they", "says they", "claim", "i've paid",
          "not received", "didn't receive", "did not receive", "reject")],
        "✅ *A customer says they've paid*\n\n"
        "Check your bank first. Then Menu → *Payments to confirm* → their payment → *Confirm — money is in* "
        "(change *Amount that arrived* if less came), or *Not received* and say why — they're told.\n"
        "Nothing is recorded until you confirm. Only the owner or authorised staff can.",
        ("staff", "salary", "supplier", "subscription", "plan", "upgrade"),
    ),
    "waiting_for_goods": (
        [("waiting", "still to deliver", "not delivered", "yet to deliver", "to deliver", "haven't collected",
          "have not collected", "owe goods", "balance of goods", "remaining goods"), _CUSTOMER + ("who", "see", "list")],
        "🚚 *Customers waiting for goods*\n\n"
        "*Customers* → *To deliver* tab — who bought and is still waiting, and how much is left. "
        "Tap one → *Waybill* when you send the next part.",
        ("supplier", "purchase order"),
    ),

    # ── Production & distributors (round 5a) ─────────────────────────────────
    "production_menu": (
        [("production",), ("menu", "can't find", "cannot find", "can't see", "cannot see", "don't see", "missing",
                           "turn on", "switch on", "show", "where is", "hide")],
        "🏭 *Production in the menu*\n\n"
        f"{_SETTINGS_PROD} → *Show Production in the menu* → on. Bakeries, food, blocks, furniture, welding and "
        "tailoring see it already.",
        ("report", "recipe", "seller", "distributor", "cost"),
    ),
    "recipe_add": (
        [("recipe", "formula", "ingredient", "what one batch uses", "materials for"),
         ("add", "create", "set", "make", "enter", "write", "put", "change", "edit", "update", "new")],
        "📝 *Adding a recipe*\n\n"
        "*Production* → *Recipes* → *+ Add or change a recipe for…* → pick the product → *One batch makes how many?* → "
        "under *What one batch uses* pick each material and its amount (*Add material* for more) → *Other costs per "
        "batch* (gas, diesel, labour) → *Save recipe*.\n"
        "Materials must be in *Inventory* with a cost price, so tiTi can work out what each one costs to make.",
        ("delete", "remove"),
    ),
    "recipe_delete": (
        [("recipe",), ("delete", "remove", "clear", "get rid")],
        "🗑️ *Deleting a recipe*\n\n"
        "*Production* → *Recipes* → *Edit* beside it → *Delete recipe*. What you made before stays recorded.",
    ),
    "production_record": (
        [("production", "produced", "we made", "i made", "what we made", "what i made", "batch", "manufactur",
          "output", "how many we made", "how many i made")],
        "🏭 *Recording what you made*\n\n"
        "*Production* → *Record production* → *What did you make?* → *How many good ones?* → *Rejects* if any → "
        "check the materials used (change an amount if you used more or less) → *Other costs (gas, labour…)* → "
        "*Best before* if it expires → *Record production*.\n"
        "The materials come out of stock and what you made goes in, at its real cost.",
        ("recipe", "seller", "distributor", "sales rep", "report", "undo", "mistake", "wrong", "reject", "spoil",
         "cost", "menu", "delete", "remove", "show", "batch number", "batch no", "expir"),
    ),
    "production_rejects": (
        [("reject", "spoil", "bad ones", "damaged", "broken", "burnt", "regrind", "crumbs", "scrap", "offcut"),
         ("production", "batch", "made", "make", "produc", "bake", "baked", "record")],
        "♻️ *Rejects when making*\n\n"
        "*Production* → *Record production* → after *How many good ones?*, put the bad ones in *Rejects*. If they're "
        "turned into something you keep (regrind, crumbs…), pick it under *Turned back into* → *How much?*.\n"
        "Rejects used materials too, so their cost falls on the good ones; what's turned back goes into stock.",
        ("seller", "distributor", "sales rep", "van"),
    ),
    "production_cost": (
        [("cost", "costs", "costing"),
         ("to make", "making", "production", "produce", "batch", "each one", "per one", "per unit", "my product")],
        "💰 *What it costs to make*\n\n"
        "*Production* → *Recipes* shows what each one costs. When you record a batch, it shows *Each … costs ₦… to "
        "make* — materials at their cost price plus *Other costs (gas, labour…)*, with rejects counted in.\n"
        "Recording sets the product's cost price, averaged with any already in stock, so profit is right.",
        ("seller", "distributor", "sales rep", "selling price", "vat", "subscription", "plan", "staff"),
    ),
    "production_undo": (
        [("production", "batch", "produced", "what we made", "what i made"),
         ("undo", "wrong", "mistake", "cancel", "reverse", "delete", "remove", "correct")],
        "↩️ *Undoing a production entry*\n\n"
        "*Production* → *History* → find it → *Undo*. What was made comes out of stock and the materials go back. "
        "Then record it again correctly.",
        ("recipe", "menu", "seller", "distributor", "batch number", "batch no", "expir"),
    ),
    "production_report": (
        [("production", "made", "material", "recipe", "produced"),
         ("report", "waste", "used vs", "compare", "against the recipe", "more than the recipe", "missing",
          "leakage", "theft", "stolen")],
        "📊 *Production report*\n\n"
        "*Production* → *Report* → pick the time.\n"
        "• *Made, sold and removed* — for each product: *Made*, *Sold*, *Removed* and *Left now*.\n"
        "• *Materials: used vs the recipe* — what was used against what the recipes say. Using more than the recipe "
        "means waste, a wrong recipe, or material going missing.",
        ("seller", "distributor", "sales rep", "staff"),
    ),
    "seller_send_out": (
        [_SELLER, ("send", "give", "goods out", "take goods", "took goods", "takes goods", "taking", "takes", "took", "collect goods", "load",
                   "out with", "morning", "go out", "record what", "carry")],
        "🚚 *Sending goods out with a seller*\n\n"
        "*Production* → *Distributors* → *Send goods out with a seller* → pick the seller (search your customers, or "
        "type a new name and phone) → each product, how many and *Their price* → *Send out*.\n"
        "The goods leave stock now. When the seller comes back, you *Settle*.",
        ("settle", "came back", "come back", "returned", "brought back", "unsold", "owe", "commission", "price",
         "staff", "invite"),
    ),
    "seller_settle": (
        [_SELLER, ("settle", "came back", "come back", "returned", "brought back", "unsold", "remaining", "left over",
                   "leftover", "paid", "pays", "payment", "spoilt", "spoiled", "evening")],
        "✅ *Settling a seller when they come back*\n\n"
        "*Production* → *Distributors* → *Out with sellers now* → *Settle* beside them → for each product, *Back, "
        "good* and *Back, spoilt* (say why) → *Paid now* → *Pay by* if they still owe → *Settle*.\n"
        "Unsold goods go back into stock, what they sold is recorded, and anything unpaid becomes their debt. "
        "You get a receipt.",
        ("staff", "invite", "commission"),
    ),
    "seller_owes": (
        [_SELLER, ("owe", "owing", "debt", "balance", "performance", "how did", "record of", "history", "sold most",
                   "best")],
        "📋 *What each seller took, sold and owes*\n\n"
        "*Production* → *Distributors* → *Sellers* — for each one: *Took*, *Back*, *Spoilt*, *Sold*, *Paid* and "
        "*Owes now*. *Out with sellers now* shows who still has goods.\n"
        "A seller's debt is also on *Customers* → *Debtors*, so you can record their payment there.",
        ("staff", "invite", "salary"),
    ),
    "seller_price": (
        [_SELLER, ("price", "commission", "percent", "wholesale", "discount", "cut", "margin")],
        "🏷️ *A seller's price or commission*\n\n"
        "When you *Send out*, each product's *Their price* starts at your wholesale price — type another to change "
        "it. Paying commission instead? Put retail less their commission; it comes to the same.\n"
        "Set a product's wholesale price on *Inventory* → the product → *Edit details*.",
        ("staff", "invite", "salary", "marketer", "plan"),
    ),
    # ── Branches ─────────────────────────────────────────────────────────────
    "branch_transfer": (
        [("transfer", "move", "send", "shift", "take"), ("branch", "shop to", "location", "outlet"),
         Loose(("stock", "goods", "product", "item", "how", "where", "some", "bag", "carton"))],
        "🚚 *Moving stock to another branch*\n\n"
        "*Inventory* → *Transfer stock* (or open the product → *Transfer*) → *From* and *To* → each product and how "
        "many → *Carried by* if you like → *Send*. You get a transfer note to print, with no prices.\n"
        "It's in the other branch at once — or, if you chose so on *Branches* → *Branch settings*, it waits until "
        "that branch taps *Received* and says what came. See them all on *Inventory* → *Transfers*.",
        ("staff", "money", "pay", "bank", "customer", "invoice", "sale", "receipt"),
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


_DATA_QUESTION = re.compile(r"^\s*(?:how much|how many|who (?:owes?|bought|paid|pays|has|is owing|are owing)"
                            r"|when did|what did|did|which customer|list)\b")


_MEANING_QUESTION = re.compile(r"^\s*(?:what\s+is|what'?s|what\s+are|what\s+does\s+.+\s+mean|meaning\s+of)\b"
                               r"(?!.*\b(?:how|where|difference)\b)")


def exact_for(text):
    """The exact answer for a how-to question — or for a plain statement with no
    numbers that clearly names one task ("remove bank details from my
    quotation"). Questions about the business's own figures ("how much did Ade
    pay on the invoice") are left to the commands that answer them."""
    from faq import _is_question
    q = fix_typos(text)
    if _DATA_QUESTION.match(q) and not re.search(r"\bvat\b", q):   # "how much VAT…" is answered here
        return None
    if _MEANING_QUESTION.match(q):     # "what is blind count?" — the feature's own guide explains it
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
