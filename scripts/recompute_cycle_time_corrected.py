#!/usr/bin/env python3
"""
Recompute cycle time with CORRECT population (renewals excluded).

Previous numbers (CONTAMINATED with 80% renewal deals):
- All-time: 116 days (113 deals)
- 12-month: 156.5 days (72 deals)
- 6-month: 158 days (47 deals)

Now computing with NEW BUSINESS/EXPANSION ONLY (renewals excluded).
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
import statistics

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_won

def recompute_corrected():
    sb = get_supabase()

    print("=" * 80)
    print("CYCLE TIME - CORRECTED (RENEWALS EXCLUDED)")
    print("=" * 80)
    print()

    # Fetch all deals
    all_deals = sb.table("deals").select(
        "deal_id,company_name,create_date,close_date,stage,pipeline_id"
    ).execute()

    # Filter: won AND not renewal pipeline
    RENEWAL_PIPELINE_ID = "866608541"
    won_non_renewal = [
        d for d in all_deals.data
        if is_won(d.get("stage")) and d.get("pipeline_id") != RENEWAL_PIPELINE_ID
    ]

    print(f"Total deals: {len(all_deals.data)}")
    won_deals = [d for d in all_deals.data if is_won(d.get("stage"))]
    print(f"Won deals (all): {len(won_deals)}")
    renewal_deals = [d for d in won_deals if d.get("pipeline_id") == RENEWAL_PIPELINE_ID]
    print(f"  Renewal pipeline: {len(renewal_deals)} (EXCLUDED)")
    print(f"  Non-renewal (new business/expansion): {len(won_non_renewal)} (INCLUDED)")
    print()

    # Parse and compute cycle times
    deals_with_cycle_time = []
    bad_data = 0

    for deal in won_non_renewal:
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

            if cycle_days < 0:
                bad_data += 1
            elif cycle_days >= 0:
                deals_with_cycle_time.append({
                    "deal_id": deal.get("deal_id"),
                    "company_name": deal.get("company_name"),
                    "close_date": close_date,
                    "cycle_days": cycle_days
                })
        except Exception as e:
            bad_data += 1

    print(f"Valid non-renewal deals with cycle time: {len(deals_with_cycle_time)}")
    print(f"Bad data: {bad_data}")
    print()

    # Compute windows
    now = datetime.now(timezone.utc)
    cutoff_12mo = now - timedelta(days=365)
    cutoff_6mo = now - timedelta(days=182)

    windows = {
        "all_time": None,
        "12_month": cutoff_12mo,
        "6_month": cutoff_6mo
    }

    print("=" * 80)
    print("RESULTS (NON-RENEWAL ONLY)")
    print("=" * 80)
    print()

    for window_name, cutoff in windows.items():
        if cutoff is None:
            window_deals = deals_with_cycle_time
        else:
            window_deals = [d for d in deals_with_cycle_time if d["close_date"] >= cutoff]

        cycle_times = [d["cycle_days"] for d in window_deals]
        cycle_times.sort()

        if not cycle_times:
            print(f"{window_name.upper().replace('_', ' ')}:")
            print(f"  No deals")
            print()
            continue

        median_val = statistics.median(cycle_times)
        p25 = cycle_times[len(cycle_times) // 4] if len(cycle_times) >= 4 else cycle_times[0]
        p75 = cycle_times[3 * len(cycle_times) // 4] if len(cycle_times) >= 4 else cycle_times[-1]

        print(f"{window_name.upper().replace('_', ' ')}:")
        print(f"  Sample: {len(cycle_times)} deals")
        print(f"  Median: {median_val:.0f} days")
        print(f"  Distribution: Min={min(cycle_times)}, P25={p25}, P75={p75}, Max={max(cycle_times)}")
        print()

    print("=" * 80)
    print("COMPARISON: CONTAMINATED vs CORRECTED")
    print("=" * 80)
    print()

    print("CONTAMINATED (with renewals):")
    print("  All-time: 116 days (113 deals)")
    print("  12-month: 156.5 days (72 deals)")
    print("  6-month: 158 days (47 deals)")
    print()

    # Compute corrected values
    all_time_cycles = [d["cycle_days"] for d in deals_with_cycle_time]
    all_time_median = statistics.median(all_time_cycles) if all_time_cycles else 0

    twelve_mo_deals = [d for d in deals_with_cycle_time if d["close_date"] >= cutoff_12mo]
    twelve_mo_cycles = [d["cycle_days"] for d in twelve_mo_deals]
    twelve_mo_median = statistics.median(twelve_mo_cycles) if twelve_mo_cycles else 0

    six_mo_deals = [d for d in deals_with_cycle_time if d["close_date"] >= cutoff_6mo]
    six_mo_cycles = [d["cycle_days"] for d in six_mo_deals]
    six_mo_median = statistics.median(six_mo_cycles) if six_mo_cycles else 0

    print("CORRECTED (non-renewal only):")
    print(f"  All-time: {all_time_median:.0f} days ({len(all_time_cycles)} deals)")
    print(f"  12-month: {twelve_mo_median:.0f} days ({len(twelve_mo_cycles)} deals)")
    print(f"  6-month: {six_mo_median:.0f} days ({len(six_mo_cycles)} deals)")
    print()

    print("CHANGES:")
    print(f"  All-time: 116 → {all_time_median:.0f} days (Δ={116-all_time_median:.0f})")
    print(f"  12-month: 156.5 → {twelve_mo_median:.0f} days (Δ={156.5-twelve_mo_median:.0f})")
    print(f"  6-month: 158 → {six_mo_median:.0f} days (Δ={158-six_mo_median:.0f})")

if __name__ == "__main__":
    recompute_corrected()
