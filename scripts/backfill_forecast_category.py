#!/usr/bin/env python3
"""
Backfill deals_snapshot.forecast_category from HubSpot property history.

Critical requirements:
1. Point-in-time matching: Use most recent history entry with timestamp <= snapshot_date
2. No lookahead bias: Future values must never be used
3. NULL when no past history: If earliest history postdates snapshot, return NULL

Usage:
    python scripts/backfill_forecast_category.py --dry-run
    python scripts/backfill_forecast_category.py
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))

from supabase import create_client


def get_category_at_snapshot_date(history, snapshot_date):
    """
    Get forecast_category value at a specific snapshot date using point-in-time matching.

    CRITICAL: Only considers history entries with timestamp <= snapshot_date.
    Never uses future values (prevents lookahead bias).

    Args:
        history: List of dicts with 'timestamp' and 'value'
        snapshot_date: Date string in 'YYYY-MM-DD' format

    Returns:
        str or None: The category value, or None if no history before snapshot_date
    """
    if not history:
        return None

    # Convert snapshot_date to datetime for comparison
    snapshot_dt = datetime.strptime(snapshot_date, '%Y-%m-%d').replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc
    )

    # Filter to only entries on or before snapshot_date
    past_entries = []
    for entry in history:
        timestamp_str = entry.get('timestamp')
        if not timestamp_str:
            continue

        # Parse HubSpot timestamp (ISO format with Z)
        entry_dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))

        # Only include if on or before snapshot date
        if entry_dt <= snapshot_dt:
            past_entries.append((entry_dt, entry.get('value')))

    if not past_entries:
        # No history before this snapshot date
        return None

    # Return the most recent past value
    past_entries.sort(key=lambda x: x[0], reverse=True)
    return past_entries[0][1]


def load_property_history_cache(cache_file='property_history_cache.json'):
    """Load property history cache from fetch-property-history workflow."""
    cache_path = Path(cache_file)

    if not cache_path.exists():
        print(f"⚠️  Property history cache not found: {cache_file}")
        print("\nRun the fetch-property-history workflow first:")
        print("  1. Go to Actions → Fetch HubSpot Property History")
        print("  2. Run workflow → downloads property_history_cache.json artifact")
        print("  3. Place artifact in repo root")
        print("\nOr run locally:")
        print("  python scripts/analytics/hubspot_history.py --all")
        return None

    with open(cache_path) as f:
        cache = json.load(f)

    print(f"✓ Loaded property history cache: {cache_file}")
    print(f"  Deals in cache: {len(cache.get('deals', {})):,}")
    print(f"  Cache timestamp: {cache.get('fetched_at', 'unknown')}")

    return cache


def backfill_from_property_history(sb, cache, dry_run=False):
    """
    Backfill deals_snapshot.forecast_category from property history cache.

    Args:
        sb: Supabase client
        cache: Property history cache dict
        dry_run: If True, report what would be done but don't write

    Returns:
        dict: Statistics about the backfill
    """
    print("\n" + "=" * 70)
    print("BACKFILLING FORECAST_CATEGORY FROM PROPERTY HISTORY")
    print("=" * 70)

    # Get all snapshot rows
    print("\nFetching all snapshot rows...")
    result = sb.table('deals_snapshot').select(
        'deal_id, snapshot_date, fiscal_quarter, forecast_category'
    ).execute()

    snapshots = result.data
    print(f"Total snapshot rows: {len(snapshots):,}")

    # Group by deal_id for efficient lookup
    snapshots_by_deal = defaultdict(list)
    for row in snapshots:
        snapshots_by_deal[row['deal_id']].append(row)

    # Statistics
    stats = {
        'total_rows': len(snapshots),
        'deals_with_history': 0,
        'deals_without_history': 0,
        'rows_populated': 0,
        'rows_left_null': 0,
        'rows_already_populated': 0,
        'null_reasons': defaultdict(int),
        'by_quarter': defaultdict(lambda: {'total': 0, 'populated': 0, 'null': 0})
    }

    # Get history from cache
    deals_history = cache.get('deals', {})

    # Process each deal
    updates = []
    unique_deals = set(row['deal_id'] for row in snapshots)

    print(f"\nProcessing {len(unique_deals):,} unique deals...")
    print(f"  Property history available for {len(deals_history):,} deals")

    for deal_id in unique_deals:
        # Check if we have history for this deal
        if deal_id not in deals_history:
            stats['deals_without_history'] += 1
            # Mark all snapshots for this deal as NULL (no history)
            for snapshot in snapshots_by_deal[deal_id]:
                quarter = snapshot.get('fiscal_quarter', 'unknown')
                stats['by_quarter'][quarter]['total'] += 1
                stats['by_quarter'][quarter]['null'] += 1
                stats['rows_left_null'] += 1
                stats['null_reasons']['no_history_for_deal'] += 1
            continue

        stats['deals_with_history'] += 1

        # Get forecast_category history for this deal
        deal_cache = deals_history[deal_id]
        forecast_history = deal_cache.get('forecast_category_history', [])

        if not forecast_history:
            # Deal in cache but no forecast_category history
            for snapshot in snapshots_by_deal[deal_id]:
                quarter = snapshot.get('fiscal_quarter', 'unknown')
                stats['by_quarter'][quarter]['total'] += 1
                stats['by_quarter'][quarter]['null'] += 1
                stats['rows_left_null'] += 1
                stats['null_reasons']['no_forecast_history'] += 1
            continue

        # Process each snapshot for this deal
        for snapshot in snapshots_by_deal[deal_id]:
            snapshot_date = snapshot['snapshot_date']
            quarter = snapshot.get('fiscal_quarter', 'unknown')
            current_value = snapshot.get('forecast_category')

            stats['by_quarter'][quarter]['total'] += 1

            # Skip if already populated (don't overwrite)
            if current_value is not None:
                stats['rows_already_populated'] += 1
                stats['by_quarter'][quarter]['populated'] += 1
                continue

            # Get point-in-time value
            category_value = get_category_at_snapshot_date(
                forecast_history,
                snapshot_date
            )

            if category_value is None:
                # No history before this snapshot date
                stats['rows_left_null'] += 1
                stats['by_quarter'][quarter]['null'] += 1
                stats['null_reasons']['history_postdates_snapshot'] += 1
            else:
                # Found a value - queue for update
                stats['rows_populated'] += 1
                stats['by_quarter'][quarter]['populated'] += 1

                updates.append({
                    'deal_id': deal_id,
                    'snapshot_date': snapshot_date,
                    'forecast_category': category_value
                })

    # Report statistics
    print("\n" + "=" * 70)
    print("BACKFILL STATISTICS")
    print("=" * 70)

    print(f"\nDeals:")
    print(f"  Unique deals in snapshots: {len(unique_deals):,}")
    print(f"  ✓ With property history: {stats['deals_with_history']:,}")
    print(f"  ✗ Without property history: {stats['deals_without_history']:,}")

    print(f"\nSnapshot rows:")
    print(f"  Total rows: {stats['total_rows']:,}")
    print(f"  Already populated: {stats['rows_already_populated']:,}")
    print(f"  To be populated: {stats['rows_populated']:,}")
    print(f"  Left NULL: {stats['rows_left_null']:,}")

    if stats['null_reasons']:
        print(f"\n  NULL reasons:")
        for reason, count in stats['null_reasons'].items():
            print(f"    {reason}: {count:,}")

    # Per-quarter coverage
    print("\n" + "=" * 70)
    print("PER-QUARTER COVERAGE")
    print("=" * 70)

    for quarter in sorted(stats['by_quarter'].keys()):
        q_stats = stats['by_quarter'][quarter]
        total = q_stats['total']
        populated = q_stats['populated']
        null = q_stats['null']

        coverage_pct = (populated / total * 100) if total > 0 else 0

        print(f"\n{quarter}:")
        print(f"  Total rows: {total:,}")
        print(f"  Populated: {populated:,} ({coverage_pct:.1f}%)")
        print(f"  NULL: {null:,}")

    # Write updates
    if dry_run:
        print("\n" + "=" * 70)
        print("DRY RUN - No changes written")
        print("=" * 70)
        print(f"\nWould update {len(updates):,} rows")
        if updates:
            print("\nSample updates (first 5):")
            for update in updates[:5]:
                print(f"  {update['deal_id']} @ {update['snapshot_date']}: {update['forecast_category']}")
    else:
        print("\n" + "=" * 70)
        print("WRITING UPDATES")
        print("=" * 70)

        if not updates:
            print("\nNo updates to write")
        else:
            print(f"\nWriting {len(updates):,} updates in batches of 100...")

            batch_size = 100
            written = 0

            for i in range(0, len(updates), batch_size):
                batch = updates[i:i + batch_size]
                sb.table('deals_snapshot').upsert(
                    batch,
                    on_conflict='deal_id,snapshot_date'
                ).execute()
                written += len(batch)

                if (i + batch_size) % 1000 == 0 or (i + batch_size) >= len(updates):
                    print(f"  Written {min(i + batch_size, len(updates)):,} / {len(updates):,} rows")

            print(f"\n✓ Backfill complete: {written:,} rows updated")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Backfill forecast_category from property history'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Report what would be done without writing'
    )
    parser.add_argument(
        '--cache-file',
        default='property_history_cache.json',
        help='Path to property history cache file'
    )
    args = parser.parse_args()

    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return 1

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Load property history cache
    cache = load_property_history_cache(args.cache_file)
    if not cache:
        return 1

    # Run backfill
    stats = backfill_from_property_history(sb, cache, dry_run=args.dry_run)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"\nTotal snapshot rows: {stats['total_rows']:,}")
    print(f"  ✓ Populated: {stats['rows_populated']:,}")
    print(f"  ✗ NULL: {stats['rows_left_null']:,}")
    print(f"  Already had value: {stats['rows_already_populated']:,}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
