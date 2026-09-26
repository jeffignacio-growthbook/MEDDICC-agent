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


# ---------------------------------------------------------------------------
# Realistic multi-deal multi-week scenario (January-comparison shape)
# ---------------------------------------------------------------------------

# 6 weekly snapshots: Aug 13 → Sep 17 (5 weeks apart = 35-day span)
AUG_13 = "2026-08-13"
AUG_20 = "2026-08-20"
AUG_27 = "2026-08-27"
SEP_03_R = "2026-09-03"  # suffixed to avoid name collision with existing constants
SEP_10_R = "2026-09-10"
SEP_17_R = "2026-09-17"

ALL_DATES_REAL = [AUG_13, AUG_20, AUG_27, SEP_03_R, SEP_10_R, SEP_17_R]

STAGE_CFG_REAL = {
    "stage_disc": {"name": "Discovery", "order": 1},
    "stage_qual": {"name": "Qualified", "order": 2},
    "stage_prop": {"name": "Proposal", "order": 3},
}


def _snap_r(deal_id, snapshot_date, stage_id, stage_order):
    return {
        "deal_id": deal_id,
        "snapshot_date": snapshot_date,
        "stage_id": stage_id,
        "stage_order": stage_order,
        "pipeline_id": "new_business",
        "owner_email": "rep@gb.io",
        "snapshot_source": "live",
        "backfill_confidence": None,
    }


# Deal B: advanced Discovery → Qualified on Aug 20 (early in window)
# Deal C: advanced Qualified → Proposal on Sep 10 (late in window)
# Deal D: stable Qualified throughout (no change — control)
ROWS_B = {
    AUG_13: _snap_r("deal-B", AUG_13, "stage_disc", 1),
    AUG_20: _snap_r("deal-B", AUG_20, "stage_qual", 2),
    AUG_27: _snap_r("deal-B", AUG_27, "stage_qual", 2),
    SEP_03_R: _snap_r("deal-B", SEP_03_R, "stage_qual", 2),
    SEP_10_R: _snap_r("deal-B", SEP_10_R, "stage_qual", 2),
    SEP_17_R: _snap_r("deal-B", SEP_17_R, "stage_qual", 2),
}
ROWS_C = {
    AUG_13: _snap_r("deal-C", AUG_13, "stage_qual", 2),
    AUG_20: _snap_r("deal-C", AUG_20, "stage_qual", 2),
    AUG_27: _snap_r("deal-C", AUG_27, "stage_qual", 2),
    SEP_03_R: _snap_r("deal-C", SEP_03_R, "stage_qual", 2),
    SEP_10_R: _snap_r("deal-C", SEP_10_R, "stage_qual", 2),
    SEP_17_R: _snap_r("deal-C", SEP_17_R, "stage_prop", 3),
}
ROWS_D = {
    d: _snap_r("deal-D", d, "stage_qual", 2)
    for d in ALL_DATES_REAL
}

BY_DATE_REAL = {
    d: [ROWS_B[d], ROWS_C[d], ROWS_D[d]]
    for d in ALL_DATES_REAL
}


def test_multi_deal_multi_week_captures_all_window_movements():
    """Realistic January-comparison shape: 6 weekly snapshots, 3 deals,
    movements scattered across the window.

    requested_days=35 → prior anchor Aug 13 (35 days before Sep 17).
    Deal B: Discovery on Aug 13, Qualified on Sep 17 → 1 advancement.
    Deal C: Qualified on Aug 13, Proposal on Sep 17 → 1 advancement.
    Deal D: Qualified on Aug 13 and Sep 17 → 0 changes (control).

    Both movements must be captured. Without the anchor fix, comparing the
    last two snapshots (Sep 10 vs Sep 17) would find only Deal C's Sep-10→Sep-17
    jump and miss Deal B (which advanced in week 1 of the window, invisible
    from the last two snapshots alone)."""
    data_gaps = []
    snap_dates, changes = _pm_view_deal_changes(
        BY_DATE_REAL, ALL_DATES_REAL, STAGE_CFG_REAL, data_gaps,
        requested_days=35,
    )
    assert snap_dates == [AUG_13, SEP_17_R], (
        f"Expected [Aug 13, Sep 17] anchors for 35-day window, got {snap_dates!r}"
    )
    advanced = [c for c in changes if c["direction"] == "advanced"]
    deal_ids_advanced = {c["deal_id"] for c in advanced}
    assert "deal-B" in deal_ids_advanced, (
        "Deal B (advanced Discovery→Qualified in week 1) was invisible in the 35-day window. "
        f"Advanced deals found: {deal_ids_advanced!r}"
    )
    assert "deal-C" in deal_ids_advanced, (
        "Deal C (advanced Qualified→Proposal in final week) was not found. "
        f"Advanced deals found: {deal_ids_advanced!r}"
    )
    assert "deal-D" not in deal_ids_advanced, (
        "Deal D (stable Qualified) should not appear as an advancement."
    )
    assert len(advanced) == 2, (
        f"Expected exactly 2 advancements (B and C), got {advanced!r}"
    )
    assert not data_gaps, (
        f"No data_gaps expected (window fits the history), got: {data_gaps!r}"
    )


def test_last_two_misses_early_movement_in_six_week_scenario():
    """Planted-bug control for the 6-week scenario: comparing only the last
    two snapshots (Sep 10 vs Sep 17) silently drops Deal B's movement
    that happened in week 1."""
    prior_date = ALL_DATES_REAL[-2]   # Sep 10
    current_date = ALL_DATES_REAL[-1]  # Sep 17

    prior_b = ROWS_B[prior_date]
    current_b = ROWS_B[current_date]
    # Both show Qualified → hardcoded last-two hides the Discovery→Qualified jump
    assert prior_b["stage_id"] == current_b["stage_id"] == "stage_qual", (
        "Planted-bug baseline: deal B should appear unchanged when comparing "
        "only Sep 10 vs Sep 17 (it advanced weeks earlier)."
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
    test_multi_deal_multi_week_captures_all_window_movements()
    print("PASS: multi-deal 35-day window captures both movements")
    test_last_two_misses_early_movement_in_six_week_scenario()
    print("PASS: planted-bug control for 6-week scenario")
    print("\nAll tests passed.")
