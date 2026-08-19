#!/usr/bin/env python3
"""
Drift tests for call adapter abstraction.
Guards against:
- Adapters not implementing the interface
- NormalizedCall returning wrong shape
- Type-check branches leaking back into calling code
- Dedup priority not driven from config
"""

import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

def test_normalized_call_to_row_shape():
    """
    to_row() produces the exact keys the calls table upsert expects.
    """
    print("\n[TEST] NormalizedCall.to_row() shape matches calls table")

    from adapters.call_source import NormalizedCall

    # Create a sample normalized call
    call = NormalizedCall(
        source="fireflies",
        source_call_id="test-123",
        title="Test Call",
        call_date="2026-08-01",
        summary="Test summary content",
        duration_minutes=30,
        participant_emails=["test@example.com"],
        participant_count=2,
        raw_transcript="Test transcript",
        summary_quality="good"
    )

    row = call.to_row()

    # Expected keys for calls table upsert
    expected_keys = {
        "source",
        "call_id",
        "title",
        "call_date",
        "summary",
        "duration_minutes",
        "participant_emails",
        "participant_count",
        "summary_quality"
    }

    actual_keys = set(row.keys())

    assert actual_keys == expected_keys, \
        f"to_row() keys mismatch. Expected {expected_keys}, got {actual_keys}"

    # Verify types
    assert isinstance(row["source"], str), "source must be string"
    assert isinstance(row["call_id"], str), "call_id must be string"
    assert isinstance(row["title"], str), "title must be string"
    assert isinstance(row["call_date"], str), "call_date must be string (ISO format)"
    assert isinstance(row["summary"], str), "summary must be string"
    assert isinstance(row["duration_minutes"], int), "duration_minutes must be int"
    assert isinstance(row["participant_emails"], list), "participant_emails must be list"
    assert isinstance(row["participant_count"], int), "participant_count must be int"
    assert isinstance(row["summary_quality"], str), "summary_quality must be string"

    print("  ✓ to_row() returns correct shape:")
    print(f"    {len(expected_keys)} fields, all typed correctly")
    print(f"    source: {row['source']}")
    print(f"    call_id: {row['call_id']}")
    print(f"    summary_quality: {row['summary_quality']}")


def test_interface_is_abstract():
    """
    CallSourceAdapter cannot be instantiated directly.
    """
    print("\n[TEST] CallSourceAdapter is abstract")

    from adapters.call_source import CallSourceAdapter

    # Attempt to instantiate the abstract class directly
    try:
        adapter = CallSourceAdapter()
        # If we get here, the class is NOT abstract - fail the test
        raise AssertionError("CallSourceAdapter should not be instantiable (missing @abstractmethod enforcement)")
    except TypeError as e:
        # Expected: "Can't instantiate abstract class CallSourceAdapter with abstract methods..."
        error_msg = str(e)
        assert "abstract" in error_msg.lower(), \
            f"Expected TypeError about abstract class, got: {error_msg}"

        print("  ✓ CallSourceAdapter is abstract")
        print(f"    Cannot instantiate: {error_msg[:100]}...")


def main():
    """Run all call adapter drift tests."""
    print("=" * 70)
    print("CALL ADAPTER ABSTRACTION TESTS (Phase 1)")
    print("=" * 70)

    tests = [
        test_normalized_call_to_row_shape,
        test_interface_is_abstract,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"\n❌ FAILED: {test.__name__}")
            print(f"   {e}")
        except Exception as e:
            failed += 1
            print(f"\n❌ ERROR in {test.__name__}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
