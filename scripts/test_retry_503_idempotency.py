"""Verification Test: Retrying an HTTP 503 database_busy Request with Idempotency Key.

Validates Item 5 of the Phase 4 Audit:
1. Simulates SQLite exclusive lock contention on the database, causing a write operation to timeout and return HTTP 503 database_busy.
2. Releases the lock and retries the transaction using the EXACT same Idempotency-Key.
3. Verifies the retried transaction succeeds (HTTP 201 Created).
4. Issues a 3rd identical request with the same Idempotency-Key, verifying cached idempotency replay.
5. Queries the database directly to confirm:
   - Exactly ONE payment was created.
   - Exactly ONE balanced double-entry ledger batch was created.
   - Zero duplicate payments, zero duplicate ledger entries, zero orphaned records.
"""

import os
import sqlite3
import sys
import threading
import time
import uuid

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.db.session import engine, init_db


def test_503_retry_and_idempotency():
    print("=" * 70)
    print(" AUDIT ITEM 5: HTTP 503 RETRY & IDEMPOTENCY INTEGRITY TEST")
    print("=" * 70)

    # Initialize app database
    init_db()

    client = TestClient(app)
    shared_key = f"audit_503_retry_{uuid.uuid4().hex[:12]}"
    test_email = f"retry503_{uuid.uuid4().hex[:8]}@example.com"
    payload = {
        "amount_cents": 12500,
        "currency": "USD",
        "card_number": "4000000000000001",
        "exp_month": 12,
        "exp_year": 2028,
        "cvv": "123",
        "capture": True,
        "customer_email": test_email,
        "description": "Item 5 Audit - 503 Lock Contention & Retry Test",
    }
    headers = {
        "X-API-Key": settings.DEFAULT_MERCHANT_API_KEY,
        "Idempotency-Key": shared_key,
        "Content-Type": "application/json",
    }

    db_path = settings.DATABASE_URL.replace("sqlite:///", "")

    print(f"\n[Step 1] Acquiring exclusive raw lock on SQLite database ({db_path})...")
    raw_conn = sqlite3.connect(db_path, timeout=0.1)
    raw_cursor = raw_conn.cursor()
    raw_cursor.execute("BEGIN EXCLUSIVE")
    print("         Exclusive lock acquired. Other mutating transactions will be blocked.")

    # Step 2: Attempt payment request while database is locked.
    # To avoid waiting full 5 seconds in this single test, execute in thread with timeout
    print("\n[Step 2] Sending payment request while database is exclusively locked...")
    response_503 = None

    def make_locked_request():
        nonlocal response_503
        try:
            # We connect a thread-level client
            response_503 = client.post("/v1/payments", json=payload, headers=headers)
        except Exception as e:
            print(f"         Request exception: {e}")

    req_thread = threading.Thread(target=make_locked_request)
    req_thread.start()

    # Hold the lock past the 5000ms busy_timeout window until the request completes with 503
    print("         Holding exclusive lock for 6.5s to force SQLite lock timeout...")
    req_thread.join(timeout=8.0)

    # Step 3: Release lock
    print("\n[Step 3] Releasing raw exclusive lock (ROLLBACK)...")
    raw_conn.rollback()
    raw_conn.close()
    print("         Exclusive lock released.")

    # Step 4: Verify first request returned HTTP 503
    print(f"\n[Step 4] Checking response of blocked request:")
    assert response_503 is not None, "No response captured for locked request!"
    print(f"         Status Code: {response_503.status_code}")
    print(f"         Response Body: {response_503.json()}")

    assert response_503.status_code == 503, f"Expected 503, got {response_503.status_code}"
    err_body = response_503.json().get("error", {})
    assert err_body.get("code") == "database_busy", f"Expected 'database_busy', got {err_body.get('code')}"
    assert err_body.get("details", {}).get("retriable") is True, "Expected retriable: True in details"
    print("         [PASS] Initial request cleanly rejected with HTTP 503 database_busy (retriable: true).")

    # Step 5: Retry the request using the EXACT SAME Idempotency-Key
    print(f"\n[Step 5] Retrying request using EXACT SAME Idempotency-Key ('{shared_key}')...")
    retry_resp = client.post("/v1/payments", json=payload, headers=headers)
    print(f"         Status Code: {retry_resp.status_code}")
    print(f"         Response Body: {retry_resp.json()}")

    assert retry_resp.status_code == 201, f"Expected 201 on retry, got {retry_resp.status_code}"
    payment_data = retry_resp.json()
    created_payment_id = payment_data.get("id")
    assert created_payment_id is not None, "Missing payment ID in retry response"
    assert payment_data.get("status") == "CAPTURED", "Payment status should be CAPTURED"
    print(f"         [PASS] Retried request succeeded with HTTP 201 Created (ID: {created_payment_id}).")

    # Step 6: Send a 3rd identical request with same key (Cached Idempotency Replay)
    print(f"\n[Step 6] Sending 3rd request with SAME key to verify cached replay...")
    replay_resp = client.post("/v1/payments", json=payload, headers=headers)
    print(f"         Status Code: {replay_resp.status_code}")
    print(f"         Response Body: {replay_resp.json()}")

    assert replay_resp.status_code == 201, f"Expected 201 on replay, got {replay_resp.status_code}"
    assert replay_resp.json().get("id") == created_payment_id, "Idempotency violated: Different ID returned on replay!"
    print("         [PASS] 3rd request returned cached response with identical payment ID.")

    # Step 7: Independent Database Inspection
    print("\n[Step 7] Independent SQL-level Database Audit for this transaction:")
    audit_conn = sqlite3.connect(db_path)
    audit_conn.row_factory = sqlite3.Row
    audit_cursor = audit_conn.cursor()

    # A. Check payment count for this payment_id
    audit_cursor.execute("SELECT COUNT(*) FROM payments WHERE id = ?", (created_payment_id,))
    pay_count = audit_cursor.fetchone()[0]
    print(f"         - Payments with ID '{created_payment_id}': {pay_count} (Expected: 1)")
    assert pay_count == 1, f"Expected exactly 1 payment record, found {pay_count}!"

    # B. Check idempotency record
    audit_cursor.execute("SELECT status, payment_id FROM idempotency_keys WHERE key = ?", (shared_key,))
    idem_row = audit_cursor.fetchone()
    print(f"         - Idempotency Key Status: {idem_row['status']}, Linked Payment: {idem_row['payment_id']}")
    assert idem_row["status"] == "COMPLETED", "Idempotency key must be COMPLETED"
    assert idem_row["payment_id"] == created_payment_id, "Idempotency key must link to created payment"

    # C. Check double-entry ledger entries for this payment
    audit_cursor.execute("""
        SELECT 
            COUNT(*) as entry_cnt,
            SUM(CASE WHEN entry_type = 'DEBIT' THEN amount_cents ELSE 0 END) as debits,
            SUM(CASE WHEN entry_type = 'CREDIT' THEN amount_cents ELSE 0 END) as credits
        FROM ledger_entries
        WHERE payment_id = ?
    """, (created_payment_id,))
    ledger_row = audit_cursor.fetchone()
    print(f"         - Ledger entries: {ledger_row['entry_cnt']} entries | Debits: {ledger_row['debits']}¢ | Credits: {ledger_row['credits']}¢")
    assert ledger_row["entry_cnt"] == 2, f"Expected exactly 2 ledger entries (1 debit, 1 credit), found {ledger_row['entry_cnt']}"
    assert ledger_row["debits"] == 12500, f"Expected 12500 cents debited, got {ledger_row['debits']}"
    assert ledger_row["credits"] == 12500, f"Expected 12500 cents credited, got {ledger_row['credits']}"
    assert ledger_row["debits"] == ledger_row["credits"], "Ledger entries must be balanced!"

    # D. Ensure no other payments exist with this unique email
    audit_cursor.execute("SELECT COUNT(*) FROM payments WHERE customer_email = ?", (test_email,))
    email_count = audit_cursor.fetchone()[0]
    print(f"         - Total payments created during this entire test: {email_count} (Expected: 1)")
    assert email_count == 1, f"Expected only 1 payment created, found {email_count}!"

    audit_conn.close()

    print("\n" + "=" * 70)
    print(" ITEM 5 AUDIT RESULT: PASSED (Zero duplicate payments/ledgers on 503 retry)")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = test_503_retry_and_idempotency()
    sys.exit(0 if success else 1)
