#!/usr/bin/env python3
"""
Conversion Rate by Qualification Week - Q1 Only (PAGINATION FIXED)

CRITICAL FIX: Previous version hit 1000-row PostgREST limit, missing 82% of data.
This version uses proper pagination to fetch all 5,697 Q1 snapshot rows.

Methodology: Track cohorts by when they qualify, not fixed calendar week.

Scope: FY2027 Q1 (complete snapshot weeks 1-13, 5,697 rows total)

For each deal in Q1:
- Find week-of-quarter when it FIRST reached qualified stage
- Group ALL deals (won and not-won) by qualification week
- Compute conversion rate per bucket (won / qualified in that week)

Output: Table showing qualification week vs conversion rate
"""

import os
import sys
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv

# Load environment
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

# Add to path
sys.path.insert(0, str(Path(__file__).parent))

from scripts.analytics.point_in_time import is_deal_in_analytics_scope, load_scope_config
from api.field_semantics import is_won
from api.db import get_supabase


QUARTER_ID = 'FY2027 Q1'
START_DATE = '2026-05-01'
END_DATE = '2026-07-31'
PIPELINE_ID = 'default'


def fetch_all_rows(supabase, table, select_cols, filters, page_size=1000):
    """Fetch all rows with pagination."""
    all_rows = []
    offset = 0

    while True:
        query = supabase.table(table).select(select_cols)

        for col, val in filters.items():
            query = query.eq(col, val)

        result = query.range(offset, offset + page_size - 1).execute()
        rows = result.data
        all_rows.extend(rows)

        if len(rows) < page_size:
            break

        offset += page_size

    return all_rows


