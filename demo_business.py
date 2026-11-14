"""
Demo business — for admins and CreditVoice marketers to show the app and train
staff, as any kind of business, without touching a real one.

  Open demo     your session moves to your own demo business; your real login
                is kept aside (cookie cv_return) and Exit demo brings it back.
  Show me as…   a fresh demo business of that type with sample products,
                customers, sales and a debt. The old demo is retired (never
                deleted from a real business — there is none to touch).
  Reset         the same type again, fresh.

A demo business and its sample customers use numbers starting 999: not real,
never messaged (whatsapp_client.is_demo_number), and demo businesses are left
out of admin counts.
"""
import secrets
from datetime import datetime, timedelta

from models import Customer, InventoryItem, User, utcnow

DEMO_DAYS = 365

# Ready-made samples for the types people demo most: (name, unit, price, qty, cost)
SAMPLES = {
    "bakery": [("bread large loaf", "loaf", 1500, 120, 900), ("bread small loaf", "loaf", 700, 150, 400),
               ("birthday cake 2kg", "cake", 15000, 4, 9000), ("chin chin pack", "pack", 1000, 60, 550),
               ("meat pie", "piece", 800, 80, 450), ("flour", "bag", 62000, 8, 60000),
               ("sugar", "kg", 1600, 40, 1500), ("yeast", "kg", 8500, 5, 8000)],
    "provision_store": [("peak milk tin", "tin", 750, 48, 600), ("indomie carton", "carton", 9800, 12, 8900),
                        ("golden penny spaghetti", "pack", 1100, 40, 950), ("rice 50kg", "bag", 78000, 6, 72000),
                        ("groundnut oil 5l", "keg", 11500, 10, 10200), ("milo 500g", "pack", 3600, 20, 3100)],
    "building_materials": [("water tank 2000l", "piece", 185000, 7, 150000), ("close couple wc", "set", 95000, 6, 70000),
                           ("wash hand basin", "piece", 38000, 10, 27000), ("floor tiles 60x60", "carton", 14500, 80, 11000),
                           ("flush door", "piece", 42000, 12, 31000), ("water heater 50l", "piece", 88000, 5, 66000)],
    "hardware_store": [("cement 50kg", "bag", 9500, 100, 8700), ("iron rod 12mm", "length", 9800, 60, 8900),
                       ("nails 3 inch", "kg", 1800, 50, 1400), ("roofing sheet", "sheet", 6500, 80, 5300)],
    "pharmacy": [("paracetamol 500mg", "pack", 600, 100, 380), ("amoxicillin 500mg", "pack", 2800, 40, 2000),
                 ("vitamin c 1000mg", "pack", 2500, 30, 1700), ("ors sachet", "sachet", 300, 120, 180),
                 ("artemether lumefantrine", "pack", 3500, 50, 2500), ("blood pressure check", None, 1000, None, None)],
    "private_school": [("tuition jss1", None, 85000, None, None), ("tuition primary 4", None, 65000, None, None),
                       ("school uniform", "set", 12000, 40, 8500), ("mathematics textbook", "book", 4500, 60, 3200),
                       ("exam fee", None, 5000, None, None)],
    "restaurant": [("jollof rice and chicken", "plate", 4500, None, None), ("amala and ewedu", "plate", 3000, None, None),
                   ("pepper soup", "bowl", 3500, None, None), ("bottled water", "bottle", 300, 120, 200),
                   ("soft drink", "bottle", 500, 96, 350)],
    "boutique_clothing": [("ankara gown", "piece", 18000, 20, 11000), ("men's kaftan", "piece", 25000, 12, 16000),
                          ("jeans trousers", "piece", 12000, 30, 7500), ("sneakers", "pair", 22000, 15, 14000)],
    "hair_salon": [("braids (medium)", None, 15000, None, None), ("wash and set", None, 5000, None, None),
                   ("relaxer", None, 7000, None, None), ("hair attachment", "pack", 3500, 40, 2400)],
    "tailor_fashion": [("sew native (men)", None, 15000, None, None), ("sew gown", None, 20000, None, None),
                       ("adjustment", None, 2500, None, None), ("ankara fabric", "yard", 2500, 60, 1700)],
}
FEATURED = ["bakery", "provision_store", "building_materials", "pharmacy", "private_school", "restaurant",
            "boutique_clothing", "hair_salon", "tailor_fashion", "hardware_store"]
SAMPLE_CUSTOMERS = ["Mama Bisi", "Engr Musa", "Ada Okafor", "Tunde Bello"]


class DemoError(ValueError):
    pass


def can_demo(db, user):
    """Admins and active CreditVoice marketers — never a demo login itself."""
    if not user or getattr(user, "is_demo", False):
        return False
    from admin import is_app_admin
    if is_app_admin(user.phone, db):
        return True
    from marketers import for_user
    return bool(for_user(db, user))


def _types():
    from business_templates import BUSINESS_CATEGORIES
    out = {}
    for cat in BUSINESS_CATEGORIES:
        for key, label in cat.get("businesses", []):
            out[key] = (label, cat["key"], cat.get("label"))
    return out


