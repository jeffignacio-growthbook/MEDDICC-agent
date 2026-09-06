#!/usr/bin/env python3
"""
Reconcile All 57 Data Quality Deals

Verify every deal from the original 57 is accounted for:
- 15 fixed (swapped)
- 20 excluded
- 4 manual review
- ??? remaining

No double-counting, no gaps.
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


# From migrations 054 and 056
FIXED_25 = [
    # Migration 054 (15 deals)
    '41610727774', '41609747244', '57601552421', '41609744165', '57553470314',
    '57856036981', '29586293533', '45092404555', '57856160781', '41609747284',
    '41610727939', '57856036663', '57553731729', '45002408375', '41609747354',
    # Migration 056 (10 deals)
    '32821739117', '43739930533', '41610728003', '57909116984', '56814175800',
    '15342570867', '56896689288', '52491158184', '41610727783', '45144997263'
]

# From migrations 055 and 057
EXCLUDED_28 = [
    # Migration 055 (20 deals)
    '41609744055', '41609747117', '57856036766', '41609744944', '57539418520',
    '57856098205', '57856099977', '41610727759', '56906140802', '51249962302',
    '54223525305', '62122018837', '16791240492', '38680235576', '60897496484',
    '18654043745', '41705593737', '53696357034', '14195068446', '54010724204',
    # Migration 057 (8 deals)
    '57553779546', '54276667418', '34494802963', '32821623700', '32820089374',
    '32821623440', '53441920789', '45489233443'
]

REVIEW_4 = [
    '15596726917',  # PepsiCo $1k
    '9086864786',   # Paceline $1k
    '43422063231',  # 7shifts $1.5k
    '60234076206',  # knowunity.ai $4k
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
    print("RECONCILE ALL 57 DATA QUALITY DEALS")
    print("=" * 80)
    print()

    # Fetch ALL deals with issues
    print("Fetching all deals...")
    offset = 0
    batch_size = 1000
    all_deals = []

    while True:
        result = supabase.table('deals') \
            .select('*') \
            .range(offset, offset + batch_size - 1) \
            .execute()

        all_deals.extend(result.data)

        if len(result.data) < batch_size:
            break
        offset += batch_size

    print(f"Total deals in database: {len(all_deals)}")
    print()

    # Find ALL issues
    negative_cycles = []
    zero_day_cycles = []

    for deal in all_deals:
        create_date = deal.get('create_date')
        close_date = deal.get('close_date')

        if not create_date or not close_date:
            continue

        cycle_days = days_between(create_date, close_date)

        if cycle_days is None:
            continue

        if cycle_days < 0:
            negative_cycles.append(deal)
        elif cycle_days == 0:
            stage = deal.get('stage')
            if stage and is_won(str(stage)):
                zero_day_cycles.append(deal)

    print(f"Total issues found:")
    print(f"  Negative cycles: {len(negative_cycles)}")
    print(f"  Zero-day won: {len(zero_day_cycles)}")
    print(f"  TOTAL: {len(negative_cycles) + len(zero_day_cycles)}")
    print()

    # Categorize each deal
    all_issue_ids = set()
    fixed_set = set(FIXED_25)
    excluded_set = set(EXCLUDED_28)
    review_set = set(REVIEW_4)
    unhandled = []

    for deal in negative_cycles + zero_day_cycles:
        deal_id = str(deal['deal_id'])
        all_issue_ids.add(deal_id)

        if deal_id not in fixed_set and deal_id not in excluded_set and deal_id not in review_set:
            unhandled.append(deal)

    print(f"Categorization:")
    print(f"  Fixed (25): {len(fixed_set)}")
    print(f"  Excluded (28): {len(excluded_set)}")
    print(f"  Review (4): {len(review_set)}")
    print(f"  Unhandled: {len(unhandled)}")
    print(f"  TOTAL: {len(fixed_set) + len(excluded_set) + len(review_set) + len(unhandled)}")
    print()

    # Check for overlap
    overlap_fix_exclude = fixed_set & excluded_set
    overlap_fix_review = fixed_set & review_set
    overlap_exclude_review = excluded_set & review_set

    if overlap_fix_exclude or overlap_fix_review or overlap_exclude_review:
        print("⚠️  OVERLAP DETECTED:")
        if overlap_fix_exclude:
            print(f"  Fixed ∩ Excluded: {overlap_fix_exclude}")
        if overlap_fix_review:
            print(f"  Fixed ∩ Review: {overlap_fix_review}")
        if overlap_exclude_review:
            print(f"  Excluded ∩ Review: {overlap_exclude_review}")
        print()

    # Show unhandled deals
    if unhandled:
        print()
        print("=" * 80)
        print(f"UNHANDLED DEALS ({len(unhandled)})")
        print("=" * 80)
        print()

        print(f"{'Deal ID':15s} | {'Company':25s} | {'Create':12s} | {'Close':12s} | {'Cycle':>7s}")
        print("-" * 90)

        for deal in sorted(unhandled, key=lambda x: days_between(x.get('create_date'), x.get('close_date')) or 0):
            deal_id = str(deal['deal_id'])[:14]
            company = (deal.get('company_name') or 'Unknown')[:23]
            create = deal.get('create_date')
            close = deal.get('close_date')
            cycle = days_between(create, close)

            print(f"{deal_id:15s} | {company:25s} | {create:12s} | {close:12s} | {cycle:>6d}d")

        print()
        print("These deals were NOT included in fix/exclude/review decisions!")
        print()

        # Categorize unhandled
        unhandled_negative = [d for d in unhandled if days_between(d.get('create_date'), d.get('close_date')) < 0]
        unhandled_zero_day = [d for d in unhandled if days_between(d.get('create_date'), d.get('close_date')) == 0]

        print(f"Unhandled breakdown:")
        print(f"  Negative cycles: {len(unhandled_negative)}")
        print(f"  Zero-day won: {len(unhandled_zero_day)}")
        print()

        if unhandled_negative:
            print("Negative cycle range:")
            cycles = [days_between(d.get('create_date'), d.get('close_date')) for d in unhandled_negative]
            print(f"  Min: {min(cycles)}d")
            print(f"  Max: {max(cycles)}d")
            print()

    # Final reconciliation
    print()
    print("=" * 80)
    print("FINAL RECONCILIATION")
    print("=" * 80)
    print()

    total_handled = len(fixed_set) + len(excluded_set) + len(review_set)
    total_issues = len(all_issue_ids)

    print(f"Total issues in database: {total_issues}")
    print(f"Total handled (fixed/excluded/review): {total_handled}")
    print(f"Total unhandled: {len(unhandled)}")
    print()

    print(f"Breakdown:")
    print(f"  Fixed (swapped dates): {len(fixed_set)}")
    print(f"  Excluded (truly broken): {len(excluded_set)}")
    print(f"  Review (manual check): {len(review_set)}")
    print(f"  Unhandled: {len(unhandled)}")
    print(f"  {'='*30}")
    print(f"  TOTAL: {total_handled + len(unhandled)}")
    print()

    if total_handled + len(unhandled) == total_issues:
        print("✓ ALL DEALS ACCOUNTED FOR")
    else:
        print(f"✗ MISMATCH: {total_issues} issues but {total_handled + len(unhandled)} categorized")

    if len(unhandled) > 0:
        print()
        print("⚠️  ACTION REQUIRED:")
        print(f"  {len(unhandled)} deals still have data quality issues but were not addressed")
        print("  Recommendation: Review these and either fix or exclude")

    print()


if __name__ == '__main__':
    main()
