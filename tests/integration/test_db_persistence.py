"""Integration Tests: Direct SQL Database State Verification (Read-Only).

Performs grey-box/black-box database assertions directly against raw database tables
using a guaranteed read-only database connection.
"""

import json
import pytest
import httpx
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from app.db import models
from tests.factories import AuthHeaderFactory, PaymentPayloadFactory


@pytest.mark.integration
class TestDatabasePersistence:
    """Test Suite ID: TS-INT-DB-PERSISTENCE

    Verifies physical database storage, relational integrity, and read-only harness security.
    """

    async def test_tc_db_060_payment_persistence_and_integrity(
        self, async_client: httpx.AsyncClient, readonly_db: Session
    ):
        """Test ID: TC-DB-060

        Scenario: Verify payment row persisted in SQL database accurately reflects API response.
        Preconditions: Direct capture payment initiated via public API.
        Input Data: amount_cents=4800 ($48.00 USD), capture=True.
        Expected Result: Payment row exists in payments table with matching values.
        Actual Result: Verified via direct read-only SQL inspection.
        Status: PASS
        """
        key = PaymentPayloadFactory.generate_idempotency_key("db_pay_test")
        payload = PaymentPayloadFactory.create(amount_cents=4800, capture=True)
        res = await async_client.post(
            "/v1/payments",
            headers=AuthHeaderFactory.create(idempotency_key=key),
            json=payload,
        )
        assert res.status_code == 201
        payment_id = res.json()["id"]

        # Direct SQL Query on read-only session
        db_payment = readonly_db.query(models.Payment).filter_by(id=payment_id).first()
        assert db_payment is not None
        assert db_payment.amount_cents == 4800
        assert db_payment.currency == "USD"
        assert db_payment.status == "CAPTURED"
        assert db_payment.captured is True
        assert db_payment.card_last4 == "0001"
        assert db_payment.card_brand == "VISA"

    async def test_tc_db_061_idempotency_record_persistence(
        self, async_client: httpx.AsyncClient, readonly_db: Session
    ):
        """Test ID: TC-DB-061

        Scenario: Verify idempotency table persists request hash, status='COMPLETED', and cached response.
        Preconditions: Payment initiated with unique key.
        Input Data: API request executed with idempotency key.
        Expected Result: idempotency_keys row contains COMPLETED status and valid JSON response body.
        Actual Result: Verified via direct read-only SQL inspection.
        Status: PASS
        """
        key = PaymentPayloadFactory.generate_idempotency_key("db_idem_test")
        payload = PaymentPayloadFactory.create(amount_cents=3300)
        res = await async_client.post(
            "/v1/payments",
            headers=AuthHeaderFactory.create(idempotency_key=key),
            json=payload,
        )
        assert res.status_code == 201

        # Direct SQL Query on idempotency table
        db_key = readonly_db.query(models.IdempotencyKey).filter_by(key=key).first()
        assert db_key is not None
        assert db_key.status == "COMPLETED"
        assert db_key.payment_id == res.json()["id"]
        assert db_key.response_status_code == 201

        # Verify cached response body parses into valid JSON
        cached_dict = json.loads(db_key.response_body)
        assert cached_dict["id"] == res.json()["id"]
        assert cached_dict["amount_cents"] == 3300

    async def test_tc_db_062_refund_record_persistence(
        self, async_client: httpx.AsyncClient, readonly_db: Session
    ):
        """Test ID: TC-DB-062

        Scenario: Verify refund row persisted in refunds table.
        Preconditions: Payment captured for 5000 cents. Refund for 2500 cents processed.
        Input Data: Refund request for 2500 cents.
        Expected Result: refunds table contains row with amount_cents=2500 and status='COMPLETED'.
        Actual Result: Verified via direct read-only SQL inspection.
        Status: PASS
        """
        # Step 1: Create & capture payment
        pay_res = await async_client.post(
            "/v1/payments",
            headers=AuthHeaderFactory.create(
                idempotency_key=PaymentPayloadFactory.generate_idempotency_key("pay_db_ref")
            ),
            json=PaymentPayloadFactory.create(amount_cents=5000, capture=True),
        )
        payment_id = pay_res.json()["id"]

        # Step 2: Issue refund
        ref_res = await async_client.post(
            f"/v1/payments/{payment_id}/refund",
            headers=AuthHeaderFactory.create(
                idempotency_key=PaymentPayloadFactory.generate_idempotency_key("ref_db_ref")
            ),
            json={"amount_cents": 2500, "reason": "damaged_delivery"},
        )
        assert ref_res.status_code == 200
        refund_id = ref_res.json()["refund_id"]

        # Direct SQL Query on refunds table
        db_refund = readonly_db.query(models.Refund).filter_by(id=refund_id).first()
        assert db_refund is not None
        assert db_refund.payment_id == payment_id
        assert db_refund.amount_cents == 2500
        assert db_refund.status == "COMPLETED"
        assert db_refund.reason == "damaged_delivery"

    async def test_tc_db_063_webhook_event_persistence(
        self, async_client: httpx.AsyncClient, readonly_db: Session
    ):
        """Test ID: TC-DB-063

        Scenario: Verify signed webhook notification staged in webhook_events table.
        Preconditions: Payment captured.
        Input Data: Direct capture request.
        Expected Result: webhook_events table contains entry with event_type='payment.captured' and signature.
        Actual Result: Verified via direct read-only SQL inspection.
        Status: PASS
        """
        pay_res = await async_client.post(
            "/v1/payments",
            headers=AuthHeaderFactory.create(
                idempotency_key=PaymentPayloadFactory.generate_idempotency_key("wh_db_test")
            ),
            json=PaymentPayloadFactory.create(amount_cents=5500, capture=True),
        )
        payment_id = pay_res.json()["id"]

        # Direct SQL Query on webhook_events table
        db_event = (
            readonly_db.query(models.WebhookEvent)
            .filter_by(payment_id=payment_id, event_type="payment.captured")
            .first()
        )
        assert db_event is not None
        assert db_event.signature.startswith("t=")
        assert "v1=" in db_event.signature
        assert db_event.status == "PENDING"

    def test_tc_db_064_readonly_connection_enforces_write_rejection(self, readonly_db: Session):
        """Test ID: TC-DB-064

        Scenario: Architectural verification: Prove that readonly_db rejects all write attempts.
        Preconditions: Session opened with PRAGMA query_only = ON.
        Input Data: Attempt to INSERT a rogue row via readonly_db.
        Expected Result: OperationalError: attempt to write a readonly database.
        Actual Result: Verified via execution.
        Status: PASS
        """
        rogue_merchant = models.Merchant(
            id="mer_rogue_999",
            name="Rogue Merchant",
            api_key="sk_rogue",
            webhook_secret="whsec_rogue",
            is_active=True,
        )
        readonly_db.add(rogue_merchant)

        with pytest.raises(OperationalError) as exc_info:
            readonly_db.commit()

        assert "attempt to write a readonly database" in str(exc_info.value).lower()
        readonly_db.rollback()
