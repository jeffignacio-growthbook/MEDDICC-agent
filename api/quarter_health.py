"""
Quarter health: one composer behind "are we in good shape this quarter?"
and its downside mirror.

compose_quarter_health() calls five existing primitives in a fixed order,
the same for both scenarios:

    query_forecast_trust            COMMIT+MOST_LIKELY forecast and its risk read
    query_pipeline                  current pipeline, the quarter's target
    query_pipeline_coverage         qualified pipeline weighted by current-stage rate
    query_high_priority_deal_risk   late-stage/COMMIT deals past their cycle
    query_loss_concentration        this quarter's losses and wins

plus one read of its own, bookings seasonality (scripts/bookings_seasonality.py).

Structure of the read (2026-09-25 reframe):
  1. Where the quarter stands: closed won QTD against target (QTD line) and
     pace: share of the quarter gone vs share of target won, with this
     business's own seasonality beside it (bookings are back-loaded and
     uneven here, so pace is never called ahead or behind on its own).
  2. The primary forward-looking figure: weighted remaining-gap coverage.
     query_pipeline_coverage's qualified Sales pipeline closing this
     quarter, each deal weighted by its current stage's governed close rate
     (query_stage_close_rate), against what is still needed (target minus
     closed won). The downside scenario gives the same figure with the
     forecast's high-risk deals removed. No flat historical rate is applied
     to anything.
  3. Modifiers on how far to trust that coverage, not verdict lines of
     their own: the forecast risk read (dollar shares), the qualified loss
     rate, and each rep's loss row with what they still have live.

Left out of the verdict (VERDICT_EXCLUDED, dropped before anything is
lifted): forecast_trust's historical same-week win rate (the "91 deals,
prior quarters" cohort) with its note and calibration evidence, until that
population is fully specified and verified; query_pipeline_coverage's
HEURISTIC proxy curve and quota-plus-stretch goal, which would compete with
the remaining-gap figure; and query_pipeline's standalone synthesis note,
which states the unweighted coverage ratio ("COVERAGE: 3.38x").

It invents no score. Each primitive's own figures go to synthesis as that
primitive returned them, and every basis statement it disclosed (outside
VERDICT_EXCLUDED) is lifted, verbatim, into `disclosed_bases` at the top of
the result, ahead of anything a character cut could reach.

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
from datetime import date

import api.handlers as handlers
from api.incremental_arr import incremental_arr

logger = logging.getLogger(__name__)

SCENARIOS = ("base", "downside")
# Handler names the two thin routed entry points will register under (both
# must go in api.evaluator.STRUCTURED_HANDLERS; see the survival test).
ENTRY_POINTS = {"base": "query_quarter_health", "downside": "query_quarter_downside"}
PRIMITIVE_ORDER = ("query_forecast_trust", "query_pipeline", "query_pipeline_coverage",
                   "query_high_priority_deal_risk", "query_loss_concentration")
# Dropped from the composed view before lifting, so neither the figures nor
# their notes reach synthesis. forecast_trust's same-week historical win rate
# ("91 deals, prior quarters") led to three wrong conclusions on 2026-09-25
# and its population is not yet fully specified; the coverage primitive's
# proxy curve and quota+stretch goal compete with the remaining-gap figure.
VERDICT_EXCLUDED = {
    "query_forecast_trust": ("historical", "calibration_evidence", "note", "stability",
                             "directional_caveat"),
    "query_pipeline_coverage": ("historical_heuristic_curve", "gap_to_goal", "real_target", "note"),
    # Written for a standalone pipeline answer: "COVERAGE: 3.38x" (the
    # unweighted ratio this view drops) and stage-breakdown/top-deal rules.
    # Its definitional rule (the total is current state, not this quarter's)
    # is in business_definition_note and the composer's own note.
    "query_pipeline": ("_synthesis_note",),
}
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
DROP_KEYS = {"query_pipeline": ("by_owner", "by_stage", "coverage_ratio")}
# Row lists whose rows are reduced to the primitive's own rendered line,
# which already states every number in the row.
TEXT_ROWS = {"query_loss_concentration": ("by_rep", "by_segment")}
# Keys the composed view carries once, in `figures` (or, for the headline, in
# the synthesis note, verbatim), not again in the primitive's copy.
IN_FIGURES = {"query_loss_concentration": (
    "closed_deal_count", "won_count", "lost_count", "qualified", "qualified_loss_rate",
    "all_closed_loss_rate", "excluded_from_qualified", "loss_rate_headline", "won_incremental_arr",
    "by_rep"),
    "query_forecast_trust": ("by_owner",)}
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
    """Call the primitives in PRIMITIVE_ORDER and compose. A primitive
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
    as_of = _today()
    try:
        from bookings_seasonality import assess_bookings_seasonality
        seasonality = assess_bookings_seasonality(sb, as_of=as_of)
    except Exception as e:
        logger.error(f"[QUARTER_HEALTH] bookings seasonality failed: {e}")
        seasonality = {"status": "error", "error": str(e)}
    return compose_from_results(results, scenario, stage_rates=stage_rates, deal_rows=deal_rows,
                                as_of=as_of, seasonality=seasonality)


