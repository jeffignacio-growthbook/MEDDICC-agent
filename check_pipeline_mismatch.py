#!/usr/bin/env python3
"""Check pipeline vs pipeline_id field discrepancy on renewal deals."""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from supabase import create_client

def main():
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Blast radius: renewal stage IDs across pipeline vs pipeline_id
    print("=== Blast Radius: Renewal Stages by pipeline vs pipeline_id ===\n")

    renewal_stages = ['1297321618', '1297321619', '1297321620', '1297321623', '1297321624']

    result = sb.table('deals').select(
        'pipeline, pipeline_id, stage, deal_value'
    ).in_('stage', renewal_stages).execute()

    if not result.data:
        print("No deals found in renewal stages")
        return

    # Group by (pipeline, pipeline_id, stage)
    from collections import defaultdict
    groups = defaultdict(lambda: {'count': 0, 'value': 0.0})

    for d in result.data:
        pipeline = d.get('pipeline', 'NULL')
        pipeline_id = d.get('pipeline_id', 'NULL')
        stage = d.get('stage', 'NULL')
        key = (pipeline, pipeline_id, stage)
        groups[key]['count'] += 1
        groups[key]['value'] += float(d.get('deal_value') or 0)

    print(f"{'pipeline':<15} {'pipeline_id':<15} {'stage':<15} {'count':<8} {'sum(deal_value)':<15}")
    print("-" * 75)

    for (pipeline, pipeline_id, stage), data in sorted(groups.items(), key=lambda x: x[1]['count'], reverse=True):
        print(f"{str(pipeline):<15} {str(pipeline_id):<15} {str(stage):<15} "
              f"{data['count']:<8} ${data['value']:>13,.0f}")

    print()

    # Check if pipeline and pipeline_id ever differ
    print("\n=== Field Comparison: pipeline vs pipeline_id (All Deals) ===\n")

    all_deals = sb.table('deals').select('pipeline, pipeline_id').execute()

    matches = 0
    mismatches = []

    for d in all_deals.data:
        pipeline = d.get('pipeline')
        pipeline_id = d.get('pipeline_id')

        if str(pipeline) == str(pipeline_id):
            matches += 1
        else:
            mismatches.append({
                'pipeline': pipeline,
                'pipeline_id': pipeline_id
            })

    print(f"Total deals: {len(all_deals.data)}")
    print(f"Matches (pipeline == pipeline_id): {matches}")
    print(f"Mismatches (pipeline != pipeline_id): {len(mismatches)}\n")

    if mismatches:
        print("Sample mismatches (first 10):")
        print(f"{'pipeline':<20} {'pipeline_id':<20}")
        print("-" * 45)
        for m in mismatches[:10]:
            print(f"{str(m['pipeline']):<20} {str(m['pipeline_id']):<20}")

    # Check what renewals handler actually filters on
    print("\n\n=== Renewals Handler Behavior ===\n")

    # Simulate renewals handler filter: pipeline=eq.866608541
    renewals_by_pipeline = sb.table('deals').select('deal_id, stage, pipeline, pipeline_id').eq(
        'pipeline', '866608541'
    ).execute()

    # Simulate if it used pipeline_id instead
    renewals_by_pipeline_id = sb.table('deals').select('deal_id, stage, pipeline, pipeline_id').eq(
        'pipeline_id', '866608541'
    ).execute()

    print(f"Filtering pipeline=eq.866608541: {len(renewals_by_pipeline.data)} deals")
    print(f"Filtering pipeline_id=eq.866608541: {len(renewals_by_pipeline_id.data)} deals")

    if len(renewals_by_pipeline.data) != len(renewals_by_pipeline_id.data):
        print(f"\n⚠️  DIFFERENT RESULTS — pipeline and pipeline_id are NOT consistent")
        print(f"   Difference: {abs(len(renewals_by_pipeline.data) - len(renewals_by_pipeline_id.data))} deals")
    else:
        print(f"\n✓ Same count — fields may be consistent")

    # Show which field has renewal stages
    renewal_stage_count_pipeline = sum(1 for d in renewals_by_pipeline.data if d.get('stage') in renewal_stages)
    renewal_stage_count_pipeline_id = sum(1 for d in renewals_by_pipeline_id.data if d.get('stage') in renewal_stages)

    print(f"\nDeals with renewal stages when filtering pipeline=866608541: {renewal_stage_count_pipeline}")
    print(f"Deals with renewal stages when filtering pipeline_id=866608541: {renewal_stage_count_pipeline_id}")

    # Check ETL source
    print("\n\n=== Which Field is Authoritative? ===\n")
    print("Checking ETL and handler usage...\n")

    # The renewals handler uses: pipeline=eq.866608541
    # If that works, pipeline is authoritative
    # If pipeline_id is wrong, ETL may be writing pipeline correctly but defaulting pipeline_id

if __name__ == '__main__':
    main()
