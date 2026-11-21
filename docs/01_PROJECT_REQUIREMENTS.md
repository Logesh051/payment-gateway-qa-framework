# Project Requirements

## Purpose
Build a small educational payment simulator and independent QA test suite.

## Problem
Payment systems should handle valid requests, reject invalid details, communicate declined payments clearly, avoid duplicate records when requests are repeated, and save transaction details accurately.

## Included
- Create a simulated payment through an API.
- Simulate successful and declined payment outcomes.
- Validate amount and dummy card number.
- Prevent a repeated request with the same idempotency key from creating another record.
- Retrieve a payment by ID.
- Verify stored payment details in SQLite.
- Run automated tests with Pytest and produce an HTML report.

## Excluded
Real banking integration, actual money transfers, merchant authentication, capture/cancellation/refunds, webhooks, accounting ledgers, concurrency stress tests, and load testing.

Use dummy card numbers only.
