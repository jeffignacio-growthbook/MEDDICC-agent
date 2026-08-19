#!/usr/bin/env python3
"""
Backfill forecast analysis fields in deals_snapshot.

Phase 2 backfill:
- fiscal_quarter: Derivable from snapshot_date + fiscal config → backfill ALL rows
- week_of_quarter: Derivable from snapshot_date + fiscal config → backfill ALL rows
- forecast_category: NOT recoverable (property history only has dealstage) → leave NULL

Critical output: Usable-quarters count (complete quarters with forecast_category populated).
"""

import os
import sys
from pathlib import Path
from datetime import datetime, date

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from supabase import create_client
from utils import get_fiscal_quarter


def get_week_of_quarter(snapshot_date_str, quarter_start):
    """Calculate week number within fiscal quarter (1-13)."""
    if isinstance(snapshot_date_str, str):
        snapshot_date = datetime.strptime(snapshot_date_str, '%Y-%m-%d').date()
    else:
        snapshot_date = snapshot_date_str

    if isinstance(quarter_start, str):
        quarter_start = datetime.strptime(quarter_start, '%Y-%m-%d').date()

    days_into_quarter = (snapshot_date - quarter_start).days
    week_num = (days_into_quarter // 7) + 1

    # Cap at 13 weeks (91 days)
    return min(week_num, 13)


def backfill_derivable_fields(sb):
    """
    Backfill fiscal_quarter and week_of_quarter for ALL historical rows.

    These fields are derivable from snapshot_date + fiscal config, so we can
    backfill them for every existing snapshot.
    """
    print("\n" + "=" * 70)
    print("BACKFILLING DERIVABLE FIELDS")
    print("=" * 70)
    print("\nFetching all snapshot rows with NULL fiscal_quarter...")

    # Get all snapshots that need backfill
    result = sb.table('deals_snapshot').select(
        'deal_id, snapshot_date'
    ).is_('fiscal_quarter', 'null').execute()

    snapshots = result.data
    total = len(snapshots)

    if total == 0:
        print("✓ No rows to backfill (all rows already have fiscal_quarter)")
        return

    print(f"Found {total:,} rows to backfill")
    print("\nProcessing in batches of 100...")

    # Process in batches
    batch_size = 100
    updated = 0

    for i in range(0, total, batch_size):
        batch = snapshots[i:i + batch_size]
        updates = []

        for row in batch:
            snapshot_date = row['snapshot_date']

            # Parse snapshot_date
            if isinstance(snapshot_date, str):
                snapshot_date_obj = datetime.strptime(snapshot_date, '%Y-%m-%d').date()
            else:
                snapshot_date_obj = snapshot_date

            # Calculate fiscal quarter and week
            q_start, q_end, fiscal_quarter_label = get_fiscal_quarter(snapshot_date_obj)
            week_of_quarter = get_week_of_quarter(snapshot_date_obj, q_start)

            updates.append({
                'deal_id': row['deal_id'],
                'snapshot_date': snapshot_date,
                'fiscal_quarter': fiscal_quarter_label,
                'week_of_quarter': week_of_quarter
            })

        # Upsert batch
        sb.table('deals_snapshot').upsert(
            updates,
            on_conflict='deal_id,snapshot_date'
        ).execute()

        updated += len(updates)
        if (i + batch_size) % 1000 == 0 or (i + batch_size) >= total:
            print(f"  Processed {min(i + batch_size, total):,} / {total:,} rows")

    print(f"\n✓ Backfilled {updated:,} rows with fiscal_quarter and week_of_quarter")


def analyze_forecast_category_coverage(sb):
    """
    Analyze forecast_category coverage to determine usable-quarters count.

    Critical output: How many complete fiscal quarters have forecast_category
    populated across the full quarter.

    This determines whether Phase 3's commit-calibration analysis can run
    now against real history or must wait for data to accumulate.
    """
    print("\n" + "=" * 70)
    print("FORECAST CATEGORY COVERAGE ANALYSIS")
    print("=" * 70)

    print("\nChecking if forecast_category is backfillable from property history...")
    print("  Property history workflow: .github/workflows/fetch-property-history.yml")
    print("  Properties captured: dealstage ONLY")
    print("  ❌ forecast_category NOT captured in property history")
    print("  → Cannot backfill historical forecast_category values")
    print("  → Historical rows will remain NULL")

    print("\nAnalyzing current forecast_category coverage...")

    # Get all snapshots with forecast_category
    result = sb.table('deals_snapshot').select(
        'fiscal_quarter, week_of_quarter, forecast_category'
    ).not_.is_('forecast_category', 'null').execute()

    snapshots_with_category = result.data
    print(f"  Snapshots with forecast_category: {len(snapshots_with_category):,}")

    if len(snapshots_with_category) == 0:
        print("\n" + "=" * 70)
        print("USABLE-QUARTERS COUNT: 0")
        print("=" * 70)
        print("\n⚠️  CRITICAL FINDING:")
        print("  No complete fiscal quarters have forecast_category populated.")
        print("  Phase 3 analyses will be SCAFFOLDING awaiting data accumulation.")
        print("\n  To enable Phase 3 analyses:")
        print("    1. Run snapshot_deals.py going forward (populates forecast_category)")
        print("    2. Wait for at least 1 complete fiscal quarter (13 weeks)")
        print("    3. Phase 3 commit-calibration will then return real data")
        print("\n  Until then:")
        print("    - week-3 conversion: will return NULL (insufficient quarters)")
        print("    - category churn: will return NULL (no category data)")
        print("    - commit calibration: will return NULL (no commit snapshots)")
        return

    # Group by fiscal quarter and check completeness
    quarters = {}
    for row in snapshots_with_category:
        q = row['fiscal_quarter']
        if q not in quarters:
            quarters[q] = set()
        quarters[q].add(row['week_of_quarter'])

    # A complete quarter has weeks 1-13
    complete_quarters = []
    for q, weeks in quarters.items():
        if len(weeks) >= 13:  # All weeks present
            complete_quarters.append(q)

    print(f"\n  Fiscal quarters with any forecast_category data: {len(quarters)}")
    print(f"  Complete quarters (weeks 1-13 all present): {len(complete_quarters)}")

    if complete_quarters:
        print(f"\n  Complete quarters:")
        for q in sorted(complete_quarters):
            print(f"    - {q}")

    print("\n" + "=" * 70)
    print(f"USABLE-QUARTERS COUNT: {len(complete_quarters)}")
    print("=" * 70)

    if len(complete_quarters) == 0:
        print("\n⚠️  Phase 3 analyses will be SCAFFOLDING awaiting data.")
        print("  Run snapshot_deals.py weekly to accumulate forecast_category data.")
    else:
        print(f"\n✓ Phase 3 analyses CAN RUN against {len(complete_quarters)} complete quarter(s).")
        print("  Commit calibration and week-3 conversion will return real data.")

    return len(complete_quarters)


def main():
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return 1

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("=" * 70)
    print("PHASE 2 BACKFILL: Forecast Analysis Fields")
    print("=" * 70)

    # Step 1: Backfill derivable fields
    backfill_derivable_fields(sb)

    # Step 2: Analyze forecast_category coverage (CRITICAL OUTPUT)
    usable_quarters = analyze_forecast_category_coverage(sb)

    print("\n" + "=" * 70)
    print("BACKFILL COMPLETE")
    print("=" * 70)
    print("\nSummary:")
    print(f"  ✓ fiscal_quarter: Backfilled for all historical rows")
    print(f"  ✓ week_of_quarter: Backfilled for all historical rows")
    print(f"  ✗ forecast_category: NOT backfillable (no property history)")
    print(f"\n  🎯 USABLE-QUARTERS COUNT: {usable_quarters or 0}")

    if not usable_quarters or usable_quarters == 0:
        print("\n  → Phase 3 will build analyses as SCAFFOLDING")
        print("  → Analyses will return NULL until data accumulates")
    else:
        print(f"\n  → Phase 3 can run against {usable_quarters} complete quarter(s)")
        print("  → Analyses will return real historical data")

    return 0


if __name__ == '__main__':
    sys.exit(main())
