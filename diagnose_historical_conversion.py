#!/usr/bin/env python3
"""
Diagnose historical_conversion_mid calculation.

Expected: week-3 snapshot count × conversion_rate × avg_deal_size
Actual (buggy): sum(deal_value × conversion_rate) = open_pipeline × rate

This proves whether convergence with stage_weighted is real or artifact.
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from supabase import create_client
from utils import load_client_config, get_fiscal_quarter
from analytics.point_in_time import load_scope_config, is_deal_in_analytics_scope
from supabase_client import select_all
from datetime import date


def main():
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    config = load_client_config()

    # Get current quarter
    today = date.today()
    _, _, current_fq = get_fiscal_quarter(today, config)

    print(f"Current fiscal quarter: {current_fq}")
    print(f"Testing historical_conversion_mid calculation\n")

    # Get scope filter
    renewal_pipeline_ids = set(
        config.get('pipeline', {}).get('value_field', {}).get('renewal_pipeline_ids', [])
    )
    excl_pipelines, stage_cfg = load_scope_config(config)

    # Get all active deals for Q3
    deals = select_all(
        sb, 'deals',
        columns='deal_id, pipeline_id, stage, deal_value, close_date, deal_status'
    )

    # Filter to Q3 default pipeline deals (same as compute_forecast.py)
    q3_start = date(2026, 8, 1)
    q3_end = date(2026, 10, 31)

    q3_default_deals = [
        d for d in deals
        if d.get('deal_status') == 'active'
        and d.get('pipeline_id') not in renewal_pipeline_ids
        and d.get('close_date')
        and q3_start <= date.fromisoformat(d['close_date'][:10]) <= q3_end
        and is_deal_in_analytics_scope(
            d.get('stage'),
            d.get('pipeline_id'),
            excl_pipelines,
            stage_cfg
        )
    ]

    open_pipeline_value = sum(d.get('deal_value') or 0 for d in q3_default_deals)
    open_deal_count = len(q3_default_deals)
    avg_deal_size = open_pipeline_value / open_deal_count if open_deal_count > 0 else 0

    print(f"{'='*70}")
    print(f"CURRENT Pipeline (what compute_forecast.py uses)")
    print(f"{'='*70}")
    print(f"  Qualified deals (default pipeline): {open_deal_count}")
    print(f"  Total pipeline value: ${open_pipeline_value:,.0f}")
    print(f"  Average deal size: ${avg_deal_size:,.0f}")
    print()

    # What the current (buggy) code computes
    current_implementation = open_pipeline_value * 0.135
    print(f"Current implementation (buggy):")
    print(f"  historical_conversion_mid = open_pipeline_value × 0.135")
    print(f"  = ${open_pipeline_value:,.0f} × 0.135")
    print(f"  = ${current_implementation:,.0f}")
    print()

    # What it SHOULD compute (Kellogg method)
    # Check if week-3 snapshot exists for Q3
    week3_snapshot = select_all(
        sb, 'deals_snapshot',
        columns='deal_id,stage_id,pipeline_id,deal_value',
        filters=[('eq', 'fiscal_quarter', current_fq),
                 ('eq', 'week_of_quarter', 3)]
    )

    if week3_snapshot:
        # Filter to qualified deals in default pipeline
        def _qualified(stage_id, pipeline_id):
            if stage_id is None or not str(stage_id).strip():
                return False
            return is_deal_in_analytics_scope(
                str(stage_id), pipeline_id, set(), stage_cfg)

        week3_qualified = [
            d for d in week3_snapshot
            if d.get('pipeline_id') not in renewal_pipeline_ids
            and _qualified(d.get('stage_id'), d.get('pipeline_id'))
        ]

        week3_count = len(week3_qualified)
        week3_value = sum(d.get('deal_value') or 0 for d in week3_qualified)
        week3_avg_size = week3_value / week3_count if week3_count > 0 else 0

        print(f"{'='*70}")
        print(f"WEEK-3 Snapshot (what Kellogg method needs)")
        print(f"{'='*70}")
        print(f"  Week-3 qualified count: {week3_count}")
        print(f"  Week-3 pipeline value: ${week3_value:,.0f}")
        print(f"  Week-3 avg deal size: ${week3_avg_size:,.0f}")
        print()

        # Correct Kellogg calculation
        expected_wins = week3_count * 0.135
        correct_forecast = expected_wins * week3_avg_size

        print(f"Correct implementation (Kellogg method):")
        print(f"  Expected wins = week3_count × 0.135")
        print(f"  = {week3_count} × 0.135 = {expected_wins:.1f} deals")
        print(f"  Forecast = expected_wins × week3_avg_deal_size")
        print(f"  = {expected_wins:.1f} × ${week3_avg_size:,.0f}")
        print(f"  = ${correct_forecast:,.0f}")
        print()

        # Comparison
        print(f"{'='*70}")
        print(f"COMPARISON")
        print(f"{'='*70}")
        print(f"  Buggy (rescaled current pipeline): ${current_implementation:,.0f}")
        print(f"  Correct (week-3 Kellogg method):    ${correct_forecast:,.0f}")
        print(f"  Difference: ${current_implementation - correct_forecast:+,.0f}")
        print()

        if abs(current_implementation - correct_forecast) < 100_000:
            print("⚠️  Numbers are close — convergence may be artifact of:")
            print("    - Week-3 snapshot similar to current pipeline")
            print("    - Similar qualified deal counts")
            print("    This doesn't validate the method; just means populations overlap")
        else:
            print("✓ Numbers differ materially — these are genuinely different methods")

    else:
        print(f"⚠️  No week-3 snapshot for {current_fq}")
        print("    Cannot compute correct Kellogg method")
        print("    Current implementation is just rescaling today's pipeline")
        print()
        print("RECOMMENDATION:")
        print("  - Wait until week-3 snapshot exists, OR")
        print("  - Use deals_snapshot from most recent complete quarter, OR")
        print("  - Label this as 'current pipeline × historical rate' not 'Kellogg method'")


if __name__ == '__main__':
    main()
