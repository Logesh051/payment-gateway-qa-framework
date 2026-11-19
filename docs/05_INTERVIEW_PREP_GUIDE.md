# 05 - Technical Interview Guide & Defense Playbook

**Target Audience:** Students & Software Quality Engineers interviewing for FinTech, Systems, and QA Engineering roles.  
**Topic:** Payment Gateway Reliability & Quality Engineering Framework  
**Document Version:** 1.1.0  

---

## 1. High-Frequency Interview Questions & Senior-Level Answers

### Q1: "Why did you build an independent QA framework instead of just writing basic unit tests inside the payment application?"
> **Senior QA Answer:**  
> "A common anti-pattern in fintech engineering is testing an application solely through internal method calls. When you invoke internal Python service functions directly in your tests, you bypass HTTP serialization, deserialization, network timeouts, middleware order, header parsing, and database connection pooling.  
> We designed an **independent test framework** that treats the payment gateway as a decoupled SUT (System Under Test). The framework fires real HTTP requests against public API contracts and independently queries the underlying SQL database to verify that financial ledger rows, state changes, and idempotency records match expected mathematical invariants. This guarantees zero discrepancies between what the API reports and what is actually stored."

---

### Q2: "How does Idempotency work in your gateway, and how did you test it?"
> **Senior QA Answer:**  
> "Idempotency ensures that performing an operation once has the exact same effect as performing it multiple times. In payment gateways, network drops often occur *after* the bank has charged the customer but *before* the merchant receives the `200 OK`. If the merchant retries, the customer could be double-charged.  
> 1. **Mechanism:** Every mutating request (`POST`) requires an `Idempotency-Key` header and a SHA-256 hash of the request payload. In our database, an atomic entry is locked in `IN_PROGRESS` state. If a request finishes, the status becomes `COMPLETED` and the exact response payload is stored.  
> 2. **Precise Rules:**  
>    - **Same Key + Same Payload:** The gateway immediately returns the cached original transaction result. No duplicate charges or ledger entries occur.  
>    - **Same Key + Different Payload:** Rejects immediately with **`HTTP 409 Conflict`** (`idempotency_payload_mismatch`). The original record is untouched.  
>    - **Different Keys:** Treated as completely independent transactions.  
> 3. **Verification in QA:**  
>    - We test immediate replay, payload modification rejection, and concurrent bursts (10 threads firing simultaneously) to guarantee zero double-charges."

---

### Q3: "What is SQLite WAL mode, and what is its single-writer limitation during concurrency tests?"
> **Senior QA Answer:**  
> "In SQLite WAL (Write-Ahead Logging) mode, readers do not block writers and writers do not block readers. However, SQLite has a fundamental architectural constraint: it is **strictly single-writer**. Only one transaction can hold the database write lock at any instant.  
> If multiple threads issue write operations simultaneously:  
> 1. We configure a 5-second `busy_timeout` (`PRAGMA busy_timeout=5000`) so SQLite automatically retries lock acquisition during concurrent bursts.  
> 2. We use `BEGIN IMMEDIATE` transactions in SQLAlchemy to acquire the write lock at the start of the transaction rather than escalating mid-flight, preventing lock-upgrade deadlocks.  
> 3. In production, we explain that multi-node gateways transition to PostgreSQL with row-level locking (`SELECT ... FOR UPDATE`), but for our local self-contained test environment, SQLite WAL provides full ACID transaction isolation with zero external daemons."

---

### Q4: "How does your system enforce a genuine double-entry ledger?"
> **Senior QA Answer:**  
> "Single-column balance tracking (e.g. `merchant.balance += 100`) is vulnerable to silent balance corruption and makes auditing impossible. We implemented a **genuine double-entry ledger**:  
> Every financial mutation creates a balanced batch in `ledger_entries` containing at least one `DEBIT` and one `CREDIT` record.  
> For example, capturing \$25.00 creates:  
> - DEBIT `customer_funds_clearing` \$25.00  
> - CREDIT `merchant_available_balance` \$25.00  
> A refund reverses this: DEBIT `merchant_available_balance`, CREDIT `customer_funds_clearing`.  
> Our test framework executes direct SQL assertions verifying that for every transaction batch, $\sum \text{Debits} = \sum \text{Credits}$, and that the merchant's available balance matches the ledger sum exactly."

---

### Q5: "How do you ensure transactional consistency across payments, idempotency keys, and webhooks?"
> **Senior QA Answer:**  
> "We bind all 4 mutations—the payment status update, the idempotency record finalization, the double-entry ledger entries, and the webhook event creation—within a **single atomic database transaction**.  
> If an error occurs anywhere (for example, if a webhook payload fails serialization or a database constraint is violated), the entire transaction rolls back (`ROLLBACK`). This guarantees that you never have a payment that succeeded while its idempotency key remains locked in `IN_PROGRESS`, or a ledger entry recorded without a corresponding payment."

---

## 2. Component-by-Component Defense Guide

| Component | What it does | How to explain it in an interview |
| :--- | :--- | :--- |
| **`app/core/state_machine.py`** | Enforces valid payment lifecycle transitions. | "Acts as a pure domain firewall. Rejects illegal operations (e.g., capturing a cancelled authorization) with HTTP 409 Conflict." |
| **`app/services/idempotency_service.py`** | Manages key locking, payload hashing, and response replay. | "Protects against network retries and double clicks. Detects payload mismatches and in-flight race conditions." |
| **`app/db/models.py`** | Defines normalized relational models. | "Separates payments from double-entry ledger entries, idempotency keys, and webhook events for strict ACID compliance." |
| **`app/services/payment_service.py`** | Orchestrates payment lifecycle and banking simulation. | "Coordinates card checks, state transitions, ledger postings, and webhook creation inside a single atomic transaction." |
| **`app/services/webhook_service.py`** | Computes HMAC-SHA256 signatures and stages webhook events. | "Guarantees data integrity and authenticity using timing-safe signature verification." |
