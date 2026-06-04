"""Simulate conversational analytics questions with real data."""
import os, textwrap
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import webhook_command_router, webhook_early_handlers
import webhook_message_flow, webhook_pending_router
from database import Base
from models import User, Customer, Transaction

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

OWNER = "2348055551234"
log = []
counter = [0]

def fake_send(to, msg): log.append(msg)

for mod in [webhook_message_flow, webhook_early_handlers,
            webhook_pending_router, webhook_command_router]:
    mod.SessionLocal = Session
    mod.send_whatsapp_message = fake_send

def send(text):
    counter[0] += 1
    webhook_message_flow.handle_webhook_body({
        "entry": [{"changes": [{"value": {"messages": [{
            "from": OWNER, "id": f"wamid.an.{counter[0]}",
            "type": "text", "text": {"body": text},
        }]}}]}]
    })

def ask(question):
    log.clear()
    send(question)
    print(f"\n{'─'*60}")
    print(f"  Q: {question}")
    print(f"{'─'*60}")
    for msg in log:
        for line in msg.splitlines():
            print(f"  {line}")

def section(t): print(f"\n{'='*60}\n  {t}\n{'='*60}")

# Silent onboard
for m in ["hello","Demo Pharmacy","yes","1","1"]: send(m)
log.clear()
db = Session()
u = db.query(User).filter(User.phone == OWNER).one()
u.subscription_plan = "GO"; u.subscription_status = "ACTIVE"
db.commit(); db.close()

# Seed transactions — 2 months of data
db = Session()
utcnow = datetime.now(timezone.utc).replace(tzinfo=None)
this_month_start = utcnow.replace(day=1, hour=0, minute=0, second=0)
last_month_start = (this_month_start.replace(day=1) - timedelta(days=1)).replace(day=1)

customers = {}
for name in ["Dickson Petrol", "Value Petro", "Emeka", "Bayo", "Fatima"]:
    c = Customer(name=name.lower(), owner_phone=OWNER)
    db.add(c); db.flush()
    customers[name] = c

# Last month: all 5 customers bought
last_month_txns = [
    ("Dickson Petrol", 1300000000, last_month_start + timedelta(days=2)),
    ("Value Petro", 2600000000, last_month_start + timedelta(days=3)),
    ("Emeka", 496000, last_month_start + timedelta(days=5)),
    ("Bayo", 240000, last_month_start + timedelta(days=6)),
    ("Fatima", 434000, last_month_start + timedelta(days=8)),
    ("Dickson Petrol", 600000000, last_month_start + timedelta(days=15)),
]

# This month: only 3 customers — Dickson and Value went quiet
this_month_txns = [
    ("Emeka", 496000, this_month_start + timedelta(days=1)),
    ("Bayo", 240000, this_month_start + timedelta(days=3)),
    ("Fatima", 434000, this_month_start + timedelta(days=4)),
]

for name, amount, date in last_month_txns + this_month_txns:
    db.add(Transaction(
        customer_id=customers[name].id,
        type="BUY", amount=amount, product="petrol",
        quantity=amount // 1300, unit="litre", unit_price=1300,
        created_at=date,
    ))

# Add some payment receipts to test top debtors
db.add(Transaction(customer_id=customers["Dickson Petrol"].id, type="PAY", amount=300000000,
                   created_at=last_month_start + timedelta(days=20)))

# Seed stock with cost/sell prices
from models import InventoryItem
db.add(InventoryItem(owner_phone=OWNER, name="petrol", unit="litre",
                     quantity=2000000, cost_price=1200, selling_price=1300))
db.commit(); db.close()

section("CONVERSATIONAL ANALYTICS")

ask("who owes me the most")
ask("why are my sales declining this month")
ask("what is my best selling product")
ask("when am I busiest")
ask("is petrol profitable")

print(f"\n{'='*60}\n")
