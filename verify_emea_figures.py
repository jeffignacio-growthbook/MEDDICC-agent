#!/usr/bin/env python3
"""
Verify exact EMEA figures for "last 2 weeks" from Sept 9.
Reconcile $120K vs $195K discrepancy.
"""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

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
print("VERIFY EXACT EMEA FIGURES")
print("=" * 70)
print()

# Define "last 2 weeks" from Sept 9
query_date = datetime(2026, 9, 9)
two_weeks_ago = query_date - timedelta(days=14)

print(f"Query date: {query_date.date()}")
print(f"Last 2 weeks = {two_weeks_ago.date()} to {query_date.date()}")
print(f"Date range: Aug 26 - Sep 9")
print()

# Get EMEA waterfall rows
waterfall_emea = select_all(sb, 'waterfall_weekly', '*',
                            filters=[
                                ('eq', 'region', 'EMEA'),
                                ('gte', 'week_ending', '2026-08-17'),
                                ('lte', 'week_ending', '2026-09-09')
                            ])

print("All EMEA waterfall rows in period:")
print("-" * 70)

for row in sorted(waterfall_emea, key=lambda x: x['week_ending']):
    week = row['week_ending']
    segment = row['segment']
    won = row.get('won_value', 0) or 0
    lost = row.get('lost_value', 0) or 0
    new = row.get('new_pipeline_value', 0) or 0

    # Check if this week falls in "last 2 weeks" window
    week_date = datetime.strptime(week, '%Y-%m-%d')
    in_window = week_date >= two_weeks_ago

    marker = "← IN WINDOW" if in_window else ""
    print(f"{week} {segment:15s} won=${won:>8,.0f} lost=${lost:>8,.0f} new=${new:>8,.0f} {marker}")

print()
print("=" * 70)
print("AGGREGATION BY DATE RANGE")
print("=" * 70)

# Calculate for different interpretations
full_period = [r for r in waterfall_emea]
last_two_weeks = [r for r in waterfall_emea if datetime.strptime(r['week_ending'], '%Y-%m-%d') >= two_weeks_ago]

def sum_movements(rows):
    return {
        'won': sum(r.get('won_value', 0) or 0 for r in rows),
        'lost': sum(r.get('lost_value', 0) or 0 for r in rows),
        'new': sum(r.get('new_pipeline_value', 0) or 0 for r in rows)
    }

full = sum_movements(full_period)
window = sum_movements(last_two_weeks)

print("Full period (Aug 17 - Sep 9):")
print(f"  Won: ${full['won']:,.0f}")
print(f"  Lost: ${full['lost']:,.0f}")
print(f"  New: ${full['new']:,.0f}")
print(f"  Total activity: ${full['won'] + full['lost'] + full['new']:,.0f}")

print()
print("'Last 2 weeks' window (Aug 26 - Sep 9):")
print(f"  Won: ${window['won']:,.0f}")
print(f"  Lost: ${window['lost']:,.0f}")
print(f"  New: ${window['new']:,.0f}")
print(f"  Total activity: ${window['won'] + window['lost'] + window['new']:,.0f}")

print()
print("=" * 70)
print("RECONCILIATION")
print("=" * 70)

print("First report said: $120K ($20K won, $100K lost)")
print("Second report said: $195K ($20K won, $175K lost)")
print()

if window['won'] == 20000 and window['lost'] == 100000:
    print("✓ FIRST REPORT CORRECT: $120K")
    print("  Matches 'last 2 weeks' window (Aug 26 - Sep 9)")
    print("  Includes only Aug 28 activity")
elif full['won'] == 20000 and full['lost'] == 175000:
    print("✓ SECOND REPORT CORRECT: $195K")
    print("  Matches full period (Aug 17 - Sep 9)")
    print("  Includes Aug 17 ($75K lost) + Aug 28 ($20K won, $100K lost)")
else:
    print("✗ Neither report matches data exactly")

print()
print("CORRECT FIGURE FOR 'LAST 2 WEEKS' (Aug 26 - Sep 9):")
print(f"  Won: ${window['won']:,.0f}")
print(f"  Lost: ${window['lost']:,.0f}")
print(f"  Total: ${window['won'] + window['lost']:,.0f}")

print()
print("NOTE: Aug 17 activity ($75K lost) falls OUTSIDE 'last 2 weeks'")
print("Should use $120K figure, not $195K")
