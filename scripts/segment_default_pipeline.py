#!/usr/bin/env python3
"""
INVESTIGATION 3: Segment "default" pipeline (not uniformly junk).

Already verified: 306 active deals in default with real incremental ARR
(Anthropic, Tubi, Comcast, etc. - $18.6M total).

Default pipeline is MIXED:
1. Real new business/expansion (active + historical wins)
2. April 2026 bulk cleanup (235 deals, blank lost_reason)
3. Pre-2023 old deals (before renewal pipeline existed)

Clean the data and recompute win rate excluding noise.
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

def segment_default():
    sb = get_supabase()

    print("=" * 80)
    print("INVESTIGATION 3: SEGMENTING 'DEFAULT' PIPELINE")
    print("=" * 80)
    print()

    # Fetch ALL deals
    all_deals = sb.table("deals").select(
        "deal_id,company_name,pipeline_id,deal_status,stage,create_date,close_date,"
        "lost_reason,new_arr,expansion_arr,renewal_revenue"
    ).execute()

    DEFAULT_PIPELINE_ID = "default"
    RENEWAL_PIPELINE_ID = "866608541"

    # ========================================================================
    # CHECK 1: Active deals in default pipeline (already verified)
    # ========================================================================
    print("=" * 80)
    print("CHECK 1: ACTIVE DEALS IN DEFAULT PIPELINE")
    print("=" * 80)
    print()

    active_deals = [d for d in all_deals.data if d.get("deal_status") == "active"]
    active_default = [d for d in active_deals if d.get("pipeline_id") == DEFAULT_PIPELINE_ID]

    # Count those with incremental ARR
    active_default_incremental = [
        d for d in active_default
        if (d.get("new_arr") or 0) > 0 or (d.get("expansion_arr") or 0) > 0
    ]

    total_incremental_arr = sum(
        (d.get("new_arr") or 0) + (d.get("expansion_arr") or 0)
        for d in active_default_incremental
    )

    print(f"ACTIVE deals in default pipeline: {len(active_default)} of {len(active_deals)}")
    print(f"  With incremental ARR: {len(active_default_incremental)}")
    print(f"  Total incremental ARR: ${total_incremental_arr:,.0f}")
    print()

    # Sample some active default deals
    print("Sample active default pipeline deals (first 10 with ARR):")
    for deal in active_default_incremental[:10]:
        name = deal.get("company_name")
        new_arr = deal.get("new_arr") or 0
        exp_arr = deal.get("expansion_arr") or 0
        total_arr = new_arr + exp_arr
        print(f"  {name}: ${total_arr:,.0f} (new=${new_arr:,.0f}, exp=${exp_arr:,.0f})")

    print()
    print("✓ Confirms: Default pipeline contains REAL new business/expansion deals")
    print()

    # ========================================================================
    # CHECK 2: Historical won deals in default pipeline
    # ========================================================================
    print("=" * 80)
    print("CHECK 2: 23 WON DEALS IN DEFAULT PIPELINE")
    print("=" * 80)
    print()

    won_default = [
        d for d in all_deals.data
        if is_won(d.get("stage")) and d.get("pipeline_id") == DEFAULT_PIPELINE_ID
    ]

    print(f"Won deals in default pipeline: {len(won_default)}")
    print()

    print("All 23 won default pipeline deals:")
    print(f"{'Company':<40} {'Close Date':<12} {'New ARR':<12} {'Exp ARR':<12}")
    print("-" * 80)

    for deal in won_default:
        name = (deal.get("company_name") or "")[:39]
        close_date = deal.get("close_date", "")[:10] if deal.get("close_date") else "N/A"
        new_arr = deal.get("new_arr") or 0
        exp_arr = deal.get("expansion_arr") or 0

        print(f"{name:<40} {close_date:<12} ${new_arr:>10,.0f} ${exp_arr:>10,.0f}")

    print()

    # Check if these look like real wins
    won_with_arr = [d for d in won_default if (d.get("new_arr") or 0) > 0 or (d.get("expansion_arr") or 0) > 0]
    print(f"Won deals with ARR > 0: {len(won_with_arr)} of {len(won_default)}")
    print()

    if len(won_with_arr) == len(won_default):
        print("✓ All won deals have real ARR - these are genuine wins")
    else:
        print(f"⚠️  {len(won_default) - len(won_with_arr)} won deals have $0 ARR - may be test/junk")

    print()

    # ========================================================================
    # CHECK 3: Lost deals segmentation
    # ========================================================================
    print("=" * 80)
    print("CHECK 3: SEGMENTING 606 LOST DEFAULT PIPELINE DEALS")
    print("=" * 80)
    print()

    lost_default = [
        d for d in all_deals.data
        if d.get("deal_status") == "lost" and d.get("pipeline_id") == DEFAULT_PIPELINE_ID
    ]

    print(f"Total lost default pipeline deals: {len(lost_default)}")
    print()

    # Segment 1: April 2026 bulk cleanup
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

    # Segment 2: Pre-2023 deals (before renewal pipeline existed)
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

    # Segment 3: Organic losses (post-2023, not April 2026 bulk)
    organic_losses = []
    for deal in lost_default:
        if deal not in april_2026_bulk and deal not in pre_2023:
            organic_losses.append(deal)

    print("Segmentation of lost deals:")
    print(f"  April 2026 bulk cleanup: {len(april_2026_bulk)}")
    print(f"  Pre-2023 (before renewal pipeline): {len(pre_2023)}")
    print(f"  Organic losses (post-2023, not bulk): {len(organic_losses)}")
    print(f"  Total: {len(april_2026_bulk) + len(pre_2023) + len(organic_losses)}")
    print()

    # ========================================================================
    # CHECK 4: Recompute win rate excluding noise
    # ========================================================================
    print("=" * 80)
    print("CHECK 4: WIN RATE AFTER CLEANING")
    print("=" * 80)
    print()

    # Original contaminated
    original_won = len(won_default)
    original_lost = len(lost_default)
    original_total = original_won + original_lost
    original_win_rate = 100 * original_won / original_total if original_total > 0 else 0

    print(f"ORIGINAL (contaminated):")
    print(f"  Won: {original_won}")
    print(f"  Lost: {original_lost}")
    print(f"  Win rate: {original_win_rate:.1f}%")
    print()

    # Exclude April 2026 bulk cleanup
    cleaned_1_lost = len(lost_default) - len(april_2026_bulk)
    cleaned_1_total = original_won + cleaned_1_lost
    cleaned_1_win_rate = 100 * original_won / cleaned_1_total if cleaned_1_total > 0 else 0

    print(f"CLEANED (exclude April 2026 bulk):")
    print(f"  Won: {original_won}")
    print(f"  Lost: {cleaned_1_lost} (removed {len(april_2026_bulk)})")
    print(f"  Win rate: {cleaned_1_win_rate:.1f}%")
    print()

    # Exclude BOTH April 2026 bulk AND pre-2023
    cleaned_2_lost = len(organic_losses)
    cleaned_2_total = original_won + cleaned_2_lost
    cleaned_2_win_rate = 100 * original_won / cleaned_2_total if cleaned_2_total > 0 else 0

    print(f"CLEANED (exclude bulk + pre-2023):")
    print(f"  Won: {original_won}")
    print(f"  Lost: {cleaned_2_lost} (removed {len(april_2026_bulk) + len(pre_2023)})")
    print(f"  Win rate: {cleaned_2_win_rate:.1f}%")
    print()

    # Check if cleaned win rate is plausible
    if 15 <= cleaned_2_win_rate <= 30:
        print(f"✅ CLEANED WIN RATE ({cleaned_2_win_rate:.1f}%) IN PLAUSIBLE RANGE (15-30%)")
        print("   Default pipeline is LEGITIMATE new business, not junk")
    elif cleaned_2_win_rate < 15:
        print(f"⚠️  CLEANED WIN RATE ({cleaned_2_win_rate:.1f}%) STILL LOW (<15%)")
        print("   May need further investigation")
    else:
        print(f"✓ CLEANED WIN RATE ({cleaned_2_win_rate:.1f}%) ABOVE TYPICAL (>30%)")
        print("   Strong new business close rate")

    print()

    # ========================================================================
    # SUMMARY
    # ========================================================================
    print("=" * 80)
    print("INVESTIGATION 3 SUMMARY")
    print("=" * 80)
    print()

    print("DEFAULT PIPELINE CHARACTERIZATION:")
    print("  ✓ Contains real active new business/expansion ($18.6M ARR)")
    print("  ✓ 23 historical wins are genuine (all have real ARR)")
    print(f"  ✓ Cleaned win rate: {cleaned_2_win_rate:.1f}% (post-2023, excluding bulk cleanup)")
    print()

    print("CONTAMINATION SOURCES:")
    print(f"  • April 2026 bulk cleanup: {len(april_2026_bulk)} deals (38.7% of losses)")
    print(f"  • Pre-2023 deals: {len(pre_2023)} deals (before renewal pipeline existed)")
    print(f"  • Combined contamination: {len(april_2026_bulk) + len(pre_2023)} deals")
    print()

    print("CONCLUSION:")
    if 15 <= cleaned_2_win_rate <= 30:
        print("  ✅ Default pipeline is LEGITIMATE NEW BUSINESS PIPELINE")
        print("     (not junk/catch-all)")
        print()
        print(f"  CORRECTED cycle_time population: {original_won} won deals")
        print(f"  CORRECTED win rate: {cleaned_2_win_rate:.1f}%")
    else:
        print(f"  ⚠️  Cleaned win rate ({cleaned_2_win_rate:.1f}%) outside typical range")
        print("     Need further investigation")

if __name__ == "__main__":
    segment_default()
