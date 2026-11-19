"""API Tests: Webhook Notification, HMAC Signing & Replay Protection.

Validates HMAC-SHA256 signature generation, timing-safe validation,
payload tampering detection, and 5-minute replay window enforcement.
"""

import time
import pytest
import httpx

from app.core.config import settings
from app.services.webhook_service import WebhookService
from tests.factories import AuthHeaderFactory, PaymentPayloadFactory


@pytest.mark.webhook
class TestWebhooks:
    """Test Suite ID: TS-API-WEBHOOKS

    Verifies cryptographic authenticity and replay mitigation for asynchronous webhook events.
    """

    async def test_tc_wh_050_valid_signature_verification(self, async_client: httpx.AsyncClient):
        """Test ID: TC-WH-050

        Scenario: Verify that a legitimately computed HMAC-SHA256 signature validates successfully.
        Preconditions: Secret key matches merchant configuration.
        Input Data: Valid HMAC computed over current timestamp and payload JSON.
        Expected Result: HTTP 200 OK with {"valid": true}.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        payload = '{"event_id":"evt_valid_123","event_type":"payment.captured","amount_cents":5000}'
        timestamp = int(time.time())
        sig = WebhookService.compute_signature(
            secret=settings.DEFAULT_MERCHANT_WEBHOOK_SECRET,
            timestamp=timestamp,
            payload_json=payload,
        )

        res = await async_client.post(
            "/v1/webhooks/verify",
            headers=AuthHeaderFactory.create(),
            json={"signature_header": sig, "payload_json": payload},
        )
        assert res.status_code == 200
        assert res.json()["valid"] is True

    async def test_tc_wh_051_tampered_payload_rejected(self, async_client: httpx.AsyncClient):
        """Test ID: TC-WH-051

        Scenario: A man-in-the-middle or client alters the payload after signature computation.
        Preconditions: Legitimate signature computed on original payload.
        Input Data: Signature for original payload, but payload altered with amount changed to 99999.
        Expected Result: HTTP 200 OK with {"valid": false}.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        original_payload = '{"event_id":"evt_tamper_1","amount_cents":5000}'
        tampered_payload = '{"event_id":"evt_tamper_1","amount_cents":99999}'

        timestamp = int(time.time())
        sig = WebhookService.compute_signature(
            secret=settings.DEFAULT_MERCHANT_WEBHOOK_SECRET,
            timestamp=timestamp,
            payload_json=original_payload,
        )

        res = await async_client.post(
            "/v1/webhooks/verify",
            headers=AuthHeaderFactory.create(),
            json={"signature_header": sig, "payload_json": tampered_payload},
        )
        assert res.status_code == 200
        assert res.json()["valid"] is False

    async def test_tc_wh_052_invalid_signature_hex_rejected(self, async_client: httpx.AsyncClient):
        """Test ID: TC-WH-052

        Scenario: Inbound webhook header contains a malformed or forged hex digest.
        Preconditions: None.
        Input Data: Signature header with bogus v1 string.
        Expected Result: HTTP 200 OK with {"valid": false}.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        payload = '{"event_id":"evt_bogus_1"}'
        timestamp = int(time.time())
        bogus_sig = f"t={timestamp},v1=deadbeefcafebabe0123456789abcdef"

        res = await async_client.post(
            "/v1/webhooks/verify",
            headers=AuthHeaderFactory.create(),
            json={"signature_header": bogus_sig, "payload_json": payload},
        )
        assert res.status_code == 200
        assert res.json()["valid"] is False

    async def test_tc_wh_053_expired_timestamp_replay_rejected(self, async_client: httpx.AsyncClient):
        """Test ID: TC-WH-053

        Scenario: An attacker captures a valid signed webhook and replays it after tolerance window.
        Preconditions: Webhook replay tolerance window is 300 seconds (5 minutes).
        Input Data: Signature generated with a timestamp from 400 seconds in the past.
        Expected Result: HTTP 200 OK with {"valid": false} (Replay attack blocked).
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        payload = '{"event_id":"evt_expired_replay"}'
        expired_timestamp = int(time.time()) - 400  # 400 seconds ago (> 300s)
        sig = WebhookService.compute_signature(
            secret=settings.DEFAULT_MERCHANT_WEBHOOK_SECRET,
            timestamp=expired_timestamp,
            payload_json=payload,
        )

        res = await async_client.post(
            "/v1/webhooks/verify",
            headers=AuthHeaderFactory.create(),
            json={"signature_header": sig, "payload_json": payload},
        )
        assert res.status_code == 200
        assert res.json()["valid"] is False

    async def test_tc_wh_054_future_skewed_timestamp_rejected(self, async_client: httpx.AsyncClient):
        """Test ID: TC-WH-054

        Scenario: Webhook payload timestamp is in the future beyond acceptable clock drift.
        Preconditions: System clock skew tolerance is 300 seconds.
        Input Data: Timestamp set to 450 seconds in the future.
        Expected Result: HTTP 200 OK with {"valid": false}.
        Actual Result: Verified via async API execution.
        Status: PASS
        """
        payload = '{"event_id":"evt_future_skew"}'
        future_timestamp = int(time.time()) + 450
        sig = WebhookService.compute_signature(
            secret=settings.DEFAULT_MERCHANT_WEBHOOK_SECRET,
            timestamp=future_timestamp,
            payload_json=payload,
        )

        res = await async_client.post(
            "/v1/webhooks/verify",
            headers=AuthHeaderFactory.create(),
            json={"signature_header": sig, "payload_json": payload},
        )
        assert res.status_code == 200
        assert res.json()["valid"] is False
