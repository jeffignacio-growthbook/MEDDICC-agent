#!/usr/bin/env python3
"""
Conversion Rate by Qualification Week - ALL QUARTERS (PAGINATION FIXED)

Run cohort-by-qualification-week analysis across Q3, Q4, and Q1 with proper pagination.
"""

import os
import sys
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent))

from scripts.analytics.point_in_time import is_deal_in_analytics_scope, load_scope_config
from api.field_semantics import is_won
from api.db import get_supabase


FISCAL_QUARTERS = [
    ('FY2026 Q3', '2025-11-01', '2026-01-31'),
    ('FY2026 Q4', '2026-02-01', '2026-04-30'),
    ('FY2027 Q1', '2026-05-01', '2026-07-31'),
]

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
    print("CONVERSION RATE BY QUALIFICATION WEEK - ALL QUARTERS (PAGINATION FIXED)")
    print("=" * 80)
    print()

    # Track aggregated cohorts across all quarters
    pooled_cohorts = defaultdict(lambda: {'qualified': [], 'won': []})
    quarter_summaries = []

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        print(f"{quarter_id}")
        print("-" * 80)

        # Get ALL snapshots with proper pagination
        snapshots = fetch_all_rows(
            supabase,
            'deals_snapshot',
            'deal_id, week_of_quarter, stage_id, pipeline_id',
            {
                'fiscal_quarter': quarter_id,
                'pipeline_id': PIPELINE_ID
            }
        )

        print(f"  Fetched {len(snapshots)} snapshot rows")

        # Group by deal_id
        snapshots_by_deal = defaultdict(list)
        for snap in snapshots:
            deal_id = str(snap['deal_id'])
            snapshots_by_deal[deal_id].append(snap)

        # Find first qualification week
        deal_qualification_weeks = {}

        for deal_id, deal_snaps in snapshots_by_deal.items():
            deal_snaps.sort(key=lambda x: x.get('week_of_quarter', 99))

            for snap in deal_snaps:
                if is_deal_in_analytics_scope(
                    stage_at_date=snap.get('stage_id'),
                    pipeline_id=snap.get('pipeline_id'),
                    excluded_pipelines=excluded_pipelines,
                    stage_cfg=stage_cfg
                ):
                    deal_qualification_weeks[deal_id] = snap.get('week_of_quarter')
                    break

        print(f"  Found {len(deal_qualification_weeks)} deals with qualification weeks")

        # Get current status
        deal_ids = list(deal_qualification_weeks.keys())

        if not deal_ids:
            print(f"  No qualified deals in {quarter_id}")
            print()
            continue

        # Batch query deals
        batch_size = 1000
        all_deals = []

        for i in range(0, len(deal_ids), batch_size):
            batch = deal_ids[i:i+batch_size]
            deals_resp = supabase.table('deals') \
                .select('deal_id, stage, close_date') \
                .in_('deal_id', batch) \
                .execute()
            all_deals.extend(deals_resp.data)

        # Build cohorts
        quarter_cohorts = defaultdict(lambda: {'qualified': [], 'won': []})

        for deal in all_deals:
            deal_id = str(deal['deal_id'])
            qual_week = deal_qualification_weeks.get(deal_id)

            if qual_week is None:
                continue

            quarter_cohorts[qual_week]['qualified'].append(deal_id)
            pooled_cohorts[qual_week]['qualified'].append(deal_id)

            stage = deal.get('stage')
            close_date = deal.get('close_date')

            if stage and is_won(str(stage)):
                if close_date and start_date <= close_date <= end_date:
                    quarter_cohorts[qual_week]['won'].append(deal_id)
                    pooled_cohorts[qual_week]['won'].append(deal_id)

        # Quarter summary
        total_qualified = sum(len(d['qualified']) for d in quarter_cohorts.values())
        total_won = sum(len(d['won']) for d in quarter_cohorts.values())
        overall_rate = total_won / total_qualified if total_qualified > 0 else 0

        print(f"  Total: {total_qualified} qualified, {total_won} wins ({overall_rate:.1%})")

        # Check week-3 specifically
        week3_data = quarter_cohorts.get(3, {'qualified': [], 'won': []})
        week3_q = len(week3_data['qualified'])
        week3_w = len(week3_data['won'])
        print(f"  Week-3: {week3_q} qualified, {week3_w} wins")

        quarter_summaries.append({
            'quarter': quarter_id,
            'total_qualified': total_qualified,
            'total_won': total_won,
            'rate': overall_rate,
            'week3_qualified': week3_q,
            'week3_won': week3_w
        })

        print()

    # POOLED RESULTS
    print()
    print("=" * 80)
    print("POOLED RESULTS ACROSS ALL QUARTERS")
    print("=" * 80)
    print()

    print(f"{'Qual Week':>10s} | {'Qualified':>10s} | {'Won':>10s} | {'Rate':>10s} | {'Confidence':>12s}")
    print("-" * 80)

    max_week = max(pooled_cohorts.keys()) if pooled_cohorts else 0

    for week in range(1, max_week + 1):
        data = pooled_cohorts.get(week, {'qualified': [], 'won': []})
        qualified = len(data['qualified'])
        won = len(data['won'])
        rate = won / qualified if qualified > 0 else 0

        confidence = "✓" if qualified >= 10 else "⚠ low n" if qualified > 0 else ""

        marker = " ← ORIGINAL CUTOFF" if week == 3 else ""
        print(f"Week {week:>5d} | {qualified:>10d} | {won:>10d} | {rate:>9.1%} | {confidence:<12s}{marker}")

    print("-" * 80)
    total_qualified = sum(len(d['qualified']) for d in pooled_cohorts.values())
    total_won = sum(len(d['won']) for d in pooled_cohorts.values())
    overall_rate = total_won / total_qualified if total_qualified > 0 else 0

    print(f"{'TOTAL':>10s} | {total_qualified:>10d} | {total_won:>10d} | {overall_rate:>9.1%} |")

    print()
    print("=" * 80)
    print("COMPARISON TO RECONCILED WIN COUNTS")
    print("=" * 80)
    print()
    print("From reconcile_all_quarters_correct.py (VALID):")
    print("  Q3: 21 total wins, 3 from week-3 cohort")
    print("  Q4: 22 total wins, 4 from week-3 cohort")
    print("  Q1: 29 total wins, 5 from week-3 cohort")
    print("  Total: 72 wins, 12 from week-3 (16.7%)")
    print()
    print("From this analysis (qualification-week method):")
    for summary in quarter_summaries:
        print(f"  {summary['quarter']}: {summary['total_won']} wins captured in cohorts")
    print(f"  Total: {total_won} wins captured")
    print()

    reconciled_total_wins = 72
    missing_wins = reconciled_total_wins - total_won
    missing_pct = missing_wins / reconciled_total_wins * 100 if reconciled_total_wins > 0 else 0

    print(f"Missing wins: {missing_wins} ({missing_pct:.1f}%)")
    print()
    print("These wins either:")
    print("  1. Never qualified in any snapshot week (entered pipeline late)")
    print("  2. Qualified after week 13 (end of quarter snapshots)")
    print("  3. Data quality issue (qualified but not captured in snapshots)")
    print()


if __name__ == '__main__':
    main()
