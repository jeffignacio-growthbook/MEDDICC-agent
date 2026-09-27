#!/usr/bin/env python3
"""
Dimensional root-cause ranking — Tier B, Stage 2.

Given a rate anomaly already identified by Stage 1 decompose_rate, enumerate
candidate dimension-value slices (single dimensions first, then pairs; depth ≤ 2)
and rank them by Adtributor-style EP × Surprise score:

    score = alignment × weight_v × (rate_gap_v / total_delta)²

where:
    weight_v      = n_baseline_v / N_baseline      (slice's share of baseline)
    rate_gap_v    = r_comparison_v − r_baseline_v  (local rate change in this slice)
    total_delta   = R_comparison − R_baseline       (global rate change)
    alignment     = +1 if rate_gap and total_delta have the same sign (contributing)
                    −1 if opposite sign (offsetting)

This is equivalent to EP × Surprise with sign:
    EP       = contribution / total_delta  (fraction of total explained)
    Surprise = rate_gap / total_delta      (how extreme the local gap is vs global)

The trivial failure mode — always ranking the largest slice highest regardless
of whether it is anomalous — is prevented by the Surprise factor: a large slice
with a proportional rate gap scores no higher than any proportional slice; only a
disproportionate rate gap lifts Surprise > 1 and boosts the combined score.

Usage (standalone):
    python scripts/analytics/dimensional_rank.py --fixture tests/fixtures/qualified_loss_fy2027_q3_2026_09_25.json
"""
import argparse
import itertools
import json
import sys
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple, Union

REPO = Path(__file__).parent.parent.parent


def _as_key(dimension) -> Tuple[Callable, str]:
    """Return (key_function, display_name) for a dimension."""
    if callable(dimension):
        name = getattr(dimension, "__name__", repr(dimension))
        return dimension, name
    return (lambda r, d=dimension: r.get(d)), str(dimension)


def _as_outcome(outcome) -> Callable:
    if callable(outcome):
        return outcome
    field, value = outcome
    return lambda r: r.get(field) == value


def _score_slice(base_rows, comp_rows, *, key_fn, out_fn, value, total_delta, N_base):
    """Compute the Adtributor-style score for one (dimension, value) slice."""
    base_sub = [r for r in base_rows if key_fn(r) == value]
    comp_sub = [r for r in comp_rows if key_fn(r) == value]
    n_b, n_c = len(base_sub), len(comp_sub)

    r_b = (sum(1 for r in base_sub if out_fn(r)) / n_b) if n_b > 0 else None
    r_c = (sum(1 for r in comp_sub if out_fn(r)) / n_c) if n_c > 0 else None

    imputed_b = r_b is None
    imputed_c = r_c is None
    if imputed_b and imputed_c:
        return None  # completely absent from both sides; skip
    if imputed_b:
        r_b = r_c   # absent from baseline: segment appeared; contribution is mix only
    if imputed_c:
        r_c = r_b   # absent from comparison: segment disappeared; contribution is mix only

    rate_gap = r_c - r_b
    weight = n_b / N_base
    contribution = weight * rate_gap

    if abs(total_delta) < 1e-9:
        ep = surprise = score = 0.0
    else:
        ep = contribution / total_delta
        surprise = rate_gap / total_delta
        # Positive score = contributing (aligns with total_delta direction)
        # Negative score = offsetting (works against total_delta)
        alignment = 1 if (rate_gap * total_delta >= 0) else -1
        score = alignment * weight * (rate_gap / total_delta) ** 2

    return {
        "rate_baseline": r_b,
        "rate_comparison": r_c,
        "rate_gap": rate_gap,
        "n_baseline": n_b,
        "n_comparison": n_c,
        "weight_baseline": weight,
        "contribution": contribution,
        "ep": ep,
        "surprise": surprise,
        "score": score,
        "imputed_baseline": imputed_b,
        "imputed_comparison": imputed_c,
    }


