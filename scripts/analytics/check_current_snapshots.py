#!/usr/bin/env python3
"""
Check current FY2027 Q3 snapshots after cleanup to understand what was deleted.
"""
import os
import sys
from dotenv import load_dotenv
from collections import defaultdict

load_dotenv()

sys.path.insert(0, 'scripts')
from supabase import create_client
from supabase_client import select_all

sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])

# Check current FY2027 Q3 snapshots
current = select_all(sb, 'deals_snapshot',
                     columns='snapshot_date, snapshot_source, fiscal_quarter',
                     filters=[('gte', 'snapshot_date', '2026-08-01'),
                             ('lte', 'snapshot_date', '2026-10-31')])

print('Current FY2027 Q3 snapshots after cleanup:')
print(f'Total rows: {len(current)}')
print()

# Group by snapshot_date and source
by_date_source = defaultdict(lambda: defaultdict(int))
fiscal_quarter_nulls = 0

for row in current:
    date = row['snapshot_date']
    source = row.get('snapshot_source', 'unknown')
    by_date_source[date][source] += 1

    if row.get('fiscal_quarter') is None:
        fiscal_quarter_nulls += 1

print('Breakdown by date and source:')
for date in sorted(by_date_source.keys()):
    print(f'  {date}:')
    for source, count in sorted(by_date_source[date].items()):
        print(f'    {source}: {count}')
    total = sum(by_date_source[date].values())
    print(f'    TOTAL: {total}')

print()
print(f'Rows with fiscal_quarter=NULL: {fiscal_quarter_nulls}')

# Calculate what was deleted
# Backfill created: 369 + 370 + 377 = 1,116 rows for weeks 1-3
print()
print('Deletion reconciliation:')
print(f'  Deleted: 420 rows')
print(f'  Week 2 overcapture: 14 rows (identified)')
print(f'  Other: 406 rows (to be explained)')
