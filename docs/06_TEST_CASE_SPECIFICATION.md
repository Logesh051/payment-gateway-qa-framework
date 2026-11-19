# 06 - Test Case Specification & Requirements Traceability Matrix (RTM)

**Document Version:** 1.0.0  
**Target Suite:** Independent QA Automated Test Framework (`tests/`)  
**Traceability Scope:** BR-01 through BR-08, API Contracts, and Non-Functional Invariants  

---

## 1. Requirements Traceability Matrix (RTM)

| Business Rule / Requirement | Description | Test Suite | Test Case IDs |
| :--- | :--- | :--- | :--- |
| **BR-01: Idempotency** | Prevent duplicate charges, payload mismatch rejection, replay caching | `tests/api/test_idempotency.py` | `TC-IDEM-030`, `TC-IDEM-031`, `TC-IDEM-032`, `TC-IDEM-033`, `TC-IDEM-034` |
| **BR-02: Amount & Currency** | Integer cents, boundary limits ($0.50 to $100k), ISO currency check | `tests/api/test_functional_negative.py` | `TC-NEG-020`, `TC-NEG-021`, `TC-NEG-022`, `TC-NEG-023` |
| **BR-03: State Machine** | Enforce valid transitions, reject illegal transitions with HTTP 409 | `tests/unit/test_state_transitions_unit.py`, `tests/api/test_state_transitions_api.py` | `TC-SM-001`, `TC-SM-002`, `TC-SM-003`, `TC-TRANS-040`, `TC-TRANS-041`, `TC-TRANS-042`, `TC-TRANS-043` |
| **BR-04: Bank Decline Simulation** | Deterministic cards trigger 402, 403, 504 status codes | `tests/api/test_functional_negative.py` | `TC-NEG-024` |
| **BR-05: Concurrency Safety** | SQLite WAL write serialization, double-capture prevention | `tests/integration/test_concurrency.py` | `TC-CONC-080`, `TC-CONC-081`, `TC-CONC-082`, `TC-CONC-083`, `TC-CONC-084` |
| **BR-06: Webhooks** | HMAC-SHA256 signatures, replay window (5 min), payload tampering | `tests/api/test_webhooks.py`, `tests/integration/test_db_persistence.py` | `TC-WH-050`, `TC-WH-051`, `TC-WH-052`, `TC-WH-053`, `TC-WH-054`, `TC-DB-063` |
| **BR-07: Refunds & Balance** | Cumulative limits, partial refunds, overdraft prevention (422) | `tests/api/test_payment_lifecycle.py`, `tests/api/test_functional_negative.py`, `tests/integration/test_db_persistence.py` | `TC-API-014`, `TC-NEG-025`, `TC-DB-062`, `TC-LED-072`, `TC-CONC-083` |
| **BR-08: Double-Entry Ledger** | Mathematical balance: $\sum \text{Debits} == \sum \text{Credits}$ across batches | `tests/integration/test_double_entry_ledger.py` | `TC-LED-070`, `TC-LED-071`, `TC-LED-072`, `TC-LED-073` |
| **API Infrastructure** | Health check, Authentication (401), Missing headers (400), 404 | `tests/api/test_health_and_auth.py` | `TC-API-001`, `TC-API-002`, `TC-API-003`, `TC-API-004`, `TC-API-005` |
| **Database Persistence** | Direct read-only SQL assertions and read-only harness security | `tests/integration/test_db_persistence.py` | `TC-DB-060`, `TC-DB-061`, `TC-DB-064` |

---

## 2. Test Case Inventory & Specifications

### 2.1 State Machine Unit Tests (`tests/unit/test_state_transitions_unit.py`)

#### `TC-SM-001`
- **Scenario:** Valid state machine transitions.
- **Preconditions:** Domain state machine loaded.
- **Input Data:** Source and valid target state pairs (e.g. `CREATED` $\to$ `AUTHORIZED`, `AUTHORIZED` $\to$ `CAPTURED`, etc.).
- **Expected Result:** `validate_transition` executes without raising exceptions.
- **Actual Result:** Verified — all valid pairs pass.
- **Status:** PASS

