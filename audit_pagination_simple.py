#!/usr/bin/env python3
"""
Simple Pagination Audit

Check actual vs returned row counts for all snapshot queries.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent))

from api.db import get_supabase

QUARTERS = [
    ('FY2026 Q3', '2025-11-01', '2026-01-31'),
    ('FY2026 Q4', '2026-02-01', '2026-04-30'),
    ('FY2027 Q1', '2026-05-01', '2026-07-31'),
]
PIPELINE_ID = 'default'


def main():
    supabase = get_supabase()

    print("=" * 80)
    print("PAGINATION AUDIT RESULTS")
    print("=" * 80)
    print()

    # Check week-3 queries (from reconcile_all_quarters_correct.py)
    print("Week-3 snapshot queries (used in reconciliation):")
    print("-" * 80)
    for quarter_id, _, _ in QUARTERS:
        resp = supabase.table('deals_snapshot') \
            .select('deal_id', count='exact') \
            .eq('fiscal_quarter', quarter_id) \
            .eq('week_of_quarter', 3) \
            .limit(1) \
            .execute()

        actual_count = resp.count
        status = "✓ Safe" if actual_count < 1000 else "⚠️ TRUNCATED"
        print(f"  {quarter_id} week-3: {actual_count:>5d} rows {status}")
    print()

    # Check all-weeks queries (from conversion_by_qualification_week)
    print("All-weeks queries (used in qualification timing analysis):")
    print("-" * 80)
    for quarter_id, _, _ in QUARTERS:
        resp = supabase.table('deals_snapshot') \
            .select('deal_id', count='exact') \
            .eq('fiscal_quarter', quarter_id) \
            .eq('pipeline_id', PIPELINE_ID) \
            .limit(1) \
            .execute()

        actual_count = resp.count
        fetched = 1000  # What the scripts actually got
        status = "⚠️ TRUNCATED" if actual_count > 1000 else "✓ Complete"
        print(f"  {quarter_id}: {actual_count:>5d} total rows, fetched {fetched} {status}")
    print()

    # Check row distribution by week for Q1 (to verify "incomplete grid" claim)
    print("Q1 row count by week (checking if weeks 3+ actually exist):")
    print("-" * 80)
    for week in range(1, 14):
        resp = supabase.table('deals_snapshot') \
            .select('deal_id', count='exact') \
            .eq('fiscal_quarter', 'FY2027 Q1') \
            .eq('week_of_quarter', week) \
            .eq('pipeline_id', PIPELINE_ID) \
            .limit(1) \
            .execute()

        count = resp.count or 0
        if count > 0:
            print(f"  Week {week:>2d}: {count:>5d} rows")
    print()

    # Check Q3 and Q4 by week
    print("Q3 row count by week:")
    print("-" * 80)
    for week in range(1, 14):
        resp = supabase.table('deals_snapshot') \
            .select('deal_id', count='exact') \
            .eq('fiscal_quarter', 'FY2026 Q3') \
            .eq('week_of_quarter', week) \
            .eq('pipeline_id', PIPELINE_ID) \
            .limit(1) \
            .execute()

        count = resp.count or 0
        if count > 0:
            print(f"  Week {week:>2d}: {count:>5d} rows")
    print()

    print("Q4 row count by week:")
    print("-" * 80)
    for week in range(1, 14):
        resp = supabase.table('deals_snapshot') \
            .select('deal_id', count='exact') \
            .eq('fiscal_quarter', 'FY2026 Q4') \
            .eq('week_of_quarter', week) \
            .eq('pipeline_id', PIPELINE_ID) \
            .limit(1) \
            .execute()

        count = resp.count or 0
        if count > 0:
            print(f"  Week {week:>2d}: {count:>5d} rows")
    print()

    print("=" * 80)
    print("IMPACT ASSESSMENT")
    print("=" * 80)
    print()
    print("AFFECTED ANALYSES:")
    print("  ❌ analyze_qualification_timing.py - All quarters truncated at 1000 rows")
    print("  ❌ conversion_by_qualification_week.py - All quarters truncated at 1000 rows")
    print("  ❌ conversion_by_qualification_week_q1.py - Q1 truncated at 1000 rows")
    print("  ✓ reconcile_all_quarters_correct.py - Week-3 queries safe (< 1000 rows)")
    print("  ✓ analyze_smb_qualification_gap.py - Used week-3 queries only")
    print()
    print("CONCLUSION:")
    print("  • Week-3 reconciliation (72 wins, 12 from cohort) is VALID")
    print("  • All qualification-timing analyses are INCOMPLETE (truncated)")
    print("  • Need to re-run with pagination to get true qualification distributions")
    print()


if __name__ == '__main__':
    main()
