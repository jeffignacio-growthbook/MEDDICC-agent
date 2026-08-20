#!/usr/bin/env python3
"""
Migration file validation tests.

Guards against:
- Duplicate migration numbers
- Missing migration files
- Incorrect dependency order

Run this before committing any new migrations.
"""

import sys
from pathlib import Path
from collections import Counter


def test_no_duplicate_migration_numbers():
    """
    Ensure no two migration files share the same numeric prefix.

    This test prevents the collision problem that existed with:
    - 012_add_forecast_weekly.sql AND 012_add_sdr_metrics.sql
    - 013_add_segmentation.sql AND 013_add_user_personas.sql
    - etc.

    On GrowthBook these were applied in the right order by hand.
    On template they would apply in undefined order, breaking dependencies.
    """
    print("\n[TEST] No duplicate migration numbers")

    migrations_dir = Path(__file__).parent / "migrations"

    if not migrations_dir.exists():
        raise FileNotFoundError(f"Migrations directory not found: {migrations_dir}")

    # Extract numeric prefix from each migration file
    migration_files = list(migrations_dir.glob("*.sql"))

    if not migration_files:
        raise FileNotFoundError(f"No migration files found in {migrations_dir}")

    # Build map of number -> filenames
    number_to_files = {}
    for filepath in migration_files:
        filename = filepath.name

        # Extract number (everything before first underscore)
        parts = filename.split("_")
        if not parts[0].isdigit():
            print(f"  ⚠️  WARNING: Non-numeric prefix in {filename}")
            continue

        number = parts[0]
        number_to_files.setdefault(number, []).append(filename)

    # Check for duplicates
    duplicates = {num: files for num, files in number_to_files.items() if len(files) > 1}

    if duplicates:
        print(f"\n  ❌ DUPLICATE MIGRATION NUMBERS FOUND:\n")
        for num, files in sorted(duplicates.items()):
            print(f"  Number {num} used by {len(files)} files:")
            for f in files:
                print(f"    - {f}")
        print("\n  Fix by renumbering conflicts to unique numbers.")
        print("  See scripts/migrations/MIGRATION_ORDER.md for canonical order.\n")
        raise AssertionError(f"Found {len(duplicates)} duplicate migration numbers")

    print(f"  ✓ Checked {len(migration_files)} migration files")
    print(f"  ✓ All migration numbers are unique (001-{max(number_to_files.keys())})")


def test_migration_sequence_has_no_gaps():
    """
    Check if migration sequence has large gaps (optional warning).

    Small gaps are OK (e.g., 027 → 028 → 030 is fine).
    Large gaps (e.g., 020 → 050) might indicate numbering issues.
    """
    print("\n[TEST] Migration sequence gap check")

    migrations_dir = Path(__file__).parent / "migrations"
    migration_files = list(migrations_dir.glob("*.sql"))

    numbers = []
    for filepath in migration_files:
        parts = filepath.name.split("_")
        if parts[0].isdigit():
            numbers.append(int(parts[0]))

    numbers.sort()

    # Check for gaps > 5 (arbitrary threshold)
    gaps = []
    for i in range(len(numbers) - 1):
        gap = numbers[i+1] - numbers[i]
        if gap > 5:
            gaps.append((numbers[i], numbers[i+1], gap))

    if gaps:
        print(f"  ⚠️  Found {len(gaps)} large gaps in migration sequence:")
        for prev, next_, gap in gaps:
            print(f"    {prev:03d} → {next_:03d} (gap of {gap})")
        print("  This is OK if intentional, but verify no migrations are missing.")
    else:
        print(f"  ✓ Migration sequence has no large gaps")
        print(f"  ✓ Range: {min(numbers):03d} - {max(numbers):03d}")


def test_critical_dependencies_respected():
    """
    Verify critical dependencies are in correct order.

    These dependencies MUST be respected:
    - 014_add_segment_reason comes after 013_add_segmentation
    - 032_user_personas_email_primary_key comes after 029_add_user_personas
    - 034_add_proposal_lifecycle comes after 020_add_data_dictionary
    """
    print("\n[TEST] Critical dependencies respected")

    migrations_dir = Path(__file__).parent / "migrations"

    # Build number -> filename map
    migrations = {}
    for filepath in migrations_dir.glob("*.sql"):
        parts = filepath.name.split("_")
        if parts[0].isdigit():
            number = int(parts[0])
            migrations[number] = filepath.name

    # Define critical dependencies
    dependencies = [
        (13, "013_add_segmentation.sql", 14, "014_add_segment_reason.sql"),
        (13, "013_add_segmentation.sql", 15, "015_create_pipeline_generation_weekly.sql"),
        (29, "029_add_user_personas.sql", 32, "032_user_personas_email_primary_key.sql"),
        (20, "020_add_data_dictionary.sql", 34, "034_add_proposal_lifecycle.sql"),
    ]

    violations = []
    for dep_num, dep_name, target_num, target_name in dependencies:
        # Check if dependency exists
        if dep_num not in migrations:
            violations.append(f"Missing dependency: {dep_num} ({dep_name})")
            continue

        # Check if target exists
        if target_num not in migrations:
            violations.append(f"Missing target: {target_num} ({target_name})")
            continue

        # Check order
        if target_num <= dep_num:
            violations.append(
                f"Order violation: {target_name} (#{target_num}) should come AFTER "
                f"{dep_name} (#{dep_num})"
            )

    if violations:
        print(f"\n  ❌ DEPENDENCY VIOLATIONS:\n")
        for v in violations:
            print(f"    {v}")
        raise AssertionError(f"Found {len(violations)} dependency violations")

    print(f"  ✓ Checked {len(dependencies)} critical dependencies")
    print("  ✓ All dependencies respected:")
    for dep_num, dep_name, target_num, target_name in dependencies:
        print(f"    {dep_num:03d} → {target_num:03d}: {target_name}")


