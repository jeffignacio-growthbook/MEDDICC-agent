#!/usr/bin/env python3
"""
Grain guard for api/table_classifier.py's hardcoded table descriptions.

WHY THIS EXISTS (2026-09-26, live routing failure): the table-classifier is
an LLM fed a one-line description per table, with zero grain-awareness.
pipeline_generation_weekly's description — "New pipeline created each week"
— was a near-verbatim match for "how much pipeline did we generate this
week," but the table had NO week column at all: it was quarter-grained
(fiscal_quarter, pipeline_id, segment), one row per quarter. The question
landed there instead of on the genuinely weekly waterfall_weekly, got 0 rows
against a fake week-filter, and fell back to "could not find anything."
Renamed to pipeline_generation_quarterly (migration 074) and its description
rewritten — this test makes the underlying failure mode structurally
unrepeatable, not just this one instance of it:

  1. Every classifier table whose NAME implies a time grain (a `_weekly`,
     `_daily`, `_monthly`, or `_quarterly` suffix) must actually HAVE a
     column matching that grain in the real schema (tests/fixtures/
     db_schema_columns.json) — a name promising a grain the table can't
     back up is exactly how this bug happened.
  2. Every such table's classifier description must explicitly STATE its
     grain word, so a human or model reading the description alone can't
     mistake a quarterly table for a weekly one (or vice versa).
  3. At most one classifier table may claim WEEKLY "new pipeline" ownership.
     Two tables both describing themselves as the place to find weekly new
     pipeline is the exact collision that misrouted the live question —
     this fails loudly if it ever recurs under any future table name.

Offline and pure: parses the real CLASSIFICATION_PROMPT string and the real
schema fixture, so a future edit to either is checked automatically, not
just this one rename.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

import api.table_classifier as table_classifier  # noqa: E402

SCHEMA_FIXTURE = REPO / "tests" / "fixtures" / "db_schema_columns.json"

# grain suffix -> substrings that a real column name must contain (any one)
# to count as backing that grain. Generic on purpose: a future _monthly or
# _daily table is checked the same way without new code.
GRAIN_COLUMN_HINTS = {
    "weekly": ["week"],
    "quarterly": ["quarter"],
    "monthly": ["month"],
    "daily": ["day", "date"],
}

TABLE_LINE = re.compile(r'^- (\w+): (.+)$', re.MULTILINE)


def parse_classifier_descriptions(prompt_text=None):
    """{table_name: description} from the real CLASSIFICATION_PROMPT (or an
    injected string, for the planted-bug controls below)."""
    text = table_classifier.CLASSIFICATION_PROMPT if prompt_text is None else prompt_text
    return dict(TABLE_LINE.findall(text))


def load_schema_columns():
    import json
    data = json.loads(SCHEMA_FIXTURE.read_text())
    return data["tables"]


def _grain_suffix(table_name):
    for suffix in GRAIN_COLUMN_HINTS:
        if table_name.endswith("_" + suffix):
            return suffix
    return None


def find_grain_mismatches(descriptions, schema_columns):
    """[(table, reason)] for every classifier table whose name implies a
    time grain but whose real columns don't back it up, or whose
    description doesn't state that grain explicitly."""
    problems = []
    for table in descriptions:
        suffix = _grain_suffix(table)
        if suffix is None:
            continue
        hints = GRAIN_COLUMN_HINTS[suffix]
        cols = schema_columns.get(table)
        if cols is None:
            problems.append((table, f"name implies {suffix!r} grain but the "
                                     f"table isn't in the schema fixture at all"))
            continue
        if not any(hint in col.lower() for col in cols for hint in hints):
            problems.append((table, f"name implies {suffix!r} grain but no "
                                     f"column matches {hints} (columns: {cols})"))
        desc = descriptions[table].lower()
        if not any(hint in desc for hint in hints + [suffix]):
            problems.append((table, f"name implies {suffix!r} grain but its "
                                     f"classifier description never says so: "
                                     f"{descriptions[table]!r}"))
    return problems


def find_weekly_new_pipeline_owners(descriptions):
    """Table names whose description claims BOTH weekly grain and new-
    pipeline-generation ownership — the collision that misrouted the live
    question. Exactly one is expected (waterfall_weekly)."""
    owners = []
    for table, desc in descriptions.items():
        d = desc.lower()
        claims_new_pipeline = bool(re.search(r'new.{0,3}pipeline|pipeline.{0,15}generat', d))
        claims_weekly = "week" in d
        if claims_new_pipeline and claims_weekly:
            owners.append(table)
    return owners


def test_grain_named_tables_have_matching_columns_and_say_so():
    descriptions = parse_classifier_descriptions()
    schema_columns = load_schema_columns()
    problems = find_grain_mismatches(descriptions, schema_columns)
    assert not problems, "Grain mismatch(es) in api/table_classifier.py:\n" + "\n".join(
        f"  {t}: {r}" for t, r in problems
    )


