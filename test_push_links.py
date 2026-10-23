"""
Phone notifications open the page they're about (still behind the login),
and the owner can hide amounts and names on the lock screen.
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from web_push import app_url, private_text


def test_tap_opens_the_page_it_is_about():
    assert app_url("/payment-claims") == "/app/payment-claims"
    assert app_url("/stock-counts/12") == "/app/stock-counts/12"
    assert app_url("/inventory?expiry=1") == "/app/inventory?expiry=1"
    assert app_url("/app/waybills/3") == "/app/waybills/3"
    assert app_url(None) == "/app"


def test_private_lock_screen_text_has_no_names_or_amounts():
    title, body = private_text("payment_claim")
    assert title == "You have a payment to confirm" and "₦" not in title + body
    assert private_text("something_new")[0] == "New alert in CreditVoice"


def test_the_setting_defaults_to_showing_details():
    from app_settings import BUSINESS_DEFAULTS
    assert BUSINESS_DEFAULTS["push_hide_details"] is False
