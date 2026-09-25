#!/usr/bin/env python3
"""
Forecast Trustworthiness Assessor — quarter-level trust signal for the
current quarter's COMMIT+MOST_LIKELY forecast category.

Answers NORTH_STAR.md's CRO Priority #1: "how much should I trust this
quarter's number." Composes two existing, separately-scoped primitives
rather than extending either one (confirmed 2026-09-19 — neither has
the other's logic, so this is a new module, not a mode on either):

  - scripts/deal_risk_assessor.py::assess_deal_risk() — per-deal
    cycle-length risk flagging, called here directly on THIS QUARTER's
    COMMIT+MOST_LIKELY cohort. NOT via get_at_risk_deals(): that
    convenience wrapper hardcodes forecast_category='COMMIT' and would
    silently drop MOST_LIKELY-tagged deals that aren't also late-stage.
  - scripts/analytics/forecast_analyses.py::query_commit_ml_calibration_by_week()
    — pooled, week-indexed historical win rate across the complete
    (closed) quarters.

Design, confirmed across the 2026-09-19 scoping session:
  - Below week 3 of the current quarter: insufficient_data/too_early,
    hard gate. Reps structurally don't produce honest Commit/Most-Likely
    tags in the coverage-building phase (weeks 1-2) — no historical
    baseline at any week is a fair comparison for this period. Week 3
    itself is the first allowed week (Jeff's domain cutoff; the pooled
    win-rate-delta data neither proves nor contradicts week 3 over
    week 4 specifically, so this is a domain call, not a data-forced
    one).
  - Week 3 onward: MOVING comparison — look up the historical win rate
    at the SAME week number the current quarter is actually in, never
    a fixed anchor. A week-4 question compares against week 4's
    historical rate, not week 10's.
  - Stability band, from the already-computed week-by-week table:
      3-6:   "forming"     (cohort still filling in, lower confidence)
      7-10:  "settled"     (largest, most stable pooled cohort)
      11-13: "late_quarter" (lost collapses toward zero by this point;
                             comparison answers a narrower question)
  - "Directional, not final" caveat applies for weeks 3-9 (the current
    quarter's cohort hasn't had as much time to resolve as the
    historical week-10 cohort had by quarter end); drops away from
    week 10 onward, where the comparison is time-matched.
    Worded in plain language by plain_baseline_sentence() ("That 32%
    comes from deals that had a full quarter to close. We're only 8
    weeks into this one, ..."), which quarter health requires verbatim.
  - Week 10's 30.8% figure is cited ONLY as evidence the underlying
    calibration approach is real (large n, stable) — never hardcoded
    as the live comparison point.

No fabricated probabilities. Read-only.
"""
import sys
from pathlib import Path
from datetime import date
from typing import Optional, Dict, Any
import logging

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "analytics"))
sys.path.insert(0, str(REPO_ROOT / "api"))

logger = logging.getLogger(__name__)

EARLY_QUARTER_GATE_WEEK = 3  # Jeff's domain cutoff (coverage-building phase ends)
CALIBRATION_EVIDENCE_WEEK = 10  # cited as evidence only, never the comparison anchor

STABILITY_BANDS = {
    "forming": range(3, 7),
    "settled": range(7, 11),
    "late_quarter": range(11, 14),
}

CATEGORIES = ["COMMIT", "MOST_LIKELY"]


def _stability_band(week: int) -> str:
    for label, wk_range in STABILITY_BANDS.items():
        if week in wk_range:
            return label
    raise ValueError(f"week {week} outside the expected 3-13 range")


def plain_baseline_sentence(win_rate: Optional[float], week: int) -> str:
    """Weeks 3-9: why this quarter's cohort can't be read against the
    same-week historical rate yet, in plain words (said word for word by
    quarter health; the old wording was "Directional, not final: ... hasn't
    had as much time to resolve as the historical week-N baseline had by
    quarter end")."""
    rate = f"That {win_rate:.0%}" if win_rate is not None else f"The historical week-{week} rate"
    return (f"{rate} comes from deals that had a full quarter to close. We're only {week} "
            f"week{'' if week == 1 else 's'} into this one, so some deals that look stuck today "
            "may still close before quarter end.")


