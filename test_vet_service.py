"""
Veterinary Service, under Agriculture: treatments and vaccinations are
services on a price list ("Select service"), the drugs they sell are stock,
and a client's record keeps the animal's details.
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from types import SimpleNamespace as N

from biz_language import nav_names
from business_templates import (
    BUSINESS_CATEGORIES, CUSTOMER_PROFILE_FIELDS, INDUSTRY_EXAMPLES, INDUSTRY_PRODUCT_CATALOG,
    RECEIPT_CONFIG, SERVICE_PRICE_CATALOG, label_group_for_user, menu_group_for_user,
    template_key_for_user,
)

VET = N(business_type="vet_service", business_category="agriculture", parent_id=None)


def test_offered_under_agriculture():
    agric = next(c for c in BUSINESS_CATEGORIES if c["key"] == "agriculture")
    assert ("vet_service", "Veterinary Service") in agric["businesses"]
    assert agric["businesses"][-1][0] == "other_agriculture"          # "Other" stays last


def test_it_works_like_a_service_with_stock():
    assert template_key_for_user(VET) == "agriculture"
    assert menu_group_for_user(VET) == "service" and label_group_for_user(VET) == "service"
    assert nav_names(VET)["till"] == "Select service"
    assert any("vaccination" in name for name, _u, _p in SERVICE_PRICE_CATALOG["vet_service"])
    assert any("dewormer" in name for name, _c in INDUSTRY_PRODUCT_CATALOG["vet_service"])


def test_examples_receipt_and_animal_details():
    assert INDUSTRY_EXAMPLES["vet_service"]
    assert RECEIPT_CONFIG["vet_service"]["title"] == "Veterinary Receipt"
    keys = [f["key"] for f in CUSTOMER_PROFILE_FIELDS["vet_service"]]
    assert keys[:2] == ["animal", "count"]
