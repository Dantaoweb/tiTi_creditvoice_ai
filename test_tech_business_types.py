"""
Technology / IT / Fintech businesses get the setup that matches how they work:
services are fees from clients (no stock), repairs and installs are jobs like
phone repair, and computer sales is a shop.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from types import SimpleNamespace as N

import pytest

from business_templates import (
    BUSINESS_CATEGORIES, CUSTOMER_PROFILE_FIELDS, INDUSTRY_EXAMPLES, INDUSTRY_PRODUCT_CATALOG,
    SERVICE_PRICE_CATALOG, label_group_for_user, menu_group_for_user,
)

TECH = next(c for c in BUSINESS_CATEGORIES if c["key"] == "technology_fintech")


def _user(bt):
    return N(business_type=bt, business_category="technology_fintech", parent_id=None)


def test_the_category_is_offered_before_other():
    keys = [c["key"] for c in BUSINESS_CATEGORIES]
    assert keys.index("technology_fintech") == len(keys) - 2 and keys[-1] == "other"
    assert TECH["label"] == "Technology / IT / Fintech"
    assert len(TECH["businesses"]) == 10


@pytest.mark.parametrize("bt, menu, words", [
    ("software_development", "fee", "professional"),
    ("web_digital_agency", "fee", "professional"),
    ("digital_marketing", "fee", "professional"),
    ("fintech_company", "fee", "professional"),
    ("pos_agent", "fee", "professional"),
    ("tech_training", "fee", "professional"),
    ("other_tech", "fee", "professional"),
    ("it_support", "service", "service"),
    ("computer_repair", "service", "service"),
    ("computer_sales", "stock", "stock"),
])
def test_each_type_behaves_like_its_kind(bt, menu, words):
    u = _user(bt)
    assert menu_group_for_user(u) == menu
    assert label_group_for_user(u) == words


def test_every_type_has_examples_and_a_price_list_or_catalogue():
    for bt, _label in TECH["businesses"]:
        if bt == "other_tech":
            continue
        assert INDUSTRY_EXAMPLES.get(bt), bt
        assert SERVICE_PRICE_CATALOG.get(bt) or INDUSTRY_PRODUCT_CATALOG.get(bt), bt


def test_computer_repair_records_the_device():
    keys = [f["key"] for f in CUSTOMER_PROFILE_FIELDS["computer_repair"]]
    assert {"device", "serial", "fault"} <= set(keys)
