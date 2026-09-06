#!/usr/bin/env python3
"""
SMB Qualification Gap Analysis

Context: SMB shows 11.0% qualification rate vs 25.9% Enterprise at week-3.
Goal: Distinguish pipeline hygiene (bad) from sales cycle timing (neutral).

Task 1: Sales cycle length by segment (won deals only)
Task 2: Fate of excluded-stage deals by segment
"""

import os
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from dotenv import load_dotenv

# Load environment
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

# Add to path
sys.path.insert(0, str(Path(__file__).parent))

from scripts.analytics.point_in_time import is_deal_in_analytics_scope, load_scope_config
from api.field_semantics import is_won, stage_bucket
from api.db import get_supabase


FISCAL_QUARTERS = [
    ('FY2026 Q3', '2025-11-01', '2026-01-31'),
    ('FY2026 Q4', '2026-02-01', '2026-04-30'),
    ('FY2027 Q1', '2026-05-01', '2026-07-31'),
]

WEEK_OF_QUARTER = 3
PIPELINE_ID = 'default'

EXCLUDED_STAGES = {
    '79653122': 'Meeting Set',
    'decisionmakerboughtin': 'Review',
    '68509551': 'Disqualified',
}


def days_between(start_date_str, end_date_str):
    """Calculate days between two ISO date strings."""
    if not start_date_str or not end_date_str:
        return None
    try:
        start = datetime.fromisoformat(start_date_str[:10])
        end = datetime.fromisoformat(end_date_str[:10])
        return (end - start).days
    except:
        return None


