#!/usr/bin/env python3
"""
Check Retroactive Deals vs Aug 9 Migration Overlap

Cross-check the 22 "retroactive entry (long cycle)" deals against Aug 9 migration.
How many have created_at = 2026-08-09?

Report any that DON'T - those need separate root cause.
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


FISCAL_QUARTERS = [
    ('FY2026 Q3', '2025-11-01', '2026-01-31'),
    ('FY2026 Q4', '2026-02-01', '2026-04-30'),
    ('FY2027 Q1', '2026-05-01', '2026-07-31'),
]

PIPELINE_ID = 'default'


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
    print("RETROACTIVE DEALS vs AUG 9 MIGRATION OVERLAP")
    print("=" * 80)
    print()

    # Step 1: Identify retroactive deals (same logic as original analysis)
    print("Step 1: Identifying retroactive entry deals (long cycle, not in snapshots)")
    print("-" * 80)
    print()

    retroactive_deals = []

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        deals_resp = supabase.table('deals') \
            .select('deal_id, company_name, stage, close_date, create_date, created_at, pipeline_id, deal_status') \
            .eq('pipeline_id', PIPELINE_ID) \
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

            # Calculate cycle
            cycle_days = days_between(create_date, close_date)

            # Long cycle (>= 14 days)
            if cycle_days is None or cycle_days < 14:
                continue

            # Created in-quarter (not carry-over)
            if create_date < start_date:
                continue

            # Check if in snapshots
            snapshot_resp = supabase.table('deals_snapshot') \
                .select('deal_id', count='exact') \
                .eq('fiscal_quarter', quarter_id) \
                .eq('deal_id', deal_id) \
                .limit(1) \
                .execute()

            if (snapshot_resp.count or 0) == 0:
                retroactive_deals.append({
                    'deal_id': deal_id,
                    'company_name': deal.get('company_name'),
                    'create_date': create_date,
                    'close_date': close_date,
                    'created_at': deal.get('created_at'),
                    'cycle_days': cycle_days,
                    'quarter_id': quarter_id
                })

    print(f"Found {len(retroactive_deals)} retroactive entry deals")
    print()

    # Step 2: Check how many are from Aug 9 migration
    print()
    print("Step 2: Checking overlap with Aug 9 migration")
    print("-" * 80)
    print()

    aug9_retroactive = []
    non_aug9_retroactive = []

    for deal in retroactive_deals:
        created_at = deal.get('created_at', '')
        if '2026-08-09' in created_at:
            aug9_retroactive.append(deal)
        else:
            non_aug9_retroactive.append(deal)

    print(f"Retroactive deals from Aug 9 migration: {len(aug9_retroactive)}")
    print(f"Retroactive deals NOT from Aug 9: {len(non_aug9_retroactive)}")
    print()

    # Print Aug 9 deals
    if aug9_retroactive:
        print("\nAug 9 migration retroactive deals:")
        print(f"{'Company':30s} | {'Cycle':>5s} | {'Created At':19s} | {'Quarter':11s}")
        print("-" * 80)
        for deal in sorted(aug9_retroactive, key=lambda x: x['company_name']):
            company = (deal['company_name'] or 'Unknown')[:28]
            cycle = str(deal['cycle_days'])
            created = (deal['created_at'] or '')[:19]
            quarter = deal['quarter_id']
            print(f"{company:30s} | {cycle:>5s} | {created:19s} | {quarter:11s}")
        print()

    # Print non-Aug-9 deals (these need separate explanation)
    if non_aug9_retroactive:
        print("\n⚠️  RETROACTIVE DEALS NOT FROM AUG 9 MIGRATION:")
        print("These need a separate root cause explanation")
        print()
        print(f"{'Company':30s} | {'Cycle':>5s} | {'Created At':19s} | {'Quarter':11s}")
        print("-" * 80)
        for deal in sorted(non_aug9_retroactive, key=lambda x: x['company_name']):
            company = (deal['company_name'] or 'Unknown')[:28]
            cycle = str(deal['cycle_days'])
            created = (deal['created_at'] or '')[:19]
            quarter = deal['quarter_id']
            print(f"{company:30s} | {cycle:>5s} | {created:19s} | {quarter:11s}")
        print()

        # Get full details for non-Aug-9 deals
        print("\nFull details:")
        for deal in non_aug9_retroactive:
            print(f"\n{deal['company_name']}:")
            print(f"  Deal ID: {deal['deal_id']}")
            print(f"  Create: {deal['create_date']}")
            print(f"  Close: {deal['close_date']}")
            print(f"  Created At: {deal['created_at']}")
            print(f"  Cycle: {deal['cycle_days']} days")
            print(f"  Quarter: {deal['quarter_id']}")

    # Summary
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()

    pct_aug9 = (len(aug9_retroactive) / len(retroactive_deals) * 100) if retroactive_deals else 0

    print(f"Total retroactive deals: {len(retroactive_deals)}")
    print(f"From Aug 9 migration: {len(aug9_retroactive)} ({pct_aug9:.1f}%)")
    print(f"NOT from Aug 9: {len(non_aug9_retroactive)}")
    print()

    if non_aug9_retroactive:
        print("⚠️  FINDING: Not all retroactive deals are from Aug 9 migration")
        print()
        print(f"   {len(non_aug9_retroactive)} deals need separate explanation:")
        print("   - Different migration event?")
        print("   - Manual retroactive entry?")
        print("   - Different CRM source?")
        print()
        print("   DO NOT fold these into pre_migration_deals without investigation")
    else:
        print("✓ All retroactive deals are from Aug 9 migration")
        print("  Can safely categorize as migration artifacts")

    print()


if __name__ == '__main__':
    main()
