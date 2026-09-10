"""
Regression tests for the 2026-09-11 budget-exhaustion defect: a "which
deals changed stage" question over deals_snapshot, with the date/anchor
logic already fixed (correct 14-day window, correct diff), still blew the
token budget because a genuinely-needed THIRD call (naming the matched
deal_ids with company_name, which deals_snapshot doesn't carry) fell
through to a fresh full-budget loop iteration instead of synthesizing
immediately — the same shortcut already used for a dimension-verification
retry, just never generalized to this shape.

_is_id_scoped_enrichment_call() detects that shape: a filter_table call
whose only real selectivity is an `in_`/`eq` on deal_id against IDs a
PRIOR step already discovered. Such a call cannot need a retry — the
population is already fixed — so its success is treated as "done,
synthesize now" in api/router.py's dynamic_query_loop, the same as
dimension_retry_succeeded.

2026-09-11, SECOND incident on the same shortcut: a live test showed it
firing after only ONE of the two required snapshot_date anchors had been
queried. The model pulled snapshot 2026-08-24, then jumped straight to an
enrichment lookup on those deal_ids against `deals` — and the shortcut,
seeing a clean ID-scoped lookup, let synthesis fire without the model ever
querying snapshot 2026-09-08 or computing a real stage-change diff.
Compounding it, the resulting Slack answer labeled its deals "as of
2026-09-08" when the data actually came from 2026-08-24 — a synthesis
labeling bug on top of the missing-anchor bug.

_snapshot_anchors_satisfied() closes the first half: the shortcut may not
fire for a snapshot-comparison question (current_snapshot_date/
prior_snapshot_date resolved) until BOTH anchor dates have actually
appeared in queried rows. verify_snapshot_date_labeling() closes the
second half: a mechanical, log-only check that an answer's "as of <date>"
claim is backed by a real snapshot_date in the data, not an assumed one.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.router import (
    _known_deal_ids_before,
    _is_id_scoped_enrichment_call,
    _queried_snapshot_dates_before,
    _snapshot_anchors_satisfied,
    _snapshot_anchor_redirect_instruction,
    _build_missing_snapshot_fetch,
    verify_snapshot_date_labeling,
)


def _raw_step(deal_ids, snapshot_date=None):
    row = lambda d: {"deal_id": d, **({"snapshot_date": snapshot_date} if snapshot_date else {})}
    return {"rows": [row(d) for d in deal_ids]}


def test_known_deal_ids_before_unions_prior_steps_only():
    accumulated = {
        "step_0_raw": _raw_step(["1", "2", "3"]),
        "step_0": {"rows": []},  # aggregated view, not a "_raw" step — ignored
        "step_1_raw": _raw_step(["3", "4"]),
        "step_2_raw": _raw_step(["999"]),  # this is the CURRENT iteration, must not count
    }
    known = _known_deal_ids_before(accumulated, iteration=2)
    assert known == {"1", "2", "3", "4"}, known
    print("✓ known_deal_ids_before unions prior steps and excludes the current one")


def test_id_scoped_lookup_after_snapshot_diff_is_detected():
    """The exact shape from the incident: two deals_snapshot pulls (step_0,
    step_1) matched deal_ids 101 and 205 as having changed stage; step_2
    looks up company_name for exactly those two ids on `deals`. This must
    be recognized as an unavoidable, ID-scoped enrichment call."""
    accumulated = {
        "step_0_raw": _raw_step(["101", "205", "310"]),  # current snapshot
        "step_1_raw": _raw_step(["101", "205"]),          # prior snapshot
    }
    known = _known_deal_ids_before(accumulated, iteration=2)

    tool_params = {
        "table": "deals",
        "columns": ["deal_id", "company_name"],
        "filters": [["in_", "deal_id", ["101", "205"]]],
    }
    assert _is_id_scoped_enrichment_call("filter_table", tool_params, known), (
        "A company_name lookup scoped to already-matched deal_ids must be "
        "recognized as enrichment, not fresh exploration"
    )
    print("✓ ID-scoped company_name lookup after a snapshot diff is detected")


def test_fresh_exploration_by_dimension_is_not_id_scoped():
    """The ORIGINAL incident's actual second call — filtering `deals` by
    region+segment+deal_status with NO deal_id filter at all — discovers a
    new population. It must NOT be treated as enrichment (it needs the
    normal dimension-verification path, not this shortcut)."""
    known = {"101", "205", "310"}
    tool_params = {
        "table": "deals",
        "columns": ["deal_id", "company_name", "segment", "region"],
        "filters": [["eq", "region", "EMEA"], ["eq", "segment", "Enterprise"],
                    ["eq", "deal_status", "active"]],
    }
    assert not _is_id_scoped_enrichment_call("filter_table", tool_params, known), (
        "A dimension-filtered exploration query must not be mistaken for "
        "ID-scoped enrichment — it can still change which deals qualify"
    )
    print("✓ a fresh dimensional exploration query is correctly NOT treated as enrichment")


def test_lookup_for_unknown_ids_is_not_enrichment():
    """A deal_id filter naming IDs we've never seen before isn't narrowing
    a known population — it's a fresh (if oddly-shaped) query and must not
    short-circuit synthesis."""
    known = {"101", "205"}
    tool_params = {
        "table": "deals",
        "columns": ["deal_id", "company_name"],
        "filters": [["in_", "deal_id", ["999", "888"]]],
    }
    assert not _is_id_scoped_enrichment_call("filter_table", tool_params, known)
    print("✓ a deal_id filter for IDs outside the known set is not treated as enrichment")


def test_id_scoped_lookup_with_companion_dimension_filter_is_excluded():
    """A deal_id filter that ALSO adds a region/segment/owner condition
    could still redefine which of the known deals qualify — conservatively
    exclude it from the shortcut rather than risk under-verifying."""
    known = {"101", "205"}
    tool_params = {
        "table": "deals",
        "columns": ["deal_id", "company_name"],
        "filters": [["in_", "deal_id", ["101", "205"]], ["eq", "region", "EMEA"]],
    }
    assert not _is_id_scoped_enrichment_call("filter_table", tool_params, known), (
        "A companion dimensional filter means this call isn't pure "
        "enrichment — must not short-circuit"
    )
    print("✓ a companion dimensional filter on an ID-scoped call is excluded, conservatively")


def test_deal_status_companion_filter_still_counts_as_enrichment():
    """Narrowing an already-fixed id set to 'active only' doesn't redefine
    the population's dimensions — it's still enrichment."""
    known = {"101", "205"}
    tool_params = {
        "table": "deals",
        "columns": ["deal_id", "company_name", "deal_status"],
        "filters": [["in_", "deal_id", ["101", "205"]], ["eq", "deal_status", "active"]],
    }
    assert _is_id_scoped_enrichment_call("filter_table", tool_params, known)
    print("✓ a deal_status companion filter doesn't disqualify an ID-scoped lookup")


def test_first_iteration_is_never_treated_as_enrichment():
    """iteration 0 has no prior steps to narrow from by construction —
    _known_deal_ids_before returns empty and the call can't be enrichment."""
    known = _known_deal_ids_before({}, iteration=0)
    tool_params = {"table": "deals", "filters": [["in_", "deal_id", ["1"]]]}
    assert known == set()
    assert not _is_id_scoped_enrichment_call("filter_table", tool_params, known)
    print("✓ an empty prior population never triggers the enrichment shortcut")


