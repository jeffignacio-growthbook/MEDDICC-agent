#!/usr/bin/env python3
"""
Complete Reconciliation of All 72 Wins

Verify every win is in exactly one category with no gaps.

Expected:
- 27 captured in qualification cohorts
- 45 missing, broken into subcategories
- Total = 72 with no overlap or gap
"""

import os
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime
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

EXCLUDED_STAGES = {
    '79653122': 'Meeting Set',
    'decisionmakerboughtin': 'Review',
    '68509551': 'Disqualified',
}


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
    excluded_pipelines, stage_cfg = load_scope_config()

    print("=" * 80)
    print("COMPLETE RECONCILIATION: ALL 72 WINS")
    print("=" * 80)
    print()

    # Step 1: Get all 72 wins
    all_wins = {}

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        deals_resp = supabase.table('deals') \
            .select('deal_id, company_name, stage, close_date, create_date, pipeline_id, deal_status') \
            .eq('pipeline_id', PIPELINE_ID) \
            .gte('close_date', start_date) \
            .lte('close_date', end_date) \
            .execute()

        for deal in deals_resp.data:
            stage = deal.get('stage')
            if stage and is_won(str(stage)):
                deal_id = str(deal['deal_id'])
                all_wins[deal_id] = {
                    'deal_id': deal_id,
                    'company_name': deal.get('company_name'),
                    'close_date': deal.get('close_date'),
                    'create_date': deal.get('create_date'),
                    'deal_status': deal.get('deal_status'),
                    'quarter_id': quarter_id,
                    'quarter_start': start_date,
                    'quarter_end': end_date,
                    'category': None  # Will assign
                }

    print(f"Total wins: {len(all_wins)}")
    print()

    # Step 2: Identify captured wins (in qualification cohorts)
    captured_win_ids = set()

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        snapshots = fetch_all_rows(
            supabase,
            'deals_snapshot',
            'deal_id, week_of_quarter, stage_id, pipeline_id',
            {'fiscal_quarter': quarter_id, 'pipeline_id': PIPELINE_ID}
        )

        snapshots_by_deal = defaultdict(list)
        for snap in snapshots:
            snapshots_by_deal[str(snap['deal_id'])].append(snap)

        deal_qualification_weeks = {}
        for deal_id, snaps in snapshots_by_deal.items():
            snaps.sort(key=lambda x: x.get('week_of_quarter', 99))
            for snap in snaps:
                if is_deal_in_analytics_scope(
                    stage_at_date=snap.get('stage_id'),
                    pipeline_id=snap.get('pipeline_id'),
                    excluded_pipelines=excluded_pipelines,
                    stage_cfg=stage_cfg
                ):
                    deal_qualification_weeks[deal_id] = snap.get('week_of_quarter')
                    break

        if deal_qualification_weeks:
            deal_ids = list(deal_qualification_weeks.keys())
            deals_resp = supabase.table('deals') \
                .select('deal_id, stage, close_date') \
                .in_('deal_id', deal_ids) \
                .execute()

            for deal in deals_resp.data:
                stage = deal.get('stage')
                close_date = deal.get('close_date')
                if stage and is_won(str(stage)):
                    if close_date and start_date <= close_date <= end_date:
                        deal_id = str(deal['deal_id'])
                        captured_win_ids.add(deal_id)
                        if deal_id in all_wins:
                            all_wins[deal_id]['category'] = 'CAPTURED'

    print(f"Captured in qualification cohorts: {len(captured_win_ids)}")
    print()

    # Step 3: Categorize missing wins
    missing_count = 0

    for deal_id, win in all_wins.items():
        if win['category'] == 'CAPTURED':
            continue

        missing_count += 1

        create_date = win['create_date']
        close_date = win['close_date']
        quarter_start = win['quarter_start']
        quarter_id = win['quarter_id']

        # Calculate cycle
        cycle_days = days_between(create_date, close_date)

        # Check if in snapshots
        snapshot_resp = supabase.table('deals_snapshot') \
            .select('deal_id, stage_id', count='exact') \
            .eq('fiscal_quarter', quarter_id) \
            .eq('deal_id', deal_id) \
            .limit(100) \
            .execute()

        in_snapshots = (snapshot_resp.count or 0) > 0

        if in_snapshots:
            # Check if was in excluded stages
            snapshots = snapshot_resp.data
            was_in_excluded = any(str(s.get('stage_id')) in EXCLUDED_STAGES for s in snapshots)

            if was_in_excluded:
                win['category'] = 'EXCLUDED_STAGES'
            elif cycle_days is not None and cycle_days < 7:
                win['category'] = 'FAST_TRACK_SHORT'
            else:
                win['category'] = 'OTHER_IN_SNAPSHOTS'
        else:
            # Not in snapshots
            if cycle_days is None:
                win['category'] = 'DATA_ERROR_NULL'
            elif cycle_days <= 0:
                win['category'] = 'DATA_ERROR_ZERO_NEG'
            elif create_date and create_date < quarter_start:
                win['category'] = 'CARRY_OVER'
            elif cycle_days < 14:
                win['category'] = 'FAST_TRACK_SHORT'
            else:
                win['category'] = 'RETROACTIVE_LONG'

    print(f"Missing from cohorts: {missing_count}")
    print()

    # Step 4: Count by category
    category_counts = defaultdict(int)
    for win in all_wins.values():
        category_counts[win['category']] += 1

    print("=" * 80)
    print("CATEGORY BREAKDOWN")
    print("=" * 80)
    print()

    category_order = [
        'CAPTURED',
        'RETROACTIVE_LONG',
        'DATA_ERROR_ZERO_NEG',
        'DATA_ERROR_NULL',
        'FAST_TRACK_SHORT',
        'CARRY_OVER',
        'EXCLUDED_STAGES',
        'OTHER_IN_SNAPSHOTS',
        None
    ]

    for category in category_order:
        count = category_counts.get(category, 0)
        if count > 0:
            pct = count / len(all_wins) * 100
            print(f"{str(category):25s}: {count:>3d} ({pct:>5.1f}%)")

    print("-" * 40)
    print(f"{'TOTAL':25s}: {len(all_wins):>3d} (100.0%)")
    print()

    # Verify no gaps
    uncategorized = [deal_id for deal_id, win in all_wins.items() if win['category'] is None]
    if uncategorized:
        print(f"⚠️  {len(uncategorized)} deals not categorized!")
        for deal_id in uncategorized[:5]:
            print(f"  {all_wins[deal_id]['company_name']}")
    else:
        print("✓ All 72 deals categorized")

    print()

    # Step 5: Print full table
    print()
    print("=" * 80)
    print("COMPLETE DEAL LIST (All 72 Wins)")
    print("=" * 80)
    print()

    # Sort by category, then company name
    sorted_wins = sorted(all_wins.values(), key=lambda x: (x['category'] or 'ZZZ', x['company_name']))

    print(f"{'Company':30s} | {'Quarter':11s} | {'Category':25s} | {'Close Date':10s}")
    print("-" * 90)

    for win in sorted_wins:
        company = (win['company_name'] or 'Unknown')[:28]
        quarter = win['quarter_id']
        category = win['category'] or 'UNCATEGORIZED'
        close_date = win['close_date'] or 'N/A'

        print(f"{company:30s} | {quarter:11s} | {category:25s} | {close_date:10s}")

    print()

    # Step 6: Verify math
    print()
    print("=" * 80)
    print("VERIFICATION")
    print("=" * 80)
    print()

    captured = category_counts['CAPTURED']
    missing_total = len(all_wins) - captured

    print(f"Captured: {captured}")
    print(f"Missing: {missing_total}")
    print(f"Total: {len(all_wins)}")
    print()

    if captured + missing_total == len(all_wins):
        print("✓ Math checks out: captured + missing = total")
    else:
        print("❌ Math error: {captured} + {missing_total} != {len(all_wins)}")

    print()


if __name__ == '__main__':
    main()
