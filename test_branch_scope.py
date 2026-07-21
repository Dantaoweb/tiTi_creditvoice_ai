"""
Phase 1 (multi-branch isolation foundation):
- customers/inventory get a branch_id, backfilled to the owner's default branch
- branch_scope_for_user resolves the branch a user is confined to
No behavior change to endpoints yet — this is the foundation.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import User, Customer, InventoryItem, Branch
from schema_updates import ensure_schema_updates
from webhook_context import branch_scope_for_user


def _engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return eng


def test_backfill_assigns_existing_rows_to_default_branch():
    eng = _engine()
    S = sessionmaker(bind=eng)
    db = S()
    db.add(User(id="o1", phone="2348000001", name="Owner", role="owner"))
    b_default = Branch(owner_phone="2348000001", name="Main", is_default=True)
    b_other = Branch(owner_phone="2348000001", name="Lekki", is_default=False)
    db.add_all([b_default, b_other]); db.commit()
    db.add(Customer(name="Ada", owner_phone="2348000001"))          # branch_id NULL
    db.add(InventoryItem(owner_phone="2348000001", name="sugar"))   # branch_id NULL
    db.commit()
    default_id = b_default.id
    db.close()

    ensure_schema_updates(eng)   # runs the one-time branch backfill

    db = S()
    assert db.query(Customer).filter_by(name="Ada").first().branch_id == default_id
    assert db.query(InventoryItem).filter_by(name="sugar").first().branch_id == default_id
    db.close()


def test_backfill_leaves_null_when_owner_has_no_default_branch():
    eng = _engine()
    S = sessionmaker(bind=eng)
    db = S()
    db.add(User(id="o2", phone="2348000002", name="Owner2", role="owner"))
    db.add(Customer(name="Bola", owner_phone="2348000002"))
    db.commit(); db.close()

    ensure_schema_updates(eng)

    db = S()
    assert db.query(Customer).filter_by(name="Bola").first().branch_id is None
    db.close()


def test_branch_scope_for_user():
    owner = User(id="o", phone="1", role="owner", parent_id=None)
    assert branch_scope_for_user(owner) == (None, False)          # all branches

    # Branch admin: full-access staff assigned to a branch → sees that branch
    branch_admin = User(id="ba", phone="2", role="delegate", parent_id="o",
                        branch_id=5, can_view_all_transactions=True)
    assert branch_scope_for_user(branch_admin) == (5, True)

    # Regular staff (even with a branch) → own records only
    regular = User(id="s", phone="3", role="delegate", parent_id="o",
                   branch_id=5, can_view_all_transactions=False)
    assert branch_scope_for_user(regular) == (None, True)

    # Full-access staff not yet assigned a branch → own records
    unassigned = User(id="s2", phone="4", role="delegate", parent_id="o",
                      branch_id=None, can_view_all_transactions=True)
    assert branch_scope_for_user(unassigned) == (None, True)
