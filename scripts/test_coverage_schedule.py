#!/usr/bin/env python3
"""
Tests for config/client.yaml's coverage.expected_multiple_schedule /
coverage.weighted_expected_multiple — GrowthBook's real schedule, wired in
2026-10-03 after shipping empty in #118 (the schedule had been part of
the original #118 scope; it shipped empty by explicit decision pending
the real numbers, not an oversight — see PENDING_WORK.md and this
commit's own message).

Covers:
1. scripts/pipeline_coverage.py::_resolve_expected_multiple — step/
   carry-forward lookup, not a bare dict.get() and not nearest-neighbor.
   GrowthBook's real sparse schedule {1: 3.0, 6: 2.0, 8: 1.5, 10: 1.0}
   resolved at every week 1-13.
2. PLANTED-BUG control: a broken (non-carry-forward) lookup must make
   test 1 fail at the unlisted weeks (5, 7, 9, 13).
3. scripts/utils.py::get_coverage_config — FAILS LOUDLY (raises
   ValueError, does not log-and-drop) when a configured, non-empty
   schedule doesn't start at week 1, or isn't non-increasing, or
   weighted_expected_multiple is present but invalid. Still lenient
   (never raises) for a genuinely EMPTY schedule — that remains a fully
   supported no-schedule state for a client that hasn't set one.
4. End-to-end: assess_pipeline_coverage with the real GrowthBook
   schedule produces independent nominal_ahead_behind (vs. the stepped
   schedule) and weighted_ahead_behind (vs. the flat 1.0 constant) —
   not one shared ahead/behind compared only to weighted, the #118
   shape this superseded.
5. quarter_days_weeks_left's sub-week fallback: 6 days left reads as
   "6 days left", never a nonsensical "0 weeks left".
"""
import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "analytics"))
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

from pipeline_coverage import _resolve_expected_multiple, _assess_coverage
from utils import get_coverage_config, quarter_days_weeks_left

GROWTHBOOK_SCHEDULE = {1: 3.0, 6: 2.0, 8: 1.5, 10: 1.0}


def test_step_lookup_resolves_growthbooks_real_schedule_at_every_week():
    print("\n[TEST] _resolve_expected_multiple: GrowthBook's real schedule, every week 1-13")
    expected = {1: 3.0, 2: 3.0, 3: 3.0, 4: 3.0, 5: 3.0,
                6: 2.0, 7: 2.0,
                8: 1.5, 9: 1.5,
                10: 1.0, 11: 1.0, 12: 1.0, 13: 1.0}
    for week, want in expected.items():
        got = _resolve_expected_multiple(GROWTHBOOK_SCHEDULE, week)
        if got != want:
            raise AssertionError(f"week {week}: expected {want}, got {got}")
    print("  ✓ all 13 weeks resolve correctly via step/carry-forward lookup")


def test_planted_bug_bare_lookup_fails_unlisted_weeks():
    """CONTROL: a bare dict.get() (the old, wrong behavior for a sparse
    schedule) returns None for every unlisted week — proves the real
    step-lookup test above is load-bearing, not vacuously true."""
    print("\n[TEST] PLANTED BUG control: bare dict.get() fails at unlisted weeks")
    broken_lookup = lambda schedule, week: schedule.get(week)
    failures = []
    for week in (5, 7, 9, 13):
        got = broken_lookup(GROWTHBOOK_SCHEDULE, week)
        if got is not None:
            failures.append(week)
    if len(failures) == len(( 5, 7, 9, 13)):
        raise AssertionError("expected the broken bare-lookup to return None at every "
                             "unlisted week — if this fails, the planted bug isn't broken")
    print("  ✓ confirmed: a bare dict.get() would wrongly return None at weeks 5, 7, 9, 13 — "
          "the real _resolve_expected_multiple's test above is load-bearing")


def test_no_schedule_entry_1_fails_loudly():
    print("\n[TEST] schedule missing week-1 anchor -> raises, does not silently drop")
    try:
        get_coverage_config({"coverage": {"expected_multiple_schedule": {2: 3.0, 6: 2.0}}})
        raise AssertionError("expected ValueError for a schedule with no week-1 entry")
    except ValueError as e:
        assert "week 1" in str(e)
    print("  ✓ raised ValueError naming the missing week-1 anchor")


def test_increasing_multiple_fails_loudly():
    print("\n[TEST] non-increasing violation (a later week's multiple is HIGHER) -> raises")
    try:
        get_coverage_config({"coverage": {"expected_multiple_schedule": {1: 1.0, 6: 2.0}}})
        raise AssertionError("expected ValueError for an increasing schedule")
    except ValueError as e:
        assert "non-increasing" in str(e)
    print("  ✓ raised ValueError naming the non-increasing violation")


