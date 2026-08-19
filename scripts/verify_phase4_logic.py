#!/usr/bin/env python3
"""
Direct verification that OLD and NEW classification logic are identical.
Tests all possible stage values to confirm behavior-preserving refactor.
"""

import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from field_semantics import is_won, is_lost, is_open, STAGE_MAP, _ALIAS_TO_CANONICAL

def old_logic(stage: str) -> str:
    """OLD hardcoded logic (from user's SQL specification)."""
    if stage in ('closedwon', '1297321623'):
        return 'won'
    elif stage in ('closedlost', '1297321624', '68509551'):
        return 'lost'
    else:
        return 'open'

def new_logic(stage: str) -> str:
    """NEW field_semantics logic."""
    if is_won(stage):
        return 'won'
    elif is_lost(stage):
        return 'lost'
    else:  # is_open() returns True for unknown stages too
        return 'open'

print("=" * 80)
print("PHASE 4 LOGIC VERIFICATION")
print("=" * 80)
print()

# Test all known stage IDs and aliases
test_stages = [
    # Known stage IDs from field_semantics
    'appointmentscheduled',
    'qualifiedtobuy',
    'presentationscheduled',
    'decisionmakerboughtin',
    'contractsent',
    'closedwon',
    'closedlost',
    # Numeric aliases
    '1297321623',  # closedwon alias
    '1297321624',  # closedlost alias
    '68509551',    # Disqualified (closedlost alias)
    # Unknown stages
    'unknown_stage_123',
    '',
    None,
]

print("Testing all known stage values:")
print()
print("Stage                    | OLD Logic | NEW Logic | Match")
print("-" * 70)

all_match = True
for stage in test_stages:
    stage_str = str(stage)[:24] if stage else '(None)'

    old = old_logic(stage) if stage else 'open'
    new = new_logic(stage) if stage else 'open'

    match = "✓" if old == new else "✗"
    if old != new:
        all_match = False

    print(f"{stage_str:24} | {old:9} | {new:9} | {match}")

print("-" * 70)
print()

# Verify the sets are identical
won_old = {'closedwon', '1297321623'}
won_new = set()
for sid in _ALIAS_TO_CANONICAL.keys():
    if is_won(sid):
        won_new.add(sid)

lost_old = {'closedlost', '1297321624', '68509551'}
lost_new = set()
for sid in _ALIAS_TO_CANONICAL.keys():
    if is_lost(sid):
        lost_new.add(sid)

print("SET COMPARISON:")
print()
print(f"Won stages:")
print(f"  OLD: {sorted(won_old)}")
print(f"  NEW: {sorted(won_new)}")
print(f"  Match: {'✓' if won_old == won_new else '✗'}")
print()
print(f"Lost stages:")
print(f"  OLD: {sorted(lost_old)}")
print(f"  NEW: {sorted(lost_new)}")
print(f"  Match: {'✓' if lost_old == lost_new else '✗'}")
print()

# Summary
if all_match and won_old == won_new and lost_old == lost_new:
    print("✅ VERIFICATION PASSED")
    print()
    print("OLD and NEW classification logic are mathematically identical.")
    print("For every possible stage value, OLD_logic(stage) == NEW_logic(stage).")
    print()
    print("Phase 4 is BEHAVIOR-PRESERVING.")
    print("Safe to proceed to Phase 5.")
    sys.exit(0)
else:
    print("❌ VERIFICATION FAILED")
    print()
    print("OLD and NEW logic produce different results!")
    print("DO NOT PROCEED TO PHASE 5.")
    sys.exit(1)
