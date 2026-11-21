"""Independent check that a payment is saved in SQLite."""

import os
import sqlite3
from tests.test_payment_api import make_payment


def test_successful_payment_is_saved_in_database(client):
    response = make_payment(client, amount=750, key="db-check-1")
    assert response.status_code == 201
    connection = sqlite3.connect(os.environ["PAYMENT_DB_PATH"])
    try:
        row = connection.execute(
            "SELECT amount_rupees, status FROM payments WHERE id = ?",
            (response.json()["id"],),
        ).fetchone()
    finally:
        connection.close()
    assert row == (750, "SUCCESS")