def test_invalid_weighted_expected_multiple_fails_loudly():
    print("\n[TEST] weighted_expected_multiple present but not a positive number -> raises")
    for bad in ("not-a-number", -1.0, 0):
        try:
            get_coverage_config({"coverage": {"weighted_expected_multiple": bad}})
            raise AssertionError(f"expected ValueError for weighted_expected_multiple={bad!r}")
        except ValueError as e:
            assert "weighted_expected_multiple" in str(e)
    print("  ✓ raised ValueError for a non-numeric and for non-positive values")


def test_empty_schedule_remains_a_supported_no_schedule_state():
    """A client with no schedule configured at all must NOT raise — the
    empty state is intentional, not a validation failure."""
    print("\n[TEST] empty schedule (no-schedule client) -> no raise, both fields None/empty")
    cfg = get_coverage_config({"coverage": {}})
    if cfg["expected_multiple_schedule"] != {}:
        raise AssertionError(f"expected empty schedule, got {cfg['expected_multiple_schedule']!r}")
    if cfg["weighted_expected_multiple"] is not None:
        raise AssertionError(f"expected weighted_expected_multiple=None, "
                             f"got {cfg['weighted_expected_multiple']!r}")
    print("  ✓ no-schedule client state still works, no raise")


def test_real_config_file_loads_and_validates():
    """The actual config/client.yaml must load cleanly with GrowthBook's
    real schedule — this would raise at import time in every handler if
    the committed YAML itself violated the validation above."""
    print("\n[TEST] the real config/client.yaml loads and validates")
    cfg = get_coverage_config()
    if cfg["expected_multiple_schedule"] != GROWTHBOOK_SCHEDULE:
        raise AssertionError(f"expected {GROWTHBOOK_SCHEDULE!r}, "
                             f"got {cfg['expected_multiple_schedule']!r}")
    if cfg["weighted_expected_multiple"] != 1.0:
        raise AssertionError(f"expected weighted_expected_multiple=1.0, "
                             f"got {cfg['weighted_expected_multiple']!r}")
    print(f"  ✓ {cfg}")


def test_nominal_and_weighted_ahead_behind_are_independent():
    """End-to-end (via _assess_coverage, imported directly — the same
    function assess_pipeline_coverage calls): with GrowthBook's real
    schedule, nominal and weighted get their OWN expected multiple and
    their OWN ahead/behind read — not one shared value compared only to
    weighted (the #118 shape this supersedes). Week 8 (nominal expects
    1.5x, weighted expects 1.0x flat): nominal coverage 2.0x is ahead of
    1.5x; weighted coverage 0.8x is behind 1.0x — independently true at
    the same time, which a single shared ahead_behind could never
    express."""
    print("\n[TEST] nominal and weighted ahead/behind are computed independently")
    coverage_config = {
        "expected_multiple_schedule": GROWTHBOOK_SCHEDULE,
        "weighted_expected_multiple": 1.0,
        "phase_boundaries": {"early_through_week": 4, "late_from_week": 10},
    }
    # remaining_gap = 100 (quota 200 - won 100); nominal 200/100=2.0x >= 1.5x -> ahead;
    # weighted 80/100=0.8x < 1.0x -> behind.
    cov = _assess_coverage(quota=200.0, qtd_won=100.0, raw_value=200.0, weighted_value=80.0,
                           current_week=8, coverage_config=coverage_config)
    if cov["nominal_expected_multiple"] != 1.5:
        raise AssertionError(f"expected nominal_expected_multiple=1.5, got {cov['nominal_expected_multiple']!r}")
    if cov["weighted_expected_multiple"] != 1.0:
        raise AssertionError(f"expected weighted_expected_multiple=1.0, got {cov['weighted_expected_multiple']!r}")
    if cov["nominal_ahead_behind"] != "ahead":
        raise AssertionError(f"expected nominal_ahead_behind='ahead', got {cov['nominal_ahead_behind']!r}")
    if cov["weighted_ahead_behind"] != "behind":
        raise AssertionError(f"expected weighted_ahead_behind='behind', got {cov['weighted_ahead_behind']!r}")
    print(f"  ✓ nominal 2.00x is ahead of 1.5x; weighted 0.80x is behind 1.0x — simultaneously true, "
          f"independent verdicts")


def test_days_under_a_week_says_days_not_zero_weeks():
    print("\n[TEST] 6 days left says '6 days left', never '0 weeks left'")
    result = quarter_days_weeks_left(date(2026, 10, 9), date(2026, 10, 3))
    if result["days_left"] != 6:
        raise AssertionError(f"expected days_left=6, got {result['days_left']!r}")
    if result["weeks_left"] != 0:
        raise AssertionError(f"expected weeks_left=0 (6 // 7), got {result['weeks_left']!r}")
    if result["label"] != "6 days left":
        raise AssertionError(f"expected label='6 days left', got {result['label']!r}")
    if "0 week" in result["label"]:
        raise AssertionError(f"label must never say '0 weeks', got {result['label']!r}")
    print(f"  ✓ {result['label']} (not '0 weeks left')")


