"""API Tests: Lifecycle State Transition Invariants via HTTP.

Verifies that invalid operational transitions across public endpoints
are rejected with HTTP 409 Conflict and standard error envelopes.
"""

import pytest
import httpx
from jsonschema import validate

from tests.factories import AuthHeaderFactory, PaymentPayloadFactory
from tests.schemas.payment_schemas import ERROR_ENVELOPE_SCHEMA


@pytest.mark.state
class TestStateTransitionsApi:
    """Test Suite ID: TS-API-STATE-TRANSITIONS

    Validates that the HTTP layer enforces domain state invariants.
    """

    async def test_tc_trans_040_cannot_capture_already_captured_payment(
        self, async_client: httpx.AsyncClient
    ):
        """Test ID: TC-TRANS-040

        Scenario: Attempting to capture a payment that is already in CAPTURED status (with new key).
        Preconditions: Payment is already captured.
        Input Data: POST /v1/payments/{id}/capture with fresh idempotency key.
        Expected Result: HTTP 409 Conflict with code 'invalid_state_transition'.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        # Step 1: Create & capture
        res_pay = await async_client.post(
            "/v1/payments",
            headers=AuthHeaderFactory.create(
                idempotency_key=PaymentPayloadFactory.generate_idempotency_key("pay_cap_state")
            ),
            json=PaymentPayloadFactory.create(amount_cents=5000, capture=True),
        )
        payment_id = res_pay.json()["id"]

        # Step 2: Attempt fresh capture
        res_cap = await async_client.post(
            f"/v1/payments/{payment_id}/capture",
            headers=AuthHeaderFactory.create(
                idempotency_key=PaymentPayloadFactory.generate_idempotency_key("fresh_cap")
            ),
            json={"amount_cents": 5000},
        )

        assert res_cap.status_code == 409
        data = res_cap.json()
        validate(instance=data, schema=ERROR_ENVELOPE_SCHEMA)
        assert data["error"]["code"] == "invalid_state_transition"
        assert data["error"]["details"]["current_status"] == "CAPTURED"
        assert data["error"]["details"]["attempted_transition"] == "CAPTURED"

    async def test_tc_trans_041_cannot_cancel_captured_payment(self, async_client: httpx.AsyncClient):
        """Test ID: TC-TRANS-041

        Scenario: Attempting to cancel/void a payment after it has been captured.
        Preconditions: Payment is in CAPTURED status.
        Input Data: POST /v1/payments/{id}/cancel.
        Expected Result: HTTP 409 Conflict with code 'invalid_state_transition'.
                         (Must issue refund rather than void).
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        res_pay = await async_client.post(
            "/v1/payments",
            headers=AuthHeaderFactory.create(
                idempotency_key=PaymentPayloadFactory.generate_idempotency_key("pay_cancel_inv")
            ),
            json=PaymentPayloadFactory.create(amount_cents=6000, capture=True),
        )
        payment_id = res_pay.json()["id"]

        res_cancel = await async_client.post(
            f"/v1/payments/{payment_id}/cancel",
            headers=AuthHeaderFactory.create(
                idempotency_key=PaymentPayloadFactory.generate_idempotency_key("cancel_inv")
            ),
            json={"reason": "attempt_void_on_captured"},
        )

        assert res_cancel.status_code == 409
        data = res_cancel.json()
        validate(instance=data, schema=ERROR_ENVELOPE_SCHEMA)
        assert data["error"]["code"] == "invalid_state_transition"
        assert data["error"]["details"]["current_status"] == "CAPTURED"
        assert data["error"]["details"]["attempted_transition"] == "CANCELLED"

    async def test_tc_trans_042_cannot_refund_uncaptured_authorization(
        self, async_client: httpx.AsyncClient
    ):
        """Test ID: TC-TRANS-042

        Scenario: Attempting to issue a refund against an uncaptured authorization hold.
        Preconditions: Payment is in AUTHORIZED status (funds not captured yet).
        Input Data: POST /v1/payments/{id}/refund.
        Expected Result: HTTP 409 Conflict with code 'invalid_state_transition'.
                         (Must void/cancel instead of refunding uncaptured funds).
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        res_auth = await async_client.post(
            "/v1/payments",
            headers=AuthHeaderFactory.create(
                idempotency_key=PaymentPayloadFactory.generate_idempotency_key("auth_ref_inv")
            ),
            json=PaymentPayloadFactory.create(amount_cents=7500, capture=False),
        )
        payment_id = res_auth.json()["id"]

        res_ref = await async_client.post(
            f"/v1/payments/{payment_id}/refund",
            headers=AuthHeaderFactory.create(
                idempotency_key=PaymentPayloadFactory.generate_idempotency_key("ref_inv")
            ),
            json={"amount_cents": 2000, "reason": "refund_on_auth"},
        )

        assert res_ref.status_code == 409
        data = res_ref.json()
        validate(instance=data, schema=ERROR_ENVELOPE_SCHEMA)
        assert data["error"]["code"] == "invalid_state_transition"
        assert data["error"]["details"]["current_status"] == "AUTHORIZED"

    async def test_tc_trans_043_cannot_capture_cancelled_payment(self, async_client: httpx.AsyncClient):
        """Test ID: TC-TRANS-043

        Scenario: Attempting to capture a payment that was previously cancelled.
        Preconditions: Payment created as auth hold and subsequently cancelled.
        Input Data: POST /v1/payments/{id}/capture.
        Expected Result: HTTP 409 Conflict with code 'invalid_state_transition'.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        # Step 1: Create auth hold
        res_auth = await async_client.post(
            "/v1/payments",
            headers=AuthHeaderFactory.create(
                idempotency_key=PaymentPayloadFactory.generate_idempotency_key("auth_canc_state")
            ),
            json=PaymentPayloadFactory.create(amount_cents=4000, capture=False),
        )
        payment_id = res_auth.json()["id"]

        # Step 2: Cancel it
        await async_client.post(
            f"/v1/payments/{payment_id}/cancel",
            headers=AuthHeaderFactory.create(
                idempotency_key=PaymentPayloadFactory.generate_idempotency_key("canc_state")
            ),
            json={"reason": "cancelled_by_buyer"},
        )

        # Step 3: Attempt capture
        res_cap = await async_client.post(
            f"/v1/payments/{payment_id}/capture",
            headers=AuthHeaderFactory.create(
                idempotency_key=PaymentPayloadFactory.generate_idempotency_key("cap_after_canc")
            ),
            json={"amount_cents": 4000},
        )

        assert res_cap.status_code == 409
        data = res_cap.json()
        validate(instance=data, schema=ERROR_ENVELOPE_SCHEMA)
        assert data["error"]["code"] == "invalid_state_transition"
        assert data["error"]["details"]["current_status"] == "CANCELLED"
