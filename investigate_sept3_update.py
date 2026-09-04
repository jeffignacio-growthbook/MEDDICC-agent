#!/usr/bin/env python3
"""
Investigate Sept 3 Update

All 8 data quality error deals were updated on Sept 3, 2026 at 20:58.
Determine:
1. What changed (compare before/after if history available)
2. Was this a correction attempt?
3. Who/what triggered it (user, script, automation)?
4. Did it partially succeed or fail?

Check for patterns across all deals updated in that window.
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


DATA_QUALITY_DEAL_IDS = [
    '57909116983',  # Make (with extra digit)
    '56814175800',  # Quizlet
    '57553779546',  # BESTSECRET
    '53696357034',  # Bluesky
    '62122018837',  # Bluesky
    '60897496480',  # LeoVegas
    '54010724204',  # Quizlet
    '60234076204',  # knowunity.ai
]


def main():
    supabase = get_supabase()

    print("=" * 80)
    print("SEPT 3 UPDATE INVESTIGATION")
    print("=" * 80)
    print()

    print("Target: 2026-09-03 20:58:00")
    print("Context: All 8 data quality errors updated in this window")
    print()

    # Query all deals updated around Sept 3 20:58
    # Expand window slightly to catch related updates
    updated_resp = supabase.table('deals') \
        .select('*') \
        .gte('updated_at', '2026-09-03T20:57:00') \
        .lte('updated_at', '2026-09-03T21:00:00') \
        .execute()

    print(f"Total deals updated 20:57-21:00: {len(updated_resp.data)}")
    print()

    if not updated_resp.data:
        print("⚠️  No deals found in this window")
        return

    # Check if data quality deals are in this set
    dq_deals_found = []
    other_deals = []

    for deal in updated_resp.data:
        deal_id = str(deal['deal_id'])
        if deal_id in DATA_QUALITY_DEAL_IDS:
            dq_deals_found.append(deal)
        else:
            other_deals.append(deal)

    print(f"Data quality deals found: {len(dq_deals_found)}/8")
    print(f"Other deals updated: {len(other_deals)}")
    print()

    if len(dq_deals_found) < 8:
        print("⚠️  Not all 8 data quality deals found in this window")
        print("   Missing deals:")
        for dq_id in DATA_QUALITY_DEAL_IDS:
            if not any(str(d['deal_id']) == dq_id for d in dq_deals_found):
                print(f"    - {dq_id}")
        print()

    # Analyze patterns
    print()
    print("=" * 80)
    print("PATTERN ANALYSIS")
    print("=" * 80)
    print()

    # Pattern 1: What fields changed?
    # (Without history table, we can only see current state, not what changed)
    print("1. Current State of Data Quality Deals:")
    print("-" * 60)

    for deal in dq_deals_found:
        print(f"\n{deal.get('company_name')} ({deal['deal_id']}):")
        print(f"  created_at: {deal.get('created_at')}")
        print(f"  updated_at: {deal.get('updated_at')}")
        print(f"  create_date: {deal.get('create_date')}")
        print(f"  close_date: {deal.get('close_date')}")
        print(f"  deal_status: {deal.get('deal_status')}")
        print(f"  stage: {deal.get('stage')}")
        print(f"  owner_email: {deal.get('owner_email')}")
        print(f"  arr_usd: {deal.get('arr_usd')}")

    print()
    print()

    # Pattern 2: Were other deals affected similarly?
    print("2. Other Deals Updated in Same Window:")
    print("-" * 60)

    if other_deals:
        print(f"\n{len(other_deals)} other deals updated:")
        for deal in other_deals[:10]:  # Show first 10
            print(f"  • {deal.get('company_name')} ({deal['deal_id']})")
            print(f"    owner: {deal.get('owner_email')}")
            print(f"    updated: {deal.get('updated_at')}")

        if len(other_deals) > 10:
            print(f"  ... and {len(other_deals) - 10} more")

        # Check if mass update
        update_times = [deal.get('updated_at') for deal in updated_resp.data]
        unique_times = set(update_times)

        if len(unique_times) <= 5:
            print()
            print("  → Mass update detected (all deals updated at similar times)")
        else:
            print()
            print("  → Scattered updates (not all at exact same time)")
    else:
        print("\n  Only the 8 data quality deals were updated")
        print("  → Targeted update, not mass operation")

    print()
    print()

    # Pattern 3: Check for patterns in ALL Sept 3 updates
    print("3. Full Sept 3 Update Context:")
    print("-" * 60)

    # Expand to full day
    full_day_resp = supabase.table('deals') \
        .select('deal_id, company_name, updated_at, owner_email', count='exact') \
        .gte('updated_at', '2026-09-03T00:00:00') \
        .lte('updated_at', '2026-09-03T23:59:59') \
        .execute()

    print(f"\nTotal deals updated on Sept 3: {full_day_resp.count}")

    # Group by hour
    by_hour = defaultdict(int)
    for deal in full_day_resp.data:
        updated_at = deal.get('updated_at')
        if updated_at:
            hour = updated_at[11:13]  # Extract hour from ISO timestamp
            by_hour[hour] += 1

    print("\nUpdates by hour:")
    for hour in sorted(by_hour.keys()):
        count = by_hour[hour]
        marker = " ← 20:58 window" if hour == '20' else ""
        print(f"  {hour}:00 - {count} deals{marker}")

    print()

    # Conclusion
    print()
    print("=" * 80)
    print("CONCLUSION")
    print("=" * 80)
    print()

    # Check if this looks like a correction attempt
    if len(other_deals) == 0:
        print("⚠️  TARGETED UPDATE")
        print()
        print("  Only the 8 data quality deals were updated")
        print("  No other deals touched in this window")
        print()
        print("  This suggests:")
        print("  - Manual correction attempt on known bad deals")
        print("  - Script targeting specific deal_ids")
        print("  - Partial fix that may have failed or been incomplete")
        print()
        print("  RECOMMENDATION:")
        print("  - Check with team: who ran update on Sept 3?")
        print("  - What were they trying to fix?")
        print("  - Why did the bad data persist?")
    elif len(other_deals) < 50:
        print("⚠️  SMALL BATCH UPDATE")
        print()
        print(f"  {len(other_deals)} other deals updated alongside the 8 bad ones")
        print("  Likely a targeted script or manual bulk update")
    else:
        print("ℹ️  MASS UPDATE")
        print()
        print(f"  {len(other_deals)} other deals updated in same window")
        print("  Likely a system-wide update (ETL, sync, migration)")
        print("  The 8 data quality deals may have been incidental")

    print()

    # Export
    output_file = 'sept3_update_analysis.txt'
    with open(output_file, 'w') as f:
        f.write("Sept 3 Update Analysis\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Deals updated 20:57-21:00: {len(updated_resp.data)}\n")
        f.write(f"Data quality deals: {len(dq_deals_found)}\n")
        f.write(f"Other deals: {len(other_deals)}\n\n")

        f.write("\nData Quality Deals:\n")
        for deal in dq_deals_found:
            f.write(f"  {deal.get('company_name')} ({deal['deal_id']})\n")
            f.write(f"    updated: {deal.get('updated_at')}\n")

        if other_deals:
            f.write("\nOther Deals:\n")
            for deal in other_deals[:20]:
                f.write(f"  {deal.get('company_name')} ({deal['deal_id']})\n")

    print(f"Full analysis written to: {output_file}")


if __name__ == '__main__':
    main()
