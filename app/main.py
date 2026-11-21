"""A small simulated payment API built for QA practice."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import sqlite3
import uuid

from fastapi import FastAPI, Header, HTTPException, Response

from app.database import get_connection, init_db
from app.schemas import PaymentRequest, PaymentResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Payment Gateway QA Simulator",
    description="Educational simulation only. It never processes real payments.",
    version="1.0.0",
    lifespan=lifespan,
)


def payment_to_dict(row):
    return {
        "id": row["id"],
        "amount_rupees": row["amount_rupees"],
        "currency": "INR",
        "card_last4": row["card_last4"],
        "status": row["status"],
        "failure_reason": row["failure_reason"],
        "created_at": row["created_at"],
    }


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "payment-gateway-qa-simulator"}


@app.post("/payments", response_model=PaymentResponse, status_code=201)
def create_payment(
    payload: PaymentRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Create a dummy payment. A card ending in 0002 simulates a decline."""
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required")

    idempotency_key = idempotency_key.strip()
    card_last4 = payload.card_number[-4:]

    with get_connection() as connection:
        existing = connection.execute(
            "SELECT * FROM payments WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()

        if existing:
            same_request = (
                existing["amount_rupees"] == payload.amount_rupees
                and existing["card_last4"] == card_last4
            )
            if not same_request:
                raise HTTPException(status_code=409, detail="Idempotency key already used for different payment details")
            response.status_code = 200
            return payment_to_dict(existing)

        payment_status = "FAILED" if card_last4 == "0002" else "SUCCESS"
        failure_reason = "Simulated card decline" if payment_status == "FAILED" else None
        payment_id = f"pay_{uuid.uuid4().hex[:12]}"
        created_at = datetime.now(timezone.utc).isoformat()

        try:
            connection.execute("""
                INSERT INTO payments
                (id, amount_rupees, card_last4, status, failure_reason, idempotency_key, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (payment_id, payload.amount_rupees, card_last4, payment_status,
                  failure_reason, idempotency_key, created_at))
            connection.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="Duplicate payment request")

        return {
            "id": payment_id,
            "amount_rupees": payload.amount_rupees,
            "currency": "INR",
            "card_last4": card_last4,
            "status": payment_status,
            "failure_reason": failure_reason,
            "created_at": created_at,
        }


@app.get("/payments/{payment_id}", response_model=PaymentResponse)
def get_payment(payment_id: str):
    with get_connection() as connection:
        payment = connection.execute(
            "SELECT * FROM payments WHERE id = ?", (payment_id,)
        ).fetchone()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment_to_dict(payment)
