#!/usr/bin/env python3
"""
EXPLICIT SEGMENTATION BEFORE COMPUTATION

Define cohorts FIRST, compute within them SECOND.
Do not blend across ERA or EVENT boundaries - that's apples to oranges.

SEGMENTATION HIERARCHY:
1. ERA: Pre-2023 vs 2023+ (pipeline scheme change)
2. EVENT: Bulk cleanup vs organic closures
3. MOTION: Within 2023+ organic - check for deal type/segment patterns

Target cohort for Q016: "default pipeline, 2023+, organic, non-bulk, won"
This is the ONLY cohort comparable to today's 306 active incremental deals.
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone
from collections import Counter, defaultdict

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_won

def define_segments():
    """Define all segments BEFORE computing anything."""
    sb = get_supabase()

    print("=" * 80)
    print("EXPLICIT SEGMENTATION - DEFINE COHORTS FIRST")
    print("=" * 80)
    print()

    # Fetch ALL deals with full attributes
    all_deals = sb.table("deals").select(
        "deal_id,company_name,pipeline_id,deal_status,stage,create_date,close_date,"
        "lost_reason,new_arr,expansion_arr,renewal_revenue,segment"
    ).execute()

    DEFAULT_PIPELINE_ID = "default"
    RENEWAL_PIPELINE_ID = "866608541"

    # Start with default pipeline only
    default_deals = [d for d in all_deals.data if d.get("pipeline_id") == DEFAULT_PIPELINE_ID]

    print(f"Starting population: {len(default_deals)} default pipeline deals")
    print()

    # ========================================================================
    # SEGMENT 1: ERA (Pre-2023 vs 2023+)
    # ========================================================================
    print("=" * 80)
    print("SEGMENT 1: ERA (Pipeline Scheme Change)")
    print("=" * 80)
    print()

    ERA_CUTOFF = datetime(2023, 1, 1, tzinfo=timezone.utc)

    pre_2023 = []
    era_2023_plus = []

    for deal in default_deals:
        create_date_str = deal.get("create_date")
        if create_date_str:
            try:
                create_date = datetime.fromisoformat(create_date_str.replace("Z", "+00:00"))
                if create_date < ERA_CUTOFF:
                    pre_2023.append(deal)
                else:
                    era_2023_plus.append(deal)
            except:
                # If can't parse, assume 2023+ (safer default)
                era_2023_plus.append(deal)
        else:
            era_2023_plus.append(deal)

    print(f"ERA SEGMENTATION:")
    print(f"  Pre-2023 (legacy process): {len(pre_2023)} deals")
    print(f"  2023+ (current process): {len(era_2023_plus)} deals")
    print()
    print("RATIONALE: Pre-2023 deals created before renewal pipeline existed.")
    print("Different process, not comparable to current motion. EXCLUDE from Q016.")
    print()

    # ========================================================================
    # SEGMENT 2: EVENT (Bulk Cleanup vs Organic)
    # ========================================================================
    print("=" * 80)
    print("SEGMENT 2: EVENT (Bulk Cleanup vs Organic)")
    print("=" * 80)
    print()

    # Work only with 2023+ deals
    era_2023_plus_closed = [d for d in era_2023_plus if d.get("deal_status") in ["won", "lost"]]

    # Define bulk cleanup events (blank lost_reason + clustered by month)
    # First, identify all months with >10 blank lost_reason deals
    lost_2023_plus = [d for d in era_2023_plus if d.get("deal_status") == "lost"]

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
    for month, deals in blank_by_month.items():
        if len(deals) > 10:
            bulk_cleanup_months.add(month)

    print(f"BULK CLEANUP MONTHS DETECTED (>10 blank lost_reason/month):")
    for month in sorted(bulk_cleanup_months):
        count = len(blank_by_month[month])
        print(f"  {month}: {count} deals")
    print()

    # Segment: Bulk cleanup vs Organic
    bulk_cleanup_deals = []
    organic_deals = []

    for deal in era_2023_plus_closed:
        close_date_str = deal.get("close_date")
        is_bulk = False

        if close_date_str and not deal.get("lost_reason") and deal.get("deal_status") == "lost":
            try:
                close_date = datetime.fromisoformat(close_date_str.replace("Z", "+00:00"))
                month_key = f"{close_date.year}-{close_date.month:02d}"
                if month_key in bulk_cleanup_months:
                    is_bulk = True
            except:
                pass

        if is_bulk:
            bulk_cleanup_deals.append(deal)
        else:
            organic_deals.append(deal)

    print(f"EVENT SEGMENTATION (2023+ closed deals):")
    print(f"  Bulk cleanup: {len(bulk_cleanup_deals)} deals")
    print(f"  Organic closures: {len(organic_deals)} deals")
    print()
    print("RATIONALE: Bulk cleanup = admin operations, not sales outcomes.")
    print("EXCLUDE from win rate and cycle time calculations.")
    print()

    # ========================================================================
    # TARGET COHORT: 2023+, Organic, Won
    # ========================================================================
    print("=" * 80)
    print("TARGET COHORT: 2023+ ORGANIC WON DEALS")
    print("=" * 80)
    print()

    organic_won = [d for d in organic_deals if is_won(d.get("stage"))]
    organic_lost = [d for d in organic_deals if d.get("deal_status") == "lost"]

    print(f"TARGET COHORT (default pipeline, 2023+, organic):")
    print(f"  Won: {len(organic_won)} deals")
    print(f"  Lost: {len(organic_lost)} deals")
    print(f"  Total closed: {len(organic_won) + len(organic_lost)}")
    print()

    # Win rate
    total_organic_closed = len(organic_won) + len(organic_lost)
    organic_win_rate = 100 * len(organic_won) / total_organic_closed if total_organic_closed > 0 else 0

    print(f"WIN RATE (2023+, organic only): {organic_win_rate:.1f}%")
    print()

    if 15 <= organic_win_rate <= 30:
        print(f"✅ WIN RATE ({organic_win_rate:.1f}%) IN EXPECTED RANGE (15-30%)")
    elif organic_win_rate < 15:
        print(f"⚠️  WIN RATE ({organic_win_rate:.1f}%) LOW (<15%)")
    else:
        print(f"✓ WIN RATE ({organic_win_rate:.1f}%) HIGH (>30%)")
    print()

    # ========================================================================
    # SEGMENT 3: MOTION (Deal Type / Segment within Organic Won)
    # ========================================================================
    print("=" * 80)
    print("SEGMENT 3: MOTION (Deal Type / Segment Analysis)")
    print("=" * 80)
    print()

    # Check if there's segmentation by segment
    segment_counts = Counter(d.get("segment") for d in organic_won)

    print(f"Segment distribution (organic won, n={len(organic_won)}):")
    for segment, count in sorted(segment_counts.items(), key=lambda x: -x[1]):
        pct = 100 * count / len(organic_won) if len(organic_won) > 0 else 0
        print(f"  {segment or '(blank)'}: {count} ({pct:.1f}%)")
    print()

    # Check if further segmentation is needed
    has_segment_variance = len([s for s in segment_counts.keys() if s]) > 1

    if has_segment_variance:
        print("⚠️  MULTIPLE SEGMENTS DETECTED")
        print("   May need further segmentation if cycle times differ significantly")
    else:
        print("✓ Homogeneous cohort - no further segmentation needed")
    print()

    # ========================================================================
    # CYCLE TIME COMPUTATION (Within Target Cohort Only)
    # ========================================================================
    print("=" * 80)
    print("CYCLE TIME (2023+ ORGANIC WON ONLY)")
    print("=" * 80)
    print()

    # Compute cycle time for organic won deals
    cycle_times = []
    for deal in organic_won:
        create_date_str = deal.get("create_date")
        close_date_str = deal.get("close_date")

        if create_date_str and close_date_str:
            try:
                create_date = datetime.fromisoformat(create_date_str.replace("Z", "+00:00"))
                close_date = datetime.fromisoformat(close_date_str.replace("Z", "+00:00"))

                days = (close_date - create_date).days
                if days >= 0:  # Exclude negative/bad data
                    cycle_times.append({
                        "company": deal.get("company_name"),
                        "days": days,
                        "segment": deal.get("segment"),
                        "close_date": close_date
                    })
            except:
                pass

    cycle_times.sort(key=lambda x: x["days"])

    print(f"Cycle time population: {len(cycle_times)} of {len(organic_won)} won deals")
    print(f"  (deals with both create_date and close_date, days >= 0)")
    print()

    if cycle_times:
        import statistics

        days_only = [ct["days"] for ct in cycle_times]
        median_days = statistics.median(days_only)
        mean_days = statistics.mean(days_only)
        p25 = statistics.quantiles(days_only, n=4)[0] if len(days_only) >= 4 else None
        p75 = statistics.quantiles(days_only, n=4)[2] if len(days_only) >= 4 else None

        print(f"CYCLE TIME DISTRIBUTION:")
        print(f"  Median: {median_days:.0f} days")
        print(f"  Mean: {mean_days:.0f} days")
        if p25 and p75:
            print(f"  P25: {p25:.0f} days")
            print(f"  P75: {p75:.0f} days")
        print(f"  Min: {min(days_only)} days")
        print(f"  Max: {max(days_only)} days")
        print()

        # Show all deals (since sample is small)
        print(f"All {len(cycle_times)} deals:")
        print(f"{'Company':<30} {'Days':<6} {'Close Date':<12} {'Segment':<15}")
        print("-" * 70)
        for ct in cycle_times:
            company = (ct["company"] or "")[:29]
            days = ct["days"]
            close_date = ct["close_date"].date()
            segment = (ct["segment"] or "")[:14]
            print(f"{company:<30} {days:<6} {close_date!s:<12} {segment:<15}")
        print()

    # ========================================================================
    # CROSS-COHORT COMPARISON (Apples to Apples)
    # ========================================================================
    print("=" * 80)
    print("CROSS-COHORT COMPARISON (APPLES TO APPLES)")
    print("=" * 80)
    print()

    # Active pipeline (today's 306 deals)
    active_deals = [d for d in all_deals.data if d.get("deal_status") == "active"]
    active_default = [d for d in active_deals if d.get("pipeline_id") == DEFAULT_PIPELINE_ID]
    active_default_incremental = [
        d for d in active_default
        if (d.get("new_arr") or 0) > 0 or (d.get("expansion_arr") or 0) > 0
    ]

    print(f"ACTIVE PIPELINE (today):")
    print(f"  Total active default: {len(active_default)} deals")
    print(f"  With incremental ARR: {len(active_default_incremental)} deals")
    print()

    print(f"HISTORICAL COHORT (2023+, organic, won):")
    print(f"  Won deals: {len(organic_won)} deals")
    print(f"  Cycle time sample: {len(cycle_times)} deals")
    print(f"  Median cycle time: {median_days:.0f} days" if cycle_times else "  (no cycle time data)")
    print()

    print("COMPARISON:")
    print(f"  Active incremental deals: {len(active_default_incremental)}")
    print(f"  Historical won deals (2023+, organic): {len(organic_won)}")
    ratio = len(active_default_incremental) / len(organic_won) if len(organic_won) > 0 else float('inf')
    print(f"  Ratio: {ratio:.1f}x")
    print()

    if ratio > 10:
        print(f"⚠️  VERY HIGH RATIO ({ratio:.1f}x)")
        print("   Active pipeline significantly larger than historical wins")
        print("   Could indicate:")
        print("     - Recent ramp in new business motion")
        print("     - Long sales cycles (deals haven't closed yet)")
        print("     - Low historical win rate")
    elif 3 <= ratio <= 10:
        print(f"✓ MODERATE RATIO ({ratio:.1f}x)")
        print("   Active pipeline larger than historical wins - plausible")
    else:
        print(f"✓ BALANCED RATIO ({ratio:.1f}x)")

    print()

    # ========================================================================
    # SUMMARY: SEGMENTATION-FIRST APPROACH
    # ========================================================================
    print("=" * 80)
    print("SUMMARY: SEGMENTATION-FIRST RESULTS")
    print("=" * 80)
    print()

    print("COHORT DEFINITIONS:")
    print(f"  1. ERA: Pre-2023 ({len(pre_2023)}) vs 2023+ ({len(era_2023_plus)})")
    print(f"  2. EVENT: Bulk cleanup ({len(bulk_cleanup_deals)}) vs Organic ({len(organic_deals)})")
    print(f"  3. MOTION: Analyzed within organic won ({len(organic_won)})")
    print()

    print("TARGET COHORT (default, 2023+, organic, won):")
    print(f"  Population: {len(organic_won)} deals")
    print(f"  Win rate: {organic_win_rate:.1f}%")
    print(f"  Cycle time: {median_days:.0f} days (median, n={len(cycle_times)})" if cycle_times else "  Cycle time: N/A")
    print()

    print("VALIDATION:")
    if 15 <= organic_win_rate <= 30:
        print(f"  ✅ Win rate ({organic_win_rate:.1f}%) validates cohort as legitimate new business")
    else:
        print(f"  ⚠️  Win rate ({organic_win_rate:.1f}%) outside expected range - needs review")

    if len(cycle_times) >= 20:
        print(f"  ✅ Sample size ({len(cycle_times)}) adequate for reliable cycle time")
    elif len(cycle_times) >= 10:
        print(f"  ⚠️  Sample size ({len(cycle_times)}) small but usable")
    else:
        print(f"  ⚠️  Sample size ({len(cycle_times)}) very small - cycle time may not be reliable")

    print()

    print("WHAT CHANGED FROM EARLIER APPROACH:")
    print("  BEFORE: Computed on blended population (606 lost), then explained contamination")
    print(f"  AFTER: Defined segments first, computed within clean cohort ({len(organic_deals)} organic)")
    print("  IMPACT: Win rate 3.7% → {:.1f}% (apples-to-apples comparison)".format(organic_win_rate))
    print()

    return {
        "organic_won": organic_won,
        "organic_lost": organic_lost,
        "cycle_times": cycle_times,
        "win_rate": organic_win_rate,
        "median_cycle_time": median_days if cycle_times else None,
        "bulk_cleanup_months": bulk_cleanup_months
    }

if __name__ == "__main__":
    result = define_segments()
