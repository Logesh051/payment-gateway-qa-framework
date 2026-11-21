"""Request and response models for the payment API."""

from pydantic import BaseModel, Field


class PaymentRequest(BaseModel):
    amount_rupees: int = Field(gt=0, description="Amount in whole Indian rupees")
    card_number: str = Field(min_length=16, max_length=19, pattern=r"^\d+$")


class PaymentResponse(BaseModel):
    id: str
    amount_rupees: int
    currency: str
    card_last4: str
    status: str
    failure_reason: str | None
    created_at: str
