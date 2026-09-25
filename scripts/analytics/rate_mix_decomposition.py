#!/usr/bin/env python3
"""
Rate-vs-mix decomposition — Tier B, stage 1 of rate/ratio root-cause.

Standalone and read-only, like Tier A (metric_reconciliation.py), the
qualification-crossing walk and the commit-cohort walk: no handler, no writes,
nothing reaches Slack.

A RATE metric (loss rate, win rate, coverage-ish ratios computed as a weighted
average of per-segment rates) can change between two populations for three
different reasons, and mistaking one for another is the Simpson's-paradox
trap this stage exists to rule out:

  rate effect   Σ_i w_old_i · (r_new_i − r_old_i)
                each segment's OWN rate moved, holding its share of the pool
                fixed. "Behavior changed."
  mix effect    Σ_i r_old_i · (w_new_i − w_old_i)
                the pool's COMPOSITION shifted toward segments that were
                always different, holding each segment's own rate fixed.
                "Composition changed, not behavior."
  interaction   Σ_i (w_new_i − w_old_i) · (r_new_i − r_old_i)
                the remainder, from weights and rates moving together.

The three sum to the observed change EXACTLY:

    rate_effect + mix_effect + interaction == R_new − R_old

by algebraic identity (not a statistical estimate), so — unlike Tier A —
there is no legitimate "unexplained residual". The result carries `residual`
and `reconciles` anyway; a non-zero residual is a bug, and the CLI/report say
so rather than hide it.

The overall rate is a weighted average of segment rates:
    R = Σ_i (n_i / N) · r_i = (Σ_i outcome-count_i) / N
so `outcome` (the numerator event, e.g. deal_status == 'lost') and `segment`
(the dimension to split by) are the only things that define the metric — both
are parameters, never hardcoded. The same function decomposes by rep, company
segment, pipeline, forecast tier, or any field/callable on the rows.

Empty cells. A segment present in only ONE population has no observed rate in
the other. Its rate there is imputed as the population where it IS present, so
its rate-change contribution is zero and its entire effect is attributed to
mix — the honest reading: a segment appearing in or vanishing from the pool is
a composition change, not a behavior change. This keeps the identity exact and
is flagged per segment (`*_imputed`).

    python scripts/analytics/rate_mix_decomposition.py --input pop.json \\
        --segment segment --outcome-field deal_status --outcome-value lost

--input takes {"baseline": [row,...], "comparison": [row,...]}; --segment is a
field name; the outcome event is --outcome-field == --outcome-value.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Union

_TERMS = ("rate_effect", "mix_effect", "interaction")


def _as_segment(segment) -> Callable[[dict], Any]:
    if callable(segment):
        return segment
    return lambda r: r.get(segment)


def _as_outcome(outcome) -> Callable[[dict], bool]:
    if callable(outcome):
        return lambda r: bool(outcome(r))
    field, value = outcome  # (field_name, value) convenience
    return lambda r: r.get(field) == value


def _rate(rows: List[dict], seg_val, seg: Callable, out: Callable):
    sub = [r for r in rows if seg(r) == seg_val]
    n = len(sub)
    rate = (sum(1 for r in sub if out(r)) / n) if n else None
    return n, rate


def decompose_rate(baseline_rows: List[dict], comparison_rows: List[dict], *,
                   segment: Union[str, Callable], outcome: Union[Callable, tuple],
                   baseline_label: str = "baseline",
                   comparison_label: str = "comparison") -> Dict[str, Any]:
    """Decompose (comparison rate − baseline rate) into rate / mix / interaction.

    baseline_rows / comparison_rows: the two populations (e.g. team vs one rep,
        this quarter vs last). The rate is losses/closed over each.
    segment: field name or callable → the dimension to split by.
    outcome: callable(row)->bool, or (field, value), → the numerator event.

    See the module docstring for the identity and the empty-cell rule.
    """
    seg = _as_segment(segment)
    out = _as_outcome(outcome)
    base_n, comp_n = len(baseline_rows), len(comparison_rows)
    if base_n == 0 or comp_n == 0:
        raise ValueError("both populations must be non-empty to compare their rates")

    seg_values = sorted(
        {seg(r) for r in baseline_rows} | {seg(r) for r in comparison_rows},
        key=lambda v: (v is None, str(v)))

    R_old = sum(1 for r in baseline_rows if out(r)) / base_n
    R_new = sum(1 for r in comparison_rows if out(r)) / comp_n
    total_delta = R_new - R_old

    rate_effect = mix_effect = interaction = 0.0
    segments: Dict[Any, Dict[str, Any]] = {}
    for sv in seg_values:
        no, ro = _rate(baseline_rows, sv, seg, out)
        nn, rn = _rate(comparison_rows, sv, seg, out)
        wo, wn = no / base_n, nn / comp_n
        # empty cell: impute the absent side's rate from the present side, so
        # the appearance/disappearance of a segment lands entirely in mix.
        base_imputed = ro is None
        comp_imputed = rn is None
        if base_imputed:
            ro = rn
        if comp_imputed:
            rn = ro
        re = wo * (rn - ro)
        me = ro * (wn - wo)
        ie = (wn - wo) * (rn - ro)
        rate_effect += re
        mix_effect += me
        interaction += ie
        segments[sv] = {
            "baseline_n": no, "baseline_rate": ro, "baseline_weight": wo,
            "comparison_n": nn, "comparison_rate": rn, "comparison_weight": wn,
            "baseline_imputed": base_imputed, "comparison_imputed": comp_imputed,
            "rate_effect": re, "mix_effect": me, "interaction": ie,
        }

    residual = total_delta - (rate_effect + mix_effect + interaction)
    dominant = max(_TERMS, key=lambda t: abs({"rate_effect": rate_effect,
                                              "mix_effect": mix_effect,
                                              "interaction": interaction}[t]))
    return {
        "baseline": {"label": baseline_label, "rate": R_old, "n": base_n},
        "comparison": {"label": comparison_label, "rate": R_new, "n": comp_n},
        "total_delta": total_delta,
        "rate_effect": rate_effect,
        "mix_effect": mix_effect,
        "interaction": interaction,
        "dominant": dominant,
        "residual": residual,
        "reconciles": abs(residual) < 1e-9,
        "segments": segments,
        "headline": _headline(comparison_label, baseline_label, total_delta,
                              rate_effect, mix_effect, interaction, dominant),
    }


def _headline(comp: str, base: str, total: float, rate: float, mix: float,
              inter: float, dominant: float) -> str:
    direction = "higher" if total > 0 else "lower" if total < 0 else "equal"
    pp = f"{abs(total) * 100:.1f}pp"
    if total == 0:
        return f"{comp}'s rate equals {base}'s — nothing to decompose."
    if dominant == "mix_effect":
        lead = (f"This is a COMPOSITION shift, not a behavior change: most of {comp}'s {pp} "
                f"{direction} rate comes from its pool being weighted toward segments that "
                f"already had different rates, not from its segments converting differently.")
    elif dominant == "rate_effect":
        lead = (f"This is a BEHAVIOR change, not composition: most of {comp}'s {pp} {direction} "
                f"rate comes from its segments' own rates moving, not from a different pool mix.")
    else:
        lead = (f"{comp}'s {pp} {direction} rate is driven by the INTERACTION of a shifting pool "
                f"and changing segment rates together.")
    return (lead + f" [rate {rate * 100:+.1f}pp | mix {mix * 100:+.1f}pp | "
            f"interaction {inter * 100:+.1f}pp]")


def report(d: Dict[str, Any], segment_label: str = "segment") -> str:
    out = []
    b, c = d["baseline"], d["comparison"]
    out.append(f"{c['label']} rate {c['rate']:.1%} (n={c['n']}) vs {b['label']} "
               f"{b['rate']:.1%} (n={b['n']}) — total {d['total_delta'] * 100:+.1f}pp")
    out.append(f"  rate effect  {d['rate_effect'] * 100:+7.2f}pp   (each segment's own rate moving)")
    out.append(f"  mix effect   {d['mix_effect'] * 100:+7.2f}pp   (pool composition shifting)")
    out.append(f"  interaction  {d['interaction'] * 100:+7.2f}pp   (both moving together)")
    out.append(f"  ── total     {(d['rate_effect'] + d['mix_effect'] + d['interaction']) * 100:+7.2f}pp"
               f"   residual {d['residual'] * 100:+.2e}pp  "
               f"({'reconciles' if d['reconciles'] else 'DOES NOT RECONCILE — BUG'})")
    out.append("")
    out.append(d["headline"])
    out.append("")
    out.append(f"  by {segment_label}:")
    for sv, s in d["segments"].items():
        flags = []
        if s["baseline_imputed"]:
            flags.append(f"{d['baseline']['label']} rate imputed (0 deals)")
        if s["comparison_imputed"]:
            flags.append(f"{d['comparison']['label']} rate imputed (0 deals)")
        flag = ("  [" + "; ".join(flags) + "]") if flags else ""
        out.append(
            f"    {str(sv):<18} {d['baseline']['label']}: {s['baseline_rate']:.0%} "
            f"w={s['baseline_weight']:.0%} (n={s['baseline_n']})  |  "
            f"{d['comparison']['label']}: {s['comparison_rate']:.0%} "
            f"w={s['comparison_weight']:.0%} (n={s['comparison_n']})  |  "
            f"rate {s['rate_effect'] * 100:+.1f} mix {s['mix_effect'] * 100:+.1f} "
            f"int {s['interaction'] * 100:+.1f}{flag}")
    return "\n".join(out)


def main():  # pragma: no cover - CLI wrapper
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, help="JSON: {baseline: [...], comparison: [...]}")
    ap.add_argument("--segment", required=True, help="row field to split by")
    ap.add_argument("--outcome-field", default="deal_status")
    ap.add_argument("--outcome-value", default="lost")
    ap.add_argument("--baseline-label", default="baseline")
    ap.add_argument("--comparison-label", default="comparison")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    data = json.loads(Path(args.input).read_text())
    d = decompose_rate(
        data["baseline"], data["comparison"],
        segment=args.segment, outcome=(args.outcome_field, args.outcome_value),
        baseline_label=args.baseline_label, comparison_label=args.comparison_label)
    print("Rate-vs-mix decomposition (Tier B stage 1), read-only.\n")
    print(report(d, args.segment))
    if args.json:
        print("\nJSON " + json.dumps(d, default=str))


if __name__ == "__main__":
    main()
