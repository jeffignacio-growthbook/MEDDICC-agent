#!/usr/bin/env python3
"""
Delete old waterfall data and re-run computation
"""

import os
import sys
from pathlib import Path
from supabase import create_client

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

print("Deleting old waterfall data for 2026-08-11...")
sb.table('waterfall_weekly').delete().eq('week_ending', '2026-08-11').execute()
print("✓ Deleted\n")

print("Re-running compute_waterfall.py...\n")
os.chdir(REPO_ROOT)
os.system('python scripts/analytics/compute_waterfall.py')

print("\n\nFetching results...")
result = sb.table('waterfall_weekly')\
    .select('week_ending, pipeline_id, new_pipeline_value, moved_forward_value, moved_backward_value, won_value, lost_value, net_change, deals_created_count')\
    .order('week_ending', desc=True)\
    .limit(4)\
    .execute()

print("\nWaterfall Results:")
print("=" * 120)
print(f"{'Week Ending':<12} {'Pipeline':<10} {'New':<12} {'Fwd':<12} {'Back':<12} {'Won':<12} {'Lost':<12} {'Net':<12} {'Created':<8}")
print("-" * 120)

for row in result.data:
    week = row['week_ending']
    pipe = row['pipeline_id']
    new = row['new_pipeline_value'] or 0
    fwd = row['moved_forward_value'] or 0
    back = row['moved_backward_value'] or 0
    won = row['won_value'] or 0
    lost = row['lost_value'] or 0
    net = row['net_change'] or 0
    created = row['deals_created_count'] or 0

    print(f"{week:<12} {pipe:<10} {new:>11,.0f} {fwd:>11,.0f} {back:>11,.0f} {won:>11,.0f} {lost:>11,.0f} {net:>11,.0f} {created:>8}")

print("=" * 120)
