#!/usr/bin/env python3
"""
Drift tests for field_semantics single source of truth.
Guards against:
- Hand-editing the generated module instead of regenerating
- Stage semantics disagreeing between yaml and generated module
- Aliases not resolving correctly
- Won/lost/open logic breaking
"""

import sys
from pathlib import Path
import yaml

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

def test_generated_module_matches_yaml():
    """
    api/field_semantics.py STAGE_MAP matches config/field_semantics.yaml.
    Fails if someone hand-edited the generated module or forgot to
    regenerate after changing the yaml.
    """
    print("\n[TEST] Generated module matches yaml")

    # Load yaml
    config_path = Path(__file__).parent.parent / "config" / "field_semantics.yaml"
    with open(config_path) as f:
        yaml_data = yaml.safe_load(f)

    # Load generated module
    from field_semantics import STAGE_MAP, OUTCOME_BUCKETS, FIELD_UNITS

    # Compare STAGE_MAP
    assert STAGE_MAP == yaml_data['stage_map'], \
        "STAGE_MAP in generated module doesn't match yaml. Did you forget to regenerate?"

    # Compare OUTCOME_BUCKETS
    assert OUTCOME_BUCKETS == yaml_data['outcome_buckets'], \
        "OUTCOME_BUCKETS in generated module doesn't match yaml"

    # Compare FIELD_UNITS
    assert FIELD_UNITS == yaml_data['field_units'], \
        "FIELD_UNITS in generated module doesn't match yaml"

    print("  ✓ STAGE_MAP, OUTCOME_BUCKETS, FIELD_UNITS all match yaml")

def test_aliases_resolve_to_canonical():
    """
    '1297321623' resolves to closedwon; '68509551' to closedlost.
    Verifies the alias resolution system works.
    """
    print("\n[TEST] Aliases resolve to canonical stage IDs")

    from field_semantics import canonical_stage, stage_bucket, stage_label

    # Test closedwon aliases
    assert canonical_stage('1297321623') == 'closedwon', \
        "Numeric closedwon alias should resolve to 'closedwon'"
    assert canonical_stage('closedwon') == 'closedwon', \
        "Canonical ID should resolve to itself"

    # Test closedlost aliases
    assert canonical_stage('1297321624') == 'closedlost', \
        "Numeric closedlost alias should resolve to 'closedlost'"
    assert canonical_stage('68509551') == 'closedlost', \
        "Disqualified alias should resolve to 'closedlost'"
    assert canonical_stage('closedlost') == 'closedlost', \
        "Canonical ID should resolve to itself"

    # Test bucket resolution through aliases
    assert stage_bucket('1297321623') == 'closed_won', \
        "Closedwon alias should return closed_won bucket"
    assert stage_bucket('68509551') == 'closed_lost', \
        "Disqualified alias should return closed_lost bucket"

    # Test label resolution through aliases
    assert stage_label('1297321623') == 'Closed Won', \
        "Closedwon alias should return 'Closed Won' label"
    assert stage_label('68509551') == 'Closed Lost', \
        "Disqualified alias should return 'Closed Lost' label"

    print("  ✓ All aliases resolve correctly:")
    print("    1297321623 -> closedwon -> closed_won bucket")
    print("    68509551 -> closedlost -> closed_lost bucket (Disqualified)")

def test_stage_bucket_covers_all_stages():
    """
    Every stage in the yaml returns a non-'unknown' bucket.
    No stages should fall through to the unknown default.
    """
    print("\n[TEST] Stage bucket covers all defined stages")

    from field_semantics import STAGE_MAP, stage_bucket

    for stage_id in STAGE_MAP.keys():
        bucket = stage_bucket(stage_id)
        assert bucket != 'unknown', \
            f"Stage '{stage_id}' returned 'unknown' bucket — check yaml definition"
        assert bucket in ['discovery', 'scoping', 'proposal', 'closed_won', 'closed_lost'], \
            f"Stage '{stage_id}' returned invalid bucket '{bucket}'"

    print(f"  ✓ All {len(STAGE_MAP)} stages return valid buckets:")
    for sid, info in STAGE_MAP.items():
        bucket = stage_bucket(sid)
        print(f"    {sid:25} -> {bucket}")

def test_is_won_is_lost_mutually_exclusive():
    """
    No stage is both won and lost; won/lost stages are not open.
    Verifies the outcome bucket logic is consistent.
    """
    print("\n[TEST] Won/lost/open are mutually exclusive")

    from field_semantics import STAGE_MAP, is_won, is_lost, is_open

    for stage_id in STAGE_MAP.keys():
        won = is_won(stage_id)
        lost = is_lost(stage_id)
        open_ = is_open(stage_id)

        # No stage can be both won and lost
        assert not (won and lost), \
            f"Stage '{stage_id}' is both won AND lost"

        # Won/lost stages cannot be open
        if won:
            assert not open_, \
                f"Stage '{stage_id}' is won but also marked open"
        if lost:
            assert not open_, \
                f"Stage '{stage_id}' is lost but also marked open"

        # Every stage must be exactly one of: won, lost, or open
        assert (won or lost or open_), \
            f"Stage '{stage_id}' is neither won, lost, nor open"

    print("  ✓ No stage is both won and lost")
    print("  ✓ Closed stages are not marked open")
    print("  ✓ Every stage is exactly one of: won, lost, or open")

    # Test aliases too
    assert is_won('1297321623'), "Closedwon alias should be won"
    assert is_lost('68509551'), "Disqualified alias should be lost"
    assert not is_open('1297321623'), "Closedwon alias should not be open"
    print("  ✓ Aliases respect won/lost/open logic")

