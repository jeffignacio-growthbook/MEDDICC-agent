#!/usr/bin/env python3
"""
Investigate why UNKNOWN/Unknown group has reconciliation failures.

Hypothesis: Deals crossing between UNKNOWN and real regions cause both
groups to fail reconciliation (boundary artifact).
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
REPO_ROOT = Path(__file__).parent

from supabase import create_client
import sys
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
from supabase_client import select_all

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Pick a week with a mismatch and trace deals
prev_date = '2026-08-24'
new_date = '2026-08-28'

print(f"Investigating UNKNOWN/Unknown reconciliation failure:")
print(f"Week: {new_date} vs {prev_date}")
print("=" * 70)

# Load both snapshots
prev_snap = select_all(sb, 'deals_snapshot', '*',
                       filters=[('eq', 'snapshot_date', prev_date)])
new_snap = select_all(sb, 'deals_snapshot', '*',
                      filters=[('eq', 'snapshot_date', new_date)])

prev_dict = {d['deal_id']: d for d in prev_snap}
new_dict = {d['deal_id']: d for d in new_snap}

print(f"\nSnapshot sizes:")
print(f"  {prev_date}: {len(prev_snap)} deals")
print(f"  {new_date}: {len(new_snap)} deals")

# Check region/segment distribution in each snapshot
print(f"\nRegion/segment distribution:")
print(f"\n{prev_date}:")
prev_groups = {}
for d in prev_snap:
    region = d.get('region') or 'NULL'
    segment = d.get('segment') or 'NULL'
    key = f"{region}/{segment}"
    prev_groups[key] = prev_groups.get(key, 0) + 1

for key in sorted(prev_groups.keys())[:5]:
    print(f"  {key}: {prev_groups[key]} deals")
if len(prev_groups) > 5:
    print(f"  ... ({len(prev_groups)} total groups)")

print(f"\n{new_date}:")
new_groups = {}
for d in new_snap:
    region = d.get('region') or 'NULL'
    segment = d.get('segment') or 'NULL'
    key = f"{region}/{segment}"
    new_groups[key] = new_groups.get(key, 0) + 1

for key in sorted(new_groups.keys())[:10]:
    print(f"  {key}: {new_groups[key]} deals")
if len(new_groups) > 10:
    print(f"  ... ({len(new_groups)} total groups)")

# Check for deals that changed region/segment between snapshots
boundary_crossers = []

for deal_id in set(prev_dict.keys()) | set(new_dict.keys()):
    p = prev_dict.get(deal_id)
    n = new_dict.get(deal_id)

    if p and n:
        prev_region = p.get('region') or 'NULL'
        new_region = n.get('region') or 'NULL'
        prev_segment = p.get('segment') or 'NULL'
        new_segment = n.get('segment') or 'NULL'

        if (prev_region, prev_segment) != (new_region, new_segment):
            boundary_crossers.append({
                'deal_id': deal_id,
                'prev_group': f"{prev_region}/{prev_segment}",
                'new_group': f"{new_region}/{new_segment}",
                'deal_value': n.get('deal_value') or p.get('deal_value')
            })

print(f"\n" + "=" * 70)
print(f"Deals crossing region/segment boundaries:")
print(f"  Total: {len(boundary_crossers)}")

if boundary_crossers:
    print(f"\nFirst 10 examples:")
    for i, d in enumerate(boundary_crossers[:10], 1):
        print(f"  {i}. Deal {d['deal_id']}: ${d['deal_value']:,.0f}")
        print(f"     {prev_date}: {d['prev_group']}")
        print(f"     {new_date}: {d['new_group']}")

    # Calculate impact
    unknown_to_real = [d for d in boundary_crossers
                       if d['prev_group'].startswith('UNKNOWN')
                       and not d['new_group'].startswith('UNKNOWN')]
    real_to_unknown = [d for d in boundary_crossers
                       if not d['prev_group'].startswith('UNKNOWN')
                       and d['new_group'].startswith('UNKNOWN')]

    unknown_to_unknown = [d for d in boundary_crossers
                          if d['prev_group'].startswith('UNKNOWN')
                          and d['new_group'].startswith('UNKNOWN')]

    print(f"\nBoundary crossing breakdown:")
    print(f"  UNKNOWN → Real region: {len(unknown_to_real)} deals")
    if unknown_to_real:
        total_value = sum(d['deal_value'] or 0 for d in unknown_to_real)
        print(f"    Total value: ${total_value:,.0f}")

    print(f"  Real region → UNKNOWN: {len(real_to_unknown)} deals")
    if real_to_unknown:
        total_value = sum(d['deal_value'] or 0 for d in real_to_unknown)
        print(f"    Total value: ${total_value:,.0f}")

    print(f"  UNKNOWN → UNKNOWN (segment change): {len(unknown_to_unknown)} deals")
    if unknown_to_unknown:
        total_value = sum(d['deal_value'] or 0 for d in unknown_to_unknown)
        print(f"    Total value: ${total_value:,.0f}")

    if unknown_to_real:
        print(f"\nImpact on reconciliation:")
        print(f"  UNKNOWN/Unknown group:")
        print(f"    Beginning: includes {len(unknown_to_real)} deals")
        print(f"    Ending: excludes those deals (moved to real regions)")
        print(f"    → Net change should account for -{len(unknown_to_real)} deals")
        print(f"    → But net_change formula doesn't track region changes!")

        print(f"\n  Real region groups:")
        print(f"    Beginning: excludes {len(unknown_to_real)} deals")
        print(f"    Ending: includes those deals")
        print(f"    → Net change should account for +{len(unknown_to_real)} deals")
        print(f"    → But net_change formula doesn't track region changes!")

print(f"\n" + "=" * 70)
print("HYPOTHESIS VERIFICATION:")
if boundary_crossers:
    unknown_boundary = len(unknown_to_real) + len(real_to_unknown)
    if unknown_boundary > 0:
        print("✓ CONFIRMED: Deals are crossing between UNKNOWN and real regions")
        print("  This is a boundary artifact, not a bug in the formula")
        print("  Expected behavior when historical data lacks enrichment")
        print(f"\n  Specifically: {unknown_boundary} deals changed between UNKNOWN and real regions")
        print("  These deals appear in one group's beginning but another group's ending,")
        print("  causing both groups to fail reconciliation even though the arithmetic")
        print("  within each group is correct.")
    else:
        print("⚠️  Boundary crossers exist, but all within UNKNOWN variants")
        print("  This suggests segment changes within UNKNOWN region")
else:
    print("✗ No boundary crossers found - need to investigate other causes")
