#!/usr/bin/env python3
"""
Verify whether the backtest convergence was real or false.

Check if negative-cycle-time deals from Q016 investigation are present
in the 22-deal "renewals excluded" population that the backtest converged on.

If they're NOT present (because they also happened to be renewals), then
the exclude_invalid_cycle_time rule was never actually needed, and the
"multi-rule iteration" was never tested - only single-rule application.
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client

# Load environment variables
load_dotenv()

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.field_semantics import is_renewal_base, is_valid_cycle_deal, is_won


def main():
    print("="*80)
    print("CONVERGENCE POPULATION VERIFICATION")
    print("="*80)
    print()
    print("Question: Did the backtest actually test multi-rule iteration,")
    print("or did it only test single-rule application?")
    print()

    # Connect to Supabase
    sb = create_client(
        os.environ['SUPABASE_URL'],
        os.environ['SUPABASE_SERVICE_KEY']
    )

    # Fetch all deals
    all_deals = sb.table("deals").select(
        "deal_id,company_name,create_date,close_date,pipeline_id,renewal_revenue,stage"
    ).execute()

    print(f"Total deals in database: {len(all_deals.data)}")

    # Filter to won deals only
    won_deals = [d for d in all_deals.data if is_won(d.get("stage"))]
    print(f"Won deals: {len(won_deals)}")

    # Population 1: Renewals excluded (what the backtest converged on)
    RENEWAL_PIPELINE_ID = "866608541"
    renewals_excluded = [
        d for d in won_deals
        if d.get("pipeline_id") != RENEWAL_PIPELINE_ID
    ]
    print(f"After exclude_renewals: {len(renewals_excluded)} deals")

    # Population 2: Renewals excluded + invalid cycle time excluded (fully clean)
    fully_clean = [
        d for d in renewals_excluded
        if is_valid_cycle_deal(d)
    ]
    print(f"After exclude_renewals + exclude_invalid_cycle_time: {len(fully_clean)} deals")

    print()
    print("-"*80)
    print("CRITICAL QUESTION")
    print("-"*80)
    print()

    # Find deals that are in renewals_excluded but NOT in fully_clean
    # These are the deals with invalid cycle time that should have been excluded
    invalid_cycle_deals = [
        d for d in renewals_excluded
        if not is_valid_cycle_deal(d)
    ]

    if not invalid_cycle_deals:
        print("✗ NO INVALID CYCLE TIME DEALS IN CONVERGED POPULATION")
        print()
        print("This means the exclude_invalid_cycle_time rule was NEVER NEEDED.")
        print("All deals with invalid cycle time happened to also be renewals,")
        print("so they were already excluded by the first rule (exclude_renewals).")
        print()
        print("IMPLICATION: Multi-rule iteration was NOT actually tested.")
        print("Only single-rule application was tested (simplest case).")
        print()
        print("To properly test iteration, need a case where:")
        print("  1. First rule alone does NOT converge")
        print("  2. Engine tries second rule")
        print("  3. Second rule achieves convergence")
        print()
        print("This is the forced multi-rule iteration test requested.")
    else:
        print(f"✓ FOUND {len(invalid_cycle_deals)} INVALID CYCLE TIME DEALS")
        print()
        print("These deals were in the 'renewals excluded' population but have")
        print("invalid cycle time (negative or missing dates).")
        print()
        print("Sample invalid cycle deals:")
        for deal in invalid_cycle_deals[:5]:
            print(f"  - {deal['deal_id']}: {deal.get('company_name')}")
            print(f"    create_date: {deal.get('create_date')}")
            print(f"    close_date: {deal.get('close_date')}")
            try:
                if deal.get('create_date') and deal.get('close_date'):
                    create_date = datetime.fromisoformat(deal['create_date'].replace("Z", "+00:00"))
                    close_date = datetime.fromisoformat(deal['close_date'].replace("Z", "+00:00"))
                    cycle_days = (close_date - create_date).days
                    print(f"    cycle_days: {cycle_days}")
            except:
                print(f"    cycle_days: [parse error]")
            print()

        print("IMPLICATION: exclude_invalid_cycle_time rule WAS NEEDED but NOT APPLIED")
        print("because the backtest converged early (after exclude_renewals alone).")
        print()
        print("This suggests the ±3 day tolerance was too loose - it accepted 52.5 days")
        print("even though there were still invalid cycle time deals contaminating the")
        print("population. True convergence requires BOTH rules.")

    print()
    print("-"*80)
    print("CYCLE TIME COMPARISON")
    print("-"*80)
    print()

    # Calculate cycle times for both populations
    def calc_median_cycle_time(deals):
        cycle_times = []
        for deal in deals:
            try:
                create_date_str = deal.get("create_date")
                close_date_str = deal.get("close_date")

                if not create_date_str or not close_date_str:
                    continue

                create_date = datetime.fromisoformat(create_date_str.replace("Z", "+00:00"))
                close_date = datetime.fromisoformat(close_date_str.replace("Z", "+00:00"))

                cycle_days = (close_date - create_date).days
                if cycle_days >= 0:
                    cycle_times.append(cycle_days)
            except:
                continue

        if not cycle_times:
            return None, 0

        sorted_times = sorted(cycle_times)
        n = len(sorted_times)
        median = sorted_times[n // 2] if n % 2 == 1 else (sorted_times[n // 2 - 1] + sorted_times[n // 2]) / 2
        return round(median, 1), n

    renewals_excluded_median, renewals_excluded_n = calc_median_cycle_time(renewals_excluded)
    fully_clean_median, fully_clean_n = calc_median_cycle_time(fully_clean)

    print(f"Renewals excluded only: {renewals_excluded_median} days (n={renewals_excluded_n})")
    print(f"Fully clean (both rules): {fully_clean_median} days (n={fully_clean_n})")
    print()

    if renewals_excluded_median and fully_clean_median:
        delta = abs(renewals_excluded_median - fully_clean_median)
        print(f"Difference: {delta} days")
        print()

        if delta <= 3:
            print(f"✓ Difference within ±3 day tolerance")
            print("Both populations produce similar results - exclude_invalid_cycle_time")
            print("may not be materially important for this metric.")
        else:
            print(f"✗ Difference EXCEEDS ±3 day tolerance")
            print("This confirms exclude_invalid_cycle_time is a real correction,")
            print("not just a theoretical hygiene rule. The backtest accepted 52.5 days")
            print("when it should have required the fully clean population.")

    print()
    print("="*80)
    print("RECOMMENDATION")
    print("="*80)
    print()
    print("Run forced multi-rule iteration test:")
    print("  1. Modify ground truth to require BOTH rules")
    print("  2. OR set tighter tolerance (±1 day instead of ±3)")
    print("  3. OR test with hygiene_requirements = ['exclude_invalid_cycle_time']")
    print("     first (forcing mismatch due to renewal contamination)")
    print("  4. Then add 'exclude_renewals' and confirm convergence")
    print()
    print("This would prove genuine multi-step iteration, not just single-rule success.")


if __name__ == '__main__':
    main()
