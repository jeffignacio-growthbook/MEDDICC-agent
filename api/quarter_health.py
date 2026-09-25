"""
Quarter health: one composer behind "are we in good shape this quarter?"
and its downside mirror.

compose_quarter_health() calls four existing primitives in a fixed order,
the same for both scenarios:

    query_forecast_trust            how much to trust COMMIT+MOST_LIKELY
    query_pipeline                  current pipeline, plus this quarter's slice
    query_high_priority_deal_risk   late-stage/COMMIT deals past their cycle
    query_loss_concentration        where this quarter's losses sit

It invents no score. Each primitive's own figures go to synthesis as that
primitive returned them, and every basis statement it disclosed is lifted,
verbatim, into `disclosed_bases` at the top of the result, ahead of
anything a character cut could reach. The synthesis note asks for a
plain-language verdict grounded in the four figures and forbids combining
them: they measure different populations.

The only calculation is the downside scenario's worst case:
    forecast_arr - sum(high-risk forecast deal incremental ARR
                       x (1 - its current stage's win rate))
with the win rate from the governed table query_stage_close_rate() (the
one query_pipeline_coverage weights with), never a new estimate. See
downside_worst_case().

Result layout, in this order (order matters: the classifier path's
last-resort cut takes the end):
    status, scenario, question_frame, _synthesis_note,
    disclosed_bases, figures, [downside], primitives
`primitives` holds each result with its lifted notes replaced by a pointer
into disclosed_bases and its per-deal lists trimmed (DETAIL_LISTS); counts
and summaries are untouched, so the composed view is bounded however many
deals there are.
"""
import copy
import logging
import re

import api.handlers as handlers
from api.incremental_arr import incremental_arr

logger = logging.getLogger(__name__)

SCENARIOS = ("base", "downside")
# Handler names the two thin routed entry points will register under (both
# must go in api.evaluator.STRUCTURED_HANDLERS; see the survival test).
ENTRY_POINTS = {"base": "query_quarter_health", "downside": "query_quarter_downside"}
PRIMITIVE_ORDER = ("query_forecast_trust", "query_pipeline",
                   "query_high_priority_deal_risk", "query_loss_concentration")
SALES_PIPELINE = "default"
RENEWAL_PIPELINE = "866608541"

# Keys whose string value is a basis/disclosure statement: lifted verbatim.
_LIFT_KEY = re.compile(r"^(note|basis|risk_basis|_synthesis_note|coverage_omitted_reason|.+_note)$")

# Per-deal lists trimmed in the composed view (counts elsewhere cover all rows).
DETAIL_LISTS = {
    "query_forecast_trust": ("assessed_deals",),
    "query_high_priority_deal_risk": ("assessed_deals",),
    "query_pipeline": ("deals", "zero_arr_deals.deals"),
}
# Breakdowns dropped from the composed view (not needed for a quarter verdict).
DROP_KEYS = {"query_pipeline": ("by_owner",)}
# Row lists whose rows are reduced to the primitive's own rendered line,
# which already states every number in the row.
TEXT_ROWS = {"query_loss_concentration": ("by_rep", "by_segment")}
HIGH_RISK_KEEP = 10
AT_RISK_KEEP = 10
# days_past_benchmark only means something beside the benchmark it is measured
# against: keep all three (check_benchmark_offsets pairs them; dropping the
# benchmark made 8 correct rows read as "no valid benchmark" live, 2026-09-25).
_HIGH_RISK_FIELDS = ("company_name", "segment", "days_open", "cycle_benchmark_days",
                     "days_past_benchmark")

FRAMES = {
    "base": "Are we in good shape this quarter?",
    "downside": "What does the downside look like this quarter?",
}


# ----------------------------------------------------------------- compose

