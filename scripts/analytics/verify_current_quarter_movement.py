#!/usr/bin/env python3
"""
Verify the zero-exits observation in the current-quarter grid.

Hypothesis (from reading backfill_current_quarter.py): that series stamps each
deal's CURRENT stage onto every week rather than reconstructing stage
point-in-time, so a deal's stage is identical across consecutive weeks by
construction and stage exits are structurally zero. The Method 2 `backfilled`
quarters DO reconstruct point-in-time, so they should show real transitions.

This script proves it empirically against the real deals_snapshot:
  * FY2027 Q3 (backfill_current_quarter): count deals present in two
    consecutive weeks whose stage_id DIFFERS. Expect ~0 (structural).
  * FY2027 Q2 (backfilled): same computation. Expect > 0 (real movement) —
    confirms the method detects transitions when they exist, so a zero in Q3
    is about the data source, not the measurement.

Runs in CI (needs SUPABASE_URL / SUPABASE_SERVICE_KEY).
"""

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
for p in ("scripts", "scripts/analytics", "."):
    sys.path.insert(0, str(REPO / p))


def _sb():
    from supabase import create_client
    return create_client(os.environ["SUPABASE_URL"],
                         os.environ["SUPABASE_SERVICE_KEY"])


def _load(sb, fiscal_quarter, source):
    from supabase_client import select_all
    rows = select_all(
        sb, "deals_snapshot",
        columns="deal_id,snapshot_date,stage_id,snapshot_source",
        filters=[("eq", "fiscal_quarter", fiscal_quarter),
                 ("eq", "snapshot_source", source)],
    )
    by_date = {}
    for r in rows:
        by_date.setdefault(r["snapshot_date"], {})[r["deal_id"]] = r.get("stage_id")
    return by_date


def _analyze(label, by_date):
    print("\n" + "=" * 72)
    print(label)
    print("=" * 72)
    dates = sorted(by_date)
    if len(dates) < 2:
        print(f"  only {len(dates)} snapshot date(s) — cannot compare pairs")
        return None
    print(f"  snapshot dates: {dates}")
    total_changed = 0
    total_pairs_common = 0
    for prev, cur in zip(dates, dates[1:]):
        p, c = by_date[prev], by_date[cur]
        common = set(p) & set(c)
        changed = [d for d in common if p[d] != c[d]]
        entered = set(c) - set(p)
        left = set(p) - set(c)
        total_changed += len(changed)
        total_pairs_common += len(common)
        print(f"  {prev} → {cur}: {len(common)} in both | "
              f"stage CHANGED: {len(changed)} | entered: {len(entered)} | "
              f"left: {len(left)}")
    print(f"  --> total stage transitions across all consecutive weeks: "
          f"{total_changed} (out of {total_pairs_common} deal-week overlaps)")
    return total_changed


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect-retired", action="store_true",
                    help="Post-retirement assertion: FY2027 Q3 'backfilled' "
                         "transitions must be > 0 and the stopgap source gone. "
                         "Exit non-zero if not — so the caveat is only removed "
                         "once the loop is genuinely closed.")
    args = ap.parse_args()
    sb = _sb()

    stopgap = _load(sb, "FY2027 Q3", "backfill_current_quarter")
    stopgap_rows = sum(len(v) for v in stopgap.values())
    stopgap_tx = _analyze(
        "FY2027 Q3 — backfill_current_quarter (stopgap; structural 0 by "
        f"construction) — rows now: {stopgap_rows}",
        stopgap) if stopgap else None

    q3b = _analyze(
        "FY2027 Q3 — backfilled (point-in-time reconstruction; expect "
        "real transitions after retirement)",
        _load(sb, "FY2027 Q3", "backfilled"))
    q2 = _analyze(
        "FY2027 Q2 — backfilled (baseline; known real transitions)",
        _load(sb, "FY2027 Q2", "backfilled"))

    print("\n" + "=" * 72)
    print("VERDICT")
    print("=" * 72)
    print(f"  FY2027 Q3 stopgap rows remaining: {stopgap_rows}")
    print(f"  FY2027 Q3 backfilled transitions: {q3b}")
    print(f"  FY2027 Q2 backfilled transitions: {q2} (baseline)")

    if args.expect_retired:
        if stopgap_rows == 0 and q3b and q3b > 0:
            print("\n  LOOP CLOSED: the stopgap is gone and the reconstructed "
                  f"FY2027 Q3 now shows {q3b} real stage transitions where the "
                  "copied-stage series showed 0/696. Same quarter, same handler, "
                  "correct data, real movement. The caveat can be removed.")
            return 0
        print("\n  ✗ NOT yet closed: caveat must stay. "
              f"(stopgap_rows={stopgap_rows}, q3_backfilled_transitions={q3b})")
        return 1

    print("\nDONE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