def type_list():
    types = _types()
    featured = [{"key": k, "label": types[k][0], "group": "Popular"} for k in FEATURED if k in types]
    rest = [{"key": k, "label": v[0], "group": v[2]} for k, v in types.items() if k not in FEATURED]
    return featured + sorted(rest, key=lambda t: (t["group"] or "", t["label"]))


def current_demo(db, owner):
    return (db.query(User).filter(User.is_demo.is_(True), User.demo_owner_id == owner.id, User.deleted_at.is_(None))
            .order_by(User.created_at.desc()).first())


def _demo_phone(db):
    while True:
        p = "999" + "".join(secrets.choice("0123456789") for _ in range(10))
        if not db.query(User.id).filter(User.phone == p).first():
            return p


def _samples_for(btype):
    if btype in SAMPLES:
        return SAMPLES[btype]
    from business_templates import INDUSTRY_PRODUCT_CATALOG, SERVICE_PRICE_CATALOG
    if btype in SERVICE_PRICE_CATALOG:
        return [(n, u, p, None, None) for n, u, p in SERVICE_PRICE_CATALOG[btype][:8]]
    names = [row[0] for row in INDUSTRY_PRODUCT_CATALOG.get(btype, [])][:8] or ["product a", "product b", "product c"]
    return [(n, "piece", 2000 + 1500 * i, 30, round((2000 + 1500 * i) * 0.75)) for i, n in enumerate(names)]


def create_demo(db, owner, business_type):
    """A fresh demo business of this type for `owner`; the old one is retired."""
    if not can_demo(db, owner):
        raise DemoError("The demo business is for CreditVoice admins and marketers.")
    types = _types()
    if business_type not in types:
        raise DemoError("Pick a business type to show.")
    label, category, _group = types[business_type]
    old = current_demo(db, owner)
    if old:
        old.deleted_at = utcnow()
        old.token_version = (old.token_version or 0) + 1
    from web_auth import _hash_pin
    demo = User(phone=_demo_phone(db), name=f"Demo ({owner.name or 'CreditVoice'})", role="owner",
                business_category=category, business_type=business_type, business_type_label=f"Demo {label}",
                subscription_plan="PREMIUM", subscription_status="ACTIVE",
                subscription_expires_at=utcnow() + timedelta(days=DEMO_DAYS),
                recovery_pin_hash=_hash_pin(secrets.token_hex(8)),        # no one logs in with a PIN
                whatsapp_linked=False, is_demo=True, demo_owner_id=owner.id, created_at=utcnow())
    db.add(demo)
    db.flush()
    _seed(db, demo, business_type)
    db.commit()
    return demo


def _seed(db, demo, btype):
    """Sample products, customers, two cash sales and a part-paid sale (a debt)."""
    items = []
    for name, unit, price, qty, cost in _samples_for(btype):
        it = InventoryItem(owner_phone=demo.phone, name=name, unit=unit, selling_price=price, cost_price=cost,
                           quantity=qty, is_available=True, category=None if qty is not None else "service",
                           created_at=utcnow())
        db.add(it)
        items.append(it)
    custs = []
    for i, n in enumerate(SAMPLE_CUSTOMERS):
        c = Customer(owner_phone=demo.phone, name=n.lower(), customer_phone=f"999{8000000 + i:07d}{i:03d}"[:13],
                     balance=0)
        db.add(c)
        custs.append(c)
    db.flush()
    sellable = [it for it in items if it.selling_price] or items
    from web_pos import save_pos_sale

    def sale(customer, picks, paid_share, due_days=None):
        lines = [{"inventory_item_id": it.id, "name": it.name, "qty": q, "unit": it.unit,
                  "unit_price": int(it.selling_price or 0)} for it, q in picks]
        total = sum(l["qty"] * l["unit_price"] for l in lines)
        save_pos_sale(db, demo.phone, demo.id, customer.id if customer else None, lines,
                      round(total * paid_share), due_date=(utcnow() + timedelta(days=due_days)) if due_days else None,
                      commit=False, vat=None)

    pick = lambda i, q: (sellable[i % len(sellable)], q)   # noqa: E731
    sale(None, [pick(0, 2), pick(1, 1)], 1)
    sale(custs[0], [pick(2, 1)], 1)
    sale(custs[1], [pick(0, 3), pick(3, 2)], 0.5, due_days=5)      # half paid: a debt with reminders due
    if btype == "bakery":
        _bakery_recipe(db, demo, items)


def _bakery_recipe(db, demo, items):
    from models import Recipe, RecipeLine
    by = {it.name: it for it in items}
    loaf, flour, sugar, yeast = (by.get(n) for n in ("bread large loaf", "flour", "sugar", "yeast"))
    if not all((loaf, flour, sugar, yeast)):
        return
    r = Recipe(owner_phone=demo.phone, product_id=loaf.id, yield_qty=80, extra_cost=4000, created_at=utcnow())
    db.add(r)
    db.flush()
    for mat, q in ((flour, 1), (sugar, 2), (yeast, 0.5)):
        db.add(RecipeLine(recipe_id=r.id, item_id=mat.id, qty=q))


def exit_allowed(db, demo_user, real_user):
    return bool(demo_user and real_user and demo_user.is_demo and demo_user.demo_owner_id == real_user.id)
