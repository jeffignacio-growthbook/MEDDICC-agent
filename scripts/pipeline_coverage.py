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
against a real quota target. This primitive is a fresh
composition, per Jeff's explicit domain specification:

  1. SCOPE: New+Expansion ARR only (is_incremental_pipeline()), renewal
     pipeline excluded. Reuses the existing split — never re-derived.
  2. QUALIFIED PIPELINE ONLY: a Sales-pipeline deal whose CURRENT stage
     is Discovery through Awaiting Signature
     (loss_concentration.discovery_or_later_stages(): config order >=
     qualified_stage_order, not won/lost, not exclude_from_analysis, so
     not Meeting Set or Review). Until 2026-09-25 this read
     highest_stage_order_reached, a high-water mark (see 3).
  3. STAGE-LEVEL WEIGHTING: each qualified deal's incremental value is
     weighted by its stage's historical close rate
     (forecast_analyses.query_stage_close_rate(), built fresh — no
     existing per-stage close-rate primitive to reuse). A deal at a
     stage whose historical cohort doesn't clear min_evidence_count is
     excluded from the weighted total (unweighted_value/
     unweighted_deal_count), never defaulted to a 1.0 weight.
     The rate is looked up by the config order of the deal's CURRENT
     stage: the table is built from deals_snapshot.stage_order, the stage
     a deal was in. It used highest_stage_order_reached, which keyed 16 of
     44 live FY2027 Q3 deals ($2,106,050) to a stage they were not in
     (weighted $1,231,113 instead of $701,826). Renewal-pipeline expansion
     has no governed rate (the table is Sales, New+Expansion only): it is
     reported as renewal_not_weighted, never given a Sales stage's rate.
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
  6. THE GOAL for the CURRENT quarter (FY2027 Q3) = the team quota
     (rep_targets team-level target, $1.55M). This is the minimum
     committed target the team is measured against.
     Stretch ($2.1M, config/targets.yaml) is Ryan's personal
     aspiration (2x YoY growth) — it is NOT additive on top of
     quota, and is reported separately as context, never summed
     into goal. The quota (team_total) is read from the live
     rep_targets table, matching query_pipeline()'s own precedent.

CRITICAL, non-negotiable distinction (never blended, per explicit
instruction): the HISTORICAL curve is a HEURISTIC (proxy-calibrated,
labeled as such everywhere it appears). The CURRENT-quarter real_target
(quota) is NEVER a heuristic — it is the actual stated goal.

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
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root
from api.incremental_arr import incremental_arr  # the one Incremental ARR definition

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


def _normalize_quarter_label(raw: str) -> str:
    """Normalize fiscal quarter labels to the 'FY2027 Q3' format used
    by deals_snapshot.  Accepts 'Q3_FY2027', 'FY2027Q3', 'FY2027 Q3',
    'q3_fy2027', 'Q2' (infers current FY)."""
    import re
    raw = raw.strip().upper().replace("_", " ")
    m = re.match(r'^(FY\d{4})\s*(Q[1-4])$', raw)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    m = re.match(r'^(Q[1-4])\s*(FY\d{4})$', raw)
    if m:
        return f"{m.group(2)} {m.group(1)}"
    m = re.match(r'^(Q[1-4])$', raw)
    if m:
        from utils import get_fiscal_quarter
        _, _, current_label = get_fiscal_quarter(date.today())
        fy = current_label.split()[0]
        return f"{fy} {m.group(1)}"
    return raw


def _period_label_for_quarter(fiscal_quarter: str) -> str:
    """Convert 'FY2027 Q3' to the rep_targets period format 'FY2027_Q3'."""
    return fiscal_quarter.replace(" ", "_")


def _is_current_quarter(fiscal_quarter: str) -> bool:
    """Return True if fiscal_quarter matches today's quarter."""
    from utils import get_fiscal_quarter
    _, _, current = get_fiscal_quarter(date.today())
    return _normalize_quarter_label(fiscal_quarter) == current


