#!/usr/bin/env python3
"""
Conversion Rate by Qualification Week

New primary methodology: Track cohorts by when they qualify, not fixed calendar week.

For each deal:
- Find week-of-quarter when it FIRST reached qualified stage
- Group ALL deals (won and not-won) by qualification week
- Compute conversion rate per bucket (won / qualified in that week)

Output: Table showing qualification week vs conversion rate
Expect: Decay curve (early qualifiers convert higher, late qualifiers lower)

This replaces query_week3_conversion() as authoritative methodology.
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
    print("CONVERSION RATE BY QUALIFICATION WEEK")
    print("=" * 80)
    print()
    print("Population: All deals that qualified in-quarter (FY2026 Q3/Q4, FY2027 Q1)")
    print("Cohort method: Group by week-of-quarter when deal FIRST qualified")
    print("Rate: % of each cohort that closed won in-quarter")
    print()

    # Track by qualification week
    cohorts = defaultdict(lambda: {'qualified': [], 'won': []})

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        print(f"Processing {quarter_id}...")

        # Get ALL snapshots for this quarter (all weeks)
        snapshots_resp = supabase.table('deals_snapshot') \
            .select('deal_id, week_of_quarter, stage_id, pipeline_id') \
            .eq('fiscal_quarter', quarter_id) \
            .eq('pipeline_id', PIPELINE_ID) \
            .execute()

        # Group snapshots by deal_id
        snapshots_by_deal = defaultdict(list)
        for snap in snapshots_resp.data:
            deal_id = str(snap['deal_id'])
            snapshots_by_deal[deal_id].append(snap)

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

        # Get current status for all these deals (batch if needed)
        deal_ids = list(deal_qualification_weeks.keys())
        batch_size = 1000

        for i in range(0, len(deal_ids), batch_size):
            batch = deal_ids[i:i+batch_size]

            deals_resp = supabase.table('deals') \
                .select('deal_id, stage, close_date') \
                .in_('deal_id', batch) \
                .execute()

            for deal in deals_resp.data:
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
                    if close_date and start_date <= close_date <= end_date:
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

        print(f"Week {week:>5d} | {qualified:>10d} | {won:>10d} | {rate:>9.1%} | {confidence:<12s}")

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

    print()
    print("NOTE: This replaces fixed week-3 methodology as primary conversion metric.")
    print("      Shape of curve (not single blended rate) is the finding.")
    print()


if __name__ == '__main__':
    main()