def assess_forecast_trust(sb, as_of: Optional[date] = None) -> Dict[str, Any]:
    """
    Quarter-level forecast-trustworthiness signal for the CURRENT
    quarter's COMMIT+MOST_LIKELY pipeline.

    Args:
        sb: Supabase client
        as_of: Date to evaluate "today" as (default: date.today()). Exposed
               for testability — NOT a historical-quarter override; this
               primitive always answers for the quarter containing `as_of`.

    Returns (gated):
        {"status": "insufficient_data", "reason": "too_early",
         "fiscal_quarter": str, "current_week": int,
         "gate_week": int, "note": str}
      or:
        {"status": "ok", "fiscal_quarter": str, "current_week": int,
         "stability": "forming"|"settled"|"late_quarter",
         "directional_caveat": bool,
         "pipeline": {"deal_count": int, "incremental_arr": float,
                      "excluded_no_incremental_arr": int},
         "risk_summary": {...assess_deal_risk()'s summary...},
         "high_risk_count": int, "high_risk_fraction": float|None,
         "historical": {"week": int, "win_rate": float|None,
                        "n": int, "reason": str|None},
         "calibration_evidence": {"week": 10, "win_rate": float|None,
                                   "n": int, "note": str},
         "assessed_deals": [...assess_deal_risk()'s per-deal output...],
         "note": str}
    """
    from utils import get_fiscal_quarter
    from deal_risk_assessor import assess_deal_risk
    from forecast_analyses import query_commit_ml_calibration_by_week
    from snapshot_deals import get_week_of_quarter

    if as_of is None:
        as_of = date.today()

    q_start, q_end, fiscal_quarter = get_fiscal_quarter(as_of)
    current_week = get_week_of_quarter(as_of, q_start)

    if current_week < EARLY_QUARTER_GATE_WEEK:
        return {
            "status": "insufficient_data",
            "reason": "too_early",
            "fiscal_quarter": fiscal_quarter,
            "current_week": current_week,
            "gate_week": EARLY_QUARTER_GATE_WEEK,
            "note": (
                f"Week {current_week} of {fiscal_quarter}: reps structurally "
                f"aren't producing reliable Commit/Most-Likely tags this "
                f"early in the quarter (coverage-building phase, not "
                f"forecasting yet). No trust signal until week "
                f"{EARLY_QUARTER_GATE_WEEK}."
            ),
        }

    # This quarter's COMMIT+MOST_LIKELY deals — own query, deliberately NOT
    # get_at_risk_deals() (hardcodes COMMIT-only; see module docstring).
    # 2026-09-23: this selected `amount`, a column `deals` has never had, so
    # every production call failed (Postgres: "column deals.amount does not
    # exist"). Dollars are now the quota basis, incremental_arr() (new_arr +
    # expansion_arr; renewal base excluded), and the deal count, the dollar
    # total and the risk assessment all use the same incremental deals
    # (is_incremental_pipeline, the Gate 3 count/sum rule). Deals with no
    # incremental ARR (pure renewals) are counted in
    # excluded_no_incremental_arr, not dropped silently.
    from incremental_arr import incremental_arr
    from field_semantics import is_incremental_pipeline
    response = sb.table("deals").select(
        "deal_id,company_name,stage,create_date,close_date,segment,"
        "forecast_category,deal_status,pipeline_id,new_arr,expansion_arr"
    ).in_("forecast_category", CATEGORIES).eq(
        "deal_status", "active"
    ).gte("close_date", q_start.isoformat()).lte(
        "close_date", q_end.isoformat()
    ).execute()
    fetched = response.data or []
    deals = [d for d in fetched if is_incremental_pipeline(d)]

    # 2026-09-24: COMMIT deals whose close date is outside this quarter or
    # missing. The cohort query above filters on close_date, so it never sees
    # them; surfaced as hygiene. After the cohort query (and after the week-3
    # gate, which makes no queries at all). See api/commit_close_date.py.
    # A failure here must not take the trust signal down with it.
    from commit_close_date import commit_close_date_mismatches
    try:
        commit_rows = sb.table("deals").select(
            "deal_id,company_name,forecast_category,deal_status,close_date,deal_value,pipeline_id"
        ).in_("forecast_category", ["COMMIT"]).eq("deal_status", "active").execute().data or []
        commit_close_date_mismatch = commit_close_date_mismatches(
            commit_rows, q_start, q_end, fiscal_quarter)
    except Exception as e:
        logger.error(f"[FORECAST_TRUST] COMMIT close-date check failed: {e}")
        commit_close_date_mismatch = None

    risk_result = assess_deal_risk(deals, sb)
    assessed = risk_result.get("assessed_deals", [])
    summary = risk_result.get("summary", {})
    total_assessed = summary.get("total_assessed", len(assessed))
    high_risk_count = summary.get("high_risk", 0)
    high_risk_fraction = (high_risk_count / total_assessed) if total_assessed else None

    total_incremental_arr = sum(incremental_arr(d) for d in deals)

    # The dollar read of the risk labels, as shares of the WHOLE forecast (the
    # number a reader cares about): a deal-count fraction over assessed deals
    # alone reads as "a third of the forecast is shaky" when it isn't.
    arr_by_id = {str(d.get("deal_id")): incremental_arr(d) for d in deals}
    high_risk_arr = sum(arr_by_id.get(str(d.get("deal_id")), 0) for d in assessed
                        if d.get("overall_label") == "high_risk")
    not_assessed_arr = sum(arr_by_id.get(str(d.get("deal_id")), 0)
                           for d in risk_result.get("not_assessed_deals", []))
    risk_dollars = {
        "forecast_arr": total_incremental_arr,
        "high_risk_arr": high_risk_arr,
        "high_risk_share_of_forecast": (high_risk_arr / total_incremental_arr) if total_incremental_arr else None,
        "not_assessed_arr": not_assessed_arr,
        "not_assessed_share_of_forecast": (not_assessed_arr / total_incremental_arr) if total_incremental_arr else None,
        "note": ("Shares are of the whole forecast's incremental ARR: high-risk deals' ARR, and "
                 "the ARR of deals with no risk read (Renewal pipeline, not assessed)."),
    }

    calib = query_commit_ml_calibration_by_week(sb)
    by_week = calib.get("by_week", {})
    current_week_row = by_week.get(current_week, {})
    evidence_week_row = by_week.get(CALIBRATION_EVIDENCE_WEEK, {})

    stability = _stability_band(current_week)
    directional_caveat = current_week < CALIBRATION_EVIDENCE_WEEK

    if directional_caveat:
        note = plain_baseline_sentence(current_week_row.get("win_rate"), current_week)
    elif stability == "late_quarter":
        note = (
            f"Week {current_week} of {fiscal_quarter}: in the historical "
            f"baseline, terminally lost deals have mostly already exited "
            f"the tracked cohort by this point in the quarter (lost "
            f"collapses toward zero after week {CALIBRATION_EVIDENCE_WEEK}) "
            f"— this comparison is answering a narrower, less meaningful "
            f"question than earlier in the quarter."
        )
    else:
        note = (
            f"Week {current_week} of {fiscal_quarter} — comparison is "
            f"time-matched against the historical week-{current_week} "
            f"baseline."
        )

    return {
        "status": "ok",
        "fiscal_quarter": fiscal_quarter,
        "current_week": current_week,
        "stability": stability,
        "directional_caveat": directional_caveat,
        "pipeline": {
            "deal_count": len(deals),
            "incremental_arr": total_incremental_arr,
            "excluded_no_incremental_arr": len(fetched) - len(deals),
        },
        "risk_summary": summary,
        "risk_basis": risk_result.get("basis"),
        "risk_not_assessed": {"deals": risk_result.get("not_assessed_deals", []),
                              "note": risk_result.get("not_assessed_note")},
        "high_risk_count": high_risk_count,
        "high_risk_fraction": high_risk_fraction,
        "risk_dollars": risk_dollars,
        "historical": {
            "week": current_week,
            "win_rate": current_week_row.get("win_rate"),
            "n": current_week_row.get("classified", 0),
            "reason": current_week_row.get("reason"),
        },
        "calibration_evidence": {
            "week": CALIBRATION_EVIDENCE_WEEK,
            "win_rate": evidence_week_row.get("win_rate"),
            "n": evidence_week_row.get("classified", 0),
            "note": (
                "Cited as evidence the calibration approach is real (the "
                "largest, most stable pooled cohort) — not used as the "
                "comparison point for this result."
            ),
        },
        "assessed_deals": assessed,
        "commit_close_date_mismatch": commit_close_date_mismatch,
        "note": note,
    }


if __name__ == "__main__":
    from db import get_supabase
    sb = get_supabase()
    import json
    print(json.dumps(assess_forecast_trust(sb), indent=2, default=str))
