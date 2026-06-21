import os

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from sqlalchemy import create_engine, event
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

    # SQLite does not enforce FK constraints by default — enable per connection.
    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

else:
    # PostgreSQL (production): tuned for Render + cloud-managed databases
    # that terminate idle connections and use SSL-terminated load balancers.
    engine = create_engine(
        DATABASE_URL,
        pool_size=5,          # keep fewer open connections (Render free = 97 limit)
        max_overflow=10,      # allow short bursts up to 15 total
        pool_pre_ping=True,   # discard stale connections before use
        pool_recycle=120,     # recycle after 2 min — shorter than Render's idle timeout
        pool_timeout=30,      # raise after 30 s waiting for a free slot
        connect_args={
            "sslmode": "require",
            "connect_timeout": 10,
            # TCP keepalives prevent Render's load balancer from silently
            # closing idle connections mid-pool.
            "keepalives": 1,
            "keepalives_idle": 30,    # send first keepalive after 30 s idle
            "keepalives_interval": 10, # retry every 10 s
            "keepalives_count": 5,    # drop connection after 5 failed keepalives
        },
    )
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()
