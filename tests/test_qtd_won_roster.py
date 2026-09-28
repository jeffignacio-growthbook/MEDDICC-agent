"""
QTD closed-won roster — guards against gap-basis drift.

Source of truth: Supabase query on 2026-09-28 for deals
  WHERE deal_status = 'won'
  AND close_date >= '2026-08-01'  (Q3 FY2027 start)
  AND close_date <= '2026-09-28'  (today)

10 won deals total; 9 pass is_incremental_pipeline (new_arr + expansion_arr > 0).
$447,775 total incremental ARR from 9 deals.

Why $373,400 appeared in the 2026-09-26 live validation
-------------------------------------------------------
Deal 65027814314 (close_date=2026-09-25, new_arr=$74,375) was not yet synced to
the DB when validation ran on 2026-09-26. The handler is correct; $373,400 was
a stale-DB artifact, not a handler bug.

Deal excluded (renewal, $0 incremental)
---------------------------------------
44452371744 | pipeline_id=866608541 (renewal) | new_arr=0 | expansion_arr=0
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.field_semantics import is_incremental_pipeline
from api.incremental_arr import incremental_arr

# ---------------------------------------------------------------------------
# Fixture — 10 QTD won deals, Q3 FY2027 (Aug 1 – Oct 31, 2026), as of 2026-09-28
# ---------------------------------------------------------------------------
_QTD_WON_DEALS = [
    {
        "deal_id": "63222153531",
        "close_date": "2026-08-03",
        "pipeline_id": "default",
        "deal_status": "won",
        "new_arr": 0,
        "expansion_arr": 2400,
    },
    {
        "deal_id": "59860100786",
        "close_date": "2026-08-18",
        "pipeline_id": "default",
        "deal_status": "won",
        "new_arr": 20000,
        "expansion_arr": 0,
    },
    {
        "deal_id": "57977964601",
        "close_date": "2026-08-24",
        "pipeline_id": "default",
        "deal_status": "won",
        "new_arr": 30000,
        "expansion_arr": 0,
    },
    {
        "deal_id": "58630730677",
        "close_date": "2026-08-28",
        "pipeline_id": "default",
        "deal_status": "won",
        "new_arr": 0,
        "expansion_arr": 50000,
    },
    {
        "deal_id": "62121618183",
        "close_date": "2026-09-01",
        "pipeline_id": "default",
        "deal_status": "won",
        "new_arr": 95000,
        "expansion_arr": 0,
    },
    {
        "deal_id": "64307147547",
        "close_date": "2026-09-08",
        "pipeline_id": "default",
        "deal_status": "won",
        "new_arr": 30000,
        "expansion_arr": 0,
    },
    {
        "deal_id": "63222360840",
        "close_date": "2026-09-10",
        "pipeline_id": "default",
        "deal_status": "won",
        "new_arr": 0,
        "expansion_arr": 95000,
    },
    {
        "deal_id": "44452371744",  # renewal pipeline — excluded
        "close_date": "2026-09-16",
        "pipeline_id": "866608541",
        "deal_status": "won",
        "new_arr": 0,
        "expansion_arr": 0,
    },
    {
        "deal_id": "60868340629",
        "close_date": "2026-09-23",
        "pipeline_id": "default",
        "deal_status": "won",
        "new_arr": 51000,
        "expansion_arr": 0,
    },
    {
        "deal_id": "65027814314",  # synced after 2026-09-26 validation
        "close_date": "2026-09-25",
        "pipeline_id": "default",
        "deal_status": "won",
        "new_arr": 74375,
        "expansion_arr": 0,
    },
]

_EXPECTED_TOTAL = 447_775.0
_EXPECTED_INCREMENTAL_COUNT = 9
_RENEWAL_DEAL_ID = "44452371744"
_LATE_SYNC_DEAL_ID = "65027814314"
_LATE_SYNC_ARR = 74_375.0
_VALIDATION_TOTAL = 373_400.0  # pre-sync total (2026-09-26)


def test_roster_total_deals():
    assert len(_QTD_WON_DEALS) == 10, "Fixture must have exactly 10 QTD won deals"


def test_incremental_filter_excludes_renewal():
    """Renewal deal (pipeline 866608541, $0 ARR) must be excluded."""
    renewal = next(d for d in _QTD_WON_DEALS if d["deal_id"] == _RENEWAL_DEAL_ID)
    assert not is_incremental_pipeline(renewal), (
        f"Renewal deal {_RENEWAL_DEAL_ID} should fail is_incremental_pipeline "
        f"(new_arr={renewal['new_arr']}, expansion_arr={renewal['expansion_arr']})"
    )


def test_incremental_count():
    """9 of 10 won deals pass is_incremental_pipeline."""
    incremental = [d for d in _QTD_WON_DEALS if is_incremental_pipeline(d)]
    assert len(incremental) == _EXPECTED_INCREMENTAL_COUNT, (
        f"Expected {_EXPECTED_INCREMENTAL_COUNT} incremental deals, "
        f"got {len(incremental)}"
    )


def test_incremental_total():
    """Sum of incremental ARR = $447,775."""
    total = sum(
        incremental_arr(d) for d in _QTD_WON_DEALS if is_incremental_pipeline(d)
    )
    assert abs(total - _EXPECTED_TOTAL) < 1.0, (
        f"QTD incremental ARR = {total:,.0f}, expected {_EXPECTED_TOTAL:,.0f}"
    )


def test_late_sync_deal_present():
    """Deal 65027814314 is in the roster (explains $373,400 vs $447,775 delta)."""
    ids = {d["deal_id"] for d in _QTD_WON_DEALS}
    assert _LATE_SYNC_DEAL_ID in ids, (
        f"Deal {_LATE_SYNC_DEAL_ID} must be in the fixture"
    )


def test_late_sync_deal_arr():
    """Deal 65027814314 contributes $74,375 = $447,775 - $373,400."""
    late = next(d for d in _QTD_WON_DEALS if d["deal_id"] == _LATE_SYNC_DEAL_ID)
    arr = incremental_arr(late)
    assert abs(arr - _LATE_SYNC_ARR) < 1.0, (
        f"Late-sync deal ARR = {arr:,.0f}, expected {_LATE_SYNC_ARR:,.0f}"
    )
    delta = _EXPECTED_TOTAL - _VALIDATION_TOTAL
    assert abs(arr - delta) < 1.0, (
        f"Late-sync ARR {arr:,.0f} ≠ delta {delta:,.0f} "
        f"($447,775 - $373,400); fixture mismatch"
    )


def test_validation_total_without_late_sync():
    """Excluding the late-sync deal gives $373,400 (the 2026-09-26 stale-DB figure)."""
    total = sum(
        incremental_arr(d)
        for d in _QTD_WON_DEALS
        if is_incremental_pipeline(d) and d["deal_id"] != _LATE_SYNC_DEAL_ID
    )
    assert abs(total - _VALIDATION_TOTAL) < 1.0, (
        f"Pre-sync total = {total:,.0f}, expected {_VALIDATION_TOTAL:,.0f}"
    )