# ─── 2026-09-11 second incident: shortcut fired with only one anchor ───

def test_queried_snapshot_dates_before_unions_prior_steps_only():
    accumulated = {
        "step_0_raw": _raw_step(["1", "2"], snapshot_date="2026-08-24"),
        "step_1_raw": _raw_step(["9"], snapshot_date="2026-09-08"),
        "step_2_raw": _raw_step(["1", "2"]),  # current iteration — must not count
    }
    assert _queried_snapshot_dates_before(accumulated, iteration=2) == \
        {"2026-08-24", "2026-09-08"}
    assert _queried_snapshot_dates_before(accumulated, iteration=1) == {"2026-08-24"}
    print("✓ queried_snapshot_dates_before unions prior steps' snapshot_date values only")


def test_shortcut_blocked_when_only_one_anchor_queried_exact_incident_shape():
    """Reproduces exactly the live-test failure: current_snapshot_date=
    2026-09-08 and prior_snapshot_date=2026-08-24 were resolved (a real
    snapshot-comparison question), but only 2026-08-24 has actually been
    queried so far. The enrichment shortcut must refuse to fire — even
    though the pending call IS a clean, ID-scoped company_name lookup on
    already-known deal_ids — because the diff it would synthesize from
    doesn't exist yet."""
    accumulated = {
        "step_0_raw": _raw_step(["101", "205"], snapshot_date="2026-08-24"),
    }
    queried = _queried_snapshot_dates_before(accumulated, iteration=1)

    known_ids = _known_deal_ids_before(accumulated, iteration=1)
    tool_params = {
        "table": "deals",
        "columns": ["deal_id", "company_name"],
        "filters": [["in_", "deal_id", ["101", "205"]]],
    }
    # The call itself still looks like clean enrichment in isolation...
    assert _is_id_scoped_enrichment_call("filter_table", tool_params, known_ids)
    # ...but the anchor gate must refuse it: prior_snapshot_date (2026-08-24)
    # was queried, current_snapshot_date (2026-09-08) was NOT.
    assert not _snapshot_anchors_satisfied(
        current_snapshot_date="2026-09-08",
        prior_snapshot_date="2026-08-24",
        queried_dates=queried,
    ), (
        "The shortcut must be blocked: only one of the two required "
        "snapshot anchors has been queried, so there is no real diff to "
        "synthesize from yet — firing here reproduces the live incident "
        "(answered from snapshot 2026-08-24 alone, snapshot 2026-09-08 "
        "never queried, no actual stage-change diff computed)."
    )
    print("✓ shortcut correctly blocked: only one of two required snapshot anchors queried")


