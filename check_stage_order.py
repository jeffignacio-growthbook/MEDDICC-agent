#!/usr/bin/env python3
"""
Diagnostic: Check stage_order distribution in deals_snapshot
to investigate false moved_backward regression.
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from supabase import create_client
from supabase_client import select_all

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Get all snapshot records for 2026-08-11
rows = select_all(
    sb, 'deals_snapshot',
    'snapshot_source, deal_status, stage_order, deal_value',
    filters=[('eq', 'snapshot_date', '2026-08-11')]
)

# Group and aggregate in Python
from collections import defaultdict

groups = defaultdict(lambda: {'count': 0, 'total_value': 0})

for row in rows:
    key = (
        row.get('snapshot_source'),
        row.get('deal_status'),
        row.get('stage_order')
    )
    groups[key]['count'] += 1
    groups[key]['total_value'] += float(row.get('deal_value') or 0)

# Sort by stage_order (nulls last, then descending)
sorted_groups = sorted(
    groups.items(),
    key=lambda x: (x[0][2] is None, -(x[0][2] or 0))
)

print("Stage Order Distribution in deals_snapshot (2026-08-11):")
print("=" * 80)
print(f"{'Source':<15} {'Status':<10} {'Order':<8} {'Count':<8} {'Total Value':>15}")
print("-" * 80)

for (source, status, order), data in sorted_groups[:20]:
    source_str = (source or 'NULL')[:14]
    status_str = (status or 'NULL')[:9]
    order_str = str(order) if order is not None else 'NULL'
    order_str = order_str[:7]
    count = data['count']
    value = data['total_value']
    print(f"{source_str:<15} {status_str:<10} {order_str:<8} {count:<8} {value:>15,.0f}")

print("-" * 80)
print(f"Total groups: {len(groups)}")