def _today() -> date:
    from sdr_utils import today_in_reporting_tz
    return today_in_reporting_tz()


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
                         deal_rows: list = None, as_of: date = None,
                         seasonality: dict = None) -> dict:
    """Pure composition over the primitive results (keyed by name). as_of
    (default: today in the reporting timezone) sets days elapsed and weeks
    left; seasonality is assess_bookings_seasonality()'s result."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}")
    bases, primitives = [], {}
    for name in PRIMITIVE_ORDER:
        res = results.get(name)
        if not isinstance(res, dict):
            res = {"status": "error", "error": f"{name} returned nothing"}
        primitives[name] = _slim(name, _lift(name, _exclude(name, copy.deepcopy(res)), bases))

    figures = {
        "forecast_trust": _forecast_figures(results.get("query_forecast_trust")),
        "pipeline": _pipeline_figures(results.get("query_pipeline")),
        "deal_risk": _risk_figures(results.get("query_high_priority_deal_risk")),
        "loss_concentration": _loss_figures(results.get("query_loss_concentration")),
    }
    ctx = rep_context(results.get("query_loss_concentration"), results.get("query_forecast_trust"),
                      results.get("query_pipeline"))
    if ctx and figures["loss_concentration"].get("status") == "ok":
        figures["loss_concentration"].update(ctx)
    as_of = as_of or _today()
    figures["quarter_to_date"] = _qtd_figures(results.get("query_loss_concentration"),
                                              results.get("query_pipeline"),
                                              figures["forecast_trust"], as_of)
    figures["pace"] = pace_figures(figures["quarter_to_date"], results.get("query_pipeline"),
                                   seasonality, as_of)
    figures["coverage"] = coverage_figures(results.get("query_pipeline_coverage"),
                                           figures["quarter_to_date"])
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
        out["downside"] = downside_coverage(results.get("query_forecast_trust") or {},
                                            stage_rates or {}, deal_rows or [], figures["coverage"])
    out["primitives"] = primitives
    loss = results.get("query_loss_concentration")
    out["_synthesis_note"] = _note(scenario, quarter, figures,
                                   loss.get("loss_rate_headline") if isinstance(loss, dict) else None,
                                   (out.get("downside") or {}).get("line"))
    return out


# ------------------------------------------------------------------ lifting

def _exclude(prim: str, res):
    """Drop VERDICT_EXCLUDED keys before anything is lifted from them."""
    if isinstance(res, dict):
        dropped = [k for k in VERDICT_EXCLUDED.get(prim, ()) if res.pop(k, None) is not None]
        if dropped:
            res["_left_out_of_verdict"] = dropped
    return res


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
    # Not-assessed (Renewal-pipeline) deals: named, bounded; the reason is the
    # primitive's note, lifted into disclosed_bases once.
    holder, key = ((res.get("risk_not_assessed"), "deals") if prim == "query_forecast_trust"
                   else (res, "not_assessed_deals"))
    if isinstance(holder, dict) and isinstance(holder.get(key), list):
        na = holder.pop(key)
        holder["not_assessed_companies"] = [d.get("company_name") for d in na[:HIGH_RISK_KEEP]]
        holder["not_assessed_count"] = len(na)
    sw = res.get("stage_weighting") if prim == "query_pipeline_coverage" else None
    if isinstance(sw, dict) and isinstance(sw.get("by_stage_order"), dict):
        sw["win_rate_by_stage_order"] = {    # string keys, as a JSON payload has them
            str(k): (round(v["win_rate"], 4) if isinstance(v, dict) and v.get("win_rate") is not None else None)
            for k, v in sw.pop("by_stage_order").items()}
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
            omitted[dotted] = f"{n} rows not shown here; the counts above cover all {n}"
    for key in DROP_KEYS.get(prim, ()):
        if key in res:
            res.pop(key)
            omitted[key] = "not shown here"
    moved = [k for k in IN_FIGURES.get(prim, ()) if k in res and res.get("status") == "ok"]
    for k in moved:
        res.pop(k)
    if moved:
        res["_in_figures"] = (
            "in figures.loss_concentration (rep rows in rep_context); the loss-rate headline is in "
            "_synthesis_note" if prim == "query_loss_concentration"
            else "by_owner is joined into figures.loss_concentration.rep_context")
    excl = res.get("by_rep_excluded") if prim == "query_loss_concentration" else None
    if isinstance(excl, list):
        res["by_rep_excluded"] = [
            f"{e.get('owner_email')} ({e.get('role')}): {e.get('closed_all')} closed, "
            f"{e.get('qualified_closed')} qualified; not in by_rep ({e.get('reason')})"
            for e in excl if isinstance(e, dict)]
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
            "current_week": res.get("current_week"),
            "forecast_arr": p.get("incremental_arr"), "forecast_deal_count": p.get("deal_count"),
            "high_risk_count": res.get("high_risk_count"),
            "high_risk_fraction": res.get("high_risk_fraction"),
            "high_risk_fraction_basis": "share of risk-assessed deals (by count), not of the forecast",
            "assessed_deal_count": (res.get("risk_summary") or {}).get("total_assessed"),
            "not_assessed_deal_count": (res.get("risk_summary") or {}).get("not_assessed"),
            **{k: (res.get("risk_dollars") or {}).get(k)
               for k in ("high_risk_arr", "high_risk_share_of_forecast", "not_assessed_arr",
                         "not_assessed_share_of_forecast") if res.get("risk_dollars")}}


def _pipeline_figures(res):
    bad = _unavailable(res)
    if bad:
        return bad
    keys = ("total_pipeline", "total_deals", "q3_scoped_pipeline", "q3_scoped_deals",
            "quarterly_target", "this_quarter")
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
    keys = ("status", "period", "closed_deal_count", "won_count", "lost_count", "qualified",
            "qualified_loss_rate", "all_closed_loss_rate", "excluded_from_qualified",
            "won_incremental_arr")
    return {k: res.get(k) for k in keys if k in res}


def rep_context(loss, ft, pipe):
    """Each qualified-loss rep row with what that rep still has live: their
    forecast this quarter (query_forecast_trust.by_owner, COMMIT and Most
    Likely) and their open pipeline (query_pipeline.by_owner), both as the
    primitives returned them. None when there are no rep rows."""
    rows = (loss or {}).get("by_rep") if isinstance(loss, dict) else None
    if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
        return None
    fc = (ft or {}).get("by_owner") if (ft or {}).get("status") == "ok" else None
    pp = (pipe or {}).get("by_owner") if not _unavailable(pipe) else None

    def live(owner):
        if fc is None:
            f = "forecast by rep unavailable"
        elif owner in fc:
            o = fc[owner]
            n = o.get("deal_count") or 0
            f = (f"${o['forecast_arr']:,.0f} forecast (COMMIT ${o['commit_arr']:,.0f}, Most Likely "
                 f"${o['most_likely_arr']:,.0f}; {n} deal{'' if n == 1 else 's'})")
        else:
            f = "$0 forecast (no COMMIT or Most Likely deals closing this quarter)"
        if pp is None:
            p = "open pipeline unavailable"
        elif owner in pp:
            p = f"${pp[owner].get('value') or 0:,.0f} open pipeline ({pp[owner].get('count')} deals)"
        else:
            p = "open pipeline not among query_pipeline's top 10 owners"
        return f"{f}; {p}"

    return {
        "rep_context": [f"{r.get('text')} | still live: {live(r.get('owner_email'))}" for r in rows],
        "rep_context_basis": (
            "Loss rows are this quarter's closed qualified deals (backward-looking); 'still live' is "
            "what the rep has open now. Forecast = the rep's COMMIT + Most Likely incremental ARR "
            "closing this quarter (query_forecast_trust.by_owner: the forecast total's own deals). "
            "Open pipeline = all the rep's active incremental pipeline, any close date "
            "(query_pipeline.by_owner, top 10 owners; current state, not this quarter)."),
    }


def _qtd_figures(loss, pipe, ft: dict, as_of: date) -> dict:
    """Closed won QTD vs the quarter's target, the gap, weeks left, and the
    gap as a share of the forecast. Reuses what the primitives already
    fetched; unavailable (with the reason, and no line) rather than guessed
    when a piece is missing or the two quarters disagree."""
    def na(reason):
        return {"status": "unavailable", "reason": reason}
    for name, res in (("query_loss_concentration", loss), ("query_pipeline", pipe)):
        bad = _unavailable(res)
        if bad:
            return na(f"{name} unavailable ({bad['error']})")
    won, target = loss.get("won_incremental_arr"), pipe.get("quarterly_target")
    tq = pipe.get("this_quarter") or {}
    q = loss.get("period") or ""
    if won is None:
        return na("query_loss_concentration returned no closed-won incremental ARR")
    if not target:
        return na(f"no quarterly target in rep_targets for {tq.get('label') or q or 'this quarter'}")
    if q != (tq.get("label") or "") or not tq.get("end"):
        return na(f"quarter mismatch: closed won is for {q!r}, the target is for {tq.get('label')!r}")
    end = date.fromisoformat(str(tq["end"])[:10])
    days_left = max((end - as_of).days, 0)
    weeks_left = days_left // 7
    left = (f"{weeks_left} week{'' if weeks_left == 1 else 's'} left" if weeks_left
            else f"{days_left} day{'' if days_left == 1 else 's'} left")
    remaining = target - won
    gap = (f"(${remaining:,.0f} remaining)" if remaining > 0 else f"(${-remaining:,.0f} over target)")
    line = (f"${won:,.0f} closed won QTD against the ${target:,.0f} target {gap}, with {left} "
            "in the quarter.")
    forecast = ft.get("forecast_arr") if ft.get("status") == "ok" else None
    share = remaining / forecast if (forecast and remaining > 0) else None
    if share is not None and share <= 1:
        line += (f" Closing that gap takes {share:.0%} of the ${forecast:,.0f} forecast "
                 "(COMMIT+MOST_LIKELY deals closing this quarter).")
    elif share is not None:
        line += (f" The gap is larger than the whole ${forecast:,.0f} forecast (COMMIT+MOST_LIKELY "
                 f"deals closing this quarter): {share:.0%} of it.")
    return {
        "status": "ok", "fiscal_quarter": q,
        "closed_won_arr": won, "closed_won_count": loss.get("won_count"), "target": target,
        "remaining_to_target": remaining, "days_left": days_left, "weeks_left": weeks_left,
        "forecast_arr": forecast, "remaining_share_of_forecast": share,
        "line": line,
        "basis": (f"Closed won = new+expansion ARR of the {loss.get('won_count')} deals won in {q} "
                  "(query_loss_concentration's rows). Target = rep_targets team incremental_arr, "
                  f"as query_pipeline reads it. Weeks left = whole weeks from {as_of.isoformat()} to "
                  f"{end.isoformat()}. Share of forecast = remaining / query_forecast_trust's open "
                  "COMMIT+MOST_LIKELY ARR: what has to close, not a prediction."),
    }


# ----------------------------------------------------------------- downside

def _sales_stage_orders():
    from utils import get_pipeline_config
    for p in get_pipeline_config().get("pipelines", []):
        if str(p.get("id")) == SALES_PIPELINE:
            return {str(s["id"]): s["order"] for s in p.get("stages", [])}
    return {}


def _money(x):
    return f"${x:,.0f}"


def pace_figures(qtd: dict, pipe, seasonality, as_of: date) -> dict:
    """Share of the quarter gone vs share of target closed won, with this
    business's own bookings seasonality beside it. Never an ahead/behind
    verdict: the seasonality line says why pace alone can't give one."""
    tq = (pipe or {}).get("this_quarter") if isinstance(pipe, dict) else None
    if qtd.get("status") != "ok" or not isinstance(tq, dict) or not tq.get("start") or not tq.get("end"):
        return {"status": "unavailable",
                "reason": qtd.get("reason") or "no quarter dates or QTD figure to take pace from"}
    start, end = date.fromisoformat(str(tq["start"])[:10]), date.fromisoformat(str(tq["end"])[:10])
    days = (end - start).days + 1
    elapsed = min(max((as_of - start).days + 1, 0), days)
    won, target = qtd["closed_won_arr"], qtd["target"]
    line = (f"{elapsed} of {days} days ({elapsed / days:.0%}) of the quarter have passed and "
            f"{won / target:.0%} of the {_money(target)} target ({_money(won)}) is closed won.")
    sz = seasonality if isinstance(seasonality, dict) else {}
    if sz.get("status") == "ok":
        n = len(sz.get("quarters") or [])
        caveat = (f"Bookings here are back-loaded and uneven: over the last {n} complete quarters, "
                  f"{sz['min_share_by_this_point']:.0%} to {sz['max_share_by_this_point']:.0%} "
                  f"(median {sz['median_share_by_this_point']:.0%}) of a quarter's closed-won ARR was "
                  f"in by this point, and a median {sz['median_share_final_week']:.0%} closed in the "
                  "final week, so pace alone doesn't show whether this quarter is ahead or behind.")
    else:
        why = sz.get("reason") or sz.get("error") or "no bookings history read"
        caveat = (f"No seasonality read ({why}), so pace alone doesn't show whether this quarter is "
                  "ahead or behind.")
    return {"status": "ok", "days_elapsed": elapsed, "days_in_quarter": days,
            "elapsed_share": elapsed / days, "target_share_won": won / target,
            "line": line, "seasonality_line": caveat,
            "seasonality": {k: sz.get(k) for k in ("status", "median_share_by_this_point",
                                                    "min_share_by_this_point", "max_share_by_this_point",
                                                    "median_share_final_week", "quarters_with_bookings")
                            if k in sz},
            "basis": ("Days: this quarter's dates from query_pipeline, today counted. Target share: "
                      "closed won QTD / target (figures.quarter_to_date). Seasonality: "
                      "scripts/bookings_seasonality.py, the share of each past quarter's closed-won "
                      "incremental ARR closed by the same point of that quarter.")}


