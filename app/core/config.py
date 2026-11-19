"""Application Configuration & Constants.

Defines environment-level configuration, monetary constraints,
and supported ISO currency codes.
"""

from typing import Set


class Settings:
    """System-wide configuration settings."""

    # Project metadata
    PROJECT_NAME: str = "Payment Gateway Reliability & Quality Engineering Simulator"
    VERSION: str = "1.0.0"

    # Database settings: Uses local SQLite in WAL mode
    DATABASE_URL: str = "sqlite:///./payment_gateway.db"
    SQLITE_BUSY_TIMEOUT_MS: int = 5000  # 5 seconds busy retry before locking error

    # Monetary constraints (in minor units / cents)
    MIN_TRANSACTION_AMOUNT_CENTS: int = 50  # $0.50
    MAX_TRANSACTION_AMOUNT_CENTS: int = 10_000_000  # $100,000.00
    SUPPORTED_CURRENCIES: Set[str] = {"USD", "EUR", "GBP", "CAD", "INR"}

    # Idempotency settings
    IDEMPOTENCY_TTL_SECONDS: int = 86400  # 24 hours
    IN_PROGRESS_LOCK_TIMEOUT_SECONDS: int = 60  # Maximum lock duration for in-flight requests

    # Webhook signature tolerance
    WEBHOOK_TOLERANCE_SECONDS: int = 300  # 5 minutes replay protection window

    # Default educational test merchant
    DEFAULT_MERCHANT_ID: str = "mer_default_test_001"
    DEFAULT_MERCHANT_API_KEY: str = "sk_test_gateway_qa_secret_key_123"
    DEFAULT_MERCHANT_WEBHOOK_SECRET: str = "whsec_test_hmac_secret_456"


settings = Settings()
