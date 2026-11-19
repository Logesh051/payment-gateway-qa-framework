# 04 - API Contract & Interface Specification

**Document Version:** 1.1.0 (Post-Architecture Review Updates)  
**Format:** RESTful JSON, OpenAPI 3.1 compliant  
**Base URL:** `http://localhost:8000`  

---

## 1. Common Headers & Authentication

All mutating requests require merchant authentication and idempotency keys:

| Header Name | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `X-API-Key` | String | Yes | Merchant API key (e.g., `sk_test_...`). |
| `Idempotency-Key` | String (UUIDv4) | Yes (on `POST`) | Client-supplied unique token to guarantee atomic execution. |
| `Content-Type` | String | Yes | Must be `application/json`. |

---

## 2. Standardized Error Envelope

All error responses strictly return the standard envelope:

```json
{
  "error": {
    "code": "invalid_state_transition",
    "message": "Cannot transition payment pay_01HN84XQ9W12 from CANCELLED to CAPTURED.",
    "details": {
      "payment_id": "pay_01HN84XQ9W12",
      "current_status": "CANCELLED",
      "attempted_transition": "CAPTURED",
      "allowed_transitions": []
    },
    "timestamp": "2026-11-16T17:15:00Z"
  }
}
```

### Standard Error Codes & HTTP Status Codes:
- `idempotency_payload_mismatch` (`HTTP 409 Conflict`)
- `concurrent_mutation_in_progress` (`HTTP 409 Conflict`)
- `invalid_state_transition` (`HTTP 409 Conflict`)
- `amount_below_minimum` (`HTTP 400 Bad Request`)
- `amount_exceeds_transaction_limit` (`HTTP 400 Bad Request`)
- `unsupported_currency` (`HTTP 400 Bad Request`)
- `insufficient_funds` (`HTTP 402 Payment Required`)
- `card_expired` (`HTTP 402 Payment Required`)
- `suspected_fraud` (`HTTP 403 Forbidden`)
- `gateway_timeout` (`HTTP 504 Gateway Timeout`)
- `refund_amount_exceeds_balance` (`HTTP 422 Unprocessable Entity`)

---

## 3. Endpoints

### 3.1 Create / Authorize Payment
- **Method / Path:** `POST /v1/payments`
- **Headers:** `Idempotency-Key`, `X-API-Key`

#### Request Payload:
```json
{
  "amount_cents": 2500,
  "currency": "USD",
  "card_number": "4000000000000001",
  "exp_month": 12,
  "exp_year": 2028,
  "cvv": "123",
  "capture": false,
  "customer_email": "qa.engineer@example.com",
  "description": "Order #1042 Test Payment"
}
```

#### Successful Response (`HTTP 201 Created`):
```json
{
  "id": "pay_01HN84XQ9W12AB34CD",
  "merchant_id": "mer_test_98765",
  "amount_cents": 2500,
  "currency": "USD",
  "status": "AUTHORIZED",
  "captured": false,
  "card_last4": "0001",
  "card_brand": "VISA",
  "failure_code": null,
  "failure_message": null,
  "created_at": "2026-11-16T17:15:00.000Z",
  "updated_at": "2026-11-16T17:15:00.120Z"
}
```

---

### 3.2 Capture Payment
- **Method / Path:** `POST /v1/payments/{payment_id}/capture`
- **Headers:** `Idempotency-Key`, `X-API-Key`

#### Request Payload (Optional Amount for Partial Capture):
```json
{
  "amount_cents": 2500
}
```

#### Successful Response (`HTTP 200 OK`):
```json
{
  "id": "pay_01HN84XQ9W12AB34CD",
  "merchant_id": "mer_test_98765",
  "amount_cents": 2500,
  "currency": "USD",
  "status": "CAPTURED",
  "captured": true,
  "card_last4": "0001",
  "card_brand": "VISA",
  "created_at": "2026-11-16T17:15:00.000Z",
  "updated_at": "2026-11-16T17:16:30.000Z"
}
```

---

### 3.3 Void / Cancel Payment
- **Method / Path:** `POST /v1/payments/{payment_id}/cancel`
- **Headers:** `Idempotency-Key`, `X-API-Key`

#### Request Payload:
```json
{
  "reason": "customer_requested_cancellation"
}
```

#### Successful Response (`HTTP 200 OK`):
```json
{
  "id": "pay_01HN84XQ9W12AB34CD",
  "status": "CANCELLED",
  "cancellation_reason": "customer_requested_cancellation",
  "updated_at": "2026-11-16T17:17:00.000Z"
}
```

---

### 3.4 Refund Payment
- **Method / Path:** `POST /v1/payments/{payment_id}/refund`
- **Headers:** `Idempotency-Key`, `X-API-Key`

#### Request Payload:
```json
{
  "amount_cents": 1000,
  "reason": "defective_item_return"
}
```

#### Successful Response (`HTTP 200 OK`):
```json
{
  "refund_id": "ref_99AZ12XY45KL78",
  "payment_id": "pay_01HN84XQ9W12AB34CD",
  "amount_refunded_cents": 1000,
  "remaining_balance_cents": 1500,
  "payment_status": "PARTIALLY_REFUNDED",
  "status": "COMPLETED",
  "created_at": "2026-11-16T17:18:00.000Z"
}
```

---

### 3.5 Query Payment Details
- **Method / Path:** `GET /v1/payments/{payment_id}`
- **Headers:** `X-API-Key`
- **Response:** `HTTP 200 OK` with full payment entity, current state, and refund history.

---

### 3.6 Query Double-Entry Ledger Summary
- **Method / Path:** `GET /v1/merchants/{merchant_id}/ledger-summary`
- **Headers:** `X-API-Key`
- **Response:** `HTTP 200 OK`
```json
{
  "merchant_id": "mer_test_98765",
  "currency": "USD",
  "available_balance_cents": 2500,
  "total_debits_cents": 5000,
  "total_credits_cents": 5000,
  "is_balanced": true,
  "entry_count": 4
}
```

---

## 4. Webhook Notification Contract

When a payment transitions to a terminal or key state (`AUTHORIZED`, `CAPTURED`, `CANCELLED`, `REFUNDED`, `FAILED`), the gateway creates and signs a webhook event:

### 4.1 Headers Sent in Webhook POST:
- `Content-Type: application/json`
- `X-Signature-SHA256: t=1763313300,v1=5d41402abc4b2a76b9719d911017c592...`
- `X-Event-Id: evt_55AA77BB`

### 4.2 Webhook Signature Calculation:
$$\text{Signature} = \text{HMAC-SHA256}(webhook\_secret, \text{"t="} + timestamp + \text{"."} + raw\_json\_body)$$
Merchant endpoints verify this signature using timing-safe comparison (`hmac.compare_digest`).
