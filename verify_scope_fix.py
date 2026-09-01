#!/usr/bin/env python3
"""Verify query_waterfall scope filter fix and report exclusion counts."""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'api'))

from supabase import create_client
from analytics.point_in_time import load_scope_config, is_deal_in_analytics_scope

def main():
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Load scope config
    excluded_pipelines, stage_cfg = load_scope_config()

    print("=== Scope Filter Configuration ===\n")
    print(f"Excluded pipelines: {excluded_pipelines}")
    print(f"Stage configurations loaded: {len(stage_cfg)}")
    print()

    # Query all active deals (what query_waterfall sees)
    active_deals = sb.table('deals').select(
        'deal_id, stage, pipeline_id, arr_usd'
    ).eq('deal_status', 'active').execute()

    before_count = len(active_deals.data)
    before_arr = sum(d.get('arr_usd') or 0 for d in active_deals.data)

    print(f"=== Before Filter ===")
    print(f"Total active deals: {before_count}")
    print(f"Total ARR: ${before_arr:,.0f}\n")

    # Apply pipeline exclusion only
    after_pipeline = [
        d for d in active_deals.data
        if str(d.get('pipeline_id', 'default')) not in excluded_pipelines
    ]

    after_pipeline_count = len(after_pipeline)
    after_pipeline_arr = sum(d.get('arr_usd') or 0 for d in after_pipeline)

    print(f"=== After Renewal Exclusion ===")
    print(f"Deals remaining: {after_pipeline_count}")
    print(f"ARR remaining: ${after_pipeline_arr:,.0f}")
    print(f"Excluded: {before_count - after_pipeline_count} deals, "
          f"${before_arr - after_pipeline_arr:,.0f}\n")

    # Apply full scope filter (pipeline + qualification gate)
    after_qualified = [
        d for d in active_deals.data
        if is_deal_in_analytics_scope(
            d.get('stage'),
            d.get('pipeline_id'),
            excluded_pipelines,
            stage_cfg
        )
    ]

    after_qualified_count = len(after_qualified)
    after_qualified_arr = sum(d.get('arr_usd') or 0 for d in after_qualified)

    print(f"=== After Qualification Gate ===")
    print(f"Deals remaining: {after_qualified_count}")
    print(f"ARR remaining: ${after_qualified_arr:,.0f}")
    print(f"Excluded by qualification: {after_pipeline_count - after_qualified_count} deals, "
          f"${after_pipeline_arr - after_qualified_arr:,.0f}\n")

    # Show which deals were excluded by qualification gate
    qualified_ids = {d['deal_id'] for d in after_qualified}
    excluded_by_qualification = [
        d for d in after_pipeline
        if d['deal_id'] not in qualified_ids
    ]

    if excluded_by_qualification:
        print(f"=== Deals Excluded by Qualification Gate ===\n")
        from collections import Counter
        stage_counts = Counter(d.get('stage') for d in excluded_by_qualification)

        for stage_id, count in stage_counts.most_common():
            stage_name = stage_cfg.get(str(stage_id), {}).get('name', stage_id)
            stage_order = stage_cfg.get(str(stage_id), {}).get('order', '?')
            arr = sum(d.get('arr_usd') or 0 for d in excluded_by_qualification if d.get('stage') == stage_id)
            print(f"  {stage_name} (order {stage_order}): {count} deals, ${arr:,.0f}")

    # Summary
    print(f"\n=== Summary ===")
    print(f"before:                      {before_count:3} deals, ${before_arr:>13,.0f}")
    print(f"after renewal exclusion:     {after_pipeline_count:3} deals, ${after_pipeline_arr:>13,.0f}")
    print(f"after qualification gate:    {after_qualified_count:3} deals, ${after_qualified_arr:>13,.0f}")

if __name__ == '__main__':
    main()
