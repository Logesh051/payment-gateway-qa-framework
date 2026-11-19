# 08 - Performance & Load Testing Results

**Document Version:** 2.0.0 (Progressive Multi-User Load Testing Report)  
**Phase:** Phase 4 – Performance and Load Testing  
**Date:** 2026-11-19  
**System Under Test (SUT):** Payment Gateway Simulator (FastAPI, SQLite WAL Mode, Integer Cents Ledger)  
**Host Environment:** Windows 11, Python 3.12.10, Uvicorn ASGI Server  
**Test Engine:** Locust 2.47.0 (Headless execution)  

---

## 1. Baseline Figure Reconciliation & Throughput Analysis

### 1.1 Baseline Discrepancy Reconciliation (Tier 1)
In the Tier 1 baseline test, the raw Locust statistics reported:
- **Total Requests Completed:** `339 requests`
- **Configured Test Run Time:** `30.00 seconds` (`--run-time 30s`)
- **Locust Reported Throughput:** `11.57688 req/s` ($\approx 11.58\text{ req/s}$)

#### Explanation of Wall-Clock vs. Measured Window
A naive calculation of $339 / 30.00\text{s}$ yields $11.30\text{ req/s}$. The difference arises from Locust's standard measurement window:
1. **Ramp-Up & Client Connection Initialization:** Locust initializes the user process, sets up the HTTP client session, and dispatches the initial handshake. The first request completed at $t \approx 0.72\text{s}$.
2. **Active Measurement Duration:** Locust measures aggregate throughput strictly between the timestamp of the first request completion and the last request completion:
   $$\Delta t_{\text{active}} = \frac{339 \text{ requests}}{11.57688264 \text{ req/s}} = 29.2825 \text{ seconds}$$
3. **Reconciliation Summary:**
   - **Nominal Wall-Clock Duration:** $30.00\text{ seconds}$ $\implies 11.30\text{ req/s}$
   - **Active Window Duration:** $29.28\text{ seconds}$ $\implies 11.58\text{ req/s}$

Both figures are mathematically consistent. Throughout this report, both active window throughput (Locust standard) and exact request counts are reported to ensure complete transparency.

---

## 2. Multi-Tier Progressive Load Testing Comparison

Testing was executed across four controlled tiers with zero changes to application code, identical database configurations (`PRAGMA busy_timeout = 5000`), and separate raw CSV outputs captured for each tier.

### 2.1 Cross-Tier Executive Comparison Table

| Metric | Tier 1 (Baseline) | Tier 2 (Light Load) | Tier 3 (Moderate Load) | Tier 4 (Stress Contention) |
| :--- | :---: | :---: | :---: | :---: |
| **Virtual Users (Concurrency)** | **1 user** | **5 users** | **10 users** | **25 users** |
| **Duration (Wall-Clock)** | 30 seconds | 30 seconds | 45 seconds | 60 seconds |
| **Ramp-Up Rate** | Immediate (1/s) | 1 user/sec | 2 users/sec | 5 users/sec |
| **Total Requests Executed** | **339** | **1,597** | **4,699** | **8,943** |
| **Throughput (Active RPS)** | **11.58 req/s** | **54.72 req/s** | **106.21 req/s** | **150.93 req/s** |
| **Successful Requests** | 339 (100.0%) | 1,597 (100.0%) | 4,699 (100.0%) | 8,938 (99.94%) |
| **Failed Requests** | **0 (0.00%)** | **0 (0.00%)** | **0 (0.00%)** | **5 (0.056%)** |
| **Unhandled Server Errors (500)** | **0 (0.00%)** | **0 (0.00%)** | **0 (0.00%)** | **0 (0.00%)** |
| **Controlled 503 (`database_busy`)**| **0** | **0** | **0** | **5** |
| **Average Response Time** | **9.56 ms** | **9.43 ms** | **16.14 ms** | **87.40 ms** |
| **Median Response Time (p50)** | **8.00 ms** | **7.00 ms** | **8.00 ms** | **12.00 ms** |
| **95th Percentile Latency (p95)**| **17.00 ms** | **27.00 ms** | **55.00 ms** | **230.00 ms** |
| **99th Percentile Latency (p99)**| **18.00 ms** | **48.00 ms** | **100.00 ms** | **2,000.00 ms** |
| **Max Response Time** | **19.74 ms** | **74.09 ms** | **331.75 ms** | **5,538.64 ms** |
| **Cold Write Avg Latency** | 12.35 ms | 11.60 ms | 20.17 ms | 79.72 ms |
| **Cached Replay Avg Latency** | **3.66 ms** | **3.57 ms** | **5.10 ms** | **7.68 ms** |
| **Idempotency Speedup Factor** | **3.37x** | **3.25x** | **3.95x** | **10.38x** |

