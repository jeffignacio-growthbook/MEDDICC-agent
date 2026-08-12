"""
Historical Snapshot Backfill Script
Phase D Task 4 - Generate 52 weeks of historical deal snapshots

Uses HubSpot property history to create weekly snapshots showing:
- Stage progression over time
- Deal status (active/won/lost) at each snapshot date
- Confidence scoring for data quality

Requires:
- Property history cache from hubspot_history.py
- Migration 017 (backfill confidence fields)

Usage:
    python scripts/analytics/backfill_snapshots.py --dry-run  # Validation report only
    python scripts/analytics/backfill_snapshots.py            # Real backfill
"""
import os
import sys
import json
import yaml
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from supabase import create_client
from supabase_client import select_all


class SnapshotBackfiller:
    """Generates historical snapshots from property history."""

    def __init__(self, property_history_cache: str = 'property_history_cache.json'):
        # Load Supabase connection
        self.supabase_url = os.environ['SUPABASE_URL']
        self.supabase_key = os.environ['SUPABASE_SERVICE_KEY']
        self.client = create_client(self.supabase_url, self.supabase_key)

        # Load pipeline config
        config_path = Path(__file__).parent.parent.parent / 'config/client.yaml'
        with open(config_path) as f:
            config = yaml.safe_load(f)
        self.config = config

        # Build stage lookup
        self.stage_map = {}
        for pipeline in config['pipeline']['pipelines']:
            for stage in pipeline['stages']:
                self.stage_map[stage['id']] = {
                    'name': stage['name'],
                    'order': stage['order'],
                    'pipeline_id': pipeline['id'],
                    'pipeline_name': pipeline['name']
                }

        # Load property history
        cache_path = Path(property_history_cache)
        if not cache_path.exists():
            raise FileNotFoundError(
                f"Property history cache not found: {property_history_cache}\n"
                f"Run hubspot_history.py first to fetch property history"
            )

        with open(cache_path) as f:
            cache = json.load(f)
        self.property_history = cache['deals']

        print(f"Loaded property history for {len(self.property_history)} deals")

    def get_stage_order(self, stage_id: str) -> Optional[int]:
        """Get stage order, returns None if unmapped."""
        if not stage_id or stage_id not in self.stage_map:
            return None
        return self.stage_map[stage_id]['order']

    def is_won_stage(self, stage_id: str) -> bool:
        """Check if stage is a won stage."""
        return stage_id == 'closedwon'

    def is_lost_stage(self, stage_id: str) -> bool:
        """Check if stage is a lost stage."""
        return stage_id in ('closedlost', '68509551')  # closedlost or Disqualified

    def get_deal_status(self, stage_id: str) -> str:
        """Compute deal_status from stage_id."""
        if self.is_won_stage(stage_id):
            return 'won'
        elif self.is_lost_stage(stage_id):
            return 'lost'
        else:
            return 'active'

    def get_stage_at_date(self, deal_id: str, snapshot_date: datetime) -> Tuple[Optional[str], str, bool]:
        """
        Get stage ID for a deal at a specific snapshot date.

        Returns:
            (stage_id, confidence, has_history)
            - stage_id: The stage at snapshot_date (or None)
            - confidence: 'exact', 'interpolated', 'inferred', or 'unknown'
            - has_history: True if property history exists
        """
        if deal_id not in self.property_history:
            # No property history available
            return None, 'unknown', False

        history = self.property_history[deal_id]['history']

        if not history:
            # Deal exists but has no stage history
            return None, 'unknown', False

        # Sort history by timestamp (oldest first)
        sorted_history = sorted(history, key=lambda x: x['timestamp'])

        # Find the most recent stage change before or at snapshot_date
        snapshot_ts = snapshot_date.isoformat()
        current_stage = None
        exact_match = False

        for entry in sorted_history:
            entry_ts = entry['timestamp']

            if entry_ts <= snapshot_ts:
                current_stage = entry['value']
                # Check if this is an exact match (same day)
                entry_date = datetime.fromisoformat(entry_ts.replace('Z', '+00:00')).date()
                snapshot_dt = snapshot_date.date()
                if entry_date == snapshot_dt:
                    exact_match = True
            else:
                # We've passed the snapshot date
                break

        if current_stage is None:
            # No stage change before this snapshot date (deal created after snapshot)
            return None, 'inferred', True

        # Determine confidence level
        if exact_match:
            confidence = 'exact'
        else:
            confidence = 'interpolated'

        return current_stage, confidence, True

    def generate_snapshot_dates(self, weeks: int = 52) -> List[datetime]:
        """
        Generate weekly snapshot dates for the past N weeks.

        Returns dates in ascending order (oldest first).
        """
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        # Start from 52 weeks ago, weekly snapshots up to today
        dates = []
        for week_offset in range(weeks, -1, -1):  # 52 weeks ago to now
            snapshot_date = today - timedelta(weeks=week_offset)
            dates.append(snapshot_date)

        return dates

    def build_snapshot(self, deal_id: str, snapshot_date: datetime) -> Optional[Dict]:
        """
        Build a single snapshot for a deal at a specific date.

        Returns snapshot dict or None if deal didn't exist at that date.
        """
        stage_id, confidence, has_history = self.get_stage_at_date(deal_id, snapshot_date)

        if stage_id is None:
            # Deal didn't exist at this snapshot date
            return None

        stage_order = self.get_stage_order(stage_id)
        deal_status = self.get_deal_status(stage_id)

        snapshot = {
            'deal_id': deal_id,
            'snapshot_date': snapshot_date.date().isoformat(),
            'stage': stage_id,
            'stage_order': stage_order,
            'deal_status': deal_status,
            'backfill_confidence': confidence,
            'has_property_history': has_history,
            'created_at': datetime.now().isoformat()
        }

        return snapshot

    def backfill_all_snapshots(self, dry_run: bool = False) -> Dict:
        """
        Generate all historical snapshots for all deals.

        Returns summary statistics.
        """
        snapshot_dates = self.generate_snapshot_dates(weeks=52)
        deal_ids = list(self.property_history.keys())

        print(f"Generating snapshots for {len(deal_ids)} deals")
        print(f"Snapshot dates: {len(snapshot_dates)} weeks (oldest: {snapshot_dates[0].date()})")
        print()

        stats = {
            'total_deals': len(deal_ids),
            'total_snapshot_dates': len(snapshot_dates),
            'snapshots_generated': 0,
            'snapshots_skipped': 0,
            'by_confidence': {
                'exact': 0,
                'interpolated': 0,
                'inferred': 0,
                'unknown': 0
            },
            'by_status': {
                'active': 0,
                'won': 0,
                'lost': 0
            }
        }

        snapshots_to_insert = []

        for deal_id in deal_ids:
            for snapshot_date in snapshot_dates:
                snapshot = self.build_snapshot(deal_id, snapshot_date)

                if snapshot:
                    stats['snapshots_generated'] += 1
                    stats['by_confidence'][snapshot['backfill_confidence']] += 1
                    stats['by_status'][snapshot['deal_status']] += 1
                    snapshots_to_insert.append(snapshot)
                else:
                    stats['snapshots_skipped'] += 1

            # Progress update every 50 deals
            if len([d for d in deal_ids if deal_ids.index(d) <= deal_ids.index(deal_id)]) % 50 == 0:
                progress = deal_ids.index(deal_id) + 1
                print(f"  Processed {progress}/{len(deal_ids)} deals...")

        print()
        print(f"Generated {len(snapshots_to_insert)} snapshots")
        print()

        if dry_run:
            print("DRY RUN - No data written to database")
            print()
            print("Sample snapshots (first 5):")
            for snap in snapshots_to_insert[:5]:
                print(f"  Deal {snap['deal_id']} @ {snap['snapshot_date']}: "
                      f"{snap['stage']} ({snap['deal_status']}) - "
                      f"confidence: {snap['backfill_confidence']}")
        else:
            print("Writing snapshots to Supabase...")
            self._insert_snapshots(snapshots_to_insert)
            print(f"✓ Inserted {len(snapshots_to_insert)} snapshots")

        return stats

    def _insert_snapshots(self, snapshots: List[Dict]):
        """Insert snapshots into Supabase in batches."""
        batch_size = 500
        total = len(snapshots)

        for i in range(0, total, batch_size):
            batch = snapshots[i:i + batch_size]
            self.client.table('deal_snapshots').upsert(
                batch,
                on_conflict='deal_id,snapshot_date'
            ).execute()

            if (i + batch_size) % 5000 == 0 or (i + batch_size) >= total:
                progress = min(i + batch_size, total)
                print(f"  Inserted {progress}/{total} snapshots...")


