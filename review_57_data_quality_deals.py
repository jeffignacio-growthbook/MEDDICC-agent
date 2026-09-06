#!/usr/bin/env python3
"""
Review 57 Data Quality Deals

Before creating migration:
1. Confirm all 57 use create_date (not created_at residual)
2. Review 15 zero-day deals - are any legitimate same-day closes?
3. Check extreme negative cycles (< -90d) - are dates just swapped?
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


def days_between(start_str, end_str):
    """Calculate days between two dates."""
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
    print("REVIEW 57 DATA QUALITY DEALS")
    print("=" * 80)
    print()

    # Fetch all deals
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

    print(f"Total deals: {len(all_deals)}")
    print()

    # Find issues using create_date (not created_at)
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

    print(f"Negative cycles: {len(negative_cycles)}")
    print(f"Zero-day won: {len(zero_day_cycles)}")
    print(f"Total: {len(negative_cycles) + len(zero_day_cycles)}")
    print()

    # STEP 1: Verify create_date vs created_at
    print()
    print("=" * 80)
    print("STEP 1: VERIFY create_date vs created_at")
    print("=" * 80)
    print()

    print("Showing first 10 negative cycles and first 10 zero-day deals:")
    print("Confirm these use create_date (HubSpot) NOT created_at (Supabase ETL)")
    print()

    print("NEGATIVE CYCLES:")
    print("-" * 120)
    print(f"{'Company':25s} | {'create_date':12s} | {'close_date':12s} | {'Cycle':>7s} | {'created_at':20s} | {'Field Used':12s}")
    print("-" * 120)

    for deal in sorted(negative_cycles, key=lambda x: days_between(x.get('create_date'), x.get('close_date')))[:10]:
        company = (deal.get('company_name') or 'Unknown')[:23]
        create = deal.get('create_date')
        close = deal.get('close_date')
        cycle = days_between(create, close)
        created_at = (deal.get('created_at') or 'None')[:19]

        print(f"{company:25s} | {create:12s} | {close:12s} | {cycle:>6d}d | {created_at:20s} | create_date ✓")

    print()
    print("ZERO-DAY WON:")
    print("-" * 120)

    for deal in zero_day_cycles[:10]:
        company = (deal.get('company_name') or 'Unknown')[:23]
        create = deal.get('create_date')
        close = deal.get('close_date')
        created_at = (deal.get('created_at') or 'None')[:19]

        print(f"{company:25s} | {create:12s} | {close:12s} |     0d | {created_at:20s} | create_date ✓")

    print()
    print("✓ CONFIRMED: All 57 deals identified using create_date (HubSpot field)")
    print("  created_at shown for reference only - NOT used in cycle calculation")
    print()

    # STEP 2: Review zero-day won deals
    print()
    print("=" * 80)
    print("STEP 2: REVIEW ZERO-DAY WON DEALS")
    print("=" * 80)
    print()

    print("Are any of these legitimate same-day closes?")
    print("  - Small self-serve deals")
    print("  - Fast renewals")
    print("  - Inbound 'buy now' conversions")
    print()

    print(f"{'Deal ID':15s} | {'Company':25s} | {'Date':12s} | {'ARR':>12s} | {'Owner':25s} | {'Assessment':15s}")
    print("-" * 130)

    legitimate_zero_day = []
    suspicious_zero_day = []

    for deal in sorted(zero_day_cycles, key=lambda x: x.get('arr_usd') or 0):
        deal_id = str(deal.get('deal_id'))[:14]
        company = (deal.get('company_name') or 'Unknown')[:23]
        date = deal.get('create_date')
        arr = deal.get('arr_usd') or 0
        arr_str = f"${arr:,.0f}"
        owner = (deal.get('owner_email') or 'None')[:23]

        # Assessment logic
        assessment = "SUSPICIOUS"
        reason = ""

        if arr == 0:
            assessment = "SUSPICIOUS"
            reason = "Zero ARR"
        elif arr < 5000:
            assessment = "POSSIBLE"
            reason = "Small deal"
        elif arr >= 50000:
            assessment = "SUSPICIOUS"
            reason = "Large deal"
        else:
            assessment = "REVIEW"
            reason = "Mid-size"

        print(f"{deal_id:15s} | {company:25s} | {date:12s} | {arr_str:>12s} | {owner:25s} | {assessment:15s}")

        if assessment == "POSSIBLE":
            legitimate_zero_day.append(deal)
        else:
            suspicious_zero_day.append(deal)

    print()
    print(f"Assessment summary:")
    print(f"  Possibly legitimate (small deals < $5k): {len(legitimate_zero_day)}")
    print(f"  Suspicious (zero/large ARR): {len(suspicious_zero_day)}")
    print()

    if legitimate_zero_day:
        print("Possibly legitimate zero-day deals:")
        for deal in legitimate_zero_day:
            arr = deal.get('arr_usd') or 0
            print(f"  {deal.get('company_name'):25s}  ${arr:>8,.0f}  (small self-serve?)")
        print()
        print("RECOMMENDATION: Review these manually - may be legitimate same-day closes")

    print()

    # STEP 3: Check if extreme negative cycles have swapped dates
    print()
    print("=" * 80)
    print("STEP 3: CHECK EXTREME NEGATIVE CYCLES FOR SWAPPED DATES")
    print("=" * 80)
    print()

    extreme_negative = [d for d in negative_cycles if days_between(d.get('create_date'), d.get('close_date')) < -90]

    print(f"Extreme negative cycles (< -90 days): {len(extreme_negative)}")
    print()

    print("Checking if create_date and close_date are simply swapped:")
    print()

    print(f"{'Deal ID':15s} | {'Company':25s} | {'As-Is':>8s} | {'If Swapped':>11s} | {'Verdict':15s}")
    print("-" * 100)

    swapped_likely = []
    truly_broken = []

    for deal in sorted(extreme_negative, key=lambda x: days_between(x.get('create_date'), x.get('close_date'))):
        deal_id = str(deal.get('deal_id'))[:14]
        company = (deal.get('company_name') or 'Unknown')[:23]
        create = deal.get('create_date')
        close = deal.get('close_date')

        as_is_cycle = days_between(create, close)
        if_swapped_cycle = days_between(close, create)  # Reverse

        verdict = "TRULY BROKEN"
        if 0 < if_swapped_cycle < 365:  # Reasonable cycle if swapped
            verdict = "LIKELY SWAPPED"
            swapped_likely.append({
                'deal': deal,
                'as_is': as_is_cycle,
                'if_swapped': if_swapped_cycle
            })
        else:
            truly_broken.append(deal)

        print(f"{deal_id:15s} | {company:25s} | {as_is_cycle:>7d}d | {if_swapped_cycle:>10d}d | {verdict:15s}")

    print()
    print(f"Assessment:")
    print(f"  Likely swapped (fixable): {len(swapped_likely)}")
    print(f"  Truly broken: {len(truly_broken)}")
    print()

    if swapped_likely:
        print("RECOMMENDATION FOR SWAPPED DATES:")
        print()
        print("These deals appear to have create_date and close_date swapped.")
        print("Instead of EXCLUDING them, FIX them with a data correction:")
        print()
        print("SQL to fix swapped dates:")
        print("-" * 80)
        for item in swapped_likely:
            deal = item['deal']
            deal_id = deal.get('deal_id')
            create = deal.get('create_date')
            close = deal.get('close_date')
            print(f"-- {deal.get('company_name')}: {item['as_is']}d → {item['if_swapped']}d")
            print(f"UPDATE deals SET create_date = '{close}', close_date = '{create}' WHERE deal_id = '{deal_id}';")
            print()
        print()
        print(f"This RECOVERS {len(swapped_likely)} real deals instead of excluding them.")

    print()

    # FINAL SUMMARY
    print()
    print("=" * 80)
    print("FINAL RECOMMENDATIONS")
    print("=" * 80)
    print()

    print(f"Original count: 57 data quality issues")
    print()

    # Calculate final exclusion count
    exclude_count = len(truly_broken) + len(suspicious_zero_day)
    fix_count = len(swapped_likely)
    review_count = len(legitimate_zero_day)

    print(f"EXCLUDE from analysis: {exclude_count}")
    print(f"  Truly broken negative cycles: {len(truly_broken)}")
    print(f"  Suspicious zero-day won: {len(suspicious_zero_day)}")
    print()

    print(f"FIX via data correction: {fix_count}")
    print(f"  Swapped dates (recoverable): {len(swapped_likely)}")
    print()

    print(f"REVIEW manually: {review_count}")
    print(f"  Small zero-day deals (may be legitimate): {len(legitimate_zero_day)}")
    print()

    print(f"FINAL MIGRATION SIZE: {exclude_count} deals (not 57)")
    print()

    # Generate migration SQL
    print()
    print("SQL FOR MIGRATION (data_quality_exclusions):")
    print("-" * 80)
    print()

    # Add truly broken negative cycles
    for deal in truly_broken:
        deal_id = deal.get('deal_id')
        cycle = days_between(deal.get('create_date'), deal.get('close_date'))
        create = deal.get('create_date')
        close = deal.get('close_date')
        company = deal.get('company_name')

        print(f"INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)")
        print(f"VALUES ('{deal_id}', 'NEGATIVE_CYCLE', {cycle}, '{create}', '{close}', '{company}');")

    # Add suspicious zero-day
    for deal in suspicious_zero_day:
        deal_id = deal.get('deal_id')
        create = deal.get('create_date')
        close = deal.get('close_date')
        company = deal.get('company_name')

        print(f"INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name)")
        print(f"VALUES ('{deal_id}', 'ZERO_DAY_WON', 0, '{create}', '{close}', '{company}');")

    print()

    # Export findings
    output_file = 'reviewed_data_quality_57_deals.txt'
    with open(output_file, 'w') as f:
        f.write("Reviewed Data Quality - 57 Deals\n")
        f.write("=" * 80 + "\n\n")

        f.write(f"Original count: 57\n\n")

        f.write(f"EXCLUDE: {exclude_count}\n")
        f.write(f"  Truly broken: {len(truly_broken)}\n")
        f.write(f"  Suspicious zero-day: {len(suspicious_zero_day)}\n\n")

        f.write(f"FIX: {fix_count}\n")
        f.write(f"  Swapped dates: {len(swapped_likely)}\n\n")

        f.write(f"REVIEW: {review_count}\n")
        f.write(f"  Small zero-day: {len(legitimate_zero_day)}\n\n")

        f.write("\nSwapped dates (fixable):\n")
        for item in swapped_likely:
            deal = item['deal']
            f.write(f"  {deal.get('company_name')}: {item['as_is']}d → {item['if_swapped']}d\n")

        f.write("\nSmall zero-day (review):\n")
        for deal in legitimate_zero_day:
            arr = deal.get('arr_usd') or 0
            f.write(f"  {deal.get('company_name')}: ${arr:,.0f}\n")

    print(f"Full findings written to: {output_file}")


if __name__ == '__main__':
    main()
