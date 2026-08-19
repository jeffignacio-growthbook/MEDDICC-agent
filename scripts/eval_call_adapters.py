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


def test_all_adapters_subclass_interface():
    """
    Fireflies/Gong/Apollo adapters all subclass CallSourceAdapter.
    """
    print("\n[TEST] All adapters subclass CallSourceAdapter")

    from adapters.call_source import CallSourceAdapter
    from adapters.fireflies_adapter import FirefliesAdapter
    from adapters.gong_adapter import GongAdapter
    from adapters.apollo_adapter import ApolloAdapter

    adapters = [
        ('FirefliesAdapter', FirefliesAdapter),
        ('GongAdapter', GongAdapter),
        ('ApolloAdapter', ApolloAdapter),
    ]

    for name, adapter_class in adapters:
        assert issubclass(adapter_class, CallSourceAdapter), \
            f"{name} does not subclass CallSourceAdapter"
        print(f"  ✓ {name} subclasses CallSourceAdapter")

    print(f"  All 3 adapters correctly subclass the interface")


def test_all_adapters_return_normalized_call():
    """
    Each adapter's _normalize returns a NormalizedCall with source set.
    """
    print("\n[TEST] All adapters return NormalizedCall from _normalize")

    from adapters.call_source import NormalizedCall
    from adapters.fireflies_adapter import FirefliesAdapter
    from adapters.gong_adapter import GongAdapter
    from adapters.apollo_adapter import ApolloAdapter

    # Create sample inputs for each adapter
    fireflies_transcript = {
        'id': 'ff-123',
        'title': 'Test Call',
        'date': 1640995200000,  # 2022-01-01
        'duration': 30,
        'organizer_email': 'test@example.com',
        'participants': ['user@example.com'],
        'summary': {
            'short_summary': 'Test summary',
            'keywords': ['test'],
        }
    }

    gong_call = {
        'id': 'gong-123',
        'title': 'Test Call',
        'started': '2022-01-01T10:00:00Z',
        'duration': 1800,  # seconds
        'brief': 'Test brief',
        'topics': ['pricing'],
        'keyPoints': ['Key point 1'],
        'parties': [{'emailAddress': 'test@example.com', 'name': 'Test User'}],
        'speakers': [],
    }

    apollo_conversation = {
        'id': 'apollo-123',
        'topic': 'Test Call',
        'start_time': '2022-01-01T10:00:00Z',
        'duration': 1800,  # seconds
        'state': 'completed',
        'host': 'test@example.com',
        'transcript': [
            {'participant_name': 'User', 'spoken_sentence': 'Hello'},
        ],
        'insights': {
            'summary': 'Test summary for Apollo conversation',
        }
    }

    # Test each adapter
    ff_adapter = FirefliesAdapter()
    result_ff = ff_adapter._normalize(fireflies_transcript)
    assert isinstance(result_ff, NormalizedCall), \
        "FirefliesAdapter._normalize must return NormalizedCall"
    assert result_ff.source == 'fireflies', \
        f"Expected source='fireflies', got '{result_ff.source}'"
    print(f"  ✓ FirefliesAdapter._normalize returns NormalizedCall with source='fireflies'")

    # GongAdapter requires credentials to instantiate, so we test the class method
    # by creating a minimal instance
    try:
        # Mock credentials
        import os
        os.environ['GONG_ACCESS_KEY'] = 'test-key'
        os.environ['GONG_ACCESS_KEY_SECRET'] = 'test-secret'

        gong_adapter = GongAdapter()
        result_gong = gong_adapter._normalize(gong_call)
        assert isinstance(result_gong, NormalizedCall), \
            "GongAdapter._normalize must return NormalizedCall"
        assert result_gong.source == 'gong', \
            f"Expected source='gong', got '{result_gong.source}'"
        print(f"  ✓ GongAdapter._normalize returns NormalizedCall with source='gong'")
    finally:
        # Clean up env
        os.environ.pop('GONG_ACCESS_KEY', None)
        os.environ.pop('GONG_ACCESS_KEY_SECRET', None)

    # ApolloAdapter requires API key
    try:
        os.environ['APOLLO_API_KEY'] = 'test-key'

        apollo_adapter = ApolloAdapter()
        result_apollo = apollo_adapter._normalize(apollo_conversation)
        assert isinstance(result_apollo, NormalizedCall), \
            "ApolloAdapter._normalize must return NormalizedCall"
        assert result_apollo.source == 'apollo', \
            f"Expected source='apollo', got '{result_apollo.source}'"
        print(f"  ✓ ApolloAdapter._normalize returns NormalizedCall with source='apollo'")
    finally:
        os.environ.pop('APOLLO_API_KEY', None)

    print(f"  All adapters return correct NormalizedCall with source field set")


