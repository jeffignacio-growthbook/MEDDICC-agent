"""
Regression test for Apollo terminal classification bug (transcript gap investigation).

BUG FIXED: Old code would mark Apollo calls as TERMINAL (no retry) based solely
on call age > 3 days, even when Apollo's conversation.state indicated the call
was NOT done processing. This caused premature terminal classification for calls
that were still being transcribed.

FIX: transcript_store.py now checks Apollo state (via source_state in extra dict)
BEFORE age-based classification. If state is not in APOLLO_DONE_STATES, the call
gets RETRY status regardless of age.

This test verifies the fix works correctly.
"""

import sys
from pathlib import Path
from datetime import date, timedelta

# Add scripts to path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from transcript_store import build_transcript_row, UNAVAILABLE, RETRY, TERMINAL


def test_apollo_not_done_prevents_terminal_despite_old_age():
    """
    Regression test: Apollo call with state not in APOLLO_DONE_STATES should
    get RETRY, not TERMINAL, even if call_date is old (>3 days).
    """

    # Plant a NOT-done Apollo call that's 30 days old
    old_date = date.today() - timedelta(days=30)
    call_id = "test_apollo_not_done_30d_old"
    source = "apollo"

    utterances = []  # Empty utterances (no transcript yet)
    error_msg = None
    extra = {
        "participant_identities": {},
        "source_state": "transcribing"  # NOT in APOLLO_DONE_STATES
    }

    row = build_transcript_row(
        source=source,
        call_id=call_id,
        utterances=utterances,
        error=error_msg,
        call_date=old_date,
        extra=extra
    )

    assert row["transcript_quality"] == UNAVAILABLE
    reason = row.get("unavailable_reason") or ""
    assert reason.startswith(RETRY), \
        f"Expected RETRY for not-done Apollo call, got: {reason}"

    print("✅ PASS: Apollo not-done state prevents TERMINAL (age=30d, state=transcribing)")
    print(f"   Result: {reason}")


def test_apollo_done_allows_terminal_when_old():
    """
    Control test: Apollo call with state in APOLLO_DONE_STATES and old age
    should get TERMINAL classification.
    """

    old_date = date.today() - timedelta(days=30)
    call_id = "test_apollo_done_30d_old"
    source = "apollo"

    utterances = []
    error_msg = None
    extra = {
        "participant_identities": {},
        "source_state": "completed"  # In APOLLO_DONE_STATES
    }

    row = build_transcript_row(
        source=source,
        call_id=call_id,
        utterances=utterances,
        error=error_msg,
        call_date=old_date,
        extra=extra
    )

    assert row["transcript_quality"] == UNAVAILABLE
    reason = row.get("unavailable_reason") or ""
    assert reason.startswith(TERMINAL), \
        f"Expected TERMINAL for done+old Apollo call, got: {reason}"

    print("✅ PASS: Apollo done+empty+old correctly classified as TERMINAL")
    print(f"   Result: {reason}")


def test_apollo_not_done_recent_gets_retry():
    """
    Control test: Recent Apollo call that's not done should get RETRY.
    """

    recent_date = date.today() - timedelta(days=1)
    call_id = "test_apollo_not_done_recent"
    source = "apollo"

    utterances = []
    error_msg = None
    extra = {
        "participant_identities": {},
        "source_state": "transcribing"
    }

    row = build_transcript_row(
        source=source,
        call_id=call_id,
        utterances=utterances,
        error=error_msg,
        call_date=recent_date,
        extra=extra
    )

    assert row["transcript_quality"] == UNAVAILABLE
    reason = row.get("unavailable_reason") or ""
    assert reason.startswith(RETRY)

    print("✅ PASS: Recent not-done Apollo call gets RETRY")


if __name__ == "__main__":
    print("=" * 80)
    print("APOLLO TERMINAL CLASSIFICATION REGRESSION TEST")
    print("=" * 80)
    print()

    try:
        test_apollo_not_done_prevents_terminal_despite_old_age()
        print()
        test_apollo_done_allows_terminal_when_old()
        print()
        test_apollo_not_done_recent_gets_retry()
        print()
        print("=" * 80)
        print("ALL TESTS PASSED")
        print("=" * 80)
    except AssertionError as e:
        print()
        print("=" * 80)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 80)
        sys.exit(1)
    except Exception as e:
        print()
        print("=" * 80)
        print(f"❌ ERROR: {type(e).__name__}: {e}")
        print("=" * 80)
        sys.exit(1)
