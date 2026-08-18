#!/usr/bin/env python3
"""
Test call deduplication logic.
Ensures Fireflies is preferred over Apollo when both exist for same date/deal.
"""

import sys
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent))

from etl_calls import deduplicate_calls_prefer_fireflies, validate_call_summary


def test_fireflies_preferred_over_apollo_same_date():
    """Fireflies call wins over Apollo when both exist for same date/deal."""
    calls = [
        {
            "id": "apollo_123",
            "title": "Acme Corp + GrowthBook",
            "date": "2026-08-05",
            "source": "apollo",
            "summary": "[Summary failed] Hey how are you"
        },
        {
            "id": "ff_456",
            "title": "Acme Corp + GrowthBook",
            "date": "2026-08-05",
            "source": "fireflies",
            "summary": "Full summary of the discovery call covering technical requirements and pricing discussion..."
        },
    ]
    result = deduplicate_calls_prefer_fireflies(calls, "acme-corp")
    assert len(result) == 1, f"Expected 1 call, got {len(result)}"
    assert result[0]["source"] == "fireflies", f"Expected fireflies, got {result[0]['source']}"
    print("  ✓ Fireflies preferred over Apollo for same deal/date")


def test_apollo_kept_when_no_fireflies():
    """Apollo call is kept when no Fireflies alternative exists."""
    calls = [
        {
            "id": "apollo_789",
            "title": "Solo Deal",
            "date": "2026-08-10",
            "source": "apollo",
            "summary": "[Summary failed] fragments"
        },
    ]
    result = deduplicate_calls_prefer_fireflies(calls, "solo-deal")
    assert len(result) == 1, f"Expected 1 call, got {len(result)}"
    assert result[0]["source"] == "apollo", f"Expected apollo, got {result[0]['source']}"
    print("  ✓ Apollo kept when no Fireflies alternative exists")


def test_longer_summary_wins_same_source():
    """When two calls from same source on same date, longer summary wins."""
    calls = [
        {
            "id": "ff_1",
            "title": "Duplicate Deal",
            "date": "2026-08-05",
            "source": "fireflies",
            "summary": "Short summary"
        },
        {
            "id": "ff_2",
            "title": "Duplicate Deal",
            "date": "2026-08-05",
            "source": "fireflies",
            "summary": "Much longer and more detailed summary here with lots of context about the call"
        },
    ]
    result = deduplicate_calls_prefer_fireflies(calls, "duplicate-deal")
    assert len(result) == 1, f"Expected 1 call, got {len(result)}"
    assert "longer" in result[0]["summary"], f"Expected longer summary, got: {result[0]['summary']}"
    print("  ✓ Longer summary wins when same source on same date")


def test_different_dates_kept():
    """Calls on different dates are both kept."""
    calls = [
        {
            "id": "apollo_1",
            "title": "Multi-Call Deal",
            "date": "2026-08-01",
            "source": "apollo",
            "summary": "First call summary"
        },
        {
            "id": "ff_1",
            "title": "Multi-Call Deal",
            "date": "2026-08-05",
            "source": "fireflies",
            "summary": "Second call summary"
        },
    ]
    result = deduplicate_calls_prefer_fireflies(calls, "multi-call-deal")
    assert len(result) == 2, f"Expected 2 calls, got {len(result)}"
    print("  ✓ Calls on different dates are both kept")


def test_summary_quality_validation():
    """Summary quality flags are added correctly."""
    # Good summary
    call1 = {"summary": "This is a comprehensive summary of the discovery call covering technical requirements."}
    validate_call_summary(call1)
    assert call1["summary_quality"] == "good", f"Expected 'good', got {call1['summary_quality']}"
    print("  ✓ Good summary detected")

    # Empty summary
    call2 = {"summary": ""}
    validate_call_summary(call2)
    assert call2["summary_quality"] == "empty", f"Expected 'empty', got {call2['summary_quality']}"
    print("  ✓ Empty summary detected")

    # Corrupted summary
    call3 = {"summary": "[Summary failed] [speaker]: fragments"}
    validate_call_summary(call3)
    assert call3["summary_quality"] == "corrupted", f"Expected 'corrupted', got {call3['summary_quality']}"
    print("  ✓ Corrupted summary detected")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Testing Call Deduplication Logic")
    print("=" * 60 + "\n")

    try:
        test_fireflies_preferred_over_apollo_same_date()
        test_apollo_kept_when_no_fireflies()
        test_longer_summary_wins_same_source()
        test_different_dates_kept()
        test_summary_quality_validation()

        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60 + "\n")

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
