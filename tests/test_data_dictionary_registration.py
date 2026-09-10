"""
Structural gate: a migration that adds a column to deals, deals_snapshot,
or waterfall_weekly must also register that column in data_dictionary (or
list it in config/data_dictionary_exclusions.yaml) — in a migration file,
not just "eventually, on the live database."

Why this exists: deals_snapshot.region and deals_snapshot.segment existed
in Postgres and were fully populated by scripts/analytics/snapshot_deals.py
since 2026-09-08 (migration 060), but were never registered in
data_dictionary — the ONLY thing api/schema_context.py's
get_schema_context() reads to decide what columns the dynamic query loop
can see. The columns were completely invisible to the model for three
days, and it correctly said so ("the snapshot data doesn't include
segment or region columns") — accurately describing what it was shown,
not what was actually in the table. That's a data-dictionary REGISTRATION
gap, the same class of bug as a prior deals.region registration miss,
recurring on a different table because registering a new column was a
separate, skippable step from the migration that added it.

IMPORTANT ASYMMETRY WITH THE DATE-RESOLUTION GATE
(tests/test_date_resolution_single_source.py): that gate could be fully
static because "does this code call resolve_time_window()" is knowable
from source alone. "Is this column registered in data_dictionary" is NOT
knowable from the repo alone — registration also happens by running
scripts/backfill_data_dictionary.py directly against the live database,
which leaves no trace in any migration file. A static check run against
this repo's full migration history found 42 of 44 historical column
additions to these three tables "missing" by a naive file-only
comparison — nearly all false positives (columns that ARE registered
live, just not via a checked-in INSERT). A gate that cries wolf 42 times
on day one gets disabled, not respected.

So this test enforces the rule going forward only: for any migration
numbered higher than DATA_DICTIONARY_BASELINE_MIGRATION (the last
migration audited when this gate was added), a new column on one of these
tables must be registered by SOME migration file or excluded in
config/data_dictionary_exclusions.yaml. History before the baseline is
intentionally not re-litigated here — that requires the live database (see
scripts/check_data_dictionary_coverage.py), not a grep.
"""
import re
import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO_ROOT = Path(__file__).parent.parent
MIGRATIONS_DIR = REPO_ROOT / "scripts" / "migrations"
EXCLUSIONS_PATH = REPO_ROOT / "config" / "data_dictionary_exclusions.yaml"

TRACKED_TABLES = {"deals", "deals_snapshot", "waterfall_weekly"}

# The last migration present when this gate was written (062 registered
# deals_snapshot.region/segment). Only migrations numbered after this one
# are held to the "must register or exclude" rule — see module docstring
# for why history before it isn't re-litigated by a static check.
DATA_DICTIONARY_BASELINE_MIGRATION = 62

NUMBERED_MIGRATION = re.compile(r'^(\d+)_')


def _migration_number(path: Path):
    m = NUMBERED_MIGRATION.match(path.name)
    return int(m.group(1)) if m else None


def _added_columns(text: str):
    """(table, column) pairs from ALTER TABLE ... ADD COLUMN clauses."""
    found = []
    for stmt in re.finditer(
        r'ALTER TABLE\s+(\w+)\s+((?:ADD COLUMN.*?)(?:;|\Z))',
        text, re.IGNORECASE | re.DOTALL
    ):
        table = stmt.group(1)
        if table not in TRACKED_TABLES:
            continue
        for colm in re.finditer(r'ADD COLUMN(?:\s+IF NOT EXISTS)?\s+(\w+)',
                                 stmt.group(2), re.IGNORECASE):
            found.append((table, colm.group(1)))
    return found


def _registered_columns(text: str):
    """(table, column) pairs from INSERT INTO data_dictionary rows shaped
    like ('supabase', 'table', 'column', ...) — the convention every
    migration touching data_dictionary in this repo already follows."""
    if "data_dictionary" not in text.lower():
        return set()
    return {
        (m.group(1), m.group(2))
        for m in re.finditer(r"\(\s*'supabase'\s*,\s*'(\w+)'\s*,\s*'(\w+)'", text)
    }


def _load_exclusions():
    if not EXCLUSIONS_PATH.exists():
        return set()
    data = yaml.safe_load(EXCLUSIONS_PATH.read_text()) or {}
    return {(e["table"], e["column"]) for e in (data.get("excluded") or [])}


def _find_unregistered_new_columns():
    all_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    registered = set()
    for f in all_files:
        registered |= _registered_columns(f.read_text())

    excluded = _load_exclusions()

    violations = []
    for f in all_files:
        num = _migration_number(f)
        if num is None or num <= DATA_DICTIONARY_BASELINE_MIGRATION:
            continue  # pre-baseline or unnumbered — not re-litigated here
        for table, column in _added_columns(f.read_text()):
            if (table, column) in registered or (table, column) in excluded:
                continue
            violations.append((f.name, table, column))
    return violations


def test_new_migrations_register_their_columns_or_exclude_them():
    violations = _find_unregistered_new_columns()
    assert not violations, (
        "New migration(s) add a column to deals/deals_snapshot/"
        "waterfall_weekly without registering it in data_dictionary or "
        "excluding it in config/data_dictionary_exclusions.yaml. This is "
        "exactly the deals_snapshot.region/segment gap from 2026-09-11 — "
        "add a data_dictionary INSERT for the column in the SAME migration "
        "(see scripts/migrations/062_register_snapshot_region_segment_in_"
        "dictionary.sql for the pattern), or add an explicit exclusion "
        "entry with a real reason if it's genuinely not meant to be "
        "queryable.\n" +
        "\n".join(f"  {fname}: {table}.{column}" for fname, table, column in violations)
    )
    print("✓ every column added to deals/deals_snapshot/waterfall_weekly "
          "since migration 062 is registered in data_dictionary or "
          "explicitly excluded")


def test_exclusions_file_is_well_formed():
    """Cheap sanity check so a typo in the exclusions file doesn't
    silently make the real test above pass for the wrong reason."""
    assert EXCLUSIONS_PATH.exists(), f"{EXCLUSIONS_PATH} must exist"
    data = yaml.safe_load(EXCLUSIONS_PATH.read_text())
    assert isinstance(data, dict) and "excluded" in data, (
        "data_dictionary_exclusions.yaml must have a top-level 'excluded' key"
    )
    for entry in data["excluded"] or []:
        assert "table" in entry and "column" in entry and "reason" in entry, (
            f"Exclusion entry missing table/column/reason: {entry}"
        )
        assert entry["table"] in TRACKED_TABLES, (
            f"Exclusion for untracked table {entry['table']!r} — "
            f"tracked tables are {TRACKED_TABLES}"
        )
    print("✓ data_dictionary_exclusions.yaml is well-formed")


if __name__ == "__main__":
    test_exclusions_file_is_well_formed()
    test_new_migrations_register_their_columns_or_exclude_them()
    print("\n✅ All tests passed")
