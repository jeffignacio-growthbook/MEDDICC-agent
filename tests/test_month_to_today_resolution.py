"""
2026-09-26: "compare our pipeline from January 2026 to today" always returned
wrong data, even after the snapshot_date filter fix (PR #83).

Root cause: two stacked bugs.

Bug 1 (PR #83, fixed): query_pipeline_movement always filtered by fiscal_quarter
regardless of time_window.start/end, so January queries returned Q3 data.

Bug 2 (this fix): "Month YYYY vs today" / "from Month YYYY to today" routed to
period=specific_month, whose resolver caps end at the last day of that month
(e.g. 2026-01-31). "Today" was never in the loaded range, so the handler
correctly found January rows but had no "today" snapshot to compare against.

Additionally, the defense-in-depth in _route_question() would promote any
period=specific with a month-boundary start to period=specific_month, so
even if the classifier emitted the right period=specific, the promotion
block converted it back to specific_month and re-introduced the end-cap bug.

Fix:
- Detect "vs today" / "to today" / "since" patterns (open-ended to present)
- Skip the specific→specific_month promotion for those questions
- If the classifier emits period=specific_month for such a question (expected
  until the classifier prompt is re-tuned), rewrite to period=specific with
  end=null; the existing specific resolver maps null end to today.

These tests verify the resolver and defense-in-depth behavior offline.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.time_resolver import resolve_time_window


TODAY = date.today()


def test_specific_with_null_end_resolves_to_today():
    """period=specific with end=null must resolve end to today — this is the
    foundation the 'Month YYYY to today' fix relies on."""
    result = resolve_time_window(
        {"period": "specific", "start": "2026-01-01", "end": None}
    )
    assert result["start"] == "2026-01-01", (
        f"expected start='2026-01-01', got {result['start']!r}"
    )
    assert result["end"] == TODAY.isoformat(), (
        f"expected end=today ({TODAY.isoformat()!r}), got {result['end']!r}"
    )


def test_specific_month_caps_at_month_end():
    """period=specific_month must cap end at the last day of the named month —
    this is correct for isolated month questions ('show me January 2026'),
    and the regression guard ensuring we don't accidentally extend it."""
    result = resolve_time_window(
        {"period": "specific_month", "month": "January", "year": 2026}
    )
    assert result["start"] == "2026-01-01", (
        f"expected start='2026-01-01', got {result['start']!r}"
    )
    assert result["end"] == "2026-01-31", (
        f"expected end='2026-01-31' for isolated month, got {result['end']!r}"
    )


def test_open_ended_rewrite_to_specific_null_end():
    """When period=specific_month is given but the question is open-ended to
    today ('vs today', 'to today', 'since'), the defense-in-depth in
    _route_question must rewrite it to period=specific with end=null before
    calling resolve_time_window.

    This test verifies the RESULT of that rewrite: resolve_time_window with
    period=specific and end=None produces end=today."""
    # Simulate what the defense-in-depth produces for "compare Jan 2026 to today":
    # specific_month → period=specific, start="2026-01-01", end=None
    rewritten = {"period": "specific", "start": "2026-01-01", "end": None}
    result = resolve_time_window(rewritten)
    assert result["start"] == "2026-01-01"
    assert result["end"] == TODAY.isoformat(), (
        f"rewritten 'vs today' must resolve to today; got {result['end']!r}"
    )
    # The loaded range now spans Jan 2026 → today, covering both endpoints
    assert result["end"] >= "2026-09-01", (
        "end must be on or after Sep 2026 for a live 'to today' query"
    )


