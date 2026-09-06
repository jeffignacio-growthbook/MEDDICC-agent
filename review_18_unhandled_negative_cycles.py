#!/usr/bin/env python3
"""
Review 18 Unhandled Negative Cycles

These have cycles from -1d to -67d. Check if they should be:
1. Swapped (if swapping gives reasonable positive cycle)
2. Excluded (if truly broken)
3. Kept as-is (if minor data quality acceptable)
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


UNHANDLED_18 = [
    '32821739117',  # Square -67d
    '43739930533',  # Action Nederland -67d
    '41610728003',  # EDF Energy -52d
    '57909116984',  # Make -41d
    '56814175800',  # Quizlet -41d
    '15342570867',  # pelmorex -29d
    '56896689288',  # Quizlet -24d
    '52491158184',  # Reach plc -19d
    '41610727783',  # Haystack TV Inc -16d
    '45144997263',  # Wix / DeviantArt -14d
    '57553779546',  # BESTSECRET -13d
    '54276667418',  # VSCO -4d
    '34494802963',  # Dribbleup -4d
    '32821623700',  # 7shifts -1d
    '32820089374',  # Breeze Airways -1d
    '32821623440',  # 7shifts -1d
    '53441920789',  # Fortis Games -1d
    '45489233443',  # lendable -1d
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
    print("REVIEW 18 UNHANDLED NEGATIVE CYCLES")
    print("=" * 80)
    print()

    print("These deals have negative cycles from -1d to -67d")
    print("Determine: SWAP (if fixable), EXCLUDE (if broken), or ACCEPT (if minor issue)")
    print()

    results = []

    for deal_id in UNHANDLED_18:
        result = supabase.table('deals').select('*').eq('deal_id', deal_id).execute()

        if not result.data:
            print(f"⚠️  Deal {deal_id} not found")
            continue

        deal = result.data[0]
        create = deal.get('create_date')
        close = deal.get('close_date')
        company = deal.get('company_name')
        stage = deal.get('stage')

        as_is = days_between(create, close)
        if_swapped = days_between(close, create) if create and close else None

        # Decision logic
        recommendation = "UNKNOWN"
        reason = ""

        if if_swapped and 14 <= if_swapped <= 365:
            recommendation = "SWAP"
            reason = f"Swapping gives reasonable {if_swapped}d cycle"
        elif as_is and as_is >= -7:
            recommendation = "EXCLUDE"
            reason = "Minor negative (<7d), likely data entry error"
        elif if_swapped and if_swapped > 365:
            recommendation = "EXCLUDE"
            reason = f"Swapping gives unreasonable {if_swapped}d cycle"
        else:
            recommendation = "EXCLUDE"
            reason = "Moderate negative, unclear if swappable"

        results.append({
            'deal_id': deal_id,
            'company': company,
            'create': create,
            'close': close,
            'as_is': as_is,
            'if_swapped': if_swapped,
            'recommendation': recommendation,
            'reason': reason
        })

    # Display
    print(f"{'Deal ID':15s} | {'Company':25s} | {'As-Is':>7s} | {'Swapped':>8s} | {'Rec':8s} | {'Reason':30s}")
    print("-" * 120)

    for r in sorted(results, key=lambda x: x['as_is'] if x['as_is'] else 0):
        deal_id = r['deal_id'][:14]
        company = (r['company'] or 'Unknown')[:23]
        as_is = f"{r['as_is']}d" if r['as_is'] else "?"
        swapped = f"{r['if_swapped']}d" if r['if_swapped'] else "?"
        rec = r['recommendation']
        reason = r['reason'][:28]

        print(f"{deal_id:15s} | {company:25s} | {as_is:>7s} | {swapped:>8s} | {rec:8s} | {reason:30s}")

    # Summary
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()

    swap_count = sum(1 for r in results if r['recommendation'] == 'SWAP')
    exclude_count = sum(1 for r in results if r['recommendation'] == 'EXCLUDE')

    print(f"SWAP (add to migration 054): {swap_count}")
    print(f"EXCLUDE (add to migration 055): {exclude_count}")
    print(f"TOTAL: {len(results)}")
    print()

    # Generate SQL for swaps
    if swap_count > 0:
        print()
        print("SQL to add to migration 054 (or new migration 056):")
        print("-" * 80)
        for r in results:
            if r['recommendation'] == 'SWAP':
                print(f"-- {r['company']}: {r['as_is']}d → {r['if_swapped']}d")
                print(f"UPDATE deals SET create_date = '{r['close']}', close_date = '{r['create']}' WHERE deal_id = '{r['deal_id']}';")
                print()

    # Generate SQL for exclusions
    if exclude_count > 0:
        print()
        print("SQL to add to migration 055 (or new migration 057):")
        print("-" * 80)
        for r in results:
            if r['recommendation'] == 'EXCLUDE':
                print(f"INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)")
                print(f"VALUES ('{r['deal_id']}', 'NEGATIVE_CYCLE', {r['as_is']}, '{r['create']}', '{r['close']}', '{r['company']}');")

    print()


if __name__ == '__main__':
    main()
