#!/usr/bin/env python3
"""
Isolate Snapshot Exclusion Condition

25 deals with 14-90 day cycles are completely missing from snapshot data.
Find the EXACT condition causing them to be skipped by the snapshot job.

Check:
1. Current deal properties (stage, status, archived, etc.)
2. Null fields that might be required by snapshot job
3. Creation timing relative to snapshot schedule
4. Common attributes across all 25 deals
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent))

from api.db import get_supabase
from api.field_semantics import is_won


def main():
    supabase = get_supabase()

    print("=" * 80)
    print("ISOLATE SNAPSHOT EXCLUSION CONDITION")
    print("=" * 80)
    print()

    FISCAL_QUARTERS = [
        ('FY2026 Q3', '2025-11-01', '2026-01-31'),
        ('FY2026 Q4', '2026-02-01', '2026-04-30'),
        ('FY2027 Q1', '2026-05-01', '2026-07-31'),
    ]

    # Get the 25 genuinely missing deals
    print("Step 1: Get full details for 25 missing deals")
    print("-" * 80)

    missing_deals = []

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        # Get wins
        deals_resp = supabase.table('deals') \
            .select('*') \
            .eq('pipeline_id', 'default') \
            .gte('close_date', start_date) \
            .lte('close_date', end_date) \
            .execute()

        for deal in deals_resp.data:
            stage = deal.get('stage')
            if not stage or not is_won(str(stage)):
                continue

            deal_id = str(deal['deal_id'])

            # Check cycle length
            create_date = deal.get('create_date')
            close_date = deal.get('close_date')

            if not create_date or not close_date:
                continue

            try:
                create_dt = datetime.fromisoformat(create_date[:10])
                close_dt = datetime.fromisoformat(close_date[:10])
                cycle_days = (close_dt - create_dt).days
            except:
                continue

            if cycle_days < 14:
                continue

            # Check if in snapshots
            snapshot_resp = supabase.table('deals_snapshot') \
                .select('deal_id', count='exact') \
                .eq('fiscal_quarter', quarter_id) \
                .eq('deal_id', deal_id) \
                .limit(1) \
                .execute()

            if (snapshot_resp.count or 0) == 0:
                missing_deals.append({
                    **deal,
                    'quarter_id': quarter_id,
                    'cycle_days': cycle_days
                })

    print(f"Found {len(missing_deals)} missing deals")
    print()

    if not missing_deals:
        print("No missing deals - exiting")
        return

    # Analyze common properties
    print("Step 2: Analyze common properties")
    print("-" * 80)
    print()

    # Check for null fields
    all_fields = set()
    for deal in missing_deals:
        all_fields.update(deal.keys())

    null_field_counts = {field: 0 for field in all_fields}

    for deal in missing_deals:
        for field in all_fields:
            if deal.get(field) is None or deal.get(field) == '':
                null_field_counts[field] += 1

    # Report fields that are frequently null
    print("Fields with high null rates:")
    print()
    frequent_nulls = {k: v for k, v in null_field_counts.items()
                      if v > len(missing_deals) * 0.5}  # >50% null

    if frequent_nulls:
        for field, count in sorted(frequent_nulls.items(), key=lambda x: -x[1]):
            pct = count / len(missing_deals) * 100
            print(f"  {field:30s}: {count}/{len(missing_deals)} ({pct:.0f}%) null")
    else:
        print("  No fields with >50% null rate")

    print()

    # Check for common non-null values
    print("Common property values:")
    print()

    # Check specific fields that might affect snapshot capture
    key_fields = ['deal_status', 'pipeline_id', 'stage', 'is_deleted', 'archived']

    for field in key_fields:
        if field not in all_fields:
            continue

        values = [str(deal.get(field, 'NULL')) for deal in missing_deals]
        unique_values = set(values)

        if len(unique_values) <= 5:  # Show if few unique values
            value_counts = {v: values.count(v) for v in unique_values}
            print(f"  {field}:")
            for val, count in sorted(value_counts.items(), key=lambda x: -x[1]):
                print(f"    {val}: {count}/{len(missing_deals)}")
        print()

    # Check creation dates relative to quarter start
    print("Creation timing relative to quarter:")
    print()

    for deal in missing_deals[:10]:
        company = deal.get('company_name', 'Unknown')
        create_date = deal.get('create_date')
        quarter_id = deal.get('quarter_id')

        # Get quarter start for this deal
        quarter_start = next((q[1] for q in FISCAL_QUARTERS if q[0] == quarter_id), None)

        if create_date and quarter_start:
            try:
                create_dt = datetime.fromisoformat(create_date[:10])
                quarter_dt = datetime.fromisoformat(quarter_start)
                days_offset = (create_dt - quarter_dt).days

                print(f"  {company:30s} | Created {days_offset:>4d} days after Q start | {quarter_id}")
            except:
                pass

    print()

    # Compare to deals that ARE in snapshots
    print()
    print("Step 3: Compare to deals that ARE in snapshots")
    print("-" * 80)
    print()

    # Get a sample of deals that ARE in snapshots
    in_snapshots_sample = []

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        snapshot_resp = supabase.table('deals_snapshot') \
            .select('deal_id') \
            .eq('fiscal_quarter', quarter_id) \
            .eq('pipeline_id', 'default') \
            .limit(10) \
            .execute()

        deal_ids = [str(s['deal_id']) for s in snapshot_resp.data]

        if deal_ids:
            deals_resp = supabase.table('deals') \
                .select('*') \
                .in_('deal_id', deal_ids[:5]) \
                .execute()

            in_snapshots_sample.extend(deals_resp.data)

    print(f"Sample of {len(in_snapshots_sample)} deals that ARE in snapshots")
    print()

    # Check same key fields for comparison
    print("Comparison of key fields:")
    print()

    for field in key_fields:
        if field not in all_fields:
            continue

        # Missing deals
        missing_values = [str(deal.get(field, 'NULL')) for deal in missing_deals]
        missing_unique = set(missing_values)

        # In-snapshot deals
        in_values = [str(deal.get(field, 'NULL')) for deal in in_snapshots_sample]
        in_unique = set(in_values)

        print(f"{field}:")
        print(f"  Missing deals: {', '.join(sorted(missing_unique)[:3])}")
        print(f"  In snapshots:  {', '.join(sorted(in_unique)[:3])}")

        # Check for differences
        only_missing = missing_unique - in_unique
        only_in_snapshots = in_unique - missing_unique

        if only_missing:
            print(f"  → Only in missing: {', '.join(sorted(only_missing))}")
        if only_in_snapshots:
            print(f"  → Only in snapshots: {', '.join(sorted(only_in_snapshots))}")

        print()

    # HYPOTHESIS TESTING
    print()
    print("=" * 80)
    print("HYPOTHESIS TESTING")
    print("=" * 80)
    print()

    hypotheses = []

    # H1: Deals created too late in quarter
    late_created = sum(1 for d in missing_deals
                       if d.get('create_date') and d.get('quarter_id'))

    print("H1: Deals created late in quarter (after week 13)")
    print("   Status: Testing...")

    # Check if any were created after week 13 of their quarter
    for deal in missing_deals:
        create_date = deal.get('create_date')
        quarter_id = deal.get('quarter_id')
        quarter_start = next((q[1] for q in FISCAL_QUARTERS if q[0] == quarter_id), None)

        if create_date and quarter_start:
            try:
                create_dt = datetime.fromisoformat(create_date[:10])
                quarter_dt = datetime.fromisoformat(quarter_start)
                days_since_start = (create_dt - quarter_dt).days
                weeks_since_start = days_since_start // 7

                if weeks_since_start > 13:
                    hypotheses.append("H1: Some deals created after week 13")
                    break
            except:
                pass

    # H2: Specific field null
    for field, count in frequent_nulls.items():
        if count == len(missing_deals):
            hypotheses.append(f"H2: All missing deals have NULL {field}")

    # H3: Specific field value
    for field in key_fields:
        if field in all_fields:
            values = [str(deal.get(field)) for deal in missing_deals]
            if len(set(values)) == 1:
                value = values[0]
                hypotheses.append(f"H3: All missing deals have {field}={value}")

    print()
    print("VIABLE HYPOTHESES:")
    for h in hypotheses:
        print(f"  • {h}")

    if not hypotheses:
        print("  No clear pattern identified - need manual investigation")

    print()


if __name__ == '__main__':
    main()
