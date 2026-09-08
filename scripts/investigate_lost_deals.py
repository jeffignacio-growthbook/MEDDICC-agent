#!/usr/bin/env python3
"""
INVESTIGATION 1: Sample 606 "lost" non-renewal deals to find root cause of 3.7% win rate.

Check:
1. Are these genuinely closed-lost, or misclassified?
2. Age distribution (bulk close-lost event like Ivan Gomez?)
3. is_won()/is_lost() logic correctness
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone
from collections import Counter

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_won, is_lost

def investigate_lost():
    sb = get_supabase()

    print("=" * 80)
    print("INVESTIGATION 1: 606 'LOST' NON-RENEWAL DEALS")
    print("=" * 80)
    print()

    # Fetch ALL deals
    all_deals = sb.table("deals").select(
        "deal_id,company_name,stage,deal_status,pipeline_id,"
        "create_date,close_date,lost_reason"
    ).execute()

    RENEWAL_PIPELINE_ID = "866608541"

    # Filter: non-renewal AND deal_status='lost'
    lost_non_renewal = [
        d for d in all_deals.data
        if d.get("pipeline_id") != RENEWAL_PIPELINE_ID and d.get("deal_status") == "lost"
    ]

    print(f"Total 'lost' non-renewal deals: {len(lost_non_renewal)}")
    print()

    # ========================================================================
    # CHECK 1: Are these genuinely lost? Sample 20
    # ========================================================================
    print("=" * 80)
    print("CHECK 1: SAMPLE OF 20 'LOST' DEALS")
    print("=" * 80)
    print()

    import random
    sample = random.sample(lost_non_renewal, min(20, len(lost_non_renewal)))

    print(f"{'Company':<30} {'Stage':<20} {'Status':<10} {'Lost Reason':<25} {'Close Date':<12}")
    print("-" * 120)

    for deal in sample:
        company = (deal.get("company_name") or "")[:29]
        stage = (deal.get("stage") or "")[:19]
        status = (deal.get("deal_status") or "")[:9]
        lost_reason = (deal.get("lost_reason") or "")[:24]
        close_date = deal.get("close_date", "")[:10] if deal.get("close_date") else "N/A"

        print(f"{company:<30} {stage:<20} {status:<10} {lost_reason:<25} {close_date:<12}")

    print()

    # ========================================================================
    # CHECK 2: is_won()/is_lost() logic vs deal_status
    # ========================================================================
    print("=" * 80)
    print("CHECK 2: is_won()/is_lost() LOGIC VALIDATION")
    print("=" * 80)
    print()

    # Check for mismatches
    mismatches = []

    for deal in lost_non_renewal:
        stage = deal.get("stage")
        status = deal.get("deal_status")

        stage_says_won = is_won(stage)
        stage_says_lost = is_lost(stage)
        status_says_lost = status == "lost"

        # Mismatch: stage says won/lost but status disagrees
        if stage_says_won and status_says_lost:
            mismatches.append({
                "company": deal.get("company_name"),
                "stage": stage,
                "status": status,
                "issue": "is_won(stage)=True but deal_status='lost'"
            })
        elif not stage_says_lost and status_says_lost:
            mismatches.append({
                "company": deal.get("company_name"),
                "stage": stage,
                "status": status,
                "issue": "is_lost(stage)=False but deal_status='lost'"
            })

    print(f"Mismatches between is_won()/is_lost() and deal_status: {len(mismatches)}")

    if mismatches:
        print()
        print("Sample mismatches (first 10):")
        for m in mismatches[:10]:
            print(f"  {m['company']}: stage='{m['stage']}', {m['issue']}")
    else:
        print("  ✓ No mismatches - is_won()/is_lost() logic consistent with deal_status")

    print()

    # ========================================================================
    # CHECK 3: Stage distribution for "lost" deals
    # ========================================================================
    print("=" * 80)
    print("CHECK 3: STAGE DISTRIBUTION")
    print("=" * 80)
    print()

    stage_counts = Counter(d.get("stage") for d in lost_non_renewal)

    print(f"Stage distribution for 606 'lost' non-renewal deals:")
    for stage, count in sorted(stage_counts.items(), key=lambda x: -x[1]):
        pct = 100 * count / len(lost_non_renewal)
        print(f"  '{stage}': {count} ({pct:.1f}%)")

    print()

    # Check if is_lost() recognizes these stages
    print("Checking if is_lost() recognizes these stages:")
    for stage, count in sorted(stage_counts.items(), key=lambda x: -x[1])[:10]:
        recognized = is_lost(stage)
        icon = "✓" if recognized else "✗"
        print(f"  {icon} '{stage}': is_lost()={recognized}")

    print()

    # ========================================================================
    # CHECK 4: Age distribution (bulk close-lost event?)
    # ========================================================================
    print("=" * 80)
    print("CHECK 4: AGE DISTRIBUTION (BULK EVENT CHECK)")
    print("=" * 80)
    print()

    # Parse close dates
    close_dates = []
    for deal in lost_non_renewal:
        close_date_str = deal.get("close_date")
        if close_date_str:
            try:
                close_date = datetime.fromisoformat(close_date_str.replace("Z", "+00:00"))
                close_dates.append(close_date)
            except:
                pass

    close_dates.sort()

    print(f"Lost deals with valid close_date: {len(close_dates)} of {len(lost_non_renewal)}")
    print()

    if close_dates:
        print(f"Close date range:")
        print(f"  Earliest: {close_dates[0].date()}")
        print(f"  Latest: {close_dates[-1].date()}")
        print()

        # Group by month to spot bulk events
        from collections import defaultdict
        by_month = defaultdict(int)

        for dt in close_dates:
            month_key = f"{dt.year}-{dt.month:02d}"
            by_month[month_key] += 1

        # Find months with >50 deals (potential bulk event)
        bulk_months = [(month, count) for month, count in by_month.items() if count > 50]

        if bulk_months:
            print("⚠️  BULK CLOSE-LOST EVENTS DETECTED:")
            print()
            for month, count in sorted(bulk_months, key=lambda x: -x[1]):
                pct = 100 * count / len(close_dates)
                print(f"  {month}: {count} deals ({pct:.1f}%)")
            print()
            print("  Suggests bulk operation, not organic losses")
        else:
            print("✓ No bulk close-lost events detected (no month >50 deals)")

        print()

        # Show distribution by year
        by_year = defaultdict(int)
        for dt in close_dates:
            by_year[dt.year] += 1

        print("Close dates by year:")
        for year in sorted(by_year.keys()):
            count = by_year[year]
            pct = 100 * count / len(close_dates)
            print(f"  {year}: {count} deals ({pct:.1f}%)")

    print()

    # ========================================================================
    # CHECK 5: Lost reason distribution
    # ========================================================================
    print("=" * 80)
    print("CHECK 5: LOST REASON DISTRIBUTION")
    print("=" * 80)
    print()

    lost_reason_counts = Counter(d.get("lost_reason") or "(blank)" for d in lost_non_renewal)

    print("Lost reason distribution:")
    for reason, count in sorted(lost_reason_counts.items(), key=lambda x: -x[1])[:10]:
        pct = 100 * count / len(lost_non_renewal)
        print(f"  '{reason}': {count} ({pct:.1f}%)")

    print()

    # ========================================================================
    # SUMMARY
    # ========================================================================
    print("=" * 80)
    print("INVESTIGATION 1 SUMMARY")
    print("=" * 80)
    print()

    print(f"Total 'lost' non-renewal deals: {len(lost_non_renewal)}")
    print(f"  With close_date: {len(close_dates)}")
    print(f"  Stage/status mismatches: {len(mismatches)}")
    print()

    if bulk_months:
        print("⚠️  BULK EVENTS FOUND - this is NOT organic close-lost behavior")
        print("   Similar to Ivan Gomez bulk event from earlier in session")
    elif mismatches:
        print("⚠️  STAGE/STATUS MISMATCHES - is_lost() logic may be wrong")
    else:
        print("✓ Deals appear genuinely lost (but 3.7% win rate still needs explanation)")

if __name__ == "__main__":
    investigate_lost()
