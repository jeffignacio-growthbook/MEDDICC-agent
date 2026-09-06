#!/usr/bin/env python3
"""
Qualification Timing Analysis

Question: Is week-3 too early as a cohort cutoff?

For all won deals (FY2026 Q3/Q4, FY2027 Q1, default pipeline):
- Determine WHEN each deal first entered a qualified stage
- Report distribution: what % of wins were qualified by week 3, 5, 8, etc.

Goal: If many wins qualify after week-3, the methodology needs fixing
(later cutoff, or cohort-by-qualification-week) not just segment caveats.
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
    print("QUALIFICATION TIMING ANALYSIS")
    print("=" * 80)
    print()
    print("Question: Is week-3 too early as a general cohort cutoff?")
    print()
    print("Population: All won deals (FY2026 Q3/Q4, FY2027 Q1, default pipeline)")
    print("Measurement: Week-of-quarter when deal first qualified (order ≥ 1)")
    print()

    # Track all won deals and their qualification timing
    won_deals_by_quarter = {}
    qualification_weeks = []

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        print(f"Processing {quarter_id}...")

        # Get ALL won deals in quarter (not just from week-3 cohort)
        deals_resp = supabase.table('deals') \
            .select('deal_id, stage, close_date, segment') \
            .eq('pipeline_id', PIPELINE_ID) \
            .execute()

        # Filter to wins in this quarter
        won_deal_ids = []
        for deal in deals_resp.data:
            stage = deal.get('stage')
            close_date = deal.get('close_date')

            if stage and is_won(str(stage)) and close_date:
                if start_date <= close_date <= end_date:
                    won_deal_ids.append(str(deal['deal_id']))

        print(f"  Found {len(won_deal_ids)} won deals in quarter")

        if not won_deal_ids:
            continue

        # For each won deal, find earliest week they qualified
        # Get ALL snapshots for these deals in this quarter
        snapshots_resp = supabase.table('deals_snapshot') \
            .select('deal_id, week_of_quarter, stage_id, pipeline_id') \
            .eq('fiscal_quarter', quarter_id) \
            .in_('deal_id', won_deal_ids) \
            .execute()

        # Group snapshots by deal_id
        snapshots_by_deal = defaultdict(list)
        for snap in snapshots_resp.data:
            deal_id = str(snap['deal_id'])
            if deal_id in won_deal_ids:
                snapshots_by_deal[deal_id].append(snap)

        # Find earliest qualification week for each won deal
        for deal_id in won_deal_ids:
            deal_snapshots = snapshots_by_deal.get(deal_id, [])

            if not deal_snapshots:
                # Deal has no snapshots (created after last snapshot week)
                qualification_weeks.append(('after_last_snapshot', quarter_id, deal_id))
                continue

            # Sort by week
            deal_snapshots.sort(key=lambda x: x.get('week_of_quarter', 99))

            # Find first week where deal was qualified
            first_qualified_week = None
            for snap in deal_snapshots:
                stage_id = snap.get('stage_id')
                pipeline_id = snap.get('pipeline_id')
                week = snap.get('week_of_quarter')

                # Check if qualified at this snapshot
                if is_deal_in_analytics_scope(
                    stage_at_date=stage_id,
                    pipeline_id=pipeline_id,
                    excluded_pipelines=excluded_pipelines,
                    stage_cfg=stage_cfg
                ):
                    first_qualified_week = week
                    break

            if first_qualified_week is not None:
                qualification_weeks.append((first_qualified_week, quarter_id, deal_id))
            else:
                # Deal was never qualified in any snapshot
                # (qualified after last snapshot, or was in excluded stages entire time)
                qualification_weeks.append(('never_qualified_in_snapshots', quarter_id, deal_id))

    print()
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print()

    # Count by qualification week
    week_counts = defaultdict(int)
    special_cases = defaultdict(int)

    for qual_week, quarter, deal_id in qualification_weeks:
        if isinstance(qual_week, int):
            week_counts[qual_week] += 1
        else:
            special_cases[qual_week] += 1

    total_wins = len(qualification_weeks)

    print(f"Total won deals analyzed: {total_wins}")
    print()

    # Report distribution
    print("Distribution: Week when deal first qualified")
    print()
    print(f"{'Week':>6s} | {'Count':>6s} | {'% of Wins':>10s} | {'Cumulative %':>15s} | {'Confidence':>12s}")
    print("-" * 80)

    cumulative = 0
    max_week = max(week_counts.keys()) if week_counts else 0

    for week in range(1, max_week + 1):
        count = week_counts.get(week, 0)
        pct = count / total_wins * 100 if total_wins > 0 else 0
        cumulative += count
        cum_pct = cumulative / total_wins * 100 if total_wins > 0 else 0

        confidence = "✓" if count >= 10 else "⚠ low n" if count > 0 else ""

        marker = " ← CURRENT CUTOFF" if week == 3 else ""
        print(f"Week {week:>2d} | {count:>6d} | {pct:>9.1f}% | {cum_pct:>14.1f}% | {confidence:<12s}{marker}")

    # Report special cases
    if special_cases:
        print()
        print("Special cases:")
        for case, count in special_cases.items():
            pct = count / total_wins * 100 if total_wins > 0 else 0
            print(f"  {case}: {count} deals ({pct:.1f}%)")

    print()
    print("=" * 80)
    print("ANALYSIS")
    print("=" * 80)
    print()

    # Calculate key metrics
    week3_and_before = sum(week_counts.get(w, 0) for w in range(1, 4))
    week3_pct = week3_and_before / total_wins * 100 if total_wins > 0 else 0

    week5_and_before = sum(week_counts.get(w, 0) for w in range(1, 6))
    week5_pct = week5_and_before / total_wins * 100 if total_wins > 0 else 0

    after_week3 = total_wins - week3_and_before
    after_week3_pct = after_week3 / total_wins * 100 if total_wins > 0 else 0

    print(f"Wins qualified by week-3: {week3_and_before} of {total_wins} ({week3_pct:.1f}%)")
    print(f"Wins qualified AFTER week-3: {after_week3} of {total_wins} ({after_week3_pct:.1f}%)")
    print()

    if week3_pct < 70:
        print("⚠️  FINDING: Week-3 cutoff captures < 70% of eventual wins")
        print("   → Systematic undercount in conversion denominator")
        print("   → Issue affects all segments, not just SMB")
        print()
        print("RECOMMENDATION:")
        if week5_pct >= 80:
            print(f"   → Move cutoff to week-5 (captures {week5_pct:.1f}% of wins)")
        print("   → OR: Track cohorts by qualification-week, not fixed calendar week")
        print("   → OR: Use 'qualified at any point in quarter' as denominator")
    elif week3_pct >= 80:
        print("✓ Week-3 cutoff captures ≥80% of eventual wins")
        print("  → Methodology is reasonable for general use")
        print("  → SMB qualification gap is segment-specific, not methodology issue")
    else:
        print("~ Week-3 cutoff captures 70-80% of eventual wins")
        print("  → Borderline reasonable, but missing non-trivial share")
        print("  → Consider moving to week-5 if data supports it")

    print()
    print("Note: Deals qualifying after last snapshot week are not captured here.")
    print("      True qualification rate may be even later than shown.")
    print()


if __name__ == '__main__':
    main()
