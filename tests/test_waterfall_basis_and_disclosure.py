#!/usr/bin/env python3
"""
query_waterfall: governed basis, quarter-scoped headline, company-wide weekly
rows, and a basis disclosure that actually reaches the model.

Before 2026-09-24 the handler had three problems (Piece 1 audit):
  - headline = sum(arr_usd) (HubSpot incremental_arr property, falling back
    to `amount`), not incremental_arr();
  - headline = every open deal, labeled with a quarter it wasn't scoped to;
  - weekly rows = raw waterfall_weekly (region, segment) slices with region
    and segment not selected, up to 19 unlabeled rows per week.

Two layers, because the pipeline_movement bug showed a handler can compute a
_synthesis_note and then drop it before returning:
  1. the REAL handler, against a fake Supabase, returns the right numbers
     and the disclosure;
  2. that exact returned dict, pushed through both synthesis paths
     (route_question's cap + truncate, and the dynamic loop via the canary
     harness), still carries the disclosure text the model is told to use.
"""
import asyncio
import copy
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.handlers as handlers  # noqa: E402
import api.router as router  # noqa: E402
from canary_harness import run_canary_case  # noqa: E402

TW = {"label": "FY2027 Q3", "start": "2026-08-01", "end": "2026-10-31"}
RENEWAL = "866608541"

DEALS = [
    # in scope, closes in Q3 -> headline
    {"deal_id": "A", "company_name": "Alpha", "stage": "presentationscheduled", "pipeline_id": "default",
     "deal_status": "active", "close_date": "2026-09-30", "new_arr": 100000, "expansion_arr": None,
     "arr_usd": 100000},
    # in scope, closes in Q3, no incremental ARR (HubSpot amount fallback): 0 on the governed basis
    {"deal_id": "E", "company_name": "Echo", "stage": "24682892", "pipeline_id": "default",
     "deal_status": "active", "close_date": "2026-10-15", "new_arr": None, "expansion_arr": None,
     "arr_usd": 40000},
    # in scope, closes in Q4 -> all-open only
    {"deal_id": "B", "company_name": "Bravo", "stage": "qualifiedtobuy", "pipeline_id": "default",
     "deal_status": "active", "close_date": "2026-12-15", "new_arr": 50000, "expansion_arr": 10000,
     "arr_usd": 60000},
    # renewal pipeline -> excluded
    {"deal_id": "C", "company_name": "Charlie", "stage": "1297321620", "pipeline_id": RENEWAL,
     "deal_status": "active", "close_date": "2026-09-01", "new_arr": None, "expansion_arr": 5000,
     "arr_usd": 300000},
    # Meeting Set -> excluded
    {"deal_id": "D", "company_name": "Delta", "stage": "79653122", "pipeline_id": "default",
     "deal_status": "active", "close_date": "2026-09-10", "new_arr": 20000, "expansion_arr": None,
     "arr_usd": 20000},
]

SLICES = [
    # week 2026-09-14: two slices, computed before value_basis existed (NULL = deal_value)
    {"week_ending": "2026-09-14", "pipeline_id": "default", "region": "EMEA", "segment": "Enterprise",
     "value_basis": None, "new_pipeline_value": 20000, "won_value": 0, "lost_value": 0,
     "net_change": 20000, "pulled_in_value": 0, "pushed_out_value": 0, "deals_qualified_count": 1},
    {"week_ending": "2026-09-14", "pipeline_id": "default", "region": "NAM", "segment": "SMB",
     "value_basis": None, "new_pipeline_value": 5000, "won_value": 3000, "lost_value": 0,
     "net_change": 2000, "pulled_in_value": 0, "pushed_out_value": 0, "deals_qualified_count": 1},
    {"week_ending": "2026-09-14", "pipeline_id": "default", "region": "APAC", "segment": "SMB",
     "value_basis": None, "new_pipeline_value": 0, "won_value": 0, "lost_value": 0,
     "net_change": 0, "pulled_in_value": 0, "pushed_out_value": 0, "deals_qualified_count": 0},
    # week 2026-09-21: recomputed on incremental_arr
    {"week_ending": "2026-09-21", "pipeline_id": "default", "region": "EMEA", "segment": "Enterprise",
     "value_basis": "incremental_arr", "new_pipeline_value": 7000, "won_value": 0, "lost_value": 1000,
     "net_change": 6000, "pulled_in_value": 0, "pushed_out_value": 0, "deals_qualified_count": 1},
    # a renewal-pipeline slice must never reach the weekly totals
    {"week_ending": "2026-09-21", "pipeline_id": RENEWAL, "region": "EMEA", "segment": "Enterprise",
     "value_basis": "incremental_arr", "new_pipeline_value": 999999, "won_value": 0, "lost_value": 0,
     "net_change": 999999, "pulled_in_value": 0, "pushed_out_value": 0, "deals_qualified_count": 0},
]


def _sb():
    """Strict fake (tests/strict_supabase.py): the REAL select_all runs
    against it, so only selected columns come back and every filter applies.
    (Until 2026-09-24 a hand-rolled select_all returned whole rows and knew
    only eq/gte/lte.)"""
    from strict_supabase import StrictSupabase
    return StrictSupabase({"deals": DEALS + DECOY_DEALS, "waterfall_weekly": SLICES + DECOY_SLICES})


