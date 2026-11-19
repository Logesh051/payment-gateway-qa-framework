"""Webhook Event Staging & HMAC Signature Verification Service.

Implements HMAC-SHA256 event signing, timestamp-based replay attack mitigation,
and timing-safe signature comparison.
"""

from datetime import datetime, timezone
import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import models


class WebhookService:
    """Handles webhook generation, HMAC signing, and cryptographic signature verification."""

    @staticmethod
    def compute_signature(secret: str, timestamp: int, payload_json: str) -> str:
        """Compute the HMAC-SHA256 signature string for an outbound payload.

        Format: t={timestamp},v1={hmac_sha256_hex}
        """
        signed_payload = f"t={timestamp}.{payload_json}".encode("utf-8")
        mac = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        return f"t={timestamp},v1={mac}"

    @classmethod
    def verify_signature(
        cls,
        secret: str,
        signature_header: str,
        payload_json: str,
        tolerance_seconds: Optional[int] = None,
    ) -> bool:
        """Verify an inbound webhook signature using timing-safe comparison.

        Args:
            secret: Merchant webhook secret key.
            signature_header: Header value formatted as 't=123456789,v1=abc...'.
            payload_json: Raw JSON string received in the request body.
            tolerance_seconds: Max acceptable clock skew in seconds (default 300s).

        Returns:
            True if signature is valid and within the tolerance window, False otherwise.
        """
        if tolerance_seconds is None:
            tolerance_seconds = settings.WEBHOOK_TOLERANCE_SECONDS

        try:
            parts = dict(part.split("=", 1) for part in signature_header.split(","))
            timestamp = int(parts["t"])
            received_mac = parts["v1"]
        except Exception:
            return False

        # Verify timestamp to prevent replay attacks
        now = int(time.time())
        if abs(now - timestamp) > tolerance_seconds:
            return False

        # Recompute expected signature
        signed_payload = f"t={timestamp}.{payload_json}".encode("utf-8")
        expected_mac = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()

        # Timing-safe comparison to prevent side-channel timing attacks
        return hmac.compare_digest(received_mac, expected_mac)

    @classmethod
    def stage_event(
        cls,
        db: Session,
        payment_id: str,
        merchant_id: str,
        webhook_secret: str,
        event_type: str,
        data: Dict[str, Any],
    ) -> models.WebhookEvent:
        """Stage an outbound signed webhook notification in the database."""
        event_id = f"evt_{uuid.uuid4().hex[:16]}"
        timestamp_int = int(time.time())
        iso_timestamp = datetime.now(timezone.utc).isoformat()

        event_payload = {
            "event_id": event_id,
            "event_type": event_type,
            "timestamp": iso_timestamp,
            "data": data,
        }
        payload_json = json.dumps(event_payload, sort_keys=True, separators=(",", ":"), default=str)
        signature = cls.compute_signature(webhook_secret, timestamp_int, payload_json)

        event = models.WebhookEvent(
            id=event_id,
            payment_id=payment_id,
            merchant_id=merchant_id,
            event_type=event_type,
            payload_json=payload_json,
            signature=signature,
            status="PENDING",
            delivery_attempts=0,
        )
        db.add(event)
        db.flush()
        return event
