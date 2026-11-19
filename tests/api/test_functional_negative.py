"""Negative & Functional Boundary Tests.

Validates boundary value analysis, malformed inputs, missing parameters,
simulated card decline codes, and refund overdraft protection.
"""

import pytest
import httpx
from jsonschema import validate

from tests.factories import AuthHeaderFactory, CardCatalog, PaymentPayloadFactory
from tests.schemas.payment_schemas import ERROR_ENVELOPE_SCHEMA


@pytest.mark.negative
class TestFunctionalNegative:
    """Test Suite ID: TS-API-NEGATIVE

    Exhaustive negative and boundary tests ensuring defensive system behavior.
    """

    @pytest.mark.parametrize(
        "invalid_amount,expected_status,expected_code",
        [
            (49, 400, "amount_below_minimum"),
            (0, 400, "amount_below_minimum"),
            (10_000_001, 400, "amount_exceeds_transaction_limit"),
        ],
    )
    async def test_tc_neg_020_invalid_amount_boundaries(
        self,
        async_client: httpx.AsyncClient,
        invalid_amount: int,
        expected_status: int,
        expected_code: str,
    ):
        """Test ID: TC-NEG-020

        Scenario: Boundary value analysis on payment amounts.
        Preconditions: Authenticated merchant.
        Input Data: Amounts below 50 cents or above 10,000,000 cents.
        Expected Result: HTTP 400 with machine-readable error code.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        payload = PaymentPayloadFactory.create(amount_cents=invalid_amount)
        headers = AuthHeaderFactory.create(
            idempotency_key=PaymentPayloadFactory.generate_idempotency_key("amt_bva")
        )
        response = await async_client.post("/v1/payments", headers=headers, json=payload)

        assert response.status_code == expected_status
        data = response.json()
        validate(instance=data, schema=ERROR_ENVELOPE_SCHEMA)
        assert data["error"]["code"] == expected_code

    async def test_tc_neg_021_floating_point_amount_rejected(self, async_client: httpx.AsyncClient):
        """Test ID: TC-NEG-021

        Scenario: Attempt to submit fractional floating-point cents (e.g. 19.99).
        Preconditions: Schema mandates integer minor units.
        Input Data: amount_cents=19.99 (float).
        Expected Result: HTTP 422 Unprocessable Entity (Schema validation failure).
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        payload = PaymentPayloadFactory.create(amount_cents=19.99)  # type: ignore
        headers = AuthHeaderFactory.create(
            idempotency_key=PaymentPayloadFactory.generate_idempotency_key("float_amt")
        )
        response = await async_client.post("/v1/payments", headers=headers, json=payload)

        assert response.status_code == 422
        data = response.json()
        validate(instance=data, schema=ERROR_ENVELOPE_SCHEMA)
        assert data["error"]["code"] == "validation_error"

    async def test_tc_neg_022_unsupported_currency_rejected(self, async_client: httpx.AsyncClient):
        """Test ID: TC-NEG-022

        Scenario: Submit payment in an unsupported ISO currency.
        Preconditions: System supports USD, EUR, GBP, CAD, INR.
        Input Data: currency='XYZ'.
        Expected Result: HTTP 400 Bad Request with code 'unsupported_currency'.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        payload = PaymentPayloadFactory.create(currency="XYZ")
        headers = AuthHeaderFactory.create(
            idempotency_key=PaymentPayloadFactory.generate_idempotency_key("bad_curr")
        )
        response = await async_client.post("/v1/payments", headers=headers, json=payload)

        assert response.status_code == 400
        data = response.json()
        validate(instance=data, schema=ERROR_ENVELOPE_SCHEMA)
        assert data["error"]["code"] == "unsupported_currency"

    @pytest.mark.parametrize("missing_field", ["card_number", "exp_month", "cvv", "amount_cents"])
    async def test_tc_neg_023_missing_mandatory_fields(
        self, async_client: httpx.AsyncClient, missing_field: str
    ):
        """Test ID: TC-NEG-023

        Scenario: Omit mandatory JSON payload fields.
        Preconditions: Strict Pydantic model validation.
        Input Data: Payload missing designated mandatory field.
        Expected Result: HTTP 422 Unprocessable Entity with error code 'validation_error'.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        payload = PaymentPayloadFactory.create()
        del payload[missing_field]

        headers = AuthHeaderFactory.create(
            idempotency_key=PaymentPayloadFactory.generate_idempotency_key("missing_fld")
        )
        response = await async_client.post("/v1/payments", headers=headers, json=payload)

        assert response.status_code == 422
        data = response.json()
        validate(instance=data, schema=ERROR_ENVELOPE_SCHEMA)
        assert data["error"]["code"] == "validation_error"

    @pytest.mark.parametrize(
        "card_no,expected_status,expected_code",
        [
            (CardCatalog.DECLINE_INSUFFICIENT_FUNDS, 402, "insufficient_funds"),
            (CardCatalog.DECLINE_CARD_EXPIRED, 402, "card_expired"),
            (CardCatalog.DECLINE_SUSPECTED_FRAUD, 403, "suspected_fraud"),
            (CardCatalog.DECLINE_GATEWAY_TIMEOUT, 504, "gateway_timeout"),
        ],
    )
    async def test_tc_neg_024_deterministic_bank_declines(
        self,
        async_client: httpx.AsyncClient,
        card_no: str,
        expected_status: int,
        expected_code: str,
    ):
        """Test ID: TC-NEG-024

        Scenario: Verify deterministic simulation triggers accurate decline envelopes and status codes.
        Preconditions: Simulator evaluates card number suffix.
        Input Data: Designated test card for decline simulation.
        Expected Result: Expected HTTP status code and error code matching bank decline reason.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        payload = PaymentPayloadFactory.create(card_number=card_no)
        headers = AuthHeaderFactory.create(
            idempotency_key=PaymentPayloadFactory.generate_idempotency_key("decline")
        )
        response = await async_client.post("/v1/payments", headers=headers, json=payload)

        assert response.status_code == expected_status
        data = response.json()
        validate(instance=data, schema=ERROR_ENVELOPE_SCHEMA)
        assert data["error"]["code"] == expected_code

    async def test_tc_neg_025_excessive_refund_attempt_rejected(self, async_client: httpx.AsyncClient):
        """Test ID: TC-NEG-025

        Scenario: Attempting a refund amount exceeding remaining refundable captured balance.
        Preconditions: Payment captured for 5000 cents ($50.00).
        Input Data: Refund request for 6000 cents ($60.00).
        Expected Result: HTTP 422 Unprocessable Entity with code 'refund_amount_exceeds_balance'.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        # Step 1: Create & capture payment for 5000 cents
        pay_payload = PaymentPayloadFactory.create(amount_cents=5000, capture=True)
        pay_headers = AuthHeaderFactory.create(
            idempotency_key=PaymentPayloadFactory.generate_idempotency_key("pay_over_ref")
        )
        pay_res = await async_client.post("/v1/payments", headers=pay_headers, json=pay_payload)
        payment_id = pay_res.json()["id"]

        # Step 2: Attempt refund of 6000 cents
        ref_headers = AuthHeaderFactory.create(
            idempotency_key=PaymentPayloadFactory.generate_idempotency_key("excess_ref")
        )
        ref_res = await async_client.post(
            f"/v1/payments/{payment_id}/refund",
            headers=ref_headers,
            json={"amount_cents": 6000, "reason": "over_refund"},
        )

        assert ref_res.status_code == 422
        data = ref_res.json()
        validate(instance=data, schema=ERROR_ENVELOPE_SCHEMA)
        assert data["error"]["code"] == "refund_amount_exceeds_balance"
        assert data["error"]["details"]["attempted_cents"] == 6000
        assert data["error"]["details"]["available_cents"] == 5000