---

## 3. Tier-by-Tier Granular Breakdown

### 3.1 Tier 1: Baseline (1 User, 30s)
- **Execution Command:** `locust -f tests/performance/locustfile.py --headless -u 1 -r 1 -t 30s --host http://127.0.0.1:8000 --csv=tests/performance/results/baseline_1u`
- **Total Requests:** 339 | **Failures:** 0 | **Active RPS:** 11.58

| Endpoint / Scenario | Requests | Failures | Avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Max (ms) | RPS |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `GET /health` | 1 | 0 | 8.89 | 9.0 | 9.0 | 9.0 | 8.89 | 0.03 |
| `POST /v1/payments` [Direct Create & Capture] | 54 | 0 | 12.72 | 14.0 | 18.0 | 18.0 | 18.00 | 1.84 |
| `POST /v1/payments` [Distinct Key Burst] | 52 | 0 | 9.88 | 7.0 | 18.0 | 18.0 | 18.23 | 1.78 |
| `POST /v1/payments` [Expected 400 - Bad Currency] | 7 | 0 | 5.95 | 7.0 | 8.0 | 8.0 | 7.92 | 0.24 |
| `POST /v1/payments` [Expected 400 - Below Min] | 6 | 0 | 6.63 | 7.0 | 8.0 | 8.0 | 8.38 | 0.20 |
| `POST /v1/payments` [Expected 402 - Bank Decline] | 7 | 0 | 12.56 | 13.0 | 17.0 | 17.0 | 16.92 | 0.24 |
| `POST /v1/payments` [Idempotency 1st Attempt] | 28 | 0 | 12.35 | 14.0 | 17.0 | 18.0 | 18.33 | 0.96 |
| `POST /v1/payments` [Idempotency 2nd Replay - Cached] | 28 | 0 | 3.66 | 3.0 | 6.0 | 13.0 | 13.14 | 0.96 |
| `POST /v1/payments` [Lifecycle Auth] | 24 | 0 | 13.62 | 14.0 | 18.0 | 20.0 | 19.74 | 0.82 |
| `POST /v1/payments` [Pre-Auth] | 42 | 0 | 12.58 | 13.0 | 18.0 | 19.0 | 18.61 | 1.43 |
| `POST /v1/payments/{id}/capture` | 42 | 0 | 6.08 | 6.0 | 8.0 | 11.0 | 11.01 | 1.43 |
| `POST /v1/payments/{id}/capture` [Lifecycle] | 24 | 0 | 6.48 | 6.0 | 9.0 | 10.0 | 9.64 | 0.82 |
| `POST /v1/payments/{id}/refund` [Lifecycle] | 24 | 0 | 6.16 | 6.0 | 9.0 | 9.0 | 8.85 | 0.82 |

---

### 3.2 Tier 2: Light Load (5 Users, 30s, Ramp-up 1/s)
- **Execution Command:** `locust -f tests/performance/locustfile.py --headless -u 5 -r 1 -t 30s --host http://127.0.0.1:8000 --csv=tests/performance/results/load_5u`
- **Total Requests:** 1,597 | **Failures:** 0 (0.00%) | **Active RPS:** 54.72

