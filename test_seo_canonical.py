"""
The SPA shell is served path-aware so Search Console no longer flags duplicate
content: each page carries a self-referencing canonical, the public legal pages
get distinct titles, and every app screen is served noindex.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-seo-000000000000000000")

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_app_root_is_noindex_with_self_canonical():
    html = client.get("/app").text
    assert '<link rel="canonical" href="https://creditvoiceai.com/app" />' in html
    assert '<meta name="robots" content="noindex,follow" />' in html


def test_terms_is_indexable_with_own_title_and_canonical():
    html = client.get("/app/terms").text
    assert '<link rel="canonical" href="https://creditvoiceai.com/app/terms" />' in html
    assert "<title>Terms of Service — CreditVoice</title>" in html
    assert "noindex" not in html  # public content page must stay indexable


def test_privacy_is_indexable_with_own_title():
    html = client.get("/app/privacy").text
    assert '<link rel="canonical" href="https://creditvoiceai.com/app/privacy" />' in html
    assert "<title>Privacy Policy — CreditVoice</title>" in html
    assert "noindex" not in html


def test_dashboard_screen_is_noindex():
    html = client.get("/app/dashboard").text
    assert '<meta name="robots" content="noindex,follow" />' in html
    assert '<link rel="canonical" href="https://creditvoiceai.com/app/dashboard" />' in html


def test_sitemap_lists_only_indexable_pages():
    xml = client.get("/sitemap.xml").text
    assert "https://creditvoiceai.com/app/terms" in xml
    assert "https://creditvoiceai.com/app/privacy" in xml
    # The bare /app app shell is noindex, so it must not be advertised.
    assert "<loc>https://creditvoiceai.com/app</loc>" not in xml


def test_default_description_drops_informal():
    html = client.get("/app").text
    assert "informal" not in html
