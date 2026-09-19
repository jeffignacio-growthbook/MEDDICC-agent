#!/usr/bin/env python3
"""
Baseline tests for assess_call_talk_ratio() (Criterion C, Apollo-specific
pipeline fix), plus Step D's planted-discrepancy and regression tests in
the same file — same convention as test_forecast_trust.py/
test_pipeline_coverage.py.

Covers:
1. Non-Apollo source (Fireflies) -> insufficient_data/source_not_supported,
   never a fabricated ratio.
2. Apollo with no participant_identities -> insufficient_data.
3. Normal Apollo case: correct internal_talk_ratio/internal_question_share
   from a hand-verifiable worked example.
4. Bot artifacts excluded from both matched and internal totals (still
   counted in unmatched_seconds, never silently dropped).
5. Unmatched (unidentified) speakers excluded the same way.
6. PLANTED-DISCREPANCY: removing the is_bot exclusion is proven to change
   the result (the bot's seconds would wrongly count), by actually
   breaking scripts/coaching_talk_ratio.py, confirming this test fails,
   then restoring and confirming a clean pass.
7. REGRESSION: a non-Apollo source must NEVER produce a numeric ratio —
   the single most important guard here, since name-matching (the
   already-failed approach) must never be silently reintroduced for
   another source. Verified the same way: plant the regression, confirm
   the test fails, restore, confirm it passes.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from coaching_talk_ratio import assess_call_talk_ratio


def _apollo_row(talk_time, question_count, total_speech, identities):
    return {
        "source": "apollo",
        "talk_time_seconds": talk_time,
        "question_count": question_count,
        "total_speech_seconds": total_speech,
        "participant_identities": identities,
    }


def test_fireflies_source_returns_insufficient_data():
    """Fireflies has no equivalent identity mechanism (confirmed live) —
    must return insufficient_data/source_not_supported, never a ratio."""
    print("\n[TEST] Fireflies source -> insufficient_data/source_not_supported")

    row = {
        "source": "fireflies",
        "talk_time_seconds": {"Ann": 100.0, "Bob": 50.0},
        "question_count": {"Ann": 3},
        "total_speech_seconds": 150.0,
    }
    result = assess_call_talk_ratio(row)

    if result.get("status") != "insufficient_data":
        raise AssertionError(f"Expected status='insufficient_data', got {result!r}")
    if result.get("reason") != "source_not_supported":
        raise AssertionError(f"Expected reason='source_not_supported', got {result!r}")
    if "internal_talk_ratio" in result:
        raise AssertionError(
            f"Fireflies row must never carry a numeric ratio, got: {result!r}")
    if "Apollo" not in result["note"]:
        raise AssertionError(f"Expected note to explain the Apollo-only limitation, "
                             f"got: {result['note']!r}")
    print("  ✓ Fireflies correctly gated, no ratio fabricated")


def test_apollo_no_identities_returns_insufficient_data():
    print("\n[TEST] Apollo with no participant_identities -> insufficient_data")

    row = _apollo_row({"p1": 100.0}, {}, 100.0, {})
    result = assess_call_talk_ratio(row)

    if result.get("status") != "insufficient_data":
        raise AssertionError(f"Expected insufficient_data, got {result!r}")
    if result.get("reason") != "no_participant_identities":
        raise AssertionError(f"Expected reason='no_participant_identities', got {result!r}")
    print("  ✓ Missing participant_identities correctly gated")


def test_normal_apollo_case_computes_correct_ratio():
    """Hand-verifiable worked example: rep (internal) talks 30s of 100s
    total, asks 1 of 4 total questions; prospect (external) talks 70s,
    asks 3 questions."""
    print("\n[TEST] Normal Apollo case — correct internal_talk_ratio/question_share")

    identities = {
        "rep1": {"name": "Rep", "email": "rep@growthbook.io", "title": None,
                 "account_id": None, "is_internal": True, "is_bot": False},
        "prospect1": {"name": "Prospect", "email": "prospect@acme.com",
                      "title": None, "account_id": None,
                      "is_internal": False, "is_bot": False},
    }
    row = _apollo_row(
        talk_time={"rep1": 30.0, "prospect1": 70.0},
        question_count={"rep1": 1, "prospect1": 3},
        total_speech=100.0,
        identities=identities,
    )
    result = assess_call_talk_ratio(row)

    if result.get("status") != "ok":
        raise AssertionError(f"Expected status='ok', got {result!r}")
    if result["internal_talk_ratio"] != 0.3:
        raise AssertionError(f"Expected internal_talk_ratio=0.3, got {result['internal_talk_ratio']}")
    if result["internal_question_share"] != 0.25:
        raise AssertionError(
            f"Expected internal_question_share=0.25 (1/4), got {result['internal_question_share']}")
    if result["matched_seconds"] != 100.0:
        raise AssertionError(f"Expected matched_seconds=100.0, got {result['matched_seconds']}")
    if result["unmatched_seconds"] != 0.0:
        raise AssertionError(f"Expected unmatched_seconds=0.0, got {result['unmatched_seconds']}")
    if "DIAGNOSTIC ONLY" not in result["note"]:
        raise AssertionError(f"Expected the permanent diagnostic-only label in note, "
                             f"got: {result['note']!r}")
    print(f"  ✓ internal_talk_ratio={result['internal_talk_ratio']}, "
          f"internal_question_share={result['internal_question_share']}")


def test_bot_and_unmatched_speakers_excluded_not_dropped():
    """A bot artifact and a genuinely unmatched speaker must both be
    excluded from matched_seconds/internal totals, but their seconds
    must still surface in unmatched_seconds — never silently vanish."""
    print("\n[TEST] Bot artifacts and unmatched speakers excluded, not silently dropped")

    identities = {
        "rep1": {"name": "Rep", "email": "rep@growthbook.io", "title": None,
                 "account_id": None, "is_internal": True, "is_bot": False},
        "bot1": {"name": "Fireflies.ai Notetaker Rep", "email": None,
                 "title": None, "account_id": None,
                 "is_internal": False, "is_bot": True},
        # "unknown1" deliberately has NO entry in identities at all.
    }
    row = _apollo_row(
        talk_time={"rep1": 40.0, "bot1": 10.0, "unknown1": 50.0},
        question_count={"rep1": 2},
        total_speech=100.0,
        identities=identities,
    )
    result = assess_call_talk_ratio(row)

    if result.get("status") != "ok":
        raise AssertionError(f"Expected status='ok', got {result!r}")
    if result["matched_seconds"] != 40.0:
        raise AssertionError(
            f"Expected matched_seconds=40.0 (bot + unknown excluded), "
            f"got {result['matched_seconds']}")
    if result["internal_talk_ratio"] != 0.4:
        raise AssertionError(f"Expected internal_talk_ratio=0.4, got {result['internal_talk_ratio']}")
    if result["unmatched_seconds"] != 60.0:
        raise AssertionError(
            f"Expected unmatched_seconds=60.0 (bot's 10 + unknown's 50, "
            f"surfaced not dropped), got {result['unmatched_seconds']}")
    print(f"  ✓ Bot (10s) and unmatched (50s) excluded from matched/internal, "
          f"surfaced in unmatched_seconds={result['unmatched_seconds']}")


def test_planted_discrepancy_bot_exclusion_is_load_bearing():
    """PLANTED-DISCREPANCY PROOF: temporarily remove the is_bot exclusion
    from the real source file, confirm the previous test's assertion
    actually fails against the broken code, then restore and confirm a
    clean pass. Proves the bot exclusion is load-bearing, not vacuous."""
    print("\n[TEST] Planted discrepancy: bot exclusion is actually load-bearing")

    source_path = Path(__file__).parent / "coaching_talk_ratio.py"
    original = source_path.read_text()
    broken = original.replace(
        "if not ident or ident.get(\"is_bot\"):",
        "if not ident:",
    )
    if broken == original:
        raise AssertionError(
            "Test setup error: the exclusion line to plant-break wasn't found "
            "in coaching_talk_ratio.py — this test no longer matches the source")

    caught = False
    try:
        source_path.write_text(broken)
        # Force a fresh import of the broken module.
        sys.modules.pop("coaching_talk_ratio", None)
        from coaching_talk_ratio import assess_call_talk_ratio as broken_assess

        identities = {
            "rep1": {"name": "Rep", "email": "rep@growthbook.io", "title": None,
                     "account_id": None, "is_internal": True, "is_bot": False},
            "bot1": {"name": "Fireflies.ai Notetaker Rep", "email": None,
                     "title": None, "account_id": None,
                     "is_internal": False, "is_bot": True},
        }
        row = _apollo_row(
            talk_time={"rep1": 40.0, "bot1": 10.0},
            question_count={"rep1": 2},
            total_speech=50.0,
            identities=identities,
        )
        broken_result = broken_assess(row)
        try:
            if broken_result["matched_seconds"] != 40.0:
                raise AssertionError(
                    f"Expected matched_seconds=40.0 (bot excluded), "
                    f"got {broken_result['matched_seconds']}")
        except AssertionError:
            caught = True
    finally:
        source_path.write_text(original)
        sys.modules.pop("coaching_talk_ratio", None)

    if not caught:
        raise AssertionError(
            "Planted removal of the is_bot exclusion was NOT caught — the bot "
            "exclusion in test_bot_and_unmatched_speakers_excluded_not_dropped "
            "is not actually load-bearing")
    print("  ✓ Planted removal of is_bot exclusion was correctly caught "
          "(bot's 10s wrongly counted as matched_seconds=50.0)")

    # Confirm the restore is clean.
    from coaching_talk_ratio import assess_call_talk_ratio as restored_assess
    identities = {
        "rep1": {"name": "Rep", "email": "rep@growthbook.io", "title": None,
                 "account_id": None, "is_internal": True, "is_bot": False},
        "bot1": {"name": "Fireflies.ai Notetaker Rep", "email": None,
                 "title": None, "account_id": None,
                 "is_internal": False, "is_bot": True},
    }
    row = _apollo_row({"rep1": 40.0, "bot1": 10.0}, {"rep1": 2}, 50.0, identities)
    restored_result = restored_assess(row)
    if restored_result["matched_seconds"] != 40.0:
        raise AssertionError(
            f"Restore did not clean up correctly — expected matched_seconds=40.0, "
            f"got {restored_result['matched_seconds']}")
    print("  ✓ Restored source confirmed clean")


def test_regression_non_apollo_source_never_produces_a_ratio():
    """THE MOST IMPORTANT TEST IN THIS BATCH.

    A non-Apollo source (Fireflies, Gong, or any future source) must
    NEVER produce a numeric internal_talk_ratio — the name-matching
    approach that already failed its own reliability bar must never be
    silently reintroduced for a source without the exact-ID bridge.
    Verified by actually planting the regression (removing the source
    gate) and confirming this test catches it before restoring.
    """
    print("\n[TEST] Regression guard: non-Apollo source can never produce a ratio")

    source_path = Path(__file__).parent / "coaching_talk_ratio.py"
    original = source_path.read_text()
    broken = original.replace(
        'if source != "apollo":\n        return {\n            "status": "insufficient_data",\n            "reason": "source_not_supported",',
        'if False:\n        return {\n            "status": "insufficient_data",\n            "reason": "source_not_supported",',
    )
    if broken == original:
        raise AssertionError(
            "Test setup error: the source gate to plant-break wasn't found — "
            "this test no longer matches the source")

    caught = False
    try:
        source_path.write_text(broken)
        sys.modules.pop("coaching_talk_ratio", None)
        from coaching_talk_ratio import assess_call_talk_ratio as broken_assess

        # Deliberately gives this Fireflies row a populated
        # participant_identities dict — a hypothetical future bug (or a
        # copy-paste from an Apollo code path) — so that with ONLY the
        # source gate removed, nothing else stops a ratio being computed.
        # A Fireflies row would never actually carry this in production
        # (migration 065 — Apollo-only), but the test must prove the
        # SOURCE CHECK ITSELF is load-bearing, not rely on a second,
        # coincidental empty-identities guard to save it.
        fireflies_row = {
            "source": "fireflies",
            "talk_time_seconds": {"Ann": 100.0, "Bob": 50.0},
            "question_count": {"Ann": 3, "Bob": 1},
            "total_speech_seconds": 150.0,
            "participant_identities": {
                "Ann": {"name": "Ann", "email": "ann@growthbook.io",
                        "title": None, "account_id": None,
                        "is_internal": True, "is_bot": False},
                "Bob": {"name": "Bob", "email": "bob@prospect.com",
                        "title": None, "account_id": None,
                        "is_internal": False, "is_bot": False},
            },
        }
        broken_result = broken_assess(fireflies_row)
        try:
            if broken_result.get("status") == "ok" or "internal_talk_ratio" in broken_result:
                raise AssertionError(
                    "REGRESSION: a Fireflies-sourced call produced a numeric "
                    f"result with the source gate removed: {broken_result!r}")
        except AssertionError:
            caught = True
    finally:
        source_path.write_text(original)
        sys.modules.pop("coaching_talk_ratio", None)

    if not caught:
        raise AssertionError(
            "Planted removal of the source gate was NOT caught — this "
            "regression guard is not actually load-bearing")
    print("  ✓ Planted removal of the source gate was correctly caught")

    from coaching_talk_ratio import assess_call_talk_ratio as restored_assess
    restored_result = restored_assess({
        "source": "fireflies",
        "talk_time_seconds": {"Ann": 100.0},
        "total_speech_seconds": 100.0,
    })
    if restored_result.get("status") != "insufficient_data":
        raise AssertionError("Restore did not clean up correctly")
    print("  ✓ Restored source confirmed clean")


def main():
    tests = [
        test_fireflies_source_returns_insufficient_data,
        test_apollo_no_identities_returns_insufficient_data,
        test_normal_apollo_case_computes_correct_ratio,
        test_bot_and_unmatched_speakers_excluded_not_dropped,
        test_planted_discrepancy_bot_exclusion_is_load_bearing,
        test_regression_non_apollo_source_never_produces_a_ratio,
    ]

    failed = []
    for test in tests:
        try:
            test()
        except Exception as e:
            failed.append((test.__name__, str(e)))
            print(f"\n  ❌ FAILED: {e}")

    print("\n" + "=" * 70)
    print("TEST SUMMARY")
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

    print("\n✅ All assess_call_talk_ratio() baseline tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
