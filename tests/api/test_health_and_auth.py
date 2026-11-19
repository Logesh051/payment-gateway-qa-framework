"""API Tests: System Health, Authentication, and Header Validation.

Validates endpoint accessibility, credential checking, and mandatory header enforcement.
"""

import pytest
import httpx
from jsonschema import validate

from tests.factories import AuthHeaderFactory, PaymentPayloadFactory
from tests.schemas.payment_schemas import ERROR_ENVELOPE_SCHEMA


@pytest.mark.api
class TestHealthAndAuth:
    """Test Suite ID: TS-API-HEALTH-AUTH

    Covers baseline system availability, merchant API authentication, and header constraints.
    """

    async def test_tc_api_001_health_check_returns_ok(self, async_client: httpx.AsyncClient):
        """Test ID: TC-API-001

        Scenario: Verify system health endpoint reports service status.
        Preconditions: Application service is initialized.
        Input Data: GET /health (unauthenticated).
        Expected Result: HTTP 200 OK with {"status": "healthy"}.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        response = await async_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "payment-gateway-simulator"

    async def test_tc_api_002_missing_api_key_returns_401(self, async_client: httpx.AsyncClient):
        """Test ID: TC-API-002

        Scenario: Attempting an API request without the X-API-Key header returns HTTP 401.
        Preconditions: Unauthenticated request sent to protected endpoint.
        Input Data: POST /v1/payments with Content-Type but no X-API-Key.
        Expected Result: HTTP 401 Unauthorized with standard error envelope.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        payload = PaymentPayloadFactory.create()
        headers = {"Content-Type": "application/json", "Idempotency-Key": "key_auth_test_1"}
        response = await async_client.post("/v1/payments", headers=headers, json=payload)

        assert response.status_code == 401
        data = response.json()
        validate(instance=data, schema=ERROR_ENVELOPE_SCHEMA)
        assert data["error"]["code"] == "unauthorized"

    async def test_tc_api_003_invalid_api_key_returns_401(self, async_client: httpx.AsyncClient):
        """Test ID: TC-API-003

        Scenario: Attempting an API request with an invalid/forged X-API-Key returns HTTP 401.
        Preconditions: Invalid credential supplied.
        Input Data: POST /v1/payments with X-API-Key: 'sk_test_bogus_key_999'.
        Expected Result: HTTP 401 Unauthorized.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        payload = PaymentPayloadFactory.create()
        headers = AuthHeaderFactory.create(
            api_key="sk_test_bogus_key_999",
            idempotency_key="key_auth_test_2",
        )
        response = await async_client.post("/v1/payments", headers=headers, json=payload)

        assert response.status_code == 401
        data = response.json()
        validate(instance=data, schema=ERROR_ENVELOPE_SCHEMA)
        assert data["error"]["code"] == "unauthorized"

    async def test_tc_api_004_missing_idempotency_key_returns_400(
        self, async_client: httpx.AsyncClient, auth_headers: dict
    ):
        """Test ID: TC-API-004

        Scenario: Attempting a mutating POST request without Idempotency-Key returns HTTP 400.
        Preconditions: Authenticated merchant calling POST without required idempotency header.
        Input Data: POST /v1/payments with valid API key but missing Idempotency-Key.
        Expected Result: HTTP 400 Bad Request with code 'missing_idempotency_key'.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        payload = PaymentPayloadFactory.create()
        # auth_headers has API key but NO Idempotency-Key
        response = await async_client.post("/v1/payments", headers=auth_headers, json=payload)

        assert response.status_code == 400
        data = response.json()
        validate(instance=data, schema=ERROR_ENVELOPE_SCHEMA)
        assert data["error"]["code"] == "missing_idempotency_key"

    async def test_tc_api_005_query_nonexistent_payment_returns_404(
        self, async_client: httpx.AsyncClient, auth_headers: dict
    ):
        """Test ID: TC-API-005

        Scenario: Querying details of a payment ID that does not exist returns HTTP 404.
        Preconditions: Authenticated merchant querying non-existent ID.
        Input Data: GET /v1/payments/pay_nonexistent_999999.
        Expected Result: HTTP 404 Not Found with code 'payment_not_found'.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        response = await async_client.get("/v1/payments/pay_nonexistent_999999", headers=auth_headers)
        assert response.status_code == 404
        data = response.json()
        validate(instance=data, schema=ERROR_ENVELOPE_SCHEMA)
        assert data["error"]["code"] == "payment_not_found"
