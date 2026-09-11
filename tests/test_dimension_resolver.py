"""
Regression tests for the 2026-09-11 proactive dimension-resolution
primitive: every dimension-related bug this week was caught reactively,
after the model already guessed. The worst instance was a fabrication —
the model asserted "EMEA isn't a tracked region" (paraphrased from the
incident description this fix was written from; the literal transcript
wasn't pasted into this task, so EMEA_FABRICATION_CLAIM below is a
reconstruction of the reported claim shape, not captured log text) —
when EMEA has been a real, governed region value the whole time.

resolve_dimension_filter() and scan_question_for_known_dimension_terms()
(api/dimension_resolver.py) close this class of bug structurally: the
exact filter clause for a term like "EMEA" is looked up against the
governed config (regions.yaml, client.yaml's segmentation and team
roster) BEFORE the model ever gets a chance to guess — including in a
fabrication direction, since the resolver either returns a real answer
or an explicit "ambiguous"/"unknown_value", never silence a model could
mistake for "this doesn't exist."

The existing reactive gate (dimension_verification.verify_dimension_
coverage) is unchanged and still runs as a backstop.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.dimension_resolver import (
    resolve_dimension_filter,
    scan_question_for_known_dimension_terms,
    format_dimension_resolution_note,
)

# Reconstructed from the incident description (see module docstring) —
# not a literal captured transcript. What matters for this test is the
# claim's SHAPE (asserting a real, governed region doesn't exist), which
# the description states precisely.
EMEA_FABRICATION_CLAIM = "EMEA isn't a tracked region in this system."


def test_emea_resolves_correctly_before_any_query_runs():
    """The core fix: EMEA must resolve to a real filter clause via pure
    config lookup — no DB call, no LLM call, nothing for the model to
    guess or fabricate an answer about. This makes the reported
    "EMEA isn't a tracked region" claim structurally impossible: the
    resolver would have told the caller the exact opposite before any
    tool call, or any model reasoning about the question, ever happened."""
    result = resolve_dimension_filter("EMEA")
    assert "error" not in result, (
        f"EMEA must resolve, not error — got {result!r}. If this fails, "
        f"the fabrication ('EMEA isn't a tracked region') becomes "
        f"possible again, because nothing tells the model the real "
        f"answer before it reasons about the question itself."
    )
    assert result == {"column": "region", "operator": "eq", "value": "EMEA"}
    print("✓ EMEA resolves to region.eq.EMEA via pure config lookup — "
          "the fabrication this closes had nothing to be caught, "
          "because the answer was never in doubt in the first place")


def test_emea_resolution_is_case_insensitive_on_direct_lookup():
    for variant in ("emea", "Emea", "EMEA", "eMeA"):
        result = resolve_dimension_filter(variant)
        assert result == {"column": "region", "operator": "eq", "value": "EMEA"}, (
            f"variant {variant!r} must resolve identically to canonical EMEA"
        )
    print("✓ EMEA resolves identically regardless of how the model or user cased it")


def test_scan_surfaces_emea_from_the_original_incident_question_shape():
    """The exact question shape from this session's recurring incident:
    'which enterprise deals changed stage in the last 2 weeks in EMEA'.
    Both EMEA (region) and enterprise (segment, lowercase as commonly
    phrased) must be found and resolved — proactively, before any tool
    call."""
    question = "which enterprise deals changed stage in the last 2 weeks in EMEA"
    resolved = scan_question_for_known_dimension_terms(question)
    by_column = {r["column"]: r for r in resolved}

    assert "region" in by_column and by_column["region"]["value"] == "EMEA", (
        f"EMEA must be found by the proactive scan — got {resolved!r}"
    )
    assert "segment" in by_column and by_column["segment"]["value"] == "Enterprise", (
        f"'enterprise' (lowercase, as commonly phrased) must resolve to "
        f"segment=Enterprise — got {resolved!r}"
    )

    note = format_dimension_resolution_note(resolved)
    assert "region.eq.EMEA" in note
    assert "segment.eq.Enterprise" in note
    print("✓ the proactive scan finds and resolves both EMEA and "
          "'enterprise' from the exact recurring incident question shape")


def test_ambiguous_rep_first_name_returns_candidates_not_a_guess():
    """Two team members share the first name 'Jake' (Jake Stangl, Jake
    H) — resolving 'Jake' alone must surface both as candidates, never
    silently pick one. This is the real, present ambiguity in the
    roster config, not a hypothetical."""
    result = resolve_dimension_filter("Jake")
    assert result.get("error") == "ambiguous", (
        f"expected an ambiguous error for a shared first name — got {result!r}"
    )
    matched_names = {c["matched_name"] for c in result["candidates"]}
    assert matched_names == {"Jake Stangl", "Jake H"}, (
        f"both Jakes on the roster must appear as candidates — got {matched_names}"
    )
    for candidate in result["candidates"]:
        assert candidate["column"] == "owner_email"
        assert candidate["operator"] == "eq"
    print("✓ a shared first name ('Jake') returns both candidates as an "
          "ambiguous error, never a silent guess at which rep was meant")


def test_ambiguous_terms_are_not_injected_into_the_proactive_scan():
    """The scan must not turn an ambiguous term into a false-confidence
    directive — injecting 'use owner_email=eq.jake@growthbook.io' when
    the question could mean either Jake would just relocate the guess
    from the model to this function."""
    question = "how many deals is Jake working this quarter"
    resolved = scan_question_for_known_dimension_terms(question)
    assert not any(r["term"].lower() == "jake" for r in resolved), (
        "an ambiguous term must not appear as a resolved directive in the scan"
    )
    print("✓ an ambiguous rep name is never silently injected as a resolved directive")


def test_unambiguous_full_name_resolves_via_scan():
    question = "what's the pipeline for Scott Keller this month"
    resolved = scan_question_for_known_dimension_terms(question)
    owner_matches = [r for r in resolved if r["column"] == "owner_email"]
    assert len(owner_matches) == 1
    assert owner_matches[0]["value"] == "scott.keller@growthbook.io"
    print("✓ an unambiguous full name ('Scott Keller') resolves correctly via the proactive scan")


def test_unknown_term_reports_known_values_not_a_bare_failure():
    result = resolve_dimension_filter("Bananas")
    assert result.get("error") == "unknown_value"
    assert "EMEA" in result["known_values"]
    assert "Enterprise" in result["known_values"]
    print("✓ an unrecognized term reports the known values actually configured, not a bare failure")


def test_common_word_collisions_are_not_injected_by_the_scan():
    """'ROW' (the region) and 'Unknown' (the segment) are also ordinary
    English words. A question that merely contains "row" or "unknown"
    in a sentence must not trigger a false dimension directive — the
    asymmetry matters here specifically because this scan PROACTIVELY
    tells the model what to do, so a false positive actively misdirects
    the query rather than just failing a downstream check."""
    question = "is there a data quality issue in a row of records with unknown owner this week"
    resolved = scan_question_for_known_dimension_terms(question)
    assert not any(r["column"] == "region" and r["value"] == "ROW" for r in resolved), (
        "the common word 'row' must not be mistaken for the ROW region"
    )
    assert not any(r["column"] == "segment" and r["value"] == "Unknown" for r in resolved), (
        "the common word 'unknown' must not be mistaken for the Unknown segment"
    )
    print("✓ common-English-word collisions (ROW region, Unknown segment) "
          "are not injected by the proactive scan")


def test_mid_market_resolves_with_or_without_the_hyphen():
    assert resolve_dimension_filter("Mid-Market") == {
        "column": "segment", "operator": "eq", "value": "Mid-Market"}
    assert resolve_dimension_filter("mid market") == {
        "column": "segment", "operator": "eq", "value": "Mid-Market"}
    print("✓ 'Mid-Market' resolves the same with or without the hyphen/casing")


def test_format_dimension_resolution_note_is_empty_when_nothing_resolves():
    assert format_dimension_resolution_note([]) == ""
    question_with_nothing = "how is pipeline trending this quarter"
    resolved = scan_question_for_known_dimension_terms(question_with_nothing)
    assert format_dimension_resolution_note(resolved) == ""
    print("✓ a question with no known dimension terms produces no directive text")


if __name__ == "__main__":
    test_emea_resolves_correctly_before_any_query_runs()
    test_emea_resolution_is_case_insensitive_on_direct_lookup()
    test_scan_surfaces_emea_from_the_original_incident_question_shape()
    test_ambiguous_rep_first_name_returns_candidates_not_a_guess()
    test_ambiguous_terms_are_not_injected_into_the_proactive_scan()
    test_unambiguous_full_name_resolves_via_scan()
    test_unknown_term_reports_known_values_not_a_bare_failure()
    test_common_word_collisions_are_not_injected_by_the_scan()
    test_mid_market_resolves_with_or_without_the_hyphen()
    test_format_dimension_resolution_note_is_empty_when_nothing_resolves()
    print("\n✅ All tests passed")
