"""
Test script for Due functions
This script demonstrates how to test the get_due_in_2_days, get_due_today, 
and get_overdue_debtors functions with sample data.
"""

from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import the functions from main.py (adjust path if needed)
from main import (
    Base, Customer, Transaction, 
    get_due_in_2_days, get_due_today, get_overdue_debtors,
    get_balance
)

# Use an in-memory SQLite database for testing
TEST_DATABASE_URL = "sqlite:///:memory:"

def setup_test_db():
    """Create test database with sample data"""
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(engine)
    
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    # Create test customers
    owner_phone_1 = "2348012345678"  # Owner 1
    owner_phone_2 = "2348087654321"  # Owner 2
    
    # Owner 1 - Customer 1: Ali (should have debt due in 2 days)
    ali = Customer(
        name="ali",
        owner_phone=owner_phone_1,
        customer_phone="2348011111111"
    )
    db.add(ali)
    db.flush()
    
    # Transaction: Ali bought 50,000 due in 2 days
    today = datetime.utcnow()
    due_in_2_days = today + timedelta(days=2)
    
    tx_ali_buy = Transaction(
        customer_id=ali.id,
        type="BUY",
        amount=50000,
        due_date=due_in_2_days,
        message_id="msg_ali_buy_1",
        created_at=today
    )
    db.add(tx_ali_buy)
    
    # Owner 1 - Customer 2: Bola (should have debt due today)
    bola = Customer(
        name="bola",
        owner_phone=owner_phone_1,
        customer_phone="2348022222222"
    )
    db.add(bola)
    db.flush()
    
    # Transaction: Bola bought 30,000 due today
    tx_bola_buy = Transaction(
        customer_id=bola.id,
        type="BUY",
        amount=30000,
        due_date=today,
        message_id="msg_bola_buy_1",
        created_at=today
    )
    db.add(tx_bola_buy)
    
    # Owner 1 - Customer 3: Chioma (should be overdue - due yesterday)
    chioma = Customer(
        name="chioma",
        owner_phone=owner_phone_1,
        customer_phone="2348033333333"
    )
    db.add(chioma)
    db.flush()
    
    # Transaction: Chioma bought 70,000 due yesterday (OVERDUE)
    due_yesterday = today - timedelta(days=1)
    tx_chioma_buy = Transaction(
        customer_id=chioma.id,
        type="BUY",
        amount=70000,
        due_date=due_yesterday,
        message_id="msg_chioma_buy_1",
        created_at=today
    )
    db.add(tx_chioma_buy)
    
    # Owner 2 - Customer 1: Diaka (should have debt due in 2 days but for different owner)
    diaka = Customer(
        name="diaka",
        owner_phone=owner_phone_2,
        customer_phone="2348044444444"
    )
    db.add(diaka)
    db.flush()
    
    # Transaction: Diaka bought 100,000 due in 2 days (but Owner 2)
    tx_diaka_buy = Transaction(
        customer_id=diaka.id,
        type="BUY",
        amount=100000,
        due_date=due_in_2_days,
        message_id="msg_diaka_buy_1",
        created_at=today
    )
    db.add(tx_diaka_buy)
    
    db.commit()
    
    return db, owner_phone_1, owner_phone_2

def test_due_in_2_days():
    """Test the get_due_in_2_days function"""
    print("\n" + "="*60)
    print("TEST: get_due_in_2_days")
    print("="*60)
    
    db, owner_1, owner_2 = setup_test_db()
    
    # Test without owner_phone (BUGGY - should get ALL customers)
    print("\n❌ BUGGY CALL (without owner_phone):")
    all_due = get_due_in_2_days(db)
    print(f"   Found {len(all_due)} debts due in 2 days (from all owners)")
    for debtor in all_due:
        print(f"   - {debtor['name'].title()}: ₦{debtor['balance']:,}")
    
    # Test with owner_phone (CORRECT - should get only Owner 1's customers)
    print(f"\n✅ FIXED CALL (with owner_phone='{owner_1}'):")
    owner_1_due = get_due_in_2_days(db, owner_1)
    print(f"   Found {len(owner_1_due)} debts due in 2 days (Owner 1 only)")
    for debtor in owner_1_due:
        print(f"   - {debtor['name'].title()}: ₦{debtor['balance']:,}")
    
    # Test with different owner
    print(f"\n✅ FIXED CALL (with owner_phone='{owner_2}'):")
    owner_2_due = get_due_in_2_days(db, owner_2)
    print(f"   Found {len(owner_2_due)} debts due in 2 days (Owner 2 only)")
    for debtor in owner_2_due:
        print(f"   - {debtor['name'].title()}: ₦{debtor['balance']:,}")
    
    print(f"\n✓ Expected: Owner 1 should see Ali only")
    print(f"✓ Expected: Owner 2 should see Diaka only")


def test_due_today():
    """Test the get_due_today function"""
    print("\n" + "="*60)
    print("TEST: get_due_today")
    print("="*60)
    
    db, owner_1, owner_2 = setup_test_db()
    
    # Test with owner_phone
    print(f"\n✅ FIXED CALL (with owner_phone='{owner_1}'):")
    owner_1_due_today = get_due_today(db, owner_1)
    print(f"   Found {len(owner_1_due_today)} debts due today (Owner 1 only)")
    for debtor in owner_1_due_today:
        print(f"   - {debtor['name'].title()}: ₦{debtor['balance']:,}")
    
    print(f"\n✓ Expected: Owner 1 should see Bola only")


def test_overdue():
    """Test the get_overdue_debtors function"""
    print("\n" + "="*60)
    print("TEST: get_overdue_debtors")
    print("="*60)
    
    db, owner_1, owner_2 = setup_test_db()
    
    # Test with owner_phone
    print(f"\n✅ FIXED CALL (with owner_phone='{owner_1}'):")
    owner_1_overdue = get_overdue_debtors(db, owner_1)
    print(f"   Found {len(owner_1_overdue)} overdue debtors (Owner 1 only)")
    for debtor in owner_1_overdue:
        print(f"   - {debtor['name'].title()}: ₦{debtor['balance']:,} (Overdue {debtor['overdue_days']} days)")
    
    print(f"\n✓ Expected: Owner 1 should see Chioma only (overdue 1 day)")


def run_all_tests():
    """Run all tests"""
    print("\n")
    print("╔" + "="*58 + "╗")
    print("║" + " TESTING DUE FUNCTIONS WITH PROPER owner_phone PARAMETER ".center(58) + "║")
    print("╚" + "="*58 + "╝")
    
    test_due_in_2_days()
    test_due_today()
    test_overdue()
    
    print("\n" + "="*60)
    print("✅ All tests completed!")
    print("="*60 + "\n")


if __name__ == "__main__":
    run_all_tests()
