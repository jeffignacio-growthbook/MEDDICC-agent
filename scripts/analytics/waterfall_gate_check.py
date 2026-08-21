#!/usr/bin/env python3
"""
Read-only diagnostic for defect 5 (compute_waterfall.py qualified-pipeline gate).

Proves, with real numbers and WITHOUT writing anything, that gating a
historical week's qualified pipeline on the current-state
highest_stage_order_reached (OLD) counts deals that had not yet qualified as of
that week, and that the point-in-time qualified_date gate (NEW) removes exactly
those deals. Reports, per backfilled snapshot date:

    OLD  = active deals with highest_stage_order_reached >= threshold
    NEW  = active deals with qualified_date <= snapshot_date (point-in-time)
    leak = OLD-only (counted too early — not yet qualified as of the date)
    gain = NEW-only (should be ~0; would signal a data-quality gap where a
           deal qualified but carries no/late qualified_date)

Never upserts. Safe to run against production.
"""
import os
import sys
from pathlib import Path
from collections import defaultdict
from datetime import date

sys.path.insert(0, str(Path(__file__).parent.parent))

from supabase import create_client
from supabase_client import select_all
from utils import load_client_config
from compute_waterfall import _qualified_as_of


def main():
    sb = create_client(os.environ['SUPABASE_URL'],
                       os.environ['SUPABASE_SERVICE_KEY'])
    config = load_client_config()
    threshold = (config.get('pipelines', {}).get('default', {})
                 .get('qualified_stage_order', 2))

    qual_rows = select_all(
        sb, 'deals',
        columns='deal_id, highest_stage_order_reached, qualified_date')
    qual_map = {r['deal_id']: r for r in qual_rows}

    # Pure-backfill snapshot dates only (same selection compute_waterfall uses).
    snaps = select_all(sb, 'deals_snapshot',
                       columns='snapshot_date,snapshot_source')
    src_by_date = defaultdict(set)
    for r in snaps:
        src_by_date[r['snapshot_date']].add(r['snapshot_source'])
    dates = sorted(d for d, s in src_by_date.items() if s == {'backfilled'})

    print("=" * 72)
    print("DEFECT 5 — waterfall qualified-pipeline gate (read-only diagnostic)")
    print("=" * 72)
    print(f"threshold (config qualified_stage_order): {threshold}")
    print(f"backfilled snapshot dates: {len(dates)}")
    if not dates:
        print("No pure-backfill snapshot dates — nothing to compare.")
        return

    # Compare across the most recent 8 dates (enough to show the pattern).
    for d in dates[-8:]:
        rows = select_all(sb, 'deals_snapshot',
                          columns='deal_id,deal_status',
                          filters=[('eq', 'snapshot_date', d)])
        active = [r['deal_id'] for r in rows
                  if r.get('deal_status') == 'active']

        old = {did for did in active
               if (qual_map.get(did, {}).get('highest_stage_order_reached') or 0)
               >= threshold}
        new = {did for did in active
               if _qualified_as_of(qual_map, did, d)}
        leak = old - new
        gain = new - old
        print(f"\n{d}: active={len(active)}  OLD={len(old)}  NEW={len(new)}  "
              f"leak(OLD-only)={len(leak)}  gain(NEW-only)={len(gain)}")
        if gain:
            # A NEW-only deal qualified (per point-in-time) but the high-water
            # mark did NOT clear the threshold — a data gap worth surfacing.
            print(f"    NEW-only (qualified_date set, high-water < threshold): "
                  f"{sorted(gain)[:5]}{' ...' if len(gain) > 5 else ''}")

    print("\nInterpretation: leak>0 means the OLD gate counted deals that had "
          "not yet qualified as of that week. The NEW point-in-time gate "
          "excludes them; they re-enter via newly_qualified in the week their "
          "qualified_date falls. gain should be ~0.")


if __name__ == '__main__':
    main()
