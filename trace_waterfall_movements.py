#!/usr/bin/env python3
"""
Trace actual waterfall movements computed for the 2 mismatch cases.
Compare what the waterfall says happened vs what actually happened.
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

print("Tracing waterfall movements for 2 mismatch cases")
print("=" * 70)

# Case 1: default/ROW/SMB week 2026-04-13
print("\nCase 1: default/ROW/SMB week 2026-04-13")
print("-" * 70)

waterfall_1 = select_all(sb, 'waterfall_weekly', '*',
                         filters=[
                             ('eq', 'week_ending', '2026-04-13'),
                             ('eq', 'region', 'ROW'),
                             ('eq', 'segment', 'SMB')
                         ])

if waterfall_1:
    wf = waterfall_1[0]
    print(f"Beginning value: ${wf['beginning_value']:,.2f}")
    print(f"Ending value: ${wf['ending_value']:,.2f}")
    print(f"\nMovements recorded:")
    print(f"  New pipeline: ${wf.get('new_pipeline_value', 0):,.2f}")
    print(f"  Newly qualified: ${wf.get('newly_qualified_value', 0):,.2f}")
    print(f"  Newly ARR-bearing: ${wf.get('newly_arr_bearing_value', 0):,.2f}")
    print(f"  Won: ${wf.get('won_value', 0):,.2f}")
    print(f"  Lost: ${wf.get('lost_value', 0):,.2f}")
    print(f"  ARR change: ${wf.get('arr_change_value', 0):,.2f}")
    print(f"  Pulled in: ${wf.get('pulled_in_value', 0):,.2f}")
    print(f"  Pushed out: ${wf.get('pushed_out_value', 0):,.2f}")
    print(f"  Moved forward: ${wf.get('moved_forward_value', 0):,.2f}")
    print(f"  Moved backward: ${wf.get('moved_backward_value', 0):,.2f}")

    print(f"\nNet change: ${wf['net_change']:,.2f}")

    # Calculate expected ending
    expected_ending = wf['beginning_value'] + wf['net_change']
    actual_ending = wf['ending_value']
    diff = actual_ending - expected_ending

    print(f"\nReconciliation:")
    print(f"  Beginning + Net change = Expected ending: ${expected_ending:,.2f}")
    print(f"  Actual ending: ${actual_ending:,.2f}")
    print(f"  Difference: ${diff:,.2f}")
else:
    print("No waterfall row found")

print("\n" + "=" * 70)
print()

# Case 2: default/EMEA/Mid-Market week 2026-05-25
print("Case 2: default/EMEA/Mid-Market week 2026-05-25")
print("-" * 70)

waterfall_2 = select_all(sb, 'waterfall_weekly', '*',
                         filters=[
                             ('eq', 'week_ending', '2026-05-25'),
                             ('eq', 'region', 'EMEA'),
                             ('eq', 'segment', 'Mid-Market')
                         ])

if waterfall_2:
    wf = waterfall_2[0]
    print(f"Beginning value: ${wf['beginning_value']:,.2f}")
    print(f"Ending value: ${wf['ending_value']:,.2f}")
    print(f"\nMovements recorded:")
    print(f"  New pipeline: ${wf.get('new_pipeline_value', 0):,.2f}")
    print(f"  Newly qualified: ${wf.get('newly_qualified_value', 0):,.2f}")
    print(f"  Newly ARR-bearing: ${wf.get('newly_arr_bearing_value', 0):,.2f}")
    print(f"  Won: ${wf.get('won_value', 0):,.2f}")
    print(f"  Lost: ${wf.get('lost_value', 0):,.2f}")
    print(f"  ARR change: ${wf.get('arr_change_value', 0):,.2f}")
    print(f"  Pulled in: ${wf.get('pulled_in_value', 0):,.2f}")
    print(f"  Pushed out: ${wf.get('pushed_out_value', 0):,.2f}")
    print(f"  Moved forward: ${wf.get('moved_forward_value', 0):,.2f}")
    print(f"  Moved backward: ${wf.get('moved_backward_value', 0):,.2f}")

    print(f"\nNet change: ${wf['net_change']:,.2f}")

    # Calculate expected ending
    expected_ending = wf['beginning_value'] + wf['net_change']
    actual_ending = wf['ending_value']
    diff = actual_ending - expected_ending

    print(f"\nReconciliation:")
    print(f"  Beginning + Net change = Expected ending: ${expected_ending:,.2f}")
    print(f"  Actual ending: ${actual_ending:,.2f}")
    print(f"  Difference: ${diff:,.2f}")
else:
    print("No waterfall row found")

print("\n" + "=" * 70)
print("ANALYSIS")
print("=" * 70)
print("Check if deals that exited the group are being tracked as movements")
print("or if they're silently disappearing (boundary crossing issue)")
