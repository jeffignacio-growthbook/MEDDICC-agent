#!/usr/bin/env python3
"""
Pipeline Coverage Assessor — "how much pipeline coverage do we actually
have against goal, right now."

Answers NORTH_STAR.md's CRO Priority #2. Confirmed 2026-09-19, before
building: query_pipeline()/query_coverage() already compute a coverage
RATIO, but query_coverage() is badly broken in production (divides one
unscoped total pipeline figure against each individual rep's own target,
producing 8,000%+ nonsense) and neither ever weights pipeline by
historical stage-level close-rate performance or reports gap-to-goal
against a real quota+stretch target. This primitive is a fresh
composition, per Jeff's explicit domain specification:

  1. SCOPE: New+Expansion ARR only (is_incremental_pipeline()), renewal
     pipeline excluded. Reuses the existing split — never re-derived.
  2. QUALIFIED PIPELINE ONLY: highest_stage_order_reached >=
     config/client.yaml's pipeline.qualified_stage_order — the exact
     existing qualification boundary query_pipeline()/query_coverage()
     already use, reused here rather than inventing a new one.
  3. STAGE-LEVEL WEIGHTING: each qualified deal's incremental value is
     weighted by its stage's historical close rate
     (forecast_analyses.query_stage_close_rate(), built fresh — no
     existing per-stage close-rate primitive to reuse). A deal at a
     stage whose historical cohort doesn't clear min_evidence_count is
     excluded from the weighted total (unweighted_value/
     unweighted_deal_count), never defaulted to a 1.0 weight.
  4. COVERAGE TARGET IS A CURVE, not a fixed multiple:
     forecast_analyses.query_coverage_proxy_target_by_week() — confirmed
     live that no complete historical quarter ever had a real target, so
     this curve is a HEURISTIC (2x prior-year-same-quarter actual proxy),
     permanently labeled as such, never presented as a real historical
     calibration. See that function's docstring for the full evidence
     picture (a permanent structural ceiling, not a fixable gap).
  5. GAP-TO-GOAL, never a bare ratio: every pipeline-vs-target comparison
     in this primitive's output is phrased "$X short of target" / "$X
     over target".
  6. THE GOAL for the CURRENT quarter (FY2027 Q3) = the REAL stated quota
     (rep_targets team-level target, $1.55M) + a manually-set $2.1M
     stretch figure — a real, explicit GrowthBook business decision (2x
     YoY growth target current headcount can't organically support),
     NOT computed or derived. Lives in config/targets.yaml
     (targets.fy2027_q3.stretch_target/stretch_note), documented there
     with the full WHY. Never assumed to generalize to any future
     client this codebase might serve. This REAL target is read
     directly from config/targets.yaml for the stretch component — it
     has NOT been seeded into the live rep_targets table (seed_targets.py
     only seeds team_total and per-rep targets from config; adding
     stretch_target there would require a live write this build does
     not perform). The quota component (team_total) IS read from the
     live rep_targets table, matching query_pipeline()'s own precedent.

CRITICAL, non-negotiable distinction (never blended, per explicit
instruction): the HISTORICAL curve is a HEURISTIC (proxy-calibrated,
labeled as such everywhere it appears). The CURRENT-quarter real_target
(quota + stretch) is NEVER a heuristic — it is the actual stated goal.

Read-only. No writes.
"""
import sys
from pathlib import Path
from datetime import date
from typing import Optional, Dict, Any
import logging
import yaml

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "analytics"))
sys.path.insert(0, str(REPO_ROOT / "api"))

logger = logging.getLogger(__name__)


def _gap_to_goal(value: Optional[float], goal: Optional[float]) -> Optional[Dict[str, Any]]:
    """Always gap-to-goal phrasing, never a bare ratio. None if either
    input is unavailable (never fabricate a comparison)."""
    if value is None or goal is None:
        return None
    diff = value - goal
    if diff >= 0:
        return {"status": "over", "amount": diff,
                "text": f"${diff:,.0f} over target"}
    return {"status": "short", "amount": -diff,
            "text": f"${-diff:,.0f} short of target"}