def test_shortcut_fires_once_both_anchors_are_queried():
    """Once BOTH anchors have been queried (the model did it right this
    time), the same enrichment call must be allowed to short-circuit —
    the fix must not become a new source of budget exhaustion by blocking
    forever."""
    accumulated = {
        "step_0_raw": _raw_step(["101", "205", "9"], snapshot_date="2026-09-08"),
        "step_1_raw": _raw_step(["101", "205"], snapshot_date="2026-08-24"),
    }
    queried = _queried_snapshot_dates_before(accumulated, iteration=2)

    assert _snapshot_anchors_satisfied(
        current_snapshot_date="2026-09-08",
        prior_snapshot_date="2026-08-24",
        queried_dates=queried,
    )
    known_ids = _known_deal_ids_before(accumulated, iteration=2)
    tool_params = {
        "table": "deals",
        "columns": ["deal_id", "company_name"],
        "filters": [["in_", "deal_id", ["101", "205"]]],
    }
    assert _is_id_scoped_enrichment_call("filter_table", tool_params, known_ids)
    print("✓ shortcut correctly fires once both snapshot anchors have been queried")


def test_anchors_satisfied_is_a_noop_for_non_snapshot_questions():
    """A question with no resolved anchors (current/prior both None) isn't
    a snapshot comparison at all — the gate must not block the existing,
    already-shipped enrichment shortcut for ordinary questions."""
    assert _snapshot_anchors_satisfied(None, None, queried_dates=set())
    print("✓ non-snapshot questions are unaffected by the anchor gate")


# ─── 2026-09-11: synthesis labeling the wrong snapshot_date ───

def test_verify_snapshot_date_labeling_catches_the_live_mismatch():
    """Reproduces the second half of the incident: the answer said 'as of
    2026-09-08' while every row actually queried carries snapshot_date
    2026-08-24."""
    answer = "2 deals moved to Negotiating as of 2026-09-08: Acme Corp, Beta Inc."
    tool_results = {"rows": [
        {"deal_id": "101", "company_name": "Acme Corp", "snapshot_date": "2026-08-24"},
        {"deal_id": "205", "company_name": "Beta Inc", "snapshot_date": "2026-08-24"},
    ]}

    ok, unmatched, real_dates = verify_snapshot_date_labeling(answer, tool_results)

    assert not ok
    assert unmatched == ["2026-09-08"]
    assert real_dates == {"2026-08-24"}
    print("✓ verify_snapshot_date_labeling catches an answer date not backed by any row")


def test_verify_snapshot_date_labeling_passes_when_dates_match():
    answer = "2 deals moved to Negotiating as of 2026-08-24: Acme Corp, Beta Inc."
    tool_results = {"rows": [
        {"deal_id": "101", "company_name": "Acme Corp", "snapshot_date": "2026-08-24"},
    ]}
    ok, unmatched, real_dates = verify_snapshot_date_labeling(answer, tool_results)
    assert ok and unmatched == []
    print("✓ verify_snapshot_date_labeling passes when the stated date is backed by real rows")


def test_verify_snapshot_date_labeling_noop_without_snapshot_data():
    """A question with no snapshot_date field anywhere (not a point-in-time
    comparison) has nothing to verify against — must not false-positive."""
    answer = "Q3 closes as of 2026-09-08: 4 deals worth $210K."
    tool_results = {"rows": [{"deal_id": "1", "close_date": "2026-09-08"}]}
    ok, unmatched, real_dates = verify_snapshot_date_labeling(answer, tool_results)
    assert ok and unmatched == [] and real_dates == set()
    print("✓ labeling check is a no-op when the data has no snapshot_date field at all")


def test_verify_snapshot_date_labeling_noop_without_as_of_claim():
    """No 'as of <date>' phrasing in the answer at all — nothing to check."""
    answer = "2 deals moved to Negotiating: Acme Corp, Beta Inc."
    tool_results = {"rows": [{"deal_id": "101", "snapshot_date": "2026-08-24"}]}
    ok, unmatched, real_dates = verify_snapshot_date_labeling(answer, tool_results)
    assert ok and unmatched == []
    print("✓ labeling check is a no-op when the answer makes no 'as of' claim")