def coverage_figures(cov, qtd: dict) -> dict:
    """The primary forward-looking figure: qualified Sales pipeline closing
    this quarter, each deal weighted by its current stage's governed close
    rate (query_pipeline_coverage), against what is still needed (target
    minus closed won, figures.quarter_to_date)."""
    bad = _unavailable(cov)
    if bad:
        return {"status": "unavailable", "reason": f"query_pipeline_coverage unavailable ({bad['error']})"}
    if qtd.get("status") != "ok":
        return {"status": "unavailable", "reason": f"no remaining gap: {qtd.get('reason')}"}
    q, sw = cov.get("qualified_pipeline") or {}, cov.get("stage_weighting") or {}
    rn = cov.get("renewal_not_weighted") or {}
    weighted, raw, n = sw.get("weighted_value"), q.get("raw_value"), q.get("deal_count")
    remaining = qtd["remaining_to_target"]
    if weighted is None or raw is None:
        return {"status": "unavailable", "reason": "query_pipeline_coverage returned no weighted value"}
    out = {"status": "ok", "qualified_pipeline_arr": raw, "qualified_deal_count": n,
           "weighted_arr": weighted, "remaining_to_target": remaining,
           "unweighted_arr": sw.get("unweighted_value"),
           "unweighted_deal_count": sw.get("unweighted_deal_count"),
           "renewal_not_weighted_arr": rn.get("value"),
           "renewal_not_weighted_count": rn.get("deal_count")}
    if remaining <= 0:
        out["coverage_of_remaining"] = None
        line = (f"The target is already met; weighted by each deal's current-stage close rate, the "
                f"{_money(raw)} of qualified Sales pipeline closing this quarter ({n} deals) is worth "
                f"{_money(weighted)} on top.")
    else:
        out["coverage_of_remaining"] = weighted / remaining
        line = (f"Weighted by each deal's current-stage close rate, the {_money(raw)} of qualified "
                f"Sales pipeline closing this quarter ({n} deals) is worth {_money(weighted)}: "
                f"{weighted / remaining:.2f}x the {_money(remaining)} still needed to reach target.")
    extra = []
    if sw.get("unweighted_deal_count"):
        extra.append(f"{sw['unweighted_deal_count']} deal(s) ({_money(sw.get('unweighted_value') or 0)}) "
                     "at a stage with too little history have no rate and are not counted")
    if rn.get("deal_count"):
        extra.append(f"{_money(rn.get('value') or 0)} of Renewal-pipeline expansion "
                     f"({rn['deal_count']} deal{'' if rn['deal_count'] == 1 else 's'}) has no stage rate "
                     "and is not counted")
    if extra:
        line += " " + "; ".join(extra)[0].upper() + "; ".join(extra)[1:] + "."
    out["line"] = line
    out["basis"] = ("Stage rate: the share of deals at that stage during a quarter that closed won by "
                    "quarter end (won / (won + lost + slipped)), pooled over complete past quarters, "
                    "Sales-pipeline New+Expansion only (query_stage_close_rate, as "
                    "query_pipeline_coverage uses it). It is not specific to the weeks left. Still "
                    "needed = target - closed won QTD (figures.quarter_to_date).")
    return out


