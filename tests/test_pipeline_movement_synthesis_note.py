#!/usr/bin/env python3
"""
query_pipeline_movement's _synthesis_note must reach the model.

#32 (2026-09-22) added the rule that movement answers always state added $,
exited $ and net $ together, delivered as result["_synthesis_note"]. The
note was written into _pm_view_movement()'s dict, but the handler's final
return rebuilt the result from a fixed list of keys and left it out, so it
never reached synthesis (Piece 1 audit, 2026-09-23). The dollar figures got
through in `summary`; the instruction to state them together did not.

Two layers:
  1. the REAL handler (fake deals_snapshot + deals) returns the note with
     the real figures;
  2. that exact returned dict carries the note into the synthesis input on
     both paths (route_question's cap + truncate, and the dynamic loop via
     the canary harness).
"""
import asyncio
import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.handlers as handlers  # noqa: E402
import api.router as router  # noqa: E402
from canary_harness import run_canary_case  # noqa: E402


def _snap(deal_id, date, stage="presentationscheduled", order=3):
    return {"deal_id": deal_id, "snapshot_date": date, "pipeline_id": "default",
            "stage_id": stage, "stage_order": order, "close_date": "2026-10-30",
            "owner_email": "rep@example.com", "snapshot_source": "prospective",
            "backfill_confidence": "exact", "week_of_quarter": 7, "fiscal_quarter": "FY2027 Q3",
            "region": "EMEA", "segment": "Enterprise", "company_name": f"Co {deal_id}"}


# 2026-09-14 -> 2026-09-21: K stays, X exits, N1 and N2 are added
ROWS = ([_snap("K", "2026-09-14"), _snap("X", "2026-09-14")]
        + [_snap("K", "2026-09-21"), _snap("N1", "2026-09-21"), _snap("N2", "2026-09-21")])
DEAL_ARR = {"N1": (100000, None), "N2": (None, 25000), "X": (40000, 5000), "K": (1, 1)}


def _deal_row(deal_id, new=None, exp=None, **kw):
    return {"deal_id": deal_id, "company_name": f"Co {deal_id}", "new_arr": new, "expansion_arr": exp,
            "deal_status": "active", "stage": "presentationscheduled", "close_date": "2026-10-30",
            "pipeline_id": "default", **kw}


def _sb(rows=None, deals=None):
    """Strict fake (tests/strict_supabase.py) for deals_snapshot + deals: the
    REAL select_all runs against it, only selected columns come back, every
    filter applies. Until 2026-09-24 the snapshot fake returned whole rows,
    knew only eq/neq/exact-ilike and asserted table == deals_snapshot, so
    _pm_company_map's select_all("deals") raised inside a swallowing except
    and company names were never looked up."""
    from strict_supabase import StrictSupabase
    if deals is None:
        deals = [_deal_row(i, *DEAL_ARR[i]) for i in DEAL_ARR]
    return StrictSupabase({"deals_snapshot": ROWS if rows is None else rows, "deals": deals})


def _as_serialized(text):
    """The note as it appears inside the JSON payload the model reads
    (json.dumps escapes non-ASCII, e.g. the em dash becomes \\u2014)."""
    return json.dumps(text)[1:-1]


def _run_handler(params=None, sb=None):
    return asyncio.run(handlers.query_pipeline_movement(
        params or {"view": "movement", "fiscal_quarter": "FY2027 Q3"}, sb or _sb()))


def test_handler_returns_the_note_with_real_figures():
    r = _run_handler()
    s = r["summary"]
    assert (s["added_arr_total"], s["exited_arr_total"], s["net_arr_change"]) == (125000, 45000, 80000), s
    note = r.get("_synthesis_note")
    assert note, "query_pipeline_movement computed a _synthesis_note but its final return dropped it"
    for part in ("added $125,000", "exited $45,000", "net $80,000", "ALWAYS state all three"):
        assert part in note, (part, note)
    # company names come from deals via _pm_company_map (dead in these tests
    # until 2026-09-24: the old fake refused the deals table and the handler
    # swallowed the error)
    assert [row.get("company_name") for row in r["rows"]] == ["Co K", "Co N1", "Co N2"], r["rows"]
    print("✓ real handler: added $125,000 (2 deals), exited $45,000, net $80,000, "
          "and the _synthesis_note carrying all three is in the returned result")


def test_note_reaches_route_question_synthesis_input():
    r = _run_handler()
    payload = router._smart_truncate_for_synthesis(
        router._cap_rows_for_synthesis(copy.deepcopy(r)), router.SYNTH_PAYLOAD_CHARS)
    assert _as_serialized(r["_synthesis_note"]) in payload
    print("✓ classifier path: the note reaches the synthesis input")


def test_note_reaches_dynamic_loop_synthesis_input():
    r = _run_handler()
    rep = run_canary_case("how has pipeline moved this quarter?", "query_pipeline_movement",
                          {"view": "movement", "fiscal_quarter": "FY2027 Q3"}, r)
    assert rep["tool_executed"] and rep["channels"]["synthesis_input"], rep["channels"]
    assert _as_serialized(r["_synthesis_note"]) in rep["synthesis_text"]
    print("✓ dynamic loop (canary harness): the note reaches the synthesis input")


if __name__ == "__main__":
    test_handler_returns_the_note_with_real_figures()
    test_note_reaches_route_question_synthesis_input()
    test_note_reaches_dynamic_loop_synthesis_input()
    print("\n✅ All tests passed")
