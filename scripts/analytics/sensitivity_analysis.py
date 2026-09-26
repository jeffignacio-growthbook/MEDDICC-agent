#!/usr/bin/env python3
"""
Single-factor "what if" sensitivity analysis — Tier C of the root-cause work.

Standalone and read-only, like Tier A (metric_reconciliation.py) and Tier B
stage 1 (rate_mix_decomposition.py): no handler, no writes, nothing reaches
Slack. It answers "what would the total be if ONE input were different" and
reports the real total, the hypothetical total, and the delta explicitly.

Two shapes, matching the two metric families the earlier tiers cover:

  rate  A weighted-average rate R = Σ_i w_i · r_i (loss rate, win rate). Hold
        every segment's WEIGHT fixed, substitute ONE segment's rate r_x with a
        hypothetical h, recompute:
            R_hyp = R + w_x · (h − r_x)
        so the delta is exactly w_x · (h − r_x). "team_average" is a named
        shortcut for h = R (the population's own overall rate). Pairs with
        rate_mix_decomposition: rate_sensitivity_from_decomposition() reads the
        per-segment weights and rates straight out of a decompose_rate result.

  sum   A sum-over-deals metric T = Σ_d value(d) (pipeline value, deal count).
        Substitute one or more deals' values with a hypothetical, recompute:
            T_hyp = T + Σ_d (h_d − v_d)
        Pairs with metric_reconciliation: sum_sensitivity_from_reconciliation()
        takes the real total from a reconcile() result's in-scope value and a
        list of per-deal {real_value, hypothetical_value} substitutions.

Null-scenario sanity check (required by design). Substituting a value back at
its REAL level must reproduce the real total EXACTLY — if it does not, the
substitution arithmetic is wrong. Both functions treat this as a first-class,
self-checking property: a null scenario that moves the total raises
AssertionError rather than returning a quietly-wrong number. `is_null` in the
result says whether the scenario was a no-op.

    python scripts/analytics/sensitivity_analysis.py rate --input rate.json \\
        --segment christian@growthbook.io --hypothetical team_average
    python scripts/analytics/sensitivity_analysis.py sum --input sum.json
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Union

_TEAM_AVG_ALIASES = {"team_average", "team average", "team_avg", "average", "avg"}


# ── rate sensitivity ──────────────────────────────────────────────────────

def _resolve_rate(hypothetical: Union[str, float], real_overall_rate: float) -> float:
    """A float hypothetical rate, or the 'team_average' shortcut resolved to the
    population's own overall rate."""
    if isinstance(hypothetical, str):
        key = hypothetical.strip().lower()
        if key in _TEAM_AVG_ALIASES:
            return real_overall_rate
        return float(hypothetical)  # a numeric string
    return float(hypothetical)