def downside_coverage(forecast_trust: dict, stage_rates: dict, deal_rows: list, cov: dict) -> dict:
    """The coverage figure with the forecast's high-risk deals removed.

    At-risk deals: query_forecast_trust's high_risk deals (assess_deal_risk
    labels). Each Sales-pipeline deal's weighted value is its incremental
    ARR x its current stage's governed rate: the same rate
    query_pipeline_coverage gave it, so removing it takes out exactly what
    that deal added to the weighted figure. A deal with no rate (Renewal
    pipeline, a stage without enough history, no deals row) added nothing
    and is listed as unrated."""
    fq = forecast_trust.get("fiscal_quarter") or "this quarter"
    if forecast_trust.get("status") != "ok":
        return {"status": "unavailable",
                "reason": f"query_forecast_trust returned {forecast_trust.get('status') or 'no result'}: "
                          "no high-risk deals to take out"}
    if cov.get("status") != "ok" or cov.get("coverage_of_remaining") is None:
        return {"status": "unavailable",
                "reason": cov.get("reason") or "no weighted coverage of a remaining gap to take them from"}
    by_order = (stage_rates or {}).get("by_stage_order") or {}
    orders = _sales_stage_orders()
    rows = {str(r.get("deal_id")): r for r in deal_rows or []}
    deals, at_risk_weighted, total = [], 0.0, 0.0
    for d in _high_risk(forecast_trust):
        did = str(d.get("deal_id"))
        r = rows.get(did)
        item = {"deal_id": did, "company_name": d.get("company_name"),
                "pipeline_id": (r or {}).get("pipeline_id"), "incremental_arr": None,
                "stage_order": None, "stage_win_rate": None, "weighted_arr": None,
                "unrated_reason": None}
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
                item["stage_win_rate"] = round(wr, 4)
                item["weighted_arr"] = round(arr * wr, 2)
                at_risk_weighted += arr * wr
        deals.append(item)
    remaining, weighted = cov["remaining_to_target"], cov["weighted_arr"]
    after = weighted - at_risk_weighted
    k = len(deals)
    line = (f"If the {k} high-risk forecast deal{'' if k == 1 else 's'} ({_money(total)}) "
            f"{'is' if k == 1 else 'are'} lost, weighted coverage falls from {_money(weighted)} to "
            f"{_money(after)}: {after / remaining:.2f}x the {_money(remaining)} still needed "
            f"(was {cov['coverage_of_remaining']:.2f}x).")
    unrated = [x for x in deals if x["weighted_arr"] is None]
    renewals = len(((forecast_trust.get("risk_not_assessed") or {}).get("deals")) or [])
    moderate = sum(1 for d in (forecast_trust.get("assessed_deals") or [])
                   if d.get("overall_label") == "moderate_risk")
    listed = sorted(deals, key=lambda x: -(x["incremental_arr"] or 0))[:AT_RISK_KEEP]
    return {
        "status": "ok", "fiscal_quarter": fq,
        "at_risk_count": k, "at_risk_arr": total, "at_risk_weighted_arr": at_risk_weighted,
        "weighted_arr_if_lost": after, "coverage_of_remaining_if_lost": after / remaining,
        "unrated_count": len(unrated), "renewal_not_assessed_count": renewals,
        "moderate_risk_excluded_count": moderate,
        "line": line,
        "at_risk_deals": listed,
        **({"at_risk_deals_omitted": f"{k - len(listed)} smaller at-risk deals not listed; "
                                     "every total above covers all of them"} if k > len(listed) else {}),
        "basis": (f"At-risk deals: the high-risk deals in query_forecast_trust's forecast "
                  f"(COMMIT+MOST_LIKELY closing in {fq}; assess_deal_risk labels, basis in "
                  "disclosed_bases). Each Sales-pipeline deal's weighted value is its incremental ARR "
                  "x its current stage's governed rate (query_stage_close_rate), the same rate the "
                  "coverage figure gave it, so taking it out removes exactly what it added. Deals with "
                  "no rate added nothing and are listed as unrated. Only high_risk deals are taken "
                  f"out: {moderate} moderate_risk deal{'' if moderate == 1 else 's'} in the forecast "
                  "(0-30 days past the cycle benchmark) not taken out, and low_risk and "
                  f"insufficient_data deals are not either. {renewals} Renewal-pipeline deal"
                  f"{'' if renewals == 1 else 's'} in the forecast "
                  f"{'is' if renewals == 1 else 'are'} not risk-assessed (reason in disclosed_bases)."),
    }


