import os
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


def normalize_database_url(url: str) -> str:
    """Normalize database URL for SQLAlchemy compatibility, converting postgres:// to postgresql://."""
    if not url:
        return url
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


RAW_DATABASE_URL = os.environ.get(
    "DUKAANVOICE_DB_URL",
    os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{Path(__file__).resolve().parent / 'dukaanvoice.db'}"
    )
)
DATABASE_URL = normalize_database_url(RAW_DATABASE_URL)

# SQLite Foreign-Key Enforcement Listener (Cross-compatible with PostgreSQL)
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# Configure engine conditionally based on dialect
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=5,
        max_overflow=10
    )

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_migrations(bind_engine=None):
    """
    Safely and idempotently applies database schema updates without data loss:
    1. Adds idempotency_key to transactions if not already present.
    2. Creates unique index for idempotency_key.
    3. Creates pending_transactions table if not already present.
    """
    target_engine = bind_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()

    # 1. Update existing transactions table with idempotency_key if missing
    if "transactions" in table_names:
        columns = [c["name"] for c in inspector.get_columns("transactions")]
        if "idempotency_key" not in columns:
            with target_engine.begin() as conn:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN idempotency_key VARCHAR(64)"))
                conn.execute(
                    text("CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_idempotency_key ON transactions(idempotency_key)")
                )

    # 2. Create pending_transactions and any new tables defined in Base.metadata
    Base.metadata.create_all(bind=target_engine)


def init_db(bind_engine=None):
    """Explicit database initialization entrypoint for deployment and server startup."""
    run_migrations(bind_engine=bind_engine)


if __name__ == "__main__":
    init_db()
