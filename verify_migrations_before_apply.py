#!/usr/bin/env python3
"""
Verify Migrations Before Apply

1. Check if data_quality_exclusions table already exists (from earlier 053 migration)
2. Verify NO overlap between 15 deals to fix (054) and 20 deals to exclude (055)
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent))

from api.db import get_supabase


# Deals from migration 054 (to be fixed by swapping dates)
DEALS_TO_FIX = [
    '41610727774',  # Haystack TV Inc
    '41609747244',  # Opera
    '57601552421',  # Asana
    '41609744165',  # Fellow
    '57553470314',  # BESTSECRET
    '57856036981',  # Make
    '29586293533',  # Asana
    '45092404555',  # lendable
    '57856160781',  # Refurbed Marketplace GmbH
    '41609747284',  # TSH
    '41610727939',  # Space Neobank
    '57856036663',  # MasterClass
    '57553731729',  # facile.it
    '45002408375',  # lendable
    '41609747354',  # Which?
]

# Deals from migration 055 (to be excluded)
DEALS_TO_EXCLUDE = [
    # Negative cycles
    '41609744055',  # Fellow
    '41609747117',  # Netthandelsgruppen
    '57856036766',  # Refurbed Marketplace GmbH
    '41609744944',  # SymplaTeste
    '57539418520',  # patreon
    '57856098205',  # Make
    '57856099977',  # Joyteractive
    '41610727759',  # kununu GmbH
    '56906140802',  # Quizlet
    # Zero-day won
    '51249962302',  # Avaaz
    '54223525305',  # AgencyAnalytics
    '62122018837',  # Bluesky
    '16791240492',  # Khan Academy
    '38680235576',  # Lease a Bike
    '60897496484',  # LeoVegas
    '18654043745',  # Square
    '41705593737',  # Uzum
    '53696357034',  # Bluesky
    '14195068446',  # Inditex
    '54010724204',  # Quizlet
]


def main():
    supabase = get_supabase()

    print("=" * 80)
    print("VERIFY MIGRATIONS BEFORE APPLY")
    print("=" * 80)
    print()

    # CHECK 1: Does data_quality_exclusions table exist?
    print("CHECK 1: Does data_quality_exclusions table already exist?")
    print("-" * 80)
    print()

    try:
        result = supabase.table('data_quality_exclusions').select('deal_id', count='exact').limit(1).execute()
        table_exists = True
        existing_count = result.count or 0
        print(f"✓ Table EXISTS")
        print(f"  Current exclusions: {existing_count}")
        print()

        if existing_count > 0:
            print("⚠️  WARNING: Table already has data")
            print()
            print("Migration 055 needs to handle existing rows:")
            print("  Option A: DROP TABLE + CREATE TABLE (loses existing data)")
            print("  Option B: DELETE existing + INSERT new (preserves table)")
            print("  Option C: INSERT ... ON CONFLICT DO NOTHING (keeps existing + adds new)")
            print()
            print("RECOMMENDATION: Use Option B (DELETE existing + INSERT new)")
            print("  This ensures clean slate with only the 20 correct exclusions")
            print()

            # Show what's currently in the table
            existing = supabase.table('data_quality_exclusions').select('deal_id, reason, company_name').execute()
            print(f"Currently excluded deals ({len(existing.data)}):")
            for row in existing.data:
                print(f"  - {row.get('deal_id')}: {row.get('company_name')} ({row.get('reason')})")
            print()

    except Exception as e:
        table_exists = False
        print(f"✗ Table DOES NOT exist")
        print(f"  Error: {str(e)}")
        print()
        print("✓ Migration 055 can proceed as-is (CREATE TABLE IF NOT EXISTS)")
        print()

    # CHECK 2: Overlap between fix and exclude lists
    print()
    print("CHECK 2: Verify NO overlap between fixes (054) and exclusions (055)")
    print("-" * 80)
    print()

    print(f"Deals to FIX (054): {len(DEALS_TO_FIX)}")
    print(f"Deals to EXCLUDE (055): {len(DEALS_TO_EXCLUDE)}")
    print()

    # Check for overlap
    fix_set = set(DEALS_TO_FIX)
    exclude_set = set(DEALS_TO_EXCLUDE)
    overlap = fix_set & exclude_set

    if overlap:
        print(f"❌ OVERLAP DETECTED: {len(overlap)} deal(s) in BOTH lists!")
        print()
        print("These deals would be FIXED and then EXCLUDED (WRONG):")
        for deal_id in overlap:
            print(f"  - {deal_id}")
        print()
        print("⚠️  DO NOT APPLY MIGRATIONS until this is resolved!")
        print()
        print("Action required:")
        print("  1. Review these deals individually")
        print("  2. Decide: FIX or EXCLUDE (not both)")
        print("  3. Update migration files")
        print()
        return False
    else:
        print("✓ NO OVERLAP - Safe to proceed")
        print()
        print("  15 deals will be FIXED (swapped dates)")
        print("  20 deals will be EXCLUDED (truly broken)")
        print("  No deal appears in both lists")
        print()

    # CHECK 3: Verify the deals in migrations are valid
    print()
    print("CHECK 3: Verify all deal IDs exist in database")
    print("-" * 80)
    print()

    all_deal_ids = DEALS_TO_FIX + DEALS_TO_EXCLUDE

    print(f"Checking {len(all_deal_ids)} deal IDs...")

    missing = []
    for deal_id in all_deal_ids:
        result = supabase.table('deals').select('deal_id').eq('deal_id', deal_id).execute()
        if not result.data:
            missing.append(deal_id)

    if missing:
        print(f"⚠️  {len(missing)} deal ID(s) NOT FOUND in database:")
        for deal_id in missing:
            print(f"  - {deal_id}")
        print()
        print("Action: Remove these from migrations or verify correct IDs")
    else:
        print(f"✓ All {len(all_deal_ids)} deal IDs exist in database")
        print()

    # SUMMARY
    print()
    print("=" * 80)
    print("SUMMARY & RECOMMENDATION")
    print("=" * 80)
    print()

    if table_exists and existing_count > 0:
        print("⚠️  ACTION REQUIRED:")
        print()
        print("Migration 055 needs modification:")
        print()
        print("Add BEFORE the INSERT statements:")
        print("```sql")
        print("-- Clear existing exclusions (from superseded 053 migration)")
        print("DELETE FROM data_quality_exclusions;")
        print("```")
        print()
        print("Then proceed with INSERTs for the 20 correct exclusions")
        print()

    if not overlap and not missing:
        print("✓ SAFE TO APPLY MIGRATIONS")
        print()
        print("Order:")
        print("  1. Apply migration 054 (fix 15 swapped dates)")
        print("  2. Verify fixes worked (check cycle_days changed)")
        print("  3. Apply migration 055 (exclude 20 broken deals)")
        print("  4. Verify exclusions (check table has 20 rows)")
        print()
    else:
        print("❌ NOT SAFE - Resolve issues above first")

    print()

    return not overlap and not missing


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
