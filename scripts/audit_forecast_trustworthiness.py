#!/usr/bin/env python3
"""
Audit-only script for the forecast-trustworthiness primitive scoping
(NORTH_STAR.md CRO Priority #1). No new primitive logic — this calls
the EXISTING, already-correctness-reviewed analyses in
scripts/analytics/forecast_analyses.py (query_commit_outcome_by_week,
query_commit_calibration) and reports their real output, plus:

1. A direct population check: is deals_snapshot.forecast_category
   actually populated for backfilled (historical) rows right now, or
   still null pending the reconstruction in
   scripts/analytics/reconstruct_forecast_category.py? This is the
   single most important check per the task — get it wrong and every
   number below is meaningless.
2. A live, concrete point-in-time-trap demonstration: for a sample of
   deals, compare their CURRENT deals.forecast_category against what
   deals_snapshot says they were tagged at various points in a closed
   quarter, to show empirically (not just theoretically) whether using
   the live field to judge a past quarter would be wrong.
3. A segment-level breakdown of commit calibration, reusing the exact
   same outcome-classification logic query_commit_calibration() uses
   (_classify_deal_outcome) — grouped by segment instead of by rep,
   since the existing function only slices by rep. Reports real sample
   sizes per segment; does not fabricate a rate below min_evidence.

READ-ONLY throughout. No writes anywhere.
"""
import os
import sys
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "analytics"))
sys.path.insert(0, str(REPO_ROOT / "api"))

from supabase_client import select_all
from db import get_supabase
from forecast_analyses import (
    query_commit_outcome_by_week,
    query_commit_calibration,
    _classify_deal_outcome,
    _quarter_window_iso,
    _get_complete_quarters,
    _load_config,
)


def part1_population_check(sb):
    print("=" * 80)
    print("PART 1: Is deals_snapshot.forecast_category actually populated for "
          "backfilled rows?")
    print("=" * 80)

    backfilled = select_all(sb, "deals_snapshot",
        columns="deal_id,snapshot_date,fiscal_quarter,week_of_quarter,"
                "snapshot_source,forecast_category",
        filters=[("eq", "snapshot_source", "backfilled")])
    prospective = select_all(sb, "deals_snapshot",
        columns="deal_id,forecast_category",
        filters=[("eq", "snapshot_source", "prospective")])

    print(f"Total backfilled (historical-reconstruction) rows: {len(backfilled)}")
    print(f"Total prospective (live-writer) rows: {len(prospective)}")

    backfilled_with_cat = [r for r in backfilled if r.get("forecast_category")]
    prospective_with_cat = [r for r in prospective if r.get("forecast_category")]

    b_pct = (len(backfilled_with_cat) / len(backfilled) * 100) if backfilled else 0
    p_pct = (len(prospective_with_cat) / len(prospective) * 100) if prospective else 0
    print(f"\nBackfilled rows with non-null forecast_category: "
          f"{len(backfilled_with_cat)}/{len(backfilled)} ({b_pct:.1f}%)")
    print(f"Prospective rows with non-null forecast_category: "
          f"{len(prospective_with_cat)}/{len(prospective)} ({p_pct:.1f}%)")

    if not backfilled:
        print("\n>>> No backfilled rows exist at all in deals_snapshot. "
              "Historical quarters are not reconstructable from this table yet.")
    elif not backfilled_with_cat:
        print("\n>>> CONFIRMED GAP: deals_snapshot has backfilled historical rows, "
              "but forecast_category is NULL on all of them. The reconstruction "
              "in scripts/analytics/reconstruct_forecast_category.py has NOT "
              "been executed yet (--execute has never run, or ran with zero "
              "resolvable rows). Every historical-quarter query below will "
              "return zero COMMIT deals until that reconstruction runs.")
    else:
        print(f"\n>>> Backfilled rows DO carry forecast_category ({b_pct:.1f}% "
              f"populated) — historical COMMIT cohorts should be queryable.")

    return {"backfilled_total": len(backfilled), "backfilled_with_cat": len(backfilled_with_cat)}