#### `TC-SM-002`
- **Scenario:** Illegal state machine transitions.
- **Preconditions:** Source state has defined transition boundaries.
- **Input Data:** 12 parameterized illegal transitions (e.g. `CANCELLED` $\to$ `CAPTURED`, `FAILED` $\to$ `AUTHORIZED`).
- **Expected Result:** Raises `InvalidStateTransitionException` with status code 409.
- **Actual Result:** Verified — all illegal transitions raise HTTP 409.
- **Status:** PASS

#### `TC-SM-003`
- **Scenario:** Terminal states allow zero transitions.
- **Preconditions:** States: `REFUNDED`, `CANCELLED`, `FAILED`.
- **Input Data:** `get_allowed_transitions(terminal_state)`.
- **Expected Result:** Returns empty list `[]`.
- **Actual Result:** Verified — returns `[]`.
- **Status:** PASS

---

### 2.2 Health & Authentication Tests (`tests/api/test_health_and_auth.py`)

#### `TC-API-001`
- **Scenario:** System health endpoint availability.
- **Preconditions:** Service running.
- **Input Data:** `GET /health`.
- **Expected Result:** HTTP 200 OK with `{"status": "healthy"}`.
- **Actual Result:** HTTP 200 OK.
- **Status:** PASS

#### `TC-API-002`
- **Scenario:** Missing API key header.
- **Preconditions:** Protected endpoint called without credentials.
- **Input Data:** `POST /v1/payments` with no `X-API-Key`.
- **Expected Result:** HTTP 401 Unauthorized with error code `unauthorized`.
- **Actual Result:** HTTP 401 Unauthorized.
- **Status:** PASS

#### `TC-API-003`
- **Scenario:** Invalid API key header.
- **Preconditions:** None.
- **Input Data:** `X-API-Key: 'sk_test_bogus_key_999'`.
- **Expected Result:** HTTP 401 Unauthorized.
- **Actual Result:** HTTP 401 Unauthorized.
- **Status:** PASS

#### `TC-API-004`
- **Scenario:** Missing Idempotency-Key on mutating request.
- **Preconditions:** Authenticated merchant.
- **Input Data:** `POST /v1/payments` without `Idempotency-Key` header.
- **Expected Result:** HTTP 400 Bad Request with code `missing_idempotency_key`.
- **Actual Result:** HTTP 400 Bad Request.
- **Status:** PASS

#### `TC-API-005`
- **Scenario:** Query non-existent payment ID.
- **Preconditions:** Payment ID not present in database.
- **Input Data:** `GET /v1/payments/pay_nonexistent_999999`.
- **Expected Result:** HTTP 404 Not Found with code `payment_not_found`.
- **Actual Result:** HTTP 404 Not Found.
- **Status:** PASS

---

### 2.3 Payment Lifecycle Tests (`tests/api/test_payment_lifecycle.py`)

#### `TC-API-010`
- **Scenario:** Direct capture payment creation.
- **Preconditions:** Valid merchant, new idempotency key.
- **Input Data:** `amount_cents=5000`, `currency='USD'`, `capture=True`.
- **Expected Result:** HTTP 201 Created, `status='CAPTURED'`, `captured=True`, schema validated.
- **Actual Result:** HTTP 201 Created.
- **Status:** PASS

#### `TC-API-011`
- **Scenario:** Two-step payment authorization hold.
- **Preconditions:** Valid merchant.
- **Input Data:** `amount_cents=8000`, `capture=False`.
- **Expected Result:** HTTP 201 Created, `status='AUTHORIZED'`, `captured=False`.
- **Actual Result:** HTTP 201 Created.
- **Status:** PASS

#### `TC-API-012`
- **Scenario:** Capture previously authorized payment.
- **Preconditions:** Payment in `AUTHORIZED` status.
- **Input Data:** `POST /v1/payments/{id}/capture` with `amount_cents=8000`.
- **Expected Result:** HTTP 200 OK, transitions to `CAPTURED`, `captured=True`.
- **Actual Result:** HTTP 200 OK.
- **Status:** PASS

#### `TC-API-013`
- **Scenario:** Void / cancel an authorized payment.
- **Preconditions:** Payment in `AUTHORIZED` status.
- **Input Data:** `POST /v1/payments/{id}/cancel` with reason.
- **Expected Result:** HTTP 200 OK, transitions to `CANCELLED`.
- **Actual Result:** HTTP 200 OK.
- **Status:** PASS

