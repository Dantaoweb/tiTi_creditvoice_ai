"""Responses are gzip-compressed for clients that accept it (mobile data)."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("WEB_SECRET_KEY", "test-secret-key-for-gzip-00000000000000000000000")

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_large_response_is_gzipped():
    r = client.get("/", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"
    assert "<html" in r.text.lower()   # client transparently decodes


def test_no_gzip_when_not_accepted():
    r = client.get("/", headers={"Accept-Encoding": "identity"})
    assert r.status_code == 200
    assert "content-encoding" not in r.headers


def test_small_response_not_gzipped():
    r = client.get("/app/api/auth/me", headers={"Accept-Encoding": "gzip"})   # tiny 401
    assert len(r.content) < 1024
    assert "content-encoding" not in r.headers
