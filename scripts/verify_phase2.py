"""Phase 2 Verification Script.

Executes and verifies every feature of the Payment Gateway Simulator:
1. Health check
2. Payment creation & direct capture
3. Idempotency (same payload, different payload 409, independent keys)
4. Two-step authorization and capture
5. Invalid state transitions (rejections with HTTP 409)
6. Payment cancellation (void)
7. Partial and full refunds with balance constraints (HTTP 422)
8. Deterministic bank decline codes (402, 403, 504)
9. Amount boundaries and currency validation
10. Genuine double-entry ledger balance assertion
11. Webhook HMAC-SHA256 signature verification
"""

import asyncio
import os
import sys
import time
import uuid

# Ensure root directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx

from app.core.config import settings
from app.main import app
from app.services.webhook_service import WebhookService

MERCHANT_API_KEY = settings.DEFAULT_MERCHANT_API_KEY
MERCHANT_ID = settings.DEFAULT_MERCHANT_ID
MERCHANT_SECRET = settings.DEFAULT_MERCHANT_WEBHOOK_SECRET

HEADERS = {
    "X-API-Key": MERCHANT_API_KEY,
    "Content-Type": "application/json",
}


async def run_verification():
    print("=" * 70)
    print("STARTING PHASE 2 COMPONENT VERIFICATION")
    print("=" * 70)

    passed_checks = 0
    total_checks = 0

    def assert_check(condition: bool, description: str):
        nonlocal passed_checks, total_checks
        total_checks += 1
        if condition:
            print(f"  [PASS] {description}")
            passed_checks += 1
        else:
            print(f"  [FAIL] {description}")
            sys.exit(1)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Health check
        print("\n1. Verifying System Health Endpoint...")
        res = await client.get("/health")
        assert_check(res.status_code == 200, "Health check returns HTTP 200")
        assert_check(res.json()["status"] == "healthy", "Service status reports 'healthy'")

        # 2. Direct Capture Payment Creation
        print("\n2. Verifying Direct Capture Payment Creation...")
        idem_key_1 = f"test_key_{uuid.uuid4().hex[:12]}"
        payload_1 = {
            "amount_cents": 5000,
            "currency": "USD",
            "card_number": "4000000000000001",
            "exp_month": 12,
            "exp_year": 2028,
            "cvv": "123",
            "capture": True,
            "customer_email": "jane.doe@example.com",
        }
        res = await client.post(
            "/v1/payments",
            headers={**HEADERS, "Idempotency-Key": idem_key_1},
            json=payload_1,
        )
        assert_check(res.status_code == 201, "Direct capture returns HTTP 201 Created")
        data_1 = res.json()
        payment_id_1 = data_1["id"]
        assert_check(data_1["status"] == "CAPTURED", "Payment status is CAPTURED")
        assert_check(data_1["captured"] is True, "captured flag is True")
        assert_check(data_1["card_last4"] == "0001", "card_last4 is correctly masked")

        # 3. Idempotency Verification
        print("\n3. Verifying Idempotency Rules...")
        # 3a. Same Key + Same Payload -> Replay Cached Result
        res_replay = await client.post(
            "/v1/payments",
            headers={**HEADERS, "Idempotency-Key": idem_key_1},
            json=payload_1,
        )
        assert_check(res_replay.status_code == 201, "Replay returns HTTP 201 Created")
        assert_check(res_replay.json()["id"] == payment_id_1, "Replay returns identical payment ID")

        # 3b. Same Key + Different Payload -> HTTP 409 Conflict
        altered_payload = {**payload_1, "amount_cents": 9999}
        res_mismatch = await client.post(
            "/v1/payments",
            headers={**HEADERS, "Idempotency-Key": idem_key_1},
            json=altered_payload,
        )
        assert_check(res_mismatch.status_code == 409, "Payload mismatch returns HTTP 409 Conflict")
        assert_check(
            res_mismatch.json()["error"]["code"] == "idempotency_payload_mismatch",
            "Error code is 'idempotency_payload_mismatch'",
        )

        # 3c. Different Key -> Independent Transaction
        idem_key_2 = f"test_key_{uuid.uuid4().hex[:12]}"
        res_diff = await client.post(
            "/v1/payments",
            headers={**HEADERS, "Idempotency-Key": idem_key_2},
            json=payload_1,
        )
        assert_check(res_diff.status_code == 201, "Different key returns HTTP 201 Created")
        assert_check(res_diff.json()["id"] != payment_id_1, "Different key generates new payment ID")

        # 4. Two-Step Authorization & Capture
        print("\n4. Verifying Two-Step Authorization and Capture...")
        idem_key_auth = f"test_key_{uuid.uuid4().hex[:12]}"
        payload_auth = {**payload_1, "capture": False, "amount_cents": 8000}
        res_auth = await client.post(
            "/v1/payments",
            headers={**HEADERS, "Idempotency-Key": idem_key_auth},
            json=payload_auth,
        )
        assert_check(res_auth.status_code == 201, "Auth returns HTTP 201 Created")
        auth_data = res_auth.json()
        payment_id_auth = auth_data["id"]
        assert_check(auth_data["status"] == "AUTHORIZED", "Payment status is AUTHORIZED")
        assert_check(auth_data["captured"] is False, "captured flag is False")

        # Capture the authorized payment
        idem_key_cap = f"test_key_{uuid.uuid4().hex[:12]}"
        res_cap = await client.post(
            f"/v1/payments/{payment_id_auth}/capture",
            headers={**HEADERS, "Idempotency-Key": idem_key_cap},
            json={"amount_cents": 8000},
        )
        assert_check(res_cap.status_code == 200, "Capture returns HTTP 200 OK")
        assert_check(res_cap.json()["status"] == "CAPTURED", "Status transitioned to CAPTURED")
        assert_check(res_cap.json()["captured"] is True, "captured flag updated to True")

        # 5. Invalid State Transition Rejection (HTTP 409)
        print("\n5. Verifying Invalid State Transitions...")
        # Attempt to re-capture already captured payment
        idem_key_invalid = f"test_key_{uuid.uuid4().hex[:12]}"
        res_recapture = await client.post(
            f"/v1/payments/{payment_id_auth}/capture",
            headers={**HEADERS, "Idempotency-Key": idem_key_invalid},
            json={"amount_cents": 8000},
        )
        assert_check(res_recapture.status_code == 409, "Recapturing returns HTTP 409 Conflict")
        assert_check(
            res_recapture.json()["error"]["code"] == "invalid_state_transition",
            "Error code is 'invalid_state_transition'",
        )

        # 6. Payment Cancellation (Void)
        print("\n6. Verifying Payment Cancellation (Void)...")
        idem_key_void = f"test_key_{uuid.uuid4().hex[:12]}"
        res_auth_to_cancel = await client.post(
            "/v1/payments",
            headers={**HEADERS, "Idempotency-Key": idem_key_void},
            json={**payload_1, "capture": False, "amount_cents": 3000},
        )
        payment_id_to_cancel = res_auth_to_cancel.json()["id"]

        idem_key_canc = f"test_key_{uuid.uuid4().hex[:12]}"
        res_cancel = await client.post(
            f"/v1/payments/{payment_id_to_cancel}/cancel",
            headers={**HEADERS, "Idempotency-Key": idem_key_canc},
            json={"reason": "customer_changed_mind"},
        )
        assert_check(res_cancel.status_code == 200, "Cancel returns HTTP 200 OK")
        assert_check(res_cancel.json()["status"] == "CANCELLED", "Status transitioned to CANCELLED")

        # Attempt to capture cancelled payment -> Must fail with 409
        idem_key_cap_canc = f"test_key_{uuid.uuid4().hex[:12]}"
        res_cap_canc = await client.post(
            f"/v1/payments/{payment_id_to_cancel}/capture",
            headers={**HEADERS, "Idempotency-Key": idem_key_cap_canc},
            json={},
        )
        assert_check(res_cap_canc.status_code == 409, "Capturing cancelled payment returns HTTP 409 Conflict")

        # 7. Refund Processing & Cumulative Limits
        print("\n7. Verifying Refund Processing...")
        # 7a. Partial refund of 2000 cents against payment_id_1 (captured 5000 cents)
        idem_ref_1 = f"test_key_{uuid.uuid4().hex[:12]}"
        res_ref_1 = await client.post(
            f"/v1/payments/{payment_id_1}/refund",
            headers={**HEADERS, "Idempotency-Key": idem_ref_1},
            json={"amount_cents": 2000, "reason": "damaged_goods"},
        )
        assert_check(res_ref_1.status_code == 200, "Partial refund returns HTTP 200 OK")
        assert_check(res_ref_1.json()["payment_status"] == "PARTIALLY_REFUNDED", "Payment status is PARTIALLY_REFUNDED")
        assert_check(res_ref_1.json()["remaining_balance_cents"] == 3000, "Remaining balance is 3000 cents")

        # 7b. Attempt refund exceeding remaining balance (attempt 4000 when 3000 left) -> 422
        idem_ref_exceed = f"test_key_{uuid.uuid4().hex[:12]}"
        res_ref_exceed = await client.post(
            f"/v1/payments/{payment_id_1}/refund",
            headers={**HEADERS, "Idempotency-Key": idem_ref_exceed},
            json={"amount_cents": 4000, "reason": "too_much"},
        )
        assert_check(res_ref_exceed.status_code == 422, "Exceeding refund returns HTTP 422 Unprocessable")
        assert_check(
            res_ref_exceed.json()["error"]["code"] == "refund_amount_exceeds_balance",
            "Error code is 'refund_amount_exceeds_balance'",
        )

        # 7c. Full remaining refund of 3000 cents -> Transitions to REFUNDED
        idem_ref_2 = f"test_key_{uuid.uuid4().hex[:12]}"
        res_ref_2 = await client.post(
            f"/v1/payments/{payment_id_1}/refund",
            headers={**HEADERS, "Idempotency-Key": idem_ref_2},
            json={"amount_cents": 3000, "reason": "return_remaining"},
        )
        assert_check(res_ref_2.status_code == 200, "Final refund returns HTTP 200 OK")
        assert_check(res_ref_2.json()["payment_status"] == "REFUNDED", "Payment status transitioned to REFUNDED")
        assert_check(res_ref_2.json()["remaining_balance_cents"] == 0, "Remaining balance is 0 cents")

        # 8. Deterministic Bank Decline Codes
        print("\n8. Verifying Deterministic Bank Declines...")
        declines = [
            ("4000000000000002", 402, "insufficient_funds"),
            ("4000000000000003", 402, "card_expired"),
            ("4000000000000004", 403, "suspected_fraud"),
            ("4000000000000005", 504, "gateway_timeout"),
        ]
        for card_no, expected_status, expected_code in declines:
            k = f"test_key_{uuid.uuid4().hex[:12]}"
            res_dec = await client.post(
                "/v1/payments",
                headers={**HEADERS, "Idempotency-Key": k},
                json={**payload_1, "card_number": card_no},
            )
            assert_check(
                res_dec.status_code == expected_status,
                f"Card ending {card_no[-4:]} returns HTTP {expected_status}",
            )
            assert_check(
                res_dec.json()["error"]["code"] == expected_code,
                f"Error code is '{expected_code}'",
            )

        # 9. Amount Boundary & Currency Validation
        print("\n9. Verifying Amount Boundaries & Currency Rules...")
        # Below 50 cents
        res_low = await client.post(
            "/v1/payments",
            headers={**HEADERS, "Idempotency-Key": f"k_{uuid.uuid4().hex[:10]}"},
            json={**payload_1, "amount_cents": 40},
        )
        assert_check(res_low.status_code == 400, "Amount below 50 cents returns HTTP 400 Bad Request")
        assert_check(res_low.json()["error"]["code"] == "amount_below_minimum", "Code is 'amount_below_minimum'")

        # Exceeding $100k
        res_high = await client.post(
            "/v1/payments",
            headers={**HEADERS, "Idempotency-Key": f"k_{uuid.uuid4().hex[:10]}"},
            json={**payload_1, "amount_cents": 10_000_001},
        )
        assert_check(res_high.status_code == 400, "Amount > $100k returns HTTP 400 Bad Request")
        assert_check(
            res_high.json()["error"]["code"] == "amount_exceeds_transaction_limit",
            "Code is 'amount_exceeds_transaction_limit'",
        )

        # Unsupported currency
        res_curr = await client.post(
            "/v1/payments",
            headers={**HEADERS, "Idempotency-Key": f"k_{uuid.uuid4().hex[:10]}"},
            json={**payload_1, "currency": "XYZ"},
        )
        assert_check(res_curr.status_code == 400, "Unsupported currency returns HTTP 400 Bad Request")
        assert_check(res_curr.json()["error"]["code"] == "unsupported_currency", "Code is 'unsupported_currency'")

        # 10. Genuine Double-Entry Ledger Invariant Assertion
        print("\n10. Verifying Genuine Double-Entry Ledger Balancing...")
        res_ledger = await client.get(
            f"/v1/merchants/{MERCHANT_ID}/ledger-summary",
            headers=HEADERS,
        )
        assert_check(res_ledger.status_code == 200, "Ledger inquiry returns HTTP 200 OK")
        ledger_data = res_ledger.json()
        assert_check(ledger_data["is_balanced"] is True, "Double-entry invariant: Sum(DEBITS) == Sum(CREDITS)")
        assert_check(
            ledger_data["total_debits_cents"] == ledger_data["total_credits_cents"],
            "Debit and Credit totals match exactly",
        )
        print(f"      Total Debits:  ${ledger_data['total_debits_cents']/100:.2f}")
        print(f"      Total Credits: ${ledger_data['total_credits_cents']/100:.2f}")
        print(f"      Merchant Avail Balance: ${ledger_data['available_balance_cents']/100:.2f}")
        print(f"      Total Ledger Entries: {ledger_data['entry_count']}")

        # 11. Webhook Signature Verification
        print("\n11. Verifying Webhook HMAC-SHA256 Signatures...")
        sample_payload = '{"event_id":"evt_test_123","event_type":"payment.captured"}'
        timestamp_now = int(time.time())
        valid_sig = WebhookService.compute_signature(MERCHANT_SECRET, timestamp_now, sample_payload)

        res_sig_valid = await client.post(
            "/v1/webhooks/verify",
            headers=HEADERS,
            json={"signature_header": valid_sig, "payload_json": sample_payload},
        )
        assert_check(res_sig_valid.json()["valid"] is True, "Valid HMAC signature passes verification")

        tampered_payload = '{"event_id":"evt_test_123","event_type":"payment.tampered"}'
        res_sig_invalid = await client.post(
            "/v1/webhooks/verify",
            headers=HEADERS,
            json={"signature_header": valid_sig, "payload_json": tampered_payload},
        )
        assert_check(res_sig_invalid.json()["valid"] is False, "Tampered payload fails signature verification")

    print("\n" + "=" * 70)
    print(f"PHASE 2 VERIFICATION COMPLETE: {passed_checks}/{total_checks} CHECKS PASSED (100%)")
    print("=" * 70)


if __name__ == "__main__":
    from app.db.session import init_db
    init_db()  # Ensure tables & default merchant are seeded
    asyncio.run(run_verification())
