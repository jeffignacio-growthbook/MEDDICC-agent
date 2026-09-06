#!/usr/bin/env python3
"""
Debug Q1 Week-3 Methodology Discrepancy

Contradiction:
- Method 1 (fixed week-3 snapshot): 76 qualified, 5 wins
- Method 2 (first qualification week): Week 3 shows 0 qualified, 0 wins

Task: Run both methods side-by-side on Q1 data and reconcile.

Key difference to test:
- Method 1: "What deals were qualified AT week 3?" (cumulative snapshot)
- Method 2: "What deals FIRST qualified IN week 3?" (incremental transition)

If a deal qualified in week 1 and stayed qualified through week 3:
- Method 1 counts it (qualified AT week 3)
- Method 2 assigns it to week 1 (FIRST qualified there)

This explains different totals, but we need to verify the 5 wins are correctly tracked.
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
WEEK_OF_QUARTER = 3
PIPELINE_ID = 'default'


def main():
    supabase = get_supabase()
    excluded_pipelines, stage_cfg = load_scope_config()

    print("=" * 80)
    print("Q1 WEEK-3 METHODOLOGY RECONCILIATION")
    print("=" * 80)
    print()

    # ========================================================================
    # METHOD 1: FIXED WEEK-3 SNAPSHOT (Original reconcile script)
    # ========================================================================
    print("METHOD 1: Fixed Week-3 Snapshot (reconcile_all_quarters_correct.py logic)")
    print("-" * 80)

    # Get week-3 snapshot for Q1
    snapshot_resp = supabase.table('deals_snapshot') \
        .select('deal_id, stage_id, pipeline_id') \
        .eq('fiscal_quarter', QUARTER_ID) \
        .eq('week_of_quarter', WEEK_OF_QUARTER) \
        .execute()

    print(f"Total snapshot rows at week-3: {len(snapshot_resp.data)}")

    # Filter to scoped deals in default pipeline
    method1_qualified_ids = []
    for row in snapshot_resp.data:
        if str(row.get('pipeline_id')) != PIPELINE_ID:
            continue

        if is_deal_in_analytics_scope(
            stage_at_date=row.get('stage_id'),
            pipeline_id=row.get('pipeline_id'),
            excluded_pipelines=excluded_pipelines,
            stage_cfg=stage_cfg
        ):
            method1_qualified_ids.append(str(row['deal_id']))

    print(f"Qualified deals AT week-3: {len(method1_qualified_ids)}")

    # Get current state and count wins
    if method1_qualified_ids:
        deals_resp = supabase.table('deals') \
            .select('deal_id, company_name, stage, close_date') \
            .in_('deal_id', method1_qualified_ids) \
            .execute()

        method1_wins = []
        for deal in deals_resp.data:
            deal_id = str(deal['deal_id'])
            stage = deal.get('stage')
            close_date = deal.get('close_date')

            if stage and is_won(str(stage)):
                if close_date and START_DATE <= close_date <= END_DATE:
                    method1_wins.append({
                        'deal_id': deal_id,
                        'company_name': deal.get('company_name'),
                        'close_date': close_date
                    })

        print(f"Wins from week-3 cohort: {len(method1_wins)}")
        print()
        print("Winning deals:")
        for win in method1_wins:
            print(f"  {win['company_name']:40s} | {win['close_date']} | {win['deal_id']}")
    else:
        method1_wins = []

    print()

    # ========================================================================
    # METHOD 2: FIRST QUALIFICATION WEEK (New conversion_by_qualification_week logic)
    # ========================================================================
    print()
    print("METHOD 2: First Qualification Week (conversion_by_qualification_week_q1.py logic)")
    print("-" * 80)

    # Get ALL snapshots for Q1
    all_snapshots_resp = supabase.table('deals_snapshot') \
        .select('deal_id, week_of_quarter, stage_id, pipeline_id') \
        .eq('fiscal_quarter', QUARTER_ID) \
        .eq('pipeline_id', PIPELINE_ID) \
        .execute()

    print(f"Total snapshot rows (all weeks): {len(all_snapshots_resp.data)}")

    # Group by deal_id
    snapshots_by_deal = defaultdict(list)
    for snap in all_snapshots_resp.data:
        deal_id = str(snap['deal_id'])
        snapshots_by_deal[deal_id].append(snap)

    print(f"Unique deals in snapshots: {len(snapshots_by_deal)}")

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

    print(f"Deals with qualification weeks: {len(deal_qualification_weeks)}")

    # Count by week
    week_counts = defaultdict(int)
    for week in deal_qualification_weeks.values():
        week_counts[week] += 1

    print()
    print("Distribution by first qualification week:")
    for week in sorted(week_counts.keys()):
        count = week_counts[week]
        marker = " ← ORIGINAL CUTOFF" if week == 3 else ""
        print(f"  Week {week}: {count} deals{marker}")

    # Get wins by qualification week
    deal_ids = list(deal_qualification_weeks.keys())
    method2_wins_by_week = defaultdict(list)

    if deal_ids:
        deals_resp = supabase.table('deals') \
            .select('deal_id, company_name, stage, close_date') \
            .in_('deal_id', deal_ids) \
            .execute()

        for deal in deals_resp.data:
            deal_id = str(deal['deal_id'])
            stage = deal.get('stage')
            close_date = deal.get('close_date')

            if stage and is_won(str(stage)):
                if close_date and START_DATE <= close_date <= END_DATE:
                    qual_week = deal_qualification_weeks.get(deal_id)
                    method2_wins_by_week[qual_week].append({
                        'deal_id': deal_id,
                        'company_name': deal.get('company_name'),
                        'close_date': close_date,
                        'qualification_week': qual_week
                    })

    method2_week3_wins = method2_wins_by_week.get(3, [])
    method2_all_wins = []
    for wins in method2_wins_by_week.values():
        method2_all_wins.extend(wins)

    print()
    print(f"Total wins (all qualification weeks): {len(method2_all_wins)}")
    print(f"Wins with qualification_week = 3: {len(method2_week3_wins)}")

    if method2_all_wins:
        print()
        print("All winning deals with their qualification weeks:")
        for win in method2_all_wins:
            qual_week = win.get('qualification_week', 'Unknown')
            print(f"  Week {qual_week} | {win['company_name']:40s} | {win['close_date']} | {win['deal_id']}")

    print()

    # ========================================================================
    # RECONCILIATION
    # ========================================================================
    print()
    print("=" * 80)
    print("RECONCILIATION")
    print("=" * 80)
    print()

    method1_win_ids = set(w['deal_id'] for w in method1_wins)
    method2_win_ids = set(w['deal_id'] for w in method2_all_wins)

    print(f"Method 1 (week-3 snapshot): {len(method1_qualified_ids)} qualified, {len(method1_wins)} wins")
    print(f"Method 2 (first qual week): {len(deal_qualification_weeks)} total qualified, {len(method2_all_wins)} wins")
    print()

    # Check if same wins
    if method1_win_ids == method2_win_ids:
        print("✓ Both methods identify the SAME winning deals")
    else:
        print("❌ Methods identify DIFFERENT winning deals")

        only_method1 = method1_win_ids - method2_win_ids
        only_method2 = method2_win_ids - method1_win_ids

        if only_method1:
            print(f"  Wins only in Method 1: {len(only_method1)}")
            for deal_id in only_method1:
                win = next(w for w in method1_wins if w['deal_id'] == deal_id)
                print(f"    {win['company_name']} | {deal_id}")

        if only_method2:
            print(f"  Wins only in Method 2: {len(only_method2)}")
            for deal_id in only_method2:
                win = next(w for w in method2_all_wins if w['deal_id'] == deal_id)
                print(f"    {win['company_name']} | {deal_id}")

    print()

    # Explain the qualification week distribution
    print("EXPLANATION OF DISCREPANCY:")
    print()
    print("Method 1: Cumulative snapshot at week-3")
    print("  → Counts all deals that ARE qualified at week-3 (regardless of when they qualified)")
    print()
    print("Method 2: First qualification week")
    print("  → Assigns each deal to the week it FIRST BECAME qualified")
    print("  → Week-3 bucket only contains deals that were NOT qualified in weeks 1-2")
    print()

    # Check if method1 qualified == sum of method2 weeks 1-3
    method2_weeks_1_to_3 = sum(week_counts.get(w, 0) for w in [1, 2, 3])

    print(f"Method 1 qualified at week-3: {len(method1_qualified_ids)}")
    print(f"Method 2 qualified in weeks 1-3 combined: {method2_weeks_1_to_3}")
    print()

    if len(method1_qualified_ids) == method2_weeks_1_to_3:
        print("✓ RECONCILED: Method 1's week-3 count = Method 2's sum of weeks 1-3")
        print("  → The difference is just cumulative vs incremental counting")
        print("  → No data bug, no infrastructure issue for this specific discrepancy")
    else:
        diff = len(method1_qualified_ids) - method2_weeks_1_to_3
        print(f"⚠️  MISMATCH: {abs(diff)} deal difference")
        print(f"  Method 1 has {'more' if diff > 0 else 'fewer'} deals than Method 2's weeks 1-3 sum")
        print("  → Investigate: Are some deals missing from snapshots?")
        print("  → Or: Does qualification status change between weeks 1-3?")

    print()

    # Track the 5 known wins through both methods
    print()
    print("=" * 80)
    print("TRACKING THE 5 KNOWN WINS")
    print("=" * 80)
    print()

    if len(method1_wins) == 5 and len(method2_all_wins) == 5:
        print("✓ Both methods find exactly 5 wins")
        print()
        print("Win-by-win comparison:")
        print()
        for win in method1_wins:
            deal_id = win['deal_id']
            company = win['company_name']

            # Find in method2
            method2_win = next((w for w in method2_all_wins if w['deal_id'] == deal_id), None)

            if method2_win:
                qual_week = method2_win.get('qualification_week', 'Not found')
                print(f"  {company:40s}")
                print(f"    Method 1: In week-3 cohort ✓")
                print(f"    Method 2: First qualified in week {qual_week}")

                if qual_week <= 3:
                    print(f"    → OK: Qualified by week {qual_week}, so IN week-3 snapshot")
                else:
                    print(f"    → ⚠️  BUG: Qualified in week {qual_week} > 3, but IN week-3 snapshot?")
                print()
            else:
                print(f"  {company:40s}")
                print(f"    Method 1: In week-3 cohort ✓")
                print(f"    Method 2: NOT FOUND ❌")
                print(f"    → BUG: Deal in week-3 snapshot but has no qualification_week assigned")
                print()
    else:
        print(f"⚠️  Win count mismatch: Method 1 has {len(method1_wins)}, Method 2 has {len(method2_all_wins)}")

    print()
    print("=" * 80)
    print("CONCLUSION")
    print("=" * 80)
    print()
    print("If reconciled: The 'week-3 = 0' finding is EXPECTED behavior")
    print("  → Method 2 shows 0 deals FIRST qualified in week 3")
    print("  → This means all deals qualified by week-3 entered in weeks 1-2")
    print("  → Week-3 snapshot still contains those deals (cumulative)")
    print()
    print("If not reconciled: There's a script bug to fix before proceeding")
    print()


if __name__ == '__main__':
    main()