def _load_snapshot_deals(sb, fiscal_quarter: str) -> list:
    """Load deal state from deals_snapshot for a completed quarter.

    Reads the latest available week for the given fiscal_quarter from
    deals_snapshot, then joins new_arr/expansion_arr from the deals
    table (ARR fields are not stored in the snapshot).
    """
    from supabase_client import select_all

    snapshots = select_all(sb, "deals_snapshot",
        columns="deal_id,pipeline_id,stage_order,close_date,deal_status,week_of_quarter",
        filters=[("eq", "fiscal_quarter", fiscal_quarter)])
    if not snapshots:
        return []

    max_week = max(s.get("week_of_quarter", 0) for s in snapshots)
    end_of_q = [s for s in snapshots if s.get("week_of_quarter") == max_week]
    logger.info("[PIPELINE_COVERAGE] historical %s: %d snapshot rows at week %d",
                fiscal_quarter, len(end_of_q), max_week)

    deal_ids = list({s["deal_id"] for s in end_of_q})
    deals_lookup: dict = {}
    for batch_start in range(0, len(deal_ids), 50):
        batch = deal_ids[batch_start:batch_start + 50]
        rows = select_all(sb, "deals",
            columns="deal_id,new_arr,expansion_arr",
            filters=[("in_", "deal_id", batch)])
        for r in rows:
            deals_lookup[r["deal_id"]] = r

    enriched = []
    for s in end_of_q:
        deal_row = deals_lookup.get(s["deal_id"], {})
        enriched.append({
            "deal_id": s["deal_id"],
            "pipeline_id": s.get("pipeline_id"),
            "stage_order": s.get("stage_order"),
            "close_date": s.get("close_date"),
            "deal_status": s.get("deal_status"),
            "new_arr": deal_row.get("new_arr"),
            "expansion_arr": deal_row.get("expansion_arr"),
        })
    return enriched


