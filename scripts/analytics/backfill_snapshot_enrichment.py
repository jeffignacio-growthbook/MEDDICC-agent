#!/usr/bin/env python3
"""
Backfill region and segment for historical deals_snapshot records.

Since property_history doesn't track region/segment changes, this backfill
uses CURRENT values from the deals table. This is imperfect (deals may have
changed region/segment over time), but it's the best available data.

Going forward, snapshot_deals.py captures point-in-time values, so future
snapshots will have accurate enrichment.

Usage: python scripts/analytics/backfill_snapshot_enrichment.py
"""

import os
from pathlib import Path
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parent.parent.parent

def main():
    load_dotenv()

    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return

    from supabase import create_client
    import sys
    sys.path.insert(0, str(REPO_ROOT / 'scripts'))
    from supabase_client import select_all

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("Backfilling region and segment for historical snapshots...")
    print("Note: Using current region/segment from deals table (best available data)")

    # Get current region/segment for all deals
    print("\nLoading current region/segment from deals table...")
    deals = select_all(sb, 'deals', 'deal_id, region, segment')
    enrichment = {d['deal_id']: (d.get('region'), d.get('segment')) for d in deals}
    print(f"✓ Loaded enrichment for {len(enrichment):,} deals")

    # Get all snapshots that need backfill
    print("\nLoading snapshots needing backfill...")
    result = sb.table('deals_snapshot')\
        .select('deal_id, snapshot_date')\
        .is_('region', 'null')\
        .execute()

    snapshots_to_update = result.data
    print(f"✓ Found {len(snapshots_to_update):,} snapshots needing backfill")

    if not snapshots_to_update:
        print("\n✓ No snapshots need backfill - all done!")
        return

    # Build update batches
    updates = []
    missing_enrichment = 0

    for snap in snapshots_to_update:
        deal_id = snap['deal_id']
        snapshot_date = snap['snapshot_date']

        if deal_id not in enrichment:
            missing_enrichment += 1
            # Deal doesn't exist in current deals table - skip
            continue

        region, segment = enrichment[deal_id]
        updates.append({
            'deal_id': deal_id,
            'snapshot_date': snapshot_date,
            'region': region,
            'segment': segment
        })

    if missing_enrichment > 0:
        print(f"\n⚠️  {missing_enrichment:,} snapshots have no current deal record (likely closed deals)")
        print(f"   These will keep NULL region/segment (acceptable for historical closed deals)")

    print(f"\nBackfilling {len(updates):,} snapshots...")

    # Batch update
    batch_size = 500
    updated = 0

    for i in range(0, len(updates), batch_size):
        batch = updates[i:i + batch_size]
        sb.table('deals_snapshot').upsert(
            batch,
            on_conflict='deal_id,snapshot_date'
        ).execute()
        updated += len(batch)

        if updated % 5000 == 0 or updated == len(updates):
            print(f"  Progress: {updated:,} / {len(updates):,} ({updated/len(updates)*100:.1f}%)")

    print(f"\n✓ Backfill complete: {updated:,} snapshots updated")

    # Verify
    print("\nVerifying backfill...")
    result = sb.table('deals_snapshot')\
        .select('deal_id', count='exact')\
        .is_('region', 'null')\
        .execute()

    remaining_nulls = result.count
    print(f"  Remaining NULL regions: {remaining_nulls:,}")

    if remaining_nulls > 0:
        print(f"  (Expected: snapshots for deals no longer in deals table)")
    else:
        print(f"  ✓ All snapshots have region/segment enrichment")


if __name__ == '__main__':
    main()