# --------------------------------------------------------------------- note

_POPULATIONS = (
    "coverage = qualified Sales pipeline closing in {q} against what {q} still needs; forecast_trust "
    "= COMMIT+MOST_LIKELY deals closing in {q}; pipeline = all active incremental ARR (current "
    "state, not this quarter); deal_risk = late-stage or COMMIT deals closing in {q}; "
    "loss_concentration = deals closed in {q}"
)


def forecast_risk_headline(ft: dict):
    """The dollar read of the forecast risk labels, built in code:
    high-risk and not-assessed ARR as shares of the WHOLE forecast. None
    when the forecast figures carry no risk dollars (gated, unavailable, or
    an older primitive)."""
    f, hi, na = ft.get("forecast_arr"), ft.get("high_risk_arr"), ft.get("not_assessed_arr")
    if not f or hi is None or na is None:
        return None
    k = ft.get("not_assessed_deal_count") or 0
    return (f"{hi / f:.0%} of the forecast (${hi:,.0f} of ${f:,.0f}) is high risk; "
            f"{na / f:.0%} (${na:,.0f} across {k} Renewal-pipeline deal{'' if k == 1 else 's'}) "
            "has no risk read yet.")


def _q(line: str) -> str:
    return "\"" + line + "\""


def _note(scenario: str, quarter: str, figures: dict, loss_headline: str = None,
          downside_line: str = None) -> str:
    names = {"forecast_trust": "query_forecast_trust", "pipeline": "query_pipeline",
             "deal_risk": "query_high_priority_deal_risk", "loss_concentration": "query_loss_concentration",
             "quarter_to_date": "quarter_to_date (QTD closed won vs target)",
             "pace": "pace (share of quarter gone vs share of target won)",
             "coverage": "coverage (weighted pipeline vs what is still needed)"}
    parts = []
    if scenario == "base":
        parts.append(f"QUARTER HEALTH ({quarter}): answer \"are we in good shape this quarter?\" in "
                     "three steps, in this order.")
    else:
        parts.append(f"QUARTER DOWNSIDE ({quarter}): answer what the downside looks like this quarter "
                     "in three steps, in this order.")
    qtd, pace, cov = (figures.get(k) or {} for k in ("quarter_to_date", "pace", "coverage"))
    step1 = ["1. WHERE THE QUARTER STANDS. State, verbatim:"]
    step1 += [_q(x) for x in (qtd.get("line"), pace.get("line"), pace.get("seasonality_line")) if x]
    step1.append("Do not call the quarter ahead or behind from pace.")
    parts.append(" ".join(step1))
    step2 = ("2. COVERAGE, THE FORWARD-LOOKING READ. State, verbatim: " + _q(cov["line"])
             if cov.get("line") else "2. COVERAGE: unavailable (see below).")
    if scenario == "downside":
        dl = downside_line
        if dl:
            step2 += " Then the downside, verbatim: " + _q(dl) + " List the at-risk deals from `downside`."
    step2 += (" This is the only coverage figure: do not quote query_pipeline's unweighted coverage "
              "ratio, do not apply any single historical win rate to the forecast or the pipeline, and "
              "do not project a quarter-end total.")
    parts.append(step2)
    step3 = ["3. HOW FAR TO TRUST THAT COVERAGE. These are modifiers on the coverage read, not "
             "separate verdicts: say for each whether it makes the coverage figure more or less "
             "reliable, and why."]
    headline = forecast_risk_headline(figures.get("forecast_trust") or {})
    if headline:
        step3.append("Forecast risk, verbatim: " + _q(headline) + " (the deal-count fraction, if "
                     "given, is a share of risk-assessed deals, not of the forecast).")
    if loss_headline:
        step3.append("Loss rate, verbatim: " + _q(loss_headline) + " Never give the all-closed rate "
                     "alone or call it the loss rate.")
    if (figures.get("loss_concentration") or {}).get("rep_context"):
        step3.append("Reps: never give a rep's loss rate on its own; give each rep's line from "
                     "figures.loss_concentration.rep_context with its 'still live' forecast and open "
                     "pipeline (basis: rep_context_basis).")
    parts.append(" ".join(step3))
    parts.append("State each figure with its own basis from `figures` and `disclosed_bases` (keep each "
                 "basis's caveats and wording rules: e.g. the pipeline total is current state, not "
                 "this quarter's).")
    parts.append("Do not combine the figures into a score, grade, index or overall number: they "
                 "measure different populations (" + _POPULATIONS.format(q=quarter) + "). The defined "
                 "calculations are the ones given above; do not add, subtract or multiply across "
                 "figures yourself. The verdict is a judgement in words on the coverage read, "
                 "adjusted by the modifiers, with the weakest point named.")
    down = [k for k, v in figures.items() if isinstance(v, dict) and v.get("status") == "unavailable"]
    if down:
        parts.append("Unavailable: " + ", ".join(
            f"{names.get(k, k)} ({figures[k].get('error') or figures[k].get('reason')})" for k in down)
            + ". Say that figure is unavailable; do not estimate it from the others.")
    not_ok = [k for k, v in figures.items()
              if isinstance(v, dict) and v.get("status") not in ("ok", "unavailable")]
    if not_ok:
        parts.append("Gated (not an error): " + ", ".join(
            f"{names.get(k, k)} returned {figures[k].get('status')}" for k in not_ok)
            + ". Report its disclosed reason instead of a figure.")
    return " ".join(parts)