def main():
    supabase = get_supabase()
    excluded_pipelines, stage_cfg = load_scope_config()

    print("=" * 80)
    print("CONVERSION RATE BY QUALIFICATION WEEK - Q1 (PAGINATION FIXED)")
    print("=" * 80)
    print()
    print("Scope: FY2027 Q1 (2026-05-01 to 2026-07-31)")
    print("       Complete snapshot weeks 1-13 available (5,697 rows)")
    print()
    print("Methodology: Cohort by week-of-quarter when deal FIRST qualified")
    print("Rate: % of each cohort that closed won in-quarter")
    print()

    # Track by qualification week
    cohorts = defaultdict(lambda: {'qualified': [], 'won': []})

    print(f"Processing {QUARTER_ID}...")

    # Get ALL snapshots for Q1 with proper pagination
    snapshots = fetch_all_rows(
        supabase,
        'deals_snapshot',
        'deal_id, week_of_quarter, stage_id, pipeline_id',
        {
            'fiscal_quarter': QUARTER_ID,
            'pipeline_id': PIPELINE_ID
        }
    )

    print(f"  Fetched {len(snapshots)} snapshot rows (with pagination)")

    # Group snapshots by deal_id
    snapshots_by_deal = defaultdict(list)
    for snap in snapshots:
        deal_id = str(snap['deal_id'])
        snapshots_by_deal[deal_id].append(snap)

    print(f"  Found {len(snapshots_by_deal)} unique deals in snapshots")

    # Find first qualification week for each deal
    deal_qualification_weeks = {}

    for deal_id, deal_snaps in snapshots_by_deal.items():
        # Sort by week
        deal_snaps.sort(key=lambda x: x.get('week_of_quarter', 99))

        # Find first week where deal was qualified
        for snap in deal_snaps:
            stage_id = snap.get('stage_id')
            pipeline_id = snap.get('pipeline_id')
            week = snap.get('week_of_quarter')

            if is_deal_in_analytics_scope(
                stage_at_date=stage_id,
                pipeline_id=pipeline_id,
                excluded_pipelines=excluded_pipelines,
                stage_cfg=stage_cfg
            ):
                deal_qualification_weeks[deal_id] = week
                break

    print(f"  Found {len(deal_qualification_weeks)} deals with qualification weeks")

    # Get current status for all these deals (with batching if > 1000)
    deal_ids = list(deal_qualification_weeks.keys())

    if not deal_ids:
        print("  No qualified deals found in Q1")
        return

    # Batch query deals table (supports up to 1000 per .in() call)
    batch_size = 1000
    all_deals = []

    for i in range(0, len(deal_ids), batch_size):
        batch = deal_ids[i:i+batch_size]

        deals_resp = supabase.table('deals') \
            .select('deal_id, stage, close_date, company_name') \
            .in_('deal_id', batch) \
            .execute()

        all_deals.extend(deals_resp.data)

    print(f"  Fetched current state for {len(all_deals)} deals")
    print()

    # Build cohorts
    for deal in all_deals:
        deal_id = str(deal['deal_id'])
        qual_week = deal_qualification_weeks.get(deal_id)

        if qual_week is None:
            continue

        # Add to qualified cohort
        cohorts[qual_week]['qualified'].append(deal_id)

        # Check if won in-quarter
        stage = deal.get('stage')
        close_date = deal.get('close_date')

        if stage and is_won(str(stage)):
            if close_date and START_DATE <= close_date <= END_DATE:
                cohorts[qual_week]['won'].append(deal_id)

    # OUTPUT: Table of qualification week vs conversion rate
    print()
    print("=" * 80)
    print("CONVERSION RATE BY QUALIFICATION WEEK")
    print("=" * 80)
    print()

    print(f"{'Qual Week':>10s} | {'Qualified':>10s} | {'Won':>10s} | {'Rate':>10s} | {'Confidence':>12s}")
    print("-" * 80)

    max_week = max(cohorts.keys()) if cohorts else 0
    cumulative_qualified = 0
    cumulative_won = 0

    for week in range(1, max_week + 1):
        data = cohorts.get(week, {'qualified': [], 'won': []})
        qualified = len(data['qualified'])
        won = len(data['won'])
        rate = won / qualified if qualified > 0 else 0

        cumulative_qualified += qualified
        cumulative_won += won

        confidence = "✓" if qualified >= 10 else "⚠ low n" if qualified > 0 else ""

        marker = " ← ORIGINAL CUTOFF" if week == 3 else ""
        print(f"Week {week:>5d} | {qualified:>10d} | {won:>10d} | {rate:>9.1%} | {confidence:<12s}{marker}")

    # Summary
    print("-" * 80)
    total_qualified = sum(len(d['qualified']) for d in cohorts.values())
    total_won = sum(len(d['won']) for d in cohorts.values())
    overall_rate = total_won / total_qualified if total_qualified > 0 else 0

    print(f"{'TOTAL':>10s} | {total_qualified:>10d} | {total_won:>10d} | {overall_rate:>9.1%} |")

    print()
    print("=" * 80)
    print("ANALYSIS")
    print("=" * 80)
    print()

    # Compute early vs late conversion
    early_weeks = [1, 2, 3, 4, 5]
    late_weeks = list(range(6, max_week + 1))

    early_qualified = sum(len(cohorts.get(w, {}).get('qualified', [])) for w in early_weeks)
    early_won = sum(len(cohorts.get(w, {}).get('won', [])) for w in early_weeks)
    early_rate = early_won / early_qualified if early_qualified > 0 else 0

    late_qualified = sum(len(cohorts.get(w, {}).get('qualified', [])) for w in late_weeks)
    late_won = sum(len(cohorts.get(w, {}).get('won', [])) for w in late_weeks)
    late_rate = late_won / late_qualified if late_qualified > 0 else 0

    print(f"Early qualification (weeks 1-5): {early_rate:.1%} ({early_won}/{early_qualified})")
    print(f"Late qualification (weeks 6+):  {late_rate:.1%} ({late_won}/{late_qualified})")
    print()

    if late_qualified > 0 and early_rate > late_rate * 1.5:
        print("✓ Clear decay curve: Early qualifiers convert at materially higher rate")
        print("  → Qualification timing is predictive of close probability")
    elif late_qualified > 0 and early_rate > late_rate:
        print("~ Modest decay: Early qualifiers convert somewhat higher")
    else:
        print("~ No clear decay: Qualification timing not strongly predictive")

    # Highlight week-3 specifically
    week3_data = cohorts.get(3, {'qualified': [], 'won': []})
    week3_qualified = len(week3_data['qualified'])
    week3_won = len(week3_data['won'])
    week3_rate = week3_won / week3_qualified if week3_qualified > 0 else 0

    print()
    print(f"Week-3 cohort (original methodology):")
    print(f"  Qualified: {week3_qualified}")
    print(f"  Won: {week3_won}")
    print(f"  Rate: {week3_rate:.1%}")
    print()

    # Calculate what % of total wins came from each qualification period
    if total_won > 0:
        early_win_share = early_won / total_won * 100
        late_win_share = late_won / total_won * 100
        week3_win_share = week3_won / total_won * 100

        print(f"Win distribution by qualification timing:")
        print(f"  Weeks 1-5: {early_won}/{total_won} wins ({early_win_share:.1f}%)")
        print(f"  Weeks 6+:  {late_won}/{total_won} wins ({late_win_share:.1f}%)")
        print(f"  Week 3 only: {week3_won}/{total_won} wins ({week3_win_share:.1f}%)")
        print()

        # Compare to week-3 snapshot methodology
        week3_snapshot_qualified = 76  # From reconciliation
        week3_snapshot_wins = 5

        print(f"Comparison to week-3 snapshot (cumulative):")
        print(f"  Snapshot method: {week3_snapshot_qualified} qualified, {week3_snapshot_wins} wins (6.6%)")
        print(f"  This method: {total_qualified} qualified across all weeks, {total_won} wins ({overall_rate:.1%})")
        print()

        weeks_1_to_3_qualified = sum(len(cohorts.get(w, {}).get('qualified', [])) for w in [1, 2, 3])
        weeks_1_to_3_won = sum(len(cohorts.get(w, {}).get('won', [])) for w in [1, 2, 3])

        print(f"  This method weeks 1-3 combined: {weeks_1_to_3_qualified} qualified, {weeks_1_to_3_won} wins")

        if weeks_1_to_3_qualified == week3_snapshot_qualified:
            print(f"  ✓ Reconciled: Incremental weeks 1-3 sum = cumulative week-3 snapshot")
        else:
            diff = week3_snapshot_qualified - weeks_1_to_3_qualified
            print(f"  ⚠️  Mismatch: {abs(diff)} deal difference (needs investigation)")

    print()
    print("=" * 80)
    print("PAGINATION FIX VERIFICATION")
    print("=" * 80)
    print()
    print("Previous version (BROKEN):")
    print("  Fetched: 1,000 rows (hit PostgREST limit)")
    print("  Found: 70 qualified deals")
    print("  Captured: 5 wins")
    print()
    print("This version (FIXED):")
    print(f"  Fetched: {len(snapshots)} rows (complete)")
    print(f"  Found: {len(deal_qualification_weeks)} qualified deals")
    print(f"  Captured: {total_won} wins")
    print()

    if len(snapshots) > 1000:
        print("✓ Pagination working: fetched > 1000 rows")
    else:
        print("⚠️  Check: fetched < 1000 rows (pagination may not be needed)")

    print()


if __name__ == '__main__':
    main()
