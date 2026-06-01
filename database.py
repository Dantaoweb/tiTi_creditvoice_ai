import os

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool


if load_dotenv:
    load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set")

_is_sqlite = DATABASE_URL.startswith("sqlite")

if _is_sqlite:
    # SQLite (used in tests): StaticPool keeps the same in-memory connection
    # across threads; the extra Postgres pool kwargs are not supported.
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    # PostgreSQL (production): full connection pool tuning
    engine = create_engine(
        DATABASE_URL,
        pool_size=10,        # connections kept open in the pool
        max_overflow=20,     # extra connections allowed under burst load
        pool_pre_ping=True,  # test connection health before use
        pool_recycle=300,    # recycle connections every 5 min to avoid stale TCP
        pool_timeout=30,     # raise after 30 s waiting for a free slot
    )
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()
