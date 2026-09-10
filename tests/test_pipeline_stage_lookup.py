"""
Regression tests for the 2026-09-11 (round 2) "pipeline_id 1297321618"
incident: a live run of "which enterprise deals changed stage in the
last 2 weeks in EMEA" found several prior-snapshot deals with
stage_order 0 and pipeline_id 1297321618 that had dropped from the
current snapshot, and — lacking any lookup for what that id means —
GUESSED in its own reasoning that "these appear to be a renewal
pipeline or pre-qualification stage" rather than checking a knowable
fact.

The guess happened to be directionally right: 1297321618 IS the
"Upcoming Renewal" stage (order 0) of the Renewal Pipeline (pipeline_id
866608541), per config/client.yaml and config/field_semantics.yaml. But
it was still a guess about something the codebase already knows for
certain, and the schema context handed to the model never surfaced it:

  - _stage_prose() (api/schema_context.py) previously only listed the
    first 3 "open"-bucket stages "for brevity" — 1297321618 was never
    in that truncated list, and none of the entries said which
    pipeline a stage belonged to.
  - The deals_snapshot table description (the table this exact
    question queries) didn't mention the stage glossary at all, only
    the "deals" table's description did.

This file tests the fix: _stage_prose() now lists every stage
(field_semantics.STAGE_MAP is only 14 entries — small enough to list in
full) annotated with which pipeline it belongs to, built from
config/client.yaml (the single source of truth for pipeline structure)
via scripts/utils.get_pipeline_config() — not a second hand-maintained
list that could drift from it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from api.schema_context import _stage_prose, _pipeline_name_by_stage_id
from api.field_semantics import STAGE_MAP

# The exact fact the live incident's model guessed at instead of knowing.
INCIDENT_STAGE_ID = "1297321618"
INCIDENT_STAGE_LABEL = "Upcoming Renewal"
RENEWAL_PIPELINE_NAME = "Renewal Pipeline"
SALES_PIPELINE_NAME = "Sales Pipeline"


def test_incident_stage_id_resolves_to_its_real_pipeline_not_a_guess():
    mapping = _pipeline_name_by_stage_id()
    assert mapping.get(INCIDENT_STAGE_ID) == RENEWAL_PIPELINE_NAME, (
        f"stage_id {INCIDENT_STAGE_ID} must resolve to {RENEWAL_PIPELINE_NAME!r} "
        f"via config/client.yaml — got {mapping.get(INCIDENT_STAGE_ID)!r}. This "
        f"is the exact fact the live incident's model guessed at ('these "
        f"appear to be a renewal pipeline') instead of looking up."
    )
    print(f"✓ stage_id {INCIDENT_STAGE_ID} resolves to {RENEWAL_PIPELINE_NAME} "
          f"via config lookup, not a guess")


def test_incident_stage_id_appears_in_stage_prose_with_label_and_pipeline():
    prose = _stage_prose()
    assert INCIDENT_STAGE_ID in prose, (
        f"stage_id {INCIDENT_STAGE_ID} must appear in the schema-context "
        f"stage glossary shown to the model — it was previously excluded "
        f"by a 'first 3 entries only, for brevity' truncation."
    )
    assert INCIDENT_STAGE_LABEL in prose, (
        f"the label {INCIDENT_STAGE_LABEL!r} for stage_id "
        f"{INCIDENT_STAGE_ID} must appear in the glossary."
    )
    assert RENEWAL_PIPELINE_NAME in prose, (
        f"the glossary must say WHICH PIPELINE stage_id "
        f"{INCIDENT_STAGE_ID} belongs to, not just its label — a bare "
        f"label still leaves 'is this new business or renewal?' as a "
        f"guess."
    )
    print(f"✓ stage_id {INCIDENT_STAGE_ID} appears in the schema glossary "
          f"with its label and pipeline name")


def test_every_stage_map_entry_appears_in_the_full_prose():
    """STAGE_MAP is the single source of truth for stage ids; the prose
    must be a complete lookup table, not a truncated sample — the
    incident happened precisely because a truncated sample omitted the
    entry that was needed."""
    prose = _stage_prose()
    missing = [sid for sid in STAGE_MAP if sid not in prose]
    assert not missing, (
        f"_stage_prose() must list EVERY stage in STAGE_MAP so the model "
        f"never has to guess — missing: {missing}"
    )
    print(f"✓ all {len(STAGE_MAP)} STAGE_MAP entries appear in the full stage prose")


def test_new_business_and_renewal_stages_are_correctly_distinguished():
    """A sales-pipeline stage and a renewal-pipeline stage must resolve
    to different pipeline names — this is what makes the glossary useful
    for the "should this deal count as new-business pipeline movement"
    question the incident actually needed answered."""
    mapping = _pipeline_name_by_stage_id()
    assert mapping.get("qualifiedtobuy") == SALES_PIPELINE_NAME, (
        "the default pipeline's 'Scoping' stage must resolve to "
        f"{SALES_PIPELINE_NAME!r}"
    )
    assert mapping.get("1297321619") == RENEWAL_PIPELINE_NAME, (
        "'Renewal Engaged' (1297321619) must resolve to "
        f"{RENEWAL_PIPELINE_NAME!r}, same pipeline as the incident stage"
    )
    print("✓ new-business and renewal-pipeline stages resolve to distinct, correct pipeline names")


def test_deals_snapshot_table_description_carries_the_stage_and_pipeline_glossary():
    """The exact table this incident's question queries (deals_snapshot,
    not deals) must itself carry the stage/pipeline glossary — before
    this fix, only the 'deals' table's description mentioned stage ids
    at all, so a question scoped entirely to deals_snapshot never saw
    a glossary in the first place, regardless of _stage_prose()'s own
    completeness."""
    import inspect
    from api import schema_context
    src = inspect.getsource(schema_context._build_schema_context)

    start = src.find('"deals_snapshot": (')
    assert start != -1, "deals_snapshot's table_descriptions entry not found"
    # Its value is a parenthesized string-literal concatenation; find the
    # matching close paren by simple depth counting from the open paren
    # right after '"deals_snapshot": '.
    depth = 0
    i = src.find("(", start)
    j = i
    while j < len(src):
        if src[j] == "(":
            depth += 1
        elif src[j] == ")":
            depth -= 1
            if depth == 0:
                break
        j += 1
    deals_snapshot_value = src[i:j + 1]

    assert "stage_note" in deals_snapshot_value, (
        "deals_snapshot's table description must include the stage "
        "glossary (stage_note), not just the 'deals' table's — a "
        "question scoped entirely to deals_snapshot (like the incident "
        "question) never sees a stage/pipeline glossary otherwise."
    )
    assert "pipeline_id" in deals_snapshot_value and "866608541" in deals_snapshot_value, (
        "deals_snapshot's table description must also spell out what "
        "pipeline_id values mean (default=Sales Pipeline, "
        "866608541=Renewal Pipeline), not just reference stage ids."
    )
    print("✓ deals_snapshot's table description carries both the stage "
          "glossary and the pipeline_id explanation")


if __name__ == "__main__":
    test_incident_stage_id_resolves_to_its_real_pipeline_not_a_guess()
    test_incident_stage_id_appears_in_stage_prose_with_label_and_pipeline()
    test_every_stage_map_entry_appears_in_the_full_prose()
    test_new_business_and_renewal_stages_are_correctly_distinguished()
    test_deals_snapshot_table_description_carries_the_stage_and_pipeline_glossary()
    print("\n✅ All tests passed")
