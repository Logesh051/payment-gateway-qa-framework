# API Contract

## Health check
- GET `/health`
- Expected: HTTP 200 and `status: healthy`.

## Create payment
- POST `/payments`
- Required header: `Idempotency-Key`
- JSON body:
```json
{"amount_rupees":500,"card_number":"4111111111111111"}
```
- Amount must be a positive whole number.
- Card number must contain 16 to 19 digits.
- Dummy card ending in `0002` simulates a decline; other valid dummy cards simulate success.
- New transaction returns HTTP 201 and status SUCCESS or FAILED.
- Same request with same key returns original payment.
- Same key with different payment details returns HTTP 409.
- Invalid fields return HTTP 422. Missing key returns HTTP 400.

## Retrieve payment
- GET `/payments/{payment_id}`
- Expected: HTTP 200 with payment details, or HTTP 404 if not found.

Educational simulation only; no real payments.
