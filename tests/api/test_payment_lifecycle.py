"""API Tests: End-to-End Payment Lifecycle Operations.

Validates payment initiation, authorization hold, capture, void/cancel,
partial refunds, full refunds, and query endpoints against OpenAPI contracts.
"""

import pytest
import httpx
from jsonschema import validate

from tests.factories import AuthHeaderFactory, PaymentPayloadFactory
from tests.schemas.payment_schemas import PAYMENT_SUCCESS_SCHEMA, REFUND_SUCCESS_SCHEMA


@pytest.mark.api
class TestPaymentLifecycle:
    """Test Suite ID: TS-API-LIFECYCLE

    Verifies the entire happy-path lifecycle of financial transactions.
    """

    async def test_tc_api_010_direct_capture_payment_creation(self, async_client: httpx.AsyncClient):
        """Test ID: TC-API-010

        Scenario: Create a direct capture payment ($50.00 USD).
        Preconditions: Authenticated merchant with unique Idempotency-Key.
        Input Data: amount_cents=5000, currency='USD', capture=True, valid Visa test card.
        Expected Result: HTTP 201 Created, status='CAPTURED', captured=True, matches OpenAPI schema.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        payload = PaymentPayloadFactory.create(amount_cents=5000, capture=True)
        headers = AuthHeaderFactory.create(
            idempotency_key=PaymentPayloadFactory.generate_idempotency_key("direct_cap")
        )

        response = await async_client.post("/v1/payments", headers=headers, json=payload)
        assert response.status_code == 201
        data = response.json()

        # Contract Schema Verification
        validate(instance=data, schema=PAYMENT_SUCCESS_SCHEMA)
        assert data["status"] == "CAPTURED"
        assert data["captured"] is True
        assert data["amount_cents"] == 5000
        assert data["currency"] == "USD"
        assert data["card_last4"] == "0001"
        assert data["card_brand"] == "VISA"

    async def test_tc_api_011_two_step_authorization_creation(self, async_client: httpx.AsyncClient):
        """Test ID: TC-API-011

        Scenario: Initiate a two-step payment (authorization hold without direct capture).
        Preconditions: Authenticated merchant.
        Input Data: amount_cents=8000 ($80.00), capture=False.
        Expected Result: HTTP 201 Created, status='AUTHORIZED', captured=False.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        payload = PaymentPayloadFactory.create(amount_cents=8000, capture=False)
        headers = AuthHeaderFactory.create(
            idempotency_key=PaymentPayloadFactory.generate_idempotency_key("auth_hold")
        )

        response = await async_client.post("/v1/payments", headers=headers, json=payload)
        assert response.status_code == 201
        data = response.json()

        validate(instance=data, schema=PAYMENT_SUCCESS_SCHEMA)
        assert data["status"] == "AUTHORIZED"
        assert data["captured"] is False

    async def test_tc_api_012_capture_authorized_payment(self, async_client: httpx.AsyncClient):
        """Test ID: TC-API-012

        Scenario: Capture a previously authorized payment.
        Preconditions: Existing payment in 'AUTHORIZED' status.
        Input Data: POST /v1/payments/{id}/capture with amount_cents=8000.
        Expected Result: HTTP 200 OK, status transitions from AUTHORIZED to CAPTURED, captured=True.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        # Step 1: Create Authorization
        auth_payload = PaymentPayloadFactory.create(amount_cents=8000, capture=False)
        auth_headers = AuthHeaderFactory.create(
            idempotency_key=PaymentPayloadFactory.generate_idempotency_key("auth_step")
        )
        auth_res = await async_client.post("/v1/payments", headers=auth_headers, json=auth_payload)
        payment_id = auth_res.json()["id"]

        # Step 2: Capture Authorization
        cap_headers = AuthHeaderFactory.create(
            idempotency_key=PaymentPayloadFactory.generate_idempotency_key("cap_step")
        )
        cap_res = await async_client.post(
            f"/v1/payments/{payment_id}/capture",
            headers=cap_headers,
            json={"amount_cents": 8000},
        )
        assert cap_res.status_code == 200
        cap_data = cap_res.json()

        validate(instance=cap_data, schema=PAYMENT_SUCCESS_SCHEMA)
        assert cap_data["status"] == "CAPTURED"
        assert cap_data["captured"] is True

    async def test_tc_api_013_cancel_authorized_payment(self, async_client: httpx.AsyncClient):
        """Test ID: TC-API-013

        Scenario: Void / cancel an authorized payment before capture.
        Preconditions: Payment in 'AUTHORIZED' status.
        Input Data: POST /v1/payments/{id}/cancel with reason='merchant_void'.
        Expected Result: HTTP 200 OK, status transitions from AUTHORIZED to CANCELLED.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        auth_payload = PaymentPayloadFactory.create(amount_cents=3500, capture=False)
        auth_headers = AuthHeaderFactory.create(
            idempotency_key=PaymentPayloadFactory.generate_idempotency_key("auth_to_cancel")
        )
        auth_res = await async_client.post("/v1/payments", headers=auth_headers, json=auth_payload)
        payment_id = auth_res.json()["id"]

        cancel_headers = AuthHeaderFactory.create(
            idempotency_key=PaymentPayloadFactory.generate_idempotency_key("cancel_step")
        )
        cancel_res = await async_client.post(
            f"/v1/payments/{payment_id}/cancel",
            headers=cancel_headers,
            json={"reason": "customer_changed_mind"},
        )
        assert cancel_res.status_code == 200
        data = cancel_res.json()
        assert data["status"] == "CANCELLED"

    async def test_tc_api_014_partial_and_full_refund_flow(self, async_client: httpx.AsyncClient):
        """Test ID: TC-API-014

        Scenario: Process incremental refunds against a captured transaction ($100 total).
                  1. Refund $30 -> Status PARTIALLY_REFUNDED, Remaining $70.
                  2. Refund $70 -> Status REFUNDED, Remaining $0.
        Preconditions: Payment in 'CAPTURED' status for 10000 cents.
        Input Data: Step 1: amount=3000. Step 2: amount=7000.
        Expected Result: Step 1 returns PARTIALLY_REFUNDED. Step 2 returns REFUNDED with remaining=0.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        # Step 1: Create & capture payment for 10000 cents ($100.00)
        pay_payload = PaymentPayloadFactory.create(amount_cents=10000, capture=True)
        pay_headers = AuthHeaderFactory.create(
            idempotency_key=PaymentPayloadFactory.generate_idempotency_key("pay_for_refund")
        )
        pay_res = await async_client.post("/v1/payments", headers=pay_headers, json=pay_payload)
        payment_id = pay_res.json()["id"]

        # Step 2: Partial refund of 3000 cents
        ref1_headers = AuthHeaderFactory.create(
            idempotency_key=PaymentPayloadFactory.generate_idempotency_key("ref_part1")
        )
        ref1_res = await async_client.post(
            f"/v1/payments/{payment_id}/refund",
            headers=ref1_headers,
            json={"amount_cents": 3000, "reason": "item_returned"},
        )
        assert ref1_res.status_code == 200
        ref1_data = ref1_res.json()
        validate(instance=ref1_data, schema=REFUND_SUCCESS_SCHEMA)
        assert ref1_data["payment_status"] == "PARTIALLY_REFUNDED"
        assert ref1_data["amount_refunded_cents"] == 3000
        assert ref1_data["remaining_balance_cents"] == 7000

        # Step 3: Full remaining refund of 7000 cents
        ref2_headers = AuthHeaderFactory.create(
            idempotency_key=PaymentPayloadFactory.generate_idempotency_key("ref_part2")
        )
        ref2_res = await async_client.post(
            f"/v1/payments/{payment_id}/refund",
            headers=ref2_headers,
            json={"amount_cents": 7000, "reason": "order_cancelled_rest"},
        )
        assert ref2_res.status_code == 200
        ref2_data = ref2_res.json()
        validate(instance=ref2_data, schema=REFUND_SUCCESS_SCHEMA)
        assert ref2_data["payment_status"] == "REFUNDED"
        assert ref2_data["amount_refunded_cents"] == 7000
        assert ref2_data["remaining_balance_cents"] == 0

    async def test_tc_api_015_query_payment_details_by_id(self, async_client: httpx.AsyncClient):
        """Test ID: TC-API-015

        Scenario: Query payment record details via GET endpoint.
        Preconditions: Valid payment created.
        Input Data: GET /v1/payments/{id}.
        Expected Result: HTTP 200 OK returning accurate payment entity matching stored values.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        payload = PaymentPayloadFactory.create(amount_cents=4500, capture=True)
        headers = AuthHeaderFactory.create(
            idempotency_key=PaymentPayloadFactory.generate_idempotency_key("query_test")
        )
        create_res = await async_client.post("/v1/payments", headers=headers, json=payload)
        payment_id = create_res.json()["id"]

        get_res = await async_client.get(f"/v1/payments/{payment_id}", headers=headers)
        assert get_res.status_code == 200
        data = get_res.json()
        assert data["id"] == payment_id
        assert data["amount_cents"] == 4500
        assert data["status"] == "CAPTURED"
