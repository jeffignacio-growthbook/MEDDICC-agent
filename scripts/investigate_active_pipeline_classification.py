#!/usr/bin/env python3
"""
INVESTIGATION: Why is active pipeline only 50% incremental when all 23 historical wins are 100% incremental?

Clean cohort (2023+, organic, won): 100.0% incremental (23/23)
Active pipeline: 50.4% incremental (58/115)
Divergence: 49.6pp - mix shift explanation does NOT hold

Possible causes:
1. Active default pipeline contains misclassified renewals (should be in renewal pipeline)
2. Data quality: 57 active deals missing ARR values (uncategorized)
3. Recent business shift: More renewals in default pipeline (unusual pattern)
"""
import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase

def investigate_active_classification():
    sb = get_supabase()

    print("=" * 80)
    print("INVESTIGATION: ACTIVE PIPELINE CLASSIFICATION")
    print("=" * 80)
    print()

    # Fetch active default pipeline deals
    all_deals = sb.table("deals").select(
        "deal_id,company_name,pipeline_id,deal_status,stage,"
        "new_arr,expansion_arr,renewal_revenue"
    ).execute()

    DEFAULT_PIPELINE_ID = "default"

    active_default = [
        d for d in all_deals.data
        if d.get("deal_status") == "active" and d.get("pipeline_id") == DEFAULT_PIPELINE_ID
    ]

    print(f"Total active default pipeline deals: {len(active_default)}")
    print()

    # Classify by ARR type (same logic as final_validation_checks.py)
    incremental = []
    renewal_only = []
    neither = []

    for deal in active_default:
        new_arr = deal.get("new_arr") or 0
        expansion_arr = deal.get("expansion_arr") or 0
        renewal_revenue = deal.get("renewal_revenue") or 0

        has_incremental = new_arr > 0 or expansion_arr > 0
        has_renewal = renewal_revenue > 0

        if has_incremental:
            incremental.append(deal)
        elif has_renewal:
            renewal_only.append(deal)
        else:
            neither.append(deal)

    print("=" * 80)
    print("CLASSIFICATION RESULTS")
    print("=" * 80)
    print()

    print(f"ACTIVE DEFAULT PIPELINE (n={len(active_default)}):")
    print(f"  Incremental (new_arr OR expansion_arr > 0): {len(incremental)} ({100*len(incremental)/len(active_default):.1f}%)")
    print(f"  Renewal only (renewal_revenue > 0, no incremental): {len(renewal_only)} ({100*len(renewal_only)/len(active_default):.1f}%)")
    print(f"  Neither (all ARR fields blank/zero): {len(neither)} ({100*len(neither)/len(active_default):.1f}%)")
    print()

    # ========================================================================
    # INVESTIGATE: 57 deals without incremental ARR
    # ========================================================================
    print("=" * 80)
    print("INVESTIGATION: 57 DEALS WITHOUT INCREMENTAL ARR")
    print("=" * 80)
    print()

    non_incremental = renewal_only + neither

    print(f"Total: {len(non_incremental)} deals")
    print(f"  Renewal-only: {len(renewal_only)} deals")
    print(f"  Uncategorized (no ARR): {len(neither)} deals")
    print()

    # Check renewal-only deals
    if renewal_only:
        print("RENEWAL-ONLY DEALS (in default pipeline - unusual):")
        print(f"{'Company':<40} {'Renewal Revenue':<15} {'Stage':<25}")
        print("-" * 85)
        for deal in renewal_only[:20]:  # Show first 20
            company = (deal.get("company_name") or "")[:39]
            renewal_rev = deal.get("renewal_revenue") or 0
            stage = (deal.get("stage") or "")[:24]
            print(f"{company:<40} ${renewal_rev:>13,.0f} {stage:<25}")

        print()
        print(f"⚠️  {len(renewal_only)} renewal-only deals in DEFAULT pipeline")
        print("   These should typically be in RENEWAL pipeline (pipeline_id='866608541')")
        print("   Suggests: Misclassification or data quality issue")
        print()

    # Check uncategorized deals
    if neither:
        print("UNCATEGORIZED DEALS (no ARR data):")
        print(f"{'Company':<40} {'Stage':<25} {'Status':<10}")
        print("-" * 80)
        for deal in neither[:20]:  # Show first 20
            company = (deal.get("company_name") or "")[:39]
            stage = (deal.get("stage") or "")[:24]
            status = deal.get("deal_status") or ""
            print(f"{company:<40} {stage:<25} {status:<10}")

        print()
        print(f"⚠️  {len(neither)} deals with NO ARR data")
        print("   Data quality gap - deals should have at least one ARR field populated")
        print()

    # ========================================================================
    # HYPOTHESIS TESTING
    # ========================================================================
    print("=" * 80)
    print("HYPOTHESIS TESTING")
    print("=" * 80)
    print()

    print("HYPOTHESIS 1: Misclassified renewals")
    if len(renewal_only) > 10:
        print(f"  ✅ SUPPORTED - {len(renewal_only)} renewal-only deals in default pipeline")
        print("     These are likely misclassified renewals (should be in renewal pipeline)")
        hypothesis_1 = True
    else:
        print(f"  ❌ NOT SUPPORTED - Only {len(renewal_only)} renewal-only deals")
        hypothesis_1 = False
    print()

    print("HYPOTHESIS 2: Data quality issues (missing ARR)")
    if len(neither) > 30:
        print(f"  ✅ SUPPORTED - {len(neither)} deals with no ARR data")
        print("     Significant data quality gap - need to populate ARR fields")
        hypothesis_2 = True
    else:
        print(f"  ❌ NOT SUPPORTED - Only {len(neither)} deals with no ARR")
        hypothesis_2 = False
    print()

    print("HYPOTHESIS 3: Recent business shift")
    print("  ⏳ PENDING - Would need to check when these deals were created")
    print("     (Are renewal-only deals all recent, or scattered throughout history?)")
    print()

    # ========================================================================
    # COMPARISON TO HISTORICAL
    # ========================================================================
    print("=" * 80)
    print("COMPARISON: ACTIVE vs HISTORICAL WON")
    print("=" * 80)
    print()

    print(f"ACTIVE PIPELINE (default, today):")
    print(f"  Total: {len(active_default)}")
    print(f"  Incremental: {len(incremental)} ({100*len(incremental)/len(active_default):.1f}%)")
    print(f"  Renewal-only: {len(renewal_only)} ({100*len(renewal_only)/len(active_default):.1f}%)")
    print(f"  Uncategorized: {len(neither)} ({100*len(neither)/len(active_default):.1f}%)")
    print()

    print(f"HISTORICAL WON (default, 2023+, organic):")
    print(f"  Incremental: 100.0% (23/23)")
    print(f"  Renewal-only: 0.0% (0/23)")
    print()

    print("DIVERGENCE ANALYSIS:")
    print(f"  Active incremental: {100*len(incremental)/len(active_default):.1f}%")
    print(f"  Historical incremental: 100.0%")
    print(f"  Gap: {100 - 100*len(incremental)/len(active_default):.1f} percentage points")
    print()

    # ========================================================================
    # CONCLUSION
    # ========================================================================
    print("=" * 80)
    print("CONCLUSION")
    print("=" * 80)
    print()

    if hypothesis_1 and hypothesis_2:
        print("ROOT CAUSE: BOTH misclassified renewals AND data quality gaps")
        print()
        print("RECOMMENDED ACTION:")
        print(f"  1. Move {len(renewal_only)} renewal-only deals to renewal pipeline (pipeline_id='866608541')")
        print(f"  2. Populate ARR fields for {len(neither)} uncategorized deals")
        print("  3. Re-run classification after fixes")
        print()
        print("IMPACT ON Q016:")
        print("  BLOCK sign-off until classification is corrected")
        print("  100% historical vs 50% active divergence indicates data quality issue, not business shift")
    elif hypothesis_1:
        print("ROOT CAUSE: Misclassified renewals in default pipeline")
        print()
        print("RECOMMENDED ACTION:")
        print(f"  Move {len(renewal_only)} renewal-only deals to renewal pipeline")
        print()
        print("PROJECTED RESULT AFTER FIX:")
        corrected_incremental_pct = 100 * len(incremental) / (len(incremental) + len(neither))
        print(f"  Active incremental: {corrected_incremental_pct:.1f}% (after moving renewals)")
        print(f"  Historical incremental: 100.0%")
        print(f"  Remaining gap: {100 - corrected_incremental_pct:.1f}pp (from uncategorized deals)")
    elif hypothesis_2:
        print("ROOT CAUSE: Data quality gaps (missing ARR fields)")
        print()
        print("RECOMMENDED ACTION:")
        print(f"  Populate ARR fields for {len(neither)} uncategorized deals")
    else:
        print("ROOT CAUSE: UNCLEAR - further investigation needed")

    print()

    return hypothesis_1 or hypothesis_2

if __name__ == "__main__":
    issues_found = investigate_active_classification()
    sys.exit(1 if issues_found else 0)
