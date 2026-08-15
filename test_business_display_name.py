"""
Receipts must never print the generic business-TYPE label (e.g. "Crop Produce
Trader") as if it were the business's NAME. business_display_name() falls back to
the owner's name in that case, but keeps a real custom business label.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-bizname-0000000000000")

from business_templates import business_display_name


class _U:
    def __init__(self, name=None, business_type=None, business_type_label=None):
        self.name = name
        self.business_type = business_type
        self.business_type_label = business_type_label


def test_generic_type_label_is_not_used_as_business_name():
    # Label still equals the generic type → show the owner's name instead.
    u = _U(name="Bayo", business_type="produce_trader", business_type_label="Crop Produce Trader")
    assert business_display_name(u) == "Bayo"


def test_custom_business_name_is_kept():
    u = _U(name="Bayo", business_type="produce_trader", business_type_label="Bayo Farms Ltd")
    assert business_display_name(u) == "Bayo Farms Ltd"


def test_no_label_falls_back_to_name():
    u = _U(name="Bayo", business_type="produce_trader", business_type_label=None)
    assert business_display_name(u) == "Bayo"


def test_case_insensitive_generic_match():
    u = _U(name="Bayo", business_type="produce_trader", business_type_label="crop produce trader")
    assert business_display_name(u) == "Bayo"


def test_none_user():
    assert business_display_name(None) == "Your business"