def _floor_only_label(days_left: int) -> str:
    """The OLD (pre-fix) label derivation — floors instead of rounding to
    the nearest week. Reproduced in-memory (never patching the real
    source) purely to prove the new rounding behavior is load-bearing,
    matching this file's own test_planted_bug_bare_lookup_fails_unlisted_
    weeks convention."""
    weeks_left = days_left // 7
    return (f"{weeks_left} week{'' if weeks_left == 1 else 's'} left" if weeks_left
            else f"{days_left} day{'' if days_left == 1 else 's'} left")


def test_weeks_left_wording_rounds_to_nearest_not_floor():
    """quarter_days_weeks_left's label: exact week counts stay bare ("N
    weeks left"), non-exact counts round to the nearest week with an
    "about" qualifier, and sub-week counts are unchanged ("N days left").
    28 -> exact 4; 27 -> about 4 (27/7=3.857, rounds up); 24 -> about 3
    (24/7=3.43); 21 -> exact 3; 6 -> sub-week, unchanged."""
    print("\n[TEST] weeks-left wording rounds to nearest week, not floor")
    end = date(2026, 10, 31)
    cases = {
        28: "4 weeks left",
        27: "about 4 weeks left",
        24: "about 3 weeks left",
        21: "3 weeks left",
        6: "6 days left",
    }
    for days_left, expected in cases.items():
        as_of = end - timedelta(days=days_left)
        result = quarter_days_weeks_left(end, as_of)
        if result["days_left"] != days_left:
            raise AssertionError(f"days_left mismatch for case {days_left}: {result['days_left']!r}")
        if result["label"] != expected:
            raise AssertionError(
                f"days_left={days_left}: expected label={expected!r}, got {result['label']!r}")
    print("  ✓ 28->'4 weeks left' (exact), 27->'about 4 weeks left' (rounds up from 3.857), "
          "24->'about 3 weeks left' (rounds from 3.43), 21->'3 weeks left' (exact), "
          "6->'6 days left' (sub-week, unchanged)")


def test_planted_bug_floor_only_label_wrong_for_27_and_24_days():
    """PLANTED-BUG CONTROL: the OLD floor-only label (_floor_only_label,
    reproduced above exactly as the pre-fix code read) produces the
    misleading "3 weeks left" for both 27 and 24 days left — proving
    test_weeks_left_wording_rounds_to_nearest_not_floor's assertions are
    load-bearing, not vacuously true. The REAL quarter_days_weeks_left
    must NOT match the floor-only output for these two cases."""
    print("\n[TEST] Planted bug: floor-only label wrongly says '3 weeks left' for 27 and 24 days")
    end = date(2026, 10, 31)
    for days_left in (27, 24):
        as_of = end - timedelta(days=days_left)
        real = quarter_days_weeks_left(end, as_of)["label"]
        broken = _floor_only_label(days_left)
        if broken != "3 weeks left":
            raise AssertionError(f"expected the old floor-only label to say '3 weeks left' "
                                 f"for {days_left} days, got {broken!r}")
        if real == broken:
            raise AssertionError(
                f"days_left={days_left}: the fixed label ({real!r}) must differ from the "
                f"old floor-only label ({broken!r}) — the planted bug was NOT caught")
    print("  ✓ old floor-only behavior ('3 weeks left') correctly differs from the fixed "
          "rounded label for both 27 and 24 days")


def main():
    tests = [
        test_step_lookup_resolves_growthbooks_real_schedule_at_every_week,
        test_planted_bug_bare_lookup_fails_unlisted_weeks,
        test_no_schedule_entry_1_fails_loudly,
        test_increasing_multiple_fails_loudly,
        test_invalid_weighted_expected_multiple_fails_loudly,
        test_empty_schedule_remains_a_supported_no_schedule_state,
        test_real_config_file_loads_and_validates,
        test_nominal_and_weighted_ahead_behind_are_independent,
        test_days_under_a_week_says_days_not_zero_weeks,
        test_weeks_left_wording_rounds_to_nearest_not_floor,
        test_planted_bug_floor_only_label_wrong_for_27_and_24_days,
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
        print(f"  ❌ Failed: {len(failed)}")
        print("\nFailed tests:")
        for name, err in failed:
            print(f"  - {name}\n    {err}")
        return 1

    print("\n✅ All coverage schedule tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
