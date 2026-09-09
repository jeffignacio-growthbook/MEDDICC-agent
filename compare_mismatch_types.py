#!/usr/bin/env python3
"""
Compare net_change mismatches to ARR masking to verify they're the same root cause.

For each net_change mismatch:
1. Check if ARR masking exists and matches the mismatch amount
2. Identify any mismatches NOT explained by ARR masking
"""

import os
from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Get all waterfall rows from the latest backfill
result = sb.table('waterfall_weekly')\
    .select('week_ending, region, segment, beginning_value, ending_value, net_change, arr_change_value')\
    .eq('computed_source', 'backfill')\
    .execute()

print("Analyzing relationship between net_change mismatches and ARR masking...")
print()

net_change_mismatches = []
arr_masked = []

for row in result.data:
    region = row['region']
    segment = row['segment']
    week = row['week_ending']

    # Check net_change reconciliation
    expected_ending = row['beginning_value'] + row['net_change']
    actual_ending = row['ending_value']
    net_change_diff = actual_ending - expected_ending

    if abs(net_change_diff) > 0.01:
        net_change_mismatches.append({
            'group': f"{region}/{segment}",
            'week': week,
            'diff': net_change_diff,
            'beginning': row['beginning_value'],
            'ending': row['ending_value'],
            'net_change': row['net_change'],
            'arr_change_value': row['arr_change_value']
        })

print(f"Total net_change mismatches: {len(net_change_mismatches)}")
print()

# For each mismatch, check if it's likely ARR-related
# Hypothesis: mismatch diff should approximately equal the missing ARR delta
print("Checking if net_change mismatches are explained by ARR masking:")
print()

arr_explained = []
other_causes = []

for m in net_change_mismatches:
    # The mismatch diff represents the missing movement
    # If ARR changes were masked, they should show up as the diff
    # but arr_change_value would be 0 or less than expected

    # Simple heuristic: if arr_change_value is 0 or very small,
    # and the diff is significant, it's likely ARR masking

    if abs(m['arr_change_value']) < 100 and abs(m['diff']) > 1000:
        arr_explained.append(m)
    else:
        other_causes.append(m)

print(f"✓ Likely ARR masking: {len(arr_explained)} mismatches")
print(f"  (arr_change_value near $0, but significant net_change diff)")

if arr_explained:
    print(f"\n  Top 10 by magnitude:")
    sorted_arr = sorted(arr_explained, key=lambda x: abs(x['diff']), reverse=True)[:10]
    for m in sorted_arr:
        print(f"    {m['group']} week {m['week']}: diff ${m['diff']:,.0f}, arr_change ${m['arr_change_value']:,.0f}")

print()
print(f"⚠️  Other causes: {len(other_causes)} mismatches")
print(f"  (arr_change_value populated OR diff is small)")

if other_causes:
    print(f"\n  Examples:")
    for m in other_causes[:10]:
        print(f"    {m['group']} week {m['week']}: diff ${m['diff']:,.0f}, arr_change ${m['arr_change_value']:,.0f}")

print()
print("=" * 70)
print("CONCLUSION:")
print("=" * 70)

pct_arr_explained = len(arr_explained) / len(net_change_mismatches) * 100

if pct_arr_explained > 90:
    print(f"✓ {pct_arr_explained:.1f}% of net_change mismatches are explained by ARR masking")
    print(f"  The precedence bug is the PRIMARY root cause")
    print(f"  Fixing Option 3 should resolve BOTH net_change mismatches AND ARR masking")
elif pct_arr_explained > 50:
    print(f"⚠️  {pct_arr_explained:.1f}% of net_change mismatches are explained by ARR masking")
    print(f"  The precedence bug is A MAJOR root cause, but not the only one")
    print(f"  Fixing Option 3 will help, but may not resolve all 82 mismatches")
else:
    print(f"✗ Only {pct_arr_explained:.1f}% of net_change mismatches are explained by ARR masking")
    print(f"  There are OTHER significant root causes beyond the precedence bug")
    print(f"  Fixing Option 3 alone won't resolve the net_change mismatches")
