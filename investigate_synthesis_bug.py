#!/usr/bin/env python3
"""
Investigate why synthesis reported $0 when data showed $120K activity.
Reproduce the exact data the LLM saw and understand the aggregation failure.
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

from supabase_client import select_all

print("=" * 70)
print("SYNTHESIS BUG INVESTIGATION")
print("=" * 70)
print()

# Reproduce the exact query the Slack handler ran
print("Step 1: Initial filter (all regions, date range)")
print("-" * 70)

step_0 = select_all(sb, 'waterfall_weekly',
                   'week_ending,pipeline_id,region,segment,beginning_value,ending_value,' +
                   'new_pipeline_value,won_value,lost_value,net_change,' +
                   'newly_qualified_value,newly_qualified_count,deals_created_count,' +
                   'moved_forward_value,moved_backward_value',
                   filters=[
                       ('gte', 'week_ending', '2026-08-17'),
                       ('lte', 'week_ending', '2026-09-09')
                   ])

print(f"Retrieved {len(step_0)} rows total")
print()

# Show ordering - does the data come back newest-first or oldest-first?
print("Week distribution (to check ordering):")
week_counts = {}
for row in step_0:
    week = row['week_ending']
    week_counts[week] = week_counts.get(week, 0) + 1

for week in sorted(week_counts.keys()):
    print(f"  {week}: {week_counts[week]} rows")

print()
print("First 5 rows as LLM would see them:")
for i, row in enumerate(step_0[:5]):
    print(f"{i+1}. {row['week_ending']} {row['region']:8s} {row['segment']:15s} " +
          f"won=${row.get('won_value', 0):>8,.0f} lost=${row.get('lost_value', 0):>8,.0f}")

print()
print("Last 5 rows as LLM would see them:")
for i, row in enumerate(step_0[-5:]):
    print(f"{len(step_0)-4+i}. {row['week_ending']} {row['region']:8s} {row['segment']:15s} " +
          f"won=${row.get('won_value', 0):>8,.0f} lost=${row.get('lost_value', 0):>8,.0f}")

print()
print("=" * 70)
print("Step 2: EMEA filter")
print("-" * 70)

step_1 = [row for row in step_0 if row['region'] == 'EMEA']
print(f"Filtered to {len(step_1)} EMEA rows")
print()

# Show EMEA rows in order
print("All 20 EMEA rows in order:")
for i, row in enumerate(step_1):
    print(f"{i+1:2d}. {row['week_ending']} {row['segment']:15s} " +
          f"won=${row.get('won_value', 0):>8,.0f} " +
          f"lost=${row.get('lost_value', 0):>8,.0f} " +
          f"new=${row.get('new_pipeline_value', 0):>8,.0f} " +
          f"net=${row.get('net_change', 0):>10,.0f}")

print()
print("=" * 70)
print("AGGREGATION ANALYSIS")
print("=" * 70)

# Calculate what the LLM SHOULD have reported
total_won = sum(row.get('won_value', 0) or 0 for row in step_1)
total_lost = sum(row.get('lost_value', 0) or 0 for row in step_1)
total_new = sum(row.get('new_pipeline_value', 0) or 0 for row in step_1)
total_net = sum(row.get('net_change', 0) or 0 for row in step_1)

print(f"Correct aggregation across all 20 rows:")
print(f"  Total won: ${total_won:,.0f}")
print(f"  Total lost: ${total_lost:,.0f}")
print(f"  Total new pipeline: ${total_new:,.0f}")
print(f"  Total net change: ${total_net:,.0f}")

print()
print("What LLM actually reported:")
print("  Total won: $0")
print("  Total lost: $0")
print("  Total new pipeline: $0")
print("  Total net change: $0")

print()
print("=" * 70)
print("PATTERN ANALYSIS")
print("=" * 70)

# Check if activity is concentrated in specific weeks
activity_by_week = {}
for row in step_1:
    week = row['week_ending']
    if week not in activity_by_week:
        activity_by_week[week] = {'won': 0, 'lost': 0, 'new': 0}

    activity_by_week[week]['won'] += row.get('won_value', 0) or 0
    activity_by_week[week]['lost'] += row.get('lost_value', 0) or 0
    activity_by_week[week]['new'] += row.get('new_pipeline_value', 0) or 0

print("Activity concentrated by week:")
for week in sorted(activity_by_week.keys()):
    act = activity_by_week[week]
    if any(v > 0 for v in act.values()):
        print(f"  {week}: won=${act['won']:,.0f} lost=${act['lost']:,.0f} new=${act['new']:,.0f}")
    else:
        print(f"  {week}: (no activity)")

print()
print("HYPOTHESIS:")
print("  If LLM only looked at most recent weeks (Sep 7-8), it would see $0")
print("  The Aug 28 activity ($20K won, $100K lost) is 'earlier' in the period")
print()
print("  This suggests: LLM anchored on RECENT rows, not ALL rows in range")

print()
print("=" * 70)
print("ROOT CAUSE ANALYSIS")
print("=" * 70)

# Check data format - is this aggregated or sample?
print("From Slack logs:")
print('  [AGGREGATE] 93 rows → aggregates + 20-row sample (20 largest by week_ending)')
print('  [TOOL] filter_table rows=20 error=none')
print()
print("This confirms:")
print("  1. Initial 93 rows were aggregated to 20-row sample")
print("  2. 'largest by week_ending' means MOST RECENT weeks shown")
print("  3. Then filtered to EMEA (20 rows → 20 EMEA rows)")
print()
print("PROBLEM: If aggregation sampled '20 most recent', but there are")
print("multiple weeks with 4-5 segments each, the sample may have")
print("overweighted recent weeks and underweighted Aug 28.")

print()
print("Check: How many segments per week?")
for week in sorted(activity_by_week.keys()):
    week_rows = [r for r in step_1 if r['week_ending'] == week]
    segments = set(r['segment'] for r in week_rows)
    print(f"  {week}: {len(segments)} segments - {', '.join(sorted(segments))}")

print()
print("CONFIRMED ROOT CAUSE:")
print("  Initial aggregation sampled '20 largest by week_ending'")
print("  With 4 segments per week × 5 weeks = 20 rows")
print("  Sample likely took MOST RECENT 20 rows (5 weeks × 4 segments)")
print("  But then synthesis only looked at Sep 7-8 data, missing Aug 28")
print()
print("FIX NEEDED:")
print("  1. Synthesis must explicitly SUM all retrieved rows, not eyeball")
print("  2. Add verification: stated total must match programmatic sum")
print("  3. For time-range questions, ensure aggregation doesn't oversample recent")
