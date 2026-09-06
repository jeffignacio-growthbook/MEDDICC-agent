#!/usr/bin/env python3
"""
Verify Data Quality Exclusions Table

Check that:
1. Table has exactly 20 rows
2. All expected deals are present
3. Reasons are correct (9 NEGATIVE_CYCLE, 11 ZERO_DAY_WON)
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent))

from api.db import get_supabase


def main():
    supabase = get_supabase()

    print("=" * 80)
    print("VERIFY DATA QUALITY EXCLUSIONS TABLE")
    print("=" * 80)
    print()

    # Get all exclusions
    result = supabase.table('data_quality_exclusions').select('*').execute()

    print(f"Total exclusions: {len(result.data)}")
    print()

    if len(result.data) != 20:
        print(f"⚠️  Expected 20 exclusions, found {len(result.data)}")
        print()

    # Group by reason
    negative_cycles = [r for r in result.data if r.get('reason') == 'NEGATIVE_CYCLE']
    zero_day = [r for r in result.data if r.get('reason') == 'ZERO_DAY_WON']

    print(f"Breakdown:")
    print(f"  NEGATIVE_CYCLE: {len(negative_cycles)} (expected 9)")
    print(f"  ZERO_DAY_WON: {len(zero_day)} (expected 11)")
    print()

    # Display negative cycles
    if negative_cycles:
        print("NEGATIVE_CYCLE exclusions:")
        print(f"{'Deal ID':15s} | {'Company':30s} | {'Cycle':>7s}")
        print("-" * 60)
        for r in sorted(negative_cycles, key=lambda x: x.get('cycle_days', 0)):
            deal_id = str(r.get('deal_id'))[:14]
            company = (r.get('company_name') or 'Unknown')[:28]
            cycle = r.get('cycle_days')
            print(f"{deal_id:15s} | {company:30s} | {cycle:>6d}d")
        print()

    # Display zero-day
    if zero_day:
        print("ZERO_DAY_WON exclusions:")
        print(f"{'Deal ID':15s} | {'Company':30s} | {'Date':12s}")
        print("-" * 60)
        for r in sorted(zero_day, key=lambda x: x.get('company_name', '')):
            deal_id = str(r.get('deal_id'))[:14]
            company = (r.get('company_name') or 'Unknown')[:28]
            date = r.get('create_date')
            print(f"{deal_id:15s} | {company:30s} | {date:12s}")
        print()

    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()

    success = (
        len(result.data) == 20 and
        len(negative_cycles) == 9 and
        len(zero_day) == 11
    )

    if success:
        print("✓ EXCLUSIONS TABLE VERIFIED")
        print()
        print("  20 total exclusions")
        print("  9 negative cycle deals")
        print("  11 zero-day won deals")
        print()
        print("Migration 055 applied successfully!")
    else:
        print("✗ VERIFICATION FAILED")
        print()
        print(f"  Expected: 20 total (9 negative, 11 zero-day)")
        print(f"  Found: {len(result.data)} total ({len(negative_cycles)} negative, {len(zero_day)} zero-day)")

    print()

    return success


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
