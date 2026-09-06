#!/usr/bin/env python3
"""
Correct Reconciliation - All Quarters

Fix pagination issue by using server-side filters BEFORE 1000-row limit.
Verify cohort-win-count ≤ total-win-count for every quarter.
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

from scripts.analytics.point_in_time import is_deal_in_analytics_scope, load_scope_config
from api.field_semantics import is_won
from api.db import get_supabase


FISCAL_QUARTERS = [
    ('FY2026 Q3', '2025-11-01', '2026-01-31'),
    ('FY2026 Q4', '2026-02-01', '2026-04-30'),
    ('FY2027 Q1', '2026-05-01', '2026-07-31'),
]

WEEK_OF_QUARTER = 3
PIPELINE_ID = 'default'


def main():
    supabase = get_supabase()
    excluded_pipelines, stage_cfg = load_scope_config()

    print("=" * 80)
    print("CORRECT RECONCILIATION - ALL QUARTERS")
    print("=" * 80)
    print()
    print("Using server-side filters to avoid pagination limit")
    print()

    grand_total_wins = 0
    grand_cohort_wins = 0

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        print(f"{quarter_id}")
        print("-" * 80)

        # TOTAL WINS: Use server-side filters
        total_wins_resp = supabase.table('deals') \
            .select('deal_id, company_name, stage, close_date') \
            .eq('pipeline_id', PIPELINE_ID) \
            .gte('close_date', start_date) \
            .lte('close_date', end_date) \
            .execute()

        total_win_ids = set()
        for deal in total_wins_resp.data:
            stage = deal.get('stage')
            if stage and is_won(str(stage)):
                total_win_ids.add(str(deal['deal_id']))

        print(f"Total wins: {len(total_win_ids)}")

        # COHORT WINS: From week-3 snapshot
        snapshot_resp = supabase.table('deals_snapshot') \
            .select('deal_id, stage_id, pipeline_id') \
            .eq('fiscal_quarter', quarter_id) \
            .eq('week_of_quarter', WEEK_OF_QUARTER) \
            .execute()

        # Filter to scoped deals in default pipeline
        scoped_deal_ids = []
        for row in snapshot_resp.data:
            if str(row.get('pipeline_id')) != PIPELINE_ID:
                continue

            if is_deal_in_analytics_scope(
                stage_at_date=row.get('stage_id'),
                pipeline_id=row.get('pipeline_id'),
                excluded_pipelines=excluded_pipelines,
                stage_cfg=stage_cfg
            ):
                scoped_deal_ids.append(str(row['deal_id']))

        if not scoped_deal_ids:
            print(f"Week-3 cohort: 0 deals")
            print(f"Cohort wins: 0")
            print()
            continue

        print(f"Week-3 cohort: {len(scoped_deal_ids)} qualified deals")

        # Get current state of cohort deals with server-side filter
        # Split into batches if needed (PostgREST .in() has limits)
        cohort_win_ids = set()
        batch_size = 100

        for i in range(0, len(scoped_deal_ids), batch_size):
            batch = scoped_deal_ids[i:i+batch_size]

            deals_resp = supabase.table('deals') \
                .select('deal_id, stage, close_date') \
                .in_('deal_id', batch) \
                .execute()

            for deal in deals_resp.data:
                deal_id = str(deal['deal_id'])
                stage = deal.get('stage')
                close_date = deal.get('close_date')

                if stage and is_won(str(stage)):
                    if close_date and start_date <= close_date <= end_date:
                        cohort_win_ids.add(deal_id)

        print(f"Cohort wins: {len(cohort_win_ids)}")

        # VERIFY
        if len(cohort_win_ids) > len(total_win_ids):
            print(f"❌ INVALID: {len(cohort_win_ids)} cohort > {len(total_win_ids)} total")
            return
        else:
            print(f"✓ Valid: {len(cohort_win_ids)} ≤ {len(total_win_ids)}")

        not_in_cohort = len(total_win_ids) - len(cohort_win_ids)
        pct_not_in_cohort = not_in_cohort / len(total_win_ids) * 100 if total_win_ids else 0
        print(f"Not in cohort: {not_in_cohort} ({pct_not_in_cohort:.1f}% qualified after week-3)")

        grand_total_wins += len(total_win_ids)
        grand_cohort_wins += len(cohort_win_ids)

        print()

    # SUMMARY
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()
    print(f"Total wins across 3 quarters: {grand_total_wins}")
    print(f"Wins from week-3 cohort: {grand_cohort_wins}")
    print(f"Wins qualifying after week-3: {grand_total_wins - grand_cohort_wins} ({(grand_total_wins - grand_cohort_wins)/grand_total_wins*100:.1f}%)")
    print()

    if grand_total_wins > 0:
        cohort_rate = grand_cohort_wins / grand_total_wins * 100
        if cohort_rate < 70:
            print(f"⚠️  Week-3 cohort captures only {cohort_rate:.1f}% of eventual wins")
            print("   → Systematic methodology issue")
        else:
            print(f"✓ Week-3 cohort captures {cohort_rate:.1f}% of eventual wins")


if __name__ == '__main__':
    main()
