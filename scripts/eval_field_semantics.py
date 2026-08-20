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

    # Blind spot this test previously had: it iterated STAGE_MAP keys, and
    # yaml parses a bare numeric key as an int. HubSpot sends stage ids as
    # strings, so 79653122, 24682892 and 43449439 resolved to 'unknown' in
    # production while this test passed on the int form. Assert both.
    for stage_id in STAGE_MAP.keys():
        as_string = str(stage_id)
        bucket = stage_bucket(as_string)
        assert bucket != 'unknown', (
            f"Stage '{as_string}' returns 'unknown' when looked up as a string. "
            f"Quote the key in config/field_semantics.yaml — yaml parses a bare "
            f"numeric key as an int, but HubSpot sends stage ids as strings."
        )

    print(f"  ✓ All {len(STAGE_MAP)} stages return valid buckets (int and str keys):")
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

def test_client_yaml_and_field_semantics_agree():
    """The two configs must not drift apart on which stages exist.

    client.yaml defines the live pipelines; field_semantics defines what each
    stage MEANS. A stage in one and not the other is drift, and drift is the
    risk — not any particular missing stage. Every stage id falls in exactly
    one of three categories:

      live        in client.yaml AND classified by field_semantics
      historical  classified, `historical: true`, absent from client.yaml
                  (still in old property history, so it must stay classified)
      retired     in retired_stages, unclassifiable, provably unreachable

    Anything else is drift and fails here.
    """
    print("\n[TEST] client.yaml and field_semantics agree on stages")

    import yaml as _yaml
    from pathlib import Path as _Path
    from field_semantics import (RETIRED_STAGES, STAGE_MAP, canonical_stage,
                                 is_historical_stage, stage_bucket)

    REPO = _Path(__file__).parent.parent
    client = _yaml.safe_load((REPO / 'config/client.yaml').read_text())

    client_ids = set()
    for pipeline in client['pipeline']['pipelines']:
        for stage in pipeline['stages']:
            client_ids.add(str(stage['id']))

    semantics_ids = set()
    for stage_id, info in STAGE_MAP.items():
        semantics_ids.add(str(stage_id))
        for alias in info.get('aliases', []):
            semantics_ids.add(str(alias))

    retired_ids = {str(s) for s in RETIRED_STAGES}

    # 1. Every live stage must be classified, or the terminal-stage inclusion
    #    rule cannot decide whether a deal is open.
    unclassified_live = sorted(
        s for s in client_ids if stage_bucket(s) == 'unknown')
    assert not unclassified_live, (
        f"client.yaml stage(s) {unclassified_live} have no classification in "
        f"field_semantics.yaml. The terminal-stage inclusion rule raises on "
        f"these, so a backfill would stop mid-run."
    )

    # 2. Nothing may be both live and retired.
    both = sorted(client_ids & retired_ids)
    assert not both, (
        f"stage(s) {both} are in client.yaml AND retired_stages. Retired means "
        f"hard-deleted and unreachable; a live pipeline stage is neither."
    )

    # 3. Anything field_semantics knows but client.yaml does not must be
    #    explicitly marked historical. Unmarked means drift.
    unexplained = sorted(
        s for s in semantics_ids - client_ids
        if not is_historical_stage(s) and s not in retired_ids)
    assert not unexplained, (
        f"stage(s) {unexplained} are classified in field_semantics.yaml but "
        f"absent from client.yaml, and not marked `historical: true`. Either "
        f"add them to the pipeline config, or mark them historical if they "
        f"only appear in old property history."
    )

    # 4. A historical stage that IS live contradicts itself — the flag would
    #    exempt a current stage from the drift check. This is what an alias
    #    silently caused for the renewal Contract Sent.
    live_but_historical = sorted(s for s in client_ids if is_historical_stage(s))
    assert not live_but_historical, (
        f"stage(s) {live_but_historical} are in client.yaml but marked "
        f"`historical: true`. A live stage must not be drift-exempt. Give it "
        f"its own stage_map entry instead of aliasing it to a historical one."
    )

    live = sorted(client_ids)
    historical = sorted(s for s in semantics_ids if is_historical_stage(s))
    print(f"  ✓ live: {len(live)}  historical: {historical}  "
          f"retired: {sorted(retired_ids)}")
    print("  ✓ no unexplained divergence between the two configs")


