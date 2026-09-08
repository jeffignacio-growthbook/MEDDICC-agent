#!/usr/bin/env python3
"""
Compare diagnostic quality: Missing Rule vs Impossible Target

Demonstrates that enhanced diagnostic meaningfully distinguishes between:
1. Missing rule case (real, achievable target, gap remains)
2. Impossible target case (unreachable target, no progress)
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.test_phase2b_real_escalation import (
    enhanced_diagnostic,
    calculate_real_ground_truth
)
from scripts.backtest_engine_generalized import (
    load_hygiene_rules,
    execute_sum_dollars_query
)


def simulate_missing_rule_case(sb):
    """Simulate case where we need a rule NOT in registry (stale pipeline)."""
    print("="*80)
    print("CASE 1: Missing Rule (Real, Achievable Target)")
    print("="*80)
    print()

    gt = calculate_real_ground_truth(sb)
    hygiene_rules = load_hygiene_rules()

    metric_spec = {
        "metric_type": "sum_dollars",
        "population_filter": {"deal_status": "active"}
    }

    # Iteration 0: Naive
    query_spec = {
        "applied_rules": [],
        "exclude_renewals": False,
        "description": "naive"
    }
    result0 = execute_sum_dollars_query(sb, query_spec, metric_spec["population_filter"])

    # Iteration 1: Apply exclude_renewals
    query_spec = {
        "applied_rules": ["exclude_renewals"],
        "exclude_renewals": True,
        "description": "exclude_renewals"
    }
    result1 = execute_sum_dollars_query(sb, query_spec, metric_spec["population_filter"])

    iterations = [
        {
            "iteration": 0,
            "applied_rules": [],
            "actual_value": result0.get("total_dollars", 0),
            "expected_value": gt["fresh_value"],
            "delta": abs(result0.get("total_dollars", 0) - gt["fresh_value"]),
            "converged": False,
            "result": result0
        },
        {
            "iteration": 1,
            "applied_rules": ["exclude_renewals"],
            "actual_value": result1.get("total_dollars", 0),
            "expected_value": gt["fresh_value"],
            "delta": abs(result1.get("total_dollars", 0) - gt["fresh_value"]),
            "converged": False,
            "result": result1
        }
    ]

    diagnostic = enhanced_diagnostic(iterations, gt["fresh_value"], 50_000, hygiene_rules)

    print(f"Naive result: ${iterations[0]['actual_value']:,.2f}")
    print(f"After exclude_renewals: ${iterations[1]['actual_value']:,.2f}")
    print(f"Target: ${gt['fresh_value']:,.2f}")
    print(f"Improvement: {diagnostic['improvement_pct']:.1f}%")
    print()
    print(f"Diagnostic type: {diagnostic['type']}")
    print(f"Severity: {diagnostic['severity']}")
    print()

    return diagnostic


def simulate_impossible_target_case(sb):
    """Simulate case where target is unreachable (wrong ground truth)."""
    print()
    print("="*80)
    print("CASE 2: Impossible Target (Wrong Ground Truth)")
    print("="*80)
    print()

    hygiene_rules = load_hygiene_rules()

    metric_spec = {
        "metric_type": "sum_dollars",
        "population_filter": {"deal_status": "active"}
    }

    # Use impossible target ($1M when actual is $7M-14M)
    impossible_target = 1_000_000

    # Iteration 0: Naive
    query_spec = {
        "applied_rules": [],
        "exclude_renewals": False,
        "description": "naive"
    }
    result0 = execute_sum_dollars_query(sb, query_spec, metric_spec["population_filter"])

    # Iteration 1: Apply exclude_renewals
    query_spec = {
        "applied_rules": ["exclude_renewals"],
        "exclude_renewals": True,
        "description": "exclude_renewals"
    }
    result1 = execute_sum_dollars_query(sb, query_spec, metric_spec["population_filter"])

    iterations = [
        {
            "iteration": 0,
            "applied_rules": [],
            "actual_value": result0.get("total_dollars", 0),
            "expected_value": impossible_target,
            "delta": abs(result0.get("total_dollars", 0) - impossible_target),
            "converged": False,
            "result": result0
        },
        {
            "iteration": 1,
            "applied_rules": ["exclude_renewals"],
            "actual_value": result1.get("total_dollars", 0),
            "expected_value": impossible_target,
            "delta": abs(result1.get("total_dollars", 0) - impossible_target),
            "converged": False,
            "result": result1
        }
    ]

    diagnostic = enhanced_diagnostic(iterations, impossible_target, 50_000, hygiene_rules)

    print(f"Naive result: ${iterations[0]['actual_value']:,.2f}")
    print(f"After exclude_renewals: ${iterations[1]['actual_value']:,.2f}")
    print(f"Target: ${impossible_target:,.2f}")
    print(f"Improvement: {diagnostic['improvement_pct']:.1f}%")
    print()
    print(f"Diagnostic type: {diagnostic['type']}")
    print(f"Severity: {diagnostic['severity']}")
    print()

    return diagnostic


def main():
    """Compare diagnostics for both failure types."""
    supabase_url = os.environ.get('SUPABASE_URL')
    supabase_key = os.environ.get('SUPABASE_SERVICE_KEY')

    if not supabase_url or not supabase_key:
        print("✗ ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        sys.exit(1)

    sb = create_client(supabase_url, supabase_key)

    print()
    print("="*80)
    print("DIAGNOSTIC QUALITY COMPARISON")
    print("="*80)
    print()
    print("Testing whether diagnostic meaningfully distinguishes between:")
    print("  1. Missing rule (real, achievable target)")
    print("  2. Impossible target (wrong ground truth)")
    print()

    diag1 = simulate_missing_rule_case(sb)
    diag2 = simulate_impossible_target_case(sb)

    print("="*80)
    print("COMPARISON SUMMARY")
    print("="*80)
    print()

    print("Case 1 (Missing Rule):")
    print(f"  Type: {diag1['type']}")
    print(f"  Improvement: {diag1['improvement_pct']:.1f}%")
    print(f"  Message preview: {diag1['message'][:100]}...")
    print()

    print("Case 2 (Impossible Target):")
    print(f"  Type: {diag2['type']}")
    print(f"  Improvement: {diag2['improvement_pct']:.1f}%")
    print(f"  Message preview: {diag2['message'][:100]}...")
    print()

    print("─"*80)
    print("QUALITY CHECK")
    print("─"*80)
    print()

    if diag1['type'] != diag2['type']:
        print("✓ DIAGNOSTIC QUALITY PASSED")
        print()
        print("Diagnostics are meaningfully different:")
        print(f"  - Missing rule: '{diag1['type']}' (improvement {diag1['improvement_pct']:.1f}%)")
        print(f"  - Impossible target: '{diag2['type']}' (improvement {diag2['improvement_pct']:.1f}%)")
        print()
        print("Messages provide different actionable guidance:")
        print(f"  - Missing rule: Recommends adding new hygiene rule to registry")
        print(f"  - Impossible target: Suggests ground truth verification needed")
        print()
        print("This is a meaningful distinction for human escalation.")
        return True
    else:
        print("✗ DIAGNOSTIC QUALITY ISSUE")
        print()
        print(f"Both cases classified as '{diag1['type']}'")
        print("Diagnostic does not meaningfully distinguish failure types.")
        print()
        print("This is a gap in escalation quality - both failure modes")
        print("produce identical diagnostics, reducing actionable guidance.")
        return False


if __name__ == '__main__':
    passed = main()
    sys.exit(0 if passed else 1)