def test_check_constraint_vocabularies_match_code():
    """Every CHECK(col IN (...)) vocabulary must be a superset of what the code
    writes to that column. This is the general form of the backfill_confidence
    incident: migration 017's CHECK allowed the old confidence words, the Phase
    1 relabel changed the code to exact/pre_history/no_history, the constraint
    was not widened, and the write failed 23514 AFTER the purge had run.

    Also reports enum-ish columns that have NO CHECK, where a bad value drifts
    in silently rather than erroring — those are a softer version of the same
    risk and worth knowing about.
    """
    import re
    from pathlib import Path as _P

    mig_dir = _P(__file__).parent / 'migrations'

    # Parse CHECK (col IN ('a','b',...)) across migrations, latest wins.
    constraints = {}   # column -> (migration_number, allowed set)
    for f in sorted(mig_dir.glob('*.sql')):
        num = int(f.name.split('_')[0])
        sql = f.read_text()
        for m in re.finditer(r"(\w+)\s+IN\s*\(([^)]*)\)", sql):
            col, body = m.group(1), m.group(2)
            vals = set(re.findall(r"'([^']*)'", body))
            if not vals:
                continue
            # Keep only CHECK contexts (a CHECK keyword near this match).
            window = sql[max(0, m.start() - 40):m.start()]
            if 'CHECK' not in window.upper():
                continue
            if col not in constraints or num >= constraints[col][0]:
                constraints[col] = (num, vals)

    # What the code emits for each constrained column. Extend this map when a
    # new CHECK-constrained column is written by code.
    code_vocab = {
        # backfill_confidence carries the stage confidence from point_in_time.
        'backfill_confidence': {'exact', 'pre_history', 'no_history'},
    }

    failures = []
    for col, emitted in code_vocab.items():
        if col not in constraints:
            failures.append(f"{col}: code emits {sorted(emitted)} but no CHECK "
                            f"constraint found — either add the column to a "
                            f"migration's CHECK or remove it from code_vocab")
            continue
        _, allowed = constraints[col]
        extra = emitted - allowed
        if extra:
            failures.append(
                f"{col}: code emits {sorted(extra)} which the CHECK does NOT "
                f"allow (allowed: {sorted(allowed)}). This is exactly the "
                f"backfill_confidence incident — widen the constraint or fix "
                f"the code before writing.")

    print("\n[TEST] CHECK-constraint vocabularies vs code")
    for col, (num, allowed) in sorted(constraints.items()):
        covered = col in code_vocab
        print(f"  {col}: CHECK(migration {num:03d}) allows {sorted(allowed)}"
              + (f"  code emits {sorted(code_vocab[col])} ⊆ allowed" if covered
                 else "  (no code_vocab entry — not written by tracked code)"))

    # Informational: enum-ish columns with a DEFAULT but no CHECK, where drift
    # is silent. Not a failure — a standing note that the DB won't catch it.
    unconstrained = []
    for f in sorted(mig_dir.glob('*.sql')):
        for m in re.finditer(r"(\w*(?:status|source|type))\s+TEXT[^,\n]*DEFAULT",
                             f.read_text(), re.I):
            col = m.group(1)
            if col not in constraints:
                unconstrained.append(col)
    if unconstrained:
        print("  enum-ish columns with NO CHECK (drift is silent, not caught): "
              + ", ".join(sorted(set(unconstrained))))

    assert not failures, "CHECK vocabulary vs code mismatch:\n  " + "\n  ".join(failures)
    print("  ✓ every code-written CHECK column emits only allowed values")


def main():
    """Run all migration validation tests."""
    print("=" * 70)
    print("MIGRATION VALIDATION TESTS")
    print("=" * 70)

    tests = [
        test_no_duplicate_migration_numbers,
        test_migration_sequence_has_no_gaps,
        test_critical_dependencies_respected,
        test_check_constraint_vocabularies_match_code,
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