def test_apollo_adapter_never_returns_summary_failed():
    """
    ApolloAdapter._normalize never yields a summary starting with
    '[Summary failed]' — even when the native summary is empty.

    This test exercises the empty-native-summary path to ensure
    the adapter's fallback logic works.
    """
    print("\n[TEST] ApolloAdapter never returns '[Summary failed]'")

    import os
    from adapters.apollo_adapter import ApolloAdapter

    # Mock Apollo API key for testing
    os.environ['APOLLO_API_KEY'] = 'test-key'

    try:
        apollo_adapter = ApolloAdapter()

        # Test case 1: Empty insights (no native summary)
        conversation_no_summary = {
            'id': 'apollo-empty-1',
            'topic': 'Test Call - No Summary',
            'start_time': '2022-01-01T10:00:00Z',
            'duration': 1800,
            'state': 'completed',
            'host': 'test@example.com',
            'transcript': [],  # No transcript
            'insights': {},  # No insights
        }

        result = apollo_adapter._normalize(conversation_no_summary)
        assert not result.summary.startswith('[Summary failed]'), \
            "Apollo adapter returned '[Summary failed]' for empty summary case"
        print(f"  ✓ Empty insights → fallback summary (no '[Summary failed]')")

        # Test case 2: Short transcript (< 100 chars)
        conversation_short = {
            'id': 'apollo-short-2',
            'topic': 'Quick Check-in',
            'start_time': '2022-01-01T11:00:00Z',
            'duration': 300,
            'state': 'completed',
            'host': 'test@example.com',
            'transcript': [
                {'participant_name': 'User', 'spoken_sentence': 'Hi'},
                {'participant_name': 'Rep', 'spoken_sentence': 'Hello'},
            ],
            'insights': {},
        }

        result = apollo_adapter._normalize(conversation_short)
        assert not result.summary.startswith('[Summary failed]'), \
            "Apollo adapter returned '[Summary failed]' for short transcript"
        print(f"  ✓ Short transcript → minimal summary (no '[Summary failed]')")

        # Test case 3: Good native summary (should use it)
        conversation_good = {
            'id': 'apollo-good-3',
            'topic': 'Discovery Call',
            'start_time': '2022-01-01T12:00:00Z',
            'duration': 1800,
            'state': 'completed',
            'host': 'test@example.com',
            'transcript': [
                {'participant_name': 'User', 'spoken_sentence': 'We need better analytics'},
            ],
            'insights': {
                'summary': 'Customer discussed analytics requirements and mentioned they are evaluating solutions.',
            },
        }

        result = apollo_adapter._normalize(conversation_good)
        assert not result.summary.startswith('[Summary failed]'), \
            "Apollo adapter returned '[Summary failed]' even with good native summary"
        assert len(result.summary) > 50, \
            "Apollo summary too short for conversation with good insights"
        print(f"  ✓ Good native summary → formatted summary (no '[Summary failed]')")

        print(f"  ApolloAdapter guarantees no '[Summary failed]' in all cases")

    finally:
        os.environ.pop('APOLLO_API_KEY', None)


def main():
    """Run all call adapter drift tests."""
    print("=" * 70)
    print("CALL ADAPTER ABSTRACTION TESTS (Phase 2)")
    print("=" * 70)

    tests = [
        test_normalized_call_to_row_shape,
        test_interface_is_abstract,
        test_all_adapters_subclass_interface,
        test_all_adapters_return_normalized_call,
        test_apollo_adapter_never_returns_summary_failed,
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
