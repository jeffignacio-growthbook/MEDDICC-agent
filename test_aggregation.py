#!/usr/bin/env python3
"""Test null/zero counts in aggregation."""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'scripts'))
sys.path.insert(0, str(Path(__file__).parent / 'api'))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

from supabase_client import SupabaseWriter
from tools import filter_table
from router import _aggregate_and_sample

async def main():
    """Test aggregation with null/zero counts."""
    writer = SupabaseWriter()

    print("Testing null/zero counts in aggregation")
    print("=" * 70)
    print()

    # Query for active deals with component value columns
    result = await filter_table(
        sb=writer.client,
        table="deals",
        columns=["deal_id", "company_name", "deal_value", "new_arr",
                 "expansion_arr", "renewal_revenue"],
        filters=[["eq", "deal_status", "active"]],
        limit=500  # Fetch all active deals (432 total)
    )

    print(f"Query returned: {result.get('row_count', len(result.get('rows', [])))} rows")
    print()

    # Apply aggregation (as done in dynamic_query_loop)
    aggregated = _aggregate_and_sample(result, sample_size=20, order_by=None)

    print(f"After aggregation:")
    print(f"  - row_count: {aggregated.get('row_count')}")
    print(f"  - sample size: {len(aggregated.get('rows', []))}")
    print(f"  - truncated: {aggregated.get('truncated')}")
    print()

    # Check for aggregates
    aggregates = aggregated.get('aggregates', {})

    if 'null_counts' in aggregates:
        print("✓ null_counts present:")
        for col, count in aggregates['null_counts'].items():
            print(f"    {col}: {count} nulls")
        print()
    else:
        print("✗ null_counts missing from aggregates")
        print()

    if 'zero_counts' in aggregates:
        print("✓ zero_counts present:")
        for col, count in aggregates['zero_counts'].items():
            print(f"    {col}: {count} zeros")
        print()
    else:
        print("✗ zero_counts missing from aggregates")
        print()

    # Calculate how many deals have NO ARR (all five fields zero or null)
    rows = result.get('rows', [])
    if len(rows) < result.get('row_count', 0):
        print(f"Note: Only {len(rows)} sample rows available (aggregation truncated)")
        print()

    # The aggregates should tell us the counts
    if 'zero_counts' in aggregates:
        deal_value_zeros = aggregates['zero_counts'].get('deal_value', 0)
        print(f"Ground truth check:")
        print(f"  - {deal_value_zeros} deals with deal_value = 0")
        print(f"  - Expected: 127 deals with all ARR fields zero/null")
        print()

        if deal_value_zeros == 127:
            print("✓ SUCCESS: zero_counts shows correct total (127)")
        else:
            print(f"  Note: deal_value zeros ({deal_value_zeros}) != all-fields-zero count (127)")
            print("  This is expected - deal_value alone doesn't capture the full condition")

if __name__ == '__main__':
    asyncio.run(main())