def assess_pipeline_coverage(
    sb, as_of: Optional[date] = None, fiscal_quarter: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Pipeline-coverage assessment: New+Expansion-only, qualified-pipeline
    coverage vs. the stated team quota (gap-to-goal), plus a
    HEURISTIC historical coverage curve for context.

    Accepts an optional fiscal_quarter (e.g. 'FY2027 Q2') to assess a
    past quarter from deals_snapshot.  Defaults to the current quarter
    when omitted.

    Args:
        sb: Supabase client
        as_of: Date to evaluate "today" as (default: date.today()).
               Exposed for testability.  Ignored when fiscal_quarter
               names a past quarter.
        fiscal_quarter: Optional fiscal quarter label (e.g. 'FY2027 Q2',
               'Q2', 'Q2_FY2027').  When omitted, uses the quarter
               containing as_of.

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

    # Determine which quarter we're assessing
    is_historical = False
    if fiscal_quarter:
        fiscal_quarter = _normalize_quarter_label(fiscal_quarter)
        if not _is_current_quarter(fiscal_quarter):
            is_historical = True

    if not fiscal_quarter or not is_historical:
        q_start, q_end, fiscal_quarter = get_fiscal_quarter(as_of)
        current_week = get_week_of_quarter(as_of, q_start)
    else:
        from time_resolver import resolve_time_window
        tw = resolve_time_window({"period": "fiscal_quarter",
                                  "fiscal_quarter": fiscal_quarter})
        q_start = date.fromisoformat(tw["start"])
        q_end = date.fromisoformat(tw["end"])
        current_week = 13

    q_start_iso, q_end_iso = q_start.isoformat(), q_end.isoformat()

    from loss_concentration import SALES_PIPELINE, discovery_or_later_stages
    pipeline_config = get_pipeline_config()
    qualifying = set(discovery_or_later_stages(pipeline_config))
    stage_order_of = {str(s["id"]): s.get("order")
                      for p in pipeline_config.get("pipelines", [])
                      if str(p.get("id")) == SALES_PIPELINE for s in p.get("stages", [])}
    qualifying_orders = {o for o in stage_order_of.values() if o is not None}

    if is_historical:
        raw_deals = _load_snapshot_deals(sb, fiscal_quarter)
    else:
        raw_deals = select_all(sb, "deals",
            columns="deal_id,pipeline_id,stage,expansion_arr,new_arr,close_date,deal_status",
            filters=[("eq", "deal_status", "active"),
                     ("gte", "close_date", q_start_iso),
                     ("lte", "close_date", q_end_iso)])

    qualified_deals, renewal_deals = [], []
    for d in raw_deals:
        if is_historical:
            if d.get("deal_status") not in ("active", None):
                continue
            if not (d.get("new_arr") or d.get("expansion_arr")):
                continue
        else:
            if d.get("deal_status") != "active" or not is_incremental_pipeline(d):
                continue
            close_date = d.get("close_date")
            if not close_date or not (q_start_iso <= str(close_date)[:10] <= q_end_iso):
                continue

        d["_incremental_value"] = incremental_arr(d)

        if is_historical:
            if str(d.get("pipeline_id")) != SALES_PIPELINE:
                renewal_deals.append(d)
                continue
            so = d.get("stage_order")
            if so is None or so not in qualifying_orders:
                continue
            d["_stage_order"] = so
        else:
            if str(d.get("pipeline_id")) != SALES_PIPELINE:
                renewal_deals.append(d)
                continue
            if str(d.get("stage")) not in qualifying:
                continue
            d["_stage_order"] = stage_order_of[str(d.get("stage"))]
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
        stage_row = by_stage_order.get(str(d["_stage_order"])) or by_stage_order.get(d["_stage_order"])
        win_rate = stage_row.get("win_rate") if stage_row else None
        if win_rate is None:
            unweighted_total += d["_incremental_value"]
            unweighted_deal_count += 1
        else:
            weighted_total += d["_incremental_value"] * win_rate
            weighted_deal_count += 1

    # Target lookup: by quarter period label (works for both current and historical)
    period_label = _period_label_for_quarter(fiscal_quarter)
    quota = None
    try:
        target_resp = sb.table("rep_targets").select("target_value").eq(
            "period", period_label).eq("level", "team").eq(
            "metric", "incremental_arr").execute()
        if isinstance(target_resp.data, list) and target_resp.data:
            val = target_resp.data[0].get("target_value")
            if isinstance(val, (int, float)):
                quota = val
    except Exception as e:
        logger.warning(f"[PIPELINE_COVERAGE] Failed to fetch team quota: {e}")

    stretch = None
    stretch_note = None
    targets_path = REPO_ROOT / "config" / "targets.yaml"
    if targets_path.exists():
        with open(targets_path) as f:
            targets_cfg = yaml.safe_load(f) or {}
        quarter_key = fiscal_quarter.lower().replace(" ", "_")
        quarter_cfg = (targets_cfg.get("targets") or {}).get(quarter_key, {})
        stretch = quarter_cfg.get("stretch_target")
        stretch_note = quarter_cfg.get("stretch_note")

    goal = quota

    target_note = (
        f"Stated target for {fiscal_quarter} — team quota from rep_targets. "
        f"This is the REAL stated target, NEVER a heuristic."
    ) if goal else (
        f"No stated target found for {fiscal_quarter} — quota "
        f"not configured. Gap-to-goal cannot be computed; "
        f"only the heuristic proxy curve is available for comparison."
    )

    # historical HEURISTIC curve — never blended with the real target.
    proxy_curve = query_coverage_proxy_target_by_week(sb)
    week_ratio = proxy_curve.get("by_week", {}).get(current_week, {})

    scope_note = (
        "New+Expansion ARR only (is_incremental_pipeline(), "
        "renewal pipeline weighted separately: see renewal_not_weighted); qualified "
        "pipeline only (Sales pipeline, Discovery through Awaiting "
        "Signature); each deal weighted by its current stage's rate"
    )
    if is_historical:
        scope_note += (f"; HISTORICAL: pipeline state from deals_snapshot "
                       f"at end of {fiscal_quarter}")

    return {
        "status": "ok",
        "fiscal_quarter": fiscal_quarter,
        "current_week": current_week,
        "is_historical": is_historical,
        "scope": scope_note,
        "qualified_pipeline": {
            "raw_value": raw_pipeline_total,
            "deal_count": raw_deal_count,
        },
        "renewal_not_weighted": {
            "deal_count": len(renewal_deals),
            "value": sum(d["_incremental_value"] for d in renewal_deals),
            "note": ("Renewal-pipeline expansion ARR closing this quarter: no governed stage "
                     "rate (the table is Sales-pipeline New+Expansion only), so it is not in "
                     "the weighted total and is not given a Sales stage's rate."),
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
            "note": target_note,
        },
        "gap_to_goal": {
            "raw_pipeline_vs_goal": _gap_to_goal(raw_pipeline_total, goal),
            "weighted_pipeline_vs_goal": _gap_to_goal(weighted_total, goal),
        },
        "historical_heuristic_curve": {
            **proxy_curve,
            "current_week_ratio": week_ratio,
        },
        "note": (
            "HEURISTIC: the historical_heuristic_curve above is calibrated "
            "against a 2x-prior-year-actual PROXY target, not a real "
            "historical quota — no complete historical quarter ever had "
            "one. It rests on a permanent structural evidence ceiling (see "
            "that field's own note) and must always be labeled a HEURISTIC "
            "wherever it is surfaced, never 'directional' or 'approximate'. "
            + (
                f"The real_target and gap_to_goal above use the REAL stated "
                f"{fiscal_quarter} team quota and are never "
                "heuristics — the two must never be conflated."
                if goal else
                f"No real target exists for {fiscal_quarter}, so gap_to_goal "
                f"fields are null."
            )
        ),
    }


if __name__ == "__main__":
    from db import get_supabase
    sb = get_supabase()
    import json
    print(json.dumps(assess_pipeline_coverage(sb), indent=2, default=str))
