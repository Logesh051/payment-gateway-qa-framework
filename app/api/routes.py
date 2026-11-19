"""RESTful API Route Handlers.

Exposes endpoints for payment creation, capture, cancellation,
refund processing, double-entry ledger inquiry, and webhook signature verification.
"""

from typing import Any, Dict
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api import schemas
from app.api.dependencies import get_authenticated_merchant, get_idempotency_key
from app.core.exceptions import GatewayException
from app.db import models
from app.db.session import get_db
from app.services.idempotency_service import IdempotencyService, compute_payload_hash
from app.services.payment_service import PaymentService
from app.services.webhook_service import WebhookService

router = APIRouter(prefix="/v1", tags=["Payment Gateway Operations"])


@router.post(
    "/payments",
    response_model=schemas.PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or Authorize a Payment",
)
def create_payment(
    payload: schemas.PaymentCreateRequest,
    merchant: models.Merchant = Depends(get_authenticated_merchant),
    idempotency_key: str = Depends(get_idempotency_key),
    db: Session = Depends(get_db),
):
    """Initiate a payment transaction.

    Enforces idempotency, evaluates card rules, records double-entry ledger
    entries, stages signed webhooks, and commits atomically.
    """
    request_hash = compute_payload_hash(payload)

    # Check for existing idempotency cache or acquire in-progress lock
    cached = IdempotencyService.acquire_or_get_cached(
        db=db,
        key=idempotency_key,
        merchant_id=merchant.id,
        request_hash=request_hash,
    )
    if cached:
        status_code, body = cached
        return JSONResponse(status_code=status_code, content=body)

    try:
        payment = PaymentService.create_payment(
            db=db,
            merchant=merchant,
            amount_cents=payload.amount_cents,
            currency=payload.currency,
            card_number=payload.card_number,
            exp_month=payload.exp_month,
            exp_year=payload.exp_year,
            cvv=payload.cvv,
            capture=payload.capture,
            customer_email=payload.customer_email,
            description=payload.description,
        )

        response_data = schemas.PaymentResponse.model_validate(payment).model_dump(mode="json")

        # Mark idempotency key completed and cache response
        IdempotencyService.finalize_key(
            db=db,
            key=idempotency_key,
            payment_id=payment.id,
            status_code=status.HTTP_201_CREATED,
            response_data=response_data,
        )
        db.commit()
        return JSONResponse(status_code=status.HTTP_201_CREATED, content=response_data)

    except GatewayException as ge:
        # For simulated bank declines (402, 403, 504), cache the failure result for idempotency
        if ge.status_code in {402, 403, 504}:
            envelope = ge.to_envelope()
            payment_id_val = ge.details.get("payment_id") or None
            IdempotencyService.finalize_key(
                db=db,
                key=idempotency_key,
                payment_id=payment_id_val,
                status_code=ge.status_code,
                response_data=envelope,
            )
            db.commit()
        else:
            db.rollback()
        raise ge
    except Exception:
        db.rollback()
        raise


@router.post(
    "/payments/{payment_id}/capture",
    response_model=schemas.PaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Capture an Authorized Payment",
)
def capture_payment(
    payment_id: str,
    payload: schemas.CaptureRequest = schemas.CaptureRequest(),
    merchant: models.Merchant = Depends(get_authenticated_merchant),
    idempotency_key: str = Depends(get_idempotency_key),
    db: Session = Depends(get_db),
):
    """Capture funds from a prior authorization hold."""
    request_hash = compute_payload_hash({"payment_id": payment_id, **payload.model_dump()})

    cached = IdempotencyService.acquire_or_get_cached(
        db=db,
        key=idempotency_key,
        merchant_id=merchant.id,
        request_hash=request_hash,
    )
    if cached:
        status_code, body = cached
        return JSONResponse(status_code=status_code, content=body)

    try:
        payment = PaymentService.capture_payment(
            db=db,
            merchant=merchant,
            payment_id=payment_id,
            amount_cents=payload.amount_cents,
        )
        response_data = schemas.PaymentResponse.model_validate(payment).model_dump(mode="json")
        IdempotencyService.finalize_key(
            db=db,
            key=idempotency_key,
            payment_id=payment.id,
            status_code=status.HTTP_200_OK,
            response_data=response_data,
        )
        db.commit()
        return JSONResponse(status_code=status.HTTP_200_OK, content=response_data)
    except Exception:
        db.rollback()
        raise