def assess_pipeline_coverage(sb, as_of: Optional[date] = None) -> Dict[str, Any]:
    """
    Current-quarter, New+Expansion-only, qualified-pipeline coverage
    assessment: raw and stage-weighted pipeline vs. the REAL stated
    quota+stretch goal (gap-to-goal), plus a HEURISTIC historical
    coverage curve for context.

    Args:
        sb: Supabase client
        as_of: Date to evaluate "today" as (default: date.today()).
               Exposed for testability.

    Returns:
        {"status": "ok", "fiscal_quarter": str, "current_week": int,
         "scope": str,
         "qualified_pipeline": {"raw_value": float, "deal_count": int},
         "stage_weighting": {
             "weighted_value": float, "weighted_deal_count": int,
             "unweighted_value": float, "unweighted_deal_count": int,
             "by_stage_order": {...query_stage_close_rate()'s table...},
             "note": str},
         "real_target": {"quota": float|None, "stretch": float|None,
             "goal": float|None, "stretch_note": str|None, "note": str},
         "gap_to_goal": {"raw_pipeline_vs_goal": {...}|None,
                         "weighted_pipeline_vs_goal": {...}|None},
         "historical_heuristic_curve": {...query_coverage_proxy_target_by_week()'s
             output..., "current_week_ratio": {...}},
         "note": str}
    """
    from utils import get_fiscal_quarter, get_pipeline_config
    from field_semantics import is_incremental_pipeline
    from forecast_analyses import (
        query_stage_close_rate, query_coverage_proxy_target_by_week)
    from snapshot_deals import get_week_of_quarter
    from supabase_client import select_all
    from time_resolver import current_quarter_label

    if as_of is None:
        as_of = date.today()

    q_start, q_end, fiscal_quarter = get_fiscal_quarter(as_of)
    current_week = get_week_of_quarter(as_of, q_start)
    q_start_iso, q_end_iso = q_start.isoformat(), q_end.isoformat()

    pipeline_config = get_pipeline_config()
    qualified_stage_order = pipeline_config.get("qualified_stage_order", 1)

    # 1+2: New+Expansion only, qualified only, Q-scoped by close_date
    # (same q3_scoped_pipeline precedent query_pipeline() uses — a
    # coverage figure must compare against a same-period target).
    deals = select_all(sb, "deals",
        columns="deal_id,pipeline_id,expansion_arr,new_arr,"
                "highest_stage_order_reached,close_date,deal_status")

    qualified_deals = []
    for d in deals:
        if d.get("deal_status") != "active":
            continue
        if not is_incremental_pipeline(d):
            continue
        stage_order = d.get("highest_stage_order_reached") or 0
        if stage_order < qualified_stage_order:
            continue
        close_date = d.get("close_date")
        if not close_date or not (q_start_iso <= str(close_date)[:10] <= q_end_iso):
            continue
        d["_incremental_value"] = (d.get("expansion_arr") or 0) + (d.get("new_arr") or 0)
        d["_stage_order"] = stage_order
        qualified_deals.append(d)

    raw_pipeline_total = sum(d["_incremental_value"] for d in qualified_deals)
    raw_deal_count = len(qualified_deals)

    # 3: stage-level weighting
    stage_rates = query_stage_close_rate(sb)
    by_stage_order = stage_rates.get("by_stage_order", {})

    weighted_total = 0.0
    weighted_deal_count = 0
    unweighted_total = 0.0
    unweighted_deal_count = 0
    for d in qualified_deals:
        stage_row = by_stage_order.get(d["_stage_order"])
        win_rate = stage_row.get("win_rate") if stage_row else None
        if win_rate is None:
            unweighted_total += d["_incremental_value"]
            unweighted_deal_count += 1
        else:
            weighted_total += d["_incremental_value"] * win_rate
            weighted_deal_count += 1

    # 6: REAL current-quarter target. Quota from the live rep_targets
    # table (query_pipeline()'s own precedent); stretch from
    # config/targets.yaml directly (not yet seeded live — see module
    # docstring).
    current_period = current_quarter_label()
    quota = None
    try:
        target_resp = sb.table("rep_targets").select("target_value").eq(
            "period", current_period).eq("level", "team").eq(
            "metric", "incremental_arr").execute()
        if target_resp.data:
            quota = target_resp.data[0].get("target_value")
    except Exception as e:
        logger.warning(f"[PIPELINE_COVERAGE] Failed to fetch team quota: {e}")

    stretch = None
    stretch_note = None
    targets_path = REPO_ROOT / "config" / "targets.yaml"
    if targets_path.exists():
        with open(targets_path) as f:
            targets_cfg = yaml.safe_load(f) or {}
        quarter_key = current_period.lower()
        quarter_cfg = (targets_cfg.get("targets") or {}).get(quarter_key, {})
        stretch = quarter_cfg.get("stretch_target")
        stretch_note = quarter_cfg.get("stretch_note")

    goal = (quota + stretch) if (quota is not None and stretch is not None) else None

    # 5: historical HEURISTIC curve — never blended with the real target.
    proxy_curve = query_coverage_proxy_target_by_week(sb)
    current_week_ratio = proxy_curve.get("by_week", {}).get(current_week, {})

    return {
        "status": "ok",
        "fiscal_quarter": fiscal_quarter,
        "current_week": current_week,
        "scope": ("New+Expansion ARR only (is_incremental_pipeline(), "
                  "renewal pipeline excluded); qualified pipeline only "
                  f"(highest_stage_order_reached >= {qualified_stage_order}); "
                  "Q-scoped by close_date"),
        "qualified_pipeline": {
            "raw_value": raw_pipeline_total,
            "deal_count": raw_deal_count,
        },
        "stage_weighting": {
            "weighted_value": weighted_total,
            "weighted_deal_count": weighted_deal_count,
            "unweighted_value": unweighted_total,
            "unweighted_deal_count": unweighted_deal_count,
            "by_stage_order": by_stage_order,
            "min_evidence_count": stage_rates.get("min_evidence_count"),
            "note": ("Deals at a stage whose historical close-rate cohort "
                     "is below min_evidence_count are excluded from the "
                     "weighted total, not defaulted to a 1.0 weight — see "
                     "unweighted_value/unweighted_deal_count."),
        },
        "real_target": {
            "quota": quota,
            "stretch": stretch,
            "goal": goal,
            "stretch_note": stretch_note,
            "note": ("REAL stated target for the current quarter — quota "
                     "from rep_targets plus a manually-set stretch figure "
                     "from config/targets.yaml (a real, explicit business "
                     "decision, documented there with the full WHY). This "
                     "is NEVER a heuristic — do not conflate it with the "
                     "historical_heuristic_curve below."),
        },
        "gap_to_goal": {
            "raw_pipeline_vs_goal": _gap_to_goal(raw_pipeline_total, goal),
            "weighted_pipeline_vs_goal": _gap_to_goal(weighted_total, goal),
        },
        "historical_heuristic_curve": {
            **proxy_curve,
            "current_week_ratio": current_week_ratio,
        },
        "note": (
            "HEURISTIC: the historical_heuristic_curve above is calibrated "
            "against a 2x-prior-year-actual PROXY target, not a real "
            "historical quota — no complete historical quarter ever had "
            "one. It rests on a permanent structural evidence ceiling (see "
            "that field's own note) and must always be labeled a HEURISTIC "
            "wherever it is surfaced, never 'directional' or 'approximate'. "
            "The real_target and gap_to_goal above use the REAL stated "
            f"{fiscal_quarter} quota+stretch target and are never "
            "heuristics — the two must never be conflated."
        ),
    }


if __name__ == "__main__":
    from db import get_supabase
    sb = get_supabase()
    import json
    print(json.dumps(assess_pipeline_coverage(sb), indent=2, default=str))
