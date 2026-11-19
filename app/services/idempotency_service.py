"""Idempotency Management Service.

Enforces the three core idempotency rules:
1. Same key + same payload => returns cached original result.
2. Same key + different payload => rejects with HTTP 409 Conflict.
3. Different keys => processed as independent transactions.
Also manages in-flight locks to prevent concurrent race conditions.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    ConcurrentMutationInProgressException,
    IdempotencyPayloadMismatchException,
)
from app.db import models


def compute_payload_hash(payload: Any) -> str:
    """Compute a deterministic SHA-256 hash of a payload dictionary or model."""
    if hasattr(payload, "model_dump"):
        data = payload.model_dump()
    elif isinstance(payload, dict):
        data = payload
    else:
        data = str(payload)

    # Canonical JSON string: sorted keys, compact separators
    canonical_json = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class IdempotencyService:
    """Orchestrates atomic idempotency locking, validation, and response replay."""

    @staticmethod
    def acquire_or_get_cached(
        db: Session,
        key: str,
        merchant_id: str,
        request_hash: str,
    ) -> Optional[Tuple[int, Dict[str, Any]]]:
        """Check for existing idempotency records or acquire an in-progress lock.

        Returns:
            Tuple of (status_code, response_body_dict) if previously completed.
            None if lock was acquired and transaction should proceed.

        Raises:
            IdempotencyPayloadMismatchException: Same key used with different payload (HTTP 409).
            ConcurrentMutationInProgressException: Key currently locked in-flight (HTTP 409).
        """
        now = datetime.now(timezone.utc)
        record = (
            db.query(models.IdempotencyKey)
            .filter_by(key=key, merchant_id=merchant_id)
            .first()
        )

        if not record:
            # Key does not exist: attempt to create in-flight lock
            lock_duration = timedelta(seconds=settings.IN_PROGRESS_LOCK_TIMEOUT_SECONDS)
            new_record = models.IdempotencyKey(
                key=key,
                merchant_id=merchant_id,
                request_hash=request_hash,
                status="IN_PROGRESS",
                locked_until=now + lock_duration,
                created_at=now,
            )
            try:
                db.add(new_record)
                db.flush()
                return None
            except IntegrityError:
                # Concurrency Race Condition: Another concurrent thread inserted this key simultaneously!
                db.rollback()
                record = (
                    db.query(models.IdempotencyKey)
                    .filter_by(key=key, merchant_id=merchant_id)
                    .first()
                )
                if not record:
                    # Winning transaction is still in-flight or was rolled back
                    raise ConcurrentMutationInProgressException(key=key)

        # Key already exists: check payload hash
        if record.request_hash != request_hash:
            raise IdempotencyPayloadMismatchException(key=key)

        # Key is completed: return cached response
        if record.status == "COMPLETED":
            cached_data = json.loads(record.response_body or "{}")
            return record.response_status_code or 200, cached_data

        # Key is IN_PROGRESS: check if lock has expired
        if record.locked_until > now:
            raise ConcurrentMutationInProgressException(key=key)

        # Lock expired (e.g. from previous server crash): re-lock and proceed
        record.locked_until = now + timedelta(seconds=settings.IN_PROGRESS_LOCK_TIMEOUT_SECONDS)
        db.flush()
        return None

    @staticmethod
    def finalize_key(
        db: Session,
        key: str,
        payment_id: Optional[str],
        status_code: int,
        response_data: Dict[str, Any],
    ) -> None:
        """Mark an idempotency key as COMPLETED and cache its response envelope."""
        record = db.query(models.IdempotencyKey).filter_by(key=key).first()
        if record:
            record.status = "COMPLETED"
            record.payment_id = payment_id if payment_id else None
            record.response_status_code = status_code
            record.response_body = json.dumps(response_data, default=str)
            db.flush()
