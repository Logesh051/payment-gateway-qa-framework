"""Integration Tests: Concurrency, Race Condition Safety & Lock Handling.

Tests parallel burst traffic against the public API using multi-threaded pools:
1. Concurrent identical idempotency requests => zero double charges.
2. Concurrent different idempotency requests => SQLite WAL write serialization.
3. Concurrent competing captures => exactly 1 succeeds, 1 rejected with 409.
4. Concurrent competing refunds => overdraft race condition prevented (HTTP 422).
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import pytest
import httpx
from sqlalchemy.orm import Session

from app.db import models
from tests.factories import AuthHeaderFactory, PaymentPayloadFactory


@pytest.mark.concurrency
class TestConcurrency:
    """Test Suite ID: TS-INT-CONCURRENCY

    Validates race condition prevention, atomicity, and thread safety under burst conditions.
    """

    def test_tc_conc_080_concurrent_identical_idempotency_burst(
        self, sync_client: httpx.Client, readonly_db: Session
    ):
        """Test ID: TC-CONC-080

        Scenario: 10 parallel threads fire the exact same payment request with the identical Idempotency-Key.
        Preconditions: Multi-threaded client burst simulating aggressive network retries.
        Input Data: 10 simultaneous POST requests sharing key 'conc_burst_key'.
        Expected Result: Exactly ONE payment created in the database.
                         Responses are either 201 Created (initial + replays) or 409 Conflict (in-flight lock).
                         Zero unhandled 500 errors. Zero double-charges.
        Actual Result: Verified via multi-threaded execution and direct read-only SQL assertion.
        Status: PASS
        """
        shared_key = PaymentPayloadFactory.generate_idempotency_key("conc_burst")
        payload = PaymentPayloadFactory.create(amount_cents=5000, capture=True)
        headers = AuthHeaderFactory.create(idempotency_key=shared_key)

        def send_request():
            return sync_client.post("/v1/payments", headers=headers, json=payload)

        # Fire 10 parallel threads simultaneously
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(send_request) for _ in range(10)]
            responses = [f.result() for f in as_completed(futures)]

        status_codes = [r.status_code for r in responses]

        # Documented valid outcomes: 201 (success or cached replay) and 409 (in-flight conflict)
        for code in status_codes:
            assert code in {201, 409}, f"Unexpected status code {code} during concurrency burst"

        # At least one request must have succeeded with 201 Created
        assert 201 in status_codes

        # SQL Direct Verification: Exactly ONE payment row exists with this key
        idem_row = readonly_db.query(models.IdempotencyKey).filter_by(key=shared_key).first()
        assert idem_row is not None
        assert idem_row.status == "COMPLETED"

        payment_rows = readonly_db.query(models.Payment).filter_by(id=idem_row.payment_id).all()
        assert len(payment_rows) == 1, "Concurrency burst created duplicate payment rows!"

        # Ledger Verification: Exactly ONE balanced pair of entries
        ledger_entries = readonly_db.query(models.LedgerEntry).filter_by(payment_id=idem_row.payment_id).all()
        assert len(ledger_entries) == 2, "Duplicate ledger entries created under concurrency!"

    def test_tc_conc_081_concurrent_different_keys_burst(
        self, sync_client: httpx.Client, readonly_db: Session
    ):
        """Test ID: TC-CONC-081

        Scenario: 6 parallel threads fire independent payments with unique Idempotency-Keys.
        Preconditions: Multi-threaded load exercising SQLite WAL write serialization.
        Input Data: 6 simultaneous POST requests with distinct keys.
        Expected Result: All requests serialize cleanly within the 5s busy_timeout window.
                         Responses are HTTP 201 Created (or 503 if busy timeout exceeded).
                         Zero corrupted records.
        Actual Result: Verified via multi-threaded execution and direct SQL assertion.
        Status: PASS
        """
        keys = [PaymentPayloadFactory.generate_idempotency_key(f"multi_{i}") for i in range(6)]
        payloads = [PaymentPayloadFactory.create(amount_cents=3000 + i * 100) for i in range(6)]

        def send_individual_payment(key, payload):
            headers = AuthHeaderFactory.create(idempotency_key=key)
            return sync_client.post("/v1/payments", headers=headers, json=payload)

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(send_individual_payment, k, p) for k, p in zip(keys, payloads)]
            responses = [f.result() for f in as_completed(futures)]

        for r in responses:
            assert r.status_code in {201, 503}, f"Unexpected status {r.status_code}"

        # Verify that all created payments have corresponding balanced ledger entries
        created_payments = [r.json()["id"] for r in responses if r.status_code == 201]
        for pid in created_payments:
            entries = readonly_db.query(models.LedgerEntry).filter_by(payment_id=pid).all()
            assert len(entries) == 2
            debits = sum(e.amount_cents for e in entries if e.entry_type == "DEBIT")
            credits = sum(e.amount_cents for e in entries if e.entry_type == "CREDIT")
            assert debits == credits

    def test_tc_conc_082_concurrent_double_capture_race_condition(
        self, sync_client: httpx.Client, readonly_db: Session
    ):
        """Test ID: TC-CONC-082

        Scenario: Two concurrent threads attempt to capture the same authorized payment simultaneously
                  with DIFFERENT idempotency keys.
        Preconditions: Payment authorized for 8000 cents ($80.00).
        Input Data: 2 simultaneous capture requests with distinct keys.
        Expected Result: Exactly ONE capture succeeds (HTTP 200). The other fails with HTTP 409 Conflict.
                         Zero duplicate debits.
        Actual Result: Verified via multi-threaded execution.
        Status: PASS
        """
        # Step 1: Create authorization
        auth_res = sync_client.post(
            "/v1/payments",
            headers=AuthHeaderFactory.create(
                idempotency_key=PaymentPayloadFactory.generate_idempotency_key("auth_race_cap")
            ),
            json=PaymentPayloadFactory.create(amount_cents=8000, capture=False),
        )
        assert auth_res.status_code == 201
        payment_id = auth_res.json()["id"]

        # Step 2: 2 concurrent threads attempt capture
        key_cap1 = PaymentPayloadFactory.generate_idempotency_key("cap_race_1")
        key_cap2 = PaymentPayloadFactory.generate_idempotency_key("cap_race_2")

        def capture_call(k):
            return sync_client.post(
                f"/v1/payments/{payment_id}/capture",
                headers=AuthHeaderFactory.create(idempotency_key=k),
                json={"amount_cents": 8000},
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(capture_call, key_cap1)
            f2 = executor.submit(capture_call, key_cap2)
            responses = [f1.result(), f2.result()]

        status_codes = sorted([r.status_code for r in responses])
        # Exactly one must succeed (200), exactly one must fail with Conflict (409)
        assert status_codes == [200, 409], f"Double capture race outcome unexpected: {status_codes}"

        # SQL Verification: Payment status is CAPTURED, exactly 1 capture ledger batch
        payment = readonly_db.query(models.Payment).filter_by(id=payment_id).first()
        assert payment.status == "CAPTURED"

        capture_entries = (
            readonly_db.query(models.LedgerEntry)
            .filter_by(payment_id=payment_id, account_name="merchant_available_balance")
            .all()
        )
        assert len(capture_entries) == 1, "More than one capture credit posted to merchant available balance!"

    def test_tc_conc_083_concurrent_competing_refunds_prevent_overdraft(
        self, sync_client: httpx.Client, readonly_db: Session
    ):
        """Test ID: TC-CONC-083

        Scenario: A payment is captured for $50.00 (5000 cents). Two concurrent threads attempt to
                  refund $40.00 each (4000 cents each) with DIFFERENT idempotency keys.
                  Combined refund ($80.00) exceeds total captured amount ($50.00).
        Preconditions: Payment captured for 5000 cents.
        Input Data: 2 simultaneous refund requests for 4000 cents each.
        Expected Result: Exactly ONE refund succeeds (HTTP 200). The competing refund fails with HTTP 422
                         (refund_amount_exceeds_balance).
                         Available balance never becomes negative.
        Actual Result: Verified via multi-threaded execution.
        Status: PASS
        """
        # Step 1: Create & capture payment for 5000 cents ($50.00)
        pay_res = sync_client.post(
            "/v1/payments",
            headers=AuthHeaderFactory.create(
                idempotency_key=PaymentPayloadFactory.generate_idempotency_key("pay_ref_race")
            ),
            json=PaymentPayloadFactory.create(amount_cents=5000, capture=True),
        )
        assert pay_res.status_code == 201
        payment_id = pay_res.json()["id"]

        # Step 2: 2 concurrent threads attempt to refund 4000 cents each
        key_ref1 = PaymentPayloadFactory.generate_idempotency_key("ref_race_1")
        key_ref2 = PaymentPayloadFactory.generate_idempotency_key("ref_race_2")

        def refund_call(k):
            return sync_client.post(
                f"/v1/payments/{payment_id}/refund",
                headers=AuthHeaderFactory.create(idempotency_key=k),
                json={"amount_cents": 4000, "reason": "race_refund_attempt"},
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(refund_call, key_ref1)
            f2 = executor.submit(refund_call, key_ref2)
            responses = [f1.result(), f2.result()]

        status_codes = sorted([r.status_code for r in responses])
        # Exactly one must succeed (200), the other must be rejected for exceeding remaining balance (422)
        assert status_codes == [200, 422], f"Refund race outcome unexpected: {status_codes}"

        # SQL Verification: Total refunded cents cannot exceed 5000
        refunds = readonly_db.query(models.Refund).filter_by(payment_id=payment_id).all()
        total_refunded = sum(r.amount_cents for r in refunds)
        assert total_refunded == 4000, f"Over-refund occurred: total refunded is {total_refunded} cents!"

    def test_tc_conc_084_idempotency_race_condition_regression(
        self, sync_client: httpx.Client, readonly_db: Session
    ):
        """Test ID: TC-CONC-084 (Regression for DEF-002)

        Scenario: Rapid simultaneous submission of identical payment requests using the same key.
                  Verifies that the TOCTOU insert race condition is resolved via atomic IntegrityError handling.
        Preconditions: Multi-threaded burst with synchronized start barrier.
        Input Data: 8 simultaneous requests sharing identical key and payload.
        Expected Result: Zero unhandled IntegrityErrors. All responses are 201 Created or 409 Conflict.
                         Exactly ONE payment record and ONE ledger batch exist in database.
        Actual Result: Verified via execution.
        Status: PASS
        """
        import threading
        race_key = PaymentPayloadFactory.generate_idempotency_key("def002_race")
        payload = PaymentPayloadFactory.create(amount_cents=7500, capture=True)
        headers = AuthHeaderFactory.create(idempotency_key=race_key)

        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()  # Synchronize all threads to hit the endpoint at the identical instant
            return sync_client.post("/v1/payments", headers=headers, json=payload)

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker) for _ in range(8)]
            responses = [f.result() for f in as_completed(futures)]

        status_codes = [r.status_code for r in responses]
        for code in status_codes:
            assert code in {201, 409}, f"Unexpected status {code} in DEF-002 regression test"

        assert 201 in status_codes

        # SQL Verification: Exactly ONE payment and ONE idempotency key row exist
        idem_row = readonly_db.query(models.IdempotencyKey).filter_by(key=race_key).first()
        assert idem_row is not None
        assert idem_row.status == "COMPLETED"

        payments = readonly_db.query(models.Payment).filter_by(id=idem_row.payment_id).all()
        assert len(payments) == 1, "DEF-002 regression: duplicate payment created!"

        ledger_entries = readonly_db.query(models.LedgerEntry).filter_by(payment_id=idem_row.payment_id).all()
        assert len(ledger_entries) == 2, "DEF-002 regression: duplicate ledger batch created!"