#### `TC-API-014`
- **Scenario:** Incremental partial and full refund flow.
- **Preconditions:** Payment captured for $100.00 (10000 cents).
- **Input Data:** Refund 1: 3000 cents. Refund 2: 7000 cents.
- **Expected Result:** Refund 1 returns `PARTIALLY_REFUNDED` (remaining 7000). Refund 2 returns `REFUNDED` (remaining 0).
- **Actual Result:** HTTP 200 OK on both steps.
- **Status:** PASS

#### `TC-API-015`
- **Scenario:** Query payment details via GET endpoint.
- **Preconditions:** Existing payment in database.
- **Input Data:** `GET /v1/payments/{id}`.
- **Expected Result:** HTTP 200 OK with full payment entity.
- **Actual Result:** HTTP 200 OK.
- **Status:** PASS

---

### 2.4 Functional & Negative Tests (`tests/api/test_functional_negative.py`)

#### `TC-NEG-020`
- **Scenario:** Boundary value analysis on amounts.
- **Preconditions:** None.
- **Input Data:** 49 cents (< min), 0 cents, 10,000,001 cents (> max).
- **Expected Result:** HTTP 400 Bad Request with corresponding error codes.
- **Actual Result:** HTTP 400 Bad Request.
- **Status:** PASS

#### `TC-NEG-021`
- **Scenario:** Reject floating-point cents.
- **Preconditions:** None.
- **Input Data:** `amount_cents=19.99`.
- **Expected Result:** HTTP 422 Unprocessable Entity (`validation_error`).
- **Actual Result:** HTTP 422 Unprocessable Entity.
- **Status:** PASS

#### `TC-NEG-022`
- **Scenario:** Reject unsupported currency.
- **Preconditions:** None.
- **Input Data:** `currency='XYZ'`.
- **Expected Result:** HTTP 400 Bad Request (`unsupported_currency`).
- **Actual Result:** HTTP 400 Bad Request.
- **Status:** PASS

#### `TC-NEG-023`
- **Scenario:** Omit mandatory JSON fields.
- **Preconditions:** None.
- **Input Data:** Payloads missing `card_number`, `exp_month`, `cvv`, or `amount_cents`.
- **Expected Result:** HTTP 422 Unprocessable Entity.
- **Actual Result:** HTTP 422 Unprocessable Entity.
- **Status:** PASS

#### `TC-NEG-024`
- **Scenario:** Deterministic bank decline codes.
- **Preconditions:** Deterministic card number suffix.
- **Input Data:** Cards ending in `0002` (funds), `0003` (expired), `0004` (fraud), `0005` (timeout).
- **Expected Result:** HTTP 402 (`insufficient_funds`), 402 (`card_expired`), 403 (`suspected_fraud`), 504 (`gateway_timeout`).
- **Actual Result:** Verified — exact status codes returned.
- **Status:** PASS

#### `TC-NEG-025`
- **Scenario:** Excessive refund attempt.
- **Preconditions:** Payment captured for 5000 cents.
- **Input Data:** Refund request for 6000 cents.
- **Expected Result:** HTTP 422 Unprocessable Entity (`refund_amount_exceeds_balance`).
- **Actual Result:** HTTP 422 Unprocessable Entity.
- **Status:** PASS

---

### 2.5 Idempotency Tests (`tests/api/test_idempotency.py`)

#### `TC-IDEM-030`
- **Scenario:** Replay identical payment request with same Idempotency-Key.
- **Preconditions:** First payment created.
- **Input Data:** Same key, identical payload.
- **Expected Result:** HTTP 201 Created returning identical payment ID from cache. Zero duplicate charges.
- **Actual Result:** HTTP 201 Created.
- **Status:** PASS

#### `TC-IDEM-031`
- **Scenario:** Same Idempotency-Key with different payload.
- **Preconditions:** Key previously completed with original payload.
- **Input Data:** Same key, modified amount ($50.00 $\to$ $95.00).
- **Expected Result:** HTTP 409 Conflict with code `idempotency_payload_mismatch`.
- **Actual Result:** HTTP 409 Conflict.
- **Status:** PASS

