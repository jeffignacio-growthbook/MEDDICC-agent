#!/usr/bin/env python3
"""
MANDATORY CROSS-METRIC PLAUSIBILITY CHECK

Before finalizing ANY population metric (count/filter of deals), check it
against already-verified, related metrics to catch obvious mismatches.

Pattern from 2026-09-06 session:
- Presented "22 non-renewal won deals (19% of wins)" as final
- Did NOT check against already-verified "306 non-renewal active deals (69%)"
- 19% vs 69% is a 3.6x divergence - massive red flag, caught too late

This check is MANDATORY before writing verified_value to canonical_questions.yaml
or metrics.yaml. Not optional. Not "only if Jeff remembers to ask."

Template-portable: This pattern applies to every client, not just GrowthBook.
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime
import json

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_won

# Plausibility check log
LOG_FILE = Path(__file__).parent.parent / "plausibility_checks.log"

def log_check(check_name, status, details):
    """Log every plausibility check for audit trail."""
    timestamp = datetime.now().isoformat()
    log_entry = {
        "timestamp": timestamp,
        "check": check_name,
        "status": status,  # "PASS", "FLAG", "ERROR"
        "details": details
    }

    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    return log_entry

def check_renewal_vs_non_renewal_consistency():
    """
    Check: q016's 22 non-renewal won deals (19% of wins) vs already-verified
    306 non-renewal active deals (69% of active).

    Expect: These should be within 2x of each other unless documented business
    shift explains divergence.
    """
    sb = get_supabase()

    print("=" * 80)
    print("PLAUSIBILITY CHECK: RENEWAL/NON-RENEWAL POPULATION CONSISTENCY")
    print("=" * 80)
    print()

    # Fetch all deals
    all_deals = sb.table("deals").select(
        "deal_id,stage,pipeline_id,deal_status"
    ).execute()

    RENEWAL_PIPELINE_ID = "866608541"

    # ========================================================================
    # METRIC 1: Active pipeline split (already verified earlier this session)
    # ========================================================================
    active_deals = [d for d in all_deals.data if d.get("deal_status") == "active"]
    active_renewal = [d for d in active_deals if d.get("pipeline_id") == RENEWAL_PIPELINE_ID]
    active_non_renewal = [d for d in active_deals if d.get("pipeline_id") != RENEWAL_PIPELINE_ID]

    pct_active_non_renewal = 100 * len(active_non_renewal) / len(active_deals) if active_deals else 0

    print(f"METRIC 1 (Already Verified): Active Pipeline Split")
    print(f"  Total active: {len(active_deals)}")
    print(f"  Non-renewal: {len(active_non_renewal)} ({pct_active_non_renewal:.1f}%)")
    print(f"  Renewal: {len(active_renewal)} ({100-pct_active_non_renewal:.1f}%)")
    print()

    # ========================================================================
    # METRIC 2: Historical won deals split (q016 population)
    # ========================================================================
    won_deals = [d for d in all_deals.data if is_won(d.get("stage"))]
    won_renewal = [d for d in won_deals if d.get("pipeline_id") == RENEWAL_PIPELINE_ID]
    won_non_renewal = [d for d in won_deals if d.get("pipeline_id") != RENEWAL_PIPELINE_ID]

    pct_won_non_renewal = 100 * len(won_non_renewal) / len(won_deals) if won_deals else 0

    print(f"METRIC 2 (q016 Population): Historical Won Deals Split")
    print(f"  Total won: {len(won_deals)}")
    print(f"  Non-renewal: {len(won_non_renewal)} ({pct_won_non_renewal:.1f}%)")
    print(f"  Renewal: {len(won_renewal)} ({100-pct_won_non_renewal:.1f}%)")
    print()

    # ========================================================================
    # PLAUSIBILITY CHECK
    # ========================================================================
    print("=" * 80)
    print("CROSS-METRIC COMPARISON")
    print("=" * 80)
    print()

    ratio = pct_active_non_renewal / pct_won_non_renewal if pct_won_non_renewal > 0 else float('inf')
    divergence = abs(pct_active_non_renewal - pct_won_non_renewal)

    print(f"Active pipeline:    {pct_active_non_renewal:.1f}% non-renewal")
    print(f"Historical wins:    {pct_won_non_renewal:.1f}% non-renewal")
    print(f"Divergence:         {divergence:.1f} percentage points")
    print(f"Ratio:              {ratio:.1f}x")
    print()

    # Define thresholds
    FLAG_DIVERGENCE_PP = 20  # Flag if >20pp difference
    FLAG_RATIO = 2.0  # Flag if >2x ratio

    flags = []

    if divergence > FLAG_DIVERGENCE_PP:
        flags.append(f"Divergence >{FLAG_DIVERGENCE_PP}pp ({divergence:.1f}pp)")

    if ratio > FLAG_RATIO or ratio < (1/FLAG_RATIO):
        flags.append(f"Ratio outside 0.5-2.0x range ({ratio:.1f}x)")

    # ========================================================================
    # RESULT
    # ========================================================================
    print("=" * 80)
    print("PLAUSIBILITY CHECK RESULT")
    print("=" * 80)
    print()

    if not flags:
        status = "PASS"
        print("✅ PASS: Metrics are plausibly consistent")
        print()
        details = {
            "active_non_renewal_pct": pct_active_non_renewal,
            "won_non_renewal_pct": pct_won_non_renewal,
            "divergence_pp": divergence,
            "ratio": ratio
        }
    else:
        status = "FLAG"
        print("🚩 FLAG: Metrics show significant divergence")
        print()
        print("Issues detected:")
        for flag in flags:
            print(f"  • {flag}")
        print()
        print("REQUIRED ACTION:")
        print("  Before finalizing q016's 22-deal population, explain why these diverge:")
        print()
        print("  Possible explanations:")
        print("    1. Business mix shift (documented pivot from renewal to new business)")
        print("    2. Renewal deals close faster (don't accumulate in active pipeline)")
        print("    3. Pipeline_id misclassification (some renewals tagged as non-renewal)")
        print("    4. Wrong filter in one of the populations")
        print()
        print("  DO NOT present 52 days as final until this is resolved.")

        details = {
            "active_non_renewal_pct": pct_active_non_renewal,
            "won_non_renewal_pct": pct_won_non_renewal,
            "divergence_pp": divergence,
            "ratio": ratio,
            "flags": flags
        }

    # Log the check
    log_check(
        "renewal_vs_non_renewal_consistency",
        status,
        details
    )

    return status == "PASS"

def check_sample_size_vs_total_population():
    """
    Check: Does the sample size for a metric make sense relative to total
    population? E.g., if claiming "22 non-renewal wins from 306 non-renewal
    active deals", is 22/306 = 7% win rate plausible?
    """
    sb = get_supabase()

    print()
    print("=" * 80)
    print("PLAUSIBILITY CHECK: SAMPLE SIZE VS TOTAL POPULATION")
    print("=" * 80)
    print()

    # Fetch all deals
    all_deals = sb.table("deals").select(
        "deal_id,stage,pipeline_id,deal_status"
    ).execute()

    RENEWAL_PIPELINE_ID = "866608541"

    # Total non-renewal deals (all statuses)
    all_non_renewal = [d for d in all_deals.data if d.get("pipeline_id") != RENEWAL_PIPELINE_ID]

    # Won non-renewal deals
    won_non_renewal = [
        d for d in all_deals.data
        if is_won(d.get("stage")) and d.get("pipeline_id") != RENEWAL_PIPELINE_ID
    ]

    # Lost non-renewal deals
    lost_non_renewal = [
        d for d in all_deals.data
        if d.get("deal_status") == "lost" and d.get("pipeline_id") != RENEWAL_PIPELINE_ID
    ]

    # Closed (won + lost)
    closed_non_renewal = len(won_non_renewal) + len(lost_non_renewal)

    print(f"Non-renewal deal population:")
    print(f"  Total (all statuses): {len(all_non_renewal)}")
    print(f"  Won: {len(won_non_renewal)}")
    print(f"  Lost: {len(lost_non_renewal)}")
    print(f"  Closed (won + lost): {closed_non_renewal}")
    print()

    # Win rate
    if closed_non_renewal > 0:
        win_rate = 100 * len(won_non_renewal) / closed_non_renewal
        print(f"Non-renewal win rate: {win_rate:.1f}% ({len(won_non_renewal)}/{closed_non_renewal})")
    else:
        win_rate = 0
        print("No closed non-renewal deals")

    print()

    # Check plausibility
    # Win rates of 5-50% are typical for B2B SaaS
    # Outside this range deserves explanation

    flags = []

    if win_rate < 5:
        flags.append(f"Win rate very low ({win_rate:.1f}% < 5%)")
    elif win_rate > 50:
        flags.append(f"Win rate very high ({win_rate:.1f}% > 50%)")

    if len(won_non_renewal) < 20:
        flags.append(f"Sample size very small ({len(won_non_renewal)} deals < 20 threshold)")

    print("=" * 80)
    print("PLAUSIBILITY CHECK RESULT")
    print("=" * 80)
    print()

    if not flags:
        status = "PASS"
        print("✅ PASS: Sample size and win rate are plausible")
        details = {
            "total_non_renewal": len(all_non_renewal),
            "won_non_renewal": len(won_non_renewal),
            "closed_non_renewal": closed_non_renewal,
            "win_rate": win_rate
        }
    else:
        status = "FLAG"
        print("🚩 FLAG: Sample size or win rate outside typical range")
        print()
        print("Issues detected:")
        for flag in flags:
            print(f"  • {flag}")
        print()
        print("REQUIRED ACTION:")
        print("  Validate with Jeff before finalizing:")
        print(f"    - Is {len(won_non_renewal)} non-renewal wins correct for GrowthBook's history?")
        print(f"    - Is {win_rate:.1f}% win rate expected for their business?")
        print(f"    - Is sample size adequate for reliable metric?")

        details = {
            "total_non_renewal": len(all_non_renewal),
            "won_non_renewal": len(won_non_renewal),
            "closed_non_renewal": closed_non_renewal,
            "win_rate": win_rate,
            "flags": flags
        }

    log_check(
        "sample_size_vs_total_population",
        status,
        details
    )

    return status == "PASS"

def run_all_checks():
    """Run all plausibility checks. Return True only if ALL pass."""
    print("=" * 80)
    print("CROSS-METRIC PLAUSIBILITY CHECKS")
    print("MANDATORY GATE BEFORE FINALIZING POPULATION METRICS")
    print("=" * 80)
    print()
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Log file: {LOG_FILE}")
    print()

    checks = [
        ("Renewal vs Non-Renewal Consistency", check_renewal_vs_non_renewal_consistency),
        ("Sample Size vs Total Population", check_sample_size_vs_total_population)
    ]

    results = []

    for check_name, check_fn in checks:
        try:
            passed = check_fn()
            results.append((check_name, "PASS" if passed else "FLAG"))
        except Exception as e:
            print(f"❌ ERROR in {check_name}: {e}")
            results.append((check_name, "ERROR"))
            log_check(check_name, "ERROR", {"error": str(e)})

    # Final summary
    print()
    print("=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)
    print()

    for check_name, status in results:
        icon = "✅" if status == "PASS" else "🚩" if status == "FLAG" else "❌"
        print(f"  {icon} {check_name}: {status}")

    print()

    all_passed = all(status == "PASS" for _, status in results)

    if all_passed:
        print("✅ ALL CHECKS PASSED")
        print("   Safe to finalize population metric")
    else:
        print("🚩 ONE OR MORE CHECKS FLAGGED")
        print("   DO NOT finalize until flags are resolved")
        print()
        print("   This is a MANDATORY gate - not optional")

    print()
    print(f"Audit trail: {LOG_FILE}")

    return all_passed

if __name__ == "__main__":
    passed = run_all_checks()
    sys.exit(0 if passed else 1)
