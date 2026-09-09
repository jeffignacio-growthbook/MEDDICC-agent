#!/usr/bin/env python3
"""
Check if ARR masking and net_change issues exist in properly-enriched groups
vs UNKNOWN groups.
"""

import os
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client

sb = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_KEY'))

# Get all backfill rows
result = sb.table('waterfall_weekly')\
    .select('week_ending, region, segment, beginning_value, ending_value, net_change, arr_change_value')\
    .eq('computed_source', 'backfill')\
    .execute()

print('Checking for ARR and net_change issues by group type...')
print()

properly_enriched = []
unknown_groups = []

for row in result.data:
    region = row['region']
    segment = row['segment']

    # Calculate expected ending
    expected_ending = row['beginning_value'] + row['net_change']
    actual_ending = row['ending_value']
    net_change_issue = abs(expected_ending - actual_ending) > 0.01

    # Store result
    group_key = f"{region}/{segment}"

    if region == 'UNKNOWN' or segment == 'Unknown':
        unknown_groups.append({
            'group': group_key,
            'week': row['week_ending'],
            'net_change_issue': net_change_issue,
            'arr_change_value': row.get('arr_change_value', 0)
        })
    else:
        properly_enriched.append({
            'group': group_key,
            'week': row['week_ending'],
            'net_change_issue': net_change_issue,
            'arr_change_value': row.get('arr_change_value', 0)
        })

# Check properly-enriched groups
print(f'PROPERLY-ENRICHED GROUPS (no UNKNOWN in region or segment):')
print(f'  Total rows: {len(properly_enriched)}')

net_issues = [r for r in properly_enriched if r['net_change_issue']]
arr_populated = [r for r in properly_enriched if abs(r['arr_change_value']) > 0.01]

print(f'  Net_change issues: {len(net_issues)}')
print(f'  Rows with non-zero arr_change_value: {len(arr_populated)}')

if net_issues:
    print(f'\n  ✗ PROPERLY-ENRICHED GROUPS HAVE NET_CHANGE ISSUES:')
    for r in net_issues[:5]:
        print(f"    {r['group']} week {r['week']}")
else:
    print(f'  ✓ Zero net_change issues in properly-enriched groups')

if arr_populated:
    print(f'\n  ARR changes captured in properly-enriched groups:')
    from collections import Counter
    by_group = Counter(r['group'] for r in arr_populated)
    for group, count in sorted(by_group.items(), key=lambda x: -x[1])[:10]:
        total_arr = sum(r['arr_change_value'] for r in arr_populated if r['group'] == group)
        print(f'    {group}: {count} weeks, ${total_arr:,.0f} total')

print()
print(f'UNKNOWN GROUPS (UNKNOWN in region or segment):')
print(f'  Total rows: {len(unknown_groups)}')

net_issues_unknown = [r for r in unknown_groups if r['net_change_issue']]
arr_populated_unknown = [r for r in unknown_groups if abs(r['arr_change_value']) > 0.01]

print(f'  Net_change issues: {len(net_issues_unknown)}')
print(f'  Rows with non-zero arr_change_value: {len(arr_populated_unknown)}')

print()
print('=' * 70)
print('CRITICAL QUESTION:')
print('=' * 70)
print('Does arr_change_value > 0 in properly-enriched groups mean:')
print('  A) ARR changes are being captured correctly (no masking), OR')
print('  B) ARR changes are being captured but some are still masked?')
print()
print('Need to check the NEW ARR reconciliation fields to answer this.')
print('The arr_change_value field alone does not tell us about masking.')