#### `TC-IDEM-032`
- **Scenario:** Different Idempotency-Keys with identical payloads.
- **Preconditions:** None.
- **Input Data:** Identical payload with `key_a` and `key_b`.
- **Expected Result:** Two independent HTTP 201 payments with unique IDs.
- **Actual Result:** Two distinct payments created.
- **Status:** PASS

#### `TC-IDEM-033`
- **Scenario:** Idempotent capture replay.
- **Preconditions:** Payment authorized and captured once with `cap_key`.
- **Input Data:** Replay capture request with same `cap_key`.
- **Expected Result:** Cached HTTP 200 OK returned; does not throw 409 Conflict.
- **Actual Result:** HTTP 200 OK.
- **Status:** PASS

#### `TC-IDEM-034`
- **Scenario:** Idempotent refund replay.
- **Preconditions:** Payment captured for 6000 cents. Refund of 2000 cents processed with `ref_key`.
- **Input Data:** Replay refund request with same `ref_key`.
- **Expected Result:** Cached HTTP 200 OK; remaining balance is NOT decremented a second time.
- **Actual Result:** HTTP 200 OK; remaining balance stays 4000 cents.
- **Status:** PASS

---

### 2.6 State Transition API Tests (`tests/api/test_state_transitions_api.py`)

#### `TC-TRANS-040`
- **Scenario:** Capturing already captured payment with new key.
- **Preconditions:** Payment is in `CAPTURED` status.
- **Input Data:** `POST /v1/payments/{id}/capture` with fresh key.
- **Expected Result:** HTTP 409 Conflict (`invalid_state_transition`).
- **Actual Result:** HTTP 409 Conflict.
- **Status:** PASS

#### `TC-TRANS-041`
- **Scenario:** Cancelling captured payment.
- **Preconditions:** Payment in `CAPTURED` status.
- **Input Data:** `POST /v1/payments/{id}/cancel`.
- **Expected Result:** HTTP 409 Conflict (`invalid_state_transition`).
- **Actual Result:** HTTP 409 Conflict.
- **Status:** PASS

#### `TC-TRANS-042`
- **Scenario:** Refunding uncaptured authorization hold.
- **Preconditions:** Payment in `AUTHORIZED` status.
- **Input Data:** `POST /v1/payments/{id}/refund`.
- **Expected Result:** HTTP 409 Conflict (`invalid_state_transition`).
- **Actual Result:** HTTP 409 Conflict.
- **Status:** PASS

#### `TC-TRANS-043`
- **Scenario:** Capturing a cancelled payment.
- **Preconditions:** Payment in `CANCELLED` status.
- **Input Data:** `POST /v1/payments/{id}/capture`.
- **Expected Result:** HTTP 409 Conflict (`invalid_state_transition`).
- **Actual Result:** HTTP 409 Conflict.
- **Status:** PASS

---

### 2.7 Webhook Tests (`tests/api/test_webhooks.py`)

#### `TC-WH-050`
- **Scenario:** Valid HMAC-SHA256 signature verification.
- **Preconditions:** Accurate merchant webhook secret.
- **Input Data:** Signature computed on current timestamp and payload.
- **Expected Result:** HTTP 200 OK with `{"valid": true}`.
- **Actual Result:** HTTP 200 OK.
- **Status:** PASS

#### `TC-WH-051`
- **Scenario:** Tampered payload rejected.
- **Preconditions:** Signature computed on original payload.
- **Input Data:** Payload modified after signing (`amount_cents` changed).
- **Expected Result:** HTTP 200 OK with `{"valid": false}`.
- **Actual Result:** HTTP 200 OK with `valid=false`.
- **Status:** PASS

#### `TC-WH-052`
- **Scenario:** Bogus signature hex rejected.
- **Preconditions:** None.
- **Input Data:** Malformed signature header.
- **Expected Result:** HTTP 200 OK with `{"valid": false}`.
- **Actual Result:** HTTP 200 OK with `valid=false`.
- **Status:** PASS

#### `TC-WH-053`
- **Scenario:** Expired timestamp replay attack rejected.
- **Preconditions:** 5-minute (300s) replay tolerance.
- **Input Data:** Timestamp from 400 seconds in the past.
- **Expected Result:** HTTP 200 OK with `{"valid": false}`.
- **Actual Result:** HTTP 200 OK with `valid=false`.
- **Status:** PASS

