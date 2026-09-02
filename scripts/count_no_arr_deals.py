#!/usr/bin/env python3
"""
Count deals with no ARR recorded across all five value columns.

Establishes ground truth for the question: "Which deals have no ARR recorded?"
"""
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

from supabase_client import SupabaseWriter

def main():
    """Run the count query and display results."""
    writer = SupabaseWriter()

    print("Running count query...")
    print("Conditions:")
    print("  - deal_status = 'active'")
    print("  - deal_value = 0 (or null)")
    print("  - new_arr = 0 (or null)")
    print("  - expansion_arr = 0 (or null)")
    print("  - renewal_revenue = 0 (or null)")
    print()

    # Fetch all active deals and filter in Python
    # PostgREST doesn't easily support complex OR conditions within AND
    from supabase_client import select_all

    all_active = select_all(
        writer.client,
        'deals',
        columns='deal_id,company_name,deal_value,new_arr,expansion_arr,renewal_revenue',
        filters=[('eq', 'deal_status', 'active')]
    )

    print(f"Fetched {len(all_active)} active deals")

    # Filter in Python for zero/null on all five value columns
    def is_zero_or_null(val):
        return val is None or val == 0 or val == 0.0

    no_arr_deals = [
        d for d in all_active
        if is_zero_or_null(d.get('deal_value'))
        and is_zero_or_null(d.get('new_arr'))
        and is_zero_or_null(d.get('expansion_arr'))
        and is_zero_or_null(d.get('renewal_revenue'))
    ]

    count = len(no_arr_deals)

    print(f"\nResult: {count} active deals with no ARR recorded")

    # Show first 5 examples
    if no_arr_deals:
        print("\nFirst 5 examples:")
        for deal in no_arr_deals[:5]:
            print(f"  - {deal.get('deal_id')}: {deal.get('company_name')}")

    print()
    print("Context: Previous attempts returned:")
    print("  - Attempt 1: 0 (wrong filter)")
    print("  - Attempt 2: 6 (from sample)")
    print("  - Attempt 3: unanswerable")
    print("  - Attempt 4: budget exhausted")
    print("  - Attempt 5: 11+ (incomplete from 100-row cap)")
    print()
    print(f"Ground truth: {count}")

if __name__ == '__main__':
    main()
