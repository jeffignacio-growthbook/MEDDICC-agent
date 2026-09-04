#!/usr/bin/env python3
"""
Verify Data Quality Exclusions Table

Run after applying migration 053 to confirm:
1. Table exists
2. All 8 deals are present
3. Queries correctly exclude these deals
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent))

from api.db import get_supabase
from api.field_semantics import is_won


EXPECTED_EXCLUSIONS = [
    ('5790911698', 'Make', 'NEGATIVE_CYCLE', -41),
    ('5681417580', 'Quizlet', 'NEGATIVE_CYCLE', -41),
    ('5755377954', 'BESTSECRET', 'NEGATIVE_CYCLE', -13),
    ('5369635703', 'Bluesky', 'ZERO_DAY_CYCLE', 0),
    ('6212201883', 'Bluesky', 'ZERO_DAY_CYCLE', 0),
    ('6089749648', 'LeoVegas', 'ZERO_DAY_CYCLE', 0),
    ('5401072420', 'Quizlet', 'ZERO_DAY_CYCLE', 0),
    ('6023407620', 'knowunity.ai', 'ZERO_DAY_CYCLE', 0),
]


def main():
    supabase = get_supabase()

    print("=" * 80)
    print("DATA QUALITY EXCLUSIONS VERIFICATION")
    print("=" * 80)
    print()

    # Step 1: Check table exists
    print("Step 1: Checking if data_quality_exclusions table exists...")
    try:
        result = supabase.table('data_quality_exclusions') \
            .select('deal_id', count='exact') \
            .limit(1) \
            .execute()
        print(f"✓ Table exists with {result.count} rows")
    except Exception as e:
        print(f"✗ Table not found: {e}")
        print()
        print("Please apply migration 053 first:")
        print("  scripts/migrations/053_add_data_quality_exclusions.sql")
        return

    print()

    # Step 2: Verify all 8 deals are present
    print("Step 2: Verifying all 8 expected deals are present...")
    result = supabase.table('data_quality_exclusions') \
        .select('deal_id, company_name, reason, cycle_days') \
        .execute()

    exclusions = result.data
    exclusion_ids = {exc['deal_id'] for exc in exclusions}

    missing = []
    for deal_id, company, reason, cycle_days in EXPECTED_EXCLUSIONS:
        if deal_id not in exclusion_ids:
            missing.append((deal_id, company, reason))

    if missing:
        print(f"✗ Missing {len(missing)} expected deals:")
        for deal_id, company, reason in missing:
            print(f"  - {company} ({deal_id}): {reason}")
    else:
        print(f"✓ All 8 expected deals present")

    print()

    # Step 3: Check for unexpected deals
    expected_ids = {deal_id for deal_id, _, _, _ in EXPECTED_EXCLUSIONS}
    unexpected = [exc for exc in exclusions if exc['deal_id'] not in expected_ids]

    if unexpected:
        print(f"⚠️  {len(unexpected)} unexpected deals in exclusions table:")
        for exc in unexpected:
            print(f"  - {exc['company_name']} ({exc['deal_id']}): {exc['reason']}")
    else:
        print("✓ No unexpected deals (only the 8 documented ones)")

    print()

    # Step 4: Print full table
    print()
    print("=" * 80)
    print(f"COMPLETE EXCLUSIONS TABLE ({len(exclusions)} deals)")
    print("=" * 80)
    print()

    print(f"{'Company':25s} | {'Deal ID':10s} | {'Reason':18s} | {'Cycle Days':>5s}")
    print("-" * 75)

    for exc in sorted(exclusions, key=lambda x: (x['reason'], x.get('cycle_days', 999), x['company_name'])):
        company = (exc['company_name'] or 'Unknown')[:23]
        deal_id = exc['deal_id'][:10]
        reason = exc['reason'][:16]
        cycle = str(exc['cycle_days']) if exc['cycle_days'] is not None else 'NULL'

        print(f"{company:25s} | {deal_id:10s} | {reason:18s} | {cycle:>5s}")

    print()

    # Step 5: Test exclusion in real query
    print()
    print("=" * 80)
    print("IMPACT TEST: Wins with vs without exclusions")
    print("=" * 80)
    print()

    FISCAL_QUARTERS = [
        ('FY2026 Q3', '2025-11-01', '2026-01-31'),
        ('FY2026 Q4', '2026-02-01', '2026-04-30'),
        ('FY2027 Q1', '2026-05-01', '2026-07-31'),
    ]

    excluded_ids = [exc['deal_id'] for exc in exclusions]

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        # Count all wins
        all_wins_resp = supabase.table('deals') \
            .select('deal_id', count='exact') \
            .eq('pipeline_id', 'default') \
            .gte('close_date', start_date) \
            .lte('close_date', end_date) \
            .execute()

        all_wins = [d for d in all_wins_resp.data if is_won(str(supabase.table('deals').select('stage').eq('deal_id', d['deal_id']).execute().data[0].get('stage', '')))]
        all_wins_count = len(all_wins)

        # Count wins excluding data quality issues
        clean_wins = [w for w in all_wins if w['deal_id'] not in excluded_ids]
        clean_wins_count = len(clean_wins)

        excluded_in_quarter = all_wins_count - clean_wins_count

        print(f"{quarter_id}:")
        print(f"  All wins: {all_wins_count}")
        print(f"  Clean wins: {clean_wins_count}")
        print(f"  Excluded: {excluded_in_quarter}")
        print()

    print()
    print("=" * 80)
    print("VERIFICATION COMPLETE")
    print("=" * 80)
    print()

    if not missing and len(exclusions) == len(EXPECTED_EXCLUSIONS):
        print("✓ Data quality exclusions table is correctly configured")
        print()
        print("Usage in queries:")
        print("  WHERE deal_id NOT IN (SELECT deal_id FROM data_quality_exclusions)")
    else:
        print("⚠️  Issues found - see details above")


if __name__ == '__main__':
    main()
