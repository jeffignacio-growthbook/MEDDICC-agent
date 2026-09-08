#!/usr/bin/env python3
"""
Count how many renewal deals are contaminating the cycle_time population.
Not just the top 5 outliers - ALL renewals.
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_won

def count_renewals():
    sb = get_supabase()

    print("=" * 80)
    print("COUNTING RENEWAL CONTAMINATION IN CYCLE TIME POPULATION")
    print("=" * 80)
    print()

    # Fetch all won deals
    all_deals = sb.table("deals").select(
        "deal_id,company_name,create_date,close_date,stage,pipeline,pipeline_id,"
        "new_arr,expansion_arr,renewal_revenue"
    ).execute()

    won_deals = [d for d in all_deals.data if is_won(d.get("stage"))]
    print(f"Total won deals: {len(won_deals)}")
    print()

    # Parse and categorize
    valid_cycles = []
    renewal_deals = []
    non_renewal_deals = []

    for deal in won_deals:
        close_date_str = deal.get("close_date")
        create_date_str = deal.get("create_date")

        if not close_date_str or not create_date_str:
            continue

        try:
            close_date = datetime.fromisoformat(close_date_str.replace("Z", "+00:00"))
            create_date = datetime.fromisoformat(create_date_str.replace("Z", "+00:00"))

            if close_date.tzinfo is None:
                close_date = close_date.replace(tzinfo=timezone.utc)
            if create_date.tzinfo is None:
                create_date = create_date.replace(tzinfo=timezone.utc)

            cycle_days = (close_date - create_date).days

            if cycle_days >= 0:
                # Categorize as renewal or not
                new_arr = deal.get("new_arr") or 0
                expansion_arr = deal.get("expansion_arr") or 0
                renewal_revenue = deal.get("renewal_revenue") or 0
                pipeline_id = deal.get("pipeline_id")

                # Check if renewal by pipeline_id
                is_renewal_pipeline = pipeline_id == "866608541"

                # Also check if renewal by ARR type
                is_renewal_arr = (renewal_revenue > 0 and new_arr == 0 and expansion_arr == 0)

                deal_record = {
                    "deal_id": deal.get("deal_id"),
                    "company_name": deal.get("company_name"),
                    "cycle_days": cycle_days,
                    "pipeline_id": pipeline_id,
                    "is_renewal_pipeline": is_renewal_pipeline,
                    "is_renewal_arr": is_renewal_arr
                }

                valid_cycles.append(deal_record)

                if is_renewal_pipeline:
                    renewal_deals.append(deal_record)
                else:
                    non_renewal_deals.append(deal_record)

        except (ValueError, AttributeError):
            continue

    print(f"Valid cycle times: {len(valid_cycles)}")
    print(f"  Renewal pipeline (pipeline_id='866608541'): {len(renewal_deals)}")
    print(f"  Non-renewal (incremental): {len(non_renewal_deals)}")
    print()

    # Statistics
    from statistics import median

    all_cycle_times = [d["cycle_days"] for d in valid_cycles]
    renewal_cycle_times = [d["cycle_days"] for d in renewal_deals]
    non_renewal_cycle_times = [d["cycle_days"] for d in non_renewal_deals]

    print("MEDIANS:")
    print("-" * 80)
    print(f"  ALL deals (contaminated): {median(all_cycle_times):.0f} days ({len(all_cycle_times)} deals)")
    print(f"  Renewal deals only: {median(renewal_cycle_times):.0f} days ({len(renewal_cycle_times)} deals)")
    print(f"  Non-renewal (CORRECT): {median(non_renewal_cycle_times):.0f} days ({len(non_renewal_cycle_times)} deals)")
    print()

    impact = median(all_cycle_times) - median(non_renewal_cycle_times)
    print(f"Contamination impact: {impact:.0f} days")
    print()

    # Show distribution of renewal cycle times
    renewal_cycle_times.sort()
    print("RENEWAL CYCLE TIME DISTRIBUTION:")
    print("-" * 80)
    print(f"  Min: {min(renewal_cycle_times)} days")
    print(f"  25th: {renewal_cycle_times[len(renewal_cycle_times)//4]} days")
    print(f"  Median: {median(renewal_cycle_times):.0f} days")
    print(f"  75th: {renewal_cycle_times[3*len(renewal_cycle_times)//4]} days")
    print(f"  Max: {max(renewal_cycle_times)} days")
    print()

    # Show examples of longest renewal cycles
    renewal_deals.sort(key=lambda d: d["cycle_days"], reverse=True)
    print(f"Top 10 longest renewal cycles:")
    for i, deal in enumerate(renewal_deals[:10], 1):
        print(f"  {i}. {deal['company_name']}: {deal['cycle_days']} days")
    print()

    print("=" * 80)
    print("CONCLUSION")
    print("=" * 80)
    print()
    print(f"⚠️  RENEWAL CONTAMINATION: {len(renewal_deals)} of {len(valid_cycles)} deals ({100*len(renewal_deals)/len(valid_cycles):.1f}%)")
    print()
    print("These renewal deals should be EXCLUDED from cycle_time metric:")
    print("  - Renewal create_date does not represent sales cycle start")
    print("  - Often created at initial close, then sit for contract duration")
    print("  - Mixing renewals with new business distorts the metric")
    print()
    print(f"CORRECTED cycle time (non-renewal only): {median(non_renewal_cycle_times):.0f} days")

if __name__ == "__main__":
    count_renewals()
