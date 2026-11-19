"""Database Session & SQLite WAL Connection Management.

Configures SQLAlchemy 2.0 engine with SQLite Write-Ahead Logging (WAL) mode,
5-second busy timeout for concurrent lock contention handling, and
foreign key constraint enforcement.
"""

from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.core.config import settings

# Engine configuration for SQLite
# check_same_thread=False allows FastAPI threads to interact safely with pooled connections
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={
        "check_same_thread": False,
        "timeout": 30.0,  # OS-level socket timeout
    },
    echo=False,
)


@event.listens_for(engine, "connect")
def configure_sqlite_pragmas(dbapi_connection, connection_record):
    """Enforce WAL mode, foreign keys, and busy timeout on every SQLite connection.

    1. PRAGMA journal_mode=WAL: Enables concurrent readers alongside an active writer.
    2. PRAGMA busy_timeout: Retries locked tables automatically for up to 5000ms.
    3. PRAGMA foreign_keys=ON: Enforces relational referential integrity.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute(f"PRAGMA busy_timeout={settings.SQLITE_BUSY_TIMEOUT_MS};")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding an isolated database session."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create all tables and seed default educational test merchant if not present."""
    from app.db import models  # Ensure all model entities are registered with Base

    Base.metadata.create_all(bind=engine)

    # Seed default educational merchant for instant local API testing
    with SessionLocal() as db:
        merchant = db.query(models.Merchant).filter_by(id=settings.DEFAULT_MERCHANT_ID).first()
        if not merchant:
            default_merchant = models.Merchant(
                id=settings.DEFAULT_MERCHANT_ID,
                name="Acme Educational Store",
                api_key=settings.DEFAULT_MERCHANT_API_KEY,
                webhook_secret=settings.DEFAULT_MERCHANT_WEBHOOK_SECRET,
                is_active=True,
            )
            db.add(default_merchant)
            db.commit()