| Endpoint / Scenario | Requests | Failures | Avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Max (ms) | RPS |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `GET /health` | 5 | 0 | 6.62 | 4.0 | 16.0 | 16.0 | 15.58 | 0.17 |
| `POST /v1/payments` [Direct Create & Capture] | 277 | 0 | 11.86 | 8.0 | 34.0 | 50.0 | 52.76 | 9.49 |
| `POST /v1/payments` [Distinct Key Burst] | 174 | 0 | 8.37 | 6.0 | 19.0 | 44.0 | 46.35 | 5.96 |
| `POST /v1/payments` [Expected 400 - Bad Currency] | 43 | 0 | 8.73 | 5.0 | 30.0 | 49.0 | 48.62 | 1.47 |
| `POST /v1/payments` [Expected 400 - Below Min] | 29 | 0 | 6.58 | 4.0 | 20.0 | 22.0 | 21.94 | 0.99 |
| `POST /v1/payments` [Expected 402 - Bank Decline] | 30 | 0 | 10.15 | 7.0 | 32.0 | 35.0 | 34.70 | 1.03 |
| `POST /v1/payments` [Idempotency 1st Attempt] | 136 | 0 | 11.60 | 8.0 | 34.0 | 53.0 | 69.25 | 4.66 |
| `POST /v1/payments` [Idempotency 2nd Replay - Cached] | 136 | 0 | 3.57 | 3.0 | 7.0 | 10.0 | 11.28 | 4.66 |
| `POST /v1/payments` [Lifecycle Auth] | 131 | 0 | 11.82 | 8.0 | 35.0 | 49.0 | 63.68 | 4.49 |
| `POST /v1/payments` [Pre-Auth] | 187 | 0 | 11.80 | 8.0 | 35.0 | 51.0 | 53.03 | 6.41 |
| `POST /v1/payments/{id}/capture` | 187 | 0 | 8.70 | 6.0 | 26.0 | 42.0 | 74.09 | 6.41 |
| `POST /v1/payments/{id}/capture` [Lifecycle] | 131 | 0 | 7.08 | 6.0 | 12.0 | 35.0 | 40.20 | 4.49 |
| `POST /v1/payments/{id}/refund` [Lifecycle] | 131 | 0 | 7.95 | 7.0 | 13.0 | 27.0 | 47.07 | 4.49 |

---

### 3.3 Tier 3: Moderate Load (10 Users, 45s, Ramp-up 2/s)
- **Execution Command:** `locust -f tests/performance/locustfile.py --headless -u 10 -r 2 -t 45s --host http://127.0.0.1:8000 --csv=tests/performance/results/load_10u`
- **Total Requests:** 4,699 | **Failures:** 0 (0.00%) | **Active RPS:** 106.21

| Endpoint / Scenario | Requests | Failures | Avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Max (ms) | RPS |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `GET /health` | 10 | 0 | 9.69 | 5.0 | 29.0 | 29.0 | 29.10 | 0.23 |
| `POST /v1/payments` [Direct Create & Capture] | 804 | 0 | 19.47 | 10.0 | 65.0 | 110.0 | 331.75 | 18.17 |
| `POST /v1/payments` [Distinct Key Burst] | 552 | 0 | 15.03 | 9.0 | 53.0 | 93.0 | 124.41 | 12.48 |
| `POST /v1/payments` [Expected 400 - Bad Currency] | 94 | 0 | 17.09 | 8.0 | 64.0 | 94.0 | 93.50 | 2.12 |
| `POST /v1/payments` [Expected 400 - Below Min] | 94 | 0 | 20.81 | 11.0 | 70.0 | 110.0 | 114.71 | 2.12 |
| `POST /v1/payments` [Expected 402 - Bank Decline] | 82 | 0 | 16.77 | 9.0 | 59.0 | 110.0 | 112.89 | 1.85 |
| `POST /v1/payments` [Idempotency 1st Attempt] | 423 | 0 | 20.17 | 11.0 | 66.0 | 110.0 | 161.04 | 9.56 |
| `POST /v1/payments` [Idempotency 2nd Replay - Cached] | 423 | 0 | **5.10** | **4.0** | **10.0** | **27.0** | **35.01** | 9.56 |
| `POST /v1/payments` [Lifecycle Auth] | 378 | 0 | 18.50 | 10.0 | 57.0 | 99.0 | 185.34 | 8.54 |
| `POST /v1/payments` [Pre-Auth] | 542 | 0 | 18.95 | 10.0 | 58.0 | 100.0 | 177.26 | 12.25 |
| `POST /v1/payments/{id}/capture` | 541 | 0 | 14.28 | 7.0 | 52.0 | 110.0 | 166.53 | 12.23 |
| `POST /v1/payments/{id}/capture` [Lifecycle] | 378 | 0 | 15.06 | 7.0 | 54.0 | 120.0 | 190.73 | 8.54 |
| `POST /v1/payments/{id}/refund` [Lifecycle] | 378 | 0 | 14.49 | 8.0 | 54.0 | 120.0 | 149.47 | 8.54 |

