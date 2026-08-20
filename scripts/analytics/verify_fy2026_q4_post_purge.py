#!/usr/bin/env python3
from dotenv import load_dotenv
load_dotenv()
"""
Re-run FY2026 Q4 week-3 breakdown after purge.

Verify that 182 closedwon and 185 closedlost drop to zero or near-zero.
Report corrected stage composition and denominator.
"""
import os
import sys
import yaml
from collections import Counter

sys.path.insert(0, 'scripts')
from supabase import create_client
from supabase_client import select_all

sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])

# Load config
with open('config/client.yaml') as f:
    config = yaml.safe_load(f)

with open('config/field_semantics.yaml') as f:
    semantics = yaml.safe_load(f)

# Get excluded stages
excluded = config.get('excluded_stages', {})
excluded_stage_ids = set()
for category, stages in excluded.items():
    for stage_def in stages:
        excluded_stage_ids.add(stage_def.get('id'))

print("=" * 80)
print("FY2026 Q4 WEEK-3 POST-PURGE VERIFICATION")
print("=" * 80)

quarter_name = 'FY2026 Q4'

# Get week-3 snapshot
week3_snapshot = select_all(sb, 'deals_snapshot',
                            columns='deal_id, snapshot_date, stage_id, pipeline_id, close_date',
                            filters=[('eq', 'fiscal_quarter', quarter_name),
                                   ('eq', 'week_of_quarter', 3)])

if not week3_snapshot:
    print(f"\n⚠️  No week-3 snapshots found for {quarter_name}")
    sys.exit(1)

week3_date = sorted(set(r['snapshot_date'] for r in week3_snapshot))[0]
print(f"\nWeek-3 snapshot date: {week3_date}")
print(f"Total snapshot rows: {len(week3_snapshot):,}")

# Filter to default pipeline
default_pipeline = [r for r in week3_snapshot
                   if r.get('pipeline_id') == 'default']

print(f"Default pipeline rows: {len(default_pipeline):,}")

# Stage breakdown
stage_map = semantics['stage_map']

def get_stage_label(stage_id):
    if not stage_id:
        return "null"
    stage_id_str = str(stage_id).lower()
    if stage_id_str in stage_map:
        return stage_map[stage_id_str]['label']
    for stage_key, stage_config in stage_map.items():
        aliases = stage_config.get('aliases', [])
        if stage_id_str in [str(a).lower() for a in aliases]:
            return stage_config['label']
    return stage_id

stage_counts = Counter(r.get('stage_id') for r in default_pipeline)

print(f"\n" + "=" * 80)
print("STAGE BREAKDOWN (Post-Purge)")
print("=" * 80)

print(f"\n{'Stage ID':<25} {'Label':<30} {'Count':>10} {'%':>8}")
print("-" * 80)

total = len(default_pipeline)
for stage_id, count in sorted(stage_counts.items(), key=lambda x: -x[1]):
    label = get_stage_label(stage_id)
    pct = (count / total * 100) if total > 0 else 0
    print(f"{str(stage_id):<25} {label:<30} {count:>10,} {pct:>7.1f}%")

print("-" * 80)
print(f"{'TOTAL':<25} {'':<30} {total:>10,} {'100.0':>7}%")

# Check closed deals
closedwon_count = stage_counts.get('closedwon', 0) + stage_counts.get('1297321623', 0)
closedlost_count = stage_counts.get('closedlost', 0) + stage_counts.get('1297321624', 0) + stage_counts.get('68509551', 0)

print(f"\n" + "=" * 80)
print("CLOSED DEALS CHECK")
print("=" * 80)

print(f"\nClosed Won in week-3 snapshot: {closedwon_count}")
print(f"Closed Lost in week-3 snapshot: {closedlost_count}")

if closedwon_count == 0 and closedlost_count == 0:
    print("\n✓ PURGE SUCCESSFUL - No closed deals in open pipeline snapshot")
elif closedwon_count <= 5 and closedlost_count <= 5:
    print(f"\n✓ MOSTLY SUCCESSFUL - Only {closedwon_count + closedlost_count} closed deals remain")
    print("  (May be deals that closed ON the snapshot date)")
else:
    print(f"\n⚠️  {closedwon_count + closedlost_count} closed deals still present")
    print("  Expected 0 or near-0 after purge")

# Exclusion impact
excluded_count = sum(1 for r in default_pipeline
                    if r.get('stage_id') in excluded_stage_ids)
qualified_count = total - excluded_count

print(f"\n" + "=" * 80)
print("DENOMINATOR CALCULATION")
print("=" * 80)

print(f"\nDefault pipeline at week-3: {total:,} deals")
print(f"Excluded stages: {excluded_count:,} deals")
print(f"Qualified open pipeline: {qualified_count:,} deals")

# Comparison
print(f"\n" + "=" * 80)
print("COMPARISON TO PRE-PURGE")
print("=" * 80)

print(f"\nPre-purge (corrupted):")
print(f"  Total: 914 deals")
print(f"  Closed Won: 182")
print(f"  Closed Lost: 185")
print(f"  Excluded: 701 deals")
print(f"  Qualified: 213 deals")

print(f"\nPost-purge (corrected):")
print(f"  Total: {total:,} deals")
print(f"  Closed Won: {closedwon_count}")
print(f"  Closed Lost: {closedlost_count}")
print(f"  Excluded: {excluded_count:,} deals")
print(f"  Qualified: {qualified_count:,} deals")

reduction_pct = ((914 - total) / 914 * 100) if total > 0 else 0
print(f"\nSnapshot size reduction: {reduction_pct:.1f}%")

if closedwon_count + closedlost_count < 20:
    print("\n✓ Snapshot now captures genuinely open pipeline")
    print(f"  Denominator ({qualified_count:,}) is realistic for forecast analysis")
else:
    print(f"\n⚠️  Still {closedwon_count + closedlost_count} closed deals - may need additional investigation")
