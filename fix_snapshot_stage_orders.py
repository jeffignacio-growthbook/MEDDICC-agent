#!/usr/bin/env python3
"""
Fix stage_order values in existing snapshots to match corrected client.yaml
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from supabase import create_client
from utils import get_stage_order
from supabase_client import select_all

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
    sys.exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Get all snapshots for Aug 9 and Aug 11
print("Fetching snapshots for Aug 9 and Aug 11...")
snapshots = select_all(
    sb, 'deals_snapshot',
    'deal_id, snapshot_date, stage_id, stage_order',
    filters=[('in_', 'snapshot_date', ['2026-08-09', '2026-08-11'])]
)

print(f"Found {len(snapshots)} snapshot rows to update\n")

# Update each snapshot with corrected stage_order
updated_count = 0
for snapshot in snapshots:
    stage_id = snapshot['stage_id']
    current_order = snapshot['stage_order']

    # Get correct order from updated config
    correct_order = get_stage_order(stage_id) or 0

    if current_order != correct_order:
        # Update the snapshot row
        sb.table('deals_snapshot').update({
            'stage_order': correct_order
        }).eq('deal_id', snapshot['deal_id']).eq('snapshot_date', snapshot['snapshot_date']).execute()

        updated_count += 1
        if updated_count <= 10:  # Show first 10 updates
            print(f"  {snapshot['snapshot_date']} Deal {snapshot['deal_id']}: "
                  f"{current_order} → {correct_order}")

print(f"\n✓ Updated {updated_count} snapshot rows with corrected stage_order values")
