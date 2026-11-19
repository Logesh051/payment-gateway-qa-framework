"""API Dependencies: Authentication & Session Injection.

Validates merchant credentials via API key header and provides scoped database sessions.
"""

from typing import Optional
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.exceptions import GatewayException, UnauthorizedMerchantException
from app.db import models
from app.db.session import get_db


def get_authenticated_merchant(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> models.Merchant:
    """Validate incoming merchant API key header against the merchants database."""
    if not x_api_key:
        raise UnauthorizedMerchantException()

    merchant = db.query(models.Merchant).filter_by(api_key=x_api_key, is_active=True).first()
    if not merchant:
        raise UnauthorizedMerchantException()

    return merchant


def get_idempotency_key(
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> str:
    """Enforce presence of Idempotency-Key header on mutating operations."""
    if not idempotency_key or not idempotency_key.strip():
        raise GatewayException(
            code="missing_idempotency_key",
            message="Mutating requests (POST) require an 'Idempotency-Key' header.",
            status_code=400,
        )
    return idempotency_key.strip()
