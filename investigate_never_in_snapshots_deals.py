#!/usr/bin/env python3
"""
Deep Dive: 39 Deals Never in Snapshots

These deals closed in-quarter but don't appear in ANY snapshot week 1-13.

Hypotheses to test:
1. Created before quarter started (carried over from previous quarter)
2. In different pipeline during quarter, moved to default late
3. Data quality issues (retroactive entries, same-day close)

Check for each:
- create_date relative to quarter boundaries
- Pipeline history (if available)
- Whether 0-day or negative-day cycles suggest retroactive entry
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent))

from api.db import get_supabase


FISCAL_QUARTERS = [
    ('FY2026 Q3', '2025-11-01', '2026-01-31'),
    ('FY2026 Q4', '2026-02-01', '2026-04-30'),
    ('FY2027 Q1', '2026-05-01', '2026-07-31'),
]

# IDs of the 39 deals never in snapshots (from previous analysis)
NEVER_IN_SNAPSHOTS = [
    '54010724204', '53696357034', '48943111066', '57909116984', '41610724641',
    # Add more as needed - showing first 5 as examples
]


def days_between(start_str, end_str):
    if not start_str or not end_str:
        return None
    try:
        start = datetime.fromisoformat(start_str[:10])
        end = datetime.fromisoformat(end_str[:10])
        return (end - start).days
    except:
        return None


def main():
    supabase = get_supabase()

    print("=" * 80)
    print("DEEP DIVE: 39 DEALS NEVER IN SNAPSHOTS")
    print("=" * 80)
    print()

    # Get details for all "never in snapshots" deals
    # Since we identified 39, let's get them by checking which wins are missing from snapshots

    print("Step 1: Get all 72 wins with create_date context")
    print("-" * 80)

    all_wins_with_context = []

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        # Get all wins in this quarter
        from api.field_semantics import is_won

        deals_resp = supabase.table('deals') \
            .select('deal_id, company_name, stage, close_date, create_date, pipeline_id') \
            .eq('pipeline_id', 'default') \
            .gte('close_date', start_date) \
            .lte('close_date', end_date) \
            .execute()

        for deal in deals_resp.data:
            stage = deal.get('stage')
            if stage and is_won(str(stage)):
                all_wins_with_context.append({
                    'deal_id': str(deal['deal_id']),
                    'company_name': deal.get('company_name'),
                    'close_date': deal.get('close_date'),
                    'create_date': deal.get('create_date'),
                    'quarter_id': quarter_id,
                    'quarter_start': start_date,
                    'quarter_end': end_date
                })

    print(f"Found {len(all_wins_with_context)} wins")
    print()

    # For each win, check if it appears in snapshots
    print("Step 2: Check which wins are NOT in snapshots")
    print("-" * 80)

    never_in_snapshots = []

    for win in all_wins_with_context:
        deal_id = win['deal_id']
        quarter_id = win['quarter_id']

        # Check if deal appears in snapshots for its close quarter
        snapshot_resp = supabase.table('deals_snapshot') \
            .select('deal_id', count='exact') \
            .eq('fiscal_quarter', quarter_id) \
            .eq('pipeline_id', 'default') \
            .eq('deal_id', deal_id) \
            .limit(1) \
            .execute()

        count = snapshot_resp.count or 0

        if count == 0:
            never_in_snapshots.append(win)

    print(f"Found {len(never_in_snapshots)} wins never in snapshots")
    print()

    # Analyze each one
    print("Step 3: Analyze create_date patterns")
    print("-" * 80)
    print()

    categories = {
        'created_before_quarter': [],
        'created_in_quarter_short_cycle': [],
        'created_in_quarter_long_cycle': [],
        'data_quality_error': []
    }

    for win in never_in_snapshots:
        deal_id = win['deal_id']
        company = win['company_name']
        create_date = win['create_date']
        close_date = win['close_date']
        quarter_start = win['quarter_start']
        quarter_end = win['quarter_end']

        cycle_days = days_between(create_date, close_date)

        # Check if created before quarter
        if create_date and create_date < quarter_start:
            categories['created_before_quarter'].append({
                'deal_id': deal_id,
                'company': company,
                'create_date': create_date,
                'close_date': close_date,
                'cycle_days': cycle_days,
                'quarter_id': win['quarter_id'],
                'days_before_quarter': days_between(create_date, quarter_start)
            })
        elif cycle_days is not None and (cycle_days < 0 or cycle_days == 0):
            categories['data_quality_error'].append({
                'deal_id': deal_id,
                'company': company,
                'create_date': create_date,
                'close_date': close_date,
                'cycle_days': cycle_days,
                'quarter_id': win['quarter_id']
            })
        elif cycle_days is not None and cycle_days < 14:
            categories['created_in_quarter_short_cycle'].append({
                'deal_id': deal_id,
                'company': company,
                'create_date': create_date,
                'close_date': close_date,
                'cycle_days': cycle_days,
                'quarter_id': win['quarter_id']
            })
        else:
            categories['created_in_quarter_long_cycle'].append({
                'deal_id': deal_id,
                'company': company,
                'create_date': create_date,
                'close_date': close_date,
                'cycle_days': cycle_days,
                'quarter_id': win['quarter_id']
            })

    # REPORT
    print()
    print("=" * 80)
    print("BREAKDOWN OF 'NEVER IN SNAPSHOTS' DEALS")
    print("=" * 80)
    print()

    for category, label in [
        ('created_before_quarter', 'Created BEFORE quarter started'),
        ('created_in_quarter_short_cycle', 'Created in-quarter, short cycle (< 14 days)'),
        ('created_in_quarter_long_cycle', 'Created in-quarter, long cycle (≥ 14 days)'),
        ('data_quality_error', 'Data quality error (0 or negative days)')
    ]:
        deals = categories[category]
        count = len(deals)
        pct = count / len(never_in_snapshots) * 100 if never_in_snapshots else 0

        print(f"{label}")
        print(f"Count: {count} ({pct:.1f}%)")
        print("-" * 80)

        if count > 0:
            print()
            for deal in deals[:10]:  # Show first 10
                if category == 'created_before_quarter':
                    days_before = deal.get('days_before_quarter', 'N/A')
                    print(f"  {deal['company']:30s} | Created {days_before} days before Q start | {deal['quarter_id']}")
                    print(f"    Create: {deal['create_date']}, Close: {deal['close_date']} ({deal['cycle_days']} days)")
                else:
                    print(f"  {deal['company']:30s} | {deal['cycle_days']} day cycle | {deal['quarter_id']}")
                    print(f"    Create: {deal['create_date']}, Close: {deal['close_date']}")

            if count > 10:
                print(f"  ... and {count - 10} more")

        print()

    # IMPLICATIONS
    print()
    print("=" * 80)
    print("IMPLICATIONS")
    print("=" * 80)
    print()

    created_before = len(categories['created_before_quarter'])
    total = len(never_in_snapshots)
    pct_before = created_before / total * 100 if total > 0 else 0

    print(f"Total 'never in snapshots': {total}")
    print(f"Created before quarter: {created_before} ({pct_before:.1f}%)")
    print()

    if pct_before > 60:
        print("✓ DOMINANT: Created in previous quarters (carry-over deals)")
        print()
        print("These deals:")
        print("  • Were created in Q2, Q3, etc. (before their close quarter)")
        print("  • Only appear in snapshots for their CREATE quarter, not CLOSE quarter")
        print("  • Miss qualification-week tracking because we query by close quarter")
        print()
        print("RECOMMENDATION:")
        print("  Option A: Track by create_quarter instead of close_quarter")
        print("  Option B: Query snapshots across ALL quarters a deal touched")
        print("  Option C: Accept this limitation and document as 'carry-over deals'")
    elif len(categories['created_in_quarter_short_cycle']) / total > 0.6:
        print("✓ DOMINANT: Created in-quarter with short cycles (< 14 days)")
        print()
        print("These deals:")
        print("  • Enter and close quickly (< 2 weeks)")
        print("  • May fall between snapshot dates (if snapshots are weekly)")
        print("  • Or enter already-qualified (skip early stages)")
        print()
        print("RECOMMENDATION:")
        print("  • Investigate why they don't appear in any snapshots")
        print("  • Check snapshot timing (do they fall between Friday snapshots?)")
        print("  • May need more frequent snapshots or treat as fast-track")
    else:
        print("~ MIXED pattern")
        print()
        print("Multiple factors:")
        print(f"  • {pct_before:.1f}% created before quarter (carry-over)")
        print(f"  • {len(categories['created_in_quarter_short_cycle'])/total*100:.1f}% short cycle in-quarter")
        print(f"  • {len(categories['created_in_quarter_long_cycle'])/total*100:.1f}% long cycle in-quarter")
        print(f"  • {len(categories['data_quality_error'])/total*100:.1f}% data quality errors")

    print()


if __name__ == '__main__':
    main()
