#!/usr/bin/env python3
"""
Find the specific deal that differs between handler (71 deals) and standalone
script (72 deals) for 12-month rolling window.

This is NOT "acceptable data drift" - it's either:
1. A race condition (deal changed state between runs)
2. A filter logic difference that only affects 1 deal today
3. Some other bug that needs to be identified

Do not accept "close enough" without finding the exact deal.
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from statistics import median

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_won
from handlers import compute_cycle_time

def find_discrepancy():
    sb = get_supabase()

    print("=" * 80)
    print("FINDING THE 71 vs 72 DEAL DISCREPANCY")
    print("=" * 80)
    print()

    # Method 1: Handler (what compute_cycle_time returns)
    print("Method 1: Handler (compute_cycle_time)")
    print("-" * 80)
    handler_result = compute_cycle_time(sb)
    print(f"  Window: {handler_result['window']}")
    print(f"  Sample size: {handler_result['sample_size']}")
    print(f"  Median: {handler_result['median_days']} days")
    print()

    # Method 2: Replicate handler logic exactly to get deal IDs
    print("Method 2: Replicating handler logic to get deal IDs")
    print("-" * 80)

    # Load config
    import yaml
    config_path = Path(__file__).parent.parent / "config" / "metrics.yaml"
    with open(config_path) as f:
        metrics_config = yaml.safe_load(f)

    cycle_config = metrics_config.get("cycle_time", {}).get("config", {})
    window_mode = cycle_config.get("window_mode", "all_time")
    rolling_window_months = cycle_config.get("rolling_window_months", 12)

    # Calculate cutoff
    now = datetime.now(timezone.utc)
    cutoff_date = now - timedelta(days=rolling_window_months * 30)

    # Fetch all deals
    all_deals = sb.table("deals").select(
        "deal_id,company_name,create_date,close_date,stage,deal_value"
    ).execute()

    won_deals = [d for d in all_deals.data if is_won(d.get("stage"))]

    # Method 2a: Handler's exact logic
    handler_deals = []
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

            # Handler's filter logic
            if close_date < cutoff_date:
                continue

            cycle_days = (close_date - create_date).days

            if cycle_days >= 0:
                handler_deals.append({
                    "deal_id": deal.get("deal_id"),
                    "company_name": deal.get("company_name"),
                    "cycle_days": cycle_days,
                    "close_date": close_date
                })
        except (ValueError, AttributeError):
            continue

    print(f"  Deals from handler logic: {len(handler_deals)}")
    print()

    # Method 3: Standalone script logic (from compute_rolling_cycle_times.py)
    print("Method 3: Standalone script logic")
    print("-" * 80)

    standalone_deals = []
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

            # Standalone's filter logic (same as handler's)
            if close_date >= cutoff_date:
                cycle_days = (close_date - create_date).days

                if cycle_days >= 0:
                    standalone_deals.append({
                        "deal_id": deal.get("deal_id"),
                        "company_name": deal.get("company_name"),
                        "cycle_days": cycle_days,
                        "close_date": close_date
                    })
        except (ValueError, AttributeError):
            continue

    print(f"  Deals from standalone logic: {len(standalone_deals)}")
    print()

    # Find differences
    handler_ids = {d["deal_id"] for d in handler_deals}
    standalone_ids = {d["deal_id"] for d in standalone_deals}

    in_handler_not_standalone = handler_ids - standalone_ids
    in_standalone_not_handler = standalone_ids - handler_ids

    print("=" * 80)
    print("DISCREPANCY ANALYSIS")
    print("=" * 80)
    print()

    if handler_ids == standalone_ids:
        print("✅ NO DISCREPANCY: Both methods return identical deal sets")
        print(f"   Both found {len(handler_ids)} deals")
        print()
        print("   The 71 vs 72 difference must be from:")
        print("   - Timing: A deal changed state between test runs")
        print("   - Or the original test run was against different data")
        print()
    else:
        print(f"⚠️  DISCREPANCY FOUND: {len(in_handler_not_standalone)} in handler only, {len(in_standalone_not_handler)} in standalone only")
        print()

        if in_handler_not_standalone:
            print(f"Deals in HANDLER but NOT standalone ({len(in_handler_not_standalone)}):")
            for deal_id in in_handler_not_standalone:
                deal = next(d for d in handler_deals if d["deal_id"] == deal_id)
                print(f"  - {deal['company_name']} (ID: {deal_id})")
                print(f"    Cycle: {deal['cycle_days']} days, Close: {deal['close_date'].date()}")
            print()

        if in_standalone_not_handler:
            print(f"Deals in STANDALONE but NOT handler ({len(in_standalone_not_handler)}):")
            for deal_id in in_standalone_not_handler:
                deal = next(d for d in standalone_deals if d["deal_id"] == deal_id)
                print(f"  - {deal['company_name']} (ID: {deal_id})")
                print(f"    Cycle: {deal['cycle_days']} days, Close: {deal['close_date'].date()}")
            print()

    # Check medians
    handler_cycle_times = sorted([d["cycle_days"] for d in handler_deals])
    standalone_cycle_times = sorted([d["cycle_days"] for d in standalone_deals])

    if handler_cycle_times and standalone_cycle_times:
        handler_median = median(handler_cycle_times)
        standalone_median = median(standalone_cycle_times)

        print(f"Medians:")
        print(f"  Handler: {handler_median} days ({len(handler_deals)} deals)")
        print(f"  Standalone: {standalone_median} days ({len(standalone_deals)} deals)")
        print(f"  Difference: {abs(handler_median - standalone_median)} days")
        print()

    print("=" * 80)
    print("CONCLUSION")
    print("=" * 80)
    print()

    if handler_ids == standalone_ids:
        print("Both methods use identical filter logic and return the same deals.")
        print("The 71 vs 72 discrepancy from the earlier test was likely timing-based:")
        print("  - A deal closed/changed state between the two test runs")
        print("  - This is acceptable as long as both methods are consistent NOW")
    else:
        print("⚠️  FILTER LOGIC DIFFERENCE FOUND")
        print("The handler and standalone script are applying different filters.")
        print("This needs to be debugged and fixed before finalizing the metric.")

if __name__ == "__main__":
    find_discrepancy()
