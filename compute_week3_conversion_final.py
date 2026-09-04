#!/usr/bin/env python3
"""
Week-3 Conversion Rate - Single Authoritative Computation

Implements spec from config/metrics.yaml lines 142-172.
Reports ONE value, computed exactly once against the defined spec.
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


# Spec from metrics.yaml
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

    print("Week-3 Conversion Rate — Single Authoritative Computation")
    print("=" * 70)
    print("\nSpec: config/metrics.yaml lines 142-172")
    print("Population: FY2026 Q3/Q4, FY2027 Q1, default pipeline, new business only")
    print("Method: Cohort tracking (numerator ⊂ denominator)")
    print()

    results_by_quarter = {}
    total_denominator = 0
    total_numerator = 0

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        print(f"\n{quarter_id} ({start_date} to {end_date})")
        print("-" * 70)

        # DENOMINATOR: Week-3 snapshot, scoped, default pipeline only
        snapshot_resp = supabase.table('deals_snapshot') \
            .select('deal_id, stage_id, pipeline_id') \
            .eq('fiscal_quarter', quarter_id) \
            .eq('week_of_quarter', WEEK_OF_QUARTER) \
            .execute()

        if not snapshot_resp.data:
            print(f"  ⚠️  No week-{WEEK_OF_QUARTER} snapshot data")
            continue

        # Filter to scoped deals in default pipeline
        cohort_deal_ids = []
        for row in snapshot_resp.data:
            # Check pipeline first
            if str(row.get('pipeline_id')) != PIPELINE_ID:
                continue

            # Check scope
            if is_deal_in_analytics_scope(
                stage_at_date=row.get('stage_id'),
                pipeline_id=row.get('pipeline_id'),
                excluded_pipelines=excluded_pipelines,
                stage_cfg=stage_cfg
            ):
                cohort_deal_ids.append(str(row['deal_id']))

        denominator = len(cohort_deal_ids)
        print(f"  Denominator: {denominator} deals (week-{WEEK_OF_QUARTER} scoped, default pipeline)")

        if denominator == 0:
            continue

        # NUMERATOR: Wins FROM cohort only, by close_date in quarter
        deals_resp = supabase.table('deals') \
            .select('deal_id, stage, close_date') \
            .in_('deal_id', cohort_deal_ids) \
            .execute()

        # Build cohort set for membership checking
        cohort_set = set(cohort_deal_ids)

        numerator = 0
        won_deals = []

        for deal in deals_resp.data:
            deal_id = str(deal['deal_id'])

            # MUST be in cohort
            if deal_id not in cohort_set:
                continue

            # MUST be won
            stage = deal.get('stage')
            if not stage or not is_won(str(stage)):
                continue

            # MUST have close_date in quarter
            close_date = deal.get('close_date')
            if not close_date:
                continue

            if start_date <= close_date <= end_date:
                numerator += 1
                won_deals.append(deal_id)

        rate = numerator / denominator if denominator > 0 else 0

        print(f"  Numerator: {numerator} wins from cohort")
        print(f"  Rate: {rate:.3f} ({rate:.1%})")

        results_by_quarter[quarter_id] = {
            'denominator': denominator,
            'numerator': numerator,
            'rate': rate,
        }

        total_denominator += denominator
        total_numerator += numerator

    # Aggregate results
    print("\n" + "=" * 70)
    print("AGGREGATE RESULTS")
    print("=" * 70)
    print()

    # Pooled rate
    pooled_rate = total_numerator / total_denominator if total_denominator > 0 else 0
    print(f"Pooled: {total_numerator} won / {total_denominator} qualified = {pooled_rate:.3f} ({pooled_rate:.1%})")

    # Trailing average
    rates = [r['rate'] for r in results_by_quarter.values() if r['rate'] > 0]
    trailing_avg = sum(rates) / len(rates) if rates else 0
    print(f"Trailing average: {trailing_avg:.3f} ({trailing_avg:.1%})")

    # Per-quarter breakdown
    print("\nPer-quarter rates:")
    for quarter_id, result in results_by_quarter.items():
        print(f"  {quarter_id}: {result['rate']:.3f} ({result['numerator']}/{result['denominator']})")

    print()
    print("=" * 70)
    print("VERIFICATION")
    print("=" * 70)
    print()
    print(f"Computation method: Cohort tracking (numerator ⊂ denominator)")
    print(f"Scope filter: is_deal_in_analytics_scope()")
    print(f"Pipeline: {PIPELINE_ID} only (renewals excluded)")
    print(f"Snapshot: week_of_quarter = {WEEK_OF_QUARTER}")
    print(f"Win definition: field_semantics.is_won()")
    print(f"Win deadline: close_date in fiscal quarter")
    print()
    print(f"✓ Numerator ({total_numerator}) is subset of denominator ({total_denominator})")
    print(f"✓ All {total_numerator} wins verified as FROM week-{WEEK_OF_QUARTER} cohort")
    print(f"✓ No deals created or qualified after week-{WEEK_OF_QUARTER} in numerator")


if __name__ == '__main__':
    main()