def main():
    supabase = get_supabase()
    excluded_pipelines, stage_cfg = load_scope_config()

    print("=" * 80)
    print("SMB QUALIFICATION GAP ANALYSIS")
    print("=" * 80)
    print()
    print("Hypothesis A: SMB has worse pipeline hygiene (deals die in excluded stages)")
    print("Hypothesis B: SMB cycles are shorter (week-3 catches them 'earlier')")
    print()

    # ========================================================================
    # TASK 1: SALES CYCLE LENGTH BY SEGMENT
    # ========================================================================
    print()
    print("TASK 1: SALES CYCLE LENGTH BY SEGMENT")
    print("=" * 80)
    print()
    print("Population: Won deals from week-3 cohort")
    print("Measurement: Days from create_date to close_date")
    print()

    cycle_lengths_by_segment = defaultdict(list)

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        # Get week-3 snapshot
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
            continue

        # Get won deals from cohort with create_date and close_date
        deals_resp = supabase.table('deals') \
            .select('deal_id, segment, stage, create_date, close_date') \
            .in_('deal_id', scoped_deal_ids) \
            .execute()

        cohort_set = set(scoped_deal_ids)

        for deal in deals_resp.data:
            deal_id = str(deal['deal_id'])

            if deal_id not in cohort_set:
                continue

            # Must be won
            stage = deal.get('stage')
            if not stage or not is_won(str(stage)):
                continue

            # Must have closed in quarter
            close_date = deal.get('close_date')
            if not close_date or not (start_date <= close_date <= end_date):
                continue

            # Calculate cycle length
            create_date = deal.get('create_date')
            days = days_between(create_date, close_date)

            if days is not None:
                segment = deal.get('segment') or 'Unknown'
                cycle_lengths_by_segment[segment].append(days)

    # Report cycle lengths
    print(f"{'Segment':<15s} | {'N':>5s} | {'Avg Days':>10s} | {'Median':>10s} | {'Min':>6s} | {'Max':>6s}")
    print("-" * 80)

    for segment in ['Enterprise', 'Mid-Market', 'SMB', 'Unknown']:
        lengths = cycle_lengths_by_segment.get(segment, [])
        n = len(lengths)

        if n == 0:
            print(f"{segment:<15s} | {n:>5d} | {'N/A':>10s} | {'N/A':>10s} | {'N/A':>6s} | {'N/A':>6s}")
            continue

        avg = sum(lengths) / n
        median = sorted(lengths)[n // 2]
        min_days = min(lengths)
        max_days = max(lengths)

        confidence = "✓" if n >= 10 else "⚠ low n"
        print(f"{segment:<15s} | {n:>5d} | {avg:>9.1f}d | {median:>9d}d | {min_days:>5d}d | {max_days:>5d}d  {confidence}")

    print()
    print("Analysis:")

    # Compare SMB to Enterprise
    smb_lengths = cycle_lengths_by_segment.get('SMB', [])
    ent_lengths = cycle_lengths_by_segment.get('Enterprise', [])

    if smb_lengths and ent_lengths:
        smb_avg = sum(smb_lengths) / len(smb_lengths)
        ent_avg = sum(ent_lengths) / len(ent_lengths)
        smb_median = sorted(smb_lengths)[len(smb_lengths) // 2]
        ent_median = sorted(ent_lengths)[len(ent_lengths) // 2]

        avg_diff = smb_avg - ent_avg
        median_diff = smb_median - ent_median

        print(f"  SMB avg: {smb_avg:.1f} days, Enterprise avg: {ent_avg:.1f} days")
        print(f"  Difference: {avg_diff:+.1f} days ({avg_diff/ent_avg*100:+.1f}%)")
        print()
        print(f"  SMB median: {smb_median} days, Enterprise median: {ent_median} days")
        print(f"  Difference: {median_diff:+d} days ({median_diff/ent_median*100:+.1f}%)")
        print()

        if abs(avg_diff) < ent_avg * 0.2:  # Less than 20% difference
            print("  → Sales cycles similar across segments (< 20% difference)")
            print("  → Hypothesis B (timing artifact) WEAKENED")
            print("  → Qualification gap likely reflects real hygiene/process difference")
        else:
            print("  → Sales cycles differ meaningfully (≥ 20% difference)")
            print("  → Week-3 represents different relative cycle points per segment")
            print("  → Hypothesis B (timing artifact) SUPPORTED")

    # ========================================================================
    # TASK 2: FATE OF EXCLUDED-STAGE DEALS
    # ========================================================================
    print()
    print()
    print("TASK 2: FATE OF EXCLUDED-STAGE DEALS BY SEGMENT")
    print("=" * 80)
    print()
    print("Population: Deals in excluded stages at week-3 snapshot")
    print("Excluded stages: Meeting Set (79653122), Review (decisionmakerboughtin), Disqualified (68509551)")
    print("Outcomes by quarter end:")
    print("  1. Progress to qualified stage (order ≥ 1, not excluded)")
    print("  2. Stay in excluded stages")
    print("  3. Marked Disqualified")
    print("  4. No terminal status (still open)")
    print()

    # Track outcomes by segment
    outcomes_by_segment = defaultdict(lambda: {
        'progressed': 0,
        'stayed_excluded': 0,
        'disqualified': 0,
        'still_open': 0,
        'total': 0
    })

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        # Get ALL week-3 snapshot deals in default pipeline (including excluded stages)
        snapshot_resp = supabase.table('deals_snapshot') \
            .select('deal_id, stage_id, pipeline_id') \
            .eq('fiscal_quarter', quarter_id) \
            .eq('week_of_quarter', WEEK_OF_QUARTER) \
            .eq('pipeline_id', PIPELINE_ID) \
            .execute()

        # Find deals in excluded stages
        excluded_deal_ids = []
        for row in snapshot_resp.data:
            stage_id = str(row.get('stage_id', ''))
            if stage_id in EXCLUDED_STAGES:
                excluded_deal_ids.append(str(row['deal_id']))

        if not excluded_deal_ids:
            continue

        # Get current state and segment
        deals_resp = supabase.table('deals') \
            .select('deal_id, segment, stage, close_date, deal_status') \
            .in_('deal_id', excluded_deal_ids) \
            .execute()

        for deal in deals_resp.data:
            segment = deal.get('segment') or 'Unknown'
            current_stage = str(deal.get('stage', ''))
            close_date = deal.get('close_date')
            deal_status = deal.get('deal_status')

            outcomes_by_segment[segment]['total'] += 1

            # Determine outcome
            current_bucket = stage_bucket(current_stage)

            # Check if progressed to qualified
            if current_stage in stage_cfg:
                cfg = stage_cfg[current_stage]
                is_qualified = (cfg.get('order', -1) >= cfg.get('qualified_stage_order', 1)
                               and not cfg.get('excluded', False))

                if is_qualified:
                    outcomes_by_segment[segment]['progressed'] += 1
                    continue

            # Check if disqualified
            if current_bucket == 'closed_lost' or current_stage == '68509551':
                outcomes_by_segment[segment]['disqualified'] += 1
                continue

            # Check if still in excluded stage
            if current_stage in EXCLUDED_STAGES:
                outcomes_by_segment[segment]['stayed_excluded'] += 1
                continue

            # Otherwise still open (but not in qualified or excluded stages)
            outcomes_by_segment[segment]['still_open'] += 1

    # Report outcomes matrix
    print(f"{'Segment':<15s} | {'Total':>6s} | {'Progressed':>11s} | {'Stayed':>11s} | {'Disqual':>11s} | {'Open':>11s}")
    print("-" * 90)

    for segment in ['Enterprise', 'Mid-Market', 'SMB', 'Unknown']:
        data = outcomes_by_segment.get(segment)
        if not data or data['total'] == 0:
            print(f"{segment:<15s} | {0:>6d} | {'N/A':>11s} | {'N/A':>11s} | {'N/A':>11s} | {'N/A':>11s}")
            continue

        total = data['total']
        prog = data['progressed']
        stayed = data['stayed_excluded']
        disq = data['disqualified']
        open_deals = data['still_open']

        prog_pct = prog / total * 100
        stayed_pct = stayed / total * 100
        disq_pct = disq / total * 100
        open_pct = open_deals / total * 100

        confidence = "✓" if total >= 10 else "⚠"

        print(f"{segment:<15s} | {total:>6d} | {prog:>4d} ({prog_pct:>4.1f}%) | {stayed:>4d} ({stayed_pct:>4.1f}%) | {disq:>4d} ({disq_pct:>4.1f}%) | {open_deals:>4d} ({open_pct:>4.1f}%)  {confidence}")

    print()
    print("Analysis:")
    print()

    # Compare SMB to Enterprise progression rates
    smb_data = outcomes_by_segment.get('SMB')
    ent_data = outcomes_by_segment.get('Enterprise')

    if smb_data and ent_data and smb_data['total'] > 0 and ent_data['total'] > 0:
        smb_prog_rate = smb_data['progressed'] / smb_data['total']
        ent_prog_rate = ent_data['progressed'] / ent_data['total']

        smb_disq_rate = smb_data['disqualified'] / smb_data['total']
        ent_disq_rate = ent_data['disqualified'] / ent_data['total']

        print(f"  SMB progression rate: {smb_prog_rate:.1%} ({smb_data['progressed']}/{smb_data['total']})")
        print(f"  Enterprise progression rate: {ent_prog_rate:.1%} ({ent_data['progressed']}/{ent_data['total']})")
        print()
        print(f"  SMB disqualification rate: {smb_disq_rate:.1%} ({smb_data['disqualified']}/{smb_data['total']})")
        print(f"  Enterprise disqualification rate: {ent_disq_rate:.1%} ({ent_data['disqualified']}/{ent_data['total']})")
        print()

        if smb_prog_rate > ent_prog_rate * 0.8:  # Within 20%
            print("  → SMB deals in excluded stages progress at similar or higher rate than Enterprise")
            print("  → Hypothesis A (worse hygiene) WEAKENED")
            print("  → Excluded-stage deals appear to advance normally, just later in cycle")
        else:
            print("  → SMB deals in excluded stages progress at meaningfully lower rate")
            print("  → Hypothesis A (worse hygiene) SUPPORTED")
            print("  → More SMB deals get stuck/die in excluded stages")

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()
    print("Qualification Rate Context:")
    print("  Enterprise: 25.9% qualify at week-3")
    print("  Mid-Market: 18.0% qualify at week-3")
    print("  SMB:        11.0% qualify at week-3")
    print()
    print("See analysis above for interpretation of cycle length and progression patterns.")
    print()


if __name__ == '__main__':
    main()
