#!/usr/bin/env python3
"""
Check if won deals have different average size than week-3 pipeline.

If won deals consistently skew larger (or smaller) than the pipeline
average, the Kellogg forecast should use won-deal average instead of
week-3 pipeline average.

Example:
  Week-3 pipeline: 100 deals × $50K avg = $5M
  Conversion: 10%

  If using pipeline average:
    Expected: 10 deals × $50K = $500K forecast

  If won deals actually average $100K (larger deals win):
    Actual: 10 deals × $100K = $1M outcome
    Bias: -50% underforecast

  Corrected forecast should use won-deal average when bias is material.
"""

import os
import sys
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from supabase import create_client
from supabase_client import select_all


def main():
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Check complete historical quarters only (Q3 FY2027 still in flight)
    quarters = ['FY2026 Q3', 'FY2026 Q4', 'FY2027 Q1', 'FY2027 Q2']

    print("Average Deal Size: Won vs Week-3 Pipeline")
    print("="*70)
    print()

    biases = []

    for quarter in quarters:
        # Get won deals from terminal state
        all_deals = select_all(
            sb, 'deals',
            columns='deal_value,pipeline_id,stage',
            filters=[('eq', 'fiscal_quarter', quarter)]
        )

        # Filter to default pipeline won deals
        # (stage names from field_semantics.yaml: closedwon or aliases)
        won_stages = ['closedwon', '1297321623']
        won_deals = [
            d for d in all_deals
            if d.get('pipeline_id') == 'default'
            and d.get('stage') in won_stages
            and d.get('deal_value')
            and d['deal_value'] > 0
        ]

        won_values = [d['deal_value'] for d in won_deals]

        # Get week-3 snapshot (default pipeline)
        week3_deals = select_all(
            sb, 'deals_snapshot',
            columns='deal_value',
            filters=[
                ('eq', 'pipeline_id', 'default'),
                ('eq', 'week_of_quarter', 3),
                ('eq', 'fiscal_quarter', quarter)
            ]
        )

        pipeline_values = [
            d['deal_value'] for d in week3_deals
            if d.get('deal_value') and d['deal_value'] > 0
        ]

        if won_values and pipeline_values:
            avg_won = sum(won_values) / len(won_values)
            avg_pipeline = sum(pipeline_values) / len(pipeline_values)
            diff_pct = ((avg_won - avg_pipeline) / avg_pipeline * 100) if avg_pipeline else 0

            biases.append(diff_pct)

            print(f"{quarter}:")
            print(f"  Won deals:       n={len(won_values):3d}  "
                  f"avg=${avg_won:>9,.0f}  "
                  f"[${min(won_values):>7,.0f}-${max(won_values):>9,.0f}]")
            print(f"  Week-3 pipeline: n={len(pipeline_values):3d}  "
                  f"avg=${avg_pipeline:>9,.0f}  "
                  f"[${min(pipeline_values):>7,.0f}-${max(pipeline_values):>9,.0f}]")
            print(f"  Bias: {diff_pct:+.1f}% "
                  f"({'LARGER' if diff_pct > 0 else 'smaller'} deals win)")
            print()
        else:
            print(f"{quarter}: Insufficient data")
            print()

    if biases:
        avg_bias = sum(biases) / len(biases)
        bias_range = max(biases) - min(biases)

        print("="*70)
        print("SUMMARY")
        print("="*70)
        print(f"Average bias across {len(biases)} quarters: {avg_bias:+.1f}%")
        print(f"Bias range: {bias_range:.1f}pp")
        print()

        if abs(avg_bias) > 10:
            print(f"⚠️  MATERIAL BIAS DETECTED: {avg_bias:+.1f}%")
            print()
            print("Won deals consistently skew " +
                  ("LARGER" if avg_bias > 0 else "smaller") +
                  " than pipeline.")
            print()
            print("RECOMMENDATION:")
            print("  Use won-deal average in compute_forecast.py instead of")
            print("  week-3 pipeline average. Current Kellogg forecast is")
            print(f"  {'under' if avg_bias > 0 else 'over'}stating by ~{abs(avg_bias):.0f}%.")
            print()
            print("  Update line ~XX in compute_forecast.py:")
            print("    # Get won-deal average for this pipeline (not week-3 avg)")
            print("    won_deals = [d for d in deals if d.stage in won_stages")
            print("                 and d.pipeline_id == pipeline_id]")
            print("    avg_won_size = sum(d.deal_value for d in won_deals) / len(won_deals)")
            print("    # Use avg_won_size instead of week3_avg_size")
        elif abs(avg_bias) > 5:
            print(f"⚠️  MODEST BIAS: {avg_bias:+.1f}%")
            print()
            print("Bias is detectable but not severe. Monitor over time.")
            print("If it persists >10%, switch to won-deal average.")
        else:
            print("✓ NO MATERIAL BIAS")
            print()
            print("Won deals have similar average size to week-3 pipeline.")
            print("Using week-3 pipeline average is unbiased. No change needed.")


if __name__ == '__main__':
    main()
