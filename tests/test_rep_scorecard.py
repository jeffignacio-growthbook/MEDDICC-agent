#!/usr/bin/env python3
"""
Per-rep scorecard (scripts/rep_scorecard.py): the two computed lines added to
every loss-concentration rep row.

  1. loss_depth: of the rep's qualified losses this quarter, how many never
     passed Discovery and how many were ever COMMIT / Most Likely.
  2. pace: wins and incremental ARR closed by this point of the quarter vs the
     same point in the rep's last 3 quarters with a Sales win.

Real data: tests/fixtures/rep_scorecard_2026_09_25.json — this quarter's
non-disqualified Sales losses with snapshot history (<= close_date, carrying
forecast_category) and Sales wins 2025-08-01..2026-10-31, both with
owner_email, captured read-only 2026-09-25 (md5 fd4d025c...). Christian and
Jake are pinned in full; the wording branches are pinned on the helpers.
"""
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "api"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import rep_scorecard as rs  # noqa: E402
from strict_supabase import StrictSupabase  # noqa: E402

FX = json.loads((REPO / "tests" / "fixtures" / "rep_scorecard_2026_09_25.json").read_text())
AS_OF = date(2026, 9, 25)
CHRISTIAN = "christian@growthbook.io"
JAKE = "jake@growthbook.io"


def _sb():
    cols = FX["loss_snapshot_columns"]
    deals = ([{**l, "pipeline_id": "default", "deal_status": "lost"} for l in FX["losses"]]
             + [{**w, "pipeline_id": "default", "deal_status": "won"} for w in FX["wins"]])
    return StrictSupabase({"deals": deals,
                           "deals_snapshot": [dict(zip(cols, r)) for r in FX["loss_snapshots"]]})


def run():
    return rs.assess_rep_scorecard(_sb(), as_of=AS_OF)


def test_helpers_cover_every_wording_branch():
    assert rs.loss_depth_line(0, 0, 0) == "no qualified losses this quarter"
    assert rs.loss_depth_line(14, 8, 0) == ("8 of 14 qualified losses never passed Discovery; "
                                            "none ever tagged COMMIT or Most Likely")
    assert rs.loss_depth_line(4, 2, 1) == ("2 of 4 qualified losses never passed Discovery; "
                                           "1 ever tagged COMMIT or Most Likely")
    assert rs.pace_line(56, 0, 0, []) == ("day-56 pace: 0 wins / $0 this quarter; no prior-quarter "
                                          "win pace to compare")
    assert rs.pace_line(56, 1, 30000, [{"label": "FY2027 Q2", "wins": 0, "arr": 0}]) == (
        "day-56 pace: 1 win / $30,000 this quarter, vs 0 wins / $0 at this point in the prior "
        "1 quarter (FY2027 Q2)")
    print("✓ loss_depth and pace wording: zero losses, none/some COMMIT-ML, no-prior and "
          "single-prior pace")


def test_christian_and_jake_pinned_on_real_data():
    by = run()["by_owner"]
    assert by[CHRISTIAN]["loss_depth"] == ("8 of 14 qualified losses never passed Discovery; "
                                           "none ever tagged COMMIT or Most Likely")
    assert by[CHRISTIAN]["pace"] == ("day-56 pace: 0 wins / $0 this quarter, vs 2-4 wins / "
                                     "$108,326-$166,250 at this point in the prior 3 quarters "
                                     "(FY2027 Q2, FY2027 Q1, FY2026 Q4)")
    assert (by[CHRISTIAN]["qualified_losses"], by[CHRISTIAN]["never_past_discovery"],
            by[CHRISTIAN]["ever_commit_ml"]) == (14, 8, 0)
    assert by[JAKE]["loss_depth"] == ("2 of 4 qualified losses never passed Discovery; "
                                      "1 ever tagged COMMIT or Most Likely")
    assert by[JAKE]["pace"] == ("day-56 pace: 0 wins / $0 this quarter, vs 1-5 wins / "
                                "$25,000-$225,000 at this point in the prior 3 quarters "
                                "(FY2027 Q2, FY2027 Q1, FY2026 Q4)")
    print("✓ Christian: 8/14 never past Discovery, none ever COMMIT/ML, 0 wins vs 2-4 prior; "
          "Jake: 2/4, 1 ever COMMIT/ML, 0 wins vs 1-5 prior")


