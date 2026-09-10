"""
Regression tests for the 2026-09-11 "scratchpad shipped as the answer"
defect: the dynamic_query_loop's "prose answer" fallback path (for when
the model doesn't wrap its response in {"answer": ...} JSON) accepted ANY
non-JSON text over 50 characters as the final Slack message, with no
check for whether it was actually a finished answer.

A live response started with a scratchpad-style table ("Deals in BOTH
snapshots — checking for stage changes"), narrated "let me use what I
have and produce the answer now," then attempted a second, cleaner
answer — and ALL of it (table, narration, both answer attempts) shipped
to Slack concatenated, because the fallback path never checked whether
the "prose answer" was one.

NOTE ON THE FIXTURE: the task described this failure precisely (exact
phrases quoted) but the raw response text itself was not pasted into the
conversation this fix was written from. RECONSTRUCTED_INCIDENT_TRANSCRIPT
below reproduces the described shape as faithfully as possible from that
description — the scratchpad table with its exact quoted title, the exact
quoted narration, and a second clean-looking answer concatenated after it
— but it is a reconstruction, not the literal captured log text. If the
real raw text is available, it should replace this fixture directly; the
assertions here would not need to change, since they test the same
underlying mechanism the description points to (self-referential process
narration, not the specific data values).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.router import _looks_like_unfinished_scratchpad


# Reconstructed from the reported incident description — see module
# docstring. Mirrors the reported shape exactly: a scratchpad table titled
# for the model's own reasoning, the quoted narration, then a second,
# cleaner attempt at the answer — both shipped together. The underlying
# real diff described alongside it (1 mover, 4 dropped, several new deals)
# is reflected in the "clean" half of this fixture.
RECONSTRUCTED_INCIDENT_TRANSCRIPT = """Deals in BOTH snapshots — checking for stage changes:

| deal_id | company | prior_stage | current_stage | changed |
|---|---|---|---|---|
| 60665391542 | Acme Corp | qualifiedtobuy | presentationscheduled | Yes |
| 61045491056 | Beta Inc | qualifiedtobuy | qualifiedtobuy | No |
| 60785721693 | Gamma LLC | appointmentscheduled | appointmentscheduled | No |

Let me use what I have and produce the answer now.

*1 deal moved stage*: Acme Corp advanced from Scoping to Technical Evaluation.

*4 deals dropped from the pipeline* since the prior snapshot: Beta Inc, Gamma LLC, Delta Co, Epsilon Ltd.

*New deals since the prior snapshot*: 6 new deals entered the pipeline, including Zeta Corp ($45K) and Eta Inc ($30K)."""


def test_reconstructed_incident_transcript_is_detected_as_scratchpad():
    assert _looks_like_unfinished_scratchpad(RECONSTRUCTED_INCIDENT_TRANSCRIPT), (
        "The reconstructed incident transcript contains the exact reported "
        "narration ('let me use what I have and produce the answer now') "
        "and must be caught, not shipped as-is."
    )
    print("✓ reconstructed incident transcript is detected as unfinished scratchpad")


def test_clean_finished_answer_is_not_flagged():
    """The SAME underlying data, delivered as a single clean answer with
    no scratchpad/narration, must pass through untouched — this fix must
    not make the loop paranoid about ordinary finished answers."""
    clean_answer = (
        "*1 deal moved stage*: Acme Corp advanced from Scoping to Technical "
        "Evaluation.\n\n"
        "*4 deals dropped from the pipeline* since the prior snapshot: "
        "Beta Inc, Gamma LLC, Delta Co, Epsilon Ltd.\n\n"
        "*New deals since the prior snapshot*: 6 new deals entered the "
        "pipeline, including Zeta Corp ($45K) and Eta Inc ($30K)."
    )
    assert not _looks_like_unfinished_scratchpad(clean_answer)
    print("✓ a clean finished answer with no narration is not flagged")


def test_benign_let_me_know_sign_off_is_not_flagged():
    """'let me know' is a normal customer-facing closing line, not process
    narration — must not false-positive on it."""
    answer = (
        "Pipeline is up 12% this quarter to $2.1M. Let me know if you need "
        "the rep-level breakdown."
    )
    assert not _looks_like_unfinished_scratchpad(answer), (
        "'let me know' is ordinary sign-off language, not a scratchpad "
        "marker — flagging it would make the gate too aggressive"
    )
    print("✓ 'let me know if...' sign-off phrasing is correctly NOT flagged")


def test_various_narration_markers_are_each_detected():
    examples = [
        "I'll now compute the totals from the table above.",
        "I will now finalize my answer based on this.",
        "Let me check this against the other snapshot first.",
        "Let me recalculate this properly.",
        "Starting over, here is the corrected breakdown.",
        "Here's my scratchpad for working through the diff.",
        "These are my working notes before the real answer.",
        "For my own reasoning, here's how I got to this number.",
        "Now let me produce the final answer.",
    ]
    for text in examples:
        assert _looks_like_unfinished_scratchpad(text), \
            f"Expected this to be flagged as scratchpad narration: {text!r}"
    print(f"✓ all {len(examples)} narration-marker examples are individually detected")


def test_markdown_table_alone_without_narration_is_not_flagged():
    """A table is not inherently a scratchpad — some finished answers may
    legitimately include one. Only self-referential process narration
    should trigger this gate; table syntax alone should not, to avoid
    over-triggering on answers that use a table on purpose."""
    answer = (
        "Stage breakdown this quarter:\n\n"
        "| Stage | Count |\n|---|---|\n| Discovery | 12 |\n| Scoping | 8 |"
    )
    assert not _looks_like_unfinished_scratchpad(answer)
    print("✓ a deliberate table with no narration is not flagged")


if __name__ == "__main__":
    test_reconstructed_incident_transcript_is_detected_as_scratchpad()
    test_clean_finished_answer_is_not_flagged()
    test_benign_let_me_know_sign_off_is_not_flagged()
    test_various_narration_markers_are_each_detected()
    test_markdown_table_alone_without_narration_is_not_flagged()
    print("\n✅ All tests passed")
