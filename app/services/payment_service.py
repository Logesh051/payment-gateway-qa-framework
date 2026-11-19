"""Core Payment Service & Transaction Orchestration.

Manages the payment lifecycle, deterministic banking simulation,
genuine double-entry ledger balancing, and webhook event dispatch
within atomic database transactions.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    AmountValidationException,
    CardExpiredException,
    GatewayTimeoutException,
    InsufficientFundsException,
    RefundLimitExceededException,
    SuspectedFraudException,
)
from app.core.state_machine import PaymentStatus, validate_transition
from app.db import models
from app.services.webhook_service import WebhookService


class PaymentService:
    """Orchestrates payment operations, state changes, and double-entry ledger entries."""

    @staticmethod
    def _validate_amount_and_currency(amount_cents: int, currency: str) -> None:
        """Enforce strict boundary value checks on transaction amounts and currency."""
        if not isinstance(amount_cents, int):
            raise AmountValidationException(
                "Amount must be an integer minor currency unit (cents).",
                code="invalid_amount_type",
            )
        if amount_cents < settings.MIN_TRANSACTION_AMOUNT_CENTS:
            raise AmountValidationException(
                f"Amount ({amount_cents} cents) is below minimum threshold of {settings.MIN_TRANSACTION_AMOUNT_CENTS} cents.",
                code="amount_below_minimum",
                details={
                    "minimum_allowed": settings.MIN_TRANSACTION_AMOUNT_CENTS,
                    "provided_amount": amount_cents,
                },
            )
        if amount_cents > settings.MAX_TRANSACTION_AMOUNT_CENTS:
            raise AmountValidationException(
                f"Amount ({amount_cents} cents) exceeds maximum limit of {settings.MAX_TRANSACTION_AMOUNT_CENTS} cents.",
                code="amount_exceeds_transaction_limit",
                details={
                    "maximum_allowed": settings.MAX_TRANSACTION_AMOUNT_CENTS,
                    "provided_amount": amount_cents,
                },
            )
        if currency.upper() not in settings.SUPPORTED_CURRENCIES:
            raise AmountValidationException(
                f"Currency '{currency}' is not supported.",
                code="unsupported_currency",
                details={"supported": list(settings.SUPPORTED_CURRENCIES)},
            )

    @staticmethod
    def _simulate_card_evaluation(card_number: str) -> str:
        """Simulate card processing using deterministic test card numbers.

        Returns:
            Card brand name if approved.

        Raises:
            InsufficientFundsException: Card ends in 0002 (HTTP 402).
            CardExpiredException: Card ends in 0003 (HTTP 402).
            SuspectedFraudException: Card ends in 0004 (HTTP 403).
            GatewayTimeoutException: Card ends in 0005 (HTTP 504).
        """
        clean_num = card_number.replace(" ", "").replace("-", "")
        last4 = clean_num[-4:] if len(clean_num) >= 4 else "0000"

        if clean_num.endswith("0002"):
            raise InsufficientFundsException(card_last4=last4)
        if clean_num.endswith("0003"):
            raise CardExpiredException(card_last4=last4)
        if clean_num.endswith("0004"):
            raise SuspectedFraudException(card_last4=last4)
        if clean_num.endswith("0005"):
            raise GatewayTimeoutException()

        # Identify simple brand
        if clean_num.startswith("4"):
            return "VISA"
        elif clean_num.startswith(("51", "52", "53", "54", "55")):
            return "MASTERCARD"
        return "GENERIC_CARD"

    @classmethod
    def _post_double_entry_batch(
        cls,
        db: Session,
        payment_id: str,
        merchant_id: str,
        currency: str,
        debit_account: str,
        credit_account: str,
        amount_cents: int,
        description: str,
    ) -> str:
        """Create a balanced pair of DEBIT and CREDIT entries sharing a unique batch_id.

        Invariant: Sum(DEBIT) == Sum(CREDIT) == amount_cents
        """
        batch_id = f"bat_{uuid.uuid4().hex[:14]}"
        now = datetime.now(timezone.utc)

        debit_entry = models.LedgerEntry(
            id=f"led_{uuid.uuid4().hex[:14]}",
            batch_id=batch_id,
            payment_id=payment_id,
            merchant_id=merchant_id,
            entry_type="DEBIT",
            account_name=debit_account,
            amount_cents=amount_cents,
            currency=currency,
            description=description,
            created_at=now,
        )

        credit_entry = models.LedgerEntry(
            id=f"led_{uuid.uuid4().hex[:14]}",
            batch_id=batch_id,
            payment_id=payment_id,
            merchant_id=merchant_id,
            entry_type="CREDIT",
            account_name=credit_account,
            amount_cents=amount_cents,
            currency=currency,
            description=description,
            created_at=now,
        )

        db.add(debit_entry)
        db.add(credit_entry)
        db.flush()
        return batch_id

    @classmethod
    def create_payment(
        cls,
        db: Session,
        merchant: models.Merchant,
        amount_cents: int,
        currency: str,
        card_number: str,
        exp_month: int,
        exp_year: int,
        cvv: str,
        capture: bool,
        customer_email: Optional[str] = None,
        description: Optional[str] = None,
    ) -> models.Payment:
        """Execute atomic payment creation, card evaluation, ledger posting, and webhook emission."""
        cls._validate_amount_and_currency(amount_cents, currency)

        clean_num = card_number.replace(" ", "").replace("-", "")
        last4 = clean_num[-4:] if len(clean_num) >= 4 else "0000"
        payment_id = f"pay_{uuid.uuid4().hex[:18]}"

        # Evaluate simulated card issuer response
        try:
            brand = cls._simulate_card_evaluation(clean_num)
        except (
            InsufficientFundsException,
            CardExpiredException,
            SuspectedFraudException,
            GatewayTimeoutException,
        ) as err:
            err.details["payment_id"] = payment_id
            # Create failed payment record in database for auditability
            failed_payment = models.Payment(
                id=payment_id,
                merchant_id=merchant.id,
                amount_cents=amount_cents,
                currency=currency.upper(),
                status=PaymentStatus.FAILED.value,
                captured=False,
                card_last4=last4,
                card_brand="UNKNOWN",
                failure_code=err.code,
                failure_message=err.message,
                customer_email=customer_email,
                description=description,
            )
            db.add(failed_payment)
            db.flush()

            # Stage webhook notification for failure
            WebhookService.stage_event(
                db=db,
                payment_id=payment_id,
                merchant_id=merchant.id,
                webhook_secret=merchant.webhook_secret,
                event_type="payment.failed",
                data={
                    "payment_id": payment_id,
                    "amount_cents": amount_cents,
                    "currency": currency.upper(),
                    "status": PaymentStatus.FAILED.value,
                    "failure_code": err.code,
                    "failure_message": err.message,
                },
            )
            raise err

        # Payment approved: determine target state (AUTHORIZED or CAPTURED)
        target_status = PaymentStatus.CAPTURED if capture else PaymentStatus.AUTHORIZED
        payment = models.Payment(
            id=payment_id,
            merchant_id=merchant.id,
            amount_cents=amount_cents,
            currency=currency.upper(),
            status=target_status.value,
            captured=capture,
            card_last4=last4,
            card_brand=brand,
            customer_email=customer_email,
            description=description,
        )
        db.add(payment)
        db.flush()

        # Post genuine double-entry ledger entries
        if capture:
            cls._post_double_entry_batch(
                db=db,
                payment_id=payment_id,
                merchant_id=merchant.id,
                currency=currency.upper(),
                debit_account="customer_funds_clearing",
                credit_account="merchant_available_balance",
                amount_cents=amount_cents,
                description=f"Direct capture for payment {payment_id}",
            )
            event_type = "payment.captured"
        else:
            cls._post_double_entry_batch(
                db=db,
                payment_id=payment_id,
                merchant_id=merchant.id,
                currency=currency.upper(),
                debit_account="customer_funds_clearing",
                credit_account="merchant_receivables",
                amount_cents=amount_cents,
                description=f"Authorization hold for payment {payment_id}",
            )
            event_type = "payment.authorized"

        # Stage signed webhook event
        WebhookService.stage_event(
            db=db,
            payment_id=payment_id,
            merchant_id=merchant.id,
            webhook_secret=merchant.webhook_secret,
            event_type=event_type,
            data={
                "payment_id": payment_id,
                "amount_cents": amount_cents,
                "currency": currency.upper(),
                "status": target_status.value,
                "captured": capture,
                "card_last4": last4,
            },
        )

        return payment

    @classmethod
    def capture_payment(
        cls,
        db: Session,
        merchant: models.Merchant,
        payment_id: str,
        amount_cents: Optional[int] = None,
    ) -> models.Payment:
        """Capture an authorized payment and transfer funds to merchant available balance."""
        payment = (
            db.query(models.Payment)
            .filter_by(id=payment_id, merchant_id=merchant.id)
            .first()
        )
        if not payment:
            from app.core.exceptions import GatewayException
            raise GatewayException("payment_not_found", f"Payment '{payment_id}' not found.", status_code=404)

        # Enforce valid state transition (must be AUTHORIZED)
        current_status = PaymentStatus(payment.status)
        validate_transition(current_status, PaymentStatus.CAPTURED, payment_id=payment_id)

        capture_amount = amount_cents or payment.amount_cents
        if capture_amount > payment.amount_cents:
            raise AmountValidationException(
                f"Capture amount ({capture_amount}) cannot exceed authorized amount ({payment.amount_cents}).",
                code="capture_amount_exceeds_authorized",
            )

        # Update payment status
        payment.status = PaymentStatus.CAPTURED.value
        payment.captured = True
        payment.updated_at = datetime.now(timezone.utc)
        db.flush()

        # Reclassify funds from merchant_receivables to merchant_available_balance
        cls._post_double_entry_batch(
            db=db,
            payment_id=payment_id,
            merchant_id=merchant.id,
            currency=payment.currency,
            debit_account="merchant_receivables",
            credit_account="merchant_available_balance",
            amount_cents=capture_amount,
            description=f"Captured authorized funds for payment {payment_id}",
        )

        # Stage webhook event
        WebhookService.stage_event(
            db=db,
            payment_id=payment_id,
            merchant_id=merchant.id,
            webhook_secret=merchant.webhook_secret,
            event_type="payment.captured",
            data={
                "payment_id": payment_id,
                "amount_cents": capture_amount,
                "currency": payment.currency,
                "status": PaymentStatus.CAPTURED.value,
            },
        )

        return payment

    @classmethod
    def cancel_payment(
        cls,
        db: Session,
        merchant: models.Merchant,
        payment_id: str,
        reason: Optional[str] = None,
    ) -> models.Payment:
        """Void / Cancel an authorized payment before capture."""
        payment = (
            db.query(models.Payment)
            .filter_by(id=payment_id, merchant_id=merchant.id)
            .first()
        )
        if not payment:
            from app.core.exceptions import GatewayException
            raise GatewayException("payment_not_found", f"Payment '{payment_id}' not found.", status_code=404)

        current_status = PaymentStatus(payment.status)
        validate_transition(current_status, PaymentStatus.CANCELLED, payment_id=payment_id)

        payment.status = PaymentStatus.CANCELLED.value
        payment.updated_at = datetime.now(timezone.utc)
        db.flush()

        # Reverse authorization hold: Debit merchant_receivables, Credit customer_funds_clearing
        cls._post_double_entry_batch(
            db=db,
            payment_id=payment_id,
            merchant_id=merchant.id,
            currency=payment.currency,
            debit_account="merchant_receivables",
            credit_account="customer_funds_clearing",
            amount_cents=payment.amount_cents,
            description=f"Void authorization hold for payment {payment_id}. Reason: {reason or 'merchant_void'}",
        )

        # Stage webhook event
        WebhookService.stage_event(
            db=db,
            payment_id=payment_id,
            merchant_id=merchant.id,
            webhook_secret=merchant.webhook_secret,
            event_type="payment.cancelled",
            data={
                "payment_id": payment_id,
                "status": PaymentStatus.CANCELLED.value,
                "reason": reason,
            },
        )

        return payment

    @classmethod
    def refund_payment(
        cls,
        db: Session,
        merchant: models.Merchant,
        payment_id: str,
        amount_cents: int,
        reason: Optional[str] = None,
    ) -> Tuple[models.Refund, models.Payment, int]:
        """Process partial or full refund against a captured payment.

        Returns:
            Tuple of (Refund model, Updated Payment model, Remaining refundable balance cents).
        """
        if amount_cents <= 0:
            raise AmountValidationException("Refund amount must be strictly greater than zero.")

        payment = (
            db.query(models.Payment)
            .filter_by(id=payment_id, merchant_id=merchant.id)
            .first()
        )
        if not payment:
            from app.core.exceptions import GatewayException
            raise GatewayException("payment_not_found", f"Payment '{payment_id}' not found.", status_code=404)

        current_status = PaymentStatus(payment.status)
        # Verify status allows refunds (must be CAPTURED, PARTIALLY_REFUNDED, or SETTLED)
        target_preview = PaymentStatus.PARTIALLY_REFUNDED
        validate_transition(current_status, target_preview, payment_id=payment_id)

        # Calculate already refunded total
        total_refunded = sum(r.amount_cents for r in payment.refunds)
        remaining_balance = payment.amount_cents - total_refunded

        if amount_cents > remaining_balance:
            raise RefundLimitExceededException(
                payment_id=payment_id,
                attempted_cents=amount_cents,
                available_cents=remaining_balance,
            )

        # Create refund entity
        refund_id = f"ref_{uuid.uuid4().hex[:14]}"
        refund = models.Refund(
            id=refund_id,
            payment_id=payment_id,
            merchant_id=merchant.id,
            amount_cents=amount_cents,
            status="COMPLETED",
            reason=reason,
        )
        db.add(refund)

        # Determine new payment state (PARTIALLY_REFUNDED vs fully REFUNDED)
        new_total_refunded = total_refunded + amount_cents
        new_remaining = payment.amount_cents - new_total_refunded

        if new_remaining == 0:
            payment.status = PaymentStatus.REFUNDED.value
        else:
            payment.status = PaymentStatus.PARTIALLY_REFUNDED.value

        payment.updated_at = datetime.now(timezone.utc)
        db.flush()

        # Post compensating double-entry ledger batch:
        # Debit: merchant_available_balance, Credit: customer_funds_clearing
        cls._post_double_entry_batch(
            db=db,
            payment_id=payment_id,
            merchant_id=merchant.id,
            currency=payment.currency,
            debit_account="merchant_available_balance",
            credit_account="customer_funds_clearing",
            amount_cents=amount_cents,
            description=f"Refund {refund_id} for payment {payment_id}. Reason: {reason or 'merchant_refund'}",
        )

        # Stage webhook event
        WebhookService.stage_event(
            db=db,
            payment_id=payment_id,
            merchant_id=merchant.id,
            webhook_secret=merchant.webhook_secret,
            event_type="payment.refunded",
            data={
                "refund_id": refund_id,
                "payment_id": payment_id,
                "amount_refunded_cents": amount_cents,
                "remaining_balance_cents": new_remaining,
                "payment_status": payment.status,
            },
        )

        return refund, payment, new_remaining

    @staticmethod
    def get_merchant_ledger_summary(db: Session, merchant_id: str) -> Dict[str, Any]:
        """Compute the genuine double-entry balance and assert mathematical integrity."""
        entries = (
            db.query(models.LedgerEntry)
            .filter_by(merchant_id=merchant_id)
            .all()
        )

        total_debits = sum(e.amount_cents for e in entries if e.entry_type == "DEBIT")
        total_credits = sum(e.amount_cents for e in entries if e.entry_type == "CREDIT")

        # Merchant available balance: Credits to merchant_available_balance minus Debits
        merchant_credits = sum(
            e.amount_cents for e in entries
            if e.account_name == "merchant_available_balance" and e.entry_type == "CREDIT"
        )
        merchant_debits = sum(
            e.amount_cents for e in entries
            if e.account_name == "merchant_available_balance" and e.entry_type == "DEBIT"
        )
        available_balance = merchant_credits - merchant_debits

        return {
            "merchant_id": merchant_id,
            "currency": "USD",
            "available_balance_cents": available_balance,
            "total_debits_cents": total_debits,
            "total_credits_cents": total_credits,
            "is_balanced": total_debits == total_credits,
            "entry_count": len(entries),
        }