def test_zero_losses_and_no_win_history_are_stated():
    by = run()["by_owner"]
    assert by["cary@growthbook.io"]["loss_depth"] == "no qualified losses this quarter"
    assert by["cary@growthbook.io"]["qualified_losses"] == 0
    # marcel: 1 qualified loss, no Sales wins anywhere in the window
    assert by["marcel@growthbook.io"]["loss_depth"].endswith("qualified losses never passed Discovery; "
                                                             "none ever tagged COMMIT or Most Likely")
    assert by["marcel@growthbook.io"]["pace"].endswith("no prior-quarter win pace to compare")
    assert by["marcel@growthbook.io"]["current_wins"] == 0
    print("✓ a rep with no qualified losses, and a rep with no win history, each say so plainly")


def test_a_loss_that_never_qualified_is_not_counted():
    """A default-pipeline loss whose only snapshots are Meeting Set never
    reached Discovery, so it is not a qualified loss and not in the counts."""
    sb = StrictSupabase({
        "deals": [{"deal_id": "MS", "owner_email": "x@y.io", "close_date": "2026-09-10",
                   "stage": "closedlost", "pipeline_id": "default", "deal_status": "lost"}],
        "deals_snapshot": [{"deal_id": "MS", "snapshot_date": "2026-09-01", "stage_id": "79653122",
                            "forecast_category": "COMMIT"}]})
    r = rs.assess_rep_scorecard(sb, as_of=AS_OF)
    assert r["by_owner"]["x@y.io"]["qualified_losses"] == 0
    assert r["by_owner"]["x@y.io"]["loss_depth"] == "no qualified losses this quarter"
    print("✓ a Meeting-Set-only loss is not a qualified loss, even if it was tagged COMMIT")


def test_snapshots_after_close_are_ignored():
    """Depth and ever-COMMIT/ML read the deal only up to its close date. A
    loss at Discovery before close, that a later snapshot shows reaching
    Negotiating and tagged COMMIT, still counts as never-past-Discovery and
    not-ever-COMMIT (those snapshots are after it closed)."""
    sb = StrictSupabase({
        "deals": [{"deal_id": "D", "owner_email": "x@y.io", "close_date": "2026-09-10",
                   "stage": "closedlost", "pipeline_id": "default", "deal_status": "lost"}],
        "deals_snapshot": [
            {"deal_id": "D", "snapshot_date": "2026-09-01", "stage_id": "appointmentscheduled",
             "forecast_category": "PIPELINE"},
            {"deal_id": "D", "snapshot_date": "2026-09-20", "stage_id": "24682892",
             "forecast_category": "COMMIT"}]})
    o = rs.assess_rep_scorecard(sb, as_of=AS_OF)["by_owner"]["x@y.io"]
    assert (o["qualified_losses"], o["never_past_discovery"], o["ever_commit_ml"]) == (1, 1, 0), o
    print("✓ snapshots after close_date don't deepen the stage or count as ever-COMMIT/ML")


def test_every_rep_row_has_both_lines():
    by = run()["by_owner"]
    for owner in ("christian@growthbook.io", "dan@growthbook.io", "james.shannon@growthbook.io",
                  JAKE, "scott.keller@growthbook.io", "marcel@growthbook.io", "cary@growthbook.io"):
        assert by[owner]["loss_depth"] and by[owner]["pace"], owner
    print("✓ all 7 AE reps have a loss_depth and a pace line")


if __name__ == "__main__":
    test_helpers_cover_every_wording_branch()
    test_christian_and_jake_pinned_on_real_data()
    test_zero_losses_and_no_win_history_are_stated()
    test_a_loss_that_never_qualified_is_not_counted()
    test_snapshots_after_close_are_ignored()
    test_every_rep_row_has_both_lines()
    print("\n✅ All tests passed")
