"""
Regression coverage for the 2026-09-11 (round 2) snapshot-diff scoping
decisions, from the same live run of "which enterprise deals changed
stage in the last 2 weeks in EMEA":

1. The response found 11 deals in the current snapshot not present in
   the prior one, and several prior-snapshot deals that dropped out
   (in the Renewal Pipeline, stage_order 0) — but left both as a vague
   aside inside its own reasoning instead of reporting them as a
   distinct, labeled category alongside stage changes.

2. Deal 59680315298's owner changed (Christian -> Scott Keller) between
   snapshots with no stage change, and the response silently classified
   it as "no change" — folding a real, relevant fact into a bucket that
   implies nothing happened.

DECISION (see the task report for the full reasoning): "changed stage"
stays scoped to stage_id/stage_order for the PRIMARY answer — broadening
it to include owner reassignment would silently redefine what the user
asked for. But an owner change on an otherwise-unchanged deal is real
information the query already surfaced, so it must be called out as an
explicit, separately-labeled aside rather than disappearing into "no
change". Population entries/exits get their own labeled category,
because a "what changed" question about a population over time
naturally includes deals entering/leaving it, not only stage deltas on
a fixed set of deals already in both snapshots.

This is prompt-instruction behavior, not a pure function — there is no
live LLM in this sandbox to run the actual multi-step comparison
against. What's tested here is structural: the instructions asserting
this scoping decision are actually present in DYNAMIC_SYSTEM_PROMPT (the
same "test what's mechanically verifiable" discipline used for the
other prompt-driven fixes in this suite), so a future edit that removes
or waters down this guidance fails a test instead of silently
regressing on the next live occurrence of this exact incident shape.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.router import DYNAMIC_SYSTEM_PROMPT

# The prompt hard-wraps long instructions across lines for readability;
# normalize whitespace before substring-matching multi-word phrases so a
# cosmetic line break doesn't fail a check that's actually satisfied.
_NORMALIZED_PROMPT = re.sub(r"\s+", " ", DYNAMIC_SYSTEM_PROMPT)


def test_prompt_requires_three_separate_labeled_diff_categories():
    prompt = _NORMALIZED_PROMPT.lower()
    assert "stage changes" in prompt, (
        "prompt must name 'stage changes' as its own category"
    )
    assert "population entries" in prompt, (
        "prompt must instruct reporting population entries (deals new to "
        "the current snapshot) as their own labeled category, not a "
        "vague aside"
    )
    assert "population exits" in prompt, (
        "prompt must instruct reporting population exits (deals dropped "
        "since the prior snapshot) as their own labeled category"
    )
    print("✓ prompt requires stage changes / population entries / population exits as separate categories")


def test_prompt_forbids_burying_entries_and_exits_as_a_vague_aside():
    prompt = _NORMALIZED_PROMPT.lower()
    assert "vague aside" in prompt or "buried" in prompt or "bury" in prompt, (
        "prompt must explicitly forbid burying population entries/exits "
        "as a vague, unlabeled aside — that's exactly what the live "
        "incident's response did"
    )
    print("✓ prompt explicitly forbids burying entries/exits as a vague aside")


def test_prompt_scopes_changed_to_stage_but_requires_surfacing_owner_changes():
    prompt = _NORMALIZED_PROMPT
    lowered = prompt.lower()
    assert "scope of \"changed\"" in lowered or "scope of 'changed'" in lowered, (
        "prompt must explicitly define the scope of a 'changed' question "
        "as stage_id/stage_order, not silently expand it"
    )
    assert "owner_email" in prompt and "no stage change" in lowered, (
        "prompt must instruct that an owner_email difference with no "
        "stage change be surfaced as a labeled aside — the live "
        "incident silently folded deal 59680315298's owner reassignment "
        "(Christian -> Scott Keller) into 'no change'"
    )
    assert "do not fold" in lowered or "not fold" in lowered, (
        "prompt must explicitly forbid folding an owner change into the "
        "stage-change count"
    )
    print("✓ prompt scopes 'changed' to stage, while requiring owner changes to be surfaced, not hidden")


def test_prompt_treats_pipeline_id_change_as_scope_exit_not_disappearance():
    lowered = _NORMALIZED_PROMPT.lower()
    assert "renewal pipeline" in lowered, (
        "prompt must reference the Renewal Pipeline explicitly when "
        "explaining a population exit caused by a pipeline_id change — "
        "the incident's dropped deals were Renewal Pipeline deals "
        "(pipeline_id 866608541, stage_id 1297321618), not deals that "
        "vanished from the business"
    )
    print("✓ prompt explains a pipeline_id-driven exit as a scope change, not a disappearance")


if __name__ == "__main__":
    test_prompt_requires_three_separate_labeled_diff_categories()
    test_prompt_forbids_burying_entries_and_exits_as_a_vague_aside()
    test_prompt_scopes_changed_to_stage_but_requires_surfacing_owner_changes()
    test_prompt_treats_pipeline_id_change_as_scope_exit_not_disappearance()
    print("\n✅ All tests passed")