def part2_point_in_time_trap(sb):
    print("\n" + "=" * 80)
    print("PART 2: Live point-in-time-trap demonstration")
    print("=" * 80)
    print("For a sample of deals with backfilled snapshot history, compare the "
          "deal's CURRENT (live) forecast_category against what deals_snapshot "
          "says it was tagged at earlier points, to show concretely whether "
          "using the live field to judge a past quarter would be wrong.\n")

    backfilled = select_all(sb, "deals_snapshot",
        columns="deal_id,snapshot_date,fiscal_quarter,week_of_quarter,forecast_category",
        filters=[("eq", "snapshot_source", "backfilled"),
                 ("__not_null__", "forecast_category")])

    if not backfilled:
        print(">>> No backfilled rows with a populated forecast_category exist "
              "to demonstrate this against (consistent with Part 1's finding, "
              "if it found none). Cannot run a live demonstration until the "
              "reconstruction has executed — this is itself evidence for the "
              "same gap, not a separate one.")
        return

    by_deal = defaultdict(list)
    for r in backfilled:
        by_deal[r["deal_id"]].append(r)

    deal_ids = list(by_deal.keys())
    current = select_all(sb, "deals", columns="deal_id,forecast_category",
        filters=[("in_", "deal_id", deal_ids[:500])])
    current_by_id = {str(d["deal_id"]): d.get("forecast_category") for d in current}

    mismatches, matches, checked = 0, 0, 0
    examples = []
    for deal_id, rows in by_deal.items():
        cur_cat = current_by_id.get(str(deal_id))
        if cur_cat is None:
            continue
        for r in rows:
            checked += 1
            snap_cat = r.get("forecast_category")
            if snap_cat != cur_cat:
                mismatches += 1
                if len(examples) < 5:
                    examples.append((deal_id, r["fiscal_quarter"], r["week_of_quarter"],
                                     snap_cat, cur_cat))
            else:
                matches += 1

    print(f"Snapshot rows checked against the deal's CURRENT live value: {checked}")
    print(f"  Same as current: {matches}")
    print(f"  DIFFERENT from current: {mismatches} "
          f"({100*mismatches/checked:.1f}% of checked rows)" if checked else "")
    if examples:
        print("\nConcrete examples (deal_id, quarter, week, historical tag, "
              "CURRENT live tag):")
        for ex in examples:
            print(f"  {ex}")
        print("\n>>> CONFIRMED: using deals.forecast_category (the live field) "
              "to judge a past quarter would misclassify these deals — their "
              "COMMIT status has since changed. deals_snapshot (or the "
              "reconstruction) is the only point-in-time-correct source.")
    elif checked:
        print("\n>>> No mismatches found in this sample — forecast_category "
              "happened not to change for these deals since the snapshot. "
              "This does NOT mean the live field is safe to use for past "
              "quarters in general — only that this sample didn't catch a "
              "change. The structural risk (a deal's category can change "
              "after the quarter closes) is still real regardless.")


