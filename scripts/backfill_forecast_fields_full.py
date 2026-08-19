#!/usr/bin/env python3
"""
Full backfill of forecast fields for ALL snapshot rows.

Backfills:
1. fiscal_quarter and week_of_quarter (derivable from snapshot_date, no API calls)
2. forecast_category (from property_history_cache.json with point-in-time matching)

Usage:
    python scripts/backfill_forecast_fields_full.py --dry-run
    python scripts/backfill_forecast_fields_full.py
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
from supabase_client import select_all
from utils import get_fiscal_quarter
from analytics.snapshot_deals import get_week_of_quarter
from backfill_forecast_category import get_category_at_snapshot_date


def backfill_all_rows(sb, cache, dry_run=False):
    """
    Backfill fiscal_quarter, week_of_quarter, and forecast_category for ALL rows.

    Args:
        sb: Supabase client
        cache: Property history cache dict
        dry_run: If True, report what would be done but don't write
    """
    print("\n" + "=" * 70)
    print("FULL BACKFILL: ALL SNAPSHOT ROWS")
    print("=" * 70)

    # Get ALL snapshot rows (paginated)
    print("\nFetching all snapshot rows (paginated)...")
    all_rows = select_all(
        sb,
        'deals_snapshot',
        columns='deal_id, snapshot_date, fiscal_quarter, week_of_quarter, forecast_category',
        page_size=1000
    )
    print(f"Total snapshot rows: {len(all_rows):,}")

    # Statistics
    stats = {
        'total_rows': len(all_rows),
        'fiscal_quarter_missing': 0,
        'fiscal_quarter_updated': 0,
        'forecast_category_missing': 0,
        'forecast_category_updated': 0,
        'forecast_category_null_reasons': defaultdict(int),
        'by_quarter': defaultdict(lambda: {
            'total_rows': 0,
            'forecast_populated': 0,
            'forecast_coverage_pct': 0.0,
            'distinct_deals': set(),
            'deals_with_category': set()
        })
    }

    # Get property history
    deals_history = cache.get('deals', {})
    print(f"Property history available for {len(deals_history):,} deals")

    # Process all rows
    updates = []
    batch_size = 100

    print(f"\nProcessing {len(all_rows):,} rows...")

    for i, row in enumerate(all_rows, 1):
        deal_id = row['deal_id']
        snapshot_date = row['snapshot_date']
        current_fq = row.get('fiscal_quarter')
        current_wq = row.get('week_of_quarter')
        current_fc = row.get('forecast_category')

        update_needed = False
        update_data = {
            'deal_id': deal_id,
            'snapshot_date': snapshot_date
        }

        # 1. Backfill fiscal_quarter and week_of_quarter (always derivable)
        if not current_fq or not current_wq:
            stats['fiscal_quarter_missing'] += 1

            # Derive from snapshot_date
            snap_dt = datetime.strptime(snapshot_date, '%Y-%m-%d').date()
            q_start, q_end, fiscal_quarter = get_fiscal_quarter(snap_dt)
            week_of_quarter = get_week_of_quarter(snap_dt, q_start)

            update_data['fiscal_quarter'] = fiscal_quarter
            update_data['week_of_quarter'] = week_of_quarter
            update_needed = True
            stats['fiscal_quarter_updated'] += 1

            # Track by quarter
            stats['by_quarter'][fiscal_quarter]['total_rows'] += 1
            stats['by_quarter'][fiscal_quarter]['distinct_deals'].add(deal_id)
        else:
            # Already has fiscal quarter
            fiscal_quarter = current_fq
            stats['by_quarter'][fiscal_quarter]['total_rows'] += 1
            stats['by_quarter'][fiscal_quarter]['distinct_deals'].add(deal_id)

        # 2. Backfill forecast_category from property history
        if not current_fc:
            stats['forecast_category_missing'] += 1

            # Check if we have property history for this deal
            if deal_id not in deals_history:
                stats['forecast_category_null_reasons']['no_property_history'] += 1
            else:
                deal_cache = deals_history[deal_id]
                forecast_history = deal_cache.get('forecast_category_history', [])

                if not forecast_history:
                    stats['forecast_category_null_reasons']['no_forecast_history'] += 1
                else:
                    # Get point-in-time value
                    category_value = get_category_at_snapshot_date(
                        forecast_history,
                        snapshot_date
                    )

                    if category_value is None:
                        stats['forecast_category_null_reasons']['history_postdates_snapshot'] += 1
                    else:
                        # Found a value
                        update_data['forecast_category'] = category_value
                        update_needed = True
                        stats['forecast_category_updated'] += 1
                        stats['by_quarter'][fiscal_quarter]['forecast_populated'] += 1
                        stats['by_quarter'][fiscal_quarter]['deals_with_category'].add(deal_id)
        else:
            # Already has forecast_category
            stats['by_quarter'][fiscal_quarter]['forecast_populated'] += 1
            stats['by_quarter'][fiscal_quarter]['deals_with_category'].add(deal_id)

        if update_needed:
            updates.append(update_data)

        # Progress reporting every 5,000 rows
        if i % 5000 == 0 or i == len(all_rows):
            print(f"  Progress: {i:,} / {len(all_rows):,} rows ({i/len(all_rows)*100:.1f}%)")

    # Calculate coverage percentages
    for quarter, qstats in stats['by_quarter'].items():
        if qstats['total_rows'] > 0:
            qstats['forecast_coverage_pct'] = (qstats['forecast_populated'] / qstats['total_rows']) * 100

    # Report statistics
    print("\n" + "=" * 70)
    print("BACKFILL STATISTICS")
    print("=" * 70)

    print(f"\nFiscal quarter fields:")
    print(f"  Missing before backfill: {stats['fiscal_quarter_missing']:,}")
    print(f"  Updated: {stats['fiscal_quarter_updated']:,}")
    print(f"  Already populated: {stats['total_rows'] - stats['fiscal_quarter_missing']:,}")

    print(f"\nForecast category fields:")
    print(f"  Missing before backfill: {stats['forecast_category_missing']:,}")
    print(f"  Updated: {stats['forecast_category_updated']:,}")
    print(f"  Left NULL: {stats['forecast_category_missing'] - stats['forecast_category_updated']:,}")

    if stats['forecast_category_null_reasons']:
        print(f"\n  NULL reasons:")
        for reason, count in stats['forecast_category_null_reasons'].items():
            print(f"    {reason}: {count:,}")

    # Per-quarter report
    print("\n" + "=" * 70)
    print("PER-QUARTER ANALYSIS")
    print("=" * 70)

    # Sort quarters
    sorted_quarters = sorted(stats['by_quarter'].keys())

    for quarter in sorted_quarters:
        qstats = stats['by_quarter'][quarter]
        total_rows = qstats['total_rows']
        forecast_rows = qstats['forecast_populated']
        coverage_pct = qstats['forecast_coverage_pct']
        distinct_deals = len(qstats['distinct_deals'])
        deals_with_cat = len(qstats['deals_with_category'])

        # Check if complete (13 weeks)
        weeks_present = set()
        quarter_rows = [r for r in all_rows if r.get('fiscal_quarter') == quarter or
                       (not r.get('fiscal_quarter') and any(u.get('fiscal_quarter') == quarter for u in updates if u['deal_id'] == r['deal_id'] and u['snapshot_date'] == r['snapshot_date']))]
        # Simplified: just mark if likely complete based on row count
        is_complete = total_rows >= (distinct_deals * 10)  # Rough heuristic

        status = "✓ COMPLETE" if is_complete else "  PARTIAL"

        print(f"\n{quarter} {status}:")
        print(f"  Total snapshot rows: {total_rows:,}")
        print(f"  Rows with forecast_category: {forecast_rows:,} ({coverage_pct:.1f}%)")
        print(f"  Distinct deals: {distinct_deals:,}")
        print(f"  Deals with category data: {deals_with_cat:,}")

    # Write updates
    if dry_run:
        print("\n" + "=" * 70)
        print("DRY RUN - No changes written")
        print("=" * 70)
        print(f"\nWould update {len(updates):,} rows")
        if updates:
            print("\nSample updates (first 5):")
            for update in updates[:5]:
                print(f"  {update}")
    else:
        print("\n" + "=" * 70)
        print("WRITING UPDATES")
        print("=" * 70)

        if not updates:
            print("\nNo updates to write")
        else:
            print(f"\nWriting {len(updates):,} updates in batches of {batch_size}...")

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

            print(f"\n✓ Full backfill complete: {written:,} rows updated")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Full backfill of forecast fields for all snapshot rows'
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
    cache_path = Path(args.cache_file)
    if not cache_path.exists():
        print(f"⚠️  Property history cache not found: {args.cache_file}")
        print("Run: python scripts/analytics/hubspot_history.py --all")
        return 1

    with open(cache_path) as f:
        cache = json.load(f)

    print(f"✓ Loaded property history cache: {args.cache_file}")
    print(f"  Deals in cache: {len(cache.get('deals', {})):,}")

    # Run full backfill
    stats = backfill_all_rows(sb, cache, dry_run=args.dry_run)

    print("\n" + "=" * 70)
    print("FULL BACKFILL SUMMARY")
    print("=" * 70)
    print(f"\nTotal snapshot rows: {stats['total_rows']:,}")
    print(f"  Fiscal quarters backfilled: {stats['fiscal_quarter_updated']:,}")
    print(f"  Forecast categories backfilled: {stats['forecast_category_updated']:,}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
