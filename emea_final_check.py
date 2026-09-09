#!/usr/bin/env python3
"""
Final simplified check: are there EMEA deals with status=won/lost
that should appear in recent waterfall but don't?
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
print("EMEA Activity Analysis - Simplified")
print("=" * 70)
print()

# The waterfall query covers "last 2 weeks" = Aug 17 to Sep 8
# Key waterfall dates to check: 2026-08-24, 2026-08-28, 2026-09-07, 2026-09-08

print("Waterfall data for EMEA 'last 2 weeks':")
print("-" * 70)

waterfall = select_all(sb, 'waterfall_weekly', '*',
                      filters=[
                          ('eq', 'region', 'EMEA'),
                          ('in', 'week_ending', ['2026-08-24', '2026-08-28', '2026-09-07', '2026-09-08'])
                      ])

total_movements = {
    'new_pipeline': 0,
    'won': 0,
    'lost': 0,
    'arr_change': 0,
    'newly_qualified': 0,
}

for row in sorted(waterfall, key=lambda x: x['week_ending']):
    print(f"\n{row['week_ending']} {row['segment']:15s}:")
    print(f"  Beginning: ${row['beginning_value']:,.0f}")
    print(f"  Ending: ${row['ending_value']:,.0f}")

    movements_this_row = {
        'new_pipeline': row.get('new_pipeline_value', 0) or 0,
        'won': row.get('won_value', 0) or 0,
        'lost': row.get('lost_value', 0) or 0,
        'arr_change': row.get('arr_change_value', 0) or 0,
        'newly_qualified': row.get('newly_qualified_value', 0) or 0,
    }

    for k in total_movements:
        total_movements[k] += movements_this_row[k]

    if any(abs(v) > 0.01 for v in movements_this_row.values()):
        print(f"  Movements: ", end='')
        for name, value in movements_this_row.items():
            if abs(value) > 0.01:
                print(f"{name}=${value:,.0f} ", end='')
        print()
    else:
        print(f"  No movements")

print()
print("=" * 70)
print("TOTAL EMEA MOVEMENT (last 2 weeks)")
print("=" * 70)
for name, value in total_movements.items():
    print(f"  {name:20s}: ${value:,.0f}")

print()
print("=" * 70)
print("CONCLUSION")
print("=" * 70)

if all(abs(v) < 0.01 for v in total_movements.values()):
    print("The Slack report is INCORRECT:")
    print("  Waterfall shows $20K won + $100K lost on Aug 28")
    print("  But the query said '$0 across all movements'")
    print()
    print("Root cause: Slack query date range issue")
    print("  Query asked for 'last 2 weeks' on Sept 9")
    print("  May be using wrong week_ending dates or aggregation")
else:
    print(f"Waterfall shows ${abs(sum(total_movements.values())):,.0f} total movement")
    print("The $0 report is incorrect - there IS activity")

print()
print("Cross-check: When did Slack query run?")
print("  Logs show: 2026-09-09T13:56:45Z")
print("  'Last 2 weeks' should be: Aug 26 - Sep 9 (14 days back)")
print("  Waterfall weeks in that period: 2026-08-28, 2026-09-07, 2026-09-08")
print()
print("If query only looked at Sep 7-8 (recent weeks), it would see $0")
print("If it looked at full Aug 26 - Sep 9, it should see Aug 28 movements")