async def compose_quarter_health(sb, params: dict = None, scenario: str = "base") -> dict:
    """Call the four primitives in PRIMITIVE_ORDER and compose. A primitive
    that raises is reported unavailable in its own section; the rest go on."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}")
    params = dict(params or {})
    results = {}
    for name in PRIMITIVE_ORDER:
        try:
            results[name] = await getattr(handlers, name)(dict(params), sb)
        except Exception as e:
            logger.error(f"[QUARTER_HEALTH] {name} failed: {e}")
            results[name] = {"status": "error", "error": f"{name} failed: {e}"}

    stage_rates = deal_rows = None
    if scenario == "downside":
        stage_rates, deal_rows = _downside_inputs(sb, results.get("query_forecast_trust") or {})
    return compose_from_results(results, scenario, stage_rates=stage_rates, deal_rows=deal_rows)


def _downside_inputs(sb, forecast_trust: dict):
    from forecast_analyses import query_stage_close_rate
    try:
        rates = query_stage_close_rate(sb)
    except Exception as e:
        logger.error(f"[QUARTER_HEALTH] stage close-rate table failed: {e}")
        rates = {"error": str(e), "by_stage_order": {}}
    ids = [d["deal_id"] for d in _high_risk(forecast_trust)]
    rows = []
    if ids:
        try:
            rows = sb.table("deals").select(
                "deal_id,company_name,pipeline_id,new_arr,expansion_arr,stage"
            ).in_("deal_id", ids).execute().data or []
        except Exception as e:
            logger.error(f"[QUARTER_HEALTH] high-risk deal rows failed: {e}")
    return rates, rows


def compose_from_results(results: dict, scenario: str, stage_rates: dict = None,
                         deal_rows: list = None) -> dict:
    """Pure composition over the four primitive results (keyed by name)."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}")
    bases, primitives = [], {}
    for name in PRIMITIVE_ORDER:
        res = results.get(name)
        if not isinstance(res, dict):
            res = {"status": "error", "error": f"{name} returned nothing"}
        primitives[name] = _slim(name, _lift(name, copy.deepcopy(res), bases))

    figures = {
        "forecast_trust": _forecast_figures(results.get("query_forecast_trust")),
        "pipeline": _pipeline_figures(results.get("query_pipeline")),
        "deal_risk": _risk_figures(results.get("query_high_priority_deal_risk")),
        "loss_concentration": _loss_figures(results.get("query_loss_concentration")),
    }
    quarter = (figures["forecast_trust"].get("fiscal_quarter")
               or figures["loss_concentration"].get("period") or "this quarter")

    out = {
        "status": "ok",
        "scenario": scenario,
        "question_frame": FRAMES[scenario],
        "_synthesis_note": None,
        "disclosed_bases": bases,
        "figures": figures,
    }
    if scenario == "downside":
        out["downside"] = downside_worst_case(results.get("query_forecast_trust") or {},
                                              stage_rates or {}, deal_rows or [])
    out["primitives"] = primitives
    out["_synthesis_note"] = _note(scenario, quarter, figures)
    return out


# ------------------------------------------------------------------ lifting

