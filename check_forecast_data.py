#!/usr/bin/env python3
"""Check forecast_weekly table contents and stage probability alignment."""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from supabase import create_client
from utils import load_client_config

def main():
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    config = load_client_config()

    # Check forecast_weekly contents
    print("=== forecast_weekly Table Contents ===\n")
    result = sb.table('forecast_weekly').select(
        'fiscal_quarter, week_ending, open_pipeline_value, '
        'stage_weighted_forecast, category_weighted_forecast, uncategorized_value'
    ).order('week_ending', desc=True).limit(10).execute()

    if not result.data:
        print('⚠️  forecast_weekly is EMPTY — no data exists\n')
        print('Run: python scripts/analytics/compute_forecast.py')
        print('OR trigger: Actions → Recompute Forecast → Run workflow\n')
    else:
        print(f'Found {len(result.data)} rows:\n')
        for row in result.data:
            print(f"{row['fiscal_quarter']:12} {row['week_ending']:12} "
                  f"open=${row['open_pipeline_value']:>10,.0f}  "
                  f"stage-wtd=${row['stage_weighted_forecast']:>10,.0f}  "
                  f"cat-wtd=${row['category_weighted_forecast']:>10,.0f}  "
                  f"uncategorized=${row['uncategorized_value']:>10,.0f}")

    # Check stage probability alignment
    print("\n\n=== Stage Probability Alignment ===\n")

    for p in config.get('pipeline', {}).get('pipelines', []):
        pipeline_id = p.get('id', 'default')
        print(f"Pipeline: {pipeline_id}")
        print(f"{'Stage Name':<30} {'Stage ID':<15} {'Probability':<12}")
        print("-" * 60)

        for s in p.get('stages', []):
            stage_id = s.get('id')
            stage_name = s.get('name', 'UNNAMED')
            prob = s.get('stage_probability', 'NOT SET')
            print(f"{stage_name:<30} {str(stage_id):<15} {str(prob):<12}")

        print()

    # Check actual stage distribution in deals
    print("\n=== Actual Deals by Stage (Active Only) ===\n")
    deals = sb.table('deals').select('stage, deal_status').execute()

    active_deals = [d for d in deals.data if d.get('deal_status') == 'active']

    from collections import Counter
    stage_counts = Counter(d['stage'] for d in active_deals if d.get('stage'))

    print(f"{'Stage ID':<15} {'Count':<10}")
    print("-" * 25)
    for stage_id, count in stage_counts.most_common():
        print(f"{str(stage_id):<15} {count:<10}")

    # Check for unmapped stages
    print("\n\n=== Stage Mapping Validation ===\n")

    prob_map = {}
    for p in config.get('pipeline', {}).get('pipelines', []):
        for s in p.get('stages', []):
            prob_map[(p['id'], s['id'])] = s.get('stage_probability')

    unmapped_stages = set()
    for d in active_deals:
        stage_id = d.get('stage')
        pipeline_id = d.get('pipeline_id', 'default')
        if stage_id and (pipeline_id, stage_id) not in prob_map:
            unmapped_stages.add((pipeline_id, stage_id))

    if unmapped_stages:
        print("⚠️  UNMAPPED STAGES (will get 0.0 probability):\n")
        for pipeline_id, stage_id in sorted(unmapped_stages):
            count = sum(1 for d in active_deals
                       if d.get('stage') == stage_id
                       and d.get('pipeline_id', 'default') == pipeline_id)
            print(f"  Pipeline: {pipeline_id}, Stage ID: {stage_id} ({count} deals)")

        total_unmapped = sum(1 for d in active_deals
                            if d.get('stage') and
                            (d.get('pipeline_id', 'default'), d['stage']) not in prob_map)
        total_active = len(active_deals)
        pct_unmapped = (total_unmapped / total_active * 100) if total_active > 0 else 0

        print(f"\n  {total_unmapped}/{total_active} active deals ({pct_unmapped:.1f}%) in unmapped stages")
        print(f"  → stage_weighted_forecast will UNDERSTATE by however much value sits in these stages")
    else:
        print("✓ All active deal stages have probability mappings")

if __name__ == '__main__':
    main()
