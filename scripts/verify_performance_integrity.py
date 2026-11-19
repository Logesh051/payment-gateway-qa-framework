"""Post-Performance-Test Data Integrity Auditor.

Independently inspects the SQLite database following load tests to verify:
1. Double-Entry Invariant: Total Debits == Total Credits (Zero discrepancy).
2. Payment State Integrity: Status distribution across all transactions.
3. Idempotency Invariant: Exactly one payment per key; no duplicate entries.
4. Orphan Detection: All ledger entries link to existing payment records.
"""

import os
import sqlite3
import sys

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.core.config import settings


def verify_integrity(db_path: str = "payment_gateway.db") -> bool:
    """Execute rigorous SQL-level audit on payment_gateway.db."""
    if not os.path.exists(db_path):
        print(f"[-] Database file '{db_path}' does not exist.")
        return False

    print("=" * 65)
    print(" POST-LOAD TEST DATABASE INTEGRITY AUDIT REPORT")
    print(f" Database: {db_path}")
    print("=" * 65)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    all_passed = True

    try:
        # 1. Payment Counts & States
        cursor.execute("SELECT status, COUNT(*) as count FROM payments GROUP BY status")
        status_rows = cursor.fetchall()
        total_payments = sum(r["count"] for r in status_rows)
        print(f"\n[+] Total Payments Recorded: {total_payments}")
        for r in status_rows:
            print(f"    - {r['status']:<20}: {r['count']}")

        # 2. Idempotency Audit
        cursor.execute("SELECT COUNT(*) FROM idempotency_keys")
        total_keys = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM idempotency_keys WHERE status = 'COMPLETED'")
        completed_keys = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM idempotency_keys WHERE status = 'IN_PROGRESS'")
        in_progress_keys = cursor.fetchone()[0]
        print(f"\n[+] Idempotency Records: {total_keys} total ({completed_keys} completed, {in_progress_keys} in-progress)")

        if in_progress_keys > 0:
            print(f"    [-] WARNING: Found {in_progress_keys} stuck IN_PROGRESS idempotency keys!")
            all_passed = False
        else:
            print("    [PASS] Zero lingering IN_PROGRESS keys (all locks finalized).")

        # Check for duplicate idempotency keys
        cursor.execute("SELECT key, COUNT(*) as cnt FROM idempotency_keys GROUP BY key HAVING cnt > 1")
        dupe_keys = cursor.fetchall()
        if dupe_keys:
            print(f"[-] CRITICAL: Found {len(dupe_keys)} duplicate idempotency keys!")
            all_passed = False
        else:
            print("    [PASS] Zero duplicate idempotency keys detected.")

        # 3. Double-Entry Ledger Verification
        cursor.execute("""
            SELECT 
                COUNT(*),
                COALESCE(SUM(CASE WHEN entry_type = 'DEBIT' THEN amount_cents ELSE 0 END), 0) as total_debits,
                COALESCE(SUM(CASE WHEN entry_type = 'CREDIT' THEN amount_cents ELSE 0 END), 0) as total_credits
            FROM ledger_entries
        """)
        ledger_count, total_debits, total_credits = cursor.fetchone()
        delta = total_debits - total_credits
        print(f"\n[+] Double-Entry Ledger Audit ({ledger_count} total entries):")
        print(f"    - Total Debits  : {total_debits:,} cents (${total_debits/100:,.2f})")
        print(f"    - Total Credits : {total_credits:,} cents (${total_credits/100:,.2f})")
        print(f"    - Imbalance (Δ) : {delta} cents")

        if delta == 0:
            print("    [PASS] Double-entry ledger is PERFECTLY BALANCED (Total Debits == Total Credits).")
        else:
            print(f"    [-] FAIL: Ledger imbalance of {delta} cents detected!")
            all_passed = False

        # Per-batch balance invariant: Every single batch must balance to zero
        cursor.execute("""
            SELECT batch_id, 
                   SUM(CASE WHEN entry_type = 'DEBIT' THEN amount_cents ELSE 0 END) as debits,
                   SUM(CASE WHEN entry_type = 'CREDIT' THEN amount_cents ELSE 0 END) as credits
            FROM ledger_entries
            GROUP BY batch_id
            HAVING debits != credits
        """)
        unbalanced_batches = cursor.fetchall()
        if unbalanced_batches:
            print(f"    [-] FAIL: Found {len(unbalanced_batches)} individual ledger batches that do not balance!")
            all_passed = False
        else:
            print("    [PASS] Every individual ledger batch is mathematically balanced.")

        # Check for duplicate / multi-payment ledger batch contamination
        cursor.execute("""
            SELECT batch_id, COUNT(DISTINCT payment_id) as p_cnt
            FROM ledger_entries
            GROUP BY batch_id
            HAVING p_cnt > 1
        """)
        cross_payment_batches = cursor.fetchall()
        if cross_payment_batches:
            print(f"    [-] FAIL: Found {len(cross_payment_batches)} ledger batches shared across multiple payments!")
            all_passed = False
        else:
            print("    [PASS] Zero cross-payment batch contamination (strict batch isolation).")

        # 4. Check for Orphaned Records
        cursor.execute("""
            SELECT COUNT(*) FROM ledger_entries le
            LEFT JOIN payments p ON le.payment_id = p.id
            WHERE p.id IS NULL
        """)
        orphaned_ledger = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM refunds r
            LEFT JOIN payments p ON r.payment_id = p.id
            WHERE p.id IS NULL
        """)
        orphaned_refunds = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM webhook_events w
            LEFT JOIN payments p ON w.payment_id = p.id
            WHERE p.id IS NULL
        """)
        orphaned_webhooks = cursor.fetchone()[0]

        total_orphans = orphaned_ledger + orphaned_refunds + orphaned_webhooks
        if total_orphans > 0:
            print(f"    [-] FAIL: Found {total_orphans} orphaned records (ledger: {orphaned_ledger}, refunds: {orphaned_refunds}, webhooks: {orphaned_webhooks})!")
            all_passed = False
        else:
            print("    [PASS] Zero orphaned records across ledger, refunds, and webhooks (100% referential integrity).")

        # 5. Refunds Audit
        cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount_cents), 0) FROM refunds")
        refund_count, total_refunds = cursor.fetchone()
        print(f"\n[+] Refund Transactions: {refund_count} refunds totaling {total_refunds:,} cents (${total_refunds/100:,.2f})")

        print("\n" + "=" * 65)
        if all_passed:
            print(" OVERALL AUDIT RESULT: PASSED (Data Invariants 100% Satisfied)")
        else:
            print(" OVERALL AUDIT RESULT: FAILED (Integrity Violations Found)")
        print("=" * 65)

    finally:
        conn.close()

    return all_passed


if __name__ == "__main__":
    db_file = sys.argv[1] if len(sys.argv) > 1 else "payment_gateway.db"
    success = verify_integrity(db_file)
    sys.exit(0 if success else 1)
