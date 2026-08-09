#!/usr/bin/env python3
"""
Verification script for Phase A analytics layer.
Compares get_excluded_stages() output with new config vs legacy config.
"""

import sys
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent / 'scripts'))

from etl_deals import get_excluded_stages

print("=" * 80)
print("PHASE A VERIFICATION: get_excluded_stages() output")
print("=" * 80)

excluded = get_excluded_stages()

print("\nExcluded Stages Dictionary:")
print("-" * 80)

print(f"\nMeeting Set stages:")
for stage_id in excluded['meeting_set']:
    print(f"  - {stage_id}")

print(f"\nDisqualified stages:")
for stage_id in excluded['disqualified']:
    print(f"  - {stage_id}")

print(f"\nClosed Won stages:")
for stage_id in excluded['closed_won']:
    print(f"  - {stage_id}")

print(f"\nClosed Lost stages:")
for stage_id in excluded['closed_lost']:
    print(f"  - {stage_id}")

print(f"\nExcluded Pipelines:")
for pipeline_id in excluded['excluded_pipelines']:
    print(f"  - {pipeline_id}")

print("\n" + "=" * 80)
print("EXPECTED (from legacy config):")
print("=" * 80)
print("\nMeeting Set: ['79653122']")
print("Disqualified: ['68509551']")
print("Closed Won: ['closedwon', '1297321623']")
print("Closed Lost: ['closedlost', '1297321624']")
print("Excluded Pipelines: ['866608541']")

print("\n" + "=" * 80)
print("VERIFICATION:")
print("=" * 80)

expected = {
    'meeting_set': ['79653122'],
    'disqualified': ['68509551'],
    'closed_won': ['closedwon', '1297321623'],
    'closed_lost': ['closedlost', '1297321624'],
    'excluded_pipelines': ['866608541'],
}

all_match = True
for key in expected.keys():
    actual_set = set(excluded[key])
    expected_set = set(expected[key])
    if actual_set == expected_set:
        print(f"✓ {key}: MATCH")
    else:
        print(f"✗ {key}: MISMATCH")
        print(f"  Expected: {expected_set}")
        print(f"  Actual: {actual_set}")
        all_match = False

print("\n" + "=" * 80)
if all_match:
    print("✓ ALL CHECKS PASSED - Config equivalence verified")
    print("  New pipeline.pipelines[] config produces identical output to legacy config")
else:
    print("✗ VERIFICATION FAILED - Outputs do not match")
    sys.exit(1)
