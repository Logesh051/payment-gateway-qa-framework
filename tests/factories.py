"""Test Data Factories & Synthetic Payload Generators.

Generates deterministic and randomized test payloads, payment requests,
idempotency keys, and merchant credentials for the independent QA test suite.
"""

from typing import Any, Dict, Optional
import uuid

from app.core.config import settings


class CardCatalog:
    """Deterministic synthetic test card numbers."""

    SUCCESS_VISA = "4000000000000001"
    SUCCESS_MASTERCARD = "5100000000000001"
    DECLINE_INSUFFICIENT_FUNDS = "4000000000000002"
    DECLINE_CARD_EXPIRED = "4000000000000003"
    DECLINE_SUSPECTED_FRAUD = "4000000000000004"
    DECLINE_GATEWAY_TIMEOUT = "4000000000000005"


class PaymentPayloadFactory:
    """Factory creating standardized payment request bodies."""

    @staticmethod
    def create(
        amount_cents: int = 5000,
        currency: str = "USD",
        card_number: str = CardCatalog.SUCCESS_VISA,
        exp_month: int = 12,
        exp_year: int = 2028,
        cvv: str = "123",
        capture: bool = True,
        customer_email: Optional[str] = "qa.tester@example.com",
        description: Optional[str] = "Independent QA Automated Test",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate a valid payment payload with optional overrides."""
        payload = {
            "amount_cents": amount_cents,
            "currency": currency,
            "card_number": card_number,
            "exp_month": exp_month,
            "exp_year": exp_year,
            "cvv": cvv,
            "capture": capture,
            "customer_email": customer_email,
            "description": description,
        }
        payload.update(kwargs)
        return payload

    @staticmethod
    def generate_idempotency_key(prefix: str = "qa_key") -> str:
        """Generate a unique UUID-based idempotency key."""
        return f"{prefix}_{uuid.uuid4().hex[:16]}"


class AuthHeaderFactory:
    """Factory generating standard authentication and content headers."""

    @staticmethod
    def create(
        api_key: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, str]:
        """Build headers dictionary with required API key and optional idempotency key."""
        headers = {
            "X-API-Key": api_key or settings.DEFAULT_MERCHANT_API_KEY,
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers
