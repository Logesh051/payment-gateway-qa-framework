"""Domain Exceptions & Structured Error Envelopes.

Defines custom exception classes representing business rule violations,
deterministic simulation declines, and concurrency conflicts.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional


class GatewayException(Exception):
    """Base exception for all payment gateway domain errors."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_envelope(self) -> Dict[str, Any]:
        """Convert the exception to the standard JSON error envelope."""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "timestamp": self.timestamp,
            }
        }


class InvalidStateTransitionException(GatewayException):
    """Raised when an illegal lifecycle transition is attempted."""

    def __init__(
        self,
        payment_id: str,
        current_status: str,
        attempted_status: str,
        allowed_transitions: list,
    ):
        super().__init__(
            code="invalid_state_transition",
            message=f"Cannot transition payment '{payment_id}' from {current_status} to {attempted_status}.",
            status_code=409,
            details={
                "payment_id": payment_id,
                "current_status": current_status,
                "attempted_status": attempted_status,
                "attempted_transition": attempted_status,
                "allowed_transitions": allowed_transitions,
            },
        )


class IdempotencyPayloadMismatchException(GatewayException):
    """Raised when a request re-uses an existing idempotency key with different payload."""

    def __init__(self, key: str):
        super().__init__(
            code="idempotency_payload_mismatch",
            message=(
                f"Idempotency key '{key}' was previously used with a different request payload. "
                "Replaying keys with altered parameters is strictly forbidden."
            ),
            status_code=409,
            details={"idempotency_key": key},
        )


class ConcurrentMutationInProgressException(GatewayException):
    """Raised when a concurrent request hits an idempotency key currently locked in-flight."""

    def __init__(self, key: str):
        super().__init__(
            code="concurrent_mutation_in_progress",
            message=f"An in-flight mutation is currently being processed for idempotency key '{key}'.",
            status_code=409,
            details={"idempotency_key": key},
        )


class AmountValidationException(GatewayException):
    """Raised when monetary amounts violate boundary or format rules."""

    def __init__(self, message: str, code: str = "invalid_amount", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code=code,
            message=message,
            status_code=400,
            details=details,
        )


class InsufficientFundsException(GatewayException):
    """Simulated bank decline: Code 51 Insufficient Funds."""

    def __init__(self, card_last4: str):
        super().__init__(
            code="insufficient_funds",
            message="Card issuer declined the transaction due to insufficient funds.",
            status_code=402,
            details={"card_last4": card_last4, "bank_decline_code": "51"},
        )


class CardExpiredException(GatewayException):
    """Simulated bank decline: Code 54 Expired Card."""

    def __init__(self, card_last4: str):
        super().__init__(
            code="card_expired",
            message="Card issuer declined the transaction because the card has expired.",
            status_code=402,
            details={"card_last4": card_last4, "bank_decline_code": "54"},
        )


class SuspectedFraudException(GatewayException):
    """Simulated fraud detection rejection: Code 59."""

    def __init__(self, card_last4: str):
        super().__init__(
            code="suspected_fraud",
            message="Transaction blocked by risk scoring and anti-fraud screening.",
            status_code=403,
            details={"card_last4": card_last4, "risk_action": "BLOCK"},
        )


class GatewayTimeoutException(GatewayException):
    """Simulated upstream bank/network timeout: Code 91."""

    def __init__(self):
        super().__init__(
            code="gateway_timeout",
            message="Upstream card network or issuing bank timed out. Transaction retriable via Idempotency-Key.",
            status_code=504,
            details={"retriable": True},
        )


class RefundLimitExceededException(GatewayException):
    """Raised when a refund request exceeds the remaining captured balance."""

    def __init__(self, payment_id: str, attempted_cents: int, available_cents: int):
        super().__init__(
            code="refund_amount_exceeds_balance",
            message=(
                f"Requested refund of {attempted_cents} cents exceeds remaining "
                f"refundable balance of {available_cents} cents."
            ),
            status_code=422,
            details={
                "payment_id": payment_id,
                "attempted_cents": attempted_cents,
                "available_cents": available_cents,
            },
        )


class UnauthorizedMerchantException(GatewayException):
    """Raised when authentication credentials fail."""

    def __init__(self):
        super().__init__(
            code="unauthorized",
            message="Invalid or missing merchant API key.",
            status_code=401,
        )
