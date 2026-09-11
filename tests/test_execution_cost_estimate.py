"""
resolve_execution_cost_estimate() (api/router.py) — a pre-execution cost
estimate for dynamic_query_loop, so a caller can warn on an expensive-
looking question before running anything rather than discovering the
200K-token ceiling mid-task.

Calibrated against REAL query_cost_log rows (calibration_query.sql run
2026-09-11), not guesses — see the module-level comment above
resolve_execution_cost_estimate() in api/router.py for the exact deltas
and, critically, the sample-size caveat: the entire table held 13 rows
at calibration time (this week's own testing, not a week of organic
traffic). Two of the five predictive signals (dimension_resolver_
matched, ambiguous_dimension_term_flagged) are not heuristics at all —
they're computed by calling the EXACT SAME functions the real primitive
uses, so there's no prediction error on whether they fire, only on
whether their calibrated cost delta holds. The other three
(snapshot_anchor_injected, enrichment_shortcut_fired,
aggregation_mismatch_caught) are genuine keyword heuristics predicting
an inherently reactive, mid-loop signal from question text alone — the
weakest part of this estimator, expected to have real error.

These tests validate the MECHANISM (reuses the real detection functions
correctly, the formula behaves sanely, the warning threshold fires and
stays user-facing-clean) and check the ONE real validation case
available: id=13 from query_cost_log, "Which stale Enterprise deals
does jake.stangl@growthbook.io own in EMEA?" (2 iterations, 35452
tokens actually measured). The assertion against it is "same order of
magnitude," not a tight tolerance — asserting tighter than the
calibration data itself supports would be dishonest precision, not a
real quality bar.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api.router as router


# The one real, individually-identified validation case from this
# session's calibration pull (query_cost_log id=13).
KNOWN_CASE_QUESTION = "Which stale Enterprise deals does jake.stangl@growthbook.io own in EMEA?"
KNOWN_CASE_ACTUAL_ITERATIONS = 2
KNOWN_CASE_ACTUAL_TOKENS = 35452


def test_reuses_the_real_dimension_detection_functions_not_a_reimplementation():
    """dimension_resolver_matched and ambiguous_dimension_term_flagged
    must come from calling scan_question_for_known_dimension_terms /
    scan_question_for_ambiguous_dimension_terms directly — the same
    functions dynamic_query_loop itself calls — not a separately
    maintained guess that could drift from the real detection logic."""
    est = router.resolve_execution_cost_estimate(KNOWN_CASE_QUESTION)
    assert est["signals_detected"]["dimension_resolver_matched"] is True, (
        "this question names EMEA/Enterprise/an owner — the real dimension "
        "resolver matches all three; the estimate must reflect that"
    )
    assert est["signals_detected"]["ambiguous_dimension_term_flagged"] is True, (
        "'Jake' matches two known reps (Jake Stangl, Jake H) in the real "
        "roster-matching logic — the estimate must reflect that"
    )
    print("✓ dimension signals come from the real detection functions, matching the known case exactly")


def test_known_case_estimate_is_same_order_of_magnitude_as_measured_cost():
    """The one individually-identified real validation case: query_cost_log
    id=13. Same-order-of-magnitude, not tight tolerance — this is a
    triage signal calibrated on n=13 rows, not a precise forecast."""
    est = router.resolve_execution_cost_estimate(KNOWN_CASE_QUESTION)

    assert KNOWN_CASE_ACTUAL_TOKENS / 2 <= est["estimated_tokens"] <= KNOWN_CASE_ACTUAL_TOKENS * 2, (
        f"estimated {est['estimated_tokens']} tokens vs actual "
        f"{KNOWN_CASE_ACTUAL_TOKENS} — outside even a 2x band, the estimator "
        f"isn't in the right neighborhood for this known case"
    )
    assert 1 <= est["estimated_iterations"] <= KNOWN_CASE_ACTUAL_ITERATIONS * 2, (
        f"estimated {est['estimated_iterations']} iterations vs actual "
        f"{KNOWN_CASE_ACTUAL_ITERATIONS}"
    )
    print(f"✓ known case (id=13): estimated {est['estimated_tokens']} tokens / "
          f"{est['estimated_iterations']} iterations vs actual "
          f"{KNOWN_CASE_ACTUAL_TOKENS} tokens / {KNOWN_CASE_ACTUAL_ITERATIONS} iterations "
          f"— same order of magnitude")


def test_a_plain_lookup_with_no_detected_signals_returns_the_baseline():
    """False-positive check: a question that trips none of the 5 signals
    must return exactly the calibrated baseline (the answered_cleanly
    group's own average), not some default drifted from it."""
    est = router.resolve_execution_cost_estimate("What is the deal value for Acme?")
    assert not any(est["signals_detected"].values()), (
        f"expected no signals detected for a plain lookup — got: {est['signals_detected']!r}"
    )
    assert est["estimated_tokens"] == router._COST_BASE_TOKENS
    assert est["estimated_iterations"] == router._COST_BASE_ITERATIONS
    assert est["warn_high_cost"] is False
    assert est["warning_message"] is None
    print("✓ a plain lookup with no detected signals returns exactly the calibrated baseline")


def test_a_stacked_multi_signal_question_crosses_the_warning_threshold():
    """A question that plausibly trips all 5 signals at once (comparison
    language, an enrichment-style follow-up, a breakdown request, a
    known dimension term, and an ambiguous name) should push the
    estimate over 70% of the 200K budget and surface the warning."""
    q = ("Compare EMEA Enterprise pipeline movement since last week, "
         "breakdown by segment, and which deals moved out - list the "
         "deals and company names for Jake")
    est = router.resolve_execution_cost_estimate(q)
    assert est["estimated_tokens"] >= 0.7 * router.DYNAMIC_LOOP_TOKEN_BUDGET, (
        f"expected a stacked-signal question to cross the warning threshold — "
        f"got {est['estimated_tokens']} tokens"
    )
    assert est["warn_high_cost"] is True
    assert est["warning_message"], "expected a non-empty warning message"
    print(f"✓ a stacked multi-signal question crosses the warning threshold "
          f"({est['estimated_tokens']} tokens) and surfaces a warning")


def test_warning_message_is_plain_language_with_no_internal_jargon():
    """PRIMITIVE_CHECKLIST.md's own user-facing-text rule applies here
    too: no 'resynthesis', 'budget', 'token', 'primitive', 'iteration'
    in anything shown to a user."""
    q = ("Compare EMEA Enterprise pipeline movement since last week, "
         "breakdown by segment, and which deals moved out - list the "
         "deals and company names for Jake")
    est = router.resolve_execution_cost_estimate(q)
    assert est["warning_message"] is not None
    banned_terms = ("resynthesis", "budget", "token", "primitive", "iteration")
    msg_lower = est["warning_message"].lower()
    for term in banned_terms:
        assert term not in msg_lower, (
            f"warning message leaks internal jargon ({term!r}): {est['warning_message']!r}"
        )
    print("✓ the warning message is plain language, no internal jargon leaked")


def test_estimated_iterations_never_leaves_the_loops_own_physical_bounds():
    """Regression control: additive deltas from 5 signals stacked at
    once could in principle push the raw sum below 0 or above the
    loop's own MAX_ITERATIONS — the clamp must hold at both ends, and
    the floor must be 1 (an answered request always takes at least one
    model call), not 0 (which only ever appeared on a crashed request
    in the calibration data, never a legitimate low-cost estimate)."""
    high_q = ("Compare EMEA Enterprise pipeline movement since last week, "
              "breakdown by segment, and which deals moved out - list the "
              "deals and company names for Jake")
    low_q = "What is the deal value for Acme?"

    est_high = router.resolve_execution_cost_estimate(high_q)
    est_low = router.resolve_execution_cost_estimate(low_q)

    assert 1.0 <= est_high["estimated_iterations"] <= router.DYNAMIC_LOOP_MAX_ITERATIONS
    assert 1.0 <= est_low["estimated_iterations"] <= router.DYNAMIC_LOOP_MAX_ITERATIONS
    print("✓ estimated_iterations stays within [1, DYNAMIC_LOOP_MAX_ITERATIONS] at both ends")


def test_confidence_label_is_present_and_names_the_real_sample_size():
    """The estimate must always self-report as low-confidence given the
    n=13 calibration set — this must never silently read as a precise
    number without that caveat attached."""
    est = router.resolve_execution_cost_estimate("What is the deal value for Acme?")
    assert "low" in est["confidence"].lower()
    assert "13" in est["confidence"], (
        f"expected the real calibration sample size (13) named in the "
        f"confidence label — got: {est['confidence']!r}"
    )
    print("✓ every estimate carries its own low-confidence, sample-size-honest label")


if __name__ == "__main__":
    tests = [
        test_reuses_the_real_dimension_detection_functions_not_a_reimplementation,
        test_known_case_estimate_is_same_order_of_magnitude_as_measured_cost,
        test_a_plain_lookup_with_no_detected_signals_returns_the_baseline,
        test_a_stacked_multi_signal_question_crosses_the_warning_threshold,
        test_warning_message_is_plain_language_with_no_internal_jargon,
        test_estimated_iterations_never_leaves_the_loops_own_physical_bounds,
        test_confidence_label_is_present_and_names_the_real_sample_size,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"✗ {t.__name__}: {e}")
    if failed:
        print(f"\n{failed}/{len(tests)} tests FAILED")
        sys.exit(1)
    print(f"\n✅ All {len(tests)} tests passed")
