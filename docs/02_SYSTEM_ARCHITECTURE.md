# 02 - System Architecture Document

**Document Version:** 1.1.0 (Post-Architecture Review Updates)  
**Status:** Approved Architecture Specification  
**Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, SQLite (WAL mode) / PostgreSQL-ready, Pytest  

---

## 1. High-Level Architecture & Separation of Concerns

The foundational design principle is the **strict architectural decoupling** of the **Payment Gateway (System Under Test - SUT)** from the **Independent Quality Engineering & Automated Testing Framework**.

```mermaid
flowchart TD
    subgraph SUT["System Under Test: Payment Gateway API (FastAPI)"]
        direction TB
        API["API Layer (Routers & Pydantic Schemas)"]
        MW["Idempotency Engine & Key Locker"]
        SVC["Service Layer (Payment, Refund, Webhook Services)"]
        SM["Domain State Machine & Invariant Guard"]
        DATA["Data Layer (SQLAlchemy 2.0 ORM)"]
        DB[("Application Database (SQLite WAL / SQL)")]
        
        API --> MW
        MW --> SVC
        SVC --> SM
        SVC --> DATA
        DATA --> DB
    end

    subgraph QA_FRAMEWORK["Independent QA Engineering & Test Framework"]
        direction TB
        TEST_RUNNER["Test Engine (Pytest Test Runner)"]
        HTTP_CLIENT["REST Client (HTTPX Sync / Async)"]
        DB_VERIFIER["Direct SQL Inspection & Double-Entry Ledger Verifier"]
        CONCURRENCY["Concurrency & Race Condition Harness"]
        WEBHOOK_SINK["Mock Webhook Listener & HMAC Validator"]
        PERF_RUNNER["JMeter Test Harness & Performance Monitor"]
        
        TEST_RUNNER --> HTTP_CLIENT
        TEST_RUNNER --> DB_VERIFIER
        TEST_RUNNER --> CONCURRENCY
        TEST_RUNNER --> WEBHOOK_SINK
        TEST_RUNNER --> PERF_RUNNER
    end

    HTTP_CLIENT -- "HTTP / REST API Calls" --> API
    CONCURRENCY -- "Parallel Burst Requests" --> API
    SVC -- "Asynchronous HTTP Callbacks" --> WEBHOOK_SINK
    DB_VERIFIER -- "Direct Read-Only DB Validation" --> DB
```

### Architectural Isolation Principles:
1. **Decoupled Codebases:** `app/` is completely unaware of `tests/`. No test helper code or test bypasses reside in application modules.
2. **Black-Box Testing Boundary:** Tests communicate via HTTP protocols (`ASGITransport` or live network socket) to exercise real request serialization, headers, and middleware.
3. **Dual-Layer Verification (API + Database):** An HTTP `200 OK` is validated against direct SQL assertions, verifying that the physical database rows, idempotency records, and double-entry ledger entries match the expected states.

---

## 2. Concurrency Architecture & SQLite WAL Single-Writer Limitation

### 2.1 The SQLite WAL Concurrency Model
In SQLite with Write-Ahead Logging (`PRAGMA journal_mode=WAL`):
- **Concurrent Readers:** Any number of reader connections can query the database concurrently without blocking or being blocked by writers.
- **Single-Writer Limitation:** Only **one write transaction** can hold the database write lock at any given microsecond. If two threads initiate write transactions concurrently, the second thread will encounter a lock conflict.

```mermaid
sequenceDiagram
    participant T1 as Thread 1 (Writer)
    participant DB as SQLite WAL Engine
    participant T2 as Thread 2 (Writer)
    
    T1->>DB: BEGIN IMMEDIATE (Acquires Write Lock)
    T2->>DB: BEGIN IMMEDIATE (Lock Contention)
    Note over DB,T2: T2 waits up to busy_timeout (5000ms)
    T1->>DB: UPDATE payments & INSERT ledger_entries
    T1->>DB: COMMIT (Releases Write Lock)
    DB-->>T2: Write Lock Acquired
    T2->>DB: UPDATE payments & INSERT ledger_entries
    T2->>DB: COMMIT (Releases Write Lock)
```

### 2.2 How Concurrency Tests Handle Database Locking
1. **Engine Timeout (`busy_timeout=5000`):** Connections are initialized with a 5000ms busy timeout. When concurrent writes occur, SQLite automatically retries internally for up to 5 seconds before giving up.
2. **Immediate Transactions (`BEGIN IMMEDIATE`):** In SQLAlchemy, mutating sessions issue `BEGIN IMMEDIATE` at the start of the transaction. This prevents "lock upgrade deadlocks" (where two connections read concurrently and both try to upgrade to a write lock simultaneously).
3. **Controlled Conflict Responses:** If contention ever exceeds the timeout threshold under extreme burst conditions, the API translates `sqlite3.OperationalError: database is locked` into a clean **`HTTP 503 Service Unavailable`** or **`HTTP 409 Conflict`** rather than crashing.
4. **Production Contrast for Technical Interviews:** In a production distributed gateway, a multi-writer database like PostgreSQL or CockroachDB is used with row-level locks (`SELECT ... FOR UPDATE NOWAIT`) and distributed Redis locks. For this local simulation, SQLite WAL with `BEGIN IMMEDIATE` provides deterministic ACID guarantees without external infrastructure.