def rank_rate_dimensions(
    baseline_rows: list,
    comparison_rows: list,
    *,
    dimensions: list,
    outcome,
    max_depth: int = 2,
    min_n: int = 2,
    total_delta: Optional[float] = None,
) -> dict:
    """
    Enumerate dimension-value slices and rank by EP × Surprise score.

    Parameters
    ----------
    baseline_rows : list of dicts
        The reference population (e.g. the team, or last quarter).
    comparison_rows : list of dicts
        The anomalous population (e.g. one rep, or this quarter).
    dimensions : list of str or callable
        Field names or (row → value) callables to enumerate.
        Pairs are formed by itertools.combinations up to max_depth=2.
    outcome : callable or (field, value) tuple
        The binary outcome defining the rate (e.g. ("deal_status", "lost")).
    max_depth : int
        Maximum number of dimensions to cross. 1 = single only, 2 = single + pairs.
    min_n : int
        Minimum baseline-count to include a slice. Slices with n_baseline < min_n
        are skipped (avoids noise from single-deal outliers).
    total_delta : float, optional
        Override for R_comparison − R_baseline. Computed from rows if omitted.

    Returns
    -------
    dict with keys:
        total_delta, baseline_rate, comparison_rate,
        candidates   : all scored slices sorted by score descending
        contributing : slices with score > 0 (explain the anomaly)
        offsetting   : slices with score < 0 (work against the anomaly)
        summary      : human-readable ranking report
    """
    if not baseline_rows or not comparison_rows:
        raise ValueError("Both populations must be non-empty")

    out_fn = _as_outcome(outcome)
    N_base = len(baseline_rows)
    N_comp = len(comparison_rows)

    R_base = sum(1 for r in baseline_rows if out_fn(r)) / N_base
    R_comp = sum(1 for r in comparison_rows if out_fn(r)) / N_comp
    if total_delta is None:
        total_delta = R_comp - R_base

    results = []

    for depth in range(1, min(max_depth, len(dimensions)) + 1):
        for dim_combo in itertools.combinations(range(len(dimensions)), depth):
            dims = [dimensions[i] for i in dim_combo]
            kfns_names = [_as_key(d) for d in dims]
            kfns = [kn[0] for kn in kfns_names]
            names = [kn[1] for kn in kfns_names]

            if depth == 1:
                key_fn = kfns[0]
                dim_label = names[0]
            else:
                def key_fn(r, ks=kfns): return tuple(k(r) for k in ks)
                dim_label = " × ".join(names)

            all_values = sorted(
                {key_fn(r) for r in baseline_rows} | {key_fn(r) for r in comparison_rows},
                key=lambda v: (v is None, str(v)),
            )

            for value in all_values:
                s = _score_slice(
                    baseline_rows, comparison_rows,
                    key_fn=key_fn, out_fn=out_fn,
                    value=value, total_delta=total_delta, N_base=N_base,
                )
                if s is None or s["n_baseline"] < min_n:
                    continue
                results.append({"dimension": dim_label, "value": value, **s})

    results.sort(key=lambda x: x["score"], reverse=True)
    contributing = [r for r in results if r["score"] > 0]
    offsetting = [r for r in results if r["score"] < 0]
    # score == 0 slices (no gap) are dropped from both lists but kept in candidates

    return {
        "total_delta": total_delta,
        "baseline_rate": R_base,
        "comparison_rate": R_comp,
        "candidates": results,
        "contributing": contributing,
        "offsetting": offsetting,
        "summary": _format_summary(
            total_delta=total_delta, R_base=R_base, R_comp=R_comp,
            N_base=N_base, N_comp=N_comp, contributing=contributing,
        ),
    }


def _format_summary(*, total_delta, R_base, R_comp, N_base, N_comp, contributing):
    lines = [
        f"Rate: {R_base:.1%} → {R_comp:.1%}  "
        f"(Δ {total_delta:+.1%},  baseline N={N_base},  comparison N={N_comp})",
        "",
    ]
    if not contributing:
        lines.append("No dimension-value slice contributes to the rate anomaly.")
        return "\n".join(lines)

    lines.append(f"{'#':<4} {'Dimension = Value':<42}  {'EP':>7}  {'Surprise':>9}  {'Score':>8}")
    lines.append("─" * 76)

    top = contributing[0]["score"]
    for i, c in enumerate(contributing[:12], 1):
        label = f"{c['dimension']} = {c['value']}"
        note = ""
        if i == 1 and len(contributing) > 1:
            gap_pct = (top - contributing[1]["score"]) / top * 100
            if gap_pct >= 50:
                note = "  ◀ clearly dominant"
            elif gap_pct >= 20:
                note = "  ◀ leading"
        lines.append(
            f"{i:<4} {label:<42}  {c['ep']:>6.1%}  {c['surprise']:>8.2f}×  {c['score']:>8.4f}{note}"
        )

    if len(contributing) > 12:
        lines.append(f"     … {len(contributing) - 12} more contributing slices")

    if len(contributing) >= 2:
        gap_pct = (top - contributing[1]["score"]) / top * 100
        lines += [
            "",
            f"Dominance gap (#1 vs #2): {gap_pct:.0f}%  "
            f"({'clearly dominant' if gap_pct >= 50 else 'marginally ahead' if gap_pct < 20 else 'leading'})",
        ]
    return "\n".join(lines)


def _load_demo_fixture(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def _cli():
    ap = argparse.ArgumentParser(description="Dimensional root-cause ranking (Stage 2)")
    ap.add_argument("--fixture", required=True, help="Path to qualified_loss fixture JSON")
    ap.add_argument("--comparison", default="christian@growthbook.io",
                    help="owner_email to use as comparison (default: christian@growthbook.io)")
    ap.add_argument("--segment", default=None,
                    help="If set, use segment=<value> as comparison instead of a rep")
    ap.add_argument("--min-n", type=int, default=2)
    ap.add_argument("--max-depth", type=int, default=2)
    args = ap.parse_args()

    fx = _load_demo_fixture(args.fixture)
    rows = fx["qualified_closed"]
    team = rows

    if args.segment:
        comp = [r for r in rows if r["segment"] == args.segment]
        comp_label = f"segment={args.segment}"
    else:
        comp = [r for r in rows if r["owner_email"] == args.comparison]
        comp_label = args.comparison

    def depth(r):
        return "discovery_only" if r["deepest_qual_order"] == 1 else "past_discovery"

    def lost(r):
        return r["deal_status"] == "lost"

    result = rank_rate_dimensions(
        team, comp,
        dimensions=[depth, "segment", "ever_commit_ml"],
        outcome=lost,
        min_n=args.min_n,
        max_depth=args.max_depth,
    )

    print(f"\nComparison: team ({len(team)}) vs {comp_label} ({len(comp)})")
    print(result["summary"])
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
