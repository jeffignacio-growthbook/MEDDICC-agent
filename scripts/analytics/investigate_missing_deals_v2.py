#!/usr/bin/env python3
"""
Investigate why deals are missing from snapshots.
Simpler approach: just check characteristics of deals in deals table.
"""
import os
import sys
from datetime import datetime
from collections import Counter
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, 'scripts')
from supabase import create_client
from supabase_client import select_all

sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])

print("=" * 80)
print("SNAPSHOT COVERAGE FAILURE: ROOT CAUSE INVESTIGATION")
print("=" * 80)

# Get FY2026 Q4 week-3 data
quarter = 'FY2026 Q4'
target_date = '2025-11-18'

print(f"\nFocus: {quarter} week-3 ({target_date})")
print(f"Observed: 221 snapshot deals / 830 genuinely open = 26.6% coverage")

# Get all snapshot metadata for this quarter
all_q4_snaps = select_all(sb, 'deals_snapshot',
                          columns='deal_id, snapshot_date, week_of_quarter',
                          filters=[('eq', 'fiscal_quarter', quarter)])

unique_deals_in_q4 = len(set(s['deal_id'] for s in all_q4_snaps))
unique_dates = len(set(s['snapshot_date'] for s in all_q4_snaps))
total_snapshot_rows = len(all_q4_snaps)

print(f"\n{quarter} Snapshot Metadata:")
print(f"  Total snapshot rows: {total_snapshot_rows:,}")
print(f"  Unique snapshot dates: {unique_dates}")
print(f"  Unique deals captured: {unique_deals_in_q4:,}")

# Check row counts per snapshot date
from collections import defaultdict
rows_per_date = Counter(s['snapshot_date'] for s in all_q4_snaps)

print(f"\n  Rows per snapshot date:")
for date in sorted(rows_per_date.keys())[:5]:
    print(f"    {date}: {rows_per_date[date]:,} rows")
print(f"  ... ({unique_dates} dates total)")

print(f"\n{'='*80}")
print("HYPOTHESIS 1: Row Cap or Pagination")
print(f"{'='*80}")

# Check if there's a consistent cap
row_counts = sorted(rows_per_date.values())
print(f"\nRow count distribution across all snapshot dates:")
print(f"  Min: {min(row_counts)}")
print(f"  Max: {max(row_counts)}")
print(f"  Median: {row_counts[len(row_counts)//2]}")

if max(row_counts) < 300:
    print(f"\n⚠️  MAX ROW COUNT: {max(row_counts)}")
    print(f"  This is suspiciously low for a sales pipeline")
    print(f"  Likely cause: Row limit in backfill or pagination failure")

print(f"\n{'='*80}")
print("HYPOTHESIS 2: Systematic Exclusion")
print(f"{'='*80}")

# Get deals table count
deals = select_all(sb, 'deals', columns='deal_id, pipeline_id')
default_pipeline_deals = [d for d in deals if d.get('pipeline_id') == 'default']

print(f"\nDeals table (current state):")
print(f"  Total deals: {len(deals):,}")
print(f"  Default pipeline: {len(default_pipeline_deals):,}")

print(f"\nComparison:")
print(f"  Deals in {quarter} snapshots: {unique_deals_in_q4:,}")
print(f"  Default pipeline deals (current): {len(default_pipeline_deals):,}")
print(f"  Coverage: {unique_deals_in_q4/len(default_pipeline_deals)*100:.1f}%")

if unique_deals_in_q4 < len(default_pipeline_deals) * 0.5:
    print(f"\n⚠️  Less than 50% of current default pipeline deals appear in Q4 snapshots")
    print(f"  Systematic exclusion likely")

print(f"\n{'='*80}")
print("HYPOTHESIS 3: Backfill Date Range")
print(f"{'='*80}")

# Check create_date distribution of deals never in snapshots
never_snapshot_deals = []
for deal in default_pipeline_deals:
    if not any(s['deal_id'] == deal['deal_id'] for s in all_q4_snaps):
        never_snapshot_deals.append(deal)

print(f"\nDefault pipeline deals never in {quarter} snapshots: {len(never_snapshot_deals):,}")

# Sample and get create dates
sample_size = min(200, len(never_snapshot_deals))
sample_never = never_snapshot_deals[:sample_size]

# Get create dates for sample
never_snap_sample_with_dates = select_all(sb, 'deals',
                                          columns='deal_id, create_date',
                                          filters=[('in', 'deal_id', 
                                                   ','.join(d['deal_id'] for d in sample_never[:50]))])

creates = [datetime.fromisoformat(d['create_date']).date() 
           for d in never_snap_sample_with_dates if d.get('create_date')]

if creates:
    print(f"\nCreate date range of deals never in snapshot (sample of {len(creates)}):")
    print(f"  Earliest: {min(creates)}")
    print(f"  Latest: {max(creates)}")
    print(f"  Before {target_date}: {sum(1 for d in creates if d <= datetime.fromisoformat(target_date).date())}")

print(f"\n{'='*80}")
print("ROOT CAUSE ASSESSMENT")
print(f"{'='*80}")

print(f"\nEvidence:")
print(f"  1. Only {unique_deals_in_q4:,} unique deals in {quarter} snapshots")
print(f"  2. {len(default_pipeline_deals):,} deals currently in default pipeline")
print(f"  3. Max {max(row_counts)} rows per snapshot date")
print(f"  4. 26.6% coverage at week-3 (221 of 830 open deals)")

print(f"\nLikely cause:")
if max(row_counts) < 300:
    print(f"  ✗ ROW LIMIT in backfill: {max(row_counts)} rows cap")
    print(f"    Check snapshot_deals.py for .limit() calls")
    print(f"    Check HubSpot API client for default page_size")
elif unique_deals_in_q4 < 500:
    print(f"  ✗ SYSTEMATIC EXCLUSION: Too few deals captured")
    print(f"    Original backfill likely had overly restrictive filters")
else:
    print(f"  ✗ INCOMPLETE BACKFILL: Missing large portion of pipeline")

print(f"\nRecovery path:")
print(f"  1. Review snapshot_deals.py for row limits")
print(f"  2. Re-run backfill with fixed inclusion rule (no limits)")
print(f"  3. Verify against genuinely_open calculation")
print(f"  4. Re-measure coverage to confirm ≥80%")