def part3_live_commit_calibration(sb):
    print("\n" + "=" * 80)
    print("PART 3: query_commit_outcome_by_week() and query_commit_calibration() "
          "— run live, unmodified, exactly as they exist today")
    print("=" * 80)

    complete_quarters = _get_complete_quarters(sb)
    print(f"Complete quarters (13 weeks of snapshot data) found: {complete_quarters}")

    obw = query_commit_outcome_by_week(sb)
    print("\n--- query_commit_outcome_by_week() ---")
    if "error" in obw:
        print(f"  {obw}")
    else:
        print(f"  quarters_analyzed: {obw['quarters_analyzed']}")
        print(f"  coverage_note: {obw['coverage_note']}")
        for wk in sorted(obw["by_week"]):
            s = obw["by_week"][wk]
            print(f"  week {wk:>2d}: n_committed={s['n_committed']:>4d} "
                  f"classified={s['classified']:>4d} won={s['won']:>3d} "
                  f"lost={s['lost']:>3d} slipped={s['slipped']:>3d} "
                  f"win_rate={s['win_rate']} reason={s['reason']}")

    calib = query_commit_calibration(sb)
    print("\n--- query_commit_calibration() ---")
    if "error" in calib:
        print(f"  {calib}")
    else:
        print(f"  anchor_week: {calib['anchor_week']}")
        print(f"  actual_hit_rate: {calib['actual_hit_rate']}")
        print(f"  claimed_hit_rate: {calib['claimed_hit_rate']}")
        print(f"  calibration_delta: {calib['calibration_delta']}")
        print(f"  pooled_below_gate: {calib['pooled_below_gate']}  "
              f"reason: {calib['pooled_reason']}")
        print(f"  breakdown: {calib['breakdown']}")
        print(f"  by_quarter: {calib['by_quarter']}")
        print(f"  by_rep ({len(calib['by_rep'])} reps): {calib['by_rep']}")
    return calib


def part4_segment_breakdown(sb, anchor_week):
    print("\n" + "=" * 80)
    print("PART 4: Segment-level commit calibration (NOT in the existing "
          "function — reuses its exact outcome-classification logic, grouped "
          "by segment instead of by rep, purely for this audit)")
    print("=" * 80)

    if anchor_week is None:
        print(">>> No anchor week available (query_commit_calibration errored "
              "above) — cannot compute a segment breakdown either. Same root "
              "cause as Part 3's error.")
        return

    config = _load_config()
    min_evidence = config.get("min_evidence_count", 30)
    complete_quarters = _get_complete_quarters(sb)

    deals_rows = select_all(sb, "deals",
        columns="deal_id,stage,close_date,segment")
    deals_by_id = {str(d["deal_id"]): d for d in deals_rows}

    by_segment = defaultdict(lambda: {"won": 0, "slipped": 0, "lost": 0})

    for quarter in complete_quarters:
        anchor_result = sb.table("deals_snapshot").select("deal_id").eq(
            "fiscal_quarter", quarter).eq(
            "week_of_quarter", anchor_week).eq(
            "forecast_category", "COMMIT").execute()
        deal_ids = [r["deal_id"] for r in anchor_result.data]
        if not deal_ids:
            continue
        q_start_iso, q_end_iso = _quarter_window_iso(sb, quarter)
        for deal_id in deal_ids:
            outcome = _classify_deal_outcome(deal_id, q_start_iso, q_end_iso, deals_by_id)
            segment = (deals_by_id.get(str(deal_id)) or {}).get("segment") or "Unknown"
            if outcome == "WON":
                by_segment[segment]["won"] += 1
            elif outcome == "SLIPPED":
                by_segment[segment]["slipped"] += 1
            elif outcome == "LOST":
                by_segment[segment]["lost"] += 1

    if not by_segment:
        print(">>> No COMMIT deals found at the anchor week across any complete "
              "quarter — same root cause as Part 1/3's gap. No segment "
              "breakdown possible.")
        return

    for segment, c in sorted(by_segment.items()):
        n = c["won"] + c["slipped"] + c["lost"]
        gated = n >= min_evidence
        rate = (c["won"] / n) if gated and n else None
        print(f"  {segment:15s} n={n:>4d}  won={c['won']:>3d} "
              f"slipped={c['slipped']:>3d} lost={c['lost']:>3d}  "
              f"hit_rate={rate if gated else f'null (n={n} < min_evidence={min_evidence})'}")


def main():
    sb = get_supabase()
    part1_population_check(sb)
    part2_point_in_time_trap(sb)
    calib = part3_live_commit_calibration(sb)
    anchor_week = calib.get("anchor_week") if isinstance(calib, dict) else None
    part4_segment_breakdown(sb, anchor_week)
    print("\n" + "=" * 80)
    print("DONE")
    print("=" * 80)


if __name__ == "__main__":
    main()