def test_config_numeric_keys_are_strings():
    """Bare numeric YAML keys parse as ints; HubSpot sends strings. Any
    config key that is a numeric identifier must be quoted. Tests that
    iterate config keys cannot catch this — they exercise the int form
    production never sends."""
    print("\n[TEST] Config numeric keys and id values are strings")

    import glob
    import yaml as _yaml
    from pathlib import Path as _Path

    REPO = _Path(__file__).parent.parent

    # Scan the configs this codebase reads at runtime. .github/workflows is
    # excluded on purpose: `on:` is parsed as boolean True by yaml 1.1, but
    # GitHub parses those files, not us.
    patterns = ['config/**/*.yaml', 'config/**/*.yml', 'prompts/**/*.yaml']
    files = sorted({f for pat in patterns
                    for f in glob.glob(str(REPO / pat), recursive=True)})
    assert files, "found no config files to scan — check the glob patterns"

    bad_keys, bad_values = [], []

    ID_FIELD = ('id', 'ids', 'stage_id', 'pipeline_id', 'owner_id', 'user_id',
                'deal_id', 'slack_id', 'hubspot_id', 'portal_id')

    def walk(node, path, parent_key=None):
        if isinstance(node, dict):
            for k, v in node.items():
                # A mapping key that did not parse as a string was unquoted.
                # If it looks like an identifier, the runtime lookup (which
                # passes a string) will miss it and fall through to a default.
                if not isinstance(k, str):
                    bad_keys.append((path, k, type(k).__name__))
                walk(v, f"{path}.{k}", parent_key=str(k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]", parent_key=parent_key)
        else:
            # Same bug class in value position: an unquoted numeric id
            # compared against a string id will never match.
            if (parent_key in ID_FIELD
                    and isinstance(node, (int, float))
                    and not isinstance(node, bool)):
                bad_values.append((path, node, type(node).__name__))

    for f in files:
        walk(_yaml.safe_load(_Path(f).read_text()), _Path(f).name)

    assert not bad_keys, (
        "Unquoted numeric YAML key(s) — quote them:\n" +
        "\n".join(f"    {p}  key={k!r} ({t})" for p, k, t in bad_keys) +
        "\n  yaml parses a bare number as an int, but HubSpot sends stage and "
        "pipeline ids as strings, so the lookup misses and silently returns a "
        "default. This is how stage_bucket() returned 'unknown' in production "
        "for Meeting Set, Negotiating and Awaiting Signature."
    )

    assert not bad_values, (
        "Unquoted numeric identifier value(s) — quote them:\n" +
        "\n".join(f"    {p} = {v!r} ({t})" for p, v, t in bad_values) +
        "\n  compared against a string id at runtime, these never match."
    )

    print(f"  ✓ {len(files)} config files scanned")
    print("  ✓ no unquoted numeric keys, no unquoted numeric id values")


def test_no_raw_stage_ids_outside_field_semantics():
    """
    Grep production files for raw numeric stage IDs and hardcoded stage mappings.
    The only files allowed to contain them are:
    - config/field_semantics.yaml (source of truth)
    - api/field_semantics.py (generated module)
    - scripts/generate_field_semantics.py (generator)
    - scripts/reconcile_*.py, scripts/verify_*.py (reconciliation artifacts)
    """
    print("\n[TEST] No raw stage IDs outside field_semantics")

    import pathlib

    # Extended list: all known numeric stage IDs
    banned = ["1297321623", "1297321624", "68509551", "79653122", "24682892", "43449439"]
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

def test_harness_boundary_isolation():
    """
    PHASE 5d ISOLATION TEST - Critical guard for harness boundary.

    Enforces that handlers and field_semantics NEVER read data_dictionary at runtime.
    This prevents the harness from going soft and ensures client porting remains
    a simple yaml swap with zero code changes.

    Violations would allow:
    - Handlers dynamically reading field definitions instead of using generated field_semantics
    - Stage logic drifting back to runtime lookups instead of compile-time yaml
    - Client-specific logic leaking into handler code

    This test locks the boundary: handlers consume ONLY the generated field_semantics.py,
    never the proposal source (data_dictionary).
    """
    print("\n[TEST] Harness boundary isolation (Phase 5d)")

    import pathlib
    import re

    # Files in the harness boundary that MUST NOT read data_dictionary
    # NOTE: schema_context.py is EXCLUDED - it's part of the dynamic query path
    # and legitimately reads data_dictionary to build schema descriptions
    harness_files = [
        "api/handlers.py",          # Handler functions (must consume only field_semantics)
        "api/field_semantics.py",   # Generated stage logic (never reads proposals)
        "scripts/etl_deals.py",     # ETL (writes to Supabase, no runtime proposals)
        "scripts/analytics/backfill_snapshots.py",  # Backfill (no runtime proposals)
    ]

    violations = []

    for file_path in harness_files:
        full_path = pathlib.Path(__file__).parent.parent / file_path
        if not full_path.exists():
            continue

        src = full_path.read_text()
        lines = src.split('\n')

        for line_num, line in enumerate(lines, 1):
            # Check for data_dictionary table access
            # Pattern: select_all(client, 'data_dictionary', ...)
            # Pattern: .table('data_dictionary')
            # Pattern: from data_dictionary

            if 'data_dictionary' in line.lower():
                stripped = line.strip()

                # Skip comments
                if stripped.startswith('#'):
                    continue

                # Skip docstrings/comments explaining what data_dictionary is
                if '#' in line and line.index('#') < line.lower().index('data_dictionary'):
                    continue

                # Detect actual code references
                # Pattern 1: select_all(sb, 'data_dictionary', ...)
                if re.search(r"select_(all|one)\s*\([^)]*['\"]data_dictionary['\"]", line):
                    violations.append(
                        f"{file_path}:{line_num} - select_all/one('data_dictionary') "
                        f"(handlers must not read data_dictionary at runtime)"
                    )

                # Pattern 2: .table('data_dictionary')
                if re.search(r"\.table\s*\(\s*['\"]data_dictionary['\"]", line):
                    violations.append(
                        f"{file_path}:{line_num} - .table('data_dictionary') "
                        f"(handlers must not read data_dictionary at runtime)"
                    )

                # Pattern 3: FROM data_dictionary (SQL)
                if re.search(r"FROM\s+data_dictionary", line, re.IGNORECASE):
                    violations.append(
                        f"{file_path}:{line_num} - FROM data_dictionary in SQL "
                        f"(handlers must not read data_dictionary at runtime)"
                    )

    if violations:
        msg = (
            f"\n❌ HARNESS BOUNDARY VIOLATED\n\n"
            f"Found {len(violations)} violations of the isolation rule:\n"
            f"Handlers and field_semantics MUST NOT read data_dictionary at runtime.\n\n"
            f"Violations:\n  " + "\n  ".join(violations) + "\n\n"
            f"The dynamic query path (api/router.py, api/tools.py) can read data_dictionary.\n"
            f"But the handler harness consumes ONLY generated field_semantics.py.\n"
            f"This keeps client porting a simple yaml swap.\n"
        )
        raise AssertionError(msg)

    print(f"  ✓ Checked {len(harness_files)} harness files")
    print("  ✓ No data_dictionary access detected")
    print("  ✓ Harness boundary is isolated (handlers consume only generated field_semantics)")

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
        test_client_yaml_and_field_semantics_agree,
        test_config_numeric_keys_are_strings,
        test_no_raw_stage_ids_outside_field_semantics,
        test_harness_boundary_isolation,  # Phase 5d - critical boundary guard
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
