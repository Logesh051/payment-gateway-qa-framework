"""Relational Database Entity Definitions.

Implements the normalized relational schema for merchants, payments,
idempotency tracking, genuine double-entry ledger entries, refunds,
and signed webhook events.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.db.session import Base


def utcnow() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


class Merchant(Base):
    """Registered merchant credentials and webhook config."""

    __tablename__ = "merchants"

    id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False)
    api_key = Column(String(255), unique=True, index=True, nullable=False)
    webhook_secret = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    # Relationships
    payments = relationship("Payment", back_populates="merchant")
    idempotency_keys = relationship("IdempotencyKey", back_populates="merchant")
    ledger_entries = relationship("LedgerEntry", back_populates="merchant")


class Payment(Base):
    """Core transaction entity managed by the domain state machine."""

    __tablename__ = "payments"

    id = Column(String(64), primary_key=True)
    merchant_id = Column(String(64), ForeignKey("merchants.id"), index=True, nullable=False)
    amount_cents = Column(BigInteger, nullable=False)  # Integer minor units
    currency = Column(String(3), nullable=False)
    status = Column(String(32), index=True, nullable=False)  # PaymentStatus enum value
    captured = Column(Boolean, default=False, nullable=False)
    card_last4 = Column(String(4), nullable=False)
    card_brand = Column(String(32), default="VISA", nullable=False)
    failure_code = Column(String(64), nullable=True)
    failure_message = Column(Text, nullable=True)
    customer_email = Column(String(255), nullable=True)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    # Relationships
    merchant = relationship("Merchant", back_populates="payments")
    refunds = relationship("Refund", back_populates="payment")
    ledger_entries = relationship("LedgerEntry", back_populates="payment")
    webhook_events = relationship("WebhookEvent", back_populates="payment")


class IdempotencyKey(Base):
    """Atomic idempotency record preventing double-charges and race conditions."""

    __tablename__ = "idempotency_keys"

    key = Column(String(128), primary_key=True)
    merchant_id = Column(String(64), ForeignKey("merchants.id"), index=True, nullable=False)
    request_hash = Column(String(64), nullable=False)  # SHA-256 of request body
    payment_id = Column(String(64), ForeignKey("payments.id"), nullable=True)
    status = Column(String(32), default="IN_PROGRESS", nullable=False)  # IN_PROGRESS, COMPLETED
    response_status_code = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    locked_until = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    # Relationships
    merchant = relationship("Merchant", back_populates="idempotency_keys")


class Refund(Base):
    """Partial or full refund issued against a captured payment."""

    __tablename__ = "refunds"

    id = Column(String(64), primary_key=True)
    payment_id = Column(String(64), ForeignKey("payments.id"), index=True, nullable=False)
    merchant_id = Column(String(64), ForeignKey("merchants.id"), index=True, nullable=False)
    amount_cents = Column(BigInteger, nullable=False)
    status = Column(String(32), default="COMPLETED", nullable=False)
    reason = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    # Relationships
    payment = relationship("Payment", back_populates="refunds")


class LedgerEntry(Base):
    """Genuine double-entry audit ledger record.

    Enforces the fundamental accounting equation:
    Sum(DEBITS in batch) == Sum(CREDITS in batch)
    """

    __tablename__ = "ledger_entries"

    id = Column(String(64), primary_key=True)
    batch_id = Column(String(64), index=True, nullable=False)
    payment_id = Column(String(64), ForeignKey("payments.id"), index=True, nullable=False)
    merchant_id = Column(String(64), ForeignKey("merchants.id"), index=True, nullable=False)
    entry_type = Column(String(16), nullable=False)  # 'DEBIT' or 'CREDIT'
    account_name = Column(String(64), nullable=False)  # e.g. customer_funds_clearing, merchant_available_balance
    amount_cents = Column(BigInteger, nullable=False)
    currency = Column(String(3), nullable=False)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    # Relationships
    merchant = relationship("Merchant", back_populates="ledger_entries")
    payment = relationship("Payment", back_populates="ledger_entries")


class WebhookEvent(Base):
    """Outbound webhook notification staged for delivery."""

    __tablename__ = "webhook_events"

    id = Column(String(64), primary_key=True)
    payment_id = Column(String(64), ForeignKey("payments.id"), index=True, nullable=False)
    merchant_id = Column(String(64), ForeignKey("merchants.id"), index=True, nullable=False)
    event_type = Column(String(64), nullable=False)  # e.g. payment.authorized, payment.captured
    payload_json = Column(Text, nullable=False)
    signature = Column(String(255), nullable=False)  # HMAC-SHA256 signature
    status = Column(String(32), default="PENDING", nullable=False)
    delivery_attempts = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    # Relationships
    payment = relationship("Payment", back_populates="webhook_events")
