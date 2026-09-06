#!/usr/bin/env python3
"""
Reconcile Deal Creation Date Discrepancy

HubSpot native report shows 106 deals created in ENTIRE August 2026.
Script found "1,510 deals on Aug 9, 2026."

Check:
1. What does created_at actually represent? (Supabase ETL timestamp?)
2. What does create_date represent? (Actual HubSpot deal creation?)
3. How many deals have create_date in August 2026?
4. How many deals have created_at = Aug 9, 2026?

Reconcile against HubSpot's 106 count.
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


def fetch_all_rows(supabase, query):
    """Fetch all rows handling pagination."""
    all_rows = []
    offset = 0
    batch_size = 1000

    while True:
        result = query.range(offset, offset + batch_size - 1).execute()
        all_rows.extend(result.data)

        if len(result.data) < batch_size:
            break
        offset += batch_size

    return all_rows


def main():
    supabase = get_supabase()

    print("=" * 80)
    print("DEAL CREATION DATE RECONCILIATION")
    print("=" * 80)
    print()

    print("Goal: Reconcile 1,510 'Aug 9' deals vs 106 deals in August 2026 per HubSpot")
    print()

    # Step 1: Check what created_at actually represents
    print("Step 1: Understanding created_at vs create_date")
    print("-" * 80)
    print()

    # Get sample deals
    sample = supabase.table('deals').select('*').limit(5).execute()

    if sample.data:
        print("Sample deal fields:")
        deal = sample.data[0]
        print(f"  created_at: {deal.get('created_at')}")
        print(f"  create_date: {deal.get('create_date')}")
        print(f"  close_date: {deal.get('close_date')}")
        print()

        print("Field definitions:")
        print("  created_at: Likely Supabase row insertion timestamp (ETL date)")
        print("  create_date: Actual deal creation date in HubSpot")
        print()

    # Step 2: Count deals by created_at = Aug 9, 2026
    print()
    print("Step 2: Deals with created_at = 2026-08-09 (Supabase ETL timestamp)")
    print("-" * 80)
    print()

    # Build query
    query = supabase.table('deals') \
        .select('deal_id', count='exact') \
        .gte('created_at', '2026-08-09T00:00:00') \
        .lte('created_at', '2026-08-09T23:59:59')

    result = query.execute()
    created_at_aug9_count = result.count or 0

    print(f"Deals with created_at = 2026-08-09: {created_at_aug9_count}")
    print()

    if created_at_aug9_count > 1000:
        print("⚠️  This is the number previously reported as '1,510 deals created Aug 9'")
        print("   BUT: This counts Supabase row insertion, NOT HubSpot deal creation")
        print()

    # Step 3: Count deals by create_date in August 2026
    print()
    print("Step 3: Deals with create_date in August 2026 (Actual HubSpot creation)")
    print("-" * 80)
    print()

    query = supabase.table('deals') \
        .select('deal_id', count='exact') \
        .gte('create_date', '2026-08-01') \
        .lte('create_date', '2026-08-31')

    result = query.execute()
    create_date_aug_count = result.count or 0

    print(f"Deals with create_date in August 2026: {create_date_aug_count}")
    print()

    print(f"HubSpot native report shows: 106 deals in August 2026")
    print(f"Supabase create_date count: {create_date_aug_count}")
    print()

    if abs(create_date_aug_count - 106) <= 10:
        print("✓ RECONCILED: Counts match within reasonable margin")
    else:
        diff = create_date_aug_count - 106
        print(f"⚠️  DISCREPANCY: {diff:+d} deal difference")
        print("   Possible causes:")
        print("   - Pipeline filter differences")
        print("   - Deals added/removed since HubSpot report")
        print("   - Different deal types included")

    print()

    # Step 4: Check create_date = Aug 9, 2026 specifically
    print()
    print("Step 4: Deals with create_date = 2026-08-09 (Actual creation on that day)")
    print("-" * 80)
    print()

    query = supabase.table('deals') \
        .select('deal_id, company_name, create_date, created_at') \
        .eq('create_date', '2026-08-09')

    aug9_create_deals = fetch_all_rows(supabase, query)

    print(f"Deals actually CREATED on Aug 9, 2026: {len(aug9_create_deals)}")
    print()

    if len(aug9_create_deals) <= 20:
        print("These are the deals ACTUALLY created on Aug 9 in HubSpot:")
        for deal in aug9_create_deals[:20]:
            print(f"  - {deal.get('company_name'):30s}  create: {deal.get('create_date')}  loaded: {deal.get('created_at')[:10]}")
    else:
        print(f"Showing first 20 of {len(aug9_create_deals)} deals:")
        for deal in aug9_create_deals[:20]:
            print(f"  - {deal.get('company_name'):30s}  create: {deal.get('create_date')}  loaded: {deal.get('created_at')[:10]}")

    print()

    # Step 5: Analyze created_at distribution
    print()
    print("Step 5: When were deals loaded into Supabase? (created_at distribution)")
    print("-" * 80)
    print()

    # Get all deals and group by created_at date
    print("Fetching all deals... (may take a moment)")
    query = supabase.table('deals').select('created_at')
    all_deals = fetch_all_rows(supabase, query)

    print(f"Total deals in Supabase: {len(all_deals)}")
    print()

    created_at_by_date = defaultdict(int)
    for deal in all_deals:
        created_at = deal.get('created_at')
        if created_at:
            date = created_at[:10]  # YYYY-MM-DD
            created_at_by_date[date] += 1

    print("Top 10 dates by Supabase row creation (created_at):")
    sorted_dates = sorted(created_at_by_date.items(), key=lambda x: -x[1])
    for date, count in sorted_dates[:10]:
        pct = count / len(all_deals) * 100
        marker = " ← BULK ETL DATE" if count > 1000 else ""
        print(f"  {date}: {count:>4d} deals ({pct:>5.1f}%){marker}")

    print()

    if created_at_by_date.get('2026-08-09', 0) > 1000:
        print("✓ CONFIRMED: Aug 9, 2026 was a bulk ETL date, NOT deal creation date")
        print(f"  {created_at_by_date['2026-08-09']} deals loaded into Supabase that day")
        print("  This explains why 'created_at = Aug 9' found 1,510 deals")
        print()

    # Step 6: Summary
    print()
    print("=" * 80)
    print("RECONCILIATION SUMMARY")
    print("=" * 80)
    print()

    print("FINDING: Field confusion in original analysis")
    print()
    print("  created_at = Supabase ETL timestamp (when row inserted)")
    print("  create_date = HubSpot deal creation date (actual business date)")
    print()

    print(f"Original analysis queried created_at, found {created_at_aug9_count} deals on Aug 9")
    print(f"This was a Supabase ETL bulk load, not {created_at_aug9_count} deals created that day")
    print()

    print(f"CORRECT metric: create_date in August 2026 = {create_date_aug_count} deals")
    print(f"HubSpot native report: 106 deals in August 2026")
    print()

    if abs(create_date_aug_count - 106) <= 10:
        print("✓ Numbers reconcile - no Aug 9 anomaly exists")
        print()
        print("IMPLICATIONS:")
        print("  1. The '66.7x spike on Aug 9' was a table field error")
        print("  2. The 'Copper migration hypothesis' was built on false premise")
        print("  3. The 49 deals by christian@growthbook.io are NOT a migration batch")
        print("  4. The 'retroactive deals' and 'duplicates' need re-evaluation")
        print("     without the migration assumption")
        print()
        print("NEXT STEPS:")
        print("  1. Re-run ALL analyses using create_date instead of created_at")
        print("  2. Check if Aug 2022 (not 2026) was actual Copper migration")
        print("  3. Re-evaluate data quality issues without migration hypothesis")
    else:
        print("⚠️  Partial reconciliation - still investigating discrepancy")

    print()

    # Export findings
    output_file = 'deal_creation_reconciliation.txt'
    with open(output_file, 'w') as f:
        f.write("Deal Creation Date Reconciliation\n")
        f.write("=" * 80 + "\n\n")

        f.write(f"created_at = Aug 9, 2026: {created_at_aug9_count} deals (Supabase ETL)\n")
        f.write(f"create_date in August 2026: {create_date_aug_count} deals (HubSpot creation)\n")
        f.write(f"HubSpot native report: 106 deals\n\n")

        f.write("Top ETL dates (created_at):\n")
        for date, count in sorted_dates[:10]:
            f.write(f"  {date}: {count} deals\n")

    print(f"Full findings written to: {output_file}")


if __name__ == '__main__':
    main()