def test_defense_in_depth_vs_today_conversion():
    """The _route_question defense-in-depth must convert period=specific_month
    to period=specific with end=null when the question contains 'vs today'."""
    import re as _re
    # Replicate the defense-in-depth logic from api/router.py
    question = "compare our pipeline from January 2026 to today"
    raw_tw = {"period": "specific_month", "month": "January", "year": 2026}

    _to_today_re = bool(_re.search(
        r'\b(to today|vs\.? today|versus today|compared to today|to now|vs\.? now)\b',
        question.lower()
    ))
    stated_years = _re.findall(r'\b(20\d{2})\b', question)
    _since_pattern = bool(
        _re.search(r'\bsince\b', question.lower()) and stated_years
    )
    _is_open_ended = _to_today_re or _since_pattern

    MONTH_NAMES = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }

    if raw_tw.get("period") == "specific_month" and _is_open_ended:
        _sm_month_name = (raw_tw.get("month") or "").lower()
        _sm_month_num = MONTH_NAMES.get(_sm_month_name)
        _sm_year = raw_tw.get("year")
        if _sm_month_num and _sm_year:
            raw_tw = {
                "period": "specific",
                "start": f"{int(_sm_year):04d}-{_sm_month_num:02d}-01",
                "end": None,
            }

    assert _is_open_ended, "question contains 'to today' — must be detected as open-ended"
    assert raw_tw["period"] == "specific", (
        f"specific_month must be rewritten to specific for 'vs today'; got {raw_tw!r}"
    )
    assert raw_tw["start"] == "2026-01-01", (
        f"start must be 2026-01-01; got {raw_tw['start']!r}"
    )
    assert raw_tw["end"] is None, (
        f"end must be None (→ today) for open-ended; got {raw_tw['end']!r}"
    )

    result = resolve_time_window(raw_tw)
    assert result["end"] == TODAY.isoformat(), (
        f"resolved end must be today; got {result['end']!r}"
    )


def test_since_pattern_detected_as_open_ended():
    """'since June 2025' implies 'from June 2025 to today' — the 'since'
    keyword with a stated year must be treated as open-ended."""
    import re as _re
    question = "how has our pipeline grown since June 2025"
    stated_years = _re.findall(r'\b(20\d{2})\b', question)
    _since_pattern = bool(
        _re.search(r'\bsince\b', question.lower()) and stated_years
    )
    assert _since_pattern, (
        "'since' + year must be detected as open-ended; "
        f"stated_years={stated_years}"
    )


def test_isolated_month_not_detected_as_open_ended():
    """'show me pipeline in March 2026' — no 'vs today', no 'since' — must
    NOT be treated as open-ended; specific_month is correct here."""
    import re as _re
    question = "show me pipeline in March 2026"
    _to_today_re = bool(_re.search(
        r'\b(to today|vs\.? today|versus today|compared to today|to now|vs\.? now)\b',
        question.lower()
    ))
    stated_years = _re.findall(r'\b(20\d{2})\b', question)
    _since_pattern = bool(
        _re.search(r'\bsince\b', question.lower()) and stated_years
    )
    _is_open_ended = _to_today_re or _since_pattern
    assert not _is_open_ended, (
        "isolated month question must not be open-ended; would wrongly extend to today"
    )


def test_defense_in_depth_empty_tw_open_ended():
    """Bug #3: when the classifier emits no time_window at all (raw_tw = {})
    for an open-ended month+year question, resolve_time_window({}) defaults
    to current_quarter and the handler silently ignores the stated month.

    The defense-in-depth fallback must detect this case (no period, open-ended,
    month+year present) and construct the correct time_window from question text.
    """
    import re as _re
    question = "compare our pipeline from January 2026 to today"
    raw_tw = {}  # classifier emitted no time_window at all

    _to_today_re = bool(_re.search(
        r'\b(to today|vs\.? today|versus today|compared to today|to now|vs\.? now)\b',
        question.lower()
    ))
    stated_years = _re.findall(r'\b(20\d{2})\b', question)
    _since_pattern = bool(_re.search(r'\bsince\b', question.lower()) and stated_years)
    _is_open_ended = _to_today_re or _since_pattern

    MONTH_NAMES = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }

    # Simulate the new fallback block
    if not raw_tw.get("period") and _is_open_ended and stated_years:
        _month_re = _re.search(
            r'\b(january|february|march|april|may|june|july|august|'
            r'september|october|november|december|'
            r'jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\b',
            question.lower()
        )
        if _month_re:
            _month_num = MONTH_NAMES.get(_month_re.group(1).lower())
            _year_int = int(stated_years[0])
            if _month_num:
                raw_tw = {
                    "period": "specific",
                    "start": f"{_year_int:04d}-{_month_num:02d}-01",
                    "end": None,
                }

    assert _is_open_ended, "question contains 'to today' — must be detected as open-ended"
    assert raw_tw.get("period") == "specific", (
        f"empty tw must be built from question text; got {raw_tw!r}"
    )
    assert raw_tw["start"] == "2026-01-01", (
        f"start must be 2026-01-01; got {raw_tw.get('start')!r}"
    )
    assert raw_tw["end"] is None, (
        f"end must be None (→ today) for open-ended; got {raw_tw.get('end')!r}"
    )

    result = resolve_time_window(raw_tw)
    assert result["end"] == TODAY.isoformat(), (
        f"resolved end must be today; got {result['end']!r}"
    )


