#!/usr/bin/env python3
"""
Backfill fiscal_quarter for 312 orphan rows with NULL values.

These rows are from historical backfill (source='backfilled', dates in 2025)
before fiscal_quarter field was added. After backfilling, we can add NOT NULL
constraint to prevent future orphans.
"""
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from supabase import create_client
from utils import get_fiscal_quarter

def main():
    sb = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_KEY'))

    print("=" * 80)
    print("BACKFILL NULL FISCAL_QUARTER VALUES")
    print("=" * 80)

    # Get all rows with fiscal_quarter=NULL
    result = sb.table('deals_snapshot').select('deal_id, snapshot_date, fiscal_quarter').is_('fiscal_quarter', 'null').execute()

    null_rows = result.data
    print(f"\nFound {len(null_rows)} rows with fiscal_quarter=NULL")

    if not null_rows:
        print("✓ No NULL values to backfill")
        return

    # Group by snapshot_date to show distribution
    from collections import defaultdict
    by_date = defaultdict(int)
    for row in null_rows:
        by_date[row['snapshot_date']] += 1

    print(f"\nDistribution across {len(by_date)} unique snapshot_dates")
    print(f"  Earliest: {min(by_date.keys())}")
    print(f"  Latest: {max(by_date.keys())}")

    # Calculate fiscal_quarter for each unique snapshot_date
    date_to_quarter = {}
    for snapshot_date in by_date.keys():
        snapshot_dt = datetime.fromisoformat(snapshot_date).date()
        q_start, q_end, fiscal_quarter_label = get_fiscal_quarter(snapshot_dt)
        week_of_quarter = ((snapshot_dt - q_start).days // 7) + 1
        week_of_quarter = min(week_of_quarter, 13)

        date_to_quarter[snapshot_date] = {
            'fiscal_quarter': fiscal_quarter_label,
            'week_of_quarter': week_of_quarter
        }

    print(f"\nFiscal quarters to backfill:")
    quarters = defaultdict(int)
    for snapshot_date, count in by_date.items():
        fq = date_to_quarter[snapshot_date]['fiscal_quarter']
        quarters[fq] += count

    for fq in sorted(quarters.keys()):
        print(f"  {fq}: {quarters[fq]} rows")

    # Update rows
    print(f"\nBackfilling {len(null_rows)} rows...")

    updated = 0
    batch_size = 100

    for snapshot_date, fq_data in date_to_quarter.items():
        # Update all rows for this snapshot_date
        rows_to_update = [r for r in null_rows if r['snapshot_date'] == snapshot_date]

        # Upsert with fiscal_quarter and week_of_quarter
        for i in range(0, len(rows_to_update), batch_size):
            batch = rows_to_update[i:i + batch_size]
            updates = []

            for row in batch:
                updates.append({
                    'deal_id': row['deal_id'],
                    'snapshot_date': row['snapshot_date'],
                    'fiscal_quarter': fq_data['fiscal_quarter'],
                    'week_of_quarter': fq_data['week_of_quarter']
                })

            sb.table('deals_snapshot').upsert(
                updates,
                on_conflict='deal_id,snapshot_date'
            ).execute()

            updated += len(updates)

    print(f"✓ Updated {updated} rows")

    # Verify
    remaining = sb.table('deals_snapshot').select('deal_id', count='exact').is_('fiscal_quarter', 'null').execute()

    print(f"\n{'=' * 80}")
    print("VERIFICATION")
    print(f"{'=' * 80}")
    print(f"\nRows with fiscal_quarter=NULL after backfill: {remaining.count}")

    if remaining.count == 0:
        print("\n✓ All NULL values backfilled successfully")
        print("\nNext step: Add NOT NULL constraint")
        print("  python3 scripts/analytics/add_fiscal_quarter_constraint.py")
    else:
        print(f"\n✗ {remaining.count} NULL values remain - investigate before adding constraint")

if __name__ == '__main__':
    main()