---

### 3.4 Tier 4: Stress / Saturation Load (25 Users, 60s, Ramp-up 5/s)
- **Execution Command:** `locust -f tests/performance/locustfile.py --headless -u 25 -r 5 -t 60s --host http://127.0.0.1:8000 --csv=tests/performance/results/stress_25u`
- **Total Requests:** 8,943 | **Failures:** 5 (0.056%) | **Active RPS:** 150.93

| Endpoint / Scenario | Requests | Failures | Avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Max (ms) | RPS |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `GET /health` | 25 | 0 | 14.91 | 15.0 | 28.0 | 29.0 | 28.52 | 0.42 |
| `POST /v1/payments` [Direct Create & Capture] | 1,508 | 1 | 111.65 | 15.0 | 460.0 | 2,400.0 | 5,538.25 | 25.45 |
| `POST /v1/payments` [Distinct Key Burst] | 1,005 | 1 | 86.83 | 12.0 | 210.0 | 1,900.0 | 5,519.50 | 16.96 |
| `POST /v1/payments` [Expected 400 - Bad Currency] | 153 | 0 | 123.66 | 15.0 | 560.0 | 3,300.0 | 3,487.85 | 2.58 |
| `POST /v1/payments` [Expected 400 - Below Min] | 177 | 0 | 59.10 | 10.0 | 320.0 | 990.0 | 1,625.61 | 2.99 |
| `POST /v1/payments` [Expected 402 - Bank Decline] | 171 | 0 | 90.81 | 14.0 | 270.0 | 2,400.0 | 3,071.33 | 2.89 |
| `POST /v1/payments` [Idempotency 1st Attempt] | 756 | 0 | 79.72 | 15.0 | 210.0 | 1,700.0 | 3,515.08 | 12.76 |
| `POST /v1/payments` [Idempotency 2nd Replay - Cached] | 756 | 0 | **7.68** | **6.0** | **20.0** | **32.0** | **64.39** | 12.76 |
| `POST /v1/payments` [Lifecycle Auth] | 801 | 1 | 120.31 | 15.0 | 440.0 | 2,700.0 | 5,508.82 | 13.52 |
| `POST /v1/payments` [Pre-Auth] | 998 | 1 | 103.71 | 14.0 | 440.0 | 2,000.0 | 5,538.64 | 16.84 |
| `POST /v1/payments/{id}/capture` | 994 | 0 | 102.08 | 11.0 | 290.0 | 2,200.0 | 4,254.86 | 16.78 |
| `POST /v1/payments/{id}/capture` [Lifecycle] | 800 | 0 | 64.25 | 11.0 | 180.0 | 1,300.0 | 5,002.03 | 13.50 |
| `POST /v1/payments/{id}/refund` [Lifecycle] | 799 | 1 | 77.43 | 11.0 | 200.0 | 2,300.0 | 5,523.15 | 13.48 |

---

## 4. Architectural Analysis: Where Performance Degrades

### 4.1 Throughput and Scaling Curves
The system demonstrates three distinct scaling regimes across the four tiers:

```
RPS
 160 |                                                  * (150.93 RPS @ 25u - Lock Saturated)
 140 |
 120 |                                    * (106.21 RPS @ 10u)
 100 |
  80 |
  60 |                      * (54.72 RPS @ 5u)
  40 |
  20 |        * (11.58 RPS @ 1u)
   0 +-------------------------------------------------------
             1u            5u             10u            25u
```

1. **Sub-linear to Linear Scaling (1 to 5 Users):** Throughput scaled from $11.58\text{ req/s}$ to $54.72\text{ req/s}$ (a $4.72\times$ throughput increase for a $5\times$ increase in users). Median latency improved slightly from 8.0ms to 7.0ms due to thread pool warm-up. SQLite lock contention was virtually undetectable ($p99 < 50\text{ms}$).
2. **Knee of the Latency Curve (10 Users):** Throughput doubled to $106.21\text{ req/s}$. The median response time remained stable at 8.0ms, but tail latency ($p99$) jumped from 48ms to 100ms. Writers began forming short lock queues behind concurrent commits.
3. **Write Contention Saturation Boundary (25 Users):** Throughput leveled off at $150.93\text{ req/s}$ (only a $1.42\times$ throughput increase for a $2.5\times$ user increase). While median response time held at 12ms, tail latency exploded: $p95 = 230\text{ms}$, $p99 = 2,000\text{ms}$, and maximum latency reached $5,538\text{ms}$.