@router.post(
    "/payments/{payment_id}/cancel",
    response_model=schemas.PaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Void an Authorized Payment",
)
def cancel_payment(
    payment_id: str,
    payload: schemas.CancelRequest = schemas.CancelRequest(),
    merchant: models.Merchant = Depends(get_authenticated_merchant),
    idempotency_key: str = Depends(get_idempotency_key),
    db: Session = Depends(get_db),
):
    """Void/cancel an authorization hold prior to capture."""
    request_hash = compute_payload_hash({"payment_id": payment_id, **payload.model_dump()})

    cached = IdempotencyService.acquire_or_get_cached(
        db=db,
        key=idempotency_key,
        merchant_id=merchant.id,
        request_hash=request_hash,
    )
    if cached:
        status_code, body = cached
        return JSONResponse(status_code=status_code, content=body)

    try:
        payment = PaymentService.cancel_payment(
            db=db,
            merchant=merchant,
            payment_id=payment_id,
            reason=payload.reason,
        )
        response_data = schemas.PaymentResponse.model_validate(payment).model_dump(mode="json")
        IdempotencyService.finalize_key(
            db=db,
            key=idempotency_key,
            payment_id=payment.id,
            status_code=status.HTTP_200_OK,
            response_data=response_data,
        )
        db.commit()
        return JSONResponse(status_code=status.HTTP_200_OK, content=response_data)
    except Exception:
        db.rollback()
        raise


@router.post(
    "/payments/{payment_id}/refund",
    response_model=schemas.RefundResponse,
    status_code=status.HTTP_200_OK,
    summary="Issue a Partial or Full Refund",
)
def refund_payment(
    payment_id: str,
    payload: schemas.RefundRequest,
    merchant: models.Merchant = Depends(get_authenticated_merchant),
    idempotency_key: str = Depends(get_idempotency_key),
    db: Session = Depends(get_db),
):
    """Process a refund against a captured payment."""
    request_hash = compute_payload_hash({"payment_id": payment_id, **payload.model_dump()})

    cached = IdempotencyService.acquire_or_get_cached(
        db=db,
        key=idempotency_key,
        merchant_id=merchant.id,
        request_hash=request_hash,
    )
    if cached:
        status_code, body = cached
        return JSONResponse(status_code=status_code, content=body)

    try:
        refund, payment, remaining_balance = PaymentService.refund_payment(
            db=db,
            merchant=merchant,
            payment_id=payment_id,
            amount_cents=payload.amount_cents,
            reason=payload.reason,
        )

        response_data = {
            "refund_id": refund.id,
            "payment_id": payment.id,
            "amount_refunded_cents": refund.amount_cents,
            "remaining_balance_cents": remaining_balance,
            "payment_status": payment.status,
            "status": refund.status,
            "created_at": refund.created_at.isoformat(),
        }

        IdempotencyService.finalize_key(
            db=db,
            key=idempotency_key,
            payment_id=payment.id,
            status_code=status.HTTP_200_OK,
            response_data=response_data,
        )
        db.commit()
        return JSONResponse(status_code=status.HTTP_200_OK, content=response_data)
    except Exception:
        db.rollback()
        raise


@router.get(
    "/payments/{payment_id}",
    response_model=schemas.PaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve Payment Details",
)
def get_payment(
    payment_id: str,
    merchant: models.Merchant = Depends(get_authenticated_merchant),
    db: Session = Depends(get_db),
):
    """Retrieve full payment details by identifier."""
    payment = (
        db.query(models.Payment)
        .filter_by(id=payment_id, merchant_id=merchant.id)
        .first()
    )
    if not payment:
        raise GatewayException("payment_not_found", f"Payment '{payment_id}' not found.", status_code=404)
    return payment


@router.get(
    "/merchants/{merchant_id}/ledger-summary",
    response_model=schemas.LedgerSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Query Genuine Double-Entry Ledger Summary",
)
def get_ledger_summary(
    merchant_id: str,
    merchant: models.Merchant = Depends(get_authenticated_merchant),
    db: Session = Depends(get_db),
):
    """Query double-entry ledger balance and assert global debit/credit balance."""
    if merchant.id != merchant_id:
        raise GatewayException("unauthorized_merchant_access", "Cannot query other merchant ledger.", status_code=403)
    return PaymentService.get_merchant_ledger_summary(db=db, merchant_id=merchant_id)


@router.post(
    "/webhooks/verify",
    status_code=status.HTTP_200_OK,
    summary="Verify HMAC-SHA256 Webhook Signature",
)
def verify_webhook_signature(
    req: schemas.WebhookVerifyRequest,
    merchant: models.Merchant = Depends(get_authenticated_merchant),
):
    """Cryptographic helper to verify webhook authenticity and timing-safe signature."""
    secret = req.secret or merchant.webhook_secret
    valid = WebhookService.verify_signature(
        secret=secret,
        signature_header=req.signature_header,
        payload_json=req.payload_json,
    )
    return {"valid": valid}
