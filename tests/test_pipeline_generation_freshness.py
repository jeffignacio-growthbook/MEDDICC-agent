#!/usr/bin/env python3
"""
Pipeline-generation freshness guard + snapshot fallback — tests first.

HIGH-SEVERITY regression guard. waterfall_weekly reported $0 new pipeline for
7 straight weeks (Aug 17 - Sep 21 2026) while ~$5.74M / 58 deals actually
crossed into qualified pipeline. Root cause: the waterfall keys "new pipeline"
on deals.qualified_date, a materialized event column that NOTHING in the live
ETL maintains — it froze at its last seed run (max = 2026-08-07). So every
crossing since read as $0, producing a false "review SDR metrics" recommendation.

The guard: if qualified_date is stale relative to the latest snapshot, DO NOT
report the (wrong, empty) column-derived number. Recompute new-pipeline directly
from deals_snapshot stage-crossing history — the source of truth this bug was
found with — and say which basis was used. A future maintenance gap then
degrades to slower-but-correct, never silent-but-empty.

Real pinned fixture: tests/fixtures/pipeline_generation_crossings_fy2027q3.json
(58 real crossings, $5,736,921, the exact weeks that wrongly showed $0).
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))

from pipeline_generation_freshness import (
    crossings_from_snapshots, iso_week_monday, weekly_new_pipeline,
    is_qualified_date_stale, new_pipeline_with_basis,
)

FX = json.loads((REPO / "tests" / "fixtures"
                 / "pipeline_generation_crossings_fy2027q3.json").read_text())


# ---- crossings_from_snapshots (source-of-truth derivation) ---------------

def test_crossing_is_first_snapshot_at_or_above_threshold():
    snaps = [
        {"deal_id": "A", "snapshot_date": "2026-08-03", "stage_order": 0},  # Meeting Set
        {"deal_id": "A", "snapshot_date": "2026-08-17", "stage_order": 2},  # crosses here
        {"deal_id": "A", "snapshot_date": "2026-08-24", "stage_order": 3},
        {"deal_id": "B", "snapshot_date": "2026-08-10", "stage_order": 0},  # never crosses
    ]
    c = crossings_from_snapshots(snaps, threshold=1)
    assert c == {"A": "2026-08-17"}, c  # B excluded; A's first qualified snapshot


def test_iso_week_monday_buckets():
    assert iso_week_monday("2026-08-17") == "2026-08-17"  # Monday
    assert iso_week_monday("2026-08-19") == "2026-08-17"  # Wed -> same week
    assert iso_week_monday("2026-08-30") == "2026-08-24"  # Sun -> week of Mon 24


# ---- weekly aggregation reproduces the real numbers ---------------------

def test_weekly_new_pipeline_matches_real_fixture():
    crossings = {r["deal_id"]: r["crossing_date"] for r in FX["crossings"]}
    arr = {r["deal_id"]: r["incremental_arr"] for r in FX["crossings"]}
    wk = weekly_new_pipeline(crossings, arr, start="2026-08-11", end="2026-09-21")
    for week, exp in FX["expected_weekly"].items():
        assert wk["weekly"][week]["deals"] == exp["deals"], (week, wk["weekly"][week])
        assert wk["weekly"][week]["incremental_arr"] == exp["incremental_arr"], week
    assert wk["total"]["deals"] == FX["expected_total"]["deals"]
    assert wk["total"]["incremental_arr"] == FX["expected_total"]["incremental_arr"]
    # NOT the false $0
    assert wk["total"]["incremental_arr"] > 5_000_000


# ---- staleness detector -------------------------------------------------

def test_stale_when_qualified_date_lags_latest_snapshot():
    # the real bug: max qualified_date 2026-08-07, latest snapshot 2026-09-21
    assert is_qualified_date_stale("2026-08-07", "2026-09-21", tolerance_days=8) is True
    # fresh: within tolerance
    assert is_qualified_date_stale("2026-09-18", "2026-09-21", tolerance_days=8) is False
    # None qualified_date is stale by definition
    assert is_qualified_date_stale(None, "2026-09-21", tolerance_days=8) is True


# ---- the guard: fallback to snapshot when stale, with basis -------------

def test_guard_falls_back_to_snapshot_and_states_basis():
    crossings = {r["deal_id"]: r["crossing_date"] for r in FX["crossings"]}
    arr = {r["deal_id"]: r["incremental_arr"] for r in FX["crossings"]}
    # column path would report $0 (stale/empty); guard must detect and recompute
    r = new_pipeline_with_basis(
        column_weekly={},                       # what the stale column yields: nothing
        max_qualified_date="2026-08-07",
        latest_snapshot_date="2026-09-21",
        snapshot_crossings=crossings, incremental_arr_by_deal=arr,
        start="2026-08-11", end="2026-09-21", tolerance_days=8)
    assert r["stale"] is True
    assert r["basis"] == "deals_snapshot_crossings"
    assert r["total"]["incremental_arr"] == FX["expected_total"]["incremental_arr"]
    assert "stale" in r["basis_statement"].lower()
    assert "snapshot" in r["basis_statement"].lower()


def test_guard_uses_column_when_fresh():
    fresh_weekly = {"weekly": {"2026-09-21": {"deals": 2, "incremental_arr": 111}},
                    "total": {"deals": 2, "incremental_arr": 111}}
    r = new_pipeline_with_basis(
        column_weekly=fresh_weekly,
        max_qualified_date="2026-09-20", latest_snapshot_date="2026-09-21",
        snapshot_crossings={}, incremental_arr_by_deal={},
        start="2026-08-11", end="2026-09-21", tolerance_days=8)
    assert r["stale"] is False
    assert r["basis"] == "qualified_date_column"
    assert r["total"]["incremental_arr"] == 111


# ---- maintainer: fills NULLs only, never overwrites ---------------------

def test_maintainer_fills_nulls_only():
    from backfill_qualified_date import rows_needing_qualified_date
    deals = [
        {"deal_id": "A", "qualified_date": None},          # null → fill
        {"deal_id": "B", "qualified_date": "2026-07-01"},  # seeded (finer) → keep
        {"deal_id": "C", "qualified_date": ""},            # empty → fill
    ]
    snaps = [
        {"deal_id": "A", "snapshot_date": "2026-08-17", "stage_order": 2},
        {"deal_id": "B", "snapshot_date": "2026-08-24", "stage_order": 2},  # differs, but B kept
        {"deal_id": "C", "snapshot_date": "2026-09-07", "stage_order": 3},
        {"deal_id": "D", "snapshot_date": "2026-09-07", "stage_order": 0},  # never crossed
    ]
    out = dict(rows_needing_qualified_date(deals, snaps, threshold=1))
    assert out == {"A": "2026-08-17", "C": "2026-09-07"}, out  # B not overwritten, D excluded


if __name__ == "__main__":
    import inspect
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            fn(); print(f"✓ {name}")
    print("\n✅ All tests passed")
