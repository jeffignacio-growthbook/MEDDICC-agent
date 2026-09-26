#!/usr/bin/env python3
"""
Path-to-target: time-feasibility gate + allocated dual-lever gap plan.

Standalone and read-only, like the other analytics primitives
(metric_reconciliation, rate_mix_decomposition, sensitivity_analysis,
stage_call_lag): no handler, no writes, nothing reaches Slack.

The gap to a period target can be closed with two levers:

  1. EXISTING pipeline — always available. Its realistic contribution is the
     deal-level scenario planning (Conservative / Likely / Stretch expected
     close, with named deals and per-deal fixes) that a caller supplies. This
     module consumes those three totals; it does not re-derive them.

  2. NET-NEW pipeline — only useful if a deal created now can actually close
     before period end. That is a TIME-FEASIBILITY question: what fraction of a
     newly-created deal's value could realistically land in the days remaining.
     time_feasibility() answers it from the real historical won-deal cycle
     distribution (create -> close), the same historical source family as
     pipeline_coverage's stage win-rate table.

The gap (bare and 1.5x-padded) is split accordingly: existing pipeline covers
what its scenarios can; the remainder is net-new, sized DOWN by the time-
feasible fraction. Whatever net-new cannot land in time is reframed as
targeting the NEXT period, not this one — and when the feasible fraction is near
zero, net-new is called out as not a viable lever this period at all.

    python scripts/analytics/path_to_target.py            # live (needs Supabase env)
"""
import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List

NEAR_ZERO_DEFAULT = 0.15
PAD_MULTIPLIER_DEFAULT = 1.5


def time_feasibility(days_remaining: int, won_cycle_days: List[int], *,
                     near_zero_threshold: float = NEAR_ZERO_DEFAULT) -> Dict[str, Any]:
    """The time-feasible fraction for net-new pipeline: the share of historical
    won deals whose cycle (create->close, in days) fits inside `days_remaining`.

    won_cycle_days: historical won-deal cycle lengths. Negative/None dropped as
        bad data. feasible_fraction is None (not 0) when there is no history, so
        "unknown" never masquerades as "impossible".
    """
    valid = [int(c) for c in won_cycle_days if c is not None and c >= 0]
    n = len(valid)
    frac = (sum(1 for c in valid if c <= days_remaining) / n) if n else None
    return {
        "days_remaining": days_remaining,
        "feasible_fraction": frac,
        "n_cycles": n,
        "avg_cycle_days": round(statistics.mean(valid), 1) if n else None,
        "median_cycle_days": statistics.median(valid) if n else None,
        "near_zero_threshold": near_zero_threshold,
        "net_new_viable": bool(frac is not None and frac >= near_zero_threshold),
    }


