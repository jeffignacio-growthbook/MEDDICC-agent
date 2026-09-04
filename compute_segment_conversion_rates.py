#!/usr/bin/env python3
"""
Compute segment-specific week-3 conversion rates with CORRECT numerator.

Numerator: in-quarter wins of deals FROM week-3 snapshot only
Denominator: week-3 qualified pipeline (scoped via is_deal_in_analytics_scope)

Evidence threshold: minimum 30 deals per segment across 3 quarters
"""

import os
import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple
from dotenv import load_dotenv

# Load environment
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from scripts.analytics.point_in_time import is_deal_in_analytics_scope, load_scope_config
from api.field_semantics import is_won
from api.db import get_supabase

QUARTERS = [
    ('FY2026 Q3', '2025-11-01', '2026-01-31', 3),
    ('FY2026 Q4', '2026-02-01', '2026-04-30', 3),
    ('FY2027 Q1', '2026-05-01', '2026-07-31', 3),
]

MIN_EVIDENCE_COUNT = 30  # Minimum deals across 3 quarters for meaningful rate


def main():
    supabase = get_supabase()
    excluded_pipelines, stage_cfg = load_scope_config()

    print("Computing segment-specific week-3 conversion rates")
    print("=" * 70)
    print()

    # Track per-segment, per-quarter data
    segment_data = defaultdict(lambda: {
        'qualified_by_quarter': defaultdict(list),  # deal_ids in week-3 snapshot
        'won_by_quarter': defaultdict(list),        # deal_ids that won in-quarter
    })

    for quarter_id, start_date, end_date, week_num in QUARTERS:
        print(f"\nProcessing {quarter_id} (week {week_num})...")

        # Get week-3 snapshot
        snapshot_resp = supabase.table('deals_snapshot') \
            .select('deal_id, stage_id, pipeline_id') \
            .eq('fiscal_quarter', quarter_id) \
            .eq('week_of_quarter', week_num) \
            .execute()

        if not snapshot_resp.data:
            print(f"  ⚠️  No snapshot data for {quarter_id} week {week_num}")
            continue

        # Filter to scoped deals
        scoped_deal_ids = []
        for row in snapshot_resp.data:
            if is_deal_in_analytics_scope(
                stage_at_date=row.get('stage_id'),
                pipeline_id=row.get('pipeline_id'),
                excluded_pipelines=excluded_pipelines,
                stage_cfg=stage_cfg
            ):
                scoped_deal_ids.append(row['deal_id'])

        print(f"  Week-3 scoped pipeline: {len(scoped_deal_ids)} deals")

        if not scoped_deal_ids:
            continue

        # Get segment and stage for these deals
        deals_resp = supabase.table('deals') \
            .select('deal_id, segment, stage, close_date') \
            .in_('deal_id', scoped_deal_ids) \
            .execute()

        # Build segment mapping
        deal_segments = {
            d['deal_id']: d.get('segment', 'unknown')
            for d in deals_resp.data
        }

        # Track qualified deals per segment (denominator)
        for deal_id in scoped_deal_ids:
            segment = deal_segments.get(deal_id, 'unknown')
            segment_data[segment]['qualified_by_quarter'][quarter_id].append(deal_id)

        # Track wins in-quarter from this cohort (numerator)
        for deal in deals_resp.data:
            deal_id = deal['deal_id']
            segment = deal.get('segment', 'unknown')
            stage = deal.get('stage')

            # Check if won in-quarter using stage semantics
            if stage and is_won(str(stage)):
                close_date = deal.get('close_date')
                if close_date and start_date <= close_date <= end_date:
                    segment_data[segment]['won_by_quarter'][quarter_id].append(deal_id)

    print("\n" + "=" * 70)
    print("SEGMENT-SPECIFIC CONVERSION RATES")
    print("=" * 70)
    print()

    results = {}

    for segment in sorted(segment_data.keys()):
        data = segment_data[segment]

        # Aggregate across quarters
        total_qualified = sum(len(deals) for deals in data['qualified_by_quarter'].values())
        total_won = sum(len(deals) for deals in data['won_by_quarter'].values())

        # Per-quarter rates
        per_quarter_rates = {}
        for quarter_id, _, _, _ in QUARTERS:
            q_qualified = len(data['qualified_by_quarter'].get(quarter_id, []))
            q_won = len(data['won_by_quarter'].get(quarter_id, []))

            if q_qualified > 0:
                per_quarter_rates[quarter_id] = q_won / q_qualified

        # Pooled rate
        pooled_rate = total_won / total_qualified if total_qualified > 0 else 0

        # Evidence check
        sufficient_evidence = total_qualified >= MIN_EVIDENCE_COUNT

        results[segment] = {
            'n': total_qualified,
            'won': total_won,
            'pooled': pooled_rate,
            'per_quarter': per_quarter_rates,
            'sufficient_evidence': sufficient_evidence
        }

        print(f"{segment.upper()}:")
        print(f"  Population: {total_qualified} qualified across 3 quarters")
        print(f"  Won: {total_won} deals")
        print(f"  Pooled rate: {pooled_rate:.1%}")

        if sufficient_evidence:
            print(f"  ✓ Sufficient evidence (≥{MIN_EVIDENCE_COUNT})")
            print(f"  Per-quarter rates:")
            for q_id, rate in per_quarter_rates.items():
                print(f"    {q_id}: {rate:.1%}")
        else:
            print(f"  ✗ Insufficient evidence (<{MIN_EVIDENCE_COUNT}) - rate not meaningful")

        print()

    # Verification against blended
    total_qualified_all = sum(r['n'] for r in results.values())
    total_won_all = sum(r['won'] for r in results.values())
    blended_check = total_won_all / total_qualified_all if total_qualified_all > 0 else 0

    print("=" * 70)
    print("VERIFICATION:")
    print(f"  Total qualified: {total_qualified_all}")
    print(f"  Total won: {total_won_all}")
    print(f"  Blended rate: {blended_check:.1%}")
    print(f"  Expected: 13.0% (22 won / 169 qualified)")

    if abs(blended_check - 0.130) < 0.001:
        print("  ✓ RECONCILES with verified blended rate")
    else:
        print(f"  ✗ MISMATCH - investigate discrepancy")

    print()

    # Output for registry
    print("=" * 70)
    print("REGISTRY YAML (for segments with sufficient evidence):")
    print("=" * 70)
    print()
    print("by_segment:")

    for segment in sorted(results.keys()):
        r = results[segment]
        if r['sufficient_evidence']:
            print(f"  {segment}:")
            print(f"    value: {r['pooled']:.3f}")
            print(f"    n: {r['n']}")
            print(f"    won: {r['won']}")
            print(f"    quarters: [fy2026_q3, fy2026_q4, fy2027_q1]")

            # Format per_quarter for YAML
            rates_str = ", ".join(f"{q}: {rate:.3f}" for q, rate in r['per_quarter'].items())
            print(f"    per_quarter: {{{rates_str}}}")
            print()
        else:
            print(f"  {segment}:")
            print(f"    value: null")
            print(f"    n: {r['n']}")
            print(f"    reason: \"Below min_evidence_count threshold ({MIN_EVIDENCE_COUNT})\"")
            print()


if __name__ == '__main__':
    main()
