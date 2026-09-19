#!/usr/bin/env python3
"""
Audit-only script: candidate-anchor-week stability check for the
point-in-time COMMIT+MOST_LIKELY calibration.

Prior audit (audit_pooled_commit_ml.py) confirmed pooling across the
4 complete quarters clears min_evidence_count=30, but only checked
the auto-selected anchor (week 1, chosen only because it's the
earliest week whose pooled cohort clears 30 - not necessarily the
most decision-relevant checkpoint). This script computes pooled n and
win_rate at EVERY week 1-13 (quarters are 13 weeks per
config/client.yaml's anchor_week comment: "pins to specific week
(1-13)"), pooled across the same 4 complete quarters, so a specific
anchor week can be picked on (a) n>=30, (b) decision-relevance, and
(c) week-to-week win-rate stability - not just "first week that
clears the gate."

Reuses _classify_deal_outcome, _quarter_window_iso, _get_complete_quarters,
_load_config from scripts/analytics/forecast_analyses.py UNMODIFIED.
Category-filter querying logic (COMMIT+MOST_LIKELY) is the same new
logic already added in audit_pooled_commit_ml.py, not duplicated
production code.

READ-ONLY throughout. No writes anywhere.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "analytics"))
sys.path.insert(0, str(REPO_ROOT / "api"))

from db import get_supabase
from forecast_analyses import (
    _classify_deal_outcome,
    _quarter_window_iso,
    _get_complete_quarters,
    _load_config,
)

CATEGORIES = ["COMMIT", "MOST_LIKELY"]
QUARTER_WEEKS = 13


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
    print(f"Category scope: {CATEGORIES}")
    print(f"Quarter length: {QUARTER_WEEKS} weeks\n")

    from supabase_client import select_all
    deals_rows = select_all(sb, "deals", columns="deal_id,stage,close_date,segment")
    deals_by_id = {str(d["deal_id"]): d for d in deals_rows}

    quarter_windows = {q: _quarter_window_iso(sb, q) for q in complete_quarters}

    print("=" * 100)
    print(f"{'week':>4s}  {'n':>4s}  {'won':>4s}  {'lost':>4s}  {'slip':>4s}  "
          f"{'win_rate':>9s}  {'delta_vs_prev':>14s}  {'gate':>6s}  by_quarter")
    print("=" * 100)

    results = {}
    prev_rate = None
    for week in range(1, QUARTER_WEEKS + 1):
        pooled = {"won": 0, "lost": 0, "slipped": 0, "unclassified": 0}
        by_quarter_n = {}
        for quarter in complete_quarters:
            deal_ids = cohort_at_week(sb, quarter, week)
            q_start_iso, q_end_iso = quarter_windows[quarter]
            c = classify_pool(deal_ids, q_start_iso, q_end_iso, deals_by_id)
            by_quarter_n[quarter] = len(deal_ids)
            for k in pooled:
                pooled[k] += c[k]

        n = pooled["won"] + pooled["lost"] + pooled["slipped"]
        gated = n >= min_evidence
        rate = (pooled["won"] / n) if gated and n else None
        results[week] = {"n": n, "rate": rate, **pooled, "by_quarter_n": by_quarter_n}

        rate_str = f"{rate:.1%}" if rate is not None else "null"
        if rate is not None and prev_rate is not None:
            delta_pp = (rate - prev_rate) * 100
            delta_str = f"{delta_pp:+.1f}pp"
        else:
            delta_str = "n/a"
        gate_str = "OK" if gated else "BELOW"

        print(f"{week:>4d}  {n:>4d}  {pooled['won']:>4d}  {pooled['lost']:>4d}  "
              f"{pooled['slipped']:>4d}  {rate_str:>9s}  {delta_str:>14s}  "
              f"{gate_str:>6s}  {by_quarter_n}")

        if rate is not None:
            prev_rate = rate

    print("\n" + "=" * 100)
    print("Candidate anchor weeks (1, 4, 7, 10, 13) - summary")
    print("=" * 100)
    for week in [1, 4, 7, 10, QUARTER_WEEKS]:
        r = results[week]
        rate_str = f"{r['rate']:.1%}" if r["rate"] is not None else "null"
        print(f"  week {week:>2d}: n={r['n']:>4d}  win_rate={rate_str}")

    print("\nDONE")


if __name__ == "__main__":
    main()