def rate_sensitivity(segment_table: Dict[Any, Dict[str, float]], segment_value,
                     hypothetical_rate: Union[str, float], *,
                     real_overall_rate: float = None,
                     segment_label: str = "segment") -> Dict[str, Any]:
    """Recompute a weighted-average rate with ONE segment's rate substituted,
    holding every segment's weight fixed.

    segment_table: {segment_value: {"weight": w, "rate": r}} for one population.
    segment_value: which segment's rate to substitute.
    hypothetical_rate: a float, a numeric string, or "team_average".
    real_overall_rate: the population's real overall rate. If given it is cross-
        checked against Σ w·r (a table that doesn't add up to its stated overall
        is a bug and raises); if omitted it is computed from the table.
    """
    if segment_value not in segment_table:
        raise ValueError(f"segment {segment_value!r} not in the table "
                         f"({sorted(segment_table)!r})")

    computed_overall = sum(s["weight"] * s["rate"] for s in segment_table.values())
    if real_overall_rate is not None and abs(computed_overall - real_overall_rate) > 1e-6:
        raise ValueError(
            f"segment table does not reconcile to the stated overall rate: "
            f"Σ w·r = {computed_overall:.6f} vs stated {real_overall_rate:.6f}")
    real_total = real_overall_rate if real_overall_rate is not None else computed_overall

    w_x = segment_table[segment_value]["weight"]
    r_x = segment_table[segment_value]["rate"]
    resolved = _resolve_rate(hypothetical_rate, real_total)

    hypothetical_total = real_total + w_x * (resolved - r_x)
    delta = hypothetical_total - real_total

    is_null = (resolved == r_x)
    if is_null and hypothetical_total != real_total:
        raise AssertionError(  # pragma: no cover - guards a substitution bug
            "null scenario (hypothetical == real) did not reproduce the real "
            f"total exactly: {hypothetical_total!r} != {real_total!r}")

    return {
        "kind": "rate",
        "real_total": real_total,
        "hypothetical_total": hypothetical_total,
        "delta": delta,
        "segment_label": segment_label,
        "segment_value": segment_value,
        "segment_weight": w_x,
        "segment_real_rate": r_x,
        "hypothetical_rate": resolved,
        "hypothetical_rate_input": hypothetical_rate,
        "is_null": is_null,
        "headline": (
            f"{segment_label} {segment_value}: real rate {r_x:.1%} (weight "
            f"{w_x:.1%}) -> hypothetical {resolved:.1%}. Overall rate "
            f"{real_total:.1%} -> {hypothetical_total:.1%} "
            f"({delta * 100:+.1f}pp)."
        ),
    }


def rate_sensitivity_from_decomposition(decomp: Dict[str, Any], segment_value,
                                        hypothetical_rate: Union[str, float], *,
                                        side: str = "comparison") -> Dict[str, Any]:
    """rate_sensitivity fed straight from a rate_mix_decomposition result. `side`
    picks which population's per-segment weights/rates to use ("comparison" or
    "baseline")."""
    if side not in ("comparison", "baseline"):
        raise ValueError("side must be 'comparison' or 'baseline'")
    table = {sv: {"weight": s[f"{side}_weight"], "rate": s[f"{side}_rate"]}
             for sv, s in decomp["segments"].items()}
    real_overall = decomp[side]["rate"]
    return rate_sensitivity(table, segment_value, hypothetical_rate,
                            real_overall_rate=real_overall)


# ── sum-metric sensitivity ────────────────────────────────────────────────

