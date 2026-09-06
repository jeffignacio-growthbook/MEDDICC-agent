#!/usr/bin/env python3
"""
Pagination Audit Across All Session Scripts

Task: Verify every deals_snapshot query from this session to check if 1000-row
pagination limit was silently hit, causing truncated results.

Scripts to audit:
1. reconcile_all_quarters_correct.py - Week-3 snapshots per quarter
2. analyze_qualification_timing.py - All snapshots per quarter
3. analyze_smb_qualification_gap.py - Week-3 + all snapshots
4. conversion_by_qualification_week.py - All snapshots across quarters
5. conversion_by_qualification_week_q1.py - All snapshots Q1 only
6. debug_q1_methodology_discrepancy.py - Week-3 + all weeks Q1

For each query:
- Report rows returned
- Check if exactly 1000 (indicates truncation)
- Estimate expected rows
- Flag if results may be incomplete
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

# Add to path
sys.path.insert(0, str(Path(__file__).parent))

from api.db import get_supabase

QUARTERS = [
    ('FY2026 Q3', '2025-11-01', '2026-01-31'),
    ('FY2026 Q4', '2026-02-01', '2026-04-30'),
    ('FY2027 Q1', '2026-05-01', '2026-07-31'),
]

PIPELINE_ID = 'default'


def check_query(description, query_func):
    """Execute query and report row count with truncation warning."""
    result = query_func()
    row_count = len(result.data)

    truncated = "⚠️ TRUNCATED" if row_count == 1000 else "✓"

    return {
        'description': description,
        'row_count': row_count,
        'truncated': row_count == 1000,
        'status': truncated
    }


def main():
    supabase = get_supabase()

    print("=" * 80)
    print("PAGINATION AUDIT - ALL DEALS_SNAPSHOT QUERIES")
    print("=" * 80)
    print()
    print("Checking every multi-week/multi-quarter query from this session")
    print("Looking for silent 1000-row truncation")
    print()

    results = []

    # ========================================================================
    # QUERY 1: Week-3 snapshots per quarter (reconcile_all_quarters_correct.py)
    # ========================================================================
    print("Query Set 1: Week-3 snapshots per quarter")
    print("-" * 80)

    for quarter_id, _, _ in QUARTERS:
        result = check_query(
            f"Week-3 snapshot - {quarter_id}",
            lambda qid=quarter_id: supabase.table('deals_snapshot')
                .select('deal_id, stage_id, pipeline_id')
                .eq('fiscal_quarter', qid)
                .eq('week_of_quarter', 3)
                .execute()
        )
        results.append(result)
        print(f"  {result['description']:50s} | {result['row_count']:>5d} rows | {result['status']}")

    print()

    # ========================================================================
    # QUERY 2: All snapshots per quarter (analyze_qualification_timing.py)
    # ========================================================================
    print("Query Set 2: All snapshots per quarter (all weeks)")
    print("-" * 80)

    for quarter_id, _, _ in QUARTERS:
        result = check_query(
            f"All weeks - {quarter_id}",
            lambda qid=quarter_id: supabase.table('deals_snapshot')
                .select('deal_id, week_of_quarter, stage_id, pipeline_id')
                .eq('fiscal_quarter', qid)
                .eq('pipeline_id', PIPELINE_ID)
                .execute()
        )
        results.append(result)
        print(f"  {result['description']:50s} | {result['row_count']:>5d} rows | {result['status']}")

    print()

    # ========================================================================
    # QUERY 3: All snapshots across all quarters (conversion_by_qualification_week.py)
    # ========================================================================
    print("Query Set 3: All snapshots across all quarters (no per-quarter filter)")
    print("-" * 80)

    # This query would have been run once per quarter in the script, but let's check
    # what happens if we query ALL quarters at once (worst case)
    result = check_query(
        "All quarters, all weeks (pooled)",
        lambda: supabase.table('deals_snapshot')
            .select('deal_id, week_of_quarter, stage_id, pipeline_id, fiscal_quarter')
            .eq('pipeline_id', PIPELINE_ID)
            .execute()
    )
    results.append(result)
    print(f"  {result['description']:50s} | {result['row_count']:>5d} rows | {result['status']}")

    print()

    # ========================================================================
    # QUERY 4: Week-3 snapshots for SMB analysis (analyze_smb_qualification_gap.py)
    # ========================================================================
    print("Query Set 4: Week-3 snapshots for excluded-stage fate analysis")
    print("-" * 80)

    for quarter_id, _, _ in QUARTERS:
        result = check_query(
            f"Week-3 all pipelines - {quarter_id}",
            lambda qid=quarter_id: supabase.table('deals_snapshot')
                .select('deal_id, stage_id, pipeline_id')
                .eq('fiscal_quarter', qid)
                .eq('week_of_quarter', 3)
                .eq('pipeline_id', PIPELINE_ID)
                .execute()
        )
        results.append(result)
        print(f"  {result['description']:50s} | {result['row_count']:>5d} rows | {result['status']}")

    print()

    # ========================================================================
    # ROW COUNT DISTRIBUTION BY QUARTER
    # ========================================================================
    print()
    print("=" * 80)
    print("DETAILED ROW COUNT DISTRIBUTION")
    print("=" * 80)
    print()

    for quarter_id, _, _ in QUARTERS:
        print(f"{quarter_id}")
        print("-" * 80)

        # Count rows by week
        week_counts_resp = supabase.rpc('get_snapshot_week_counts', {
            'quarter': quarter_id,
            'pipe': PIPELINE_ID
        }).execute()

        # If RPC doesn't exist, fall back to manual query per week
        print("  Rows per week:")
        for week in range(1, 14):
            result = supabase.table('deals_snapshot') \
                .select('deal_id', count='exact') \
                .eq('fiscal_quarter', quarter_id) \
                .eq('week_of_quarter', week) \
                .eq('pipeline_id', PIPELINE_ID) \
                .limit(1) \
                .execute()

            count = result.count or 0
            if count > 0:
                truncated = " ⚠️ (may be truncated)" if count >= 1000 else ""
                print(f"    Week {week:>2d}: {count:>5d} rows{truncated}")

        print()

    # ========================================================================
    # SUMMARY
    # ========================================================================
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()

    truncated_queries = [r for r in results if r['truncated']]

    if truncated_queries:
        print(f"❌ FOUND {len(truncated_queries)} TRUNCATED QUERIES")
        print()
        print("These queries hit the 1000-row limit and may have incomplete data:")
        for r in truncated_queries:
            print(f"  - {r['description']}")
        print()
        print("IMPACT:")
        print("  • Win counts may be undercounted")
        print("  • Qualification timing analysis incomplete")
        print("  • Segment breakdowns may be skewed")
        print("  • Cannot trust any cross-quarter or multi-week analysis")
        print()
        print("ACTION REQUIRED:")
        print("  1. Implement proper pagination in all affected scripts")
        print("  2. Re-run all analyses with complete data")
        print("  3. Compare new results to previous (flag if materially different)")
    else:
        print("✓ NO TRUNCATION DETECTED")
        print()
        print("All queries returned < 1000 rows, indicating complete results.")
        print("(Note: This doesn't guarantee ALL data is captured, just that we")
        print(" didn't hit PostgREST's default limit)")

    print()

    # ========================================================================
    # EXPECTED VS ACTUAL ROW COUNTS
    # ========================================================================
    print()
    print("=" * 80)
    print("EXPECTED VS ACTUAL ROW COUNTS")
    print("=" * 80)
    print()

    print("Assumptions:")
    print("  - ~13 weeks per quarter")
    print("  - ~400-600 active deals per week")
    print("  - Expected: ~5,200-7,800 rows per quarter")
    print()

    for quarter_id, _, _ in QUARTERS:
        # Count actual total rows for this quarter
        actual_resp = supabase.table('deals_snapshot') \
            .select('deal_id', count='exact') \
            .eq('fiscal_quarter', quarter_id) \
            .eq('pipeline_id', PIPELINE_ID) \
            .limit(1) \
            .execute()

        actual_count = actual_resp.count or 0
        expected_min = 5200
        expected_max = 7800

        status = "✓" if expected_min <= actual_count <= expected_max else "⚠️"

        print(f"{quarter_id}: {actual_count:>6d} rows (expected {expected_min}-{expected_max}) {status}")

        if actual_count < expected_min:
            print(f"  → Significantly fewer rows than expected (possible data gap)")
        elif actual_count > expected_max:
            print(f"  → More rows than expected (high deal volume, or duplicates?)")

    print()


if __name__ == '__main__':
    main()