### 4.2 SQLite WAL Single-Writer Bottleneck Mechanics
Under SQLite's Write-Ahead Logging (`WAL`) architecture:
- Multiple concurrent threads can read simultaneously without blocking.
- Mutating transactions (`BEGIN IMMEDIATE ... COMMIT`) require an exclusive lock on the WAL writer log.
- When 25 concurrent virtual users issue 150+ mutating requests per second, each write transaction holds the exclusive lock for 2–10ms.
- As the queue of waiting writers backs up, individual wait times accumulate exponentially.
- At 25 users, exactly 5 requests exceeded the 5,000ms `PRAGMA busy_timeout`.
- **System Resilience:** Rather than crashing or returning an unhandled HTTP 500 error, the application intercepted `OperationalError: database is locked` and returned a structured `HTTP 503 database_busy` with `{"retriable": true}`. The transactions were rolled back cleanly with zero orphaned rows.

### 4.3 Empirical Proof: The Power of Idempotency Caching Under Contention
The comparison between cold initial payments and cached idempotency replays provides conclusive proof of the architectural value of idempotency caching:

```mermaid
flowchart TD
    subgraph Tier_4_Contention ["Tier 4 (25 Users Under Contention)"]
        Cold["Cold Write Payment Attempt<br>Avg: 79.72 ms | Max: 3,515 ms<br>(Blocked in SQLite Writer Lock Queue)"]
        Cached["Cached Idempotency Replay<br>Avg: 7.68 ms | Max: 64 ms<br>(Fast Read Query - Bypasses Writer Lock)"]
    end
```

- In Tier 1 (1 user), cached replays were **3.37x faster** than cold writes (3.66ms vs 12.35ms).
- In Tier 4 (25 users), cold writes slowed down to an average of **79.72ms** (with tail latencies up to 3,515ms) due to writer queueing.
- However, cached replays took only **7.68ms** (p99 was 32ms, max 64ms).
- **Under contention, cached idempotency replays were 10.38x faster than cold writes.** Because cached requests only perform read lookups on the indexed idempotency table and do not require writer locks or ledger modifications, they completely bypass the write serialization bottleneck.

---

## 5. Continuous Post-Tier Database Integrity Audit

