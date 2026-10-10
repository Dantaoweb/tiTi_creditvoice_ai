"""
Where things are in the web app — what tiTi tells someone who asks "where do
I…" or "how do I find…".

One entry per menu item in frontend/src/components/Layout.jsx (a test fails
when a menu item has no entry, so a new screen can't ship that tiTi knows
nothing about). Some names change with the business type, so each entry says
what else it may be called.

The menu: on a phone, tap ☰ (top left). Items used often rise to the top;
everything else is under "More" at the bottom of the menu.
"""

NAV_GUIDE = {
    "/home": {
        "name": "Chat with tiTi",
        "what": "Ask tiTi anything, or type a sale the way you would on WhatsApp.",
    },
    "/capture": {
        "name": "Record sale",
        "also": "Record fee payment (schools), Record contribution (thrift), Record job (services), Record payment (clinics)",
        "what": "Record a sale, payment or stock by typing or voice.",
    },
    "/poultry": {
        "name": "Egg & Feed",
        "what": "Poultry farms only: log daily egg collection by grade and feed used, and see the egg/feed report.",
    },
    "/school": {
        "name": "School fees",
        "what": "Schools only: classes, terms, fee lists, raising a term's fees and exemptions.",
    },
    "/pos": {
        "name": "Select product (the till)",
        "also": "Sell textbooks (schools), Select service (services, clinics)",
        "what": "Sell from your price list: tap products or tap 📷 Scan to use the camera, add a Discount (₦ or %), pick a customer, take payment, print the receipt.",
    },
    "/inventory": {
        "name": "Add stock",
        "also": "Price list (services), Textbooks & stock (schools), Medications & supplies (clinics), Ingredients & supplies (food)",
        "what": "Products, prices, stock levels, barcodes. Tap a product → Edit to change price or add a barcode (📷 Scan fills it).",
    },
    "/customers": {
        "name": "My customers",
        "also": "My clients, My students, My members, My patients",
        "what": "Everyone you sell to: balances, history, details/measurements (pencil icon), and their receipts.",
    },
    "/thrift": {
        "name": "Thrift / Ajo",
        "what": "Personal savings and savings groups (rotating ajo, daily collection, target).",
    },
    "/reminders": {
        "name": "Reminders",
        "also": "Fee reminders, Contribution reminders, Payment reminders",
        "what": "Send debt reminders to customers on WhatsApp.",
    },
    "/dashboard": {
        "name": "Dashboard",
        "what": "Sales, debts, Gross profit (sales minus cost of goods, before expenses), top products and the Margin Insight card (Discounts given, items sold below cost) for a period.",
    },
    "/insights": {
        "name": "Insights",
        "what": "Profit by product for a period (best earners, loss-makers), margin per product, price-change log and stock received.",
    },
    "/receipts": {
        "name": "Receipts",
        "what": "Every past receipt to view, share or reprint; New Receipt to write one by hand (with a Discount box).",
    },
    "/invoices": {
        "name": "Invoices",
        "what": "Ask a customer to pay: New invoice (scan or type items, add a Discount), send it, mark delivered, record payment.",
    },
    "/deliveries": {
        "name": "Deliveries",
        "what": "Jobs with a deliver/ready-by date; change the date or tell the customer it's ready.",
    },
    "/wallet": {
        "name": "Wallet",
        "what": "Coming soon — let customers pay you directly.",
    },
    "/transactions": {
        "name": "Transactions",
        "where": "Under More",
        "what": "Every sale and payment, with void (cancel) for mistakes.",
    },
    "/fuel": {
        "name": "Fuel Station",
        "where": "Under More",
        "what": "Filling stations only: pumps, meter readings and fuel sales.",
    },
    "/suppliers": {
        "name": "Suppliers",
        "where": "Under More",
        "what": "Who you buy from and what you owe them — and the Verified Supplier directory: find suppliers, connect with them, or apply to be listed (Pro).",
    },
    "/staff": {
        "name": "Staff",
        "where": "Under More",
        "what": "Invite staff (Pro): each logs in with their own phone and PIN; make one a branch admin.",
    },
    "/partners": {
        "name": "Partners",
        "where": "Under More",
        "what": "Link co-owners or investors with a read-only view (Pro/Premium).",
    },
    "/notes": {
        "name": "Notes",
        "where": "Under More",
        "what": "Private business notes.",
    },
    "/branches": {
        "name": "Branches",
        "where": "Under More",
        "what": "Create branches and see each one's records (web only).",
    },
    "/automation": {
        "name": "Automation",
        "where": "Under More",
        "what": "Turn on automatic reminders and messages.",
    },
    "/opportunities": {
        "name": "Opportunities",
        "where": "Under More",
        "what": "Loans, grants, equipment and trade offers from the CreditVoice team; apply in-app.",
    },
    "/scorecard": {
        "name": "Business Score",
        "where": "Under More",
        "what": "Your business score from your records, finance offers you qualify for, and repayments on financing you took.",
    },
    "/admin": {
        "name": "Admin",
        "where": "Under More (CreditVoice admins only)",
        "what": "For the CreditVoice team, not businesses.",
    },
    "/profile": {
        "name": "My Profile",
        "where": "Under More",
        "what": "Business name and address on receipts, PIN, linked phones, and 'Your review — free advert' to appear on our homepage.",
    },
    "/upgrade": {
        "name": "Upgrade Plan",
        "where": "Under More",
        "what": "See plans and upgrade: pay by card (active at once) or bank transfer (active once confirmed), or redeem a plan code.",
    },
}


def nav_guide_text():
    """The menu as a block for tiTi's instructions."""
    lines = [
        "WHERE TO FIND THINGS (web app menu — on a phone tap ☰ top-left; often-used "
        "items rise to the top, the rest are under \"More\" at the bottom):",
    ]
    for entry in NAV_GUIDE.values():
        name = entry["name"]
        if entry.get("also"):
            name += f" (may be called: {entry['also']})"
        where = f" [{entry['where']}]" if entry.get("where") else ""
        lines.append(f"- {name}{where}: {entry['what']}")
    lines.append(
        "When telling someone where something is, give the taps in order, e.g. "
        "\"Menu → More → Suppliers\". Use the name their business type sees if you know it."
    )
    return "\n".join(lines)
