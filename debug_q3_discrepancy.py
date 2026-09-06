#!/usr/bin/env python3
"""
Debug Q3 Win Count Discrepancy

Q3 shows 2 total wins but 3 from week-3 cohort (impossible).
Check for filter inconsistencies between the two queries.
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


PIPELINE_ID = 'default'
Q3_START = '2025-11-01'
Q3_END = '2026-01-31'


def main():
    supabase = get_supabase()
    excluded_pipelines, stage_cfg = load_scope_config()

    print("=" * 80)
    print("Q3 WIN COUNT RECONCILIATION")
    print("=" * 80)
    print()

    # QUERY 1: Week-3 cohort wins (original method)
    print("QUERY 1: Wins from week-3 cohort")
    print("-" * 80)

    snapshot_resp = supabase.table('deals_snapshot') \
        .select('deal_id, stage_id, pipeline_id') \
        .eq('fiscal_quarter', 'FY2026 Q3') \
        .eq('week_of_quarter', 3) \
        .execute()

    print(f"Total snapshot rows: {len(snapshot_resp.data)}")

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

    print(f"Scoped deals in week-3 cohort: {len(scoped_deal_ids)}")

    if not scoped_deal_ids:
        print("No scoped deals found")
        return

    # Get current state of cohort deals
    deals_resp = supabase.table('deals') \
        .select('deal_id, company_name, stage, close_date, pipeline_id') \
        .in_('deal_id', scoped_deal_ids) \
        .execute()

    cohort_set = set(scoped_deal_ids)
    cohort_wins = []

    for deal in deals_resp.data:
        deal_id = str(deal['deal_id'])

        if deal_id not in cohort_set:
            continue

        stage = deal.get('stage')
        if not stage or not is_won(str(stage)):
            continue

        close_date = deal.get('close_date')
        if close_date and Q3_START <= close_date <= Q3_END:
            cohort_wins.append({
                'deal_id': deal_id,
                'company': deal.get('company_name'),
                'close_date': close_date,
                'pipeline': deal.get('pipeline_id'),
                'stage': stage
            })

    print(f"\nWins from week-3 cohort: {len(cohort_wins)}")
    for win in cohort_wins:
        print(f"  {win['company']:30s} | {win['close_date']} | {win['deal_id']}")

    # QUERY 2: Total wins (all deals, same filters)
    print()
    print("QUERY 2: Total wins in Q3")
    print("-" * 80)

    all_deals_resp = supabase.table('deals') \
        .select('deal_id, company_name, stage, close_date, pipeline_id') \
        .execute()

    total_wins = []

    for deal in all_deals_resp.data:
        # Apply SAME filters as cohort query
        pipeline_id = str(deal.get('pipeline_id', ''))
        if pipeline_id != PIPELINE_ID:
            continue

        stage = deal.get('stage')
        if not stage or not is_won(str(stage)):
            continue

        close_date = deal.get('close_date')
        if not close_date or not (Q3_START <= close_date <= Q3_END):
            continue

        total_wins.append({
            'deal_id': str(deal['deal_id']),
            'company': deal.get('company_name'),
            'close_date': close_date,
            'pipeline': pipeline_id,
            'stage': stage
        })

    print(f"Total wins in Q3: {len(total_wins)}")
    for win in total_wins:
        print(f"  {win['company']:30s} | {win['close_date']} | {win['deal_id']}")

    # RECONCILIATION
    print()
    print("=" * 80)
    print("RECONCILIATION")
    print("=" * 80)
    print()

    cohort_win_ids = set(w['deal_id'] for w in cohort_wins)
    total_win_ids = set(w['deal_id'] for w in total_wins)

    # Wins in cohort but not in total (SHOULD BE IMPOSSIBLE)
    phantom_wins = cohort_win_ids - total_win_ids
    if phantom_wins:
        print(f"⚠️  PHANTOM WINS: {len(phantom_wins)} deals in cohort but not in total")
        for deal_id in phantom_wins:
            win_info = next(w for w in cohort_wins if w['deal_id'] == deal_id)
            print(f"    {win_info['company']} | {win_info['deal_id']}")
            print(f"    close_date: {win_info['close_date']}")
            print(f"    Issue: Deal closed outside Q3 date range?")
            print()

    # Wins in total but not in cohort (EXPECTED)
    missing_wins = total_win_ids - cohort_win_ids
    if missing_wins:
        print(f"Wins NOT in week-3 cohort: {len(missing_wins)} deals")
        for deal_id in missing_wins:
            win_info = next(w for w in total_wins if w['deal_id'] == deal_id)
            print(f"  {win_info['company']:30s} | {win_info['close_date']} | qualified after week-3")

    # Summary
    print()
    print("SUMMARY:")
    print(f"  Cohort wins: {len(cohort_wins)}")
    print(f"  Total wins:  {len(total_wins)}")
    print(f"  Phantom:     {len(phantom_wins)} (cohort > total - ERROR)")
    print(f"  Missing:     {len(missing_wins)} (qualified after week-3)")
    print()

    if len(cohort_wins) > len(total_wins):
        print("❌ INVALID: Cohort count exceeds total count")
        print("   → Filter inconsistency between queries")
        print("   → Do NOT proceed until resolved")
    else:
        print("✓ Valid: Cohort count ≤ total count")


if __name__ == '__main__':
    main()