def path_to_target(gap_bare: float, existing_scenarios: Dict[str, float],
                   feasibility: Dict[str, Any], *,
                   pad_multiplier: float = PAD_MULTIPLIER_DEFAULT) -> Dict[str, Any]:
    """Allocate the gap across the existing-pipeline lever and the net-new lever.

    gap_bare: the bare gap to target. Also planned at gap_bare * pad_multiplier.
    existing_scenarios: {"conservative", "likely", "stretch"} — expected close
        from EXISTING pipeline (the deal-level scenario planning).
    feasibility: a time_feasibility() result (its feasible_fraction sizes net-new).
    """
    for k in ("conservative", "likely", "stretch"):
        if k not in existing_scenarios:
            raise ValueError(f"existing_scenarios missing '{k}'")
    likely = float(existing_scenarios["likely"])
    conservative = float(existing_scenarios["conservative"])
    stretch = float(existing_scenarios["stretch"])
    frac = feasibility.get("feasible_fraction") or 0.0
    viable = bool(feasibility.get("net_new_viable"))

    def allocate(gap: float) -> Dict[str, Any]:
        net_new_needed = max(0.0, gap - likely)          # never negative
        feasible_now = net_new_needed * frac
        return {
            "gap": gap,
            "existing_likely_covers": min(likely, gap),
            "net_new_needed": net_new_needed,
            "net_new_feasible_this_period": feasible_now,
            "net_new_next_period": net_new_needed - feasible_now,
            "covered_by_conservative": conservative >= gap,
            "covered_by_likely": likely >= gap,
            "covered_by_stretch": stretch >= gap,
        }

    gap_padded = gap_bare * pad_multiplier
    bare_plan = allocate(gap_bare)
    padded_plan = allocate(gap_padded)

    # Narrative — honest about which lever does the work and whether net-new can
    # even land in time.
    if bare_plan["net_new_needed"] == 0.0:
        lead = ("Existing pipeline covers the bare gap at the Likely scenario"
                + (" (and even Conservative)" if bare_plan["covered_by_conservative"] else "")
                + " — net-new is upside, not required this period.")
    elif not viable:
        lead = (f"Net-new is not a viable lever this period: only "
                f"{frac:.0%} of a newly-created deal could close in the "
                f"{feasibility.get('days_remaining')} days left. Work the "
                f"existing pipeline; reframe net-new (${bare_plan['net_new_next_period']:,.0f}) "
                f"as targeting NEXT period.")
    else:
        lead = (f"Existing pipeline (Likely ${likely:,.0f}) leaves "
                f"${bare_plan['net_new_needed']:,.0f} of net-new; only "
                f"~{frac:.0%} (${bare_plan['net_new_feasible_this_period']:,.0f}) "
                f"can realistically land in the {feasibility.get('days_remaining')} "
                f"days left — the rest (${bare_plan['net_new_next_period']:,.0f}) "
                f"targets NEXT period.")

    return {
        "gap_bare": float(gap_bare),
        "gap_padded": float(gap_padded),
        "pad_multiplier": pad_multiplier,
        "existing_scenarios": {"conservative": conservative, "likely": likely,
                               "stretch": stretch},
        "feasibility": feasibility,
        "net_new_viable": viable,
        "bare_plan": bare_plan,
        "padded_plan": padded_plan,
        "headline": lead,
        "note": ("Existing-pipeline scenarios (Conservative/Likely/Stretch) are the "
                 "deal-level plan's expected close, supplied by the coverage/attainment "
                 "primitives; net-new is sized only to the time-feasible fraction from "
                 "the real won-deal cycle distribution. Read-only — a plan, not an action."),
    }


def report(r: Dict[str, Any]) -> str:
    out = ["Path to target — time-feasibility gate + dual-lever gap plan (read-only).", ""]
    s = r["existing_scenarios"]
    f = r["feasibility"]
    out.append(f"Gap: ${r['gap_bare']:,.0f} bare | ${r['gap_padded']:,.0f} at "
               f"{r['pad_multiplier']}x pad")
    out.append(f"Existing pipeline expected close — Conservative ${s['conservative']:,.0f} | "
               f"Likely ${s['likely']:,.0f} | Stretch ${s['stretch']:,.0f}")
    if f.get("feasible_fraction") is None:
        out.append("Time feasibility: unknown (no cycle history).")
    else:
        out.append(f"Time feasibility: {f['feasible_fraction']:.0%} of a new deal could "
                   f"close in {f['days_remaining']}d (avg cycle {f['avg_cycle_days']}d, "
                   f"median {f['median_cycle_days']}d, n={f['n_cycles']}).")
    out.append("")
    for label, p in (("BARE", r["bare_plan"]), (f"PADDED {r['pad_multiplier']}x", r["padded_plan"])):
        out.append(f"  {label} gap ${p['gap']:,.0f}:")
        out.append(f"    existing pipeline (Likely) covers ${p['existing_likely_covers']:,.0f} "
                   f"[Conservative covers: {p['covered_by_conservative']}]")
        out.append(f"    net-new needed ${p['net_new_needed']:,.0f} -> "
                   f"${p['net_new_feasible_this_period']:,.0f} feasible this period, "
                   f"${p['net_new_next_period']:,.0f} -> next period")
    out.append("")
    out.append(r["headline"])
    return "\n".join(out)


def main():  # pragma: no cover - live wiring
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True,
                    help='JSON: {gap_bare, days_remaining, won_cycle_days:[...], '
                         'existing_scenarios:{conservative,likely,stretch}, pad_multiplier?}')
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    data = json.loads(Path(args.input).read_text())
    feas = time_feasibility(data["days_remaining"], data["won_cycle_days"])
    r = path_to_target(data["gap_bare"], data["existing_scenarios"], feas,
                       pad_multiplier=data.get("pad_multiplier", PAD_MULTIPLIER_DEFAULT))
    print(report(r))
    if args.json:
        print("\nJSON " + json.dumps(r, default=str))


if __name__ == "__main__":
    main()
