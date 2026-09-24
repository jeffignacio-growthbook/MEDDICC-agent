#!/usr/bin/env python3
"""
query_pipeline_movement's deal_changes view: a deal that left says how.

Live, 2026-09-24 21:20 UTC, after #56: "What's changed with Jake H's deals
this week?" routed to this view (reason_tag query_pipeline_movement_fast_
path) and answered "Comcast — left pipeline (was in Discovery, no longer in
snapshot) ... if it closed lost or was disqualified, make sure the loss
reason is logged". Comcast closed lost; the CRM says so.

_pm_left_reason() classified an exit by its row in the CURRENT snapshot,
unscoped: a closed stage there meant won/lost, an excluded one meant
"moved_to_excluded_stage", no row meant "gone_from_snapshot". But a deal's
snapshot rows stop when it closes. Of the 108 Sales-pipeline deals closed
since 2026-08-01 (100 lost, 8 won), 1 has a last snapshot row at a closed
stage; the other 107 end on an open stage. So almost every close came back
"gone_from_snapshot", and the answer could only guess.

The view now classifies each exit from the deal's current `deals` row, as
the movement view's exited_breakdown already does (_pm_classify_exits):
won/lost from deal_status (or a won/lost stage); still open falls back to
the snapshot reason. The result says the status is as of today.

Real handler, strict fake (tests/strict_supabase.py).
"""
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import test_pipeline_movement_synthesis_note as pm  # noqa: E402

PRIOR, CURRENT = "2026-09-14", "2026-09-21"
MEETING_SET = "79653122"
ROWS = ([pm._snap(i, PRIOR) for i in ("K", "COMCAST", "WONGONE", "OPENGONE", "TOMS")]
        + [pm._snap("K", CURRENT),
           pm._snap("TOMS", CURRENT, stage=MEETING_SET, order=0)])    # dropped to an excluded stage


def _deal(i, status, stage, close="2026-10-30"):
    return {"deal_id": i, "company_name": f"Co {i}", "pipeline_id": "default", "new_arr": 1000,
            "expansion_arr": None, "deal_status": status, "stage": stage, "close_date": close}


DEALS = [_deal("K", "active", "presentationscheduled"),
         _deal("COMCAST", "lost", "closedlost", "2026-09-08"),     # the live case: lost, no current row
         _deal("WONGONE", "won", "closedwon", "2026-09-18"),
         _deal("OPENGONE", "active", "presentationscheduled"),     # still open, row missing
         _deal("TOMS", "active", MEETING_SET)]


def _run():
    return pm._run_handler({"view": "deal_changes", "fiscal_quarter": "FY2027 Q3"},
                           pm._sb(rows=ROWS, deals=DEALS))


def test_a_close_with_no_current_snapshot_row_is_reported_as_the_close():
    r = _run()
    left = {c["deal_id"]: c.get("reason") for c in r["changes"] if c["direction"] == "left_pipeline"}
    assert left == {"COMCAST": "closed_lost", "WONGONE": "closed_won",
                    "OPENGONE": "gone_from_snapshot", "TOMS": "moved_to_excluded_stage"}, left
    print("✓ deal_changes: a lost deal with no current snapshot row is closed_lost (was "
          "gone_from_snapshot); won likewise; still-open exits keep the snapshot reason")


def test_the_result_says_the_status_is_as_of_today():
    r = _run()
    assert "today" in (r.get("exit_reason_as_of") or ""), r.keys()
    print("✓ deal_changes says an exit's won/lost status is the deals table's, as of today")


if __name__ == "__main__":
    test_a_close_with_no_current_snapshot_row_is_reported_as_the_close()
    test_the_result_says_the_status_is_as_of_today()
    print("\n✅ All tests passed")
