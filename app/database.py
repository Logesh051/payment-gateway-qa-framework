"""Small SQLite helper for the simulated payment application."""

import os
import sqlite3
from contextlib import contextmanager


def database_path():
    return os.getenv("PAYMENT_DB_PATH", "payment_gateway.db")


@contextmanager
def get_connection():
    connection = sqlite3.connect(database_path())
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def init_db():
    """Create the payments table if it does not already exist."""
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id TEXT PRIMARY KEY,
                amount_rupees INTEGER NOT NULL CHECK (amount_rupees > 0),
                card_last4 TEXT NOT NULL,
                status TEXT NOT NULL,
                failure_reason TEXT,
                idempotency_key TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )
        """)
        connection.commit()
