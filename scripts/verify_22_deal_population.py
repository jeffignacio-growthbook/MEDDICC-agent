#!/usr/bin/env python3
"""
Verify the 22 non-renewal won deals number before accepting 52 days as correct.

Checks:
1. Pipeline_id filter correctness (does "866608541" catch ALL renewals?)
2. is_won() correctness across both populations
3. Active vs historical business mix (306 active non-renewal vs 22 won?)
4. Date range for won deals (truly all-time or bounded?)
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

def verify_population():
    sb = get_supabase()

    print("=" * 80)
    print("VERIFYING 22 NON-RENEWAL WON DEALS POPULATION")
    print("=" * 80)
    print()

    # Fetch ALL deals (not just won)
    all_deals = sb.table("deals").select(
        "deal_id,company_name,create_date,close_date,stage,pipeline_id,deal_status"
    ).execute()

    print(f"Total deals in database: {len(all_deals.data)}")
    print()

    # ============================================================================
    # CHECK 1: Pipeline_id distribution
    # ============================================================================
    print("=" * 80)
    print("CHECK 1: PIPELINE_ID DISTRIBUTION")
    print("=" * 80)
    print()

    from collections import Counter

    # All deals
    pipeline_counts_all = Counter(d.get("pipeline_id") for d in all_deals.data)
    print("Pipeline_id distribution (ALL deals):")
    for pid, count in sorted(pipeline_counts_all.items(), key=lambda x: -x[1]):
        print(f"  {pid}: {count} deals ({100*count/len(all_deals.data):.1f}%)")
    print()

    # Active deals only
    active_deals = [d for d in all_deals.data if d.get("deal_status") == "active"]
    pipeline_counts_active = Counter(d.get("pipeline_id") for d in active_deals)
    print(f"Pipeline_id distribution (ACTIVE deals, n={len(active_deals)}):")
    for pid, count in sorted(pipeline_counts_active.items(), key=lambda x: -x[1]):
        print(f"  {pid}: {count} deals ({100*count/len(active_deals):.1f}%)")
    print()

    # Won deals only
    won_deals_all = [d for d in all_deals.data if is_won(d.get("stage"))]
    pipeline_counts_won = Counter(d.get("pipeline_id") for d in won_deals_all)
    print(f"Pipeline_id distribution (WON deals, n={len(won_deals_all)}):")
    for pid, count in sorted(pipeline_counts_won.items(), key=lambda x: -x[1]):
        print(f"  {pid}: {count} deals ({100*count/len(won_deals_all):.1f}%)")
    print()

    # Check for unexpected pipeline IDs
    expected_renewal_pid = "866608541"
    unexpected_pids = [pid for pid in pipeline_counts_won.keys() if pid not in [expected_renewal_pid, "default", None]]

    if unexpected_pids:
        print(f"⚠️  UNEXPECTED pipeline_ids found: {unexpected_pids}")
        print(f"   May need to check if these are renewal or non-renewal")
    else:
        print(f"✓ Only expected pipeline_ids found ('{expected_renewal_pid}', 'default', None)")
    print()

    # ============================================================================
    # CHECK 2: is_won() correctness
    # ============================================================================
    print("=" * 80)
    print("CHECK 2: is_won() STAGE RECOGNITION")
    print("=" * 80)
    print()

    # Count by stage for won deals
    stage_counts = Counter(d.get("stage") for d in won_deals_all)
    print(f"Stage distribution for is_won()=True deals (n={len(won_deals_all)}):")
    for stage, count in sorted(stage_counts.items(), key=lambda x: -x[1]):
        print(f"  '{stage}': {count} deals")
    print()

    # Check if deal_status contradicts is_won()
    status_mismatch = []
    for deal in all_deals.data:
        stage_says_won = is_won(deal.get("stage"))
        status_says_won = deal.get("deal_status") == "won"

        if stage_says_won != status_says_won:
            status_mismatch.append({
                "company": deal.get("company_name"),
                "stage": deal.get("stage"),
                "deal_status": deal.get("deal_status"),
                "stage_says_won": stage_says_won,
                "status_says_won": status_says_won
            })

    if status_mismatch:
        print(f"⚠️  MISMATCH between is_won(stage) and deal_status: {len(status_mismatch)} deals")
        print("Sample mismatches:")
        for deal in status_mismatch[:5]:
            print(f"  {deal['company']}: stage='{deal['stage']}', deal_status='{deal['deal_status']}'")
        print()
    else:
        print("✓ is_won(stage) matches deal_status='won' for all deals")
        print()

    # ============================================================================
    # CHECK 3: Business mix shift (active vs historical)
    # ============================================================================
    print("=" * 80)
    print("CHECK 3: BUSINESS MIX (ACTIVE vs HISTORICAL WON)")
    print("=" * 80)
    print()

    RENEWAL_PIPELINE_ID = "866608541"

    # Active deals split
    active_renewal = [d for d in active_deals if d.get("pipeline_id") == RENEWAL_PIPELINE_ID]
    active_non_renewal = [d for d in active_deals if d.get("pipeline_id") != RENEWAL_PIPELINE_ID]

    print(f"ACTIVE deals (n={len(active_deals)}):")
    print(f"  Renewal pipeline: {len(active_renewal)} ({100*len(active_renewal)/len(active_deals):.1f}%)")
    print(f"  Non-renewal: {len(active_non_renewal)} ({100*len(active_non_renewal)/len(active_deals):.1f}%)")
    print()

    # Won deals split
    won_renewal = [d for d in won_deals_all if d.get("pipeline_id") == RENEWAL_PIPELINE_ID]
    won_non_renewal = [d for d in won_deals_all if d.get("pipeline_id") != RENEWAL_PIPELINE_ID]

    print(f"WON deals (n={len(won_deals_all)}):")
    print(f"  Renewal pipeline: {len(won_renewal)} ({100*len(won_renewal)/len(won_deals_all):.1f}%)")
    print(f"  Non-renewal: {len(won_non_renewal)} ({100*len(won_non_renewal)/len(won_deals_all):.1f}%)")
    print()

    pct_active_non_renewal = 100 * len(active_non_renewal) / len(active_deals)
    pct_won_non_renewal = 100 * len(won_non_renewal) / len(won_deals_all)
    shift = pct_active_non_renewal - pct_won_non_renewal

    print(f"BUSINESS MIX SHIFT:")
    print(f"  Active pipeline: {pct_active_non_renewal:.1f}% non-renewal")
    print(f"  Historical wins: {pct_won_non_renewal:.1f}% non-renewal")
    print(f"  Shift: {shift:.1f} percentage points")
    print()

    if abs(shift) > 30:
        print("⚠️  MASSIVE SHIFT (>30pp) - this needs explanation:")
        print("   - Did GrowthBook pivot from renewal-heavy to new-business recently?")
        print("   - Or is this a population/filter bug?")
    elif abs(shift) > 15:
        print("⚠️  SIGNIFICANT SHIFT (>15pp) - worth investigating")
    else:
        print("✓ Business mix shift is reasonable")
    print()

    # ============================================================================
    # CHECK 4: Date range for won deals
    # ============================================================================
    print("=" * 80)
    print("CHECK 4: DATE RANGE FOR WON DEALS")
    print("=" * 80)
    print()

    # Parse close dates for won deals
    won_with_dates = []
    for deal in won_deals_all:
        close_date_str = deal.get("close_date")
        if close_date_str:
            try:
                close_date = datetime.fromisoformat(close_date_str.replace("Z", "+00:00"))
                won_with_dates.append({
                    "company": deal.get("company_name"),
                    "close_date": close_date,
                    "pipeline_id": deal.get("pipeline_id")
                })
            except:
                pass

    won_with_dates.sort(key=lambda d: d["close_date"])

    print(f"Won deals with valid close_date: {len(won_with_dates)} of {len(won_deals_all)}")
    print()

    if won_with_dates:
        earliest = won_with_dates[0]
        latest = won_with_dates[-1]

        print(f"Date range:")
        print(f"  Earliest: {earliest['close_date'].date()} ({earliest['company']})")
        print(f"  Latest: {latest['close_date'].date()} ({latest['company']})")
        print()

        # Check if there's a cutoff
        date_gaps = []
        for i in range(1, len(won_with_dates)):
            gap_days = (won_with_dates[i]["close_date"] - won_with_dates[i-1]["close_date"]).days
            if gap_days > 180:  # 6-month gap
                date_gaps.append({
                    "before": won_with_dates[i-1],
                    "after": won_with_dates[i],
                    "gap_days": gap_days
                })

        if date_gaps:
            print(f"⚠️  LARGE DATE GAPS found (>180 days):")
            for gap in date_gaps:
                print(f"   {gap['before']['close_date'].date()} → {gap['after']['close_date'].date()} ({gap['gap_days']} days)")
            print()
        else:
            print("✓ No large date gaps - appears to be continuous all-time data")
            print()

        # Split by pipeline and show date ranges
        won_renewal_dates = [d for d in won_with_dates if d["pipeline_id"] == RENEWAL_PIPELINE_ID]
        won_non_renewal_dates = [d for d in won_with_dates if d["pipeline_id"] != RENEWAL_PIPELINE_ID]

        if won_renewal_dates:
            print(f"Renewal pipeline date range (n={len(won_renewal_dates)}):")
            print(f"  {won_renewal_dates[0]['close_date'].date()} to {won_renewal_dates[-1]['close_date'].date()}")
            print()

        if won_non_renewal_dates:
            print(f"Non-renewal date range (n={len(won_non_renewal_dates)}):")
            print(f"  {won_non_renewal_dates[0]['close_date'].date()} to {won_non_renewal_dates[-1]['close_date'].date()}")
            print()

    # ============================================================================
    # FINAL SUMMARY
    # ============================================================================
    print("=" * 80)
    print("FINAL POPULATION BREAKDOWN")
    print("=" * 80)
    print()

    print(f"Total won deals: {len(won_deals_all)}")
    print(f"  By pipeline_id:")
    for pid, count in sorted(pipeline_counts_won.items(), key=lambda x: -x[1]):
        pct = 100 * count / len(won_deals_all)
        pipeline_label = "RENEWAL" if pid == RENEWAL_PIPELINE_ID else "NON-RENEWAL"
        print(f"    {pid} ({pipeline_label}): {count} deals ({pct:.1f}%)")
    print()

    # Check cycle time calculation eligibility
    won_non_renewal_with_dates = [
        d for d in won_non_renewal
        if d.get("close_date") and d.get("create_date")
    ]

    print(f"Non-renewal won deals eligible for cycle time: {len(won_non_renewal_with_dates)}")
    print(f"  (has both create_date and close_date)")
    print()

    if len(won_non_renewal_with_dates) != 22:
        print(f"⚠️  DISCREPANCY: Expected 22, found {len(won_non_renewal_with_dates)}")
        print("   Need to check date parsing logic")
    else:
        print("✓ Count matches expected 22 non-renewal won deals")

    print()
    print("=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)
    print()

    if len(won_non_renewal) < 30:
        print(f"⚠️  VERY SMALL SAMPLE: Only {len(won_non_renewal)} non-renewal wins")
        print()
        print("Before accepting 52 days as final:")
        print("  1. Verify this matches Jeff's intuition for total non-renewal wins")
        print("  2. Confirm GrowthBook is genuinely renewal-heavy business (80%+ of wins)")
        print("  3. Consider if sample is too small for reliable cycle time metric")

if __name__ == "__main__":
    verify_population()
