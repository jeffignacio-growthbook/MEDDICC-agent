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

ROUND 2 (2026-09-11, same day, same question): a second live run of
"which enterprise deals changed stage in the last 2 weeks in EMEA" hit
this gate's blind spot from a different angle. This time the raw text
WAS pasted verbatim into the report — see
VERBATIM_INCIDENT_TRANSCRIPT_ROUND_2 below — and it exposed two distinct
bugs: (1) the narration markers didn't cover "Now I have both snapshots.
Let me diff them properly.", a gap now closed by adding "diff" to the
check/verify/... marker alternation and a new "now i have (both|all)"
marker; (2) the model can also wrap this exact narration INSIDE valid
{"answer": "..."} JSON, which reaches the `if "answer" in parsed:` branch
of dynamic_query_loop — a second entry point for a finished answer that
never called _looks_like_unfinished_scratchpad() at all, independent of
the prose-fallback path tested here. See
test_json_wrapped_answer_path_also_checks_for_scratchpad below for that
part of the fix (a structural check, since exercising the live JSON
branch needs a real multi-turn LLM loop this sandbox can't run).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
REPO_ROOT = Path(__file__).parent.parent

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


# 2026-09-11 ROUND 2 — this is the actual raw log text (not a
# reconstruction), pasted verbatim from a live run of "which enterprise
# deals changed stage in the last 2 weeks in EMEA". The opening two
# paragraphs below are copied exactly as reported. The task's own report
# elided the middle of the real transcript with "[... continues with raw
# per-deal breakdown, internal reasoning about what pipeline_id 1297321618
# 'appears to be', then a final {"answer": ...} block]" — that elision is
# the reporter's own, not this file's; VERBATIM_INCIDENT_TRANSCRIPT_ROUND_2
# keeps the exact opening/narration lines that matter for detection and
# fills the elided middle with a plain marker rather than inventing
# per-deal rows that were never actually shown. This is what slipped past
# the gate: neither "now i have both" nor "let me diff" was a recognized
# narration marker, so _looks_like_unfinished_scratchpad(...) returned
# False and the raw per-deal breakdown + internal reasoning shipped
# straight to Slack.
VERBATIM_INCIDENT_TRANSCRIPT_ROUND_2 = """Now I have both snapshots. Let me diff them properly.

**Prior snapshot (2026-07-27) — Enterprise EMEA deals with new-business stage IDs:**
- 54169480766 → stage_order 2 (qualifiedtobuy) — Jake
[... raw per-deal breakdown and internal reasoning about pipeline_id 1297321618, elided in the original report — see module docstring ...]"""


def test_verbatim_incident_transcript_round_2_is_detected_as_scratchpad():
    assert _looks_like_unfinished_scratchpad(VERBATIM_INCIDENT_TRANSCRIPT_ROUND_2), (
        "This is the actual raw log text from the live incident (not a "
        "reconstruction) — its opening line 'Now I have both snapshots. "
        "Let me diff them properly.' must be caught by the narration "
        "markers, and previously was not."
    )
    print("✓ verbatim round-2 incident transcript is detected as unfinished scratchpad")


def test_now_i_have_both_and_let_me_diff_markers_individually_detected():
    """The two specific phrases the gate missed in the round-2 incident,
    isolated from the rest of the transcript, so a future regression in
    either marker fails here directly rather than only via the full
    transcript fixture above."""
    assert _looks_like_unfinished_scratchpad("Now I have both snapshots in hand."), (
        "'now i have both' must be a recognized narration marker"
    )
    assert _looks_like_unfinished_scratchpad("Let me diff them properly."), (
        "'let me diff' must be a recognized narration marker"
    )
    assert _looks_like_unfinished_scratchpad("Let me diff them."), (
        "'let me diff them' (no trailing 'properly') must also match"
    )
    print("✓ 'now i have both' and 'let me diff [them [properly]]' are each individually detected")


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


def test_json_wrapped_answer_path_also_checks_for_scratchpad():
    """STRUCTURAL GATE (2026-09-11, round 2): dynamic_query_loop has two
    places a finished answer can come from — the prose-fallback path
    (when JSON parsing fails, tested above via _looks_like_unfinished_
    scratchpad directly) and the `if "answer" in parsed:` branch (when
    the model successfully wraps its response in {"answer": ...} JSON).
    Before this fix, only the first path called
    _looks_like_unfinished_scratchpad() — a model that wrapped scratchpad
    narration inside otherwise-valid JSON skipped the check entirely.

    This can't be exercised with a live multi-turn loop in this sandbox
    (no Anthropic/Supabase credentials), so — same shape as the date-
    resolution and data-dictionary structural gates elsewhere in this
    suite — it greps the actual source for the call site: the scratchpad
    check must appear BETWEEN `answer_text = parsed["answer"]` and the
    branch's own `return {"answer": parsed["answer"], ...}`, not just
    once anywhere in the function (which the prose-fallback call alone
    would already satisfy without actually covering this branch)."""
    src = (REPO_ROOT / "api" / "router.py").read_text()

    marker_start = 'answer_text = parsed["answer"]'
    marker_end = 'return {"answer": parsed["answer"], "tool_results": tool_results,'
    start = src.find(marker_start)
    end = src.find(marker_end)
    assert start != -1 and end != -1 and start < end, (
        "Could not locate the `if \"answer\" in parsed:` branch's body "
        "between its answer_text assignment and its return — router.py "
        "may have been restructured; update this test's markers."
    )
    branch_body = src[start:end]

    assert "_looks_like_unfinished_scratchpad(answer_text)" in branch_body, (
        "The `if \"answer\" in parsed:` branch of dynamic_query_loop "
        "must call _looks_like_unfinished_scratchpad(answer_text) before "
        "returning — otherwise scratchpad narration wrapped in valid "
        "JSON bypasses the gate entirely, which is exactly what the "
        "2026-09-11 round-2 incident's root-cause hypothesis #1 asked "
        "to be ruled out or fixed."
    )
    print("✓ the JSON-wrapped-answer branch also calls "
          "_looks_like_unfinished_scratchpad before returning")


if __name__ == "__main__":
    test_reconstructed_incident_transcript_is_detected_as_scratchpad()
    test_verbatim_incident_transcript_round_2_is_detected_as_scratchpad()
    test_now_i_have_both_and_let_me_diff_markers_individually_detected()
    test_clean_finished_answer_is_not_flagged()
    test_benign_let_me_know_sign_off_is_not_flagged()
    test_various_narration_markers_are_each_detected()
    test_markdown_table_alone_without_narration_is_not_flagged()
    test_json_wrapped_answer_path_also_checks_for_scratchpad()
    print("\n✅ All tests passed")
