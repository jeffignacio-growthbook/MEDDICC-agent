#!/usr/bin/env python3
"""
Maintainer/backfill for deals.qualified_date from deals_snapshot crossings.

WHY THIS EXISTS (high-severity fix, 2026-09-26): deals.qualified_date is the
event column the waterfall keys "new pipeline generated" on. It was seeded once
from HubSpot dealstage history and then NOTHING kept it current — the daily
analytics ETL (etl_deals.py --mode analytics) never writes it. It froze at
2026-08-07, so every qualification crossing since read as $0 new pipeline (58
deals / ~$5.74M silently dropped, producing a false "review SDR metrics"
recommendation).

This is the durable maintainer: idempotently fill qualified_date for any deal
that HAS a real qualification crossing in deals_snapshot (first snapshot at
stage_order >= threshold) but a NULL qualified_date. It FILLS NULLS ONLY — it
never overwrites an existing value, because the original seed used HubSpot
dealstage history (finer-grained than weekly snapshots) and is authoritative
where present. Wired into daily-analytics-etl.yml so the column can't refreeze;
the pipeline_generation_freshness guard is the safety net if it ever does.

Crossing derivation is the unit-tested crossings_from_snapshots() shared with
the freshness guard — one source of truth.
"""
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))

from pipeline_generation_freshness import crossings_from_snapshots


def rows_needing_qualified_date(deal_rows: List[dict],
                                snapshot_rows: List[dict], *,
                                threshold: int = 1) -> List[Tuple[str, str]]:
    """[(deal_id, crossing_date)] for deals with a real crossing but a NULL
    qualified_date. Fills nulls only — never overwrites an existing value."""
    crossings = crossings_from_snapshots(snapshot_rows, threshold=threshold)
    current = {str(d.get("deal_id")): d.get("qualified_date") for d in deal_rows}
    out: List[Tuple[str, str]] = []
    for did, cdate in crossings.items():
        if not current.get(did):  # None or empty → fill
            out.append((did, cdate))
    return out


def main():  # pragma: no cover - live wiring, exercised via the daily ETL / MCP
    import os
    from supabase_client import SupabaseWriter, select_all
    sb = SupabaseWriter().client

    pipeline = "default"
    deals = select_all(sb, "deals", columns="deal_id,qualified_date",
                       filters=[("eq", "pipeline_id", pipeline)])
    snaps = []
    ids = [str(d["deal_id"]) for d in deals]
    for i in range(0, len(ids), 100):
        snaps.extend(select_all(sb, "deals_snapshot",
            columns="deal_id,snapshot_date,stage_order,pipeline_id",
            filters=[("eq", "pipeline_id", pipeline),
                     ("in_", "deal_id", ids[i:i + 100])]))

    updates = rows_needing_qualified_date(deals, snaps)
    for did, cdate in updates:
        sb.table("deals").update({"qualified_date": cdate}).eq("deal_id", did).execute()
    print(f"qualified_date maintainer: filled {len(updates)} null rows from "
          f"deals_snapshot crossings (never overwrites existing values).")


if __name__ == "__main__":
    main()
