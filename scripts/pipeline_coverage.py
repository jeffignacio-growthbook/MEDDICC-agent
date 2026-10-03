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
     picture (a permanent structural ceiling, not a fixable gap). Still
     computed and cached (cache_payload, for explain_prior_answer
     citation) but no longer in the rendered answer — see 7.
  5. THE GOAL for the CURRENT quarter (FY2027 Q3) = the team quota
     (rep_targets team-level target, $1.55M). This is the minimum
     committed target the team is measured against.
     Stretch ($2.1M, config/targets.yaml) is Ryan's personal
     aspiration (2x YoY growth) — it is NOT additive on top of
     quota, and is reported separately as context, never summed
     into goal. The quota (team_total) is read from the live
     rep_targets table, matching query_pipeline()'s own precedent.
  6. CONFIG-DRIVEN COVERAGE, denominator = the REMAINING gap (2026-10-03):
     coverage is never computed against the bare quota — it is always
     against quota minus QTD closed-won (the remaining commitment),
     matching query_path_to_target's own "how much more do we need"
     framing. Two ratios are reported against that same remaining gap:
     nominal (qualified_pipeline.raw_value) and weighted
     (stage_weighting.weighted_value). QTD closed-won reuses
     forecast_analyses.actual_incremental_closed_won() (made public and
     generalized the same day — see that function's own docstring for the
     three-way reconciliation that preceded the change) rather than a
     fourth, new copy of "closed-won incremental ARR in a window".
     Edge cases, all graceful, never fabricated: quota already met
     (QTD won >= quota) reports that fact, no ratio (division by a
     non-positive remaining gap is meaningless); zero QTD won needs no
     special case (remaining gap is simply the full quota); missing quota
     propagates None through remaining_gap/both ratios/ahead_behind,
     same discipline the old gap_to_goal null-propagation used.
  7. EXPECTED MULTIPLE AND PHASE are config/client.yaml-driven
     (coverage.expected_multiple_schedule, coverage.phase_boundaries —
     scripts/utils.py::get_coverage_config()). No schedule configured for
     the current week means no ahead/behind judgment — never inferred
     from the HEURISTIC historical curve, which is a permanently
     evidence-ceilinged proxy, not a real per-week expectation. "phase"
     (early/mid/late) is reported unconditionally (it only needs
     current_week, not the schedule) so synthesis guidance can be
     phase-aware even when no expected multiple exists for the week.

CRITICAL, non-negotiable distinction (never blended, per explicit
instruction): the HISTORICAL curve is a HEURISTIC (proxy-calibrated,
labeled as such everywhere it appears, never shown in the rendered
answer — see api/handlers.py::query_pipeline_coverage). The CURRENT-
quarter real_target (quota) and the remaining-gap coverage ratios are
NEVER heuristics — they are real, measured figures.

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


def _coverage_phase(current_week: int, phase_boundaries: Dict[str, int]) -> str:
    """early/mid/late from config/client.yaml's coverage.phase_boundaries
    (scripts/utils.py::get_coverage_config) — needs only current_week, so
    this is always reported, even when no expected_multiple_schedule
    exists for the week."""
    if current_week <= phase_boundaries["early_through_week"]:
        return "early"
    if current_week >= phase_boundaries["late_from_week"]:
        return "late"
    return "mid"


def _coverage_equation(value: Optional[float], remaining_gap: Optional[float],
                       value_label: str) -> Optional[str]:
    """'$value value_label / $remaining_gap remaining = N.NNx' — every
    number states its basis. None if either operand is unavailable
    (never fabricate a ratio) or remaining_gap isn't positive (quota
    already met — no ratio makes sense against a zero-or-negative
    remaining commitment; see the caller's quota_met handling)."""
    if value is None or not remaining_gap or remaining_gap <= 0:
        return None
    return f"${value:,.0f} {value_label} / ${remaining_gap:,.0f} remaining = {value / remaining_gap:.2f}x"


