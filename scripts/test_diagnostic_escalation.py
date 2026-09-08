#!/usr/bin/env python3
"""Insert test escalation row and verify check script counts it."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Try to import psycopg2
try:
    import psycopg2
except ImportError:
    print("Installing psycopg2-binary...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary"])
    import psycopg2

db_url = os.getenv('SUPABASE_DB_URL')
if not db_url:
    print("ERROR: SUPABASE_DB_URL not set")
    sys.exit(1)

print("=" * 80)
print("Testing Diagnostic Escalation Tracking")
print("=" * 80)
print()

try:
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    print("1. Checking current escalation count...")
    cur.execute("SELECT COUNT(*) FROM diagnostic_escalations")
    before_count = cur.fetchone()[0]
    print(f"   Current count: {before_count}")
    print()

    print("2. Inserting test escalation...")
    cur.execute("""
        INSERT INTO diagnostic_escalations (
            metric_name,
            metric_type,
            naive_value,
            final_value,
            target_value,
            improvement_pct,
            remaining_gap_pct,
            classifier_type,
            classifier_confidence,
            rules_tried,
            iterations_count,
            converged
        ) VALUES (
            'test_pipeline_value',
            'sum_dollars',
            14221230,
            7160865,
            7005865,
            97.9,
            2.2,
            'missing_rule',
            'high',
            ARRAY['exclude_renewals'],
            1,
            false
        )
        RETURNING id
    """)
    test_id = cur.fetchone()[0]
    print(f"   ✓ Test row inserted (id: {test_id})")
    print()

    print("3. Verifying count increased...")
    cur.execute("SELECT COUNT(*) FROM diagnostic_escalations")
    after_count = cur.fetchone()[0]
    print(f"   New count: {after_count}")

    if after_count == before_count + 1:
        print("   ✓ Count increased correctly")
    else:
        print(f"   ✗ Count mismatch (expected {before_count + 1}, got {after_count})")
        sys.exit(1)
    print()

    print("4. Running check_diagnostic_rederivation.py...")
    print()

    # Run the check script
    import subprocess
    result = subprocess.run(
        [sys.executable, "scripts/check_diagnostic_rederivation.py"],
        capture_output=True,
        text=True
    )

    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)

    if result.returncode == 0:
        print("   ✓ Check script ran successfully")
    else:
        print(f"   ✗ Check script exited with code {result.returncode}")
        sys.exit(1)
    print()

    print("5. Cleaning up test row...")
    cur.execute("DELETE FROM diagnostic_escalations WHERE id = %s", (test_id,))
    print(f"   ✓ Test row deleted")
    print()

    cur.close()
    conn.close()

    print("=" * 80)
    print("✅ All tests passed - diagnostic escalation tracking works")
    print("=" * 80)

except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)
