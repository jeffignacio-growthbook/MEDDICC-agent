#!/usr/bin/env python3
"""
Audit-only script: pooled COMMIT+MOST_LIKELY sample-size check for the
forecast-trustworthiness primitive.

Decision from Jeff: scope = COMMIT+MOST_LIKELY, not COMMIT-only. The
reconstruct-forecast-category.yml dry-run already showed every single
quarter falls below min_evidence_count=30 under EITHER definition, so
per-quarter breakdowns are ruled out regardless. This checks whether
POOLING across all complete (closed) quarters clears the floor under
the broader COMMIT+MOST_LIKELY definition.

Reuses _classify_deal_outcome, _quarter_window_iso, _get_complete_quarters,
_load_config from scripts/analytics/forecast_analyses.py UNMODIFIED.
The only new logic here is querying deals_snapshot with
forecast_category IN ('COMMIT', 'MOST_LIKELY') instead of the existing
functions' hardcoded COMMIT-only filter — those existing functions are
not touched.

Reports TWO cohort definitions, since they answer different questions
and both were relevant across the two audit rounds:

  A. "Ever COMMIT+MOST_LIKELY during the quarter" - distinct
     (deal_id, quarter) pairs where the deal carried either tag at ANY
     point across the quarter's 13 weeks, deduplicated per deal per
     quarter. Matches audit task 1's original literal phrasing
     ("marked forecast_category='COMMIT' at some point during that
     quarter").

  B. "Fixed anchor-week, pooled across quarters" - same selection
     method query_commit_calibration() already uses for COMMIT-only:
     scan weeks 1-13, pick the earliest week whose POOLED (summed
     across all complete quarters) cohort at that exact week clears
     min_evidence_count, then classify outcomes for that week's cohort
     in every quarter. This is the apples-to-apples comparison against
     the already-reported COMMIT-only n=30 / 56.7% figure.

READ-ONLY throughout. No writes anywhere.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "analytics"))
sys.path.insert(0, str(REPO_ROOT / "api"))

from supabase_client import select_all
from db import get_supabase
from forecast_analyses import (
    _classify_deal_outcome,
    _quarter_window_iso,
    _get_complete_quarters,
    _load_config,
)

CATEGORIES = ["COMMIT", "MOST_LIKELY"]


def cohort_ever_in_quarter(sb, quarter):
    rows = select_all(sb, "deals_snapshot",
        columns="deal_id,week_of_quarter,forecast_category",
        filters=[("eq", "fiscal_quarter", quarter),
                 ("eq", "snapshot_source", "backfilled"),
                 ("in_", "forecast_category", CATEGORIES)])
    return sorted({r["deal_id"] for r in rows})


def cohort_at_week(sb, quarter, week):
    result = sb.table("deals_snapshot").select("deal_id").eq(
        "fiscal_quarter", quarter).eq(
        "week_of_quarter", week).eq(
        "snapshot_source", "backfilled").in_(
        "forecast_category", CATEGORIES).execute()
    return [r["deal_id"] for r in result.data]


def classify_pool(deal_ids, q_start_iso, q_end_iso, deals_by_id):
    counts = {"won": 0, "lost": 0, "slipped": 0, "unclassified": 0}
    for deal_id in deal_ids:
        outcome = _classify_deal_outcome(deal_id, q_start_iso, q_end_iso, deals_by_id)
        if outcome == "WON":
            counts["won"] += 1
        elif outcome == "LOST":
            counts["lost"] += 1
        elif outcome == "SLIPPED":
            counts["slipped"] += 1
        else:
            counts["unclassified"] += 1
    return counts


def main():
    sb = get_supabase()
    config = _load_config()
    min_evidence = config.get("min_evidence_count", 30)
    complete_quarters = _get_complete_quarters(sb)

    print(f"Complete (closed) quarters used for pooling: {complete_quarters}")
    print(f"min_evidence_count: {min_evidence}")
    print(f"Category scope: {CATEGORIES}\n")

    deals_rows = select_all(sb, "deals", columns="deal_id,stage,close_date,segment")
    deals_by_id = {str(d["deal_id"]): d for d in deals_rows}

    print("=" * 80)
    print("COHORT A: ever tagged COMMIT or MOST_LIKELY at ANY week during the quarter"
          " (dedup per deal per quarter)")
    print("=" * 80)
    pooled_a = {"won": 0, "lost": 0, "slipped": 0, "unclassified": 0}
    for quarter in complete_quarters:
        deal_ids = cohort_ever_in_quarter(sb, quarter)
        q_start_iso, q_end_iso = _quarter_window_iso(sb, quarter)
        c = classify_pool(deal_ids, q_start_iso, q_end_iso, deals_by_id)
        n = c["won"] + c["lost"] + c["slipped"]
        print(f"  {quarter}: distinct deals={len(deal_ids):>4d}  classified={n:>4d}  "
              f"won={c['won']:>3d} lost={c['lost']:>3d} slipped={c['slipped']:>3d} "
              f"unclassified={c['unclassified']:>3d}")
        for k in pooled_a:
            pooled_a[k] += c[k]

    n_a = pooled_a["won"] + pooled_a["lost"] + pooled_a["slipped"]
    print(f"\n  POOLED across {len(complete_quarters)} quarters: n={n_a}  "
          f"won={pooled_a['won']} lost={pooled_a['lost']} slipped={pooled_a['slipped']}")
    if n_a >= min_evidence:
        rate = pooled_a["won"] / n_a
        print(f"  >>> CLEARS gate (n={n_a} >= {min_evidence}). win_rate = {rate:.1%}")
    else:
        print(f"  >>> BELOW gate (n={n_a} < {min_evidence}). No rate reported.")

    print("\n" + "=" * 80)
    print("COHORT B: fixed anchor-week (earliest week whose POOLED cross-quarter "
          "cohort clears the gate), same selection method query_commit_calibration() "
          "already uses for COMMIT-only")
    print("=" * 80)

    anchor_week, per_week_totals = None, {}
    for week in range(1, 14):
        counts_by_quarter = {q: len(cohort_at_week(sb, q, week)) for q in complete_quarters}
        total = sum(counts_by_quarter.values())
        per_week_totals[week] = (total, counts_by_quarter)
        if anchor_week is None and total >= min_evidence:
            anchor_week = week

    for week in sorted(per_week_totals):
        total, by_q = per_week_totals[week]
        marker = "  <== anchor" if week == anchor_week else ""
        print(f"  week {week:>2d}: pooled_total={total:>4d}  by_quarter={by_q}{marker}")

    if anchor_week is None:
        print(f"\n  >>> No week's pooled cohort ever clears min_evidence_count="
              f"{min_evidence}. Cohort B cannot report a rate at any anchor week.")
    else:
        pooled_b = {"won": 0, "lost": 0, "slipped": 0, "unclassified": 0}
        for quarter in complete_quarters:
            deal_ids = cohort_at_week(sb, quarter, anchor_week)
            q_start_iso, q_end_iso = _quarter_window_iso(sb, quarter)
            c = classify_pool(deal_ids, q_start_iso, q_end_iso, deals_by_id)
            n = c["won"] + c["lost"] + c["slipped"]
            print(f"  {quarter} @ week {anchor_week}: distinct deals={len(deal_ids):>4d}  "
                  f"classified={n:>4d}  won={c['won']:>3d} lost={c['lost']:>3d} "
                  f"slipped={c['slipped']:>3d} unclassified={c['unclassified']:>3d}")
            for k in pooled_b:
                pooled_b[k] += c[k]

        n_b = pooled_b["won"] + pooled_b["lost"] + pooled_b["slipped"]
        print(f"\n  POOLED @ anchor week {anchor_week} across {len(complete_quarters)} "
              f"quarters: n={n_b}  won={pooled_b['won']} lost={pooled_b['lost']} "
              f"slipped={pooled_b['slipped']}")
        if n_b >= min_evidence:
            rate = pooled_b["won"] / n_b
            print(f"  >>> CLEARS gate (n={n_b} >= {min_evidence}). win_rate = {rate:.1%}")
        else:
            print(f"  >>> BELOW gate (n={n_b} < {min_evidence}). No rate reported.")

    print("\nDONE")


if __name__ == "__main__":
    main()
