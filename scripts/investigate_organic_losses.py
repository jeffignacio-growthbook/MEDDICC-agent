#!/usr/bin/env python3
"""
INVESTIGATION 4: Deep dive into 361 "organic" losses in default pipeline.

After excluding April 2026 bulk cleanup (235 deals) and pre-2023 deals (22 deals),
we're left with 361 "organic losses" (post-2023, not bulk) — but 6.0% win rate
is still below expected 15-30% range.

Check:
1. Are there OTHER bulk cleanup events besides April 2026?
2. Lost_reason distribution (blank = likely junk/cleanup)
3. Stage distribution (are these real sales losses or admin cleanup?)
4. Month-by-month distribution to spot patterns
5. Sample deals to understand what they represent
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
from field_semantics import is_won, is_lost

def investigate_organic_losses():
    sb = get_supabase()

    print("=" * 80)
    print("INVESTIGATION 4: DEEP DIVE INTO 361 'ORGANIC' LOSSES")
    print("=" * 80)
    print()

    # Fetch ALL deals
    all_deals = sb.table("deals").select(
        "deal_id,company_name,pipeline_id,deal_status,stage,create_date,close_date,"
        "lost_reason,new_arr,expansion_arr,renewal_revenue"
    ).execute()

    DEFAULT_PIPELINE_ID = "default"
    RENEWAL_PIPELINE_ID = "866608541"

    # Get lost default pipeline deals
    lost_default = [
        d for d in all_deals.data
        if d.get("deal_status") == "lost" and d.get("pipeline_id") == DEFAULT_PIPELINE_ID
    ]

    # Segment out the noise we already identified
    april_2026_bulk = []
    for deal in lost_default:
        close_date_str = deal.get("close_date")
        lost_reason = deal.get("lost_reason")

        if close_date_str and not lost_reason:  # Blank lost reason
            try:
                close_date = datetime.fromisoformat(close_date_str.replace("Z", "+00:00"))
                if close_date.year == 2026 and close_date.month == 4:
                    april_2026_bulk.append(deal)
            except:
                pass

    pre_2023 = []
    for deal in lost_default:
        create_date_str = deal.get("create_date")

        if create_date_str:
            try:
                create_date = datetime.fromisoformat(create_date_str.replace("Z", "+00:00"))
                if create_date.year < 2023:
                    pre_2023.append(deal)
            except:
                pass

    # Organic losses = everything else
    organic_losses = [
        d for d in lost_default
        if d not in april_2026_bulk and d not in pre_2023
    ]

    print(f"Total lost default pipeline deals: {len(lost_default)}")
    print(f"  April 2026 bulk cleanup: {len(april_2026_bulk)}")
    print(f"  Pre-2023 deals: {len(pre_2023)}")
    print(f"  Organic losses (post-2023, not April bulk): {len(organic_losses)}")
    print()

    # ========================================================================
    # CHECK 1: Lost_reason distribution for organic losses
    # ========================================================================
    print("=" * 80)
    print("CHECK 1: LOST_REASON DISTRIBUTION")
    print("=" * 80)
    print()

    lost_reason_counts = Counter(d.get("lost_reason") or "(blank)" for d in organic_losses)

    print(f"Lost reason distribution for {len(organic_losses)} organic losses:")
    for reason, count in sorted(lost_reason_counts.items(), key=lambda x: -x[1])[:15]:
        pct = 100 * count / len(organic_losses)
        print(f"  '{reason}': {count} ({pct:.1f}%)")

    print()

    blank_count = lost_reason_counts.get("(blank)", 0)
    blank_pct = 100 * blank_count / len(organic_losses) if len(organic_losses) > 0 else 0

    if blank_pct > 50:
        print(f"⚠️  {blank_pct:.1f}% of organic losses have blank lost_reason")
        print("   Blank lost_reason typically indicates admin cleanup, not sales feedback")
    else:
        print(f"✓ Only {blank_pct:.1f}% blank lost_reason - most have sales feedback")

    print()

    # ========================================================================
    # CHECK 2: Month-by-month distribution to spot additional bulk events
    # ========================================================================
    print("=" * 80)
    print("CHECK 2: MONTHLY DISTRIBUTION (SPOT BULK EVENTS)")
    print("=" * 80)
    print()

    # Parse close dates
    close_dates = []
    for deal in organic_losses:
        close_date_str = deal.get("close_date")
        if close_date_str:
            try:
                close_date = datetime.fromisoformat(close_date_str.replace("Z", "+00:00"))
                close_dates.append(close_date)
            except:
                pass

    close_dates.sort()

    if close_dates:
        print(f"Organic losses with valid close_date: {len(close_dates)} of {len(organic_losses)}")
        print()

        # Group by month
        by_month = defaultdict(int)
        for dt in close_dates:
            month_key = f"{dt.year}-{dt.month:02d}"
            by_month[month_key] += 1

        # Find months with >30 deals (potential bulk event)
        bulk_candidates = [(month, count) for month, count in by_month.items() if count > 30]

        if bulk_candidates:
            print("⚠️  POTENTIAL ADDITIONAL BULK EVENTS (>30 deals in a month):")
            print()
            for month, count in sorted(bulk_candidates, key=lambda x: -x[1]):
                pct = 100 * count / len(close_dates)
                print(f"  {month}: {count} deals ({pct:.1f}%)")

            print()
            print("  These may be additional bulk cleanup events")
        else:
            print("✓ No additional bulk events detected (no month >30 deals)")

        print()

        # Show distribution by year-month (last 24 months)
        print("Monthly distribution (last 24 months):")
        recent_months = sorted([m for m in by_month.keys() if m >= "2024-09"], reverse=True)[:24]

        for month in recent_months:
            count = by_month[month]
            pct = 100 * count / len(close_dates) if len(close_dates) > 0 else 0
            bar = "█" * min(int(count / 2), 50)  # Scale bar
            print(f"  {month}: {count:3d} {bar} ({pct:.1f}%)")

    print()

    # ========================================================================
    # CHECK 3: Stage distribution for organic losses
    # ========================================================================
    print("=" * 80)
    print("CHECK 3: STAGE DISTRIBUTION")
    print("=" * 80)
    print()

    stage_counts = Counter(d.get("stage") for d in organic_losses)

    print(f"Stage distribution for {len(organic_losses)} organic losses:")
    for stage, count in sorted(stage_counts.items(), key=lambda x: -x[1])[:10]:
        pct = 100 * count / len(organic_losses)
        print(f"  '{stage}': {count} ({pct:.1f}%)")

    print()

    # Check if these are expected closed-lost stages
    expected_lost_stages = [
        "closedlost", "closed lost", "lost", "disqualified", "unresponsive",
        "not a fit", "no budget", "timing", "competitor"
    ]

    unexpected_stages = []
    for stage, count in stage_counts.items():
        stage_lower = (stage or "").lower()
        if not any(expected in stage_lower for expected in expected_lost_stages):
            unexpected_stages.append((stage, count))

    if unexpected_stages:
        print(f"⚠️  UNEXPECTED STAGES (not typical closed-lost):")
        for stage, count in unexpected_stages[:5]:
            pct = 100 * count / len(organic_losses)
            print(f"  '{stage}': {count} ({pct:.1f}%)")
        print()
        print("  These may be misclassified (deal_status='lost' but stage doesn't match)")
    else:
        print("✓ All stages are expected closed-lost stages")

    print()

    # ========================================================================
    # CHECK 4: Sample organic losses to understand what they represent
    # ========================================================================
    print("=" * 80)
    print("CHECK 4: SAMPLE OF 20 ORGANIC LOSSES")
    print("=" * 80)
    print()

    import random
    sample = random.sample(organic_losses, min(20, len(organic_losses)))

    print(f"{'Company':<30} {'Stage':<25} {'Close Date':<12} {'Lost Reason':<30}")
    print("-" * 100)

    for deal in sample:
        company = (deal.get("company_name") or "")[:29]
        stage = (deal.get("stage") or "")[:24]
        close_date = deal.get("close_date", "")[:10] if deal.get("close_date") else "N/A"
        lost_reason = (deal.get("lost_reason") or "(blank)")[:29]

        print(f"{company:<30} {stage:<25} {close_date:<12} {lost_reason:<30}")

    print()

    # ========================================================================
    # CHECK 5: Breakdown by presence of lost_reason
    # ========================================================================
    print("=" * 80)
    print("CHECK 5: ORGANIC LOSSES WITH VS WITHOUT LOST_REASON")
    print("=" * 80)
    print()

    with_reason = [d for d in organic_losses if d.get("lost_reason")]
    without_reason = [d for d in organic_losses if not d.get("lost_reason")]

    print(f"Organic losses breakdown:")
    print(f"  With lost_reason: {len(with_reason)} ({100*len(with_reason)/len(organic_losses):.1f}%)")
    print(f"  Without lost_reason (blank): {len(without_reason)} ({100*len(without_reason)/len(organic_losses):.1f}%)")
    print()

    if len(without_reason) > len(with_reason):
        print("⚠️  MAJORITY have blank lost_reason - likely admin cleanup, not sales feedback")
        print()
        print("HYPOTHESIS: The 361 'organic losses' may contain MULTIPLE bulk cleanup events,")
        print("not just April 2026. Need to look at monthly clusters with blank lost_reason.")
    else:
        print("✓ Majority have lost_reason - these appear to be genuine sales losses")

    print()

    # ========================================================================
    # CHECK 6: Find all bulk cleanup candidates (blank lost_reason clusters)
    # ========================================================================
    print("=" * 80)
    print("CHECK 6: ALL BULK CLEANUP CANDIDATES (BLANK LOST_REASON)")
    print("=" * 80)
    print()

    # Get close dates for deals with blank lost_reason
    blank_reason_dates = []
    for deal in organic_losses:
        if not deal.get("lost_reason"):
            close_date_str = deal.get("close_date")
            if close_date_str:
                try:
                    close_date = datetime.fromisoformat(close_date_str.replace("Z", "+00:00"))
                    blank_reason_dates.append(close_date)
                except:
                    pass

    blank_reason_dates.sort()

    if blank_reason_dates:
        # Group by month
        blank_by_month = defaultdict(int)
        for dt in blank_reason_dates:
            month_key = f"{dt.year}-{dt.month:02d}"
            blank_by_month[month_key] += 1

        print(f"Blank lost_reason deals by month (showing months with >10 deals):")
        print()

        bulk_cleanup_months = []
        for month in sorted(blank_by_month.keys(), reverse=True):
            count = blank_by_month[month]
            if count > 10:  # Threshold for potential bulk event
                pct = 100 * count / len(blank_reason_dates)
                bulk_cleanup_months.append((month, count))
                print(f"  {month}: {count} deals ({pct:.1f}%)")

        print()

        if len(bulk_cleanup_months) > 1:
            print(f"⚠️  FOUND {len(bulk_cleanup_months)} BULK CLEANUP MONTHS (>10 blank lost_reason deals)")
            print()
            print("These are all likely bulk cleanup events, NOT organic sales losses.")
            print()
            total_bulk_cleanup = sum(count for _, count in bulk_cleanup_months)
            print(f"Total deals in bulk cleanup months: {total_bulk_cleanup}")
            print(f"Percentage of organic losses: {100*total_bulk_cleanup/len(organic_losses):.1f}%")
        else:
            print("✓ Only one bulk cleanup month detected")

    print()

    # ========================================================================
    # SUMMARY
    # ========================================================================
    print("=" * 80)
    print("INVESTIGATION 4 SUMMARY")
    print("=" * 80)
    print()

    print(f"361 'organic losses' breakdown:")
    print(f"  With lost_reason (likely real sales losses): {len(with_reason)}")
    print(f"  Blank lost_reason (likely cleanup): {len(without_reason)}")
    print()

    if blank_pct > 50 and len(bulk_cleanup_months) > 1:
        print("⚠️  ADDITIONAL CONTAMINATION DETECTED:")
        print()
        print(f"  {len(bulk_cleanup_months)} bulk cleanup months found (>10 blank lost_reason deals/month)")
        print(f"  Total bulk cleanup deals: {total_bulk_cleanup} ({100*total_bulk_cleanup/len(organic_losses):.1f}%)")
        print()
        print("CORRECTED POPULATION for win rate:")
        truly_organic = len(organic_losses) - total_bulk_cleanup
        won_count = 23  # From segment_default_pipeline.py
        corrected_win_rate = 100 * won_count / (won_count + truly_organic) if (won_count + truly_organic) > 0 else 0
        print(f"  Won: {won_count}")
        print(f"  Truly organic losses: {truly_organic}")
        print(f"  CORRECTED WIN RATE: {corrected_win_rate:.1f}%")
        print()

        if 15 <= corrected_win_rate <= 30:
            print(f"✅ CORRECTED WIN RATE ({corrected_win_rate:.1f}%) IN EXPECTED RANGE (15-30%)")
            print("   Default pipeline is LEGITIMATE new business pipeline")
        elif corrected_win_rate < 15:
            print(f"⚠️  CORRECTED WIN RATE ({corrected_win_rate:.1f}%) STILL LOW (<15%)")
            print("   May need further investigation")
        else:
            print(f"✓ CORRECTED WIN RATE ({corrected_win_rate:.1f}%) ABOVE TYPICAL (>30%)")

if __name__ == "__main__":
    investigate_organic_losses()
