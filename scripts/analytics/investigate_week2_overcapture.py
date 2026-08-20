#!/usr/bin/env python3
"""
Investigate week 2 overcapture - find deals that shouldn't be in snapshot.
"""
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, 'scripts')
from supabase import create_client
from supabase_client import select_all

sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])

snapshot_date = '2026-08-10'
snapshot_dt = datetime.fromisoformat(snapshot_date).date()

# Get week 2 snapshot
snapshot = select_all(sb, 'deals_snapshot',
                      columns='deal_id, pipeline_id, close_date',
                      filters=[('eq', 'snapshot_date', snapshot_date)])

# Get all deals
deals = select_all(sb, 'deals',
                  columns='deal_id, create_date, close_date, pipeline_id')

# Build lookup
deals_dict = {d['deal_id']: d for d in deals}
snapshot_close_dates = {s['deal_id']: s.get('close_date') for s in snapshot}

print("WEEK 2 OVERCAPTURE INVESTIGATION")
print("=" * 80)
print(f"Snapshot date: {snapshot_date}")
print(f"Snapshot rows: {len(snapshot)}")
print()

# Find deals in snapshot that should NOT be there
violations = []

for snap in snapshot:
    deal_id = snap['deal_id']
    pipeline_id = snap.get('pipeline_id')

    deal = deals_dict.get(deal_id)
    if not deal:
        violations.append((deal_id, pipeline_id, "Deal not found in deals table"))
        continue

    # Check create_date
    create_date = deal.get('create_date')
    if not create_date:
        violations.append((deal_id, pipeline_id, "No create_date"))
        continue

    create_dt = datetime.fromisoformat(create_date).date()
    if create_dt > snapshot_dt:
        violations.append((deal_id, pipeline_id, f"Created after snapshot ({create_date})"))
        continue

    # Check close_date (use snapshot's version for point-in-time)
    close_date = snapshot_close_dates.get(deal_id)
    if close_date:
        close_dt = datetime.fromisoformat(close_date).date()
        if close_dt < snapshot_dt:
            violations.append((deal_id, pipeline_id, f"Closed before snapshot ({close_date})"))

if violations:
    print(f"Found {len(violations)} deals that should NOT be in week 2 snapshot:\n")
    for deal_id, pipeline_id, reason in violations:
        print(f"  {deal_id} ({pipeline_id}): {reason}")
else:
    print("No violations found - overcapture must be due to verification logic issue")

print()
print("=" * 80)
print("Checking reverse: deals that SHOULD be in snapshot but are missing")
print("=" * 80)

snapshot_ids = set(s['deal_id'] for s in snapshot)
missing = []

for deal in deals:
    deal_id = deal['deal_id']
    pipeline_id = deal.get('pipeline_id')

    # Should this deal be in the snapshot?
    create_date = deal.get('create_date')
    if not create_date:
        continue

    create_dt = datetime.fromisoformat(create_date).date()
    if create_dt > snapshot_dt:
        continue

    # Use snapshot close_date if available, else current
    close_date = snapshot_close_dates.get(deal_id) or deal.get('close_date')
    if close_date:
        close_dt = datetime.fromisoformat(close_date).date()
        if close_dt < snapshot_dt:
            continue

    # Deal should be in snapshot
    if deal_id not in snapshot_ids:
        missing.append((deal_id, pipeline_id, create_date, close_date or "NULL"))

if missing:
    print(f"\nFound {len(missing)} deals that SHOULD be in snapshot but are missing:\n")
    for deal_id, pipeline_id, create_date, close_date in missing[:10]:
        print(f"  {deal_id} ({pipeline_id}): created {create_date}, closes {close_date}")
    if len(missing) > 10:
        print(f"  ... and {len(missing) - 10} more")
else:
    print("\nNo missing deals")
