#!/usr/bin/env python3
"""
Verify Swapped Dates Were Fixed

Check that the 15 deals from migration 054 now have positive cycles.
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


FIXED_DEALS = [
    ('41610727774', 'Haystack TV Inc', 359),
    ('41609747244', 'Opera', 345),
    ('57601552421', 'Asana', 335),
    ('41609744165', 'Fellow', 311),
    ('57553470314', 'BESTSECRET', 307),
    ('57856036981', 'Make', 300),
    ('29586293533', 'Asana', 236),
    ('45092404555', 'lendable', 223),
    ('57856160781', 'Refurbed Marketplace GmbH', 215),
    ('41609747284', 'TSH', 189),
    ('41610727939', 'Space Neobank', 184),
    ('57856036663', 'MasterClass', 158),
    ('57553731729', 'facile.it', 155),
    ('45002408375', 'lendable', 119),
    ('41609747354', 'Which?', 102),
]


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
    print("VERIFY SWAPPED DATES FIXED")
    print("=" * 80)
    print()

    print(f"Checking {len(FIXED_DEALS)} deals...")
    print()

    print(f"{'Deal ID':15s} | {'Company':25s} | {'Expected':>9s} | {'Actual':>9s} | {'Status':7s}")
    print("-" * 85)

    success_count = 0
    fail_count = 0

    for deal_id, company, expected_cycle in FIXED_DEALS:
        result = supabase.table('deals').select('create_date, close_date').eq('deal_id', deal_id).execute()

        if not result.data:
            print(f"{deal_id:15s} | {company:25s} | {expected_cycle:>8d}d | {'NOT FOUND':>9s} | FAIL")
            fail_count += 1
            continue

        deal = result.data[0]
        create = deal.get('create_date')
        close = deal.get('close_date')
        actual_cycle = days_between(create, close)

        if actual_cycle == expected_cycle:
            status = "✓ PASS"
            success_count += 1
        else:
            status = "✗ FAIL"
            fail_count += 1

        print(f"{deal_id:15s} | {company[:23]:25s} | {expected_cycle:>8d}d | {actual_cycle:>8d}d | {status}")

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()

    print(f"Success: {success_count}/{len(FIXED_DEALS)}")
    print(f"Failed: {fail_count}/{len(FIXED_DEALS)}")
    print()

    if fail_count == 0:
        print("✓ ALL FIXES VERIFIED")
        print("  All 15 deals now have correct positive cycles")
        print()
        print("Ready to proceed with migration 055 (exclusions)")
    else:
        print("✗ SOME FIXES FAILED")
        print("  Do not proceed until issues resolved")

    return fail_count == 0


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
