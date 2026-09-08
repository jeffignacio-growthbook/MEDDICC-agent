#!/usr/bin/env python3
"""
Get specific deal_ids for bulk cleanup exclusion (from Q016 investigation)

Criteria (from Q016_FINAL_SIGNOFF.md):
1. Lost deals with blank lost_reason in bulk cleanup months (>10 per month threshold)
2. Pre-2023 legacy deals

IMPORTANT: Matches Q016 exact criteria:
- DEFAULT PIPELINE ONLY (pipeline_id='default')
- Bulk months identified by >10 blank lost_reason deals/month

Expected: 496 deals (235 April + 239 other months + 22 pre-2023)
"""
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / 'api'))
from db import get_supabase

# Bulk cleanup months from Q016 investigation
BULK_CLEANUP_MONTHS = [
    "2023-08",
    "2024-11",
    "2026-01",
    "2026-02",
    "2026-03",
    "2026-04",  # The big one (235 deals)
    "2026-05",
    "2026-06",
    "2026-07",
    "2026-08"
]

def main():
    sb = get_supabase()

    print("=" * 80)
    print("IDENTIFYING BULK CLEANUP DEALS (from Q016 investigation)")
    print("=" * 80)
    print()

    # Fetch lost deals from DEFAULT PIPELINE ONLY (matching Q016)
    DEFAULT_PIPELINE_ID = "default"
    lost_deals = sb.table('deals').select(
        'deal_id,company_name,lost_reason,close_date,create_date,pipeline_id'
    ).eq('deal_status', 'lost').eq('pipeline_id', DEFAULT_PIPELINE_ID).execute().data

    print(f"Total lost deals (default pipeline only): {len(lost_deals)}")
    print()

    bulk_cleanup_deals = set()

    # CRITERION 1: Lost deals with blank lost_reason in bulk cleanup months
    print("CRITERION 1: Blank lost_reason in bulk cleanup months")
    print()

    by_month = {}

    for deal in lost_deals:
        close_date = deal.get('close_date')
        lost_reason = deal.get('lost_reason')

        if not close_date:
            continue

        # Get YYYY-MM format
        close_month = close_date[:7]

        # Check if blank lost_reason in bulk month
        if close_month in BULK_CLEANUP_MONTHS and not lost_reason:
            bulk_cleanup_deals.add(deal['deal_id'])

            if close_month not in by_month:
                by_month[close_month] = []
            by_month[close_month].append(deal['deal_id'])

    print(f"{'Month':<15} {'Count':<10}")
    print("-" * 30)
    for month in sorted(BULK_CLEANUP_MONTHS):
        count = len(by_month.get(month, []))
        if count > 0:
            print(f"{month:<15} {count:<10}")

    criterion1_count = len(bulk_cleanup_deals)
    print()
    print(f"Total from Criterion 1: {criterion1_count}")
    print()

    # CRITERION 2: Pre-2023 legacy deals
    print("CRITERION 2: Pre-2023 legacy deals")
    print()

    pre_2023_deals = set()

    for deal in lost_deals:
        create_date = deal.get('create_date')

        if create_date and create_date < '2023-01-01':
            pre_2023_deals.add(deal['deal_id'])
            bulk_cleanup_deals.add(deal['deal_id'])

    criterion2_count = len(pre_2023_deals)
    print(f"Total from Criterion 2: {criterion2_count}")
    print()

    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()
    print(f"Criterion 1 (blank lost_reason in bulk months): {criterion1_count}")
    print(f"Criterion 2 (pre-2023 deals): {criterion2_count}")
    print(f"Total unique bulk cleanup deals: {len(bulk_cleanup_deals)}")
    print()

    # Verify against Q016 expectation (496 deals)
    expected = 496
    if len(bulk_cleanup_deals) == expected:
        print(f"✅ Matches Q016 expectation: {expected} deals")
    else:
        diff = len(bulk_cleanup_deals) - expected
        print(f"⚠️  Discrepancy: {len(bulk_cleanup_deals)} vs {expected} expected ({diff:+d})")

    print()

    # Save to JSON
    output = {
        'total_bulk_cleanup_deals': len(bulk_cleanup_deals),
        'deal_ids': sorted(list(bulk_cleanup_deals)),
        'by_criterion': {
            'blank_lost_reason_bulk_months': sorted(list(bulk_cleanup_deals - pre_2023_deals)),
            'pre_2023_legacy': sorted(list(pre_2023_deals))
        },
        'by_month': {month: sorted(deals) for month, deals in by_month.items()}
    }

    output_file = Path(__file__).parent.parent / 'bulk_cleanup_deal_ids.json'
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Bulk cleanup deal IDs saved to: {output_file}")

if __name__ == '__main__':
    main()
