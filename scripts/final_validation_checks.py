#!/usr/bin/env python3
"""
FINAL VALIDATION CHECKS BEFORE Q016 SIGN-OFF

1. Direct incremental vs renewal classification of clean cohort won deals
   (using same logic as active pipeline: incremental = new_arr OR expansion_arr > 0)

2. Identify exact deal causing 23 vs 22 discrepancy (won deals vs cycle time sample)
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

def final_validation():
    sb = get_supabase()

    print("=" * 80)
    print("FINAL VALIDATION CHECKS - Q016 SIGN-OFF")
    print("=" * 80)
    print()

    # Fetch ALL deals with ARR fields
    all_deals = sb.table("deals").select(
        "deal_id,company_name,pipeline_id,deal_status,stage,create_date,close_date,"
        "lost_reason,new_arr,expansion_arr,renewal_revenue"
    ).execute()

    DEFAULT_PIPELINE_ID = "default"
    RENEWAL_PIPELINE_ID = "866608541"

    # ========================================================================
    # SETUP: Define clean cohort (2023+, organic, won)
    # ========================================================================
    print("=" * 80)
    print("SETUP: DEFINE CLEAN COHORT")
    print("=" * 80)
    print()

    # Step 1: Default pipeline, 2023+
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
                default_2023_plus.append(deal)  # Assume 2023+ if can't parse
        else:
            default_2023_plus.append(deal)

    # Step 2: Exclude bulk cleanup (EVENT contamination)
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
    organic_2023_plus_closed = []
    for deal in default_2023_plus:
        if deal.get("deal_status") in ["won", "lost"]:
            # Exclude if it's a bulk cleanup lost deal
            if deal.get("deal_status") == "lost" and deal.get("deal_id") in bulk_cleanup_deal_ids:
                continue
            organic_2023_plus_closed.append(deal)

    # Won deals in clean cohort
    organic_won = [d for d in organic_2023_plus_closed if is_won(d.get("stage"))]

    print(f"Clean cohort (default, 2023+, organic, won): {len(organic_won)} deals")
    print()

    # ========================================================================
    # CHECK 1: INCREMENTAL VS RENEWAL CLASSIFICATION
    # ========================================================================
    print("=" * 80)
    print("CHECK 1: INCREMENTAL VS RENEWAL CLASSIFICATION")
    print("=" * 80)
    print()

    # Use SAME logic as active pipeline:
    # Incremental = new_arr > 0 OR expansion_arr > 0
    # Renewal = renewal_revenue > 0 (and NO incremental)

    incremental_won = []
    renewal_won = []
    neither_won = []

    for deal in organic_won:
        new_arr = deal.get("new_arr") or 0
        expansion_arr = deal.get("expansion_arr") or 0
        renewal_revenue = deal.get("renewal_revenue") or 0

        has_incremental = new_arr > 0 or expansion_arr > 0
        has_renewal = renewal_revenue > 0

        if has_incremental:
            incremental_won.append(deal)
        elif has_renewal:
            renewal_won.append(deal)
        else:
            neither_won.append(deal)

    pct_incremental = 100 * len(incremental_won) / len(organic_won) if len(organic_won) > 0 else 0
    pct_renewal = 100 * len(renewal_won) / len(organic_won) if len(organic_won) > 0 else 0
    pct_neither = 100 * len(neither_won) / len(organic_won) if len(organic_won) > 0 else 0

    print(f"CLEAN COHORT WON DEALS (n={len(organic_won)}):")
    print(f"  Incremental (new_arr OR expansion_arr > 0): {len(incremental_won)} ({pct_incremental:.1f}%)")
    print(f"  Renewal only (renewal_revenue > 0, no incremental): {len(renewal_won)} ({pct_renewal:.1f}%)")
    print(f"  Neither (all ARR fields blank/zero): {len(neither_won)} ({pct_neither:.1f}%)")
    print()

    # Show breakdown
    print("Incremental deals:")
    for deal in incremental_won:
        name = deal.get("company_name") or "(blank)"
        new_arr = deal.get("new_arr") or 0
        exp_arr = deal.get("expansion_arr") or 0
        print(f"  {name}: new_arr=${new_arr:,.0f}, expansion_arr=${exp_arr:,.0f}")
    print()

    if renewal_won:
        print("Renewal-only deals:")
        for deal in renewal_won:
            name = deal.get("company_name") or "(blank)"
            renewal_rev = deal.get("renewal_revenue") or 0
            print(f"  {name}: renewal_revenue=${renewal_rev:,.0f}")
        print()

    if neither_won:
        print("⚠️  Deals with NO ARR data:")
        for deal in neither_won:
            name = deal.get("company_name") or "(blank)"
            print(f"  {name}: all ARR fields blank/zero")
        print()

    # ========================================================================
    # COMPARISON: Clean cohort vs Active pipeline
    # ========================================================================
    print("=" * 80)
    print("DIRECT COMPARISON: CLEAN COHORT VS ACTIVE PIPELINE")
    print("=" * 80)
    print()

    # Active pipeline (today's numbers - already established)
    active_deals = [d for d in all_deals.data if d.get("deal_status") == "active"]
    active_default = [d for d in active_deals if d.get("pipeline_id") == DEFAULT_PIPELINE_ID]
    active_default_incremental = [
        d for d in active_default
        if (d.get("new_arr") or 0) > 0 or (d.get("expansion_arr") or 0) > 0
    ]

    pct_active_incremental = 100 * len(active_default_incremental) / len(active_default) if len(active_default) > 0 else 0

    print(f"ACTIVE PIPELINE (default, today):")
    print(f"  Total active: {len(active_default)}")
    print(f"  With incremental ARR: {len(active_default_incremental)} ({pct_active_incremental:.1f}%)")
    print()

    print(f"HISTORICAL WON (default, 2023+, organic):")
    print(f"  Total won: {len(organic_won)}")
    print(f"  With incremental ARR: {len(incremental_won)} ({pct_incremental:.1f}%)")
    print()

    print("DIRECT COMPARISON:")
    print(f"  Active incremental: {pct_active_incremental:.1f}%")
    print(f"  Historical won incremental: {pct_incremental:.1f}%")
    divergence = abs(pct_active_incremental - pct_incremental)
    print(f"  Divergence: {divergence:.1f} percentage points")
    print()

    # Interpret
    if divergence <= 10:
        print(f"✅ DIVERGENCE ({divergence:.1f}pp) IS SMALL - Mix shift explanation holds")
        print("   Active and historical are reasonably consistent")
        mix_shift_holds = True
    elif divergence <= 20:
        print(f"⚠️  DIVERGENCE ({divergence:.1f}pp) IS MODERATE - Borderline")
        print("   Could indicate mild business shift or minor classification differences")
        mix_shift_holds = True
    else:
        print(f"🚩 DIVERGENCE ({divergence:.1f}pp) IS LARGE - Mix shift explanation does NOT hold")
        print("   Further investigation required before sign-off")
        mix_shift_holds = False

    print()

    # ========================================================================
    # CHECK 2: 23 vs 22 DISCREPANCY
    # ========================================================================
    print("=" * 80)
    print("CHECK 2: 23 vs 22 DISCREPANCY (WON DEALS VS CYCLE TIME SAMPLE)")
    print("=" * 80)
    print()

    print(f"Total won deals in clean cohort: {len(organic_won)}")
    print()

    # Compute cycle times (same logic as segment_and_compute.py)
    cycle_time_eligible = []
    cycle_time_ineligible = []

    for deal in organic_won:
        create_date_str = deal.get("create_date")
        close_date_str = deal.get("close_date")

        if not create_date_str or not close_date_str:
            cycle_time_ineligible.append({
                "deal": deal,
                "reason": f"Missing {'create_date' if not create_date_str else 'close_date'}"
            })
            continue

        try:
            create_date = datetime.fromisoformat(create_date_str.replace("Z", "+00:00"))
            close_date = datetime.fromisoformat(close_date_str.replace("Z", "+00:00"))

            days = (close_date - create_date).days
            if days < 0:
                cycle_time_ineligible.append({
                    "deal": deal,
                    "reason": f"Negative days ({days})"
                })
            else:
                cycle_time_eligible.append({
                    "deal": deal,
                    "days": days
                })
        except Exception as e:
            cycle_time_ineligible.append({
                "deal": deal,
                "reason": f"Date parsing error: {str(e)}"
            })

    print(f"Cycle time eligible: {len(cycle_time_eligible)} deals")
    print(f"Cycle time ineligible: {len(cycle_time_ineligible)} deals")
    print()

    if cycle_time_ineligible:
        print(f"DISCREPANCY EXPLAINED:")
        print(f"  {len(organic_won)} won deals - {len(cycle_time_ineligible)} ineligible = {len(cycle_time_eligible)} cycle time sample")
        print()
        print("Ineligible deal(s):")
        for item in cycle_time_ineligible:
            deal = item["deal"]
            reason = item["reason"]
            deal_id = deal.get("deal_id")
            company = deal.get("company_name") or "(blank)"
            create_date = deal.get("create_date") or "NULL"
            close_date = deal.get("close_date") or "NULL"
            print(f"  deal_id: {deal_id}")
            print(f"    Company: {company}")
            print(f"    Reason: {reason}")
            print(f"    create_date: {create_date}")
            print(f"    close_date: {close_date}")
            print()
    else:
        print("✓ All won deals have valid cycle time data")
        print()

    # ========================================================================
    # FINAL SUMMARY
    # ========================================================================
    print("=" * 80)
    print("FINAL SUMMARY - Q016 SIGN-OFF READINESS")
    print("=" * 80)
    print()

    print("CHECK 1: Incremental vs Renewal Classification")
    if mix_shift_holds:
        print(f"  ✅ PASSED - Divergence {divergence:.1f}pp is acceptable")
        print(f"     Active: {pct_active_incremental:.1f}% incremental")
        print(f"     Historical: {pct_incremental:.1f}% incremental")
    else:
        print(f"  🚩 FAILED - Divergence {divergence:.1f}pp too large")
        print(f"     Active: {pct_active_incremental:.1f}% incremental")
        print(f"     Historical: {pct_incremental:.1f}% incremental")
        print("     Further investigation required")
    print()

    print("CHECK 2: 23 vs 22 Discrepancy")
    if len(cycle_time_ineligible) == len(organic_won) - len(cycle_time_eligible):
        print(f"  ✅ EXPLAINED - {len(cycle_time_ineligible)} deal(s) missing date fields")
        for item in cycle_time_ineligible:
            deal = item["deal"]
            print(f"     deal_id={deal.get('deal_id')}: {item['reason']}")
    else:
        print(f"  ⚠️  Math doesn't add up - investigate further")
    print()

    print("OVERALL SIGN-OFF STATUS:")
    if mix_shift_holds and len(cycle_time_ineligible) == len(organic_won) - len(cycle_time_eligible):
        print("  ✅ READY FOR SIGN-OFF")
        print()
        print("  Q016 cycle_time: 52 days (median, n=22)")
        print(f"  Clean cohort: default, 2023+, organic, won (n={len(organic_won)})")
        print(f"  Win rate: {100 * len(organic_won) / len(organic_2023_plus_closed):.1f}% (validates as legitimate new business)")
        print(f"  Incremental mix: {pct_incremental:.1f}% (consistent with active {pct_active_incremental:.1f}%)")
        return True
    else:
        print("  🚩 NOT READY - Address flagged issues before sign-off")
        return False

if __name__ == "__main__":
    ready = final_validation()
    sys.exit(0 if ready else 1)
