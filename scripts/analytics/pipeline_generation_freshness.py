#!/usr/bin/env python3
"""
Pipeline-generation freshness guard + snapshot fallback.

HIGH-SEVERITY anti-silent-failure guard for "new pipeline generated" (the
waterfall's new_pipeline_value). That metric keys on deals.qualified_date, a
materialized event column that the live ETL does not maintain — when it goes
stale (its last seed run freezes it) every subsequent qualification crossing
reads as $0, which on 2026-09-26 produced a false "$0 new pipeline for 7 weeks
-> review SDR metrics" while ~$5.74M / 58 deals had actually crossed.

The guard: compare max(qualified_date) against the latest snapshot_date. If it
lags by more than a tolerance, DO NOT trust the column-derived number — recompute
new-pipeline directly from deals_snapshot stage-crossing history (the source of
truth) and state which basis was used. A maintenance gap then degrades to
slower-but-correct, never silent-but-empty.

Pure functions here are unit-tested against the real crossings fixture
(tests/fixtures/pipeline_generation_crossings_fy2027q3.json). compute_waterfall
calls new_pipeline_with_basis(); the backfill and the ETL maintainer keep
qualified_date current so the fresh path is the norm.
"""
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

DEFAULT_TOLERANCE_DAYS = 8  # one weekly snapshot cadence + a day of slack


def _d(iso: str) -> date:
    return date.fromisoformat(str(iso)[:10])


def iso_week_monday(iso: str) -> str:
    d = _d(iso)
    return (d - timedelta(days=d.weekday())).isoformat()


def crossings_from_snapshots(snapshot_rows: List[dict], *, threshold: int = 1) -> Dict[str, str]:
    """{deal_id: first_crossing_date} — the earliest snapshot_date at which each
    deal was seen at stage_order >= threshold (the qualification crossing). The
    source-of-truth derivation, independent of deals.qualified_date."""
    first: Dict[str, str] = {}
    for r in snapshot_rows:
        so = r.get("stage_order")
        if so is None or so < threshold:
            continue
        did = str(r.get("deal_id"))
        day = str(r.get("snapshot_date"))[:10]
        if did not in first or day < first[did]:
            first[did] = day
    return first


def weekly_new_pipeline(crossings: Dict[str, str], incremental_arr_by_deal: Dict[str, float], *,
                        start: str, end: str) -> Dict[str, Any]:
    """Aggregate crossings whose date is within [start, end] into ISO-week
    (Monday-keyed) buckets: {week: {deals, incremental_arr}} plus a total."""
    weekly: Dict[str, Dict[str, float]] = {}
    tot_deals = 0
    tot_arr = 0.0
    for did, cdate in crossings.items():
        c = str(cdate)[:10]
        if c < start or c > end:
            continue
        wk = iso_week_monday(c)
        b = weekly.setdefault(wk, {"deals": 0, "incremental_arr": 0.0})
        b["deals"] += 1
        b["incremental_arr"] += float(incremental_arr_by_deal.get(did, 0) or 0)
        tot_deals += 1
        tot_arr += float(incremental_arr_by_deal.get(did, 0) or 0)
    # normalize arr to int where whole (the fixture/DB values are whole dollars)
    for b in weekly.values():
        b["incremental_arr"] = int(round(b["incremental_arr"]))
    return {
        "weekly": dict(sorted(weekly.items())),
        "total": {"deals": tot_deals, "incremental_arr": int(round(tot_arr))},
    }


def is_qualified_date_stale(max_qualified_date: Optional[str], latest_snapshot_date: str, *,
                            tolerance_days: int = DEFAULT_TOLERANCE_DAYS) -> bool:
    """True when qualified_date can no longer be trusted for new-pipeline: it is
    missing entirely, or its max lags the latest snapshot by more than
    tolerance_days (a maintenance gap)."""
    if not max_qualified_date:
        return True
    return (_d(latest_snapshot_date) - _d(max_qualified_date)).days > tolerance_days


def new_pipeline_with_basis(*, column_weekly: Dict[str, Any],
                            max_qualified_date: Optional[str], latest_snapshot_date: str,
                            snapshot_crossings: Dict[str, str],
                            incremental_arr_by_deal: Dict[str, float],
                            start: str, end: str,
                            threshold: int = 1,
                            tolerance_days: int = DEFAULT_TOLERANCE_DAYS) -> Dict[str, Any]:
    """Return new-pipeline weekly/total with an explicit basis. Uses the
    qualified_date column when fresh; when stale, recomputes from
    deals_snapshot crossings and says so — never silently reports the empty
    column number.
    """
    stale = is_qualified_date_stale(max_qualified_date, latest_snapshot_date,
                                    tolerance_days=tolerance_days)
    if stale:
        computed = weekly_new_pipeline(snapshot_crossings, incremental_arr_by_deal,
                                       start=start, end=end)
        basis = "deals_snapshot_crossings"
        statement = (
            f"deals.qualified_date is stale (max {max_qualified_date or 'none'} vs latest "
            f"snapshot {latest_snapshot_date}); new-pipeline recomputed from deals_snapshot "
            f"stage-crossing history (source of truth), not the frozen column.")
        return {"stale": True, "basis": basis, "basis_statement": statement,
                "weekly": computed["weekly"], "total": computed["total"]}
    return {"stale": False, "basis": "qualified_date_column",
            "basis_statement": (f"deals.qualified_date is current (max {max_qualified_date} vs "
                                f"latest snapshot {latest_snapshot_date}); new-pipeline from "
                                f"qualified_date."),
            "weekly": column_weekly.get("weekly", {}),
            "total": column_weekly.get("total", {"deals": 0, "incremental_arr": 0})}
