#!/usr/bin/env python3
"""
Identify Unique Data Quality Issues

Get the distinct list of deals with impossible timelines (negative or zero cycles)
using the CORRECT date fields (create_date, close_date).

Output clean list for data_quality_exclusions table.
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


def days_between(start_str, end_str):
    """Calculate days between two dates."""
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
    print("IDENTIFY UNIQUE DATA QUALITY ISSUES")
    print("=" * 80)
    print()

    print("Finding all deals with impossible timelines:")
    print("  - Negative cycles (close_date < create_date)")
    print("  - Zero-day cycles (close_date = create_date)")
    print()

    # Get ALL deals
    print("Fetching all deals...")
    offset = 0
    batch_size = 1000
    all_deals = []

    while True:
        result = supabase.table('deals') \
            .select('*') \
            .range(offset, offset + batch_size - 1) \
            .execute()

        all_deals.extend(result.data)

        if len(result.data) < batch_size:
            break
        offset += batch_size

    print(f"Total deals: {len(all_deals)}")
    print()

    # Find issues
    negative_cycles = []
    zero_day_cycles = []

    for deal in all_deals:
        create_date = deal.get('create_date')
        close_date = deal.get('close_date')

        if not create_date or not close_date:
            continue

        cycle_days = days_between(create_date, close_date)

        if cycle_days is None:
            continue

        if cycle_days < 0:
            negative_cycles.append({
                'deal_id': str(deal['deal_id']),
                'company_name': deal.get('company_name'),
                'create_date': create_date,
                'close_date': close_date,
                'cycle_days': cycle_days,
                'stage': deal.get('stage'),
                'arr_usd': deal.get('arr_usd'),
                'owner_email': deal.get('owner_email')
            })
        elif cycle_days == 0:
            # Check if it's a won deal (0-day won deals are suspicious)
            stage = deal.get('stage')
            if stage and is_won(str(stage)):
                zero_day_cycles.append({
                    'deal_id': str(deal['deal_id']),
                    'company_name': deal.get('company_name'),
                    'create_date': create_date,
                    'close_date': close_date,
                    'cycle_days': cycle_days,
                    'stage': stage,
                    'arr_usd': deal.get('arr_usd'),
                    'owner_email': deal.get('owner_email')
                })

    print(f"Negative cycles found: {len(negative_cycles)}")
    print(f"Zero-day cycles (won deals): {len(zero_day_cycles)}")
    print()

    # Display negative cycles
    if negative_cycles:
        print()
        print("NEGATIVE CYCLES (close before create):")
        print("-" * 100)
        print(f"{'Deal ID':15s} | {'Company':25s} | {'Create':12s} | {'Close':12s} | {'Cycle':>7s} | {'Stage':15s}")
        print("-" * 100)

        for deal in sorted(negative_cycles, key=lambda x: x['cycle_days']):
            deal_id = deal['deal_id'][:14]
            company = (deal['company_name'] or 'Unknown')[:23]
            create = deal['create_date']
            close = deal['close_date']
            cycle = f"{deal['cycle_days']}d"
            stage = (deal['stage'] or 'None')[:13]

            print(f"{deal_id:15s} | {company:25s} | {create:12s} | {close:12s} | {cycle:>7s} | {stage:15s}")

    # Display zero-day cycles
    if zero_day_cycles:
        print()
        print("ZERO-DAY CYCLES (won on same day as created):")
        print("-" * 100)
        print(f"{'Deal ID':15s} | {'Company':25s} | {'Date':12s} | {'ARR':>12s} | {'Owner':25s}")
        print("-" * 100)

        for deal in sorted(zero_day_cycles, key=lambda x: x['company_name']):
            deal_id = deal['deal_id'][:14]
            company = (deal['company_name'] or 'Unknown')[:23]
            date = deal['create_date']
            arr = f"${deal['arr_usd']:,.0f}" if deal['arr_usd'] else "$0"
            owner = (deal['owner_email'] or 'None')[:23]

            print(f"{deal_id:15s} | {company:25s} | {date:12s} | {arr:>12s} | {owner:25s}")

    # Summary
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()

    total_issues = len(negative_cycles) + len(zero_day_cycles)

    print(f"Total data quality issues: {total_issues}")
    print(f"  Negative cycles: {len(negative_cycles)}")
    print(f"  Zero-day won deals: {len(zero_day_cycles)}")
    print()

    if total_issues > 0:
        print("RECOMMENDATION:")
        print()
        print("These deals should be added to data_quality_exclusions table:")
        print()
        print("  Reason categories:")
        print("    - NEGATIVE_CYCLE: close_date < create_date")
        print("    - ZERO_DAY_WON: created and won same day (suspicious)")
        print()
        print("  These deals should be EXCLUDED from conversion analysis:")
        print("    - They cannot have valid qualification_week")
        print("    - They distort cycle time metrics")
        print("    - They suggest data entry errors or bulk imports")
        print()

        # Generate SQL for migration
        print()
        print("SQL INSERT statements for migration:")
        print("-" * 80)
        print()

        for deal in negative_cycles:
            print(f"INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)")
            print(f"VALUES ('{deal['deal_id']}', 'NEGATIVE_CYCLE', {deal['cycle_days']}, '{deal['create_date']}', '{deal['close_date']}', '{deal['company_name']}');")

        for deal in zero_day_cycles:
            print(f"INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)")
            print(f"VALUES ('{deal['deal_id']}', 'ZERO_DAY_WON', 0, '{deal['create_date']}', '{deal['close_date']}', '{deal['company_name']}');")

    else:
        print("✓ NO DATA QUALITY ISSUES FOUND")
        print("  All deals have valid timelines")

    print()

    # Export findings
    output_file = 'unique_data_quality_issues.txt'
    with open(output_file, 'w') as f:
        f.write("Unique Data Quality Issues\n")
        f.write("=" * 80 + "\n\n")

        f.write(f"Total issues: {total_issues}\n")
        f.write(f"Negative cycles: {len(negative_cycles)}\n")
        f.write(f"Zero-day won: {len(zero_day_cycles)}\n\n")

        if negative_cycles:
            f.write("Negative Cycles:\n")
            for deal in negative_cycles:
                f.write(f"  {deal['deal_id']}: {deal['company_name']} ({deal['cycle_days']}d)\n")
            f.write("\n")

        if zero_day_cycles:
            f.write("Zero-Day Won Deals:\n")
            for deal in zero_day_cycles:
                f.write(f"  {deal['deal_id']}: {deal['company_name']} (0d)\n")
            f.write("\n")

    print(f"Full findings written to: {output_file}")


if __name__ == '__main__':
    main()
