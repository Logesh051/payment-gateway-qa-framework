"""API Tests: Idempotency Verification & Replay Protection.

Validates the three precise idempotency requirements:
1. Same key + same payload => returns cached original result.
2. Same key + different payload => rejects with HTTP 409 Conflict.
3. Different keys => independent transactions.
"""

import pytest
import httpx
from jsonschema import validate

from tests.factories import AuthHeaderFactory, PaymentPayloadFactory
from tests.schemas.payment_schemas import ERROR_ENVELOPE_SCHEMA, PAYMENT_SUCCESS_SCHEMA


@pytest.mark.idempotency
class TestIdempotency:
    """Test Suite ID: TS-API-IDEMPOTENCY

    Verifies atomic idempotency protection, replay caching, and collision detection.
    """

    async def test_tc_idem_030_same_key_same_payload_returns_cached_result(
        self, async_client: httpx.AsyncClient
    ):
        """Test ID: TC-IDEM-030

        Scenario: Replaying an identical payment request using the same Idempotency-Key.
        Preconditions: First payment executed successfully.
        Input Data: Identical Idempotency-Key and identical JSON payload.
        Expected Result: HTTP 201 Created returning identical payment ID from cache.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        key = PaymentPayloadFactory.generate_idempotency_key("replay_test")
        payload = PaymentPayloadFactory.create(amount_cents=6500)
        headers = AuthHeaderFactory.create(idempotency_key=key)

        # First Call
        res1 = await async_client.post("/v1/payments", headers=headers, json=payload)
        assert res1.status_code == 201
        data1 = res1.json()
        payment_id_1 = data1["id"]

        # Second Call (Exact Replay)
        res2 = await async_client.post("/v1/payments", headers=headers, json=payload)
        assert res2.status_code == 201
        data2 = res2.json()

        assert data2["id"] == payment_id_1
        assert data2["amount_cents"] == data1["amount_cents"]
        assert data2["created_at"] == data1["created_at"]

    async def test_tc_idem_031_same_key_different_payload_returns_409(
        self, async_client: httpx.AsyncClient
    ):
        """Test ID: TC-IDEM-031

        Scenario: Re-using an existing Idempotency-Key with an altered payload.
        Preconditions: Key previously completed with original payload.
        Input Data: Same key, but amount_cents changed from 5000 to 9500.
        Expected Result: HTTP 409 Conflict with error code 'idempotency_payload_mismatch'.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        key = PaymentPayloadFactory.generate_idempotency_key("mismatch_test")
        original_payload = PaymentPayloadFactory.create(amount_cents=5000)
        headers = AuthHeaderFactory.create(idempotency_key=key)

        # Initial call
        res1 = await async_client.post("/v1/payments", headers=headers, json=original_payload)
        assert res1.status_code == 201

        # Second call with same key, altered payload
        altered_payload = PaymentPayloadFactory.create(amount_cents=9500)
        res2 = await async_client.post("/v1/payments", headers=headers, json=altered_payload)

        assert res2.status_code == 409
        data2 = res2.json()
        validate(instance=data2, schema=ERROR_ENVELOPE_SCHEMA)
        assert data2["error"]["code"] == "idempotency_payload_mismatch"
        assert data2["error"]["details"]["idempotency_key"] == key

    async def test_tc_idem_032_different_keys_create_independent_transactions(
        self, async_client: httpx.AsyncClient
    ):
        """Test ID: TC-IDEM-032

        Scenario: Sending identical payment payloads with different Idempotency-Keys.
        Preconditions: Two distinct customer orders with identical cart totals.
        Input Data: Identical payload with key_A and key_B.
        Expected Result: Two separate HTTP 201 transactions with unique payment IDs.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        key_a = PaymentPayloadFactory.generate_idempotency_key("key_a")
        key_b = PaymentPayloadFactory.generate_idempotency_key("key_b")
        payload = PaymentPayloadFactory.create(amount_cents=4200)

        res_a = await async_client.post(
            "/v1/payments",
            headers=AuthHeaderFactory.create(idempotency_key=key_a),
            json=payload,
        )
        res_b = await async_client.post(
            "/v1/payments",
            headers=AuthHeaderFactory.create(idempotency_key=key_b),
            json=payload,
        )

        assert res_a.status_code == 201
        assert res_b.status_code == 201
        assert res_a.json()["id"] != res_b.json()["id"]

    async def test_tc_idem_033_idempotent_capture_replay(self, async_client: httpx.AsyncClient):
        """Test ID: TC-IDEM-033

        Scenario: Replaying a capture request with the same idempotency key.
        Preconditions: Payment authorized. Capture executed once with key_cap.
        Input Data: Replaying capture request with identical key_cap.
        Expected Result: Second call returns cached HTTP 200 OK instead of throwing 409 Conflict.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        # Step 1: Create Authorization
        auth_payload = PaymentPayloadFactory.create(amount_cents=7000, capture=False)
        auth_res = await async_client.post(
            "/v1/payments",
            headers=AuthHeaderFactory.create(
                idempotency_key=PaymentPayloadFactory.generate_idempotency_key("auth_cap_idem")
            ),
            json=auth_payload,
        )
        payment_id = auth_res.json()["id"]

        # Step 2: First Capture
        cap_key = PaymentPayloadFactory.generate_idempotency_key("cap_idem")
        cap_headers = AuthHeaderFactory.create(idempotency_key=cap_key)
        res_cap1 = await async_client.post(
            f"/v1/payments/{payment_id}/capture",
            headers=cap_headers,
            json={"amount_cents": 7000},
        )
        assert res_cap1.status_code == 200

        # Step 3: Replay identical Capture
        res_cap2 = await async_client.post(
            f"/v1/payments/{payment_id}/capture",
            headers=cap_headers,
            json={"amount_cents": 7000},
        )
        assert res_cap2.status_code == 200
        assert res_cap2.json()["id"] == payment_id
        assert res_cap2.json()["status"] == "CAPTURED"

    async def test_tc_idem_034_idempotent_refund_replay(self, async_client: httpx.AsyncClient):
        """Test ID: TC-IDEM-034

        Scenario: Replaying a refund request with the same idempotency key.
        Preconditions: Payment captured for 6000 cents. Refund for 2000 cents initiated with key_ref.
        Input Data: Replaying refund request with identical key_ref.
        Expected Result: Second call returns cached HTTP 200 OK without subtracting balance a second time.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        # Step 1: Create & capture payment for 6000 cents
        pay_res = await async_client.post(
            "/v1/payments",
            headers=AuthHeaderFactory.create(
                idempotency_key=PaymentPayloadFactory.generate_idempotency_key("pay_ref_idem")
            ),
            json=PaymentPayloadFactory.create(amount_cents=6000, capture=True),
        )
        payment_id = pay_res.json()["id"]

        # Step 2: First Refund
        ref_key = PaymentPayloadFactory.generate_idempotency_key("ref_idem")
        ref_headers = AuthHeaderFactory.create(idempotency_key=ref_key)
        ref_payload = {"amount_cents": 2000, "reason": "item_defective"}

        res_ref1 = await async_client.post(
            f"/v1/payments/{payment_id}/refund",
            headers=ref_headers,
            json=ref_payload,
        )
        assert res_ref1.status_code == 200
        data1 = res_ref1.json()
        assert data1["remaining_balance_cents"] == 4000

        # Step 3: Replay Refund (same key)
        res_ref2 = await async_client.post(
            f"/v1/payments/{payment_id}/refund",
            headers=ref_headers,
            json=ref_payload,
        )
        assert res_ref2.status_code == 200
        data2 = res_ref2.json()
        assert data2["refund_id"] == data1["refund_id"]
        assert data2["remaining_balance_cents"] == 4000  # NOT decremented to 2000!
