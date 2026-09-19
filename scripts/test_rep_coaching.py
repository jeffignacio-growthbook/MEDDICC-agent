#!/usr/bin/env python3
"""
Baseline tests for assess_rep_coaching() - Step 2 verification: hard transcript gate.

Tests:
1. Deal with zero transcript-scored calls → insufficient_data/no_transcript_available,
   no downstream computation.
2. Deal with at least one transcript-scored call → identifies most recent one.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from rep_coaching import assess_rep_coaching


def test_no_transcript_calls_gates_immediately():
    """Zero transcript-scored calls → insufficient_data, no downstream work."""
    print("\n[TEST] Deal with zero transcript-scored calls → gate fires")

    # Mock Supabase client that returns empty list for call_scores query
    class MockSB:
        def table(self, name):
            return self

        def select(self, cols):
            return self

        def eq(self, field, value):
            return self

        def range(self, start, end):
            return self

        def execute(self):
            class Result:
                data = []
                count = 0
            return Result()

    sb = MockSB()
    result = assess_rep_coaching(sb, "test_deal_no_transcripts")

    # Verify gate fired
    if result.get("status") != "insufficient_data":
        raise AssertionError(f"Expected status='insufficient_data', got {result!r}")
    if result.get("reason") != "no_transcript_available":
        raise AssertionError(f"Expected reason='no_transcript_available', got {result!r}")
    if "transcript-scored call" not in result.get("note", ""):
        raise AssertionError(f"Expected note to explain transcript requirement, got: {result['note']!r}")

    # Verify no downstream data present (gate short-circuited)
    if "target_call_id" in result:
        raise AssertionError(f"Gate should have short-circuited before computing target_call_id")
    if "criterion_a" in result or "criterion_b" in result or "criterion_c" in result:
        raise AssertionError(f"Gate should have short-circuited before running criteria")

    print("  ✓ Gate fired correctly, no downstream computation")


def test_coverage_note_present_when_gated():
    """Coverage disclosure must appear in the gated (no transcript) path."""
    print("\n[TEST] Coverage note present in gated (insufficient_data) path")

    # Mock Supabase that returns empty call_scores AND has coverage data
    class MockSB:
        def __init__(self):
            self.table_name = None

        def table(self, name):
            self.table_name = name
            return self

        def select(self, cols):
            return self

        def eq(self, field, value):
            return self

        def range(self, start, end):
            return self

        def execute(self):
            class Result:
                def __init__(self, table_name):
                    # call_scores: empty (gate fires)
                    # deals: 2 total deals
                    # calls: 2 calls
                    # call_scores (for coverage): 1 deal has transcript
                    if table_name == "call_scores" and hasattr(self, '_for_coverage'):
                        data = [{"call_id": "call1", "deal_id": "deal1", "text_source": "transcript"}]
                    elif table_name == "call_scores":
                        data = []  # Zero for the deal being assessed
                    elif table_name == "deals":
                        data = [{"deal_id": "deal1", "deal_status": "active"},
                                {"deal_id": "deal2", "deal_status": "active"}]
                    elif table_name == "calls":
                        data = [{"call_id": "call1", "deal_id": "deal1"},
                                {"call_id": "call2", "deal_id": "deal2"}]
                    else:
                        data = []
                    self.data = data
                    self.count = len(data)

                data = []
                count = 0

            result = Result(self.table_name)
            return result

    sb = MockSB()
    result = assess_rep_coaching(sb, "deal_no_transcripts")

    # Verify gate fired
    if result.get("status") != "insufficient_data":
        raise AssertionError(f"Expected status='insufficient_data', got {result.get('status')}")

    # Verify coverage_note is present
    if "coverage_note" not in result:
        raise AssertionError(f"Expected coverage_note in gated path, got keys: {result.keys()}")

    coverage_note = result.get("coverage_note")
    if not isinstance(coverage_note, str) or len(coverage_note) == 0:
        raise AssertionError(f"Expected non-empty coverage_note string, got: {coverage_note!r}")

    # Verify it mentions "deals" and "transcript"
    if "deals" not in coverage_note.lower() or "transcript" not in coverage_note.lower():
        raise AssertionError(f"Expected coverage note to mention 'deals' and 'transcript', "
                             f"got: {coverage_note!r}")

    print(f"  ✓ Coverage note present in gated path: '{coverage_note[:80]}...'")


def test_with_transcript_calls_identifies_most_recent():
    """At least one transcript-scored call → identifies most recent one."""
    print("\n[TEST] Deal with transcript-scored calls → identifies most recent")

    # Mock Supabase client that returns transcript calls
    class MockSB:
        def table(self, name):
            return self

        def select(self, cols):
            return self

        def eq(self, field, value):
            self.field = field
            return self

        def range(self, start, end):
            return self

        def execute(self):
            class Result:
                # Return 3 transcript-scored calls with different dates
                data = [
                    {"call_id": "call_1", "deal_id": "test_deal",
                     "call_date": "2026-09-15", "text_source": "transcript"},
                    {"call_id": "call_2", "deal_id": "test_deal",
                     "call_date": "2026-09-18", "text_source": "transcript"},  # Most recent
                    {"call_id": "call_3", "deal_id": "test_deal",
                     "call_date": "2026-09-10", "text_source": "transcript"},
                ]
                count = 3
            return Result()

    sb = MockSB()
    result = assess_rep_coaching(sb, "test_deal")

    # Gate should NOT fire
    if result.get("reason") == "no_transcript_available":
        raise AssertionError(f"Gate fired incorrectly with transcript calls present: {result!r}")

    # Should identify the most recent call (call_2 from 2026-09-18)
    if result.get("target_call_id") != "call_2":
        raise AssertionError(f"Expected target_call_id='call_2', got {result.get('target_call_id')}")
    if result.get("target_call_date") != "2026-09-18":
        raise AssertionError(f"Expected target_call_date='2026-09-18', got {result.get('target_call_date')}")
    if result.get("transcript_call_count") != 3:
        raise AssertionError(f"Expected transcript_call_count=3, got {result.get('transcript_call_count')}")

    print(f"  ✓ Most recent call identified: call_id={result['target_call_id']}, "
          f"call_date={result['target_call_date']}, "
          f"total_transcript_calls={result['transcript_call_count']}")


def test_coverage_note_present_when_ungated():
    """Coverage disclosure must appear in the ungated (has transcript) path."""
    print("\n[TEST] Coverage note present in ungated (has transcript) path")

    # Mock Supabase that returns transcript calls AND has coverage data
    class MockSB:
        def __init__(self):
            self.table_name = None
            self.filters_applied = []

        def table(self, name):
            self.table_name = name
            return self

        def select(self, cols):
            return self

        def eq(self, field, value):
            self.filters_applied.append((field, value))
            return self

        def range(self, start, end):
            return self

        def execute(self):
            class Result:
                def __init__(self, table_name, filters_applied):
                    # Check if this is the call_scores query for the specific deal
                    is_deal_query = any(f[0] == "deal_id" for f in filters_applied)
                    is_transcript_filter = any(f[0] == "text_source" for f in filters_applied)

                    if table_name == "call_scores" and is_deal_query and is_transcript_filter:
                        # The deal being assessed has transcript calls
                        data = [
                            {"call_id": "call_1", "deal_id": "test_deal",
                             "call_date": "2026-09-15", "text_source": "transcript"},
                            {"call_id": "call_2", "deal_id": "test_deal",
                             "call_date": "2026-09-18", "text_source": "transcript"},
                        ]
                    elif table_name == "call_scores" and is_transcript_filter:
                        # Coverage query: some deals have transcripts
                        data = [{"call_id": "call1", "deal_id": "deal1", "text_source": "transcript"},
                                {"call_id": "call2", "deal_id": "deal2", "text_source": "transcript"}]
                    elif table_name == "deals":
                        data = [{"deal_id": "deal1", "deal_status": "active"},
                                {"deal_id": "deal2", "deal_status": "active"},
                                {"deal_id": "deal3", "deal_status": "active"}]
                    elif table_name == "calls":
                        data = [{"call_id": "call1", "deal_id": "deal1"},
                                {"call_id": "call2", "deal_id": "deal2"}]
                    else:
                        data = []
                    self.data = data
                    self.count = len(data)

                data = []
                count = 0

            result = Result(self.table_name, self.filters_applied)
            self.filters_applied = []  # Reset for next call
            return result

    sb = MockSB()
    result = assess_rep_coaching(sb, "test_deal")

    # Gate should NOT fire
    if result.get("reason") == "no_transcript_available":
        raise AssertionError(f"Gate fired incorrectly with transcript calls present: {result!r}")

    # Verify coverage_note is present in the ungated path too
    if "coverage_note" not in result:
        raise AssertionError(f"Expected coverage_note in ungated path, got keys: {result.keys()}")

    coverage_note = result.get("coverage_note")
    if not isinstance(coverage_note, str) or len(coverage_note) == 0:
        raise AssertionError(f"Expected non-empty coverage_note string, got: {coverage_note!r}")

    # Verify it mentions "deals" and "transcript"
    if "deals" not in coverage_note.lower() or "transcript" not in coverage_note.lower():
        raise AssertionError(f"Expected coverage note to mention 'deals' and 'transcript', "
                             f"got: {coverage_note!r}")

    print(f"  ✓ Coverage note present in ungated path: '{coverage_note[:80]}...'")


def main():
    tests = [
        test_no_transcript_calls_gates_immediately,
        test_coverage_note_present_when_gated,
        test_with_transcript_calls_identifies_most_recent,
        test_coverage_note_present_when_ungated,
    ]

    failed = []
    for test in tests:
        try:
            test()
        except Exception as e:
            failed.append((test.__name__, str(e)))
            print(f"\n  ❌ FAILED: {e}")

    print("\n" + "=" * 70)
    print("TEST SUMMARY - Steps 2-3: Hard Transcript Gate + Coverage Disclosure")
    print("=" * 70)

    passed = len(tests) - len(failed)
    print(f"\nTotal tests: {len(tests)}")
    print(f"  ✓ Passed: {passed}")

    if failed:
        print(f"  ✗ Failed: {len(failed)}")
        print("\nFailed tests:")
        for name, error in failed:
            print(f"  - {name}")
            print(f"    {error[:200]}")
        return 1

    print("\n✅ All hard transcript gate + coverage disclosure tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
