#!/usr/bin/env python3
"""
Audit Data Quality Errors: 8 Deals with Impossible Timelines

Identify deals with 0-day or negative create-to-close cycles, check for
patterns (bulk import, manual entry, migration), and either fix timestamps
or flag for exclusion across all scripts/dashboards.
"""

import os
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent))

from api.db import get_supabase
from api.field_semantics import is_won


FISCAL_QUARTERS = [
    ('FY2026 Q3', '2025-11-01', '2026-01-31'),
    ('FY2026 Q4', '2026-02-01', '2026-04-30'),
    ('FY2027 Q1', '2026-05-01', '2026-07-31'),
]


def days_between(start_str, end_str):
    if not start_str or not end_str:
        return None
    try:
        start = datetime.fromisoformat(start_str[:10])
        end = datetime.fromisoformat(end_str[:10])
        return (end - start).days
    except:
        return None


def main():
    supabase = get_supabase()

    print("=" * 80)
    print("DATA QUALITY AUDIT: Impossible Timeline Deals")
    print("=" * 80)
    print()

    # Step 1: Find all deals with 0-day or negative cycles
    data_quality_errors = []

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
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
            create_date = deal.get('create_date')
            close_date = deal.get('close_date')

            if not create_date or not close_date:
                data_quality_errors.append({
                    'deal_id': deal_id,
                    'company_name': deal.get('company_name'),
                    'create_date': create_date,
                    'close_date': close_date,
                    'cycle_days': None,
                    'error_type': 'NULL_DATES',
                    'quarter_id': quarter_id,
                    'deal': deal
                })
                continue

            cycle_days = days_between(create_date, close_date)

            if cycle_days is not None and cycle_days <= 0:
                error_type = 'ZERO_DAY' if cycle_days == 0 else 'NEGATIVE_CYCLE'
                data_quality_errors.append({
                    'deal_id': deal_id,
                    'company_name': deal.get('company_name'),
                    'create_date': create_date,
                    'close_date': close_date,
                    'cycle_days': cycle_days,
                    'error_type': error_type,
                    'quarter_id': quarter_id,
                    'deal': deal
                })

    print(f"Found {len(data_quality_errors)} deals with data quality issues")
    print()

    # Step 2: Categorize by error type
    by_type = defaultdict(list)
    for err in data_quality_errors:
        by_type[err['error_type']].append(err)

    print("Error Type Breakdown:")
    print("-" * 80)
    for error_type in ['NEGATIVE_CYCLE', 'ZERO_DAY', 'NULL_DATES']:
        count = len(by_type[error_type])
        if count > 0:
            print(f"{error_type:20s}: {count} deals")
    print()

    # Step 3: Analyze patterns
    print()
    print("=" * 80)
    print("PATTERN ANALYSIS")
    print("=" * 80)
    print()

    # Check creation timestamps for clustering (bulk import indicator)
    print("Creation timestamp clustering:")
    print("-" * 80)

    creation_timestamps = []
    for err in data_quality_errors:
        create_datetime = err['deal'].get('create_date')
        if create_datetime and 'T' in str(create_datetime):
            try:
                dt = datetime.fromisoformat(str(create_datetime).replace('Z', '+00:00'))
                creation_timestamps.append({
                    'deal_id': err['deal_id'],
                    'company_name': err['company_name'],
                    'datetime': dt,
                    'date': dt.strftime('%Y-%m-%d'),
                    'time': dt.strftime('%H:%M:%S'),
                    'hour': dt.strftime('%H')
                })
            except:
                pass

    if creation_timestamps:
        # Group by date
        by_date = defaultdict(list)
        for ts in creation_timestamps:
            by_date[ts['date']].append(ts)

        print("\nCreation dates:")
        for date in sorted(by_date.keys()):
            deals = by_date[date]
            print(f"  {date}: {len(deals)} deals")
            for deal in deals:
                print(f"    {deal['time']} - {deal['company_name']} ({deal['deal_id']})")

        # Check if clustered in same hour (suggests bulk import)
        by_hour = defaultdict(list)
        for ts in creation_timestamps:
            by_hour[ts['date'] + ' ' + ts['hour']].append(ts)

        max_in_hour = max(len(deals) for deals in by_hour.values())
        if max_in_hour >= len(data_quality_errors) * 0.5:
            print(f"\n  → {max_in_hour}/{len(data_quality_errors)} deals created in same hour (likely bulk import)")
        else:
            print(f"\n  → Scattered across dates/times (likely manual entries)")
    else:
        print("  No timestamp data available")

    print()

    # Check for source fields
    print("\nSource field analysis:")
    print("-" * 80)

    sample_deal = data_quality_errors[0]['deal']
    all_fields = set(sample_deal.keys())

    source_fields = [
        'hs_object_source', 'hs_object_source_id', 'hs_object_source_label',
        'hs_created_by_user_id', 'created_by', 'source', 'deal_source'
    ]

    existing_source_fields = [f for f in source_fields if f in all_fields]

    if existing_source_fields:
        for field in existing_source_fields:
            values = defaultdict(list)
            for err in data_quality_errors:
                value = err['deal'].get(field)
                if value is not None:
                    values[str(value)].append(err)

            if values:
                print(f"\n{field}:")
                for value, deals_list in sorted(values.items(), key=lambda x: -len(x[1])):
                    print(f"  {value}: {len(deals_list)} deals")
    else:
        print("  No source fields populated")

    print()

    # Step 4: Print full list
    print()
    print("=" * 80)
    print("COMPLETE LIST OF DATA QUALITY ERRORS")
    print("=" * 80)
    print()

    print(f"{'Company':30s} | {'Deal ID':10s} | {'Create':10s} | {'Close':10s} | {'Days':>5s} | {'Type':15s}")
    print("-" * 100)

    for err in sorted(data_quality_errors, key=lambda x: (x['error_type'], x.get('cycle_days', 999), x['company_name'])):
        company = (err['company_name'] or 'Unknown')[:28]
        deal_id = err['deal_id'][:10]
        create = err['create_date'][:10] if err['create_date'] else 'NULL'
        close = err['close_date'][:10] if err['close_date'] else 'NULL'
        days = str(err['cycle_days']) if err['cycle_days'] is not None else 'NULL'
        error_type = err['error_type']

        print(f"{company:30s} | {deal_id:10s} | {create:10s} | {close:10s} | {days:>5s} | {error_type:15s}")

    print()

    # Step 5: Recommendation
    print()
    print("=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)
    print()

    print("Based on pattern analysis:")
    print()

    if creation_timestamps:
        by_date = defaultdict(list)
        for ts in creation_timestamps:
            by_date[ts['date']].append(ts)

        if len(by_date) <= 2:
            print("✓ CLUSTERED TIMESTAMPS - Likely bulk import or migration")
            print("  → Check if these came from a specific data migration")
            print("  → If migration artifact, investigate source system for correct dates")
            print("  → If not recoverable, flag permanently")
        else:
            print("✗ SCATTERED TIMESTAMPS - Likely manual entry errors")
            print("  → Individual data entry mistakes")
            print("  → Unlikely to have correct source data")
            print("  → Recommend flagging rather than attempting to fix")

    print()
    print("Action items:")
    print("1. Create data_quality_exclusions table to track these deals")
    print("2. Add to all metric queries: WHERE deal_id NOT IN (data_quality_exclusions)")
    print("3. Periodic review to see if new deals appear with same pattern")
    print()


if __name__ == '__main__':
    main()