#### `TC-WH-054`
- **Scenario:** Future-skewed timestamp rejected.
- **Preconditions:** Clock skew tolerance 300s.
- **Input Data:** Timestamp 450 seconds in the future.
- **Expected Result:** HTTP 200 OK with `{"valid": false}`.
- **Actual Result:** HTTP 200 OK with `valid=false`.
- **Status:** PASS

---

### 2.8 Database Integration & Read-Only Tests (`tests/integration/test_db_persistence.py`)

#### `TC-DB-060`
- **Scenario:** Payment persistence and integrity in SQL database.
- **Preconditions:** Payment created via API.
- **Input Data:** Query `payments` table with `readonly_db`.
- **Expected Result:** Database row exists with matching amount, status, currency, and card brand.
- **Actual Result:** Database row verified.
- **Status:** PASS

#### `TC-DB-061`
- **Scenario:** Idempotency record persistence in SQL database.
- **Preconditions:** Payment initiated with unique key.
- **Input Data:** Query `idempotency_keys` table with `readonly_db`.
- **Expected Result:** Row has `status='COMPLETED'`, correct request hash, and parsable JSON response body.
- **Actual Result:** Database row verified.
- **Status:** PASS

#### `TC-DB-062`
- **Scenario:** Refund record persistence in SQL database.
- **Preconditions:** Refund processed via API.
- **Input Data:** Query `refunds` table with `readonly_db`.
- **Expected Result:** Row exists with matching `amount_cents` and `status='COMPLETED'`.
- **Actual Result:** Database row verified.
- **Status:** PASS

#### `TC-DB-063`
- **Scenario:** Webhook event persistence in SQL database.
- **Preconditions:** Payment captured via API.
- **Input Data:** Query `webhook_events` table with `readonly_db`.
- **Expected Result:** Staged row exists with `event_type='payment.captured'` and valid signature.
- **Actual Result:** Database row verified.
- **Status:** PASS

#### `TC-DB-064`
- **Scenario:** Hardware-level read-only connection security verification.
- **Preconditions:** Connection configured with `PRAGMA query_only = ON`.
- **Input Data:** Attempt to INSERT a record via `readonly_db`.
- **Expected Result:** SQLite raises `OperationalError: attempt to write a readonly database`.
- **Actual Result:** OperationalError raised and write rejected.
- **Status:** PASS

---

### 2.9 Double-Entry Ledger Tests (`tests/integration/test_double_entry_ledger.py`)

#### `TC-LED-070`
- **Scenario:** Batch balance invariant: $\sum \text{Debits} == \sum \text{Credits}$.
- **Preconditions:** Various transactions executed.
- **Input Data:** Group by `batch_id` in `ledger_entries`.
- **Expected Result:** For every batch, debit total strictly equals credit total.
- **Actual Result:** Invariant holds across 100% of batches.
- **Status:** PASS

#### `TC-LED-071`
- **Scenario:** Direct capture ledger postings.
- **Preconditions:** Payment captured for $50.00 (5000 cents).
- **Input Data:** Inspect `ledger_entries` for payment.
- **Expected Result:** DEBIT `customer_funds_clearing` (5000) and CREDIT `merchant_available_balance` (5000).
- **Actual Result:** Verified.
- **Status:** PASS

#### `TC-LED-072`
- **Scenario:** Refund compensating ledger postings.
- **Preconditions:** Payment refunded for $25.00 (2500 cents).
- **Input Data:** Inspect refund entries in `ledger_entries`.
- **Expected Result:** DEBIT `merchant_available_balance` (2500) and CREDIT `customer_funds_clearing` (2500).
- **Actual Result:** Verified.
- **Status:** PASS

#### `TC-LED-073`
- **Scenario:** Ledger summary API matches direct SQL calculation.
- **Preconditions:** Active merchant.
- **Input Data:** `GET /v1/merchants/{id}/ledger-summary`.
- **Expected Result:** API returned totals match direct SQL sums, `is_balanced=True`.
- **Actual Result:** Verified — API and SQL numbers match identically.
- **Status:** PASS

---

### 2.10 Concurrency Tests (`tests/integration/test_concurrency.py`)

