"""API Request and Response Data Transfer Objects (Pydantic v2).

Enforces strict type safety and boundary validation on incoming payloads,
ensuring integer cents representation and ISO standards.
"""

from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class PaymentCreateRequest(BaseModel):
    """Payload for initiating a payment charge or authorization hold."""

    amount_cents: int = Field(
        ...,
        description="Amount in integer minor currency units (cents). Floating-point rejected.",
        examples=[2500],
    )
    currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="ISO 4217 currency code (e.g., USD, EUR, GBP).",
        examples=["USD"],
    )
    card_number: str = Field(
        ...,
        min_length=13,
        max_length=19,
        description="Simulated test card number.",
        examples=["4000000000000001"],
    )
    exp_month: int = Field(..., ge=1, le=12, examples=[12])
    exp_year: int = Field(..., ge=2024, le=2040, examples=[2028])
    cvv: str = Field(..., min_length=3, max_length=4, examples=["123"])
    capture: bool = Field(
        default=True,
        description="True for one-step direct capture; False for two-step authorization hold.",
    )
    customer_email: Optional[str] = Field(default=None, examples=["qa.engineer@example.com"])
    description: Optional[str] = Field(default=None, examples=["Order #1042 Test Payment"])


class PaymentResponse(BaseModel):
    """Standard representation of a payment entity."""

    id: str
    merchant_id: str
    amount_cents: int
    currency: str
    status: str
    captured: bool
    card_last4: str
    card_brand: str
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CaptureRequest(BaseModel):
    """Payload for capturing an authorized hold."""

    amount_cents: Optional[int] = Field(
        default=None,
        description="Optional partial capture amount in minor units. Defaults to authorized total.",
    )


class CancelRequest(BaseModel):
    """Payload for voiding an uncaptured payment authorization."""

    reason: Optional[str] = Field(
        default="merchant_requested_cancellation",
        description="Reason for cancellation.",
    )


class RefundRequest(BaseModel):
    """Payload for partial or full refund."""

    amount_cents: int = Field(
        ...,
        gt=0,
        description="Refund amount in minor units (cents).",
        examples=[1000],
    )
    reason: Optional[str] = Field(
        default="customer_return",
        description="Reason for the refund.",
    )


class RefundResponse(BaseModel):
    """Response returned upon successful refund processing."""

    refund_id: str
    payment_id: str
    amount_refunded_cents: int
    remaining_balance_cents: int
    payment_status: str
    status: str
    created_at: datetime


class LedgerSummaryResponse(BaseModel):
    """Genuine double-entry ledger balance summary."""

    merchant_id: str
    currency: str
    available_balance_cents: int
    total_debits_cents: int
    total_credits_cents: int
    is_balanced: bool
    entry_count: int


class WebhookVerifyRequest(BaseModel):
    """Helper schema for testing webhook signature verification."""

    signature_header: str
    payload_json: str
    secret: Optional[str] = None
