import os

# Provide an in-memory SQLite database for all tests that don't set their own URL.
# This must run before any module that imports database.py.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
