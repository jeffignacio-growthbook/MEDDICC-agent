#!/usr/bin/env python3
"""
Test that enhanced plausibility check PASSES on clean cohort.

Shows that segmentation-first approach resolves the block.
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone
from collections import defaultdict

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_won

# Import enhanced check
from enhanced_plausibility_check import run_enhanced_plausibility_check

def test_clean_cohort():
    """
    Create clean cohort (2023+, organic, won) and verify plausibility check passes.
    """
    sb = get_supabase()

    print("=" * 80)
    print("TEST: ENHANCED PLAUSIBILITY CHECK ON CLEAN COHORT")
    print("=" * 80)
    print()

    # Fetch all deals
    all_deals = sb.table("deals").select(
        "deal_id,company_name,pipeline_id,deal_status,stage,create_date,close_date,lost_reason"
    ).execute()

    DEFAULT_PIPELINE_ID = "default"
    RENEWAL_PIPELINE_ID = "866608541"

    # Step 1: Filter to default pipeline, 2023+
    ERA_CUTOFF = datetime(2023, 1, 1, tzinfo=timezone.utc)

    default_2023_plus = []
    for deal in all_deals.data:
        if deal.get("pipeline_id") != DEFAULT_PIPELINE_ID:
            continue

        create_date_str = deal.get("create_date")
        if create_date_str:
            try:
                create_date = datetime.fromisoformat(create_date_str.replace("Z", "+00:00"))
                if create_date >= ERA_CUTOFF:
                    default_2023_plus.append(deal)
            except:
                pass

    print(f"Step 1: Default pipeline, 2023+ = {len(default_2023_plus)} deals")
    print()

    # Step 2: Exclude bulk cleanup events (organic only)
    # Identify bulk cleanup months
    lost_2023_plus = [d for d in default_2023_plus if d.get("deal_status") == "lost"]

    blank_by_month = defaultdict(list)
    for deal in lost_2023_plus:
        if not deal.get("lost_reason"):  # Blank lost_reason
            close_date_str = deal.get("close_date")
            if close_date_str:
                try:
                    close_date = datetime.fromisoformat(close_date_str.replace("Z", "+00:00"))
                    month_key = f"{close_date.year}-{close_date.month:02d}"
                    blank_by_month[month_key].append(deal)
                except:
                    pass

    # Find bulk cleanup months (>10 blank lost_reason deals)
    bulk_cleanup_months = set()
    for month, deals_in_month in blank_by_month.items():
        if len(deals_in_month) > 10:
            bulk_cleanup_months.add(month)

    # Get IDs of bulk cleanup deals
    bulk_cleanup_deal_ids = set()
    for month in bulk_cleanup_months:
        for deal in blank_by_month[month]:
            bulk_cleanup_deal_ids.add(deal.get("deal_id"))

    # Filter to organic only (exclude bulk cleanup)
    organic_2023_plus = [
        d for d in default_2023_plus
        if d.get("deal_id") not in bulk_cleanup_deal_ids or d.get("deal_status") != "lost"
    ]

    print(f"Step 2: Exclude bulk cleanup = {len(organic_2023_plus)} organic deals")
    print(f"  (Removed {len(bulk_cleanup_deal_ids)} bulk cleanup deals)")
    print()

    # Step 3: Run enhanced plausibility check on CLEAN cohort
    print("Step 3: Run enhanced plausibility check on CLEAN cohort")
    print()

    passed = run_enhanced_plausibility_check(
        population_description="Default pipeline, 2023+, organic closures only",
        deals=organic_2023_plus,
        metric_name="cycle_time",
        metric_value=52
    )

    print()
    print("=" * 80)
    print("TEST RESULT")
    print("=" * 80)
    print()

    if passed:
        print("✅ PASSED: Clean cohort clears plausibility check")
        print()
        print("CONCLUSION:")
        print("  Segmentation-first approach resolves EVENT contamination block.")
        print("  Safe to compute metrics on clean cohort (2023+, organic only).")
    else:
        print("❌ FAILED: Clean cohort still blocked/flagged")
        print()
        print("  This should not happen - investigate further")

    return passed

if __name__ == "__main__":
    passed = test_clean_cohort()
    sys.exit(0 if passed else 1)
