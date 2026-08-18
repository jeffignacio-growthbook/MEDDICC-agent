#!/usr/bin/env python3
"""
Seed Jake Stangl's Q3 FY2027 targets in rep_targets table.

Assumes:
- 10 meetings booked per month = 30 for Q3
- 75% show rate = 22 meetings held
- 50% SQL conversion = 11 SQLs created
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent))
from api.db import get_supabase

sb = get_supabase()

print("\n" + "="*80)
print("SEEDING JAKE STANGL'S Q3 FY2027 TARGETS")
print("="*80)

targets = [
    {
        'period': 'Q3_FY2027',
        'level': 'rep',
        'entity_name': 'Jake Stangl',
        'entity_email': 'jake.stangl@growthbook.io',
        'role': 'sdr',
        'metric': 'meetings_booked',
        'target_value': 30,  # 10 per month × 3 months
        'parent_entity': 'SDR Team'
    },
    {
        'period': 'Q3_FY2027',
        'level': 'rep',
        'entity_name': 'Jake Stangl',
        'entity_email': 'jake.stangl@growthbook.io',
        'role': 'sdr',
        'metric': 'meetings_held',
        'target_value': 22,  # 30 × 75% show rate
        'parent_entity': 'SDR Team'
    },
    {
        'period': 'Q3_FY2027',
        'level': 'rep',
        'entity_name': 'Jake Stangl',
        'entity_email': 'jake.stangl@growthbook.io',
        'role': 'sdr',
        'metric': 'sqls_created',
        'target_value': 11,  # 22 × 50% SQL conversion
        'parent_entity': 'SDR Team'
    }
]

print("\nTargets to insert:")
for target in targets:
    print(f"  {target['metric']:20} {target['target_value']:3} "
          f"({target['period']})")

print("\nInserting into rep_targets table...")
# First, delete any existing Q3 targets for Jake
try:
    sb.table('rep_targets').delete().eq(
        'entity_email', 'jake.stangl@growthbook.io'
    ).eq('period', 'Q3_FY2027').execute()
    print("  Cleared existing Q3 targets for Jake")
except Exception as e:
    print(f"  Note: Could not clear existing targets: {e}")

for target in targets:
    try:
        result = sb.table('rep_targets').insert(target).execute()
        print(f"  ✓ {target['metric']}: {target['target_value']}")
    except Exception as e:
        print(f"  ✗ {target['metric']}: {e}")

# Verify
print("\nVerifying targets in database:")
verify = sb.table('rep_targets').select('*').eq(
    'entity_email', 'jake.stangl@growthbook.io'
).eq('period', 'Q3_FY2027').execute()

if verify.data:
    print(f"\n✓ Found {len(verify.data)} targets for Jake Stangl in Q3 FY2027:")
    for target in verify.data:
        print(f"  {target['metric']:20} {target['target_value']:3}")
else:
    print("\n✗ No targets found (table may not exist yet)")

print("\n" + "="*80)
print("NEXT STEPS:")
print("="*80)
print("1. Confirm targets with Ryan or Jake's manager")
print("2. Run meetings ETL to populate actual meetings data")
print("3. Test query_sdr_metrics with meetings in progress vs target")
print("="*80 + "\n")