def sum_sensitivity(real_total: float, adjustments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Recompute a sum-over-deals total with one or more deals held at a
    hypothetical value.

    real_total: the metric's real total (e.g. a reconcile() result's in-scope
        value).
    adjustments: [{"deal_id", "label"?, "real_value", "hypothetical_value"}].
        Each deal's contribution to the metric moves from real_value to
        hypothetical_value (e.g. 0.0 for "would have exited scope").
    """
    real_total = float(real_total)
    out_adj = []
    total_delta = 0.0
    for a in adjustments:
        rv = float(a["real_value"])
        hv = float(a["hypothetical_value"])
        d = hv - rv
        total_delta += d
        out_adj.append({
            "deal_id": a.get("deal_id"),
            "label": a.get("label"),
            "real_value": rv,
            "hypothetical_value": hv,
            "delta": d,
        })

    hypothetical_total = real_total + total_delta
    is_null = all(a["delta"] == 0.0 for a in out_adj)
    if is_null and hypothetical_total != real_total:
        raise AssertionError(  # pragma: no cover - guards a substitution bug
            "null scenario (all hypothetical == real) did not reproduce the "
            f"real total exactly: {hypothetical_total!r} != {real_total!r}")

    return {
        "kind": "sum",
        "real_total": real_total,
        "hypothetical_total": hypothetical_total,
        "delta": total_delta,
        "adjustments": out_adj,
        "is_null": is_null,
        "headline": (
            f"{len(out_adj)} deal(s) held at a hypothetical value: total "
            f"{real_total:+,.2f} -> {hypothetical_total:+,.2f} "
            f"({total_delta:+,.2f})."
        ),
    }


def sum_sensitivity_from_reconciliation(recon_result: Dict[str, Any],
                                        adjustments: List[Dict[str, Any]], *,
                                        basis: str = "current_in_scope") -> Dict[str, Any]:
    """sum_sensitivity anchored on a metric_reconciliation result's in-scope
    total. `basis` is "current_in_scope" (default) or "prior_in_scope"."""
    if basis not in ("current_in_scope", "prior_in_scope"):
        raise ValueError("basis must be 'current_in_scope' or 'prior_in_scope'")
    real_total = recon_result[basis]["value"]
    return sum_sensitivity(real_total, adjustments)


# ── report + CLI ──────────────────────────────────────────────────────────

def report(result: Dict[str, Any]) -> str:
    out = [result["headline"], ""]
    if result["kind"] == "rate":
        out.append(f"  real overall rate    {result['real_total']:.4%}")
        out.append(f"  hypothetical rate    {result['hypothetical_total']:.4%}")
        out.append(f"  delta                {result['delta'] * 100:+.2f}pp")
        out.append(f"  ({result['segment_label']} {result['segment_value']}: "
                   f"{result['segment_real_rate']:.1%} -> "
                   f"{result['hypothetical_rate']:.1%}, weight "
                   f"{result['segment_weight']:.1%} held fixed)")
    else:
        out.append(f"  real total           {result['real_total']:+,.2f}")
        out.append(f"  hypothetical total   {result['hypothetical_total']:+,.2f}")
        out.append(f"  delta                {result['delta']:+,.2f}")
        for a in result["adjustments"]:
            out.append(f"    {str(a['deal_id']):<12} "
                       f"{a['real_value']:+,.2f} -> {a['hypothetical_value']:+,.2f} "
                       f"({a['delta']:+,.2f})")
    if result["is_null"]:
        out.append("  [null scenario: hypothetical == real, total unchanged]")
    return "\n".join(out)


def main():  # pragma: no cover - CLI wrapper
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)

    pr = sub.add_parser("rate", help="rate-based sensitivity")
    pr.add_argument("--input", required=True,
                    help='JSON: a rate_mix_decomposition result, or '
                         '{"segment_table": {...}, "real_overall_rate": ...}')
    pr.add_argument("--segment", required=True)
    pr.add_argument("--hypothetical", required=True,
                    help='a rate (0-1) or "team_average"')
    pr.add_argument("--side", default="comparison")

    ps = sub.add_parser("sum", help="sum-metric sensitivity")
    ps.add_argument("--input", required=True,
                    help='JSON: {"real_total": ..., "adjustments": [...]} or a '
                         'metric_reconciliation result with "adjustments"')
    ps.add_argument("--basis", default="current_in_scope")

    args = ap.parse_args()
    data = json.loads(Path(args.input).read_text())
    hyp = args.hypothetical if args.mode == "rate" else None
    if args.mode == "rate":
        h: Union[str, float] = hyp
        try:
            h = float(hyp)
        except (TypeError, ValueError):
            pass
        if "segments" in data:  # a decomposition result
            result = rate_sensitivity_from_decomposition(data, args.segment, h, side=args.side)
        else:
            result = rate_sensitivity(data["segment_table"], args.segment, h,
                                      real_overall_rate=data.get("real_overall_rate"))
    else:
        if "current_in_scope" in data or "prior_in_scope" in data:
            result = sum_sensitivity_from_reconciliation(data, data["adjustments"], basis=args.basis)
        else:
            result = sum_sensitivity(data["real_total"], data["adjustments"])

    print("Sensitivity analysis (single-factor what-if), read-only.\n")
    print(report(result))
    print("\nJSON " + json.dumps(result, default=str))


if __name__ == "__main__":
    main()
