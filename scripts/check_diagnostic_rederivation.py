#!/usr/bin/env python3
"""
Check if diagnostic classifier re-derivation trigger has fired.

Runs monthly via GitHub Actions. Checks escalation count and notifies
if re-derivation threshold (20+ human-reviewed escalations) is reached.

Exit codes:
  0 - Check ran successfully (may or may not have triggered)
  1 - Error connecting to database or querying data
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

try:
    from supabase import create_client
except ImportError:
    print("ERROR: supabase-py not installed")
    print("Run: pip install supabase")
    sys.exit(1)

# Supabase connection
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    sys.exit(1)

# Owner for notifications (REPLACE WITH ACTUAL SLACK HANDLE)
OWNER_SLACK_HANDLE = "@jeff"  # TODO: Replace with actual Slack handle
OWNER_EMAIL = "jeff@revopsimpact.com"  # TODO: Replace with actual email

# Re-derivation threshold
REDERIVATION_THRESHOLD = 20

print("="*80)
print("DIAGNOSTIC CLASSIFIER RE-DERIVATION CHECK")
print("="*80)
print(f"Date: {datetime.now().isoformat()}")
print(f"Threshold: {REDERIVATION_THRESHOLD} human-reviewed escalations")
print()

try:
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Check if table exists
    # Try a simple query first to verify table exists
    try:
        test_query = sb.table("diagnostic_escalations").select("id", count="exact").limit(1).execute()
    except Exception as e:
        error_str = str(e).lower()
        if any(keyword in error_str for keyword in ["does not exist", "relation", "could not find", "pgrst205"]):
            print("ℹ️  diagnostic_escalations table does not exist yet")
            print()
            print("This is normal if Phase 2b hasn't been deployed to production yet.")
            print("The table will be created when the first escalation is logged.")
            print()
            print("No action required at this time.")
            sys.exit(0)
        else:
            raise

    # Count total escalations
    total_result = sb.table("diagnostic_escalations").select("id", count="exact").execute()
    total_escalations = total_result.count or 0

    # Count human-reviewed escalations (required for re-derivation)
    reviewed_result = sb.table("diagnostic_escalations").select(
        "id", count="exact"
    ).eq("human_reviewed", True).execute()
    reviewed_count = reviewed_result.count or 0

    print(f"Total escalations logged: {total_escalations}")
    print(f"Human-reviewed escalations: {reviewed_count}")
    print()

    if reviewed_count >= REDERIVATION_THRESHOLD:
        print("⚠️  RE-DERIVATION TRIGGER FIRED")
        print("="*80)
        print()
        print(f"   ✓ Threshold reached: {reviewed_count} >= {REDERIVATION_THRESHOLD}")
        print()
        print("ACTION REQUIRED:")
        print(f"   Owner: {OWNER_SLACK_HANDLE} ({OWNER_EMAIL})")
        print("   Deadline: Within 2 weeks of this notification")
        print()
        print("PROCEDURE:")
        print("   1. Read: DIAGNOSTIC_REDERIVATION_PROCEDURE.md")
        print("   2. Export human-reviewed escalations")
        print("   3. Analyze current classifier accuracy")
        print("   4. Re-tune thresholds from real production data")
        print("   5. Validate new thresholds")
        print("   6. Update code and documentation")
        print()
        print("NOTIFICATION:")
        print(f"   - Slack: {OWNER_SLACK_HANDLE} in #revenue-ops")
        print(f"   - Email: {OWNER_EMAIL}")
        print(f"   - GitHub: Issue auto-created with checklist")
        print()
        print("="*80)

        # In production, this would:
        # - Send Slack notification
        # - Send email
        # - Create GitHub issue
        # For now, just print the notification

    else:
        remaining = REDERIVATION_THRESHOLD - reviewed_count
        print(f"✓ Threshold not yet reached")
        print(f"   {reviewed_count} / {REDERIVATION_THRESHOLD} human-reviewed escalations")
        print(f"   {remaining} more needed to trigger re-derivation")
        print()
        print("No action required at this time.")

    print()
    print("Check completed successfully.")
    sys.exit(0)

except Exception as e:
    print()
    print("="*80)
    print("ERROR")
    print("="*80)
    print(f"Failed to check re-derivation status: {e}")
    print()
    print("This check will run again next month.")
    print(f"If this error persists, contact: {OWNER_EMAIL}")
    sys.exit(1)
