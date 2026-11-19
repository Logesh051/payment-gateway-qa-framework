# Payment Gateway Reliability & Quality Engineering Framework

An industry-oriented Software Quality Engineering (QE) and automated testing framework built for simulating and validating financial transaction reliability, idempotency, state transitions, ledger integrity, and concurrency safety.

---

## 📌 Project Overview

In fintech and payment infrastructure, testing is not merely checking if an endpoint returns `200 OK`. Quality Engineers must guarantee:
- **Zero Double-Charging:** Enforced via atomic database-backed idempotency tokens.
- **Strict State Transitions:** Regulated by a deterministic finite state machine (invalid transitions rejected with `HTTP 409 Conflict`).
- **Genuine Double-Entry Ledger Balancing:** Every transaction has mathematically verifiable debit/credit balance consistency ($\sum \text{Debits} = \sum \text{Credits}$).
- **Concurrency & Race Condition Safety:** Resilient under multi-threaded parallel burst traffic, with SQLite WAL busy timeout handling.
- **Defensive Error Handling:** Deterministic bank decline codes (`402`, `403`, `504`) and amount boundary checks.
- **Independent QA Automation Framework:** Decoupled Pytest suite using read-only database assertions and black-box HTTP testing.

---

## 🏛️ Clean Architecture & Separation of Concerns

```
payment-gateway-qa-framework/
├── app/                                   # System Under Test (SUT) - Decoupled Payment API
│   ├── api/
│   │   ├── dependencies.py                # Auth & Idempotency key extraction
│   │   ├── routes.py                      # REST endpoints for payment, capture, cancel, refund, ledger
│   │   └── schemas.py                     # Pydantic v2 schemas with integer minor units (cents)
│   ├── core/
│   │   ├── config.py                      # SQLite WAL settings, monetary bounds, currencies
│   │   ├── exceptions.py                  # Structured domain error envelopes
│   │   └── state_machine.py               # Explicit state transition map & validator
│   ├── db/
│   │   ├── models.py                      # Merchants, Payments, Idempotency, Refunds, Ledger, Webhooks
│   │   └── session.py                     # Engine with WAL mode, busy_timeout=5000, foreign keys
│   └── services/
│       ├── idempotency_service.py         # SHA-256 payload hashing, atomic lock & replay
│       ├── payment_service.py             # Orchestration, double-entry batching, banking simulation
│       └── webhook_service.py             # HMAC-SHA256 signing & timing-safe verification
│
├── tests/                                 # Independent Quality Engineering Test Framework
│   ├── conftest.py                        # Isolated test DB, read-only session & HTTP fixtures
│   ├── factories.py                       # Test data factories (cards, amounts, payloads, keys)
│   ├── schemas/
│   │   └── payment_schemas.py             # JSON schemas for contract validation
│   ├── unit/
│   │   └── test_state_transitions_unit.py # Unit tests for pure state machine domain logic
│   ├── api/
│   │   ├── test_health_and_auth.py        # Health, API key authentication, 400/401/404 handling
│   │   ├── test_payment_lifecycle.py      # End-to-end payment creation, auth, capture, refund
│   │   ├── test_functional_negative.py    # Negative boundary values, declines, missing fields
│   │   ├── test_idempotency.py            # Same key replay, payload mismatch 409, distinct keys
│   │   ├── test_state_transitions_api.py  # Invalid transitions rejected with HTTP 409 Conflict
│   │   └── test_webhooks.py               # HMAC-SHA256 verification, replay window, tampering
│   └── integration/
│       ├── test_db_persistence.py         # Direct read-only SQL persistence assertions
│       ├── test_double_entry_ledger.py    # Batch balance invariants (Sum Debits == Sum Credits)
│       └── test_concurrency.py            # Multi-threaded bursts, race conditions, double capture
│
├── docs/                                  # Specifications & Architectural Documentation
│   ├── 01_PROJECT_REQUIREMENTS.md
│   ├── 02_SYSTEM_ARCHITECTURE.md
│   ├── 03_TEST_STRATEGY.md
│   ├── 04_API_CONTRACT.md
│   ├── 05_INTERVIEW_PREP_GUIDE.md
│   └── 06_TEST_CASE_SPECIFICATION.md      # Complete RTM & test case inventory
│
├── scripts/
│   └── verify_phase2.py                   # Automated component verification script
│
├── pytest.ini                             # Pytest configuration, markers, and asyncio mode
├── report.html                            # Standalone self-contained HTML test execution report
├── requirements.txt
├── .gitignore
└── README.md
```

---

## ⚙️ Environment & Local Setup

- **Operating System:** Windows 11
- **Language / Runtime:** Python 3.12 (via `py -3.12`)
- **Database:** SQLite with Write-Ahead Logging (`WAL` mode) and 5000ms busy timeout.
- **Safety Policy:** Strictly local educational simulation. Real card numbers, production credentials, and live banking rails are strictly forbidden.

### Setup Instructions

1. **Activate Virtual Environment:**
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
2. **Install Dependencies:**
   ```powershell
   pip install -r requirements.txt
   ```
3. **Run the Independent QA Automated Test Suite:**
   ```powershell
   # Run all 66 automated tests with HTML report and coverage
   pytest --html=report.html --self-contained-html --cov=app --cov-report=term-missing
   ```
4. **Run Live Payment Gateway Server:**
   ```powershell
   uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```
   Interactive OpenAPI Documentation: `http://127.0.0.1:8000/docs`

---

## 🚦 Roadmap & Implementation Status

- [x] **Phase 1: Architecture, Requirements, and Test Strategy** (Approved & Updated)
- [x] **Phase 2: Core Simulation API & Domain Engine Implementation** (Completed & Verified)
- [x] **Phase 3: Independent Test Automation Framework & Pytest Test Suites** (Completed: 66/66 Passed, 94% Coverage)
- [ ] **Phase 4: Concurrency Stress, SQL Ledger Balancing & Deep Edge Case Suites**
- [ ] **Phase 5: Performance Testing (JMeter / Locust) & CI/CD Pipeline (GitHub Actions)**
- [ ] **Phase 6: Final Verification, Test Evidence Reports & Technical Interview Defense**