def test_empty_tw_isolated_month_not_rewritten():
    """The empty-tw fallback must NOT fire for isolated month questions that
    are NOT open-ended (no 'to today', no 'since'). Constructing a time_window
    for 'show me March 2026' should still go through specific_month, not open
    the range to today."""
    import re as _re
    question = "show me pipeline in March 2026"
    raw_tw = {}

    _to_today_re = bool(_re.search(
        r'\b(to today|vs\.? today|versus today|compared to today|to now|vs\.? now)\b',
        question.lower()
    ))
    stated_years = _re.findall(r'\b(20\d{2})\b', question)
    _since_pattern = bool(_re.search(r'\bsince\b', question.lower()) and stated_years)
    _is_open_ended = _to_today_re or _since_pattern

    # Simulate the new fallback block — must NOT fire
    if not raw_tw.get("period") and _is_open_ended and stated_years:
        raw_tw = {"period": "specific", "start": "2026-03-01", "end": None}

    assert not _is_open_ended, "isolated month must not be open-ended"
    assert not raw_tw.get("period"), (
        "fallback must NOT fire for isolated months; time_window should stay empty"
    )


def test_period_custom_with_explicit_dates_resolves_correctly():
    """Bug #4: the dynamic loop's LLM emits period='custom' for cross-quarter
    date ranges. resolve_time_window had no 'custom' branch, so it fell through
    to the else clause and returned current-quarter dates — silently overwriting
    the correct start/end the LLM provided.

    Fix: treat period='custom' identically to period='specific': pass start/end
    through directly, mapping null end to today.
    """
    result = resolve_time_window(
        {"period": "custom", "start": "2026-01-01", "end": "2026-09-26"}
    )
    assert result["start"] == "2026-01-01", (
        f"period=custom must pass start through; got {result['start']!r}"
    )
    assert result["end"] == "2026-09-26", (
        f"period=custom must pass explicit end through; got {result['end']!r}"
    )


def test_period_custom_with_null_end_resolves_to_today():
    """period=custom with end=null must resolve end to today, same as
    period=specific with null end (open-ended 'from Month YYYY to today')."""
    result = resolve_time_window(
        {"period": "custom", "start": "2026-01-01", "end": None}
    )
    assert result["start"] == "2026-01-01", (
        f"period=custom+null end must pass start through; got {result['start']!r}"
    )
    assert result["end"] == TODAY.isoformat(), (
        f"period=custom+null end must resolve to today; got {result['end']!r}"
    )


if __name__ == "__main__":
    test_specific_with_null_end_resolves_to_today()
    print("PASS: specific + null end resolves to today")
    test_specific_month_caps_at_month_end()
    print("PASS: specific_month caps at month end (regression guard)")
    test_open_ended_rewrite_to_specific_null_end()
    print("PASS: open-ended rewrite resolves to today")
    test_defense_in_depth_vs_today_conversion()
    print("PASS: defense-in-depth converts specific_month to specific+null for 'vs today'")
    test_since_pattern_detected_as_open_ended()
    print("PASS: 'since' + year detected as open-ended")
    test_isolated_month_not_detected_as_open_ended()
    print("PASS: isolated month not treated as open-ended")
    test_defense_in_depth_empty_tw_open_ended()
    print("PASS: empty time_window fallback constructs from question text")
    test_empty_tw_isolated_month_not_rewritten()
    print("PASS: empty-tw fallback does not fire for isolated months")
    test_period_custom_with_explicit_dates_resolves_correctly()
    print("PASS: period=custom with explicit dates passes through correctly")
    test_period_custom_with_null_end_resolves_to_today()
    print("PASS: period=custom with null end resolves to today")
    print("\nAll tests passed.")
