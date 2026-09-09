#!/usr/bin/env python3
"""
Force backfill ALL snapshots with current region/segment from deals table,
regardless of current enrichment values.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parent

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

    print("Force backfilling ALL snapshots with current region/segment...")
    print("This will overwrite existing enrichment values")

    # Get current region/segment for all deals
    print("\nLoading current region/segment from deals table...")
    deals = select_all(sb, 'deals', 'deal_id, region, segment')
    enrichment = {d['deal_id']: (d.get('region') or 'UNKNOWN', d.get('segment') or 'Unknown') for d in deals}
    print(f"✓ Loaded enrichment for {len(enrichment):,} deals")

    # Get ALL snapshots
    print("\nLoading ALL snapshots...")
    snapshots = select_all(sb, 'deals_snapshot', 'deal_id, snapshot_date')
    print(f"✓ Found {len(snapshots):,} total snapshots")

    # Build update batches
    updates = []
    missing_enrichment = 0

    for snap in snapshots:
        deal_id = snap['deal_id']
        snapshot_date = snap['snapshot_date']

        if deal_id not in enrichment:
            missing_enrichment += 1
            # Deal doesn't exist in current deals table - set to UNKNOWN
            updates.append({
                'deal_id': deal_id,
                'snapshot_date': snapshot_date,
                'region': 'UNKNOWN',
                'segment': 'Unknown'
            })
            continue

        region, segment = enrichment[deal_id]
        updates.append({
            'deal_id': deal_id,
            'snapshot_date': snapshot_date,
            'region': region,
            'segment': segment
        })

    if missing_enrichment > 0:
        print(f"\n⚠️  {missing_enrichment:,} snapshots have no current deal record")
        print(f"   Setting these to UNKNOWN/Unknown")

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

    # Verify enrichment distribution
    print("\nVerifying enrichment distribution...")
    result = sb.table('deals_snapshot')\
        .select('region, segment')\
        .limit(1000)\
        .execute()

    from collections import Counter
    regions = Counter(r.get('region') or 'NULL' for r in result.data)
    segments = Counter(r.get('segment') or 'Unknown' for r in result.data)

    print(f"  Sample of 1000 snapshots:")
    print(f"    Regions: {dict(regions)}")
    print(f"    Segments: {dict(segments)}")

    unknown_region = regions.get('UNKNOWN', 0) + regions.get('NULL', 0)
    unknown_segment = segments.get('Unknown', 0) + segments.get('NULL', 0)
    pct_enriched_region = (len(result.data) - unknown_region) / len(result.data) * 100
    pct_enriched_segment = (len(result.data) - unknown_segment) / len(result.data) * 100

    print(f"    Enrichment: {pct_enriched_region:.1f}% region, {pct_enriched_segment:.1f}% segment")


if __name__ == '__main__':
    main()