def main():
    parser = argparse.ArgumentParser(description='Backfill historical deal snapshots')
    parser.add_argument('--dry-run', action='store_true',
                       help='Generate validation report without writing to database')
    parser.add_argument('--cache-file', default='property_history_cache.json',
                       help='Path to property history cache file')

    args = parser.parse_args()

    print("=" * 70)
    if args.dry_run:
        print("HISTORICAL SNAPSHOT BACKFILL - DRY RUN")
    else:
        print("HISTORICAL SNAPSHOT BACKFILL")
    print("=" * 70)
    print()

    # Create backfiller
    backfiller = SnapshotBackfiller(property_history_cache=args.cache_file)

    # Run backfill
    stats = backfiller.backfill_all_snapshots(dry_run=args.dry_run)

    # Print summary
    print()
    print("=" * 70)
    print("BACKFILL SUMMARY")
    print("=" * 70)
    print(f"Total deals: {stats['total_deals']}")
    print(f"Snapshot dates: {stats['total_snapshot_dates']} weeks")
    print(f"Snapshots generated: {stats['snapshots_generated']}")
    print(f"Snapshots skipped: {stats['snapshots_skipped']}")
    print()
    print("By confidence level:")
    for level, count in stats['by_confidence'].items():
        pct = count / stats['snapshots_generated'] * 100 if stats['snapshots_generated'] > 0 else 0
        print(f"  {level}: {count} ({pct:.1f}%)")
    print()
    print("By deal status:")
    for status, count in stats['by_status'].items():
        pct = count / stats['snapshots_generated'] * 100 if stats['snapshots_generated'] > 0 else 0
        print(f"  {status}: {count} ({pct:.1f}%)")

    return 0


if __name__ == '__main__':
    sys.exit(main())