---

## 3. Precise Idempotency Specification

```mermaid
flowchart TD
    REQ["Incoming POST Request with Idempotency-Key"] --> HASH["Compute SHA-256 Hash of Request Body"]
    HASH --> LOOKUP{"Lookup Key in idempotency_keys Table"}
    
    LOOKUP -- "Key Does NOT Exist" --> INSERT["Acquire Lock: INSERT status='IN_PROGRESS'"]
    INSERT --> EXEC["Execute Transaction Atomically"]
    EXEC --> SAVE["UPDATE key status='COMPLETED', save status_code & response_body"]
    SAVE --> RET["Return Response to Client"]
    
    LOOKUP -- "Key Exists & status='IN_PROGRESS'" --> CONFLICT_IN_FLIGHT["Return HTTP 409 Conflict (concurrent_mutation_in_progress)"]
    
    LOOKUP -- "Key Exists & status='COMPLETED'" --> CHECK_HASH{"stored_hash == current_hash?"}
    CHECK_HASH -- "Yes (Same Payload)" --> REPLAY["Return Cached Original Response (HTTP 200/201)"]
    CHECK_HASH -- "No (Different Payload)" --> CONFLICT_MISMATCH["Return HTTP 409 Conflict (idempotency_payload_mismatch)"]
```

1. **Same Key + Same Payload:** Returns original transaction result immediately from cache. Zero duplicate charges, zero new ledger entries.
2. **Same Key + Different Payload:** Rejects with **`HTTP 409 Conflict`** and error code `idempotency_payload_mismatch`. Original transaction remains untouched.
3. **Different Keys:** Treated as completely independent transactions.

---

## 4. Relational Database Schema & Genuine Double-Entry Ledger

All monetary values are stored as **64-bit integers (`BIGINT`)** representing minor units (cents).

```mermaid
erDiagram
    MERCHANTS ||--o{ PAYMENTS : owns
    PAYMENTS ||--o{ REFUNDS : has
    PAYMENTS ||--o{ WEBHOOK_EVENTS : emits
    PAYMENTS ||--o| IDEMPOTENCY_KEYS : maps
    PAYMENTS ||--o{ LEDGER_ENTRIES : records

    MERCHANTS {
        string id PK
        string name
        string api_key_hash
        string webhook_secret
        boolean is_active
        datetime created_at
    }

    PAYMENTS {
        string id PK
        string merchant_id FK
        bigint amount_cents
        string currency
        string status
        boolean captured
        string card_last4
        string card_brand
        string failure_code
        string failure_message
        datetime created_at
        datetime updated_at
    }

    IDEMPOTENCY_KEYS {
        string key PK
        string merchant_id FK
        string request_hash
        string payment_id FK
        string status
        int response_status_code
        string response_body
        datetime locked_until
        datetime created_at
    }

    REFUNDS {
        string id PK
        string payment_id FK
        string merchant_id FK
        bigint amount_cents
        string status
        string reason
        datetime created_at
    }

    LEDGER_ENTRIES {
        string id PK
        string batch_id
        string payment_id FK
        string merchant_id FK
        string entry_type "DEBIT or CREDIT"
        string account_name "customer_funds_clearing / merchant_available_balance"
        bigint amount_cents
        string currency
        string description
        datetime created_at
    }

    WEBHOOK_EVENTS {
        string id PK
        string payment_id FK
        string merchant_id FK
        string event_type
        string payload_json
        string status
        int delivery_attempts
        datetime created_at
    }
```

### 4.1 Genuine Double-Entry Ledger Invariant
Every transaction creates balanced entries in `ledger_entries` sharing a unique `batch_id`:
$$\sum_{\text{batch}} \text{Amount}_{\text{DEBIT}} = \sum_{\text{batch}} \text{Amount}_{\text{CREDIT}}$$

When \$50.00 is captured:
- Entry 1 (Batch `bat_01`): `entry_type = DEBIT`, `account_name = customer_funds_clearing`, `amount_cents = 5000`
- Entry 2 (Batch `bat_01`): `entry_type = CREDIT`, `account_name = merchant_available_balance`, `amount_cents = 5000`

When \$20.00 is refunded:
- Entry 1 (Batch `bat_02`): `entry_type = DEBIT`, `account_name = merchant_available_balance`, `amount_cents = 2000`
- Entry 2 (Batch `bat_02`): `entry_type = CREDIT`, `account_name = customer_funds_clearing`, `amount_cents = 2000`

---

## 5. Transactional Consistency Guarantee
All mutations across the 4 core entities (`payments`, `idempotency_keys`, `ledger_entries`, `webhook_events`) are bound to a single database transaction:
```python
try:
    # 1. Update Payment record
    # 2. Record balanced double-entry ledger entries
    # 3. Stage signed webhook event
    # 4. Finalize idempotency key to COMPLETED with cached response
    db.commit()
except Exception:
    db.rollback()
    raise
```
This guarantees zero orphaned records and zero ledger imbalances.
