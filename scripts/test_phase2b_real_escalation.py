#!/usr/bin/env python3
"""
Test 2 (IMPROVED): Real Escalation with Meaningful Diagnostic

Tests non-convergence with a REAL, ACHIEVABLE target that requires a
hygiene rule NOT in the registry. Verifies the diagnostic meaningfully
distinguishes between:
- Missing rule (can't converge with available rules)
- Impossible target (ground truth is wrong)
- Data quality issue (systematic contamination)
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.backtest_engine_generalized import (
    load_hygiene_rules,
    execute_sum_dollars_query
)
from api.field_semantics import is_open


def calculate_real_ground_truth(sb):
    """
    Calculate ground truth for pipeline_value excluding stale deals.

    Real hygiene issue: Deals open > 180 days contaminate pipeline.
    This is a REAL, ACHIEVABLE target that requires a rule NOT in registry.
    """
    print("Calculating ground truth (excluding stale deals >180 days)...")
    print()

    RENEWAL_PIPELINE_ID = "866608541"

    all_deals = sb.table("deals").select(
        "deal_id,company_name,stage,deal_value,pipeline_id,create_date"
    ).execute()

    # Get active, non-renewal deals
    active = [d for d in all_deals.data if is_open(d.get("stage"))]
    non_renewal_active = [d for d in active if d.get("pipeline_id") != RENEWAL_PIPELINE_ID]

    # Filter out stale deals (>180 days old)
    fresh_deals = []
    stale_deals = []

    for deal in non_renewal_active:
        create_date_str = deal.get("create_date")
        if create_date_str:
            try:
                if isinstance(create_date_str, str):
                    create_date = datetime.fromisoformat(create_date_str.replace("Z", "+00:00"))
                else:
                    create_date = create_date_str

                age_days = (datetime.now(create_date.tzinfo) - create_date).days

                if age_days > 180:
                    stale_deals.append(deal)
                else:
                    fresh_deals.append(deal)
            except:
                # If can't parse date, include in fresh (benefit of doubt)
                fresh_deals.append(deal)
        else:
            # No create date, include in fresh
            fresh_deals.append(deal)

    naive_value = sum(d.get("deal_value", 0) or 0 for d in non_renewal_active)
    fresh_value = sum(d.get("deal_value", 0) or 0 for d in fresh_deals)
    stale_value = sum(d.get("deal_value", 0) or 0 for d in stale_deals)

    print(f"Total active (non-renewal) deals: {len(non_renewal_active)}")
    print(f"  Naive pipeline value: ${naive_value:,.2f}")
    print()
    print(f"Fresh deals (<180 days): {len(fresh_deals)}")
    print(f"  Fresh pipeline value: ${fresh_value:,.2f}")
    print()
    print(f"Stale deals (>180 days): {len(stale_deals)}")
    print(f"  Stale pipeline value: ${stale_value:,.2f}")
    print(f"  Stale percentage: {(stale_value / naive_value * 100) if naive_value else 0:.1f}%")
    print()

    if stale_deals:
        print("Stale deals found:")
        for deal in sorted(stale_deals, key=lambda d: d.get("deal_value", 0), reverse=True):
            create_str = deal.get("create_date", "")[:10] if deal.get("create_date") else "unknown"
            print(f"  - {deal.get('company_name')}: ${deal.get('deal_value', 0):,.2f} (created {create_str})")

    return {
        "naive_value": naive_value,
        "fresh_value": fresh_value,
        "stale_value": stale_value,
        "n_fresh": len(fresh_deals),
        "n_stale": len(stale_deals),
        "contamination_pct": (stale_value / naive_value * 100) if naive_value else 0
    }


def enhanced_diagnostic(
    iterations: list,
    ground_truth_value: float,
    tolerance: float,
    available_rules: list
) -> dict:
    """
    Generate enhanced diagnostic that distinguishes WHY convergence failed.

    Returns:
        Diagnostic with classification of failure type
    """
    if not iterations:
        return {
            "type": "no_iterations",
            "message": "No iterations completed",
            "severity": "error"
        }

    naive_result = iterations[0]
    final_result = iterations[-1]

    naive_value = naive_result['actual_value']
    final_value = final_result['actual_value']
    target_value = ground_truth_value

    # Calculate deltas
    naive_delta = abs(naive_value - target_value)
    final_delta = abs(final_value - target_value)
    improvement = naive_delta - final_delta
    improvement_pct = (improvement / naive_delta * 100) if naive_delta > 0 else 0

    # Classify failure type
    diagnostic = {
        "naive_value": naive_value,
        "final_value": final_value,
        "target_value": target_value,
        "naive_delta": naive_delta,
        "final_delta": final_delta,
        "improvement": improvement,
        "improvement_pct": improvement_pct,
        "rules_tried": [r for r in final_result.get('applied_rules', [])],
        "iterations_count": len(iterations)
    }

    # Calculate remaining gap as percentage of final value
    remaining_gap_pct = (final_delta / final_value * 100) if final_value > 0 else 0

    # Classification logic
    if improvement_pct > 90 and remaining_gap_pct < 5:
        # Massive improvement (>90%) and small remaining gap (<5% of result)
        # Strongly suggests missing rule - we're very close, just need one more filter
        diagnostic["type"] = "missing_rule"
        diagnostic["severity"] = "needs_new_rule"
        diagnostic["remaining_gap_pct"] = remaining_gap_pct
        diagnostic["message"] = (
            f"Massive improvement ({improvement_pct:.1f}%) with small remaining gap "
            f"({remaining_gap_pct:.1f}% of result).\n\n"
            f"Pattern strongly suggests a filtering rule is needed that's NOT in the current registry.\n\n"
            f"Existing rules improved the result from {naive_value:,.0f} to {final_value:,.0f}, "
            f"bringing us within {final_delta:,.0f} of target {target_value:,.0f}.\n\n"
            f"The small remaining gap ({remaining_gap_pct:.1f}%) indicates we're on the right track "
            f"and just need one additional hygiene rule.\n\n"
            f"Recommended action:\n"
            f"  1. Investigate what differentiates the target from current result\n"
            f"  2. Define new hygiene rule to close this gap\n"
            f"  3. Add to config/field_semantics.yaml\n"
            f"  4. Re-run backtest to verify convergence"
        )

    elif improvement_pct > 50 and remaining_gap_pct > 50:
        # Moderate improvement but HUGE remaining gap
        # Suggests ground truth is wrong or completely different approach needed
        diagnostic["type"] = "impossible_target"
        diagnostic["severity"] = "ground_truth_suspect"
        diagnostic["remaining_gap_pct"] = remaining_gap_pct
        diagnostic["message"] = (
            f"Moderate improvement ({improvement_pct:.1f}%) but massive remaining gap "
            f"({remaining_gap_pct:.1f}% of result, ${final_delta:,.0f}).\n\n"
            f"Applied rules: {', '.join(diagnostic['rules_tried']) if diagnostic['rules_tried'] else 'none'}\n\n"
            f"This pattern suggests the target ({target_value:,.0f}) is unreachable:\n"
            f"  - Remaining gap is {remaining_gap_pct:.1f}% of current result\n"
            f"  - Would require filtering out majority of remaining data\n"
            f"  - Target may be miscalculated or based on wrong population\n\n"
            f"Recommended action:\n"
            f"  1. Verify ground truth calculation method\n"
            f"  2. Check if target value is achievable with ANY filtering\n"
            f"  3. Review population filter specification\n"
            f"  4. Consider whether target is based on different time period or dataset"
        )

    elif improvement_pct < 10:
        # Little to no improvement
        # Suggests wrong ground truth or completely wrong approach
        diagnostic["type"] = "impossible_target"
        diagnostic["severity"] = "ground_truth_suspect"
        diagnostic["message"] = (
            f"Minimal improvement ({improvement_pct:.1f}%) after trying all available rules.\n\n"
            f"Applied rules: {', '.join(diagnostic['rules_tried']) if diagnostic['rules_tried'] else 'none'}\n\n"
            f"This pattern suggests:\n"
            f"  - Ground truth may be incorrect (target {target_value:,.0f} unreachable)\n"
            f"  - Completely different filtering approach needed\n"
            f"  - Population filter mismatch\n\n"
            f"Recommended action:\n"
            f"  1. Verify ground truth calculation method\n"
            f"  2. Check if target value is achievable with ANY filtering\n"
            f"  3. Review population filter specification"
        )

    else:
        # Moderate improvement (10-50%)
        # Suggests partial progress, may need multiple new rules or hybrid approach
        diagnostic["type"] = "partial_progress"
        diagnostic["severity"] = "multiple_rules_needed"
        diagnostic["message"] = (
            f"Partial improvement ({improvement_pct:.1f}%) but insufficient.\n\n"
            f"Remaining gap: {final_delta:,.0f} (tolerance: {tolerance:,.0f})\n\n"
            f"This pattern suggests:\n"
            f"  - Multiple missing hygiene rules needed\n"
            f"  - Complex data quality issue\n"
            f"  - Combination of existing + new rules required\n\n"
            f"Recommended action:\n"
            f"  1. Analyze deals in final result vs target\n"
            f"  2. Identify multiple contamination sources\n"
            f"  3. Define compound filtering strategy"
        )

    return diagnostic


def test_real_escalation_with_enhanced_diagnostic(sb):
    """
    Test 2 (IMPROVED): Real escalation case with meaningful diagnostic.

    Uses stale pipeline (deals >180 days old) as REAL hygiene gap.
    Tests whether diagnostic meaningfully distinguishes failure types.
    """
    print("\n" + "="*80)
    print("TEST 2 (IMPROVED): Real Escalation with Enhanced Diagnostic")
    print("="*80)
    print()
    print("Goal: Test non-convergence with REAL, ACHIEVABLE target")
    print("Real hygiene gap: Stale pipeline (deals >180 days old)")
    print("Missing rule: exclude_stale_pipeline (NOT in registry)")
    print()

    # Calculate real ground truth
    gt = calculate_real_ground_truth(sb)

    print()
    print("─"*80)
    print("Running backtest with current registry rules...")
    print("─"*80)
    print()

    hygiene_rules = load_hygiene_rules()

    # Metric spec
    metric_spec = {
        "metric_type": "sum_dollars",
        "population_filter": {
            "deal_status": "active",
        }
    }

    # Run iterations manually to capture full trail
    iterations = []

    # Iteration 0: Naive
    print("\nIteration 0: Naive (no rules)")
    query_spec = {
        "applied_rules": [],
        "exclude_renewals": False,
        "description": "naive (no hygiene rules)"
    }
    result = execute_sum_dollars_query(sb, query_spec, metric_spec["population_filter"])

    naive_value = result.get("total_dollars", 0)
    target_value = gt["fresh_value"]
    tolerance = 50_000  # $50K tolerance

    delta = abs(naive_value - target_value)
    converged = delta <= tolerance

    iterations.append({
        "iteration": 0,
        "applied_rules": [],
        "actual_value": naive_value,
        "expected_value": target_value,
        "delta": delta,
        "converged": converged,
        "result": result
    })

    print(f"  Result: ${naive_value:,.2f}")
    print(f"  Target: ${target_value:,.2f}")
    print(f"  Delta: ${delta:,.2f}")
    print(f"  Status: {'✓ Converged' if converged else '✗ Mismatch'}")

    if not converged:
        # Iteration 1: Apply exclude_renewals (only rule we have)
        print("\nIteration 1: Apply exclude_renewals")
        query_spec = {
            "applied_rules": ["exclude_renewals"],
            "exclude_renewals": True,
            "description": "exclude_renewals"
        }
        result = execute_sum_dollars_query(sb, query_spec, metric_spec["population_filter"])

        final_value = result.get("total_dollars", 0)
        delta = abs(final_value - target_value)
        converged = delta <= tolerance

        iterations.append({
            "iteration": 1,
            "applied_rules": ["exclude_renewals"],
            "actual_value": final_value,
            "expected_value": target_value,
            "delta": delta,
            "converged": converged,
            "result": result
        })

        print(f"  Result: ${final_value:,.2f}")
        print(f"  Target: ${target_value:,.2f}")
        print(f"  Delta: ${delta:,.2f}")
        print(f"  Status: {'✓ Converged' if converged else '✗ Mismatch'}")

    # Generate enhanced diagnostic
    print()
    print("─"*80)
    print("ENHANCED DIAGNOSTIC")
    print("─"*80)
    print()

    diagnostic = enhanced_diagnostic(iterations, target_value, tolerance, hygiene_rules)

    print(f"Failure type: {diagnostic['type'].upper()}")
    print(f"Severity: {diagnostic['severity']}")
    print()
    print(diagnostic['message'])

    print()
    print("─"*80)
    print("DIAGNOSTIC QUALITY CHECK")
    print("─"*80)
    print()

    if diagnostic['type'] == 'missing_rule':
        print("✓ DIAGNOSTIC PASSED: Correctly identified 'missing_rule' pattern")
        print()
        print("Diagnostic signals:")
        print(f"  - Significant improvement ({diagnostic['improvement_pct']:.1f}%)")
        print(f"  - Existing rules helped but gap remains")
        print(f"  - Recommends adding new rule to registry")
        print()
        print("This is meaningfully different from 'impossible_target' diagnostic.")
        return True
    else:
        print(f"✗ DIAGNOSTIC ISSUE: Expected 'missing_rule', got '{diagnostic['type']}'")
        print()
        print("This may indicate:")
        print("  - Diagnostic logic needs refinement")
        print("  - Real contamination pattern doesn't match expectations")
        print("  - Classification thresholds need adjustment")
        return False


def main():
    """Run improved Test 2 with real escalation case."""
    supabase_url = os.environ.get('SUPABASE_URL')
    supabase_key = os.environ.get('SUPABASE_SERVICE_KEY')

    if not supabase_url or not supabase_key:
        print("✗ ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        sys.exit(1)

    sb = create_client(supabase_url, supabase_key)

    passed = test_real_escalation_with_enhanced_diagnostic(sb)

    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
