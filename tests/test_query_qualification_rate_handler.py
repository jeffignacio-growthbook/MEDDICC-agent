"""
query_qualification_rate handler — Step A/B/D tests (tests-first, offline-capable).

Wraps qualification_crossing_walk.walk() + summarise() — reads deals_snapshot
(default pipeline) + deals (deal_id, deal_status, close_date, company_name).
Returns walk() result dict verbatim.

STEP A — handler callable with empty params dict (no required params).
STEP B — appears in HANDLER_DESCRIPTIONS with meaningful description.
STEP D — planted-bug controls: conversion rate and outcome counts must be
         computed correctly; a deal first seen at a qualified stage (never
         observed crossing from Meeting Set) must not count as a crosser.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "analytics"))

import api.handlers as handlers_module
import api.router as router
from qualification_crossing_walk import walk, MEETING_SET, QUALIFIED_STAGES


# ---------------------------------------------------------------------------
# Strict fake Supabase
# ---------------------------------------------------------------------------

class _FakeSupabase:
    def __init__(self, snapshot_rows=None, deal_rows=None):
        self._snapshot_rows = snapshot_rows or []
        self._deal_rows = deal_rows or []
        self._current_table = None

    def table(self, name):
        self._current_table = name
        return self

    def select(self, *args, **kwargs):
        return self

    def eq(self, col, val):
        return self

    def in_(self, col, vals):
        return self

    def range(self, start, end):
        self._range_start = start
        self._range_end = end
        return self

    def execute(self):
        class _R:
            pass
        r = _R()
        if self._current_table == "deals_snapshot":
            rows = self._snapshot_rows
        elif self._current_table == "deals":
            rows = self._deal_rows
        else:
            rows = []
        start = getattr(self, "_range_start", 0)
        end = getattr(self, "_range_end", max(len(rows) - 1, 0))
        r.data = rows[start:end + 1]
        return r


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fixtures: snapshot rows and deal rows
# ---------------------------------------------------------------------------

def _snap(deal_id, snapshot_date, stage_id, pipeline_id="default"):
    return {
        "deal_id": deal_id,
        "snapshot_date": snapshot_date,
        "stage_id": stage_id,
        "pipeline_id": pipeline_id,
        "snapshot_source": "live",
        "backfill_confidence": None,
    }


def _deal(deal_id, company_name, deal_status, close_date=None):
    return {
        "deal_id": deal_id,
        "company_name": company_name,
        "deal_status": deal_status,
        "close_date": close_date,
    }


# Deal that crossed from Meeting Set → qualified → won
SNAP_CROSSER_MS = _snap("deal-1", "2026-01-01", MEETING_SET)
SNAP_CROSSER_Q = _snap("deal-1", "2026-01-07", QUALIFIED_STAGES[0])  # within pin_days
DEAL_CROSSER_WON = _deal("deal-1", "AlphaCorp", "won", "2026-03-01")

# Deal stuck at Meeting Set — never qualified
SNAP_STUCK_MS = _snap("deal-2", "2026-01-01", MEETING_SET)
SNAP_STUCK_MS2 = _snap("deal-2", "2026-01-15", MEETING_SET)
DEAL_STUCK = _deal("deal-2", "BetaCorp", "active")

# Deal first seen at qualified stage — should NOT be a crosser
SNAP_FIRST_QUAL = _snap("deal-3", "2026-01-01", QUALIFIED_STAGES[0])
DEAL_FIRST_QUAL_LOST = _deal("deal-3", "GammaCorp", "lost", "2026-02-01")

# Deal on a different pipeline — should be ignored
SNAP_RENEWAL = _snap("deal-4", "2026-01-01", MEETING_SET, pipeline_id="renewal")
DEAL_RENEWAL = _deal("deal-4", "DeltaCorp", "active")


# ---------------------------------------------------------------------------
# Step A — parameter completeness
# ---------------------------------------------------------------------------

def test_step_a_handler_exists():
    assert hasattr(handlers_module, "query_qualification_rate"), (
        "query_qualification_rate not found in handlers module — implement it"
    )


def test_step_a_accepts_empty_params():
    fn = getattr(handlers_module, "query_qualification_rate", None)
    if fn is None:
        pytest.skip("handler not yet implemented")
    sb = _FakeSupabase(snapshot_rows=[], deal_rows=[])
    result = _run(fn({}, sb))
    assert isinstance(result, dict)


def test_step_a_returns_crossings_key():
    fn = getattr(handlers_module, "query_qualification_rate", None)
    if fn is None:
        pytest.skip("handler not yet implemented")
    sb = _FakeSupabase(snapshot_rows=[], deal_rows=[])
    result = _run(fn({}, sb))
    assert "crossings" in result, f"Missing 'crossings' key: {result.keys()}"
    assert "summary" in result


# ---------------------------------------------------------------------------
# Step B — registry registration
# ---------------------------------------------------------------------------

def test_step_b_in_handler_descriptions():
    registry = getattr(router, "HANDLER_DESCRIPTIONS", {})
    assert "query_qualification_rate" in registry, (
        f"'query_qualification_rate' missing from HANDLER_DESCRIPTIONS"
    )


def test_step_b_description_mentions_qualification():
    registry = getattr(router, "HANDLER_DESCRIPTIONS", {})
    desc = registry.get("query_qualification_rate", "").lower()
    assert any(kw in desc for kw in ["qualification", "qualify", "meeting set", "qualified"]), (
        f"Description not meaningful for qualification handler: {desc!r}"
    )


# ---------------------------------------------------------------------------
# Step D — planted-bug controls + walk() unit tests
# ---------------------------------------------------------------------------

def test_step_d_crosser_counted_correctly():
    """A deal that goes Meeting Set -> qualified (within pin_days) must appear in crossings."""
    result = walk(
        [SNAP_CROSSER_MS, SNAP_CROSSER_Q],
        [DEAL_CROSSER_WON],
    )
    assert result["summary"]["crossers"] == 1
    assert result["summary"]["won"] == 1
    assert len(result["crossings"]) == 1
    assert result["crossings"][0]["deal_id"] == "deal-1"
    assert result["crossings"][0]["pinned"] is True  # gap = 6 days <= 7


def test_step_d_stuck_deal_not_a_crosser():
    """A deal stuck at Meeting Set is not a crosser — only counted in ever_meeting_set."""
    result = walk(
        [SNAP_STUCK_MS, SNAP_STUCK_MS2],
        [DEAL_STUCK],
    )
    assert result["summary"]["crossers"] == 0
    assert result["summary"]["ever_meeting_set"] == 1
    assert len(result["crossings"]) == 0


def test_step_d_first_seen_qualified_not_a_crosser():
    """Planted bug: a deal first seen at a qualified stage (no Meeting Set row) must NOT
    be counted as a crosser even though it has a qualifying stage."""
    result = walk(
        [SNAP_FIRST_QUAL],
        [DEAL_FIRST_QUAL_LOST],
    )
    assert result["summary"]["crossers"] == 0
    # It should be counted in never_meeting_set
    assert result["summary"]["never_meeting_set"] >= 1


def test_step_d_renewal_pipeline_ignored():
    """Deals on pipelines other than 'default' must not be counted."""
    result = walk(
        [SNAP_RENEWAL],
        [DEAL_RENEWAL],
    )
    assert result["summary"]["deals_seen"] == 0
    assert result["summary"]["crossers"] == 0


def test_step_d_full_scenario_mixed():
    """Full scenario: crosser, stuck, first-seen-qual, renewal — check each bucket."""
    snaps = [
        SNAP_CROSSER_MS, SNAP_CROSSER_Q,  # deal-1: crosser, won
        SNAP_STUCK_MS, SNAP_STUCK_MS2,    # deal-2: stuck at Meeting Set
        SNAP_FIRST_QUAL,                   # deal-3: first seen qualified
        SNAP_RENEWAL,                      # deal-4: renewal pipeline (ignored)
    ]
    deals = [DEAL_CROSSER_WON, DEAL_STUCK, DEAL_FIRST_QUAL_LOST, DEAL_RENEWAL]
    result = walk(snaps, deals)

    s = result["summary"]
    # Only default pipeline deals counted
    assert s["deals_seen"] == 3  # deal-1, deal-2, deal-3
    assert s["ever_meeting_set"] == 2  # deal-1, deal-2
    assert s["crossers"] == 1  # only deal-1
    assert s["won"] == 1
    assert s["lost"] == 0
    assert s["never_meeting_set"] >= 1  # deal-3


def test_step_d_win_rate_correct():
    """Win rate = won / (won + lost) — open deals not in denominator."""
    # 2 crossers: 1 won, 1 lost
    SNAP_C1_MS = _snap("c1", "2026-01-01", MEETING_SET)
    SNAP_C1_Q = _snap("c1", "2026-01-06", QUALIFIED_STAGES[0])
    SNAP_C2_MS = _snap("c2", "2026-01-01", MEETING_SET)
    SNAP_C2_Q = _snap("c2", "2026-01-06", QUALIFIED_STAGES[0])
    deals = [
        _deal("c1", "Corp1", "won", "2026-03-01"),
        _deal("c2", "Corp2", "lost", "2026-02-01"),
    ]
    result = walk([SNAP_C1_MS, SNAP_C1_Q, SNAP_C2_MS, SNAP_C2_Q], deals)
    s = result["summary"]
    assert s["won"] == 1
    assert s["lost"] == 1
    assert s["resolved"] == 2