def _assess_coverage(
    quota: Optional[float], qtd_won: float,
    raw_value: float, weighted_value: float,
    current_week: int, coverage_config: Dict[str, Any],
) -> Dict[str, Any]:
    """The config-driven coverage block: remaining gap, nominal/weighted
    coverage against it, expected multiple for the week, ahead/behind,
    and phase. Denominator is ALWAYS the remaining gap (quota minus QTD
    closed-won), never the bare quota — see this module's own docstring,
    point 6. All null-propagated, never fabricated: missing quota, quota
    already met, and no configured expected-multiple schedule are each
    handled explicitly, not silently defaulted."""
    phase = _coverage_phase(current_week, coverage_config["phase_boundaries"])
    expected_multiple = coverage_config["expected_multiple_schedule"].get(current_week)

    if quota is None:
        return {
            "remaining_gap": None, "quota_met": None,
            "nominal_coverage": None, "weighted_coverage": None,
            "expected_multiple": expected_multiple, "ahead_behind": None,
            "phase": phase,
            "equations": {"remaining": None, "nominal": None, "weighted": None},
            "note": ("No stated quota for this quarter — remaining gap and "
                     "coverage ratios cannot be computed. Pipeline figures "
                     "above are still real; only the comparison against "
                     "quota is unavailable."),
        }

    remaining_gap = quota - qtd_won
    quota_met = remaining_gap <= 0

    if quota_met:
        remaining_eq = (f"${quota:,.0f} quota - ${qtd_won:,.0f} won = $0 remaining "
                        f"(quota already met, ${-remaining_gap:,.0f} over)")
        return {
            "remaining_gap": 0.0, "quota_met": True,
            "nominal_coverage": None, "weighted_coverage": None,
            "expected_multiple": expected_multiple, "ahead_behind": None,
            "phase": phase,
            "equations": {"remaining": remaining_eq, "nominal": None, "weighted": None},
            "note": (f"Quota already met this quarter (${qtd_won:,.0f} won >= "
                     f"${quota:,.0f} quota) — no remaining gap to cover, so no "
                     f"coverage ratio is computed. Never divide by a zero or "
                     f"negative remaining commitment."),
        }

    nominal_coverage = raw_value / remaining_gap
    weighted_coverage = weighted_value / remaining_gap
    ahead_behind = None
    if expected_multiple is not None:
        ahead_behind = "ahead" if weighted_coverage >= expected_multiple else "behind"

    remaining_eq = (f"${quota:,.0f} quota - ${qtd_won:,.0f} won = "
                    f"${remaining_gap:,.0f} remaining")
    nominal_eq = _coverage_equation(raw_value, remaining_gap, "raw qualified pipeline")
    weighted_eq = _coverage_equation(weighted_value, remaining_gap, "weighted pipeline")

    return {
        "remaining_gap": remaining_gap, "quota_met": False,
        "nominal_coverage": nominal_coverage, "weighted_coverage": weighted_coverage,
        "expected_multiple": expected_multiple, "ahead_behind": ahead_behind,
        "phase": phase,
        "equations": {"remaining": remaining_eq, "nominal": nominal_eq, "weighted": weighted_eq},
        "note": (
            "Denominator is the REMAINING gap (quota minus QTD closed-won), "
            "never the bare quota. nominal_coverage = qualified_pipeline."
            "raw_value / remaining_gap; weighted_coverage = stage_weighting."
            "weighted_value / remaining_gap. expected_multiple and "
            "ahead_behind come from config/client.yaml's coverage."
            "expected_multiple_schedule for the current week; null when no "
            "schedule is configured for that week (never inferred from the "
            "HEURISTIC historical curve)."
        ),
    }


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
    coverage vs. the REMAINING gap (quota minus QTD closed-won — never
    the bare quota), plus a HEURISTIC historical coverage curve kept for
    citation only (see api/handlers.py::query_pipeline_coverage — it is
    no longer in the rendered answer).

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
         "qtd_won": {"value": float, "note": str},
         "coverage": {"remaining_gap": float|None, "quota_met": bool|None,
             "nominal_coverage": float|None, "weighted_coverage": float|None,
             "expected_multiple": float|None, "ahead_behind": str|None,
             "phase": str, "equations": {"remaining", "nominal", "weighted"},
             "note": str},
         "historical_heuristic_curve": {...query_coverage_proxy_target_by_week()'s
             output..., "current_week_ratio": {...}},
         "note": str}
    """
    from utils import get_fiscal_quarter, get_pipeline_config, get_coverage_config
    from field_semantics import is_incremental_pipeline
    from forecast_analyses import (
        query_stage_close_rate, query_coverage_proxy_target_by_week,
        actual_incremental_closed_won)
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
        f"not configured. Remaining-gap coverage cannot be computed; "
        f"only the heuristic proxy curve is available for comparison."
    )

    # QTD closed-won incremental ARR for this same window — the remaining-
    # gap denominator (point 6 of this module's docstring). Reuses
    # forecast_analyses.actual_incremental_closed_won() rather than a
    # fourth copy of "closed-won incremental ARR in [start, end]".
    qtd_won, qtd_won_n = actual_incremental_closed_won(sb, q_start_iso, q_end_iso)
    qtd_won_note = (
        f"${qtd_won:,.0f} closed-won incremental ARR ({qtd_won_n} deal"
        f"{'' if qtd_won_n == 1 else 's'}) in {fiscal_quarter}, same basis "
        f"as qualified_pipeline (is_incremental_pipeline(), renewal pipeline "
        f"excluded) and same outcome test as query_path_to_target/"
        f"assess_loss_concentration (deal_status == 'won')."
    )

    coverage_config = get_coverage_config()
    coverage = _assess_coverage(
        quota=quota, qtd_won=qtd_won,
        raw_value=raw_pipeline_total, weighted_value=weighted_total,
        current_week=current_week, coverage_config=coverage_config,
    )

    # Calendar-based days/weeks left — the SAME single source of truth
    # api/quarter_health.py's exposure answer uses (quarter_days_weeks_
    # left), not a week-index subtraction. 2026-10-03: the coverage
    # synthesis note used to let the model derive "weeks left" itself
    # from `13 - current_week`, which both ignores that the current
    # week is only partially elapsed and isn't calendar-based — it said
    # "3 weeks" the same day exposure correctly said "4 weeks left" (28
    # calendar days).
    from utils import quarter_days_weeks_left
    quarter_time_left = quarter_days_weeks_left(q_end, as_of)

    # historical HEURISTIC curve — never blended with the real target.
    # Still computed (cache_payload, citation) even though it's no longer
    # rendered — see api/handlers.py::query_pipeline_coverage.
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
        "quarter_time_left": quarter_time_left,
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
        "qtd_won": {
            "value": qtd_won,
            "deal_count": qtd_won_n,
            "note": qtd_won_note,
        },
        "coverage": coverage,
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
                f"The real_target and coverage above use the REAL stated "
                f"{fiscal_quarter} team quota and QTD closed-won, and are "
                "never heuristics — the two must never be conflated."
                if goal else
                f"No real target exists for {fiscal_quarter}, so coverage "
                f"fields are null."
            )
        ),
    }


if __name__ == "__main__":
    from db import get_supabase
    sb = get_supabase()
    import json
    print(json.dumps(assess_pipeline_coverage(sb), indent=2, default=str))
