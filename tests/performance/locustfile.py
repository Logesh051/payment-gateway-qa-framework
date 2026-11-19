"""Locust Load & Performance Testing Suite for Payment Gateway Simulator.

Implements realistic simulated user workflows across 6 core payment scenarios:
1. Normal payment creation (single-step authorization and capture).
2. Two-step payment authorization and subsequent capture.
3. Full payment lifecycle (Authorization -> Capture -> Partial Refund).
4. Idempotency cache verification and replay latency under load.
5. High-throughput bursts with unique idempotency keys.
6. Negative scenarios and deterministic bank declines (validating 4xx error handling).
"""

import os
import random
import sys
import uuid
from locust import HttpUser, task, between, tag

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.core.config import settings


class PaymentGatewayUser(HttpUser):
    """Simulated merchant client executing payment gateway API operations."""

    # Paced user think-time between 50ms and 200ms for high-frequency testing
    wait_time = between(0.05, 0.2)

    def on_start(self):
        """Verify gateway health prior to initiating load tasks."""
        self.api_key = settings.DEFAULT_MERCHANT_API_KEY
        self.default_headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }
        with self.client.get("/health", headers={"X-API-Key": self.api_key}, catch_response=True) as resp:
            if resp.status_code == 200 and resp.json().get("status") == "healthy":
                resp.success()
            else:
                resp.failure(f"Health check failed with status {resp.status_code}")

    def _generate_key(self, prefix: str = "perf") -> str:
        """Generate a random UUID-based idempotency key."""
        return f"{prefix}_{uuid.uuid4().hex[:16]}"

    # =========================================================================
    # SCENARIO 1: Normal Payment Creation (Single-step Auth & Capture)
    # =========================================================================
    @tag("scenario1", "create", "normal")
    @task(30)
    def task_create_payment_direct(self):
        """Direct payment creation with immediate capture (weight: 30)."""
        amount = random.randint(1000, 20000)  # $10.00 to $200.00
        idem_key = self._generate_key("create")
        headers = {**self.default_headers, "Idempotency-Key": idem_key}
        payload = {
            "amount_cents": amount,
            "currency": "USD",
            "card_number": "4000000000000001",
            "exp_month": 12,
            "exp_year": 2028,
            "cvv": "123",
            "capture": True,
            "customer_email": "loadtest@example.com",
            "description": "Locust Scenario 1 - Direct Payment",
        }

        with self.client.post(
            "/v1/payments",
            json=payload,
            headers=headers,
            name="/v1/payments [Direct Create & Capture]",
            catch_response=True,
        ) as response:
            if response.status_code == 201:
                data = response.json()
                if data.get("status") == "CAPTURED" and data.get("amount_cents") == amount:
                    response.success()
                else:
                    response.failure(f"Unexpected payment status: {data.get('status')}")
            elif response.status_code == 503:
                response.failure("Database Busy (SQLite Lock Saturation)")
            else:
                response.failure(f"HTTP {response.status_code}: {response.text}")

    # =========================================================================
    # SCENARIO 2: Two-Step Authorization & Capture
    # =========================================================================
    @tag("scenario2", "auth_capture")
    @task(20)
    def task_auth_and_capture(self):
        """Two-step flow: Authorize first, then capture in a separate request (weight: 20)."""
        amount = random.randint(1500, 15000)
        auth_key = self._generate_key("auth")
        headers = {**self.default_headers, "Idempotency-Key": auth_key}
        auth_payload = {
            "amount_cents": amount,
            "currency": "USD",
            "card_number": "4000000000000001",
            "exp_month": 12,
            "exp_year": 2028,
            "cvv": "123",
            "capture": False,
            "customer_email": "loadtest.auth@example.com",
            "description": "Locust Scenario 2 - Pre-Authorization",
        }

        # Step 1: Pre-Authorization
        payment_id = None
        with self.client.post(
            "/v1/payments",
            json=auth_payload,
            headers=headers,
            name="/v1/payments [Pre-Auth]",
            catch_response=True,
        ) as auth_resp:
            if auth_resp.status_code == 201:
                data = auth_resp.json()
                if data.get("status") == "AUTHORIZED":
                    payment_id = data.get("id")
                    auth_resp.success()
                else:
                    auth_resp.failure(f"Expected AUTHORIZED, got {data.get('status')}")
                    return
            else:
                auth_resp.failure(f"Auth failed with HTTP {auth_resp.status_code}")
                return

        # Step 2: Capture
        if payment_id:
            cap_key = self._generate_key("cap")
            cap_headers = {**self.default_headers, "Idempotency-Key": cap_key}
            cap_payload = {"amount_cents": amount}

            with self.client.post(
                f"/v1/payments/{payment_id}/capture",
                json=cap_payload,
                headers=cap_headers,
                name="/v1/payments/{id}/capture",
                catch_response=True,
            ) as cap_resp:
                if cap_resp.status_code == 200 and cap_resp.json().get("status") == "CAPTURED":
                    cap_resp.success()
                else:
                    cap_resp.failure(f"Capture failed with HTTP {cap_resp.status_code}")

    # =========================================================================
    # SCENARIO 3: Full Payment Lifecycle (Auth -> Capture -> Refund)
    # =========================================================================
    @tag("scenario3", "lifecycle")
    @task(15)
    def task_payment_lifecycle(self):
        """Full lifecycle: Authorize -> Capture -> Partial Refund (weight: 15)."""
        amount = 10000  # $100.00
        refund_amount = 3000  # $30.00

        # Step 1: Pre-Auth
        auth_key = self._generate_key("life_auth")
        auth_headers = {**self.default_headers, "Idempotency-Key": auth_key}
        auth_payload = {
            "amount_cents": amount,
            "currency": "USD",
            "card_number": "4000000000000001",
            "exp_month": 12,
            "exp_year": 2028,
            "cvv": "123",
            "capture": False,
            "customer_email": "loadtest.lifecycle@example.com",
            "description": "Locust Scenario 3 - Lifecycle Auth",
        }

        payment_id = None
        with self.client.post(
            "/v1/payments",
            json=auth_payload,
            headers=auth_headers,
            name="/v1/payments [Lifecycle Auth]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 201:
                payment_id = resp.json().get("id")
                resp.success()
            else:
                resp.failure(f"Lifecycle Auth failed: HTTP {resp.status_code}")
                return

        # Step 2: Capture
        cap_key = self._generate_key("life_cap")
        with self.client.post(
            f"/v1/payments/{payment_id}/capture",
            json={"amount_cents": amount},
            headers={**self.default_headers, "Idempotency-Key": cap_key},
            name="/v1/payments/{id}/capture [Lifecycle]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Lifecycle Capture failed: HTTP {resp.status_code}")
                return

        # Step 3: Partial Refund
        ref_key = self._generate_key("life_ref")
        with self.client.post(
            f"/v1/payments/{payment_id}/refund",
            json={"amount_cents": refund_amount, "reason": "load_test_return"},
            headers={**self.default_headers, "Idempotency-Key": ref_key},
            name="/v1/payments/{id}/refund [Lifecycle]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                if data.get("payment_status") == "PARTIALLY_REFUNDED":
                    resp.success()
                else:
                    resp.failure(f"Unexpected refund state: {data.get('payment_status')}")
            else:
                resp.failure(f"Lifecycle Refund failed: HTTP {resp.status_code}")

    # =========================================================================
    # SCENARIO 4: Idempotency Replay & Cache Latency
    # =========================================================================
    @tag("scenario4", "idempotency", "replay")
    @task(15)
    def task_idempotency_replay(self):
        """Execute initial payment followed by repeated identical requests (weight: 15)."""
        idem_key = self._generate_key("replay")
        headers = {**self.default_headers, "Idempotency-Key": idem_key}
        payload = {
            "amount_cents": 4500,
            "currency": "USD",
            "card_number": "4000000000000001",
            "exp_month": 12,
            "exp_year": 2028,
            "cvv": "123",
            "capture": True,
            "customer_email": "loadtest.replay@example.com",
            "description": "Locust Scenario 4 - Idempotency Replay Initial",
        }

        first_payment_id = None
        # Initial request: writes to database
        with self.client.post(
            "/v1/payments",
            json=payload,
            headers=headers,
            name="/v1/payments [Idempotency 1st Attempt]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 201:
                first_payment_id = resp.json().get("id")
                resp.success()
            else:
                resp.failure(f"Initial request failed: HTTP {resp.status_code}")
                return

        # Immediate replay with same key and payload: should hit idempotency cache
        with self.client.post(
            "/v1/payments",
            json=payload,
            headers=headers,
            name="/v1/payments [Idempotency 2nd Replay - Cached]",
            catch_response=True,
        ) as replay_resp:
            if replay_resp.status_code == 201:
                replayed_id = replay_resp.json().get("id")
                if replayed_id == first_payment_id:
                    replay_resp.success()
                else:
                    replay_resp.failure(f"Idempotency violation! Mismatched ID: {replayed_id} vs {first_payment_id}")
            else:
                replay_resp.failure(f"Cached replay failed: HTTP {replay_resp.status_code}")

    # =========================================================================
    # SCENARIO 5: Rapid Bursts with Distinct Idempotency Keys
    # =========================================================================
    @tag("scenario5", "burst")
    @task(10)
    def task_concurrent_distinct_keys(self):
        """Simulate rapid independent transactions with distinct keys (weight: 10)."""
        for i in range(2):
            idem_key = self._generate_key(f"burst_{i}")
            headers = {**self.default_headers, "Idempotency-Key": idem_key}
            payload = {
                "amount_cents": random.randint(2000, 8000),
                "currency": "EUR",
                "card_number": "4000000000000001",
                "exp_month": 12,
                "exp_year": 2028,
                "cvv": "123",
                "capture": True,
                "customer_email": f"burst_{i}@example.com",
                "description": f"Locust Scenario 5 - Burst Step {i}",
            }
            with self.client.post(
                "/v1/payments",
                json=payload,
                headers=headers,
                name="/v1/payments [Distinct Key Burst]",
                catch_response=True,
            ) as resp:
                if resp.status_code == 201:
                    resp.success()
                else:
                    resp.failure(f"Burst request failed: HTTP {resp.status_code}")

    # =========================================================================
    # SCENARIO 6: Invalid Requests & Expected Error Handling
    # =========================================================================
    @tag("scenario6", "errors", "negative")
    @task(10)
    def task_negative_scenarios(self):
        """Validate gateway error resilience and HTTP status envelopes under load (weight: 10)."""
        sub_scenario = random.choice(["below_min", "unsupported_currency", "bank_decline"])

        if sub_scenario == "below_min":
            # Amount < 50 cents -> 400 Bad Request
            headers = {**self.default_headers, "Idempotency-Key": self._generate_key("err_min")}
            payload = {
                "amount_cents": 10,  # Below MIN (50)
                "currency": "USD",
                "card_number": "4000000000000001",
                "exp_month": 12,
                "exp_year": 2028,
                "cvv": "123",
                "capture": True,
            }
            with self.client.post(
                "/v1/payments",
                json=payload,
                headers=headers,
                name="/v1/payments [Expected 400 - Below Min]",
                catch_response=True,
            ) as resp:
                if resp.status_code == 400 and resp.json().get("error", {}).get("code") == "amount_below_minimum":
                    resp.success()
                else:
                    resp.failure(f"Expected 400 amount_below_minimum, got {resp.status_code}")

        elif sub_scenario == "unsupported_currency":
            # Currency not supported -> 400 Bad Request
            headers = {**self.default_headers, "Idempotency-Key": self._generate_key("err_curr")}
            payload = {
                "amount_cents": 2500,
                "currency": "XYZ",  # Unsupported
                "card_number": "4000000000000001",
                "exp_month": 12,
                "exp_year": 2028,
                "cvv": "123",
                "capture": True,
            }
            with self.client.post(
                "/v1/payments",
                json=payload,
                headers=headers,
                name="/v1/payments [Expected 400 - Bad Currency]",
                catch_response=True,
            ) as resp:
                if resp.status_code == 400 and resp.json().get("error", {}).get("code") == "unsupported_currency":
                    resp.success()
                else:
                    resp.failure(f"Expected 400 unsupported_currency, got {resp.status_code}")

        elif sub_scenario == "bank_decline":
            # Card ending in 0002 -> 402 Insufficient Funds
            headers = {**self.default_headers, "Idempotency-Key": self._generate_key("err_decline")}
            payload = {
                "amount_cents": 7500,
                "currency": "USD",
                "card_number": "4000000000000002",  # Insufficient funds
                "exp_month": 12,
                "exp_year": 2028,
                "cvv": "123",
                "capture": True,
            }
            with self.client.post(
                "/v1/payments",
                json=payload,
                headers=headers,
                name="/v1/payments [Expected 402 - Bank Decline]",
                catch_response=True,
            ) as resp:
                if resp.status_code == 402 and resp.json().get("error", {}).get("code") == "insufficient_funds":
                    resp.success()
                else:
                    resp.failure(f"Expected 402 insufficient_funds, got {resp.status_code}")
