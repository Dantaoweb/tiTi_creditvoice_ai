"""
PWA install files must be served as real files (correct content types), not
swallowed by the SPA catch-all — otherwise Add-to-Home-Screen breaks.
"""
import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-pwa-000000000000000000")

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_manifest_served_as_manifest():
    r = client.get("/app/manifest.webmanifest")
    assert r.status_code == 200
    assert "manifest" in r.headers["content-type"]
    data = json.loads(r.text)
    assert data["start_url"] == "/app"
    assert data["display"] == "standalone"
    assert any(i["src"].endswith("pwa-192.png") for i in data["icons"])


def test_service_worker_served_as_javascript():
    r = client.get("/app/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    # A fetch handler is what makes the app installable.
    assert "addEventListener" in r.text and "fetch" in r.text


def test_pwa_icons_served_as_png():
    for path in ("/app/pwa-192.png", "/app/pwa-512.png"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"


def test_index_links_manifest():
    r = client.get("/app")
    assert r.status_code == 200
    assert 'rel="manifest"' in r.text
