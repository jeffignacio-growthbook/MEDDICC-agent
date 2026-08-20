"""
Historical Snapshot Backfill Script
Phase D Task 4 - Generate 52 weeks of historical deal snapshots

Uses HubSpot property history to create weekly snapshots showing:
- Stage progression over time
- Deal status (active/won/lost) at each snapshot date
- Confidence scoring for data quality

deal_value and close_date are reconstructed point-in-time from property
history, not proxied from today's values. Proxying them was one of the two
documented causes of the prior attempt's failure: it made backfilled
arr_change read as 0, because a deal cannot change its own value
retroactively when every week is stamped with today's number.

deal_value goes through utils.compute_deal_value on point-in-time component
values, so the GrowthBook value rule -- Incremental ARR, amount fallback,
plus Renewal ARR for renewals -- is applied once and not reimplemented here.

If NO value component resolves at a date, deal_value is None, not 0.0. An
all-blank component set means the value is UNKNOWN at that date, and
compute_deal_value would otherwise return 0.0 through the fallback path,
which is a fabricated number wearing the same clothes as the proxy it
replaced.

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
from collections import Counter
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# Add api path for field_semantics import
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'api'))

# Import field_semantics for canonical stage logic
try:
    from field_semantics import is_won, is_lost
except ImportError:
    from api.field_semantics import is_won, is_lost

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from supabase import create_client
from supabase_client import select_all

# Import shared point-in-time reconstruction logic
from point_in_time import get_stage_at_date as _get_stage_at_date
from point_in_time import get_field_at_date as _get_field_at_date
from point_in_time import is_deal_open_at_date, is_terminal_stage
from hubspot_history import HISTORY_KEYS
from utils import compute_deal_value, get_value_properties


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

        # Per-property history, shaped for point_in_time.get_field_at_date.
        # A record fetched before a property joined TRACKED_PROPERTIES has no
        # key for it, which reads as no_history rather than crashing.
        self.field_history = {}
        for prop, key in HISTORY_KEYS.items():
            self.field_history[prop] = {
                deal_id: {'history': rec.get(key) or []}
                for deal_id, rec in cache['deals'].items()
            }

        self.value_properties = get_value_properties(config)
        missing = [p for p in self.value_properties if p not in HISTORY_KEYS]
        if missing:
            raise ValueError(
                f"Value properties {missing} are not tracked in the property "
                f"history cache. Add them to hubspot_history.TRACKED_PROPERTIES "
                f"and re-fetch, or deal_value falls back to a proxy again."
            )

        print(f"Loaded property history for {len(self.property_history)} deals")

        # Load current deal data for mismatch detection and ARR values
        all_deals = select_all(
            self.client, 'deals',
            columns='deal_id,stage,company_name,deal_value,close_date,owner_email,pipeline_id'
        )
        self.current_deals = {d['deal_id']: d for d in all_deals}
        print(f"Loaded current data for {len(self.current_deals)} deals")

    def get_stage_order(self, stage_id: str) -> Optional[int]:
        """Get stage order, returns None if unmapped."""
        if not stage_id or stage_id not in self.stage_map:
            return None
        return self.stage_map[stage_id]['order']

    def is_won_stage(self, stage_id: str) -> bool:
        """Check if stage is a won stage. Uses field_semantics (handles aliases)."""
        return is_won(stage_id)

    def is_lost_stage(self, stage_id: str) -> bool:
        """Check if stage is a lost stage. Uses field_semantics (handles all aliases)."""
        return is_lost(stage_id)

    def get_deal_status(self, stage_id: str) -> str:
        """Compute deal_status from stage_id."""
        if self.is_won_stage(stage_id):
            return 'won'
        elif self.is_lost_stage(stage_id):
            return 'lost'
        else:
            return 'active'

    def get_value_at_date(self, deal_id, snapshot_date, pipeline_id):
        """
        Point-in-time deal value, via the shared GrowthBook value rule.

        Returns (value, confidence):
            value      float, or None when NO component resolved at this date
            confidence 'exact'       at least one component resolved
                       'pre_history' the deal predates its value history
                       'no_history'  no value history for this deal at all

        None, not 0.0, when nothing resolves. compute_deal_value on an
        all-blank property dict returns 0.0 through the amount fallback, and
        writing that would replace a proxy with a fabrication.
        """
        pit_props, confidences = {}, []
        for prop in self.value_properties:
            value, conf = _get_field_at_date(
                self.field_history[prop], deal_id, snapshot_date)
            pit_props[prop] = value
            confidences.append(conf)

        if 'exact' not in confidences:
            # Nothing resolved: the value is unknown at this date, not zero.
            return None, ('pre_history' if 'pre_history' in confidences
                          else 'no_history')

        return compute_deal_value(pit_props, self.config, pipeline_id), 'exact'

    def get_close_date_at_date(self, deal_id, snapshot_date):
        """
        Point-in-time close_date. Returns (value, confidence).

        close_date is a forecast that moves, so today's value says nothing
        about what was forecast at an earlier date. Reconstructing it is what
        makes the historical series comparable week to week.
        """
        raw, conf = _get_field_at_date(
            self.field_history['closedate'], deal_id, snapshot_date)
        if raw in (None, '', 'null'):
            return None, conf
        return str(raw)[:10], conf

    def is_open_at_date(self, deal_create_date, stage_at_date, snapshot_date):
        """
        Inclusion rule, delegated to the shared implementation so Method 1 and
        Method 2 cannot diverge. Terminal-stage, not close_date: a close_date
        that has slipped past D does not make an open deal closed.
        """
        return is_deal_open_at_date(
            deal_create_date, stage_at_date, snapshot_date, is_terminal_stage)

    def get_stage_at_date(self, deal_id: str, snapshot_date: datetime) -> Tuple[Optional[str], str, bool]:
        """
        Get stage ID for a deal at a specific snapshot date.

        Thin wrapper around shared point_in_time.get_stage_at_date.
        Delegates to single source of truth for reconstruction logic.

        Returns:
            (stage_id, confidence, has_history)
            - stage_id: The stage at snapshot_date (or None)
            - confidence: 'exact', 'pre_history', 'no_history'
            - has_history: True if property history exists
        """
        return _get_stage_at_date(self.property_history, deal_id, snapshot_date)

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

        # Get pipeline_id from stage_map (uses pipeline['id'] not pipeline['name'])
        stage_info = self.stage_map.get(stage_id, {})
        pipeline_id = stage_info.get('pipeline_id', 'default')

        # owner_email has no property history tracked, so it stays current.
        # Flagged rather than silent: an owner reassignment makes historical
        # owner attribution wrong, which matters for per-rep analysis.
        current = self.current_deals.get(deal_id, {})

        deal_value, value_confidence = self.get_value_at_date(
            deal_id, snapshot_date, pipeline_id)
        close_date, close_confidence = self.get_close_date_at_date(
            deal_id, snapshot_date)

        snapshot = {
            'deal_id': deal_id,
            'snapshot_date': snapshot_date.date().isoformat(),
            'pipeline_id': pipeline_id,
            'stage_id': stage_id,
            'stage_order': stage_order,
            'deal_value': deal_value,        # point-in-time, None if unknown
            'close_date': close_date,        # point-in-time
            'owner_email': current.get('owner_email'),   # current, see above
            'deal_status': deal_status,
            'snapshot_source': 'backfilled',
            'backfill_confidence': confidence,
            'value_confidence': value_confidence,
            'close_date_confidence': close_confidence,
            'has_property_history': has_history
        }

        return snapshot

    def backfill_all_snapshots(self, dry_run: bool = False) -> Dict:
        """
        Generate all historical snapshots for all deals.

        Returns summary statistics.
        """
        snapshot_dates = self.generate_snapshot_dates(weeks=52)

        # Find earliest prospective snapshot date — never backfill
        # on or after this date
        prospective = select_all(self.client, 'deals_snapshot',
            columns='snapshot_date',
            filters=[('eq', 'snapshot_source', 'prospective')])
        if prospective:
            earliest_prospective = min(r['snapshot_date'] for r in prospective)
            earliest_prospective_dt = datetime.fromisoformat(earliest_prospective)
            print(f"Earliest prospective snapshot: {earliest_prospective}")
            print(f"Backfill will stop before this date")
            print()
        else:
            earliest_prospective_dt = None

        # Filter out dates >= earliest prospective
        if earliest_prospective_dt:
            snapshot_dates = [d for d in snapshot_dates if d < earliest_prospective_dt]

        deal_ids = list(self.property_history.keys())

        print(f"Generating snapshots for {len(deal_ids)} deals")
        print(f"Snapshot dates: {len(snapshot_dates)} weeks (oldest: {snapshot_dates[0].date()})")
        print()

        stats = {
            'total_deals': len(deal_ids),
            'total_snapshot_dates': len(snapshot_dates),
            'snapshots_generated': 0,
            'snapshots_skipped': 0,
            'mismatched_deals': 0,
            # Counter, not a fixed dict: the old keys were the retired
            # interpolated/inferred labels, so any current label
            # ('pre_history', 'cleared', 'no_history') would KeyError here
            # mid-backfill.
            'by_confidence': Counter(),
            'by_status': {
                'active': 0,
                'won': 0,
                'lost': 0
            },
            'mismatch_examples': []
        }

        snapshots_to_insert = []

        for deal_id in deal_ids:
            deal_snapshots = []

            # Build all snapshots for this deal
            for snapshot_date in snapshot_dates:
                snapshot = self.build_snapshot(deal_id, snapshot_date)

                if snapshot:
                    deal_snapshots.append(snapshot)
                else:
                    stats['snapshots_skipped'] += 1

            # Check for history replay mismatch
            if deal_snapshots:
                final_snapshot = deal_snapshots[-1]  # Last snapshot (most recent)
                final_stage = final_snapshot['stage_id']
                current_deal = self.current_deals.get(deal_id)
                current_stage = current_deal.get('stage') if current_deal else None
                company_name = current_deal.get('company_name', 'Unknown') if current_deal else 'Unknown'

                if current_stage and final_stage != current_stage:
                    # MISMATCH: History replay doesn't match current stage
                    stats['mismatched_deals'] += 1

                    # Mark ALL snapshots for this deal as excluded_mismatch
                    for snap in deal_snapshots:
                        snap['backfill_confidence'] = 'excluded_mismatch'

                    # Print mismatch clearly
                    print(f"  MISMATCH: {company_name} | final_stage={final_stage} current_stage={current_stage} — excluded from win-rate analysis")

                    # Track example for report (first 10)
                    if len(stats['mismatch_examples']) < 10:
                        stats['mismatch_examples'].append({
                            'company_name': company_name,
                            'deal_id': deal_id,
                            'final_replay_stage': final_stage,
                            'current_actual_stage': current_stage
                        })

                # Add to insert list and update stats
                for snap in deal_snapshots:
                    stats['snapshots_generated'] += 1
                    stats['by_confidence'][snap['backfill_confidence']] += 1
                    stats['by_status'][snap['deal_status']] += 1
                    snapshots_to_insert.append(snap)

            # Progress update every 50 deals
            if (deal_ids.index(deal_id) + 1) % 50 == 0:
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
                      f"{snap['stage_id']} ({snap['deal_status']}) - "
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
            self.client.table('deals_snapshot').upsert(
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
    print()

    # Report on mismatches
    if stats['mismatched_deals'] > 0:
        print("=" * 70)
        print("HISTORY REPLAY MISMATCHES (excluded from win-rate)")
        print("=" * 70)
        print(f"Deals with mismatches: {stats['mismatched_deals']}")
        print()
        print("First 10 examples:")
        print()
        for ex in stats['mismatch_examples']:
            print(f"  {ex['company_name']}")
            print(f"    Deal ID: {ex['deal_id']}")
            print(f"    Final replay stage: {ex['final_replay_stage']}")
            print(f"    Current actual stage: {ex['current_actual_stage']}")
            print()
        print("These deals are flagged as 'excluded_mismatch' and should be")
        print("excluded from win-rate and conversion analysis.")
        print("=" * 70)

    return 0


if __name__ == '__main__':
    sys.exit(main())
