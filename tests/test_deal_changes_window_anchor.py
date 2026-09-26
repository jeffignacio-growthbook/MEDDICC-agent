"""
_pm_view_deal_changes ignores requested_days — planted-bug controls.

Before the fix, _pm_view_deal_changes hardcoded:
    prior_date, current_date = all_dates[-2], all_dates[-1]

This means "show me deal changes in the last 3 weeks" would compare the
last two WEEKLY snapshots (7 days apart) rather than the snapshot nearest
to 21 days ago vs today. Deals that moved BEFORE the penultimate snapshot
would be invisible.

Fix: accept requested_days parameter and delegate anchor selection to
_pm_select_snapshot_anchors (same helper _pm_view_movement already uses).

PLANTED BUG:
  Snapshots: Sep 3, Sep 10, Sep 17, Sep 24 (4 weekly snapshots).
  Deal A: Discovery on Sep 3, advanced to Qualified on Sep 10, unchanged Sep 10→Sep 24.
  User asks: "changes in the last 3 weeks" → requested_days=21.

  Without fix (hardcoded last-two = Sep 17 vs Sep 24):
    Deal A is Qualified on both → 0 changes. The advancement is hidden.

  With fix (anchor = Sep 24 - 21 = Sep 3 → Sep 3 vs Sep 24):
    Deal A is Discovery on Sep 3, Qualified on Sep 24 → 1 "advanced" change.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import logging
logging.disable(logging.CRITICAL)

from api.handlers import _pm_view_deal_changes, _pm_select_snapshot_anchors


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------

def _snap(deal_id, snapshot_date, stage_id, stage_order, pipeline_id="default"):
    return {
        "deal_id": deal_id,
        "snapshot_date": snapshot_date,
        "stage_id": stage_id,
        "stage_order": stage_order,
        "pipeline_id": pipeline_id,
        "owner_email": "rep@gb.io",
        "snapshot_source": "live",
        "backfill_confidence": None,
    }


DISCOVERY = "stage_discovery"
QUALIFIED = "stage_qualified"
STAGE_CFG = {
    DISCOVERY: {"name": "Discovery", "order": 1},
    QUALIFIED: {"name": "Qualified", "order": 2},
}

# 4 weekly snapshots spanning 21 days
SEP_03 = "2026-09-03"
SEP_10 = "2026-09-10"
SEP_17 = "2026-09-17"
SEP_24 = "2026-09-24"

ALL_DATES = [SEP_03, SEP_10, SEP_17, SEP_24]

# Deal A: Discovery on Sep 3, Qualified from Sep 10 onward
ROWS_DEAL_A = [
    _snap("deal-A", SEP_03, DISCOVERY, 1),
    _snap("deal-A", SEP_10, QUALIFIED, 2),
    _snap("deal-A", SEP_17, QUALIFIED, 2),
    _snap("deal-A", SEP_24, QUALIFIED, 2),
]

BY_DATE = {
    SEP_03: [ROWS_DEAL_A[0]],
    SEP_10: [ROWS_DEAL_A[1]],
    SEP_17: [ROWS_DEAL_A[2]],
    SEP_24: [ROWS_DEAL_A[3]],
}


# ---------------------------------------------------------------------------
# Planted-bug test: without fix, the advancement is invisible
# ---------------------------------------------------------------------------

def test_planted_bug_hardcoded_last_two_misses_earlier_movement():
    """Planted-bug baseline: hardcoding all_dates[-2], all_dates[-1] silently
    drops movement that occurred BEFORE the penultimate snapshot.
    This test documents the wrong behavior — the fix must make it pass
    the next test instead of this one."""
    # Simulate the old hardcoded behavior
    prior_date = ALL_DATES[-2]   # Sep 17
    current_date = ALL_DATES[-1]  # Sep 24

    prior_rows = {r["deal_id"]: r for r in BY_DATE[prior_date]}
    current_rows = {r["deal_id"]: r for r in BY_DATE[current_date]}

    deal_a_prior_stage = prior_rows["deal-A"]["stage_id"]
    deal_a_current_stage = current_rows["deal-A"]["stage_id"]

    # Both are Qualified → no change visible
    assert deal_a_prior_stage == deal_a_current_stage == QUALIFIED, (
        "Planted bug baseline: deal A should appear unchanged when comparing "
        "the last two snapshots (Sep 17 vs Sep 24)"
    )


def test_fix_requested_days_selects_correct_prior_anchor():
    """_pm_select_snapshot_anchors with requested_days=21 on these 4 snapshots
    must pick Sep 3 as the prior anchor (Sep 24 - 21 days = Sep 3)."""
    prior, current, gaps = _pm_select_snapshot_anchors(ALL_DATES, requested_days=21)
    assert prior == SEP_03, (
        f"Expected prior anchor Sep 3 for 21-day window, got {prior!r}"
    )
    assert current == SEP_24, (
        f"Expected current anchor Sep 24, got {current!r}"
    )


def test_deal_changes_with_requested_days_captures_earlier_movement():
    """After the fix: _pm_view_deal_changes with requested_days=21 compares
    Sep 3 vs Sep 24, finding deal A advanced from Discovery to Qualified."""
    data_gaps = []
    snap_dates, changes = _pm_view_deal_changes(
        BY_DATE, ALL_DATES, STAGE_CFG, data_gaps,
        requested_days=21,
    )
    assert snap_dates == [SEP_03, SEP_24], (
        f"Expected [Sep 3, Sep 24] snap dates, got {snap_dates!r}"
    )
    advanced = [c for c in changes if c["direction"] == "advanced"]
    assert len(advanced) == 1, (
        f"Expected 1 advanced change (Discovery→Qualified), got {advanced!r}"
    )
    assert advanced[0]["deal_id"] == "deal-A"
    assert advanced[0]["prior_stage"] == "Discovery"
    assert advanced[0]["current_stage"] == "Qualified"


def test_deal_changes_no_requested_days_still_uses_last_two():
    """When requested_days is None (no time window), deal_changes falls back
    to comparing the last two snapshots — existing default preserved."""
    data_gaps = []
    snap_dates, changes = _pm_view_deal_changes(
        BY_DATE, ALL_DATES, STAGE_CFG, data_gaps,
        requested_days=None,
    )
    assert snap_dates == [SEP_17, SEP_24], (
        f"Expected [Sep 17, Sep 24] (last two) snap dates, got {snap_dates!r}"
    )
    # Deal A is Qualified on both → no changes
    assert changes == [], (
        f"Expected no changes when comparing last two snapshots, got {changes!r}"
    )


def test_deal_changes_requested_days_gap_message_when_no_old_enough_snapshot():
    """When requested_days exceeds the available date range, a data_gap message
    must be emitted — deal_changes must not silently use the oldest snapshot
    without disclosing that the window is shorter than requested."""
    by_date_short = {SEP_17: BY_DATE[SEP_17], SEP_24: BY_DATE[SEP_24]}
    all_dates_short = [SEP_17, SEP_24]  # only 7 days, but user wants 21

    data_gaps = []
    snap_dates, changes = _pm_view_deal_changes(
        by_date_short, all_dates_short, STAGE_CFG, data_gaps,
        requested_days=21,
    )
    # A gap message must be present — it would be wrong to silently deliver 7 days
    assert any("21" in g for g in data_gaps) or any("Requested" in g for g in data_gaps), (
        f"Expected a data_gap disclosure about 21-day window; got: {data_gaps!r}"
    )


if __name__ == "__main__":
    test_planted_bug_hardcoded_last_two_misses_earlier_movement()
    print("PASS: planted-bug baseline documented")
    test_fix_requested_days_selects_correct_prior_anchor()
    print("PASS: anchor helper picks Sep 3 for 21-day window")
    test_deal_changes_with_requested_days_captures_earlier_movement()
    print("PASS: deal_changes with requested_days=21 finds advancement")
    test_deal_changes_no_requested_days_still_uses_last_two()
    print("PASS: no requested_days → last two (regression)")
    test_deal_changes_requested_days_gap_message_when_no_old_enough_snapshot()
    print("PASS: gap message when window exceeds available history")
    print("\nAll tests passed.")