def _lift(prim: str, obj, bases: list, path: str = ""):
    """Move every disclosure string into `bases` (verbatim), leaving a
    pointer. A text two primitives both disclose (the same deal-risk basis,
    the same COMMIT close-date note) is stored once with both sources.
    Recurses into dicts and lists."""
    if isinstance(obj, dict):
        for k in list(obj):
            v = obj[k]
            p = f"{path}.{k}" if path else k
            if isinstance(v, str) and v.strip() and _LIFT_KEY.match(k):
                src = f"{prim}.{p}"
                i = next((j for j, b in enumerate(bases) if b["text"] == v), None)
                if i is None:
                    bases.append({"sources": [src], "text": v})
                    i = len(bases) - 1
                else:
                    bases[i]["sources"].append(src)
                obj[k] = f"-> disclosed_bases[{i}]"
            else:
                _lift(prim, v, bases, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _lift(prim, v, bases, f"{path}[{i}]")
    return obj


def _slim(prim: str, res: dict) -> dict:
    """Per-deal lists out, counts and summaries untouched. The high-risk
    deals are still named: compactly for deal risk, by name only for
    forecast trust (the downside block lists that cohort's at-risk deals
    with their dollars)."""
    if prim in ("query_forecast_trust", "query_high_priority_deal_risk") and "assessed_deals" in res:
        hi = _high_risk(res)
        if prim == "query_forecast_trust":
            res["high_risk_companies"] = [d.get("company_name") for d in hi[:HIGH_RISK_KEEP]]
        else:
            res["high_risk_deals"] = [{k: d.get(k) for k in _HIGH_RISK_FIELDS} for d in hi[:HIGH_RISK_KEEP]]
        if len(hi) > HIGH_RISK_KEEP:
            res["high_risk_omitted"] = (f"{len(hi) - HIGH_RISK_KEEP} more high-risk deals not "
                                        "named; the counts cover all of them")
    omitted = {}
    for dotted in DETAIL_LISTS.get(prim, ()):
        *parents, key = dotted.split(".")
        holder = res
        for p in parents:
            holder = holder.get(p) if isinstance(holder, dict) else None
        if not isinstance(holder, dict) or not isinstance(holder.get(key), list):
            continue
        n = len(holder[key])
        if n:
            holder[key] = []
            omitted[dotted] = (f"{n} per-deal rows not shown in this composed view; every count "
                               f"and total above covers all {n}")
    for key in DROP_KEYS.get(prim, ()):
        if key in res:
            res.pop(key)
            omitted[key] = "breakdown not shown in this composed view"
    for key in TEXT_ROWS.get(prim, ()):
        rows = res.get(key)
        if isinstance(rows, list) and all(isinstance(r, dict) and r.get("text") for r in rows):
            res[key] = [r["text"] for r in rows]
    if omitted:
        res["_rows_omitted"] = omitted
    return res


def _high_risk(res: dict) -> list:
    return [d for d in (res.get("assessed_deals") or []) if d.get("overall_label") == "high_risk"]


# ------------------------------------------------------------------ figures

def _unavailable(res):
    if not isinstance(res, dict):
        return {"status": "unavailable", "error": "no result"}
    if res.get("error") or res.get("status") == "error":
        return {"status": "unavailable", "error": str(res.get("error") or "error")}
    return None


def _forecast_figures(res):
    bad = _unavailable(res)
    if bad:
        return bad
    if res.get("status") != "ok":
        return {"status": res.get("status"), "reason": res.get("reason"),
                "fiscal_quarter": res.get("fiscal_quarter"), "current_week": res.get("current_week")}
    p = res.get("pipeline") or {}
    return {"status": "ok", "fiscal_quarter": res.get("fiscal_quarter"),
            "current_week": res.get("current_week"), "stability": res.get("stability"),
            "forecast_arr": p.get("incremental_arr"), "forecast_deal_count": p.get("deal_count"),
            "high_risk_count": res.get("high_risk_count"),
            "high_risk_fraction": res.get("high_risk_fraction"),
            "historical_win_rate_same_week": (res.get("historical") or {}).get("win_rate"),
            "historical_n": (res.get("historical") or {}).get("n")}


def _pipeline_figures(res):
    bad = _unavailable(res)
    if bad:
        return bad
    keys = ("total_pipeline", "total_deals", "q3_scoped_pipeline", "q3_scoped_deals",
            "quarterly_target", "coverage_ratio", "this_quarter")
    return {"status": "ok", **{k: res.get(k) for k in keys if k in res}}


def _risk_figures(res):
    bad = _unavailable(res)
    if bad:
        return bad
    return {"status": "ok", "summary": res.get("summary")}


def _loss_figures(res):
    bad = _unavailable(res)
    if bad:
        return bad
    keys = ("status", "period", "closed_deal_count", "won_count", "lost_count", "team_loss_rate")
    return {k: res.get(k) for k in keys if k in res}


# ----------------------------------------------------------------- downside

def _sales_stage_orders():
    from utils import get_pipeline_config
    for p in get_pipeline_config().get("pipelines", []):
        if str(p.get("id")) == SALES_PIPELINE:
            return {str(s["id"]): s["order"] for s in p.get("stages", [])}
    return {}


def downside_worst_case(forecast_trust: dict, stage_rates: dict, deal_rows: list) -> dict:
    """worst_case_arr = forecast_arr - weighted_expected_loss.

    forecast_arr: query_forecast_trust's COMMIT+MOST_LIKELY incremental ARR
    closing this quarter. At-risk deals: that same cohort's high_risk deals
    (assess_deal_risk labels), so the subtraction stays inside one
    population. Each deal's expected loss is incremental_arr x (1 - win
    rate), the win rate read from stage_rates (query_stage_close_rate()'s
    by_stage_order) at the config order of the deal's CURRENT stage, Sales
    pipeline only: the table is built from snapshot stage_order (the stage
    the deal was in), and deals.highest_stage_order_reached is a different
    measure. No rate, no weight: the deal is listed as unrated."""
    fq = forecast_trust.get("fiscal_quarter") or "this quarter"
    if forecast_trust.get("status") != "ok":
        return {"status": "unavailable",
                "reason": f"query_forecast_trust returned {forecast_trust.get('status') or 'no result'}: "
                          "no forecast to take a worst case from"}
    forecast = (forecast_trust.get("pipeline") or {}).get("incremental_arr")
    by_order = (stage_rates or {}).get("by_stage_order") or {}
    orders = _sales_stage_orders()
    rows = {str(r.get("deal_id")): r for r in deal_rows or []}

    deals, weighted, unrated_arr, total = [], 0.0, 0.0, 0.0
    for d in _high_risk(forecast_trust):
        did = str(d.get("deal_id"))
        r = rows.get(did)
        item = {"deal_id": did, "company_name": d.get("company_name"),
                "pipeline_id": (r or {}).get("pipeline_id"), "stage": (r or {}).get("stage"),
                "incremental_arr": None, "stage_order": None, "stage_win_rate": None,
                "expected_loss": None, "unrated_reason": None}
        if r is None:
            item["unrated_reason"] = "no deals row returned for this deal"
            deals.append(item)
            continue
        arr = incremental_arr(r)
        item["incremental_arr"] = arr
        total += arr
        if str(r.get("pipeline_id")) != SALES_PIPELINE:
            item["unrated_reason"] = ("Renewal pipeline deal: the governed stage table is New+Expansion "
                                      "Sales-pipeline only" if str(r.get("pipeline_id")) == RENEWAL_PIPELINE
                                      else f"pipeline {r.get('pipeline_id')!r} has no governed stage rate")
        else:
            so = orders.get(str(r.get("stage")))
            item["stage_order"] = so
            row = by_order.get(str(so)) if so is not None else None
            if row is None and so is not None:
                row = by_order.get(so)
            wr = (row or {}).get("win_rate")
            if so is None:
                item["unrated_reason"] = f"stage {r.get('stage')!r} not in the Sales pipeline config"
            elif wr is None:
                item["unrated_reason"] = ((row or {}).get("reason")
                                          or f"no governed win rate for stage order {so}")
            else:
                item["stage_win_rate"] = wr
                item["expected_loss"] = arr * (1 - wr)
                weighted += item["expected_loss"]
        if item["expected_loss"] is None:
            unrated_arr += arr
        deals.append(item)

    unrated = [x for x in deals if x["expected_loss"] is None]
    moderate = sum(1 for d in (forecast_trust.get("assessed_deals") or [])
                   if d.get("overall_label") == "moderate_risk")
    mod_line = (f"Only high_risk deals are subtracted: {moderate} moderate_risk deal"
                f"{'' if moderate == 1 else 's'} in the forecast cohort (0-30 days past the cycle "
                "benchmark) not subtracted, and low_risk and insufficient_data deals are not either. ")
    listed = sorted(deals, key=lambda x: -(x["incremental_arr"] or 0))[:AT_RISK_KEEP]
    for x in listed:
        x.pop("stage", None)
    return {
        "status": "ok",
        "fiscal_quarter": fq,
        "forecast_arr": forecast,
        "at_risk_count": len(deals),
        "at_risk_arr": total,
        "weighted_expected_loss": weighted,
        "worst_case_arr": (forecast - weighted) if forecast is not None else None,
        "unrated_count": len(unrated),
        "unrated_at_risk_arr": unrated_arr,
        "moderate_risk_excluded_count": moderate,
        "floor_if_all_at_risk_lost": (forecast - total) if forecast is not None else None,
        "at_risk_deals": listed,
        **({"at_risk_deals_omitted": f"{len(deals) - len(listed)} smaller at-risk deals not listed; "
                                     "every total above covers all of them"}
           if len(deals) > len(listed) else {}),
        "basis": (
            f"Worst case = query_forecast_trust's forecast (COMMIT+MOST_LIKELY incremental ARR closing "
            f"in {fq}) minus, for each of that cohort's high-risk deals (assess_deal_risk labels, basis "
            "in disclosed_bases), its incremental ARR x (1 - the win rate of the deal's current stage) "
            "from the governed stage close-rate table query_stage_close_rate() (won / (won + lost + "
            f"slipped) within the quarter, pooled over {(stage_rates or {}).get('quarters_analyzed')} "
            "complete quarters, New+Expansion only; the table query_pipeline_coverage weights with). "
            "Looked up by the deal's current stage order on the Sales pipeline. " + mod_line
            + "Deals with no governed "
            "rate (Renewal pipeline, which the table excludes, or a stage below min_evidence_count) are "
            "listed as unrated and left out of the weighted figure, never given a default weight; "
            "floor_if_all_at_risk_lost assumes every at-risk deal is lost. The stage rate is the "
            "historical rate for every deal at that stage, not for deals flagged high-risk, so the "
            "weighted loss may understate the downside."
        ),
    }


# --------------------------------------------------------------------- note

_POPULATIONS = (
    "forecast_trust = COMMIT+MOST_LIKELY deals closing in {q}; pipeline = all active incremental "
    "ARR (current state, not this quarter) plus its own this-quarter figure; deal_risk = late-stage "
    "or COMMIT deals closing in {q}; loss_concentration = deals closed in {q}"
)


def _note(scenario: str, quarter: str, figures: dict) -> str:
    down = [k for k, v in figures.items() if v.get("status") == "unavailable"]
    names = {"forecast_trust": "query_forecast_trust", "pipeline": "query_pipeline",
             "deal_risk": "query_high_priority_deal_risk", "loss_concentration": "query_loss_concentration"}
    parts = []
    if scenario == "base":
        parts.append(f"QUARTER HEALTH ({quarter}): answer \"are we in good shape this quarter?\" with a "
                     "plain-language verdict grounded only in the four figures in `figures`.")
    else:
        parts.append(f"QUARTER DOWNSIDE ({quarter}): answer what the downside looks like this quarter. "
                     "Lead with `downside`: worst_case_arr = forecast_arr - weighted_expected_loss, "
                     "stated with its `basis`; give unrated_at_risk_arr (and why those deals are "
                     "unrated) and floor_if_all_at_risk_lost beside it. Then a plain-language verdict "
                     "on the downside grounded in the four figures in `figures`.")
    parts.append("State each figure with its own basis from `disclosed_bases` (keep each basis's "
                 "caveats and wording rules: e.g. the pipeline total is current state, not this "
                 "quarter's).")
    parts.append("Do not combine the figures into a score, grade, index or overall number, and do not "
                 "weight one against another numerically: they measure different populations ("
                 + _POPULATIONS.format(q=quarter) + "). Do not add or subtract across them"
                 + (" (the worst case is the one defined calculation)." if scenario == "downside" else ".")
                 + " The verdict is a judgement in words: which figures point which way, and the "
                 "weakest one named.")
    if down:
        parts.append("Unavailable: " + ", ".join(f"{names[k]} ({figures[k].get('error')})" for k in down)
                     + ". Say that figure is unavailable; do not estimate it from the others.")
    not_ok = [k for k, v in figures.items() if v.get("status") not in ("ok", "unavailable")]
    if not_ok:
        parts.append("Gated (not an error): " + ", ".join(
            f"{names[k]} returned {figures[k].get('status')}" for k in not_ok)
            + ". Report its disclosed reason instead of a figure.")
    return " ".join(parts)
