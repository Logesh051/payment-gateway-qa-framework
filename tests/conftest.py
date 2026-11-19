"""Pytest Configuration & Fixture Architecture.

Implements isolated test database management, read-only SQL inspection connections,
HTTP client fixtures, and test lifecycle teardown.
Guarantees that tests never modify the development database.
"""

import os
import sys
from typing import AsyncGenerator, Generator
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import httpx

# Ensure root workspace is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings
from app.db import models
from app.db.session import Base, get_db
from app.main import app
from tests.factories import AuthHeaderFactory, PaymentPayloadFactory

# Dedicated isolated test database path - NEVER touches development database (payment_gateway.db)
TEST_DB_FILE = os.path.abspath("test_isolated_gateway.db")
TEST_DATABASE_URL = f"sqlite:///{TEST_DB_FILE}"

# 1. Primary Test Engine (Used by FastAPI SUT during test execution)
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30.0},
    echo=False,
)


@event.listens_for(test_engine, "connect")
def configure_test_sqlite_pragmas(dbapi_connection, connection_record):
    """Enable WAL mode, foreign keys, and 5s busy timeout on test database."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()


TestSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=test_engine,
)

# 2. Dedicated Read-Only Test Engine (Strictly for independent test verification)
# PRAGMA query_only = ON guarantees this connection cannot mutate the database
readonly_test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30.0},
    echo=False,
)


@event.listens_for(readonly_test_engine, "connect")
def configure_readonly_pragmas(dbapi_connection, connection_record):
    """Enforce hardware-level read-only mode for QA database verifier connections."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA query_only=ON;")  # Rejects all writes with OperationalError
    cursor.close()


ReadOnlySessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=readonly_test_engine,
)


@pytest.fixture(scope="session", autouse=True)
def setup_isolated_test_database():
    """Session fixture: Creates the isolated test database, seeds default merchant,

    and removes the file upon test suite completion.
    """
    # Remove any stale test database
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except OSError:
            pass

    # Create tables in the isolated test database
    Base.metadata.create_all(bind=test_engine)

    # Seed default educational merchant in test DB
    with TestSessionLocal() as session:
        merchant = models.Merchant(
            id=settings.DEFAULT_MERCHANT_ID,
            name="Acme Educational Store (Test)",
            api_key=settings.DEFAULT_MERCHANT_API_KEY,
            webhook_secret=settings.DEFAULT_MERCHANT_WEBHOOK_SECRET,
            is_active=True,
        )
        session.add(merchant)
        session.commit()

    # Override application dependency to point to isolated test database
    def override_get_db() -> Generator[Session, None, None]:
        db = TestSessionLocal()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    yield

    # Teardown: clear overrides and clean up test database files
    app.dependency_overrides.clear()
    test_engine.dispose()
    readonly_test_engine.dispose()

    # Clean up test DB and SQLite WAL artifacts
    for ext in ["", "-wal", "-shm"]:
        target = f"{TEST_DB_FILE}{ext}"
        if os.path.exists(target):
            try:
                os.remove(target)
            except OSError:
                pass


@pytest.fixture
def readonly_db() -> Generator[Session, None, None]:
    """Provides a guaranteed read-only database session for independent QA inspection.

    Any attempt to execute an INSERT/UPDATE/DELETE on this session will raise:
    sqlite3.OperationalError: attempt to write a readonly database.
    """
    session = ReadOnlySessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
async def async_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Asynchronous HTTP client wired to the FastAPI application via ASGITransport."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
def sync_client() -> Generator[httpx.Client, None, None]:
    """Synchronous HTTP client for multi-threaded concurrency testing."""
    from starlette.testclient import TestClient
    with TestClient(app) as client:
        yield client


@pytest.fixture
def auth_headers() -> dict:
    """Default headers with valid merchant API key and JSON content type."""
    return AuthHeaderFactory.create()


@pytest.fixture
def payload_factory():
    """Fixture providing PaymentPayloadFactory for test cases."""
    return PaymentPayloadFactory
