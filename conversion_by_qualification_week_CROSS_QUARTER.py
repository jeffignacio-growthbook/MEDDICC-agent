#!/usr/bin/env python3
"""
Conversion Rate by Qualification Week - With Cross-Quarter Support

Enhanced version that captures carry-over deals (created in prior quarter,
closed in analyzed quarter) by checking prior quarter snapshots.

Fixes: 3 carry-over deals previously excluded from conversion_rate_prospective.
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
from scripts.analytics.cross_quarter_qualification import find_qualification_week_cross_quarter
from scripts.utils.pagination import fetch_all_rows_by_filters
from api.field_semantics import is_won
from api.db import get_supabase


FISCAL_QUARTERS = [
    ('FY2026 Q3', '2025-11-01', '2026-01-31'),
    ('FY2026 Q4', '2026-02-01', '2026-04-30'),
    ('FY2027 Q1', '2026-05-01', '2026-07-31'),
]

PIPELINE_ID = 'default'


def main():
    supabase = get_supabase()
    excluded_pipelines, stage_cfg = load_scope_config()

    print("=" * 80)
    print("CONVERSION RATE BY QUALIFICATION WEEK (Cross-Quarter Enabled)")
    print("=" * 80)
    print()

    all_qualified = []
    all_wins = []

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        print(f"\n{quarter_id} ({start_date} to {end_date})")
        print("-" * 80)

        # Get all snapshots for this quarter using pagination
        snapshots = fetch_all_rows_by_filters(
            supabase,
            'deals_snapshot',
            'deal_id, week_of_quarter, stage_id, pipeline_id',
            eq={'fiscal_quarter': quarter_id, 'pipeline_id': PIPELINE_ID}
        )

        print(f"  Snapshots retrieved: {len(snapshots)}")

        # Group by deal_id and find first qualified week
        snapshots_by_deal = defaultdict(list)
        for snap in snapshots:
            snapshots_by_deal[str(snap['deal_id'])].append(snap)

        deal_qualification_weeks = {}
        deal_qualification_quarters = {}

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
                    deal_qualification_quarters[deal_id] = quarter_id
                    break

        print(f"  Deals qualified in {quarter_id}: {len(deal_qualification_weeks)}")

        # Get current state of all qualified deals
        if deal_qualification_weeks:
            deal_ids = list(deal_qualification_weeks.keys())
            deals_resp = supabase.table('deals') \
                .select('deal_id, stage, close_date, create_date, company_name') \
                .in_('deal_id', deal_ids) \
                .execute()

            for deal in deals_resp.data:
                deal_id = str(deal['deal_id'])
                stage = deal.get('stage')
                close_date = deal.get('close_date')
                create_date = deal.get('create_date')

                qualification_week = deal_qualification_weeks[deal_id]
                qualification_quarter = deal_qualification_quarters[deal_id]

                # Add to qualified deals
                all_qualified.append({
                    'deal_id': deal_id,
                    'company_name': deal.get('company_name'),
                    'qualification_week': qualification_week,
                    'qualification_quarter': qualification_quarter,
                    'close_quarter': quarter_id,
                    'stage': stage,
                    'close_date': close_date,
                    'create_date': create_date
                })

                # Check if won in-quarter
                if stage and is_won(str(stage)):
                    if close_date and start_date <= close_date <= end_date:
                        all_wins.append({
                            'deal_id': deal_id,
                            'company_name': deal.get('company_name'),
                            'qualification_week': qualification_week,
                            'qualification_quarter': qualification_quarter,
                            'close_quarter': quarter_id,
                            'close_date': close_date,
                            'create_date': create_date
                        })

        # CROSS-QUARTER LOOKUP: Check for carry-over wins
        # (deals closed in this quarter but created before it started)
        print(f"\n  Checking for carry-over deals...")

        wins_in_quarter_resp = supabase.table('deals') \
            .select('deal_id, stage, close_date, create_date, company_name') \
            .eq('pipeline_id', PIPELINE_ID) \
            .gte('close_date', start_date) \
            .lte('close_date', end_date) \
            .execute()

        carry_over_count = 0
        carry_over_qualified_count = 0

        for deal in wins_in_quarter_resp.data:
            stage = deal.get('stage')
            if not stage or not is_won(str(stage)):
                continue

            deal_id = str(deal['deal_id'])

            # Skip if already captured
            if deal_id in deal_qualification_weeks:
                continue

            create_date = deal.get('create_date')
            close_date = deal.get('close_date')

            if not create_date or not close_date:
                continue

            # Check if created before quarter start (carry-over candidate)
            if create_date < start_date:
                carry_over_count += 1

                # Use cross-quarter lookup
                result = find_qualification_week_cross_quarter(
                    supabase,
                    deal_id,
                    create_date,
                    close_date,
                    quarter_id,
                    excluded_pipelines,
                    stage_cfg
                )

                if result:
                    qualification_week, qualification_quarter = result
                    carry_over_qualified_count += 1

                    print(f"    ✓ {deal.get('company_name')}: qualified in {qualification_quarter} week {qualification_week}")

                    # Add to qualified deals
                    all_qualified.append({
                        'deal_id': deal_id,
                        'company_name': deal.get('company_name'),
                        'qualification_week': qualification_week,
                        'qualification_quarter': qualification_quarter,
                        'close_quarter': quarter_id,
                        'stage': stage,
                        'close_date': close_date,
                        'create_date': create_date
                    })

                    # Add to wins
                    all_wins.append({
                        'deal_id': deal_id,
                        'company_name': deal.get('company_name'),
                        'qualification_week': qualification_week,
                        'qualification_quarter': qualification_quarter,
                        'close_quarter': quarter_id,
                        'close_date': close_date,
                        'create_date': create_date
                    })

        print(f"  Carry-over deals checked: {carry_over_count}")
        print(f"  Carry-over deals qualified: {carry_over_qualified_count}")

    # Calculate conversion by qualification week
    print()
    print("=" * 80)
    print("CONVERSION BY QUALIFICATION WEEK (All Quarters Combined)")
    print("=" * 80)
    print()

    by_week = defaultdict(lambda: {'qualified': 0, 'won': 0})

    for deal in all_qualified:
        week = deal['qualification_week']
        by_week[week]['qualified'] += 1

    for win in all_wins:
        week = win['qualification_week']
        by_week[week]['won'] += 1

    print(f"{'Week':>4s} | {'Qualified':>10s} | {'Won':>5s} | {'Rate':>7s}")
    print("-" * 40)

    total_qualified = 0
    total_won = 0

    for week in sorted(by_week.keys()):
        qualified = by_week[week]['qualified']
        won = by_week[week]['won']
        rate = won / qualified if qualified > 0 else 0

        total_qualified += qualified
        total_won += won

        print(f"{week:>4d} | {qualified:>10d} | {won:>5d} | {rate:>6.1%}")

    print("-" * 40)
    blended_rate = total_won / total_qualified if total_qualified > 0 else 0
    print(f"{'ALL':>4s} | {total_qualified:>10d} | {total_won:>5d} | {blended_rate:>6.1%}")

    print()
    print(f"Total qualified deals: {total_qualified}")
    print(f"Total wins: {total_won}")
    print(f"Blended conversion rate: {blended_rate:.1%}")

    # Compare to previous version
    print()
    print("=" * 80)
    print("COMPARISON TO PREVIOUS VERSION")
    print("=" * 80)
    print()

    print("Previous (without cross-quarter lookup):")
    print("  Qualified: 376")
    print("  Won: 27")
    print("  Rate: 7.2%")
    print()

    print("Current (with cross-quarter lookup):")
    print(f"  Qualified: {total_qualified}")
    print(f"  Won: {total_won}")
    print(f"  Rate: {blended_rate:.1%}")
    print()

    added_qualified = total_qualified - 376
    added_won = total_won - 27

    print(f"Change:")
    print(f"  Qualified: +{added_qualified} deals")
    print(f"  Won: +{added_won} deals")
    print(f"  Expected: +3 wins from carry-over (Fellow, Yeet!, Wellhub)")
    print()

    if added_won == 3:
        print("✓ Cross-quarter lookup working correctly - captured all 3 carry-over deals")
    else:
        print(f"⚠️  Expected +3 wins, got +{added_won}")


if __name__ == '__main__':
    main()
