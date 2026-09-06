#!/usr/bin/env python3
"""
Check Pipeline Migration Hypothesis

For the 22 "long cycle but not in snapshots" deals, check if they appear in
snapshot data with ANY pipeline_id (not just 'default').

If yes: Pipeline migration issue (deals start in other pipelines, move to default late)
If no: Genuine gap (deals missing from snapshots entirely)
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent))

from api.db import get_supabase
from api.field_semantics import is_won


def days_between(start_str, end_str):
    if not start_str or not end_str:
        return None
    try:
        from datetime import datetime
        start = datetime.fromisoformat(start_str[:10])
        end = datetime.fromisoformat(end_str[:10])
        return (end - start).days
    except:
        return None


def main():
    supabase = get_supabase()

    print("=" * 80)
    print("PIPELINE MIGRATION CHECK")
    print("=" * 80)
    print()

    FISCAL_QUARTERS = [
        ('FY2026 Q3', '2025-11-01', '2026-01-31'),
        ('FY2026 Q4', '2026-02-01', '2026-04-30'),
        ('FY2027 Q1', '2026-05-01', '2026-07-31'),
    ]

    # Step 1: Get all wins that are NOT in default pipeline snapshots
    print("Step 1: Identify wins not in default pipeline snapshots")
    print("-" * 80)

    wins_not_in_default_snapshots = []

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        # Get wins
        deals_resp = supabase.table('deals') \
            .select('deal_id, company_name, stage, close_date, create_date') \
            .eq('pipeline_id', 'default') \
            .gte('close_date', start_date) \
            .lte('close_date', end_date) \
            .execute()

        for deal in deals_resp.data:
            stage = deal.get('stage')
            if not stage or not is_won(str(stage)):
                continue

            deal_id = str(deal['deal_id'])

            # Check if in default snapshots
            snapshot_resp = supabase.table('deals_snapshot') \
                .select('deal_id', count='exact') \
                .eq('fiscal_quarter', quarter_id) \
                .eq('pipeline_id', 'default') \
                .eq('deal_id', deal_id) \
                .limit(1) \
                .execute()

            if (snapshot_resp.count or 0) == 0:
                create_date = deal.get('create_date')
                close_date = deal.get('close_date')
                cycle_days = days_between(create_date, close_date)

                # Only include long-cycle deals (≥ 14 days)
                if cycle_days is not None and cycle_days >= 14:
                    wins_not_in_default_snapshots.append({
                        'deal_id': deal_id,
                        'company_name': deal.get('company_name'),
                        'close_date': close_date,
                        'create_date': create_date,
                        'cycle_days': cycle_days,
                        'quarter_id': quarter_id
                    })

    print(f"Found {len(wins_not_in_default_snapshots)} long-cycle wins not in default snapshots")
    print()

    if not wins_not_in_default_snapshots:
        print("No deals to check - exiting")
        return

    # Step 2: Check if these deals appear in snapshots with ANY pipeline_id
    print("Step 2: Check if deals appear in snapshots with ANY pipeline_id")
    print("-" * 80)
    print()

    pipeline_migration_deals = []
    genuinely_missing_deals = []

    for win in wins_not_in_default_snapshots:
        deal_id = win['deal_id']
        quarter_id = win['quarter_id']
        company = win['company_name']

        # Check for ANY pipeline_id
        snapshot_resp = supabase.table('deals_snapshot') \
            .select('deal_id, pipeline_id, week_of_quarter, stage_id') \
            .eq('fiscal_quarter', quarter_id) \
            .eq('deal_id', deal_id) \
            .execute()

        if snapshot_resp.data:
            # Deal exists in snapshots, but with different pipeline_id
            pipelines_seen = set(str(s.get('pipeline_id')) for s in snapshot_resp.data)
            weeks_seen = sorted(set(s.get('week_of_quarter') for s in snapshot_resp.data))

            pipeline_migration_deals.append({
                **win,
                'other_pipelines': list(pipelines_seen),
                'weeks_in_other_pipeline': weeks_seen,
                'snapshot_count': len(snapshot_resp.data)
            })
        else:
            # Deal genuinely missing from all snapshots
            genuinely_missing_deals.append(win)

    # REPORT
    print()
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print()

    print(f"Total long-cycle deals checked: {len(wins_not_in_default_snapshots)}")
    print(f"Pipeline migration: {len(pipeline_migration_deals)} ({len(pipeline_migration_deals)/len(wins_not_in_default_snapshots)*100:.1f}%)")
    print(f"Genuinely missing: {len(genuinely_missing_deals)} ({len(genuinely_missing_deals)/len(wins_not_in_default_snapshots)*100:.1f}%)")
    print()

    if pipeline_migration_deals:
        print()
        print("PIPELINE MIGRATION DEALS")
        print("-" * 80)
        print()
        print("These deals appear in snapshots with OTHER pipeline_ids:")
        print()

        for deal in pipeline_migration_deals[:10]:
            print(f"{deal['company_name']:30s} | {deal['cycle_days']} days | {deal['quarter_id']}")
            print(f"  Other pipelines: {', '.join(deal['other_pipelines'])}")
            print(f"  Weeks seen: {', '.join(map(str, deal['weeks_in_other_pipeline']))}")
            print(f"  Snapshot count: {deal['snapshot_count']}")
            print()

        if len(pipeline_migration_deals) > 10:
            print(f"... and {len(pipeline_migration_deals) - 10} more")
            print()

        # Determine if migration is normal pattern
        print()
        print("MIGRATION PATTERN ANALYSIS")
        print("-" * 80)
        print()

        # Count unique source pipelines
        all_source_pipelines = set()
        for deal in pipeline_migration_deals:
            all_source_pipelines.update(deal['other_pipelines'])

        print(f"Unique source pipelines: {len(all_source_pipelines)}")
        for pipeline in sorted(all_source_pipelines):
            count = sum(1 for d in pipeline_migration_deals if pipeline in d['other_pipelines'])
            pct = count / len(pipeline_migration_deals) * 100
            print(f"  {pipeline}: {count} deals ({pct:.1f}%)")

        print()

        # Check timing of migration (early weeks vs late weeks)
        early_weeks = sum(1 for d in pipeline_migration_deals if max(d['weeks_in_other_pipeline']) <= 5)
        late_weeks = sum(1 for d in pipeline_migration_deals if min(d['weeks_in_other_pipeline']) >= 8)

        print(f"Timing of snapshot appearances in other pipeline:")
        print(f"  Early weeks (1-5): {early_weeks} deals")
        print(f"  Late weeks (8-13): {late_weeks} deals")
        print(f"  Spanning early and late: {len(pipeline_migration_deals) - early_weeks - late_weeks} deals")

    if genuinely_missing_deals:
        print()
        print("GENUINELY MISSING DEALS")
        print("-" * 80)
        print()
        print("These deals do NOT appear in ANY pipeline snapshots:")
        print()

        for deal in genuinely_missing_deals[:10]:
            print(f"{deal['company_name']:30s} | {deal['cycle_days']} days | {deal['quarter_id']}")
            print(f"  Created: {deal['create_date']}, Closed: {deal['close_date']}")
            print()

        if len(genuinely_missing_deals) > 10:
            print(f"... and {len(genuinely_missing_deals) - 10} more")

    # CONCLUSION
    print()
    print("=" * 80)
    print("CONCLUSION")
    print("=" * 80)
    print()

    if len(pipeline_migration_deals) > len(genuinely_missing_deals):
        print("✓ PRIMARY ISSUE: Pipeline Migration")
        print()
        print("Most long-cycle 'missing' wins are actually in snapshots, just with")
        print("different pipeline_ids. They migrate to 'default' late in their lifecycle.")
        print()
        print("NEXT STEPS:")
        print("  1. Audit all scripts filtering deals_snapshot by pipeline_id='default'")
        print("  2. Determine if migration is normal/expected pattern or data inconsistency")
        print("  3. If normal: adjust queries to track deals across pipeline transitions")
        print("  4. If inconsistency: fix pipeline assignment process upstream")
    elif len(genuinely_missing_deals) > len(pipeline_migration_deals):
        print("✓ PRIMARY ISSUE: Genuine Snapshot Gap")
        print()
        print("Most long-cycle 'missing' wins are NOT in snapshots with any pipeline_id.")
        print()
        print("NEXT STEPS:")
        print("  1. Isolate EXACT condition causing deals to be skipped")
        print("  2. Check for: specific stage? null field? timing issue?")
        print("  3. Get precise, falsifiable root cause before writing to backlog")
    else:
        print("~ MIXED: Both issues present")
        print()
        print("Need to address both pipeline migration AND genuine snapshot gaps")

    print()


if __name__ == '__main__':
    main()
