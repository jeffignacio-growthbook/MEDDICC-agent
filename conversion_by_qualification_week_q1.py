#!/usr/bin/env python3
"""
Conversion Rate by Qualification Week - Q1 Only

Methodology: Track cohorts by when they qualify, not fixed calendar week.

Scope: FY2027 Q1 ONLY (complete snapshot weeks 1-13)
- Q3/Q4 excluded due to incomplete snapshot grid
- Q3: only weeks 1-2 captured (missing 3+)
- Q4: only weeks 4-13 captured (missing 1-3)

For each deal in Q1:
- Find week-of-quarter when it FIRST reached qualified stage
- Group ALL deals (won and not-won) by qualification week
- Compute conversion rate per bucket (won / qualified in that week)

Output: Table showing qualification week vs conversion rate
Expect: Decay curve (early qualifiers convert higher, late qualifiers lower)

Reference: n=29 total wins in Q1, n=5 from week-3 cohort (17.2%)
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


def main():
    supabase = get_supabase()
    excluded_pipelines, stage_cfg = load_scope_config()

    print("=" * 80)
    print("CONVERSION RATE BY QUALIFICATION WEEK - Q1 ONLY")
    print("=" * 80)
    print()
    print("Scope: FY2027 Q1 (2026-05-01 to 2026-07-31)")
    print("       Complete snapshot weeks 1-13 available")
    print()
    print("Methodology: Cohort by week-of-quarter when deal FIRST qualified")
    print("Rate: % of each cohort that closed won in-quarter")
    print()
    print("Note: Q3/Q4 excluded due to incomplete snapshot grid")
    print()

    # Track by qualification week
    cohorts = defaultdict(lambda: {'qualified': [], 'won': []})

    print(f"Processing {QUARTER_ID}...")

    # Get ALL snapshots for Q1 (all weeks)
    snapshots_resp = supabase.table('deals_snapshot') \
        .select('deal_id, week_of_quarter, stage_id, pipeline_id') \
        .eq('fiscal_quarter', QUARTER_ID) \
        .eq('pipeline_id', PIPELINE_ID) \
        .execute()

    print(f"  Fetched {len(snapshots_resp.data)} snapshot rows")

    # Group snapshots by deal_id
    snapshots_by_deal = defaultdict(list)
    for snap in snapshots_resp.data:
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

    # Get current status for all these deals
    deal_ids = list(deal_qualification_weeks.keys())

    if not deal_ids:
        print("  No qualified deals found in Q1")
        return

    # Batch query (split if > 1000)
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
    elif late_qualified > 0:
        print("~ Modest or no decay: Qualification timing less predictive")

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
        print(f"  Week 3:    {week3_won}/{total_won} wins ({week3_win_share:.1f}%)")
        print()

    print()
    print("=" * 80)
    print("LIMITATIONS & NEXT STEPS")
    print("=" * 80)
    print()
    print("LIMITATIONS:")
    print("  1. Single-quarter data (Q1 only) - patterns may not generalize")
    print("  2. Small n per bucket (many weeks have < 10 deals)")
    print("  3. Q3/Q4 excluded due to incomplete snapshot grid")
    print()
    print("SNAPSHOT GRID GAPS (Infrastructure Backlog):")
    print("  - Q3: weeks 1-2 only (missing 3-13)")
    print("  - Q4: weeks 4-13 only (missing 1-3)")
    print("  - Q1: weeks 1-13 complete ✓")
    print()
    print("  Root cause investigation needed:")
    print("    • Was snapshot job not running during Q3/Q4 early weeks?")
    print("    • Data deletion or migration issue?")
    print("    • Can we backfill from HubSpot? (API test showed: NO)")
    print()
    print("NEXT STEPS:")
    print("  1. Accumulate more quarters of complete snapshot data")
    print("  2. Re-run analysis with 3+ quarters (better statistical power)")
    print("  3. Consider alternative cutoff (week-5, week-8) based on curve shape")
    print()
    print("Note: This replaces fixed week-3 methodology as primary conversion metric")
    print("      once sufficient data accumulated. Shape of curve (not single blended")
    print("      rate) is the finding.")
    print()


if __name__ == '__main__':
    main()
