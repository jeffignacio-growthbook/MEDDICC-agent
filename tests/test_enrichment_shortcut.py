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
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.router import _known_deal_ids_before, _is_id_scoped_enrichment_call


def _raw_step(deal_ids):
    return {"rows": [{"deal_id": d} for d in deal_ids]}


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


if __name__ == "__main__":
    test_known_deal_ids_before_unions_prior_steps_only()
    test_id_scoped_lookup_after_snapshot_diff_is_detected()
    test_fresh_exploration_by_dimension_is_not_id_scoped()
    test_lookup_for_unknown_ids_is_not_enrichment()
    test_id_scoped_lookup_with_companion_dimension_filter_is_excluded()
    test_deal_status_companion_filter_still_counts_as_enrichment()
    test_first_iteration_is_never_treated_as_enrichment()
    print("\n✅ All tests passed")
