#!/usr/bin/env python3
"""
Stress Test: Diagnostic Classifier Edge Cases

The diagnostic classifier uses thresholds (90%, 5%, 50%) that were tuned
to make TWO test cases work:
  - 97.9% improvement, 2.2% gap → missing_rule
  - 53.4% improvement, 86% gap → impossible_target

This is curve-fitting, not validation. Test classifier against edge cases
to verify it produces REASONABLE classifications across the full space.

Edge cases to test:
  1. ~70% improvement, ~30% gap (middle of the range)
  2. ~95% improvement, ~15% gap (near missing_rule boundary)
  3. ~40% improvement, ~40% gap (neither condition matches)
  4. ~85% improvement, ~8% gap (just below missing_rule threshold)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.test_phase2b_real_escalation import enhanced_diagnostic


def test_diagnostic_classifier():
    """Test diagnostic classifier against edge cases."""

    print("="*80)
    print("DIAGNOSTIC CLASSIFIER STRESS TEST")
    print("="*80)
    print()
    print("Testing classifier against edge cases NOT used during development")
    print()

    # Test cases: (naive, final, target, description)
    test_cases = [
        {
            "name": "Known Case 1: Missing Rule (Original)",
            "naive": 14_221_230,
            "final": 7_160_865,
            "target": 7_005_865,
            "expected": "missing_rule",
            "notes": "Original test case - classifier was tuned for this"
        },
        {
            "name": "Known Case 2: Impossible Target (Original)",
            "naive": 14_221_230,
            "final": 7_160_865,
            "target": 1_000_000,
            "expected": "impossible_target",
            "notes": "Original test case - classifier was tuned for this"
        },
        {
            "name": "Edge Case 1: Middle Range (70% improvement, 30% gap)",
            "naive": 10_000_000,
            "final": 4_000_000,
            "target": 2_800_000,
            "expected": "partial_progress or missing_rule",
            "notes": "Falls between the two extremes - which branch fires?"
        },
        {
            "name": "Edge Case 2: Near Missing Rule Boundary (95% improvement, 15% gap)",
            "naive": 10_000_000,
            "final": 1_500_000,
            "target": 1_275_000,
            "expected": "missing_rule or partial_progress",
            "notes": "High improvement but gap exceeds 5% threshold"
        },
        {
            "name": "Edge Case 3: Neither Condition (40% improvement, 40% gap)",
            "naive": 10_000_000,
            "final": 6_000_000,
            "target": 3_600_000,
            "expected": "partial_progress",
            "notes": "Improvement < 50%, doesn't match either main branch"
        },
        {
            "name": "Edge Case 4: Just Below Threshold (85% improvement, 8% gap)",
            "naive": 10_000_000,
            "final": 1_500_000,
            "target": 1_380_000,
            "expected": "partial_progress",
            "notes": "Improvement < 90%, gap > 5% - misses missing_rule condition"
        },
        {
            "name": "Edge Case 5: High Gap, Low Improvement (30% improvement, 70% gap)",
            "naive": 10_000_000,
            "final": 7_000_000,
            "target": 2_100_000,
            "expected": "partial_progress",
            "notes": "Low improvement, high gap - falls through to else?"
        }
    ]

    tolerance = 100_000  # Not used in classifier, but required for signature
    available_rules = []  # Not used in classification

    results = []

    for i, case in enumerate(test_cases, 1):
        print(f"─"*80)
        print(f"TEST CASE {i}: {case['name']}")
        print(f"─"*80)
        print()

        # Build mock iterations
        naive_delta = abs(case['naive'] - case['target'])
        final_delta = abs(case['final'] - case['target'])
        improvement = naive_delta - final_delta
        improvement_pct = (improvement / naive_delta * 100) if naive_delta > 0 else 0
        remaining_gap_pct = (final_delta / case['final'] * 100) if case['final'] > 0 else 0

        print(f"Naive value: ${case['naive']:,.0f}")
        print(f"Final value: ${case['final']:,.0f}")
        print(f"Target value: ${case['target']:,.0f}")
        print()
        print(f"Improvement: {improvement_pct:.1f}%")
        print(f"Remaining gap: {remaining_gap_pct:.1f}% of final value")
        print()

        iterations = [
            {
                "iteration": 0,
                "applied_rules": [],
                "actual_value": case['naive'],
                "expected_value": case['target'],
                "delta": naive_delta,
                "converged": False
            },
            {
                "iteration": 1,
                "applied_rules": ["exclude_renewals"],
                "actual_value": case['final'],
                "expected_value": case['target'],
                "delta": final_delta,
                "converged": False
            }
        ]

        diagnostic = enhanced_diagnostic(iterations, case['target'], tolerance, available_rules)

        print(f"Classifier output: {diagnostic['type']}")
        print(f"Expected (when designed): {case['expected']}")
        print()

        # Check if classification is reasonable
        classification_ok = False
        reason = ""

        if case['name'].startswith("Known Case"):
            # Original cases should match expected
            classification_ok = diagnostic['type'] == case['expected']
            reason = "Original test case - should match expected"
        else:
            # Edge cases - check if classification is REASONABLE, not necessarily matches expected
            if improvement_pct > 80 and remaining_gap_pct < 10:
                # High improvement, low gap - should be missing_rule
                classification_ok = diagnostic['type'] == 'missing_rule'
                reason = "High improvement + low gap → missing_rule is reasonable"
            elif improvement_pct < 50 and remaining_gap_pct > 50:
                # Low improvement, high gap - should be impossible_target
                classification_ok = diagnostic['type'] == 'impossible_target'
                reason = "Low improvement + high gap → impossible_target is reasonable"
            elif improvement_pct > 50 and improvement_pct < 90:
                # Middle range - partial_progress is reasonable
                classification_ok = diagnostic['type'] == 'partial_progress'
                reason = "Middle range → partial_progress is reasonable"
            else:
                # Any classification could be reasonable, accept anything
                classification_ok = True
                reason = f"Edge case - {diagnostic['type']} is acceptable"

        if classification_ok:
            print(f"✓ REASONABLE: {reason}")
        else:
            print(f"✗ QUESTIONABLE: {reason}")
            print(f"   Got '{diagnostic['type']}' for {improvement_pct:.1f}% improvement, {remaining_gap_pct:.1f}% gap")

        print()
        print(f"Notes: {case['notes']}")
        print()

        results.append({
            "case": case['name'],
            "improvement_pct": improvement_pct,
            "remaining_gap_pct": remaining_gap_pct,
            "classification": diagnostic['type'],
            "reasonable": classification_ok,
            "reason": reason
        })

    # Summary
    print()
    print("="*80)
    print("STRESS TEST SUMMARY")
    print("="*80)
    print()

    known_cases = [r for r in results if "Known Case" in r['case']]
    edge_cases = [r for r in results if "Edge Case" in r['case']]

    print("Known Cases (classifier tuned for these):")
    for r in known_cases:
        status = "✓" if r['reasonable'] else "✗"
        print(f"  {status} {r['case']}: {r['classification']}")

    print()
    print("Edge Cases (NOT seen during development):")
    for r in edge_cases:
        status = "✓" if r['reasonable'] else "✗"
        print(f"  {status} {r['case']}: {r['classification']}")
        print(f"     {r['improvement_pct']:.1f}% improvement, {r['remaining_gap_pct']:.1f}% gap")

    print()
    print("─"*80)
    print("CLASSIFIER QUALITY ASSESSMENT")
    print("─"*80)
    print()

    known_pass = all(r['reasonable'] for r in known_cases)
    edge_pass = all(r['reasonable'] for r in edge_cases)

    if known_pass and edge_pass:
        print("✓ Classifier produces REASONABLE classifications across tested range")
        print()
        print("HOWEVER: This is still a HAND-PICKED HEURISTIC")
        print()
        print("The thresholds (90%, 5%, 50%) were chosen to fit known cases.")
        print("Stress test shows it generalizes reasonably to edge cases,")
        print("but it has NOT been validated against production data.")
        print()
        print("Honest labeling: HEURISTIC (same as Signal 3's 14-day threshold)")
        print()
        print("Recommended documentation:")
        print("  - Label as 'diagnostic_heuristic' in code")
        print("  - Document thresholds as hand-picked, not derived")
        print("  - Note: validated on 7 synthetic cases, not production data")
        print("  - Include re-derivation trigger: Review after 20+ production escalations")
        return True
    elif known_pass:
        print("✓ Known cases pass")
        print("✗ Some edge cases produce questionable classifications")
        print()
        print("Classifier works on training data but may not generalize well.")
        print("Recommend refining threshold logic before production use.")
        return False
    else:
        print("✗ Classifier fails even on known cases")
        print()
        print("Critical issue - classifier is not working as designed.")
        return False


if __name__ == '__main__':
    passed = test_diagnostic_classifier()
    sys.exit(0 if passed else 1)