After each load tier, the independent audit script [verify_performance_integrity.py](file:///c:/Users/Logesh/Documents/payment-gateway-qa-framework/scripts/verify_performance_integrity.py) was executed to verify all 6 required data invariants.

### 5.1 Cumulative Database State Progression

| Audit Checkpoint | Total Payments | Completed Idem Keys | Lingering In-Progress Keys | Duplicate Keys | Ledger Entries | Total Debits ($) | Total Credits ($) | Imbalance (Δ) | Orphan Records |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Post-Baseline (1u)** | 220 | 318 | 0 | 0 | 614 | $23,420.28 | $23,420.28 | **0 cents** | 0 |
| **Post-Tier 2 (5u)** | 1,164 | 1,713 | 0 | 0 | 3,344 | $130,675.06 | $130,675.06 | **0 cents** | 0 |
| **Post-Tier 3 (10u)** | 3,962 | 5,821 | 0 | 0 | 11,396 | $443,645.68 | $443,645.68 | **0 cents** | 0 |
| **Post-Tier 4 (25u)** | **9,218** | **13,680** | **0** | **0** | **26,772** | **$1,037,780.66** | **$1,037,780.66** | **0 cents** | **0** |

### 5.2 Final Audit Output (Post-Tier 4 Stress Verification)

```
=================================================================
 POST-LOAD TEST DATABASE INTEGRITY AUDIT REPORT
 Database: payment_gateway.db
=================================================================

[+] Total Payments Recorded: 9218
    - AUTHORIZED          : 1
    - CANCELLED           : 2
    - CAPTURED            : 7581
    - FAILED              : 294
    - PARTIALLY_REFUNDED  : 1338
    - REFUNDED            : 2

[+] Idempotency Records: 13680 total (13680 completed, 0 in-progress)
    [PASS] Zero lingering IN_PROGRESS keys (all locks finalized).
    [PASS] Zero duplicate idempotency keys detected.

[+] Double-Entry Ledger Audit (26772 total entries):
    - Total Debits  : 103,778,066 cents ($1,037,780.66)
    - Total Credits : 103,778,066 cents ($1,037,780.66)
    - Imbalance (Δ) : 0 cents
    [PASS] Double-entry ledger is PERFECTLY BALANCED (Total Debits == Total Credits).
    [PASS] Every individual ledger batch is mathematically balanced.
    [PASS] Zero cross-payment batch contamination (strict batch isolation).
    [PASS] Zero orphaned records across ledger, refunds, and webhooks (100% referential integrity).

[+] Refund Transactions: 1342 refunds totaling 4,024,000 cents ($40,240.00)

=================================================================
 OVERALL AUDIT RESULT: PASSED (Data Invariants 100% Satisfied)
=================================================================
```

---

## 6. Conclusions & Quality Engineering Insights

1. **Scalability Envelope:** The simulated payment gateway can comfortably serve up to **10 concurrent users at >105 RPS** with median response times under 10ms and p95 under 55ms.
2. **Boundary Behavior (25 Users):** When pushed to 25 concurrent users (150+ RPS), SQLite WAL write serialization forms the primary performance bottleneck. However, the system degrades predictably and safely: 99.94% of requests succeeded, zero database corruptions occurred, exactly balanced double-entry accounting was maintained across \$1.037M in simulated volume, and timed-out requests received graceful `HTTP 503 database_busy` responses.
3. **Idempotency Protection:** The framework demonstrated that idempotency caching is not only a functional safeguard against double-charging, but also a massive performance booster under write contention (providing a 10.4x speedup over cold database transactions).

---

## 7. Retrying Failed HTTP 503 Requests: Concurrency & Idempotency Proof

To rigorously evaluate Item 5 of the Phase 4 audit, a dedicated verification test was executed via [test_retry_503_idempotency.py](file:///c:/Users/Logesh/Documents/payment-gateway-qa-framework/scripts/test_retry_503_idempotency.py):
1. **Contention Simulation:** An exclusive raw SQLite lock was acquired on the database, forcing a mutating payment request to exceed the 5,000ms `busy_timeout`.
2. **Controlled 503 Error:** The gateway intercepted `OperationalError: database is locked` and returned `HTTP 503 database_busy` with `{"retriable": true}`. The uncommitted lock was rolled back.
3. **Safe Retry:** The client retried the identical transaction using the **exact same** `Idempotency-Key`.
4. **Successful Execution:** The retried request succeeded with `HTTP 201 Created` (`status: CAPTURED`).
5. **Cached Replay Verification:** A 3rd request sent with the same key hit the completed cache, returning the identical payment ID.
6. **SQL Database Audit:**
   - Exactly **1 payment record** was created.
   - Exactly **2 ledger entries** (1 Debit, 1 Credit = \$125.00) were created.
   - Zero duplicate payments, zero duplicate ledger entries, and zero orphaned records were created.

```
======================================================================
 AUDIT ITEM 5: HTTP 503 RETRY & IDEMPOTENCY INTEGRITY TEST
======================================================================
[Step 1] Acquiring exclusive raw lock on SQLite database (./payment_gateway.db)...
         Exclusive lock acquired. Other mutating transactions will be blocked.
[Step 2] Sending payment request while database is exclusively locked...
         Holding exclusive lock for 6.5s to force SQLite lock timeout...
[Step 3] Releasing raw exclusive lock (ROLLBACK)...
         Exclusive lock released.
[Step 4] Checking response of blocked request:
         Status Code: 503
         Response Body: {'error': {'code': 'database_busy', 'message': 'Database is temporarily busy under concurrent load. Safely retry with your Idempotency-Key.', 'details': {'retriable': True}}}
         [PASS] Initial request cleanly rejected with HTTP 503 database_busy (retriable: true).
[Step 5] Retrying request using EXACT SAME Idempotency-Key ('audit_503_retry_f3a21237f6c2')...
         Status Code: 201
         Response Body: {'id': 'pay_4b70c508c5204572b3', 'status': 'CAPTURED', ...}
         [PASS] Retried request succeeded with HTTP 201 Created (ID: pay_4b70c508c5204572b3).
[Step 6] Sending 3rd request with SAME key to verify cached replay...
         Status Code: 201
         [PASS] 3rd request returned cached response with identical payment ID.
[Step 7] Independent SQL-level Database Audit for this transaction:
         - Payments with ID 'pay_4b70c508c5204572b3': 1 (Expected: 1)
         - Idempotency Key Status: COMPLETED, Linked Payment: pay_4b70c508c5204572b3
         - Ledger entries: 2 entries | Debits: 12500¢ | Credits: 12500¢
         - Total payments created during this entire test: 1 (Expected: 1)
======================================================================
 ITEM 5 AUDIT RESULT: PASSED (Zero duplicate payments/ledgers on 503 retry)
======================================================================
```

---

## 8. Apache JMeter Test Plan Status

- **Status:** **Prepared and Validated (Not Executed)**
- **Artifact:** [payment_gateway_load_test.jmx](file:///c:/Users/Logesh/Documents/payment-gateway-qa-framework/tests/performance/payment_gateway_load_test.jmx)
- **Explanation:** The Windows 11 host environment does not have Java or Apache JMeter installed on the system PATH (`java -version` and `jmeter` not found). In accordance with the Phase 4 test strategy, Locust 2.47.0 was utilized as the live execution engine. The JMeter test plan is completely authored and validated as an enterprise XML deliverable ready for immediate execution in environments where the Java/JMeter runtime is present.

---

## 9. Comprehensive Performance Artifact Index

| Artifact Description | File Path |
| :--- | :--- |
| **Locust Load Suite** | [locustfile.py](file:///c:/Users/Logesh/Documents/payment-gateway-qa-framework/tests/performance/locustfile.py) |
| **Apache JMeter Plan** | [payment_gateway_load_test.jmx](file:///c:/Users/Logesh/Documents/payment-gateway-qa-framework/tests/performance/payment_gateway_load_test.jmx) |
| **Integrity Auditor Script** | [verify_performance_integrity.py](file:///c:/Users/Logesh/Documents/payment-gateway-qa-framework/scripts/verify_performance_integrity.py) |
| **503 Retry Test Script** | [test_retry_503_idempotency.py](file:///c:/Users/Logesh/Documents/payment-gateway-qa-framework/scripts/test_retry_503_idempotency.py) |
| **Tier 1 (1u) Stats CSV** | [baseline_1u_stats.csv](file:///c:/Users/Logesh/Documents/payment-gateway-qa-framework/tests/performance/results/baseline_1u_stats.csv) |
| **Tier 1 (1u) Audit Log** | [baseline_1u_integrity_audit.txt](file:///c:/Users/Logesh/Documents/payment-gateway-qa-framework/tests/performance/results/baseline_1u_integrity_audit.txt) |
| **Tier 2 (5u) Stats CSV** | [load_5u_stats.csv](file:///c:/Users/Logesh/Documents/payment-gateway-qa-framework/tests/performance/results/load_5u_stats.csv) |
| **Tier 2 (5u) Audit Log** | [load_5u_integrity_audit.txt](file:///c:/Users/Logesh/Documents/payment-gateway-qa-framework/tests/performance/results/load_5u_integrity_audit.txt) |
| **Tier 3 (10u) Stats CSV**| [load_10u_stats.csv](file:///c:/Users/Logesh/Documents/payment-gateway-qa-framework/tests/performance/results/load_10u_stats.csv) |
| **Tier 3 (10u) Audit Log**| [load_10u_integrity_audit.txt](file:///c:/Users/Logesh/Documents/payment-gateway-qa-framework/tests/performance/results/load_10u_integrity_audit.txt) |
| **Tier 4 (25u) Stats CSV**| [stress_25u_stats.csv](file:///c:/Users/Logesh/Documents/payment-gateway-qa-framework/tests/performance/results/stress_25u_stats.csv) |
| **Tier 4 (25u) Failures CSV**| [stress_25u_failures.csv](file:///c:/Users/Logesh/Documents/payment-gateway-qa-framework/tests/performance/results/stress_25u_failures.csv) |
| **Tier 4 (25u) Audit Log**| [stress_25u_integrity_audit.txt](file:///c:/Users/Logesh/Documents/payment-gateway-qa-framework/tests/performance/results/stress_25u_integrity_audit.txt) |
