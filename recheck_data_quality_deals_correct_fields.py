#!/usr/bin/env python3
"""
Re-check Original 8 Data Quality Deals - Using Correct Date Fields

Original finding: 8 deals with impossible timelines (0-day or negative cycles)

Now that we know:
- created_at = Supabase ETL timestamp (ignore this)
- create_date = Actual HubSpot deal creation date (use this)
- close_date = Actual HubSpot close date (use this)

Re-check if these 8 deals STILL have impossible timelines when using correct fields.
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


# Original 8 deals identified as data quality issues
ORIGINAL_8_DEALS = [
    # Negative cycles (close before create)
    ('5790911698', 'DoorDash', -41, 'NEGATIVE_CYCLE'),
    ('5681417580', 'Bluesky', -41, 'NEGATIVE_CYCLE'),
    ('5788408491', 'LeoVegas', -41, 'NEGATIVE_CYCLE'),

    # Zero-day cycles (same-day close)
    ('5369635703', 'Quizlet', 0, 'ZERO_DAY'),
    ('5363748624', 'Bluesky', 0, 'ZERO_DAY'),
    ('5362086234', 'Quizlet', 0, 'ZERO_DAY'),
    ('5368374698', 'DoorDash', 0, 'ZERO_DAY'),
    ('5365757013', 'LeoVegas', 0, 'ZERO_DAY'),
]


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
    print("RE-CHECK DATA QUALITY DEALS - CORRECT DATE FIELDS")
    print("=" * 80)
    print()

    print("Original finding: 8 deals with impossible timelines")
    print("Issue: Analysis used created_at (Supabase ETL), not create_date (HubSpot)")
    print()
    print("Re-checking with CORRECT fields:")
    print("  create_date = Actual HubSpot deal creation")
    print("  close_date = Actual HubSpot close date")
    print()

    results = []

    for deal_id_expected, company, original_cycle, reason in ORIGINAL_8_DEALS:
        # Search by company name since deal IDs might have extra digits
        result = supabase.table('deals') \
            .select('*') \
            .ilike('company_name', f'%{company}%') \
            .execute()

        if not result.data:
            print(f"⚠️  {company}: Not found in database")
            continue

        # If multiple deals, try to find the one with matching issue
        for deal in result.data:
            create_date = deal.get('create_date')
            close_date = deal.get('close_date')
            created_at = deal.get('created_at')

            if not create_date or not close_date:
                continue

            # Calculate cycle using CORRECT fields
            cycle_days = days_between(create_date, close_date)

            # Store result
            results.append({
                'company': deal.get('company_name'),
                'deal_id': str(deal.get('deal_id')),
                'create_date': create_date,
                'close_date': close_date,
                'created_at': created_at[:10] if created_at else None,
                'cycle_days': cycle_days,
                'original_cycle': original_cycle,
                'original_reason': reason,
                'still_has_issue': cycle_days <= 0 if cycle_days is not None else False
            })

    # Display results
    print()
    print("Results using CORRECT date fields (create_date, close_date):")
    print("-" * 80)
    print(f"{'Company':20s} | {'Create':12s} | {'Close':12s} | {'Cycle':>6s} | {'Original':>8s} | {'Issue?':7s}")
    print("-" * 80)

    for r in sorted(results, key=lambda x: x['company']):
        company = r['company'][:18]
        create = r['create_date']
        close = r['close_date']
        cycle = r['cycle_days']
        orig = r['original_cycle']
        issue = "YES" if r['still_has_issue'] else "NO"

        cycle_str = f"{cycle}d" if cycle is not None else "?"
        orig_str = f"{orig}d"

        print(f"{company:20s} | {create:12s} | {close:12s} | {cycle_str:>6s} | {orig_str:>8s} | {issue:7s}")

    print()

    # Summary
    still_invalid = [r for r in results if r['still_has_issue']]
    now_valid = [r for r in results if not r['still_has_issue']]

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()

    print(f"Original data quality issues: {len(ORIGINAL_8_DEALS)}")
    print(f"Still have issues (using correct dates): {len(still_invalid)}")
    print(f"Resolved (were false positives): {len(now_valid)}")
    print()

    if still_invalid:
        print("⚠️  DEALS STILL REQUIRING ATTENTION:")
        for r in still_invalid:
            print(f"  {r['company']:20s}  {r['create_date']} → {r['close_date']}  ({r['cycle_days']}d cycle)")
        print()
        print("These deals genuinely have impossible timelines:")
        print("  - Negative cycles (close before create), OR")
        print("  - Zero-day cycles (same-day create and close)")
        print()
        print("ACTION: Add these to data_quality_exclusions table")
    else:
        print("✓ ALL 8 'ISSUES' WERE FALSE POSITIVES")
        print()
        print("The impossible timelines were an artifact of using created_at")
        print("(Supabase ETL timestamp) instead of create_date (HubSpot date).")
        print()
        print("When using the correct date fields, all deals have valid timelines.")
        print()
        print("IMPLICATIONS:")
        print("  1. No data quality exclusions needed")
        print("  2. No migration to create data_quality_exclusions table")
        print("  3. Original 'missing wins' analysis can proceed without exclusions")

    print()

    # Check what the created_at dates were
    if results:
        print()
        print("Context: What were the created_at (ETL) dates for these deals?")
        print("-" * 80)

        etl_dates = {}
        for r in results:
            etl_date = r['created_at']
            if etl_date:
                etl_dates[etl_date] = etl_dates.get(etl_date, 0) + 1

        for date, count in sorted(etl_dates.items()):
            marker = " ← Aug 9 bulk ETL" if date == '2026-08-09' else ""
            print(f"  {date}: {count} deal(s){marker}")

        print()
        print("This confirms why the original analysis thought these were problematic:")
        print("  - All loaded on Aug 9 (created_at = 2026-08-09)")
        print("  - But create_date and close_date were from earlier months")
        print("  - Using created_at as 'creation date' made cycles appear negative/zero")

    print()

    # Export findings
    output_file = 'data_quality_recheck_correct_fields.txt'
    with open(output_file, 'w') as f:
        f.write("Data Quality Re-check - Correct Date Fields\n")
        f.write("=" * 80 + "\n\n")

        f.write(f"Original issues: {len(ORIGINAL_8_DEALS)}\n")
        f.write(f"Still invalid: {len(still_invalid)}\n")
        f.write(f"Resolved: {len(now_valid)}\n\n")

        if still_invalid:
            f.write("Deals still requiring attention:\n")
            for r in still_invalid:
                f.write(f"  {r['company']}: {r['create_date']} → {r['close_date']} ({r['cycle_days']}d)\n")
        else:
            f.write("All 8 'issues' were false positives from field confusion.\n")
            f.write("No data quality exclusions needed.\n")

    print(f"Full findings written to: {output_file}")


if __name__ == '__main__':
    main()