def test_exactly_one_weekly_new_pipeline_owner():
    descriptions = parse_classifier_descriptions()
    owners = find_weekly_new_pipeline_owners(descriptions)
    assert owners == ["waterfall_weekly"], (
        f"Expected exactly one table (waterfall_weekly) to claim weekly "
        f"new-pipeline ownership, got {owners}. Two tables both describing "
        f"themselves this way is the exact collision that misrouted "
        f"'how much pipeline did we generate this week' onto a "
        f"quarter-grained table."
    )


def test_pipeline_generation_quarterly_present_not_weekly():
    """Direct regression pin for the renamed table itself, in addition to
    the generic checks above."""
    descriptions = parse_classifier_descriptions()
    assert "pipeline_generation_weekly" not in descriptions, (
        "the old grain-lying name should no longer appear in the classifier prompt"
    )
    assert "pipeline_generation_quarterly" in descriptions
    desc = descriptions["pipeline_generation_quarterly"].lower()
    assert "quarter" in desc
    assert "not weekly" in desc or "never for" in desc or "no week" in desc, (
        f"pipeline_generation_quarterly's description should explicitly "
        f"disclaim weekly use, got: {descriptions['pipeline_generation_quarterly']!r}"
    )


if __name__ == "__main__":
    tests = [
        test_grain_named_tables_have_matching_columns_and_say_so,
        test_exactly_one_weekly_new_pipeline_owner,
        test_pipeline_generation_quarterly_present_not_weekly,
    ]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")

    # Planted-bug controls: corrupt the real inputs and confirm a test
    # catches each corruption. Operates on the SAME parse/check functions
    # the tests above call, via injected prompt text / schema dicts.
    print("\n--- planted-bug controls ---")

    real_schema = load_schema_columns()

    # (1) Reintroduce the exact original bug: revert the description back to
    # claiming weekly grain with no disclaimer, alongside the real
    # waterfall_weekly description. Two weekly new-pipeline owners.
    bad_prompt_collision = table_classifier.CLASSIFICATION_PROMPT.replace(
        "pipeline_generation_quarterly: QUARTERLY (by fiscal_quarter, NOT weekly — no week column exists) "
        "generation totals with in-quarter-vs-rollover split. Only for \"this/last QUARTER\" questions; "
        "never for \"this week.\"",
        "pipeline_generation_quarterly: New pipeline created each week"
    )
    assert bad_prompt_collision != table_classifier.CLASSIFICATION_PROMPT, (
        "planted-bug replace() did not match — update this control's search string"
    )
    owners = find_weekly_new_pipeline_owners(parse_classifier_descriptions(bad_prompt_collision))
    assert len(owners) == 2, f"expected the planted collision bug to produce 2 owners, got {owners}"
    print("CAUGHT collision planted bug (2 weekly new-pipeline owners)")

    # (2) Strip the grain word from pipeline_generation_quarterly's
    # description entirely (but keep it distinct from waterfall_weekly, so
    # only the "states its grain" check should fire, not the collision one).
    bad_prompt_silent = table_classifier.CLASSIFICATION_PROMPT.replace(
        "pipeline_generation_quarterly: QUARTERLY (by fiscal_quarter, NOT weekly — no week column exists) "
        "generation totals with in-quarter-vs-rollover split. Only for \"this/last QUARTER\" questions; "
        "never for \"this week.\"",
        "pipeline_generation_quarterly: Pipeline generation totals with a rollover split, by pipeline and segment."
    )
    assert bad_prompt_silent != table_classifier.CLASSIFICATION_PROMPT, (
        "planted-bug replace() did not match — update this control's search string"
    )
    assert "quarter" not in bad_prompt_silent.split("pipeline_generation_quarterly:")[1].split("\n")[0].lower(), (
        "planted-bug description still mentions 'quarter' — strengthen the control"
    )
    problems = find_grain_mismatches(parse_classifier_descriptions(bad_prompt_silent), real_schema)
    problem_tables = [t for t, _ in problems]
    assert "pipeline_generation_quarterly" in problem_tables, (
        f"expected the silent-grain planted bug to be flagged, got problems: {problems}"
    )
    print("CAUGHT silent-grain planted bug (description doesn't state its grain)")

    # (3) Column/name mismatch: fake a schema where the real quarterly table
    # lost its fiscal_quarter column (simulating a future rename that forgets
    # the schema fixture, or a table renamed to a grain it can't back up).
    bad_schema = dict(real_schema)
    bad_schema["pipeline_generation_quarterly"] = ["id", "generated_value", "pipeline_id", "segment"]
    problems = find_grain_mismatches(parse_classifier_descriptions(), bad_schema)
    problem_tables = [t for t, _ in problems]
    assert "pipeline_generation_quarterly" in problem_tables, (
        f"expected the missing-fiscal_quarter-column planted bug to be flagged, got: {problems}"
    )
    print("CAUGHT column-mismatch planted bug (name implies grain, column removed)")

    print("\nAll grain-guard tests + planted-bug controls passed.")
