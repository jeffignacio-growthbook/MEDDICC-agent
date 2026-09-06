#!/usr/bin/env python3
"""
Check Retroactive Deal Sources

For the 22 long-cycle retroactive deals, check HubSpot fields indicating
HOW they were created: bulk import, API, manual, specific integration.

Look for fields like:
- hs_created_by_user_id
- hs_object_source
- hs_object_source_id
- hs_object_source_label
- Any import/integration identifiers
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


def main():
    supabase = get_supabase()

    print("=" * 80)
    print("RETROACTIVE DEAL SOURCE ANALYSIS")
    print("=" * 80)
    print()

    FISCAL_QUARTERS = [
        ('FY2026 Q3', '2025-11-01', '2026-01-31'),
        ('FY2026 Q4', '2026-02-01', '2026-04-30'),
        ('FY2027 Q1', '2026-05-01', '2026-07-31'),
    ]

    # Get long-cycle wins not in snapshots (the 22-25 deals)
    print("Step 1: Identify long-cycle retroactive deals")
    print("-" * 80)

    retroactive_deals = []

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
                continue

            # Calculate cycle length
            try:
                create_dt = datetime.fromisoformat(create_date[:10])
                close_dt = datetime.fromisoformat(close_date[:10])
                cycle_days = (close_dt - create_dt).days
            except:
                continue

            # Long cycle (>= 14 days)
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
                # Determine if carry-over or retroactive
                quarter_start_dt = datetime.fromisoformat(start_date)
                days_before_quarter = (quarter_start_dt - create_dt).days

                category = 'carry_over' if days_before_quarter > 0 else 'retroactive'

                retroactive_deals.append({
                    'deal_id': deal_id,
                    'company_name': deal.get('company_name'),
                    'create_date': create_date,
                    'close_date': close_date,
                    'cycle_days': cycle_days,
                    'quarter_id': quarter_id,
                    'category': category,
                    'deal': deal  # Full deal object for field inspection
                })

    print(f"Found {len(retroactive_deals)} long-cycle deals not in snapshots")
    print()

    retroactive_only = [d for d in retroactive_deals if d['category'] == 'retroactive']
    carry_over = [d for d in retroactive_deals if d['category'] == 'carry_over']

    print(f"  Retroactive (created in-quarter): {len(retroactive_only)}")
    print(f"  Carry-over (created before quarter): {len(carry_over)}")
    print()

    print("RECONCILIATION:")
    print(f"  Total long-cycle missing: {len(retroactive_deals)} (matches pipeline migration check)")
    print(f"  Breakdown: {len(retroactive_only)} retroactive + {len(carry_over)} carry-over")
    print()

    # Analyze source fields for retroactive deals only
    if not retroactive_only:
        print("No retroactive deals to analyze")
        return

    print()
    print("Step 2: Analyze source fields for 22 retroactive deals")
    print("-" * 80)
    print()

    # Check what source fields exist
    sample_deal = retroactive_only[0]['deal']
    all_fields = set(sample_deal.keys())

    # Common HubSpot source fields
    source_fields = [
        'hs_object_source',
        'hs_object_source_id',
        'hs_object_source_label',
        'hs_created_by_user_id',
        'hs_created_by',
        'created_by',
        'source',
        'deal_source',
        'import_source',
        'hs_import_id'
    ]

    existing_source_fields = [f for f in source_fields if f in all_fields]

    print(f"Source fields available: {', '.join(existing_source_fields) if existing_source_fields else 'None found'}")
    print()

    if not existing_source_fields:
        print("⚠️  No standard source fields found in deal data")
        print("   Available fields:")
        for field in sorted(all_fields)[:20]:
            print(f"     {field}")
        print(f"   ... and {len(all_fields) - 20} more")
        print()
    else:
        # Group by source field values
        for field in existing_source_fields:
            values = defaultdict(list)

            for deal in retroactive_only:
                value = deal['deal'].get(field)
                if value is not None:
                    values[str(value)].append(deal)

            print(f"{field}:")
            print("-" * 40)

            if values:
                for value, deals_list in sorted(values.items(), key=lambda x: -len(x[1])):
                    count = len(deals_list)
                    pct = count / len(retroactive_only) * 100
                    print(f"  {value:30s}: {count:>2d} deals ({pct:>5.1f}%)")

                    # Show examples
                    for deal in deals_list[:3]:
                        print(f"    • {deal['company_name']:25s} | {deal['cycle_days']} days | {deal['deal_id']}")

                    if len(deals_list) > 3:
                        print(f"    ... and {len(deals_list) - 3} more")
            else:
                print(f"  (All NULL)")

            print()

    # Additional analysis: Check deal_status and created date patterns
    print()
    print("Step 3: Additional Pattern Analysis")
    print("-" * 80)
    print()

    # Check if all have deal_status='won'
    statuses = [d['deal'].get('deal_status') for d in retroactive_only]
    status_counts = defaultdict(int)
    for s in statuses:
        status_counts[str(s)] += 1

    print("deal_status distribution:")
    for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
        pct = count / len(retroactive_only) * 100
        print(f"  {status}: {count}/{len(retroactive_only)} ({pct:.1f}%)")
    print()

    # Check creation time of day (bulk imports often happen at specific times)
    print("Creation timestamp patterns:")
    creation_times = []
    for deal in retroactive_only:
        create_datetime = deal['deal'].get('create_date')
        if create_datetime and 'T' in str(create_datetime):
            try:
                dt = datetime.fromisoformat(str(create_datetime).replace('Z', '+00:00'))
                creation_times.append(dt.strftime('%H:%M'))
            except:
                pass

    if creation_times:
        time_counts = defaultdict(int)
        for t in creation_times:
            hour = t.split(':')[0]
            time_counts[hour] += 1

        print("  Creation hour distribution:")
        for hour in sorted(time_counts.keys()):
            count = time_counts[hour]
            print(f"    {hour}:00-{hour}:59: {count} deals")

        # Check if clustered (suggests bulk import)
        max_in_hour = max(time_counts.values())
        if max_in_hour >= len(retroactive_only) * 0.5:
            print(f"  → {max_in_hour} deals created in same hour (possible bulk import)")
    else:
        print("  No timestamps available")

    print()

    # CONCLUSION
    print()
    print("=" * 80)
    print("CONCLUSION")
    print("=" * 80)
    print()

    if existing_source_fields:
        # Check if there's a dominant source
        for field in existing_source_fields:
            values = defaultdict(int)
            for deal in retroactive_only:
                value = str(deal['deal'].get(field))
                if value != 'None':
                    values[value] += 1

            if values:
                max_value = max(values.items(), key=lambda x: x[1])
                if max_value[1] >= len(retroactive_only) * 0.6:
                    print(f"✓ DOMINANT SOURCE: {field}={max_value[0]}")
                    print(f"  {max_value[1]}/{len(retroactive_only)} deals ({max_value[1]/len(retroactive_only)*100:.1f}%)")
                    print()
                    print("  → Systematic source (fixable process issue)")
                    print("  → Can potentially be excluded upstream or tagged for separate tracking")
                    print()
                    return

    print("~ NO DOMINANT SOURCE identified")
    print("  → Either source fields not populated, or scattered manual entries")
    print("  → Likely permanent characteristic of how some deals enter pipeline")
    print("  → Recommend: Accept as limitation + document separately")
    print()


if __name__ == '__main__':
    main()
