#!/usr/bin/env python3
"""
Weekly (or nightly) snapshot of open pipeline deals into deals_snapshot.

INVARIANTS:
1. Point-in-time correctness: Every field in deals_snapshot is the value
   as of snapshot_date, never current state from a later date.

2. Inclusion rule: A deal belongs in the snapshot for date D if:
   - created_date <= D, AND
   - (close_date IS NULL OR close_date >= D)

   Deals drop out of snapshots after they close. Historical snapshots
   capture the open pipeline as of that date, not all deals ever.

Idempotent — running twice same day upserts, not duplicates.
Must be run AFTER etl_deals.py --mode analytics so the deals table is current.

Usage: python scripts/analytics/snapshot_deals.py
"""

import os
import json
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


def get_week_of_quarter(snapshot_date, quarter_start):
    """
    Calculate week number within fiscal quarter (1-13).

    Args:
        snapshot_date: Date of the snapshot
        quarter_start: Start date of the fiscal quarter

    Returns:
        int: Week number (1-13)
    """
    if isinstance(snapshot_date, str):
        snapshot_date = datetime.strptime(snapshot_date, '%Y-%m-%d').date()
    if isinstance(quarter_start, str):
        quarter_start = datetime.strptime(quarter_start, '%Y-%m-%d').date()

    days_into_quarter = (snapshot_date - quarter_start).days
    week_num = (days_into_quarter // 7) + 1

    # Cap at 13 weeks (91 days)
    return min(week_num, 13)


def main():
    from dotenv import load_dotenv
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

    today = date.today().isoformat()
    today_date = date.today()

    # Calculate fiscal quarter and week for today's snapshot
    from utils import get_fiscal_quarter
    q_start, q_end, fiscal_quarter_label = get_fiscal_quarter(today_date)
    week_of_quarter = get_week_of_quarter(today_date, q_start)

    # Read all current deals from Supabase (paginated)
    deals = select_all(
        sb, 'deals',
        'deal_id, pipeline_id, stage, deal_value, '
        'close_date, owner_email, deal_status, create_date, '
        'highest_stage_order_reached, forecast_category'
    )
    if not deals:
        print("No deals in Supabase — run etl_deals.py first")
        return

    # Filter to deals that belong in today's snapshot per inclusion rule
    from datetime import datetime
    qualified_deals = []
    for d in deals:
        # Must be created before or on snapshot date
        create_date = d.get('create_date')
        if not create_date:
            continue  # Skip deals without create_date

        create_dt = datetime.fromisoformat(create_date).date()
        if create_dt > today_date:
            continue  # Deal created after snapshot date

        # Must be open on snapshot date (not closed before it)
        close_date = d.get('close_date')
        if close_date:
            close_dt = datetime.fromisoformat(close_date).date()
            if close_dt < today_date:
                continue  # Deal closed before snapshot date

        qualified_deals.append(d)

    print(f"Qualified deals for snapshot: {len(qualified_deals):,} / {len(deals):,}")

    # Build snapshot rows
    from utils import get_stage_order

    snapshots = []
    for d in qualified_deals:
        order = get_stage_order(d.get('stage', '')) or 0
        snapshots.append({
            'deal_id': d['deal_id'],
            'snapshot_date': today,
            'pipeline_id': d.get('pipeline_id', 'default'),
            'stage_id': d.get('stage'),
            'stage_order': order,
            'deal_value': d.get('deal_value'),
            'close_date': d.get('close_date'),
            'owner_email': d.get('owner_email'),
            'deal_status': d.get('deal_status', 'active'),
            'snapshot_source': 'prospective',
            'forecast_category': d.get('forecast_category'),
            'fiscal_quarter': fiscal_quarter_label,
            'week_of_quarter': week_of_quarter,
        })

    # Upsert (idempotent on deal_id + snapshot_date PK)
    written = 0
    batch_size = 100
    for i in range(0, len(snapshots), batch_size):
        batch = snapshots[i:i + batch_size]
        sb.table('deals_snapshot').upsert(
            batch,
            on_conflict='deal_id,snapshot_date'
        ).execute()
        written += len(batch)

    print(f"✓ Snapshot {today}: {written} deals written to "
          f"deals_snapshot")

    # Coverage assertion: Verify we captured expected deals (all pipelines)
    import yaml
    config_path = REPO_ROOT / 'config' / 'client.yaml'
    min_coverage = 95   # Default floor
    max_coverage = 105  # Default ceiling

    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f)
            forecast_config = config.get('forecast_analysis', {})
            min_coverage = forecast_config.get('min_write_coverage_pct', 95)
            max_coverage = forecast_config.get('max_write_coverage_pct', 105)

    # Get all unique pipelines
    all_pipelines = set(d.get('pipeline_id') for d in deals if d.get('pipeline_id'))

    print(f"\nCoverage check (all pipelines, point-in-time):")

    all_passed = True
    failures = []
    total_genuinely_open = 0
    total_captured = 0

    # First, fetch today's snapshot to get point-in-time close_date
    todays_snapshot = select_all(
        sb, 'deals_snapshot',
        'deal_id, pipeline_id, close_date',
        filters=[('eq', 'snapshot_date', today)]
    )
    snapshot_close_dates = {s['deal_id']: s.get('close_date') for s in todays_snapshot}

    for pipeline_id in sorted(all_pipelines, key=lambda x: (x != 'default', x)):
        # Count qualified deals in this pipeline
        qualified_pipeline = [d for d in qualified_deals if d.get('pipeline_id') == pipeline_id]
        qualified_pipeline_ids = set(d['deal_id'] for d in qualified_pipeline)

        # Genuinely open in this pipeline (using point-in-time close_date from snapshot)
        genuinely_open = []
        for d in deals:
            if d.get('pipeline_id') != pipeline_id:
                continue

            create_date = d.get('create_date')
            if not create_date:
                continue

            create_dt = datetime.fromisoformat(create_date).date()
            if create_dt > today_date:
                continue

            # Use close_date from snapshot (point-in-time) if available, else from deals table
            deal_id = d['deal_id']
            close_date = snapshot_close_dates.get(deal_id) or d.get('close_date')

            if close_date:
                close_dt = datetime.fromisoformat(close_date).date()
                if close_dt < today_date:
                    continue

            genuinely_open.append(d)

        genuinely_open_ids = set(d['deal_id'] for d in genuinely_open)
        genuinely_open_count = len(genuinely_open_ids)
        qualified_count = len(qualified_pipeline_ids)

        # Check for missing and extra deals
        missing = genuinely_open_ids - qualified_pipeline_ids
        extra = qualified_pipeline_ids - genuinely_open_ids

        coverage_pct = (qualified_count / genuinely_open_count * 100) if genuinely_open_count > 0 else 0

        total_genuinely_open += genuinely_open_count
        total_captured += qualified_count

        # Check both floor and ceiling
        if coverage_pct < min_coverage:
            status = "✗ UNDER"
            all_passed = False
            failures.append((pipeline_id, coverage_pct, 'undercapture', len(missing), len(extra)))
        elif coverage_pct > max_coverage:
            status = "✗ OVER"
            all_passed = False
            failures.append((pipeline_id, coverage_pct, 'overcapture', len(missing), len(extra)))
        else:
            status = "✓"

        print(f"  {pipeline_id:<20} Open: {genuinely_open_count:>4}  Captured: {qualified_count:>4}  "
              f"Coverage: {coverage_pct:>5.1f}%  {status}")

        if not all_passed and (coverage_pct < min_coverage or coverage_pct > max_coverage):
            print(f"    Missing: {len(missing)}  Extra: {len(extra)}")

    # Overall coverage
    overall_coverage = (total_captured / total_genuinely_open * 100) if total_genuinely_open > 0 else 0
    print(f"  {'─' * 60}")
    print(f"  {'TOTAL':<20} Open: {total_genuinely_open:>4}  Captured: {total_captured:>4}  "
          f"Coverage: {overall_coverage:>5.1f}%")

    if not all_passed:
        error_msg = f"\n✗ COVERAGE ASSERTION FAILED\n"
        error_msg += f"  Valid range: {min_coverage}% - {max_coverage}%\n\n"

        for pipeline_id, cov_pct, failure_type, missing, extra in failures:
            if failure_type == 'undercapture':
                error_msg += f"  {pipeline_id}: {cov_pct:.1f}% < {min_coverage}% (UNDERCAPTURE)\n"
                error_msg += f"    Missing {missing} deals - systematic exclusion bug (like 291-row cap)\n"
            else:
                error_msg += f"  {pipeline_id}: {cov_pct:.1f}% > {max_coverage}% (OVERCAPTURE)\n"
                error_msg += f"    Extra {extra} deals - inclusion-rule bug (closed deals in open snapshot)\n"

        error_msg += f"\n  Fix before deploying to production"
        print(error_msg)
        raise AssertionError(error_msg)

    print(f"\n  ✓ Coverage assertion passed ({min_coverage}% - {max_coverage}%)")


if __name__ == '__main__':
    main()
