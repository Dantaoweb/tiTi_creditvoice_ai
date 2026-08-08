"""
Public SEO surface: crawlable landing page at /, robots.txt, and sitemap.xml.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-landing-00000000000000")

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_home_is_crawlable_html_with_seo_tags():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    # Real server-rendered content (not an empty SPA shell).
    assert "CreditVoice" in body
    assert "<h1" in body
    # SEO essentials present.
    assert '<link rel="canonical" href="https://creditvoiceai.com/"' in body
    assert 'property="og:title"' in body
    assert 'name="twitter:card"' in body
    assert 'application/ld+json' in body
    assert '"FAQPage"' in body
    # Template placeholders were substituted (and the raw file uses HTML
    # comments so it validates clean in editors).
    assert "<!--WA_BUTTON-->" not in body and "<!--GSC_META-->" not in body
    assert "%%" not in body


def test_head_home_ok():
    assert client.head("/").status_code == 200


def test_robots_points_to_sitemap():
    r = client.get("/robots.txt")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert "Sitemap: https://creditvoiceai.com/sitemap.xml" in r.text
    assert "Disallow: /app/api/" in r.text


def test_sitemap_lists_home():
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "xml" in r.headers["content-type"]
    assert "<loc>https://creditvoiceai.com/</loc>" in r.text
    assert "<urlset" in r.text


def test_gsc_meta_injected_when_env_set(monkeypatch):
    monkeypatch.setenv("GOOGLE_SITE_VERIFICATION", "abc123token")
    body = client.get("/").text
    assert '<meta name="google-site-verification" content="abc123token"' in body