# 2026-09-11 ROUND 3: a THIRD incident on this same mechanism family — see
# tests/test_snapshot_finalize_forced_fetch.py for the full end-to-end
# reproduction. These two unit tests pin the extracted logic directly.

def test_redirect_instruction_is_none_when_anchors_already_satisfied():
    assert _snapshot_anchor_redirect_instruction(
        "2026-09-08", "2026-07-27", {"2026-09-08", "2026-07-27"}) is None
    print("✓ redirect instruction is None once both anchors are queried")


def test_redirect_instruction_is_none_for_non_snapshot_questions():
    assert _snapshot_anchor_redirect_instruction(None, None, set()) is None
    print("✓ redirect instruction is None when this isn't a snapshot-comparison question")


def test_redirect_instruction_names_the_specific_missing_date():
    instruction = _snapshot_anchor_redirect_instruction(
        "2026-09-08", "2026-07-27", {"2026-09-08"})
    assert instruction is not None
    assert "2026-07-27" in instruction, (
        "the redirect must name the SPECIFIC missing date, not just say "
        "'query the missing snapshot'"
    )
    assert "filter_table" in instruction, (
        "the redirect must tell the model what action to take (issue a "
        "filter_table call), not just what's wrong"
    )
    print("✓ redirect instruction names the specific missing snapshot_date and the concrete next action")


def test_build_missing_snapshot_fetch_reuses_template_filters():
    """The forced fetch must reuse the SAME region/segment/etc. filters
    from a prior deals_snapshot query, only swapping the snapshot_date —
    never guess fresh filters that could silently answer a different
    population."""
    queries_run = [
        {"tool": "filter_table", "params": {
            "table": "deals_snapshot",
            "columns": ["deal_id", "stage_id", "region", "segment", "snapshot_date"],
            "filters": [["eq", "snapshot_date", "2026-09-08"],
                        ["eq", "region", "EMEA"],
                        ["eq", "segment", "Enterprise"]],
        }, "rows_returned": 5},
    ]
    result = _build_missing_snapshot_fetch(queries_run, "2026-07-27")
    assert result is not None
    table, columns, filters = result
    assert table == "deals_snapshot"
    filters_by_col = {f[1]: f[2] for f in filters}
    assert filters_by_col["snapshot_date"] == "2026-07-27", (
        "snapshot_date must be swapped to the missing date"
    )
    assert filters_by_col["region"] == "EMEA", (
        "region filter must be carried over unchanged"
    )
    assert filters_by_col["segment"] == "Enterprise", (
        "segment filter must be carried over unchanged"
    )
    print("✓ the forced fetch reuses the template query's region/segment filters, swapping only snapshot_date")


def test_build_missing_snapshot_fetch_returns_none_without_a_template():
    """No prior deals_snapshot filter_table call with a snapshot_date
    filter exists yet — there is nothing safe to model the forced fetch
    on, so this must return None rather than guess filters."""
    assert _build_missing_snapshot_fetch([], "2026-07-27") is None
    queries_run = [
        {"tool": "filter_table", "params": {
            "table": "deals", "filters": [["eq", "region", "EMEA"]],
        }, "rows_returned": 5},
    ]
    assert _build_missing_snapshot_fetch(queries_run, "2026-07-27") is None
    print("✓ returns None when no deals_snapshot query with a snapshot_date filter exists to model on")


if __name__ == "__main__":
    test_known_deal_ids_before_unions_prior_steps_only()
    test_id_scoped_lookup_after_snapshot_diff_is_detected()
    test_fresh_exploration_by_dimension_is_not_id_scoped()
    test_lookup_for_unknown_ids_is_not_enrichment()
    test_id_scoped_lookup_with_companion_dimension_filter_is_excluded()
    test_deal_status_companion_filter_still_counts_as_enrichment()
    test_first_iteration_is_never_treated_as_enrichment()
    test_queried_snapshot_dates_before_unions_prior_steps_only()
    test_shortcut_blocked_when_only_one_anchor_queried_exact_incident_shape()
    test_shortcut_fires_once_both_anchors_are_queried()
    test_anchors_satisfied_is_a_noop_for_non_snapshot_questions()
    test_verify_snapshot_date_labeling_catches_the_live_mismatch()
    test_verify_snapshot_date_labeling_passes_when_dates_match()
    test_verify_snapshot_date_labeling_noop_without_snapshot_data()
    test_verify_snapshot_date_labeling_noop_without_as_of_claim()
    test_redirect_instruction_is_none_when_anchors_already_satisfied()
    test_redirect_instruction_is_none_for_non_snapshot_questions()
    test_redirect_instruction_names_the_specific_missing_date()
    test_build_missing_snapshot_fetch_reuses_template_filters()
    test_build_missing_snapshot_fetch_returns_none_without_a_template()
    print("\n✅ All tests passed")