# In the tables but outside what query_waterfall asks for: its own filters
# must drop them (the old fake would have returned them, or had nothing to drop).
DECOY_DEALS = [
    {"deal_id": "W", "company_name": "WonCo", "stage": "closedwon", "pipeline_id": "default",
     "deal_status": "won", "close_date": "2026-09-15", "new_arr": 777000, "expansion_arr": None,
     "arr_usd": 777000},
]
DECOY_SLICES = [
    {"week_ending": "2026-07-27", "pipeline_id": "default", "region": "EMEA", "segment": "Enterprise",
     "value_basis": None, "new_pipeline_value": 555000, "won_value": 555000, "lost_value": 555000,
     "net_change": 555000, "pulled_in_value": 0, "pushed_out_value": 0, "deals_qualified_count": 9},
]


def _run_handler(question="what does our pipeline look like this quarter?"):
    saved = handlers.compute_at_risk_deals
    handlers.compute_at_risk_deals = lambda sb, **kw: []
    try:
        return asyncio.run(handlers.query_waterfall({"time_window": TW, "question": question}, _sb()))
    finally:
        handlers.compute_at_risk_deals = saved


def test_headline_is_incremental_arr_closing_in_the_period():
    r = _run_handler()
    ps = r["pipeline_summary"]
    assert ps["basis"] == "incremental_arr"
    assert ps["total_incremental_arr"] == 100000.0, ps["total_incremental_arr"]
    assert ps["total_open_count"] == 2, ps["total_open_count"]            # A and E
    assert "total_open_arr" not in ps, "the ambiguous arr_usd headline must be gone"
    assert ps["all_open_pipeline"]["incremental_arr"] == 160000.0 and ps["all_open_pipeline"]["count"] == 3
    assert "NOT scoped to FY2027 Q3" in ps["all_open_pipeline"]["statement"]
    old = sum(d["arr_usd"] for d in DEALS if d["deal_id"] in ("A", "E", "B"))
    assert old == 200000 and ps["total_incremental_arr"] != old
    assert sum(s["count"] for s in ps["by_stage"]) == ps["total_open_count"]
    print(f"✓ headline $100,000 over 2 deals closing in FY2027 Q3 on incremental_arr() "
          f"(old arr_usd all-open figure: ${old:,}); all-open $160,000 over 3 deals labeled separately")


def test_weekly_rows_are_company_wide_with_labeled_slices_and_basis():
    r = _run_handler()
    weeks = {w["week_ending"]: w for w in r["waterfall"]}
    assert list(weeks) == ["2026-09-14", "2026-09-21"], list(weeks)
    w14, w21 = weeks["2026-09-14"], weeks["2026-09-21"]
    assert w14["new_pipeline_value"] == 25000 and w14["won_value"] == 3000 and w14["slice_count"] == 3
    assert [(s["region"], s["segment"]) for s in w14["by_slice"]] == [("EMEA", "Enterprise"), ("NAM", "SMB")]
    assert w14["value_basis"] == "deal_value" and w21["value_basis"] == "incremental_arr"
    assert w21["new_pipeline_value"] == 7000, "renewal-pipeline slice leaked into the weekly total"
    assert "each week's value_basis says which" in r["waterfall_basis_statement"]
    print("✓ weekly: one company-wide row per week (slices summed, non-zero slices labeled), "
          "renewal slice excluded, value_basis per week (deal_value / incremental_arr)")


def _note_parts(r):
    return [r["pipeline_summary"]["basis_statement"], "$100,000", "closing in FY2027 Q3",
            "ALL open pipeline regardless of close date", r["waterfall_basis_statement"]]


def test_disclosure_reaches_route_question_synthesis_input():
    r = _run_handler()
    note = r["_synthesis_note"]
    for part in _note_parts(r)[1:]:
        assert part in note, (part, note)
    payload = router._smart_truncate_for_synthesis(
        router._cap_rows_for_synthesis(copy.deepcopy(r)), router.SYNTH_PAYLOAD_CHARS)
    for part in [note, r["pipeline_summary"]["basis_statement"], r["waterfall_basis_statement"]]:
        assert part in payload, f"not in the classifier path's synthesis input: {part[:80]!r}"
    print("✓ classifier path: _synthesis_note, basis_statement and waterfall_basis_statement "
          "all reach the synthesis input")


def test_disclosure_reaches_dynamic_loop_synthesis_input():
    r = _run_handler()
    rep = run_canary_case("what does our pipeline look like this quarter?", "query_waterfall",
                          {}, r, time_window=TW)
    assert rep["tool_executed"] and rep["channels"]["synthesis_input"], rep["channels"]
    text = rep["synthesis_text"]
    for part in _note_parts(r):
        assert part in text, f"not in the dynamic loop's synthesis input: {part[:80]!r}"
    print("✓ dynamic loop (canary harness): the real handler result's _synthesis_note, "
          "pipeline_summary and waterfall_basis_statement reach the synthesis input")


def test_control_a_dropped_note_is_detected():
    """Planted bug: the pipeline_movement shape (note computed, not returned)."""
    r = _run_handler()
    r.pop("_synthesis_note")
    payload = router._smart_truncate_for_synthesis(
        router._cap_rows_for_synthesis(copy.deepcopy(r)), router.SYNTH_PAYLOAD_CHARS)
    assert "ALL open pipeline regardless of close date" not in payload
    print("✓ control: with the note dropped, its instruction is absent from the synthesis input")


if __name__ == "__main__":
    test_headline_is_incremental_arr_closing_in_the_period()
    test_weekly_rows_are_company_wide_with_labeled_slices_and_basis()
    test_disclosure_reaches_route_question_synthesis_input()
    test_disclosure_reaches_dynamic_loop_synthesis_input()
    test_control_a_dropped_note_is_detected()
    print("\n✅ All tests passed")