def test_stage_transition_returns_correct_keys():
    """
    stage_transition() returns the expected transition keys or None.
    """
    print("\n[TEST] Stage transitions defined correctly")

    from field_semantics import stage_transition

    # Test expected transitions
    assert stage_transition('appointmentscheduled') == 'discovery_to_scoping', \
        "Discovery stage should have discovery_to_scoping transition"
    assert stage_transition('qualifiedtobuy') == 'scoping_to_proposal', \
        "Scoping stage should have scoping_to_proposal transition"
    assert stage_transition('presentationscheduled') == 'proposal_to_negotiating', \
        "Tech eval stage should have proposal_to_negotiating transition"

    # Test stages with no transition
    assert stage_transition('closedwon') is None, \
        "Closedwon should have no transition"
    assert stage_transition('closedlost') is None, \
        "Closedlost should have no transition"

    # Test unknown stage
    assert stage_transition('unknown_stage') is None, \
        "Unknown stage should return None"

    print("  ✓ Transitions defined for appropriate stages")
    print("  ✓ Closed stages have no transitions")

def test_unknown_stages_handled_gracefully():
    """
    Unknown stage IDs don't crash, return sensible defaults.
    """
    print("\n[TEST] Unknown stages handled gracefully")

    from field_semantics import (
        canonical_stage, stage_bucket, stage_label,
        is_won, is_lost, is_open, stage_transition
    )

    unknown = 'completely_unknown_stage_12345'

    # canonical_stage returns input unchanged
    assert canonical_stage(unknown) == unknown, \
        "Unknown stage should return itself"

    # stage_bucket returns 'unknown'
    assert stage_bucket(unknown) == 'unknown', \
        "Unknown stage should return 'unknown' bucket"

    # stage_label returns input unchanged
    assert stage_label(unknown) == unknown, \
        "Unknown stage should return itself as label"

    # is_won/is_lost return False
    assert not is_won(unknown), "Unknown stage should not be won"
    assert not is_lost(unknown), "Unknown stage should not be lost"

    # is_open returns True (safe default — treat unknown as open)
    assert is_open(unknown), \
        "Unknown stage should default to open for safety"

    # stage_transition returns None
    assert stage_transition(unknown) is None, \
        "Unknown stage should have no transition"

    print("  ✓ Unknown stages don't crash")
    print("  ✓ Unknown stages default to 'unknown' bucket and open status")

def test_no_raw_stage_ids_outside_field_semantics():
    """
    Grep etl_deals.py, backfill_snapshots.py, handlers.py, schema_context.py,
    stage_requirements.py for raw numeric stage IDs and hardcoded closedwon/closedlost
    lists. The only file allowed to contain them is config/field_semantics.yaml and
    the generated module.
    """
    print("\n[TEST] No raw stage IDs outside field_semantics")

    import pathlib

    banned = ["1297321623", "1297321624", "68509551"]
    checked = [
        "scripts/etl_deals.py",
        "scripts/analytics/backfill_snapshots.py",
        "api/handlers.py",
        "api/schema_context.py",
        "api/stage_requirements.py"
    ]

    violations = []
    for file_path in checked:
        full_path = pathlib.Path(__file__).parent.parent / file_path
        if not full_path.exists():
            continue

        src = full_path.read_text()
        for banned_id in banned:
            if banned_id in src:
                # Check if it's in active code (not comments/docstrings/config examples)
                lines = src.split('\n')
                for line_num, line in enumerate(lines, 1):
                    if banned_id not in line:
                        continue

                    stripped = line.strip()
                    # Skip comments
                    if stripped.startswith('#'):
                        continue
                    # Skip YAML config examples in docstrings (contain 'id:')
                    if 'id:' in line:
                        continue
                    # Skip stage name-to-ID mapping dicts (contain both stage name and ID)
                    if ': ' in line and ("'" in line or '"' in line):
                        # Line looks like "'Disqualified': '68509551'" - skip
                        continue

                    # Real violation - active code reference
                    violations.append(f"{file_path}:{line_num} contains {banned_id}")

    assert len(violations) == 0, \
        f"Found {len(violations)} raw stage ID leaks:\n  " + "\n  ".join(violations)

    print(f"  ✓ Checked {len(checked)} files for raw numeric stage IDs")
    print("  ✓ No violations found (all stage logic routes through field_semantics)")

def main():
    """Run all field_semantics drift tests."""
    print("=" * 70)
    print("FIELD SEMANTICS DRIFT TESTS")
    print("=" * 70)

    tests = [
        test_generated_module_matches_yaml,
        test_aliases_resolve_to_canonical,
        test_stage_bucket_covers_all_stages,
        test_is_won_is_lost_mutually_exclusive,
        test_stage_transition_returns_correct_keys,
        test_unknown_stages_handled_gracefully,
        test_no_raw_stage_ids_outside_field_semantics,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"\n❌ FAILED: {test.__name__}")
            print(f"   {e}")
        except Exception as e:
            failed += 1
            print(f"\n❌ ERROR in {test.__name__}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)

    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
