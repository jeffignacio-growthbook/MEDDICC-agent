#!/usr/bin/env python3
"""
Wave 4 Item 4: Drift test for at-risk definition isolation.

Ensures no handler computes at-risk status via inline logic outside the
canonical compute_at_risk_deals() function.

This prevents the q012 duplication bug from recurring as new handlers are built.

Usage:
    python3 scripts/test_at_risk_isolation.py

Exit codes:
    0 - All tests passed (no at-risk logic outside semantic layer)
    1 - Drift detected (inline at-risk logic found in handlers)
"""

import re
import sys
from pathlib import Path


def check_at_risk_isolation():
    """
    Verify all at-risk logic routes through compute_at_risk_deals().

    Returns True if no violations found, False otherwise.
    """
    print("[TEST] At-risk logic isolation (Wave 4 Item 4)")
    print("  Checking for inline at-risk computations outside canonical function...")

    handlers_path = Path(__file__).parent.parent / "api" / "handlers.py"
    if not handlers_path.exists():
        print(f"  ❌ handlers.py not found at {handlers_path}")
        return False

    content = handlers_path.read_text()

    # Patterns that indicate inline at-risk computation
    # These should ONLY appear inside compute_at_risk_deals()
    forbidden_patterns = [
        # Simple threshold comparisons (from old quick check logic)
        (r'\boverall_score\s*<\s*40\b', 'overall_score < 40'),
        (r'\bchampion_score\s*<\s*4\b', 'champion_score < 4'),

        # Combined threshold checks
        (r'\bscore\s*<\s*40\s+or\s+champ', 'score < 40 or champ < 4'),
        (r'\boverall.*<.*40.*or.*champion.*<.*4', 'overall < 40 or champion < 4'),

        # Stage-aware band checking outside unified function
        # (band_meets calls should only be in compute_at_risk_deals)
        (r'if not band_meets\([^)]+\):', 'band_meets() check'),
    ]

    violations = []

    for pattern, desc in forbidden_patterns:
        matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)

        for match in matches:
            # Get line number
            line_num = content[:match.start()].count('\n') + 1

            # Get context around the match
            line_start = content.rfind('\n', 0, match.start()) + 1
            line_end = content.find('\n', match.end())
            if line_end == -1:
                line_end = len(content)
            line_text = content[line_start:line_end].strip()

            # Check if this is inside compute_at_risk_deals() definition
            # Find the function definition before this match
            func_start = content.rfind('def compute_at_risk_deals', 0, match.start())
            next_func = content.find('\ndef ', match.start())
            next_async_func = content.find('\nasync def ', match.start())

            # If next_func is -1, we're at the end of the file
            if next_func == -1:
                next_func = len(content)
            if next_async_func == -1:
                next_async_func = len(content)

            # Take the closer of the two
            next_func_pos = min(next_func, next_async_func)

            # If we found compute_at_risk_deals before the match,
            # and no other function between compute_at_risk_deals and the match,
            # then this match is INSIDE compute_at_risk_deals (allowed)
            if func_start != -1 and func_start < match.start() < next_func_pos:
                # Inside compute_at_risk_deals - this is allowed
                continue

            # Outside compute_at_risk_deals - this is a violation
            violations.append({
                'line': line_num,
                'pattern': desc,
                'text': line_text,
                'context': content[max(0, match.start()-100):match.end()+100]
            })

    if violations:
        print("  ❌ DRIFT DETECTED: At-risk logic found outside compute_at_risk_deals()")
        print("\n  Violations:")
        for v in violations:
            print(f"    Line {v['line']}: {v['pattern']}")
            print(f"      {v['text']}")
        print("\n  Fix: All at-risk checks must use compute_at_risk_deals()")
        print("  See config/field_semantics.yaml → deal_states.at_risk for definition")
        return False

    print("  ✓ No drift: All at-risk logic uses compute_at_risk_deals()")
    return True


def check_at_risk_function_exists():
    """Verify compute_at_risk_deals() function is defined in handlers.py"""
    print("[TEST] Canonical at-risk function exists")

    handlers_path = Path(__file__).parent.parent / "api" / "handlers.py"
    content = handlers_path.read_text()

    if 'def compute_at_risk_deals(' not in content:
        print("  ❌ compute_at_risk_deals() not found in handlers.py")
        return False

    print("  ✓ compute_at_risk_deals() defined in handlers.py")
    return True


def check_semantic_layer_function_exists():
    """Verify is_at_risk_quick() is defined in field_semantics.py"""
    print("[TEST] Semantic layer at-risk function exists")

    semantics_path = Path(__file__).parent.parent / "api" / "field_semantics.py"
    content = semantics_path.read_text()

    if 'def is_at_risk_quick(' not in content:
        print("  ❌ is_at_risk_quick() not found in field_semantics.py")
        return False

    print("  ✓ is_at_risk_quick() defined in field_semantics.py")
    return True


def main():
    print("=" * 70)
    print("AT-RISK LOGIC ISOLATION TEST (Wave 4 Drift Prevention)")
    print("=" * 70)
    print()

    results = []

    # Test 1: Canonical function exists
    results.append(check_at_risk_function_exists())
    print()

    # Test 2: Semantic layer function exists
    results.append(check_semantic_layer_function_exists())
    print()

    # Test 3: No inline at-risk logic outside canonical function
    results.append(check_at_risk_isolation())
    print()

    # Summary
    passed = sum(results)
    total = len(results)
    print("=" * 70)
    print(f"RESULTS: {passed} passed, {total - passed} failed")
    print("=" * 70)

    if all(results):
        print("\n✅ All tests passed - at-risk logic is properly isolated")
        return 0
    else:
        print("\n❌ Some tests failed - at-risk logic isolation violated")
        print("   This prevents the q012 bug from recurring")
        return 1


if __name__ == '__main__':
    sys.exit(main())