#### `TC-CONC-080`
- **Scenario:** 10 parallel threads fire identical request with same Idempotency-Key.
- **Preconditions:** Multi-threaded client burst simulating aggressive retries.
- **Input Data:** 10 simultaneous POST requests sharing single key.
- **Expected Result:** Exactly ONE payment created in database. Responses are 201 or 409. Zero double-charges.
- **Actual Result:** Verified — exactly 1 payment created, zero duplicate debits.
- **Status:** PASS

#### `TC-CONC-081`
- **Scenario:** 6 parallel threads fire independent payments with unique keys.
- **Preconditions:** SQLite WAL write serialization under multi-threaded load.
- **Input Data:** 6 simultaneous POST requests with distinct keys.
- **Expected Result:** All serialize within 5s `busy_timeout`; all created payments have balanced ledger entries.
- **Actual Result:** Verified — all requests succeed with 201 Created and balanced ledgers.
- **Status:** PASS

#### `TC-CONC-082`
- **Scenario:** Concurrent double-capture race condition.
- **Preconditions:** Payment authorized for $80.00. 2 concurrent threads attempt capture with distinct keys.
- **Input Data:** 2 simultaneous capture requests.
- **Expected Result:** Exactly ONE succeeds (200 OK), other rejected with 409 Conflict. No double capture.
- **Actual Result:** Verified — status codes `[200, 409]`. Exactly 1 capture credit in database.
- **Status:** PASS

#### `TC-CONC-083`
- **Scenario:** Concurrent competing refunds race condition (preventing phantom overdraft).
- **Preconditions:** Payment captured for $50.00. 2 concurrent threads attempt to refund $40.00 each ($80.00 total).
- **Input Data:** 2 simultaneous refund requests.
- **Expected Result:** Exactly ONE refund succeeds (200 OK), competing refund fails with HTTP 422 (`refund_amount_exceeds_balance`). Available balance never negative.
- **Actual Result:** Verified — status codes `[200, 422]`. Total refunded is strictly 4000 cents.
- **Status:** PASS

#### `TC-CONC-084`
- **Scenario:** Synchronized 8-thread barrier race on identical idempotency key (Regression for DEF-002).
- **Preconditions:** Threading barrier synchronization forcing simultaneous entry into `acquire_or_get_cached`.
- **Input Data:** 8 parallel threads released at the exact same microsecond with identical key and payload.
- **Expected Result:** Zero unhandled IntegrityErrors. All status codes are 201 or 409. Exactly 1 payment and 1 ledger batch in database.
- **Actual Result:** Verified across 25 consecutive iterations with 100% pass rate.
- **Status:** PASS

---

## 3. Defect Log & Remediation History

### DEF-001: State Transition Exception Contract Schema Discrepancy
- **Component:** `app/core/exceptions.py` (`InvalidStateTransitionException`)
- **Severity / Priority:** Medium / High
- **Root Cause:** Error detail dictionary provided `attempted_status` instead of the OpenAPI contract standard `attempted_transition`.
- **Fix:** Added `attempted_transition` to exception details dictionary.
- **Verification:** `TC-TRANS-040` through `TC-TRANS-043` pass with zero schema validation errors.

### DEF-002: TOCTOU Race Condition in Concurrent Idempotency Key Lock Acquisition
- **Component:** `app/services/idempotency_service.py` (`acquire_or_get_cached`)
- **Severity / Priority:** High / Critical
- **Root Cause:** Time-of-Check to Time-of-Use (TOCTOU) race condition. When multiple threads concurrently queried `idempotency_keys` before any thread had flushed, all observed `record is None`. Multiple threads then attempted `INSERT`, causing secondary threads to fail with `sqlite3.IntegrityError: UNIQUE constraint failed: idempotency_keys.key`.
- **Fix:** Wrapped lock insertion in a `try ... except IntegrityError` block. When collision occurs, the losing thread catches `IntegrityError`, issues `db.rollback()`, and retrieves the winning transaction's record to return either cached completed response, 409 mismatch, or 409 in-progress lock.
- **Verification Evidence:** Executed 25 consecutive aggressive stress iterations of the concurrency suite (all 25 passed, 0 failures). Verified with dedicated regression test `TC-CONC-084`. Exactly one payment created in database.
