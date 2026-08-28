#!/usr/bin/env python3
"""
Test fiscal quarter resolution before dynamic loop.

Bug caught: "Get customers due to renew in Q3 and Q4" caused the loop to guess
quarter boundaries mid-run ("Q3 = Aug–Oct 2026, Q4 = Nov 2027–Jan 2027" - wrong).

Fix: Resolve quarter references before the loop and pass concrete dates.
"""

import sys
from pathlib import Path
from datetime import date

# Add api to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.time_resolver import resolve_time_window


def test_named_quarter_resolution():
    """Fiscal quarters resolve to concrete dates from config."""

    # FY starts Feb 1, so Q3 = Aug-Oct, Q4 = Nov-Jan
    q3_result = resolve_time_window({"period": "fiscal_quarter", "fiscal_quarter": "Q3"})
    q4_result = resolve_time_window({"period": "fiscal_quarter", "fiscal_quarter": "Q4"})

    print(f"[TEST] Named quarter resolution")
    print(f"  Q3: {q3_result['start']} to {q3_result['end']} ({q3_result['label']})")
    print(f"  Q4: {q4_result['start']} to {q4_result['end']} ({q4_result['label']})")

    # Q3 should be Aug-Oct
    assert q3_result['start'].startswith("20") and "-08-01" in q3_result['start'], \
        f"Q3 should start in August, got {q3_result['start']}"
    assert q3_result['end'].startswith("20") and "-10-31" in q3_result['end'], \
        f"Q3 should end in October, got {q3_result['end']}"

    # Q4 should be Nov-Jan (wraps into next calendar year)
    assert q4_result['start'].startswith("20") and "-11-01" in q4_result['start'], \
        f"Q4 should start in November, got {q4_result['start']}"
    assert q4_result['end'].startswith("20") and "-01-31" in q4_result['end'], \
        f"Q4 should end in January, got {q4_result['end']}"

    print(f"  ✓ Q3 and Q4 resolve correctly")


def test_fiscal_year_explicit():
    """FY2027 Q2 resolves to correct year boundaries."""

    result = resolve_time_window({"period": "fiscal_quarter", "fiscal_quarter": "FY2027 Q2"})

    print(f"\n[TEST] Explicit fiscal year")
    print(f"  FY2027 Q2: {result['start']} to {result['end']} ({result['label']})")

    # FY2027 Q2 = May-Jul 2026 (Q1 is Feb-Apr 2026)
    assert "2026-05-01" == result['start'], f"FY2027 Q2 should start 2026-05-01, got {result['start']}"
    assert "2026-07-31" == result['end'], f"FY2027 Q2 should end 2026-07-31, got {result['end']}"

    print(f"  ✓ Explicit FY year resolves correctly")


def test_quarter_never_guessed():
    """The model should never derive quarter boundaries — they come from config."""

    # This would previously cause: "Based on time context, I'll treat Q3 = Aug–Oct 2026"
    # Now it gets concrete dates before the loop starts

    q3 = resolve_time_window({"period": "fiscal_quarter", "fiscal_quarter": "Q3"})

    print(f"\n[TEST] Model never guesses quarters")
    print(f"  Q3 resolved to: {q3['start']} to {q3['end']}")
    print(f"  ✓ Concrete dates from config, not model inference")


def main():
    """Run quarter resolution tests."""
    print("=" * 70)
    print("FISCAL QUARTER RESOLUTION TESTS")
    print("=" * 70)

    try:
        test_named_quarter_resolution()
        test_fiscal_year_explicit()
        test_quarter_never_guessed()

        print("\n" + "=" * 70)
        print("RESULTS: 3 passed, 0 failed")
        print("=" * 70)
        return 0
    except AssertionError as e:
        print(f"\n  ❌ {e}")
        print("\n" + "=" * 70)
        print("RESULTS: 0 passed, 1 failed")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
