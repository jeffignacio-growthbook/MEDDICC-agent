"""
Tests for two follow-ups to the 2026-10-03 coverage-answer-omissions fix
(commit 3c4e5289, PR #120), both in api/handlers.py::query_pipeline_coverage:

1. CURRENT-PIPELINE-BY-STAGE BREAKDOWN: a real live Slack answer said
   "most deals are sitting in Discovery and Scoping" — an unsupported
   model inference, since the payload never actually showed a by-stage
   breakdown. scripts/pipeline_coverage.py now computes qualified_
   pipeline.by_stage_order (deal_count + value per stage, aggregates
   only — see scripts/test_pipeline_by_stage.py for that primitive's own
   tests); this handler annotates it with stage_name (same pattern
   already used for stage_weighting.by_stage_order) and adds a
   "STAGE CLAIMS" guidance line to _synthesis_note that forbids inferring
   stage concentration when the field is absent/empty.

2. LATE-PHASE COMMIT-QUESTION GUIDANCE: in the late phase, when no named
   commit-stage deal data is available, the guidance used to tell the
   model something generic ("suggest checking committed pipeline
   directly"). It now tells the model to name the EXACT follow-up
   question that would get that data (e.g. "which deals are in commit?"),
   so the user gets something actionable instead of a vague pointer.

Mirrors tests/test_pipeline_coverage_gap_arithmetic.py's pattern exactly:
offline/deterministic, no live LLM/Supabase — patch
pipeline_coverage.assess_pipeline_coverage, call
handlers.query_pipeline_coverage directly.
"""
import sys
import types
import copy
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[1]
for p in ("", "scripts", "scripts/analytics", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

if "supabase" not in sys.modules:
    _fake = types.ModuleType("supabase")
    _fake.create_client = lambda *a, **k: None
    _fake.Client = type("Client", (), {})
    sys.modules["supabase"] = _fake

import asyncio  # noqa: E402
from api import handlers  # noqa: E402

from test_pipeline_coverage_gap_arithmetic import _coverage, BASE_FIXTURE  # noqa: E402


async def _run(fixture):
    with patch("pipeline_coverage.assess_pipeline_coverage", return_value=dict(fixture)):
        return await handlers.query_pipeline_coverage({}, MagicMock())


def test_by_stage_order_annotated_with_stage_names():
    """qualified_pipeline.by_stage_order's integer stage_order keys get a
    "stage_name" sibling field added, same annotation already applied to
    stage_weighting.by_stage_order — order 1 is Discovery, order 2 is
    Scoping in GrowthBook's real config/client.yaml (the exact two stages
    the unsupported live-Slack claim named)."""
    print("\n[TEST] qualified_pipeline.by_stage_order gets stage_name annotations")
    fixture = copy.deepcopy(BASE_FIXTURE)
    fixture["qualified_pipeline"]["by_stage_order"] = {
        1: {"deal_count": 12, "value": 500000.0},
        2: {"deal_count": 8, "value": 300000.0},
    }
    result = asyncio.run(_run(fixture))
    bso = result["qualified_pipeline"]["by_stage_order"]

    assert bso[1]["stage_name"] == "Discovery", f"expected Discovery, got {bso[1]!r}"
    assert bso[2]["stage_name"] == "Scoping", f"expected Scoping, got {bso[2]!r}"
    # Original aggregate fields must survive the annotation untouched.
    assert bso[1]["deal_count"] == 12 and bso[1]["value"] == 500000.0
    assert bso[2]["deal_count"] == 8 and bso[2]["value"] == 300000.0
    print("  ✓ stage order 1 -> Discovery, stage order 2 -> Scoping, counts/values intact")


def test_synthesis_note_always_carries_stage_claims_guidance():
    """The STAGE CLAIMS guidance line must be present in _synthesis_note
    regardless of phase/quota branch — it is a standing caution, not
    conditional on any other field."""
    print("\n[TEST] STAGE CLAIMS guidance present in every branch")
    for fixture, label in (
        (BASE_FIXTURE, "normal mid-phase"),
        (_quota_met_fixture(), "quota-met"),
        (_no_quota_fixture(), "no-quota"),
    ):
        result = asyncio.run(_run(fixture))
        note = result.get("_synthesis_note")
        assert note, f"expected a _synthesis_note ({label})"
        assert "STAGE CLAIMS" in note, f"expected STAGE CLAIMS guidance ({label}), got: {note!r}"
        assert "qualified_pipeline.by_stage_order" in note, (
            f"expected the guidance to name the actual field ({label}), got: {note!r}")
        assert "do not" in note.lower() and "infer" in note.lower(), (
            f"expected an explicit prohibition on inferring stage concentration "
            f"({label}), got: {note!r}")
    print("  ✓ present in normal, quota-met, and no-quota branches alike")


def _quota_met_fixture():
    fixture = copy.deepcopy(BASE_FIXTURE)
    fixture["coverage"] = _coverage(
        remaining_gap=0.0, nominal_coverage=None, weighted_coverage=None,
        quota_met=True, phase="mid",
        equations={"remaining": "$1,000,000 quota - $1,200,000 won = $0 remaining "
                                "(quota already met, $200,000 over)",
                   "nominal": None, "weighted": None})
    return fixture


def _no_quota_fixture():
    fixture = copy.deepcopy(BASE_FIXTURE)
    fixture["real_target"]["quota"] = None
    fixture["real_target"]["goal"] = None
    fixture["coverage"] = _coverage(
        remaining_gap=None, nominal_coverage=None, weighted_coverage=None,
        quota_met=None, phase="mid")
    return fixture


def test_late_phase_names_concrete_follow_up_question_not_vague_pointer():
    """LATE phase, no named-commit data available: guidance must name a
    CONCRETE follow-up question (e.g. "which deals are in commit") rather
    than a vague pointer like "pull the committed pipeline" / "check
    committed pipeline directly"."""
    print("\n[TEST] late phase: concrete follow-up question, not a vague pointer")
    late_fixture = copy.deepcopy(BASE_FIXTURE)
    late_fixture["coverage"]["phase"] = "late"
    late_fixture["current_week"] = 11
    late_fixture["quarter_time_left"] = {"days_left": 14, "weeks_left": 2, "label": "2 weeks left"}

    result = asyncio.run(_run(late_fixture))
    note = result["_synthesis_note"]

    assert "which deals are in commit" in note.lower(), (
        f"expected a concrete example follow-up question, got: {note!r}")
    assert "exact follow-up question" in note.lower(), (
        f"expected the model to be told to NAME a follow-up question, got: {note!r}")
    assert "do not" in note.lower() and "vague pointer" in note.lower(), (
        f"expected an explicit prohibition on a vague pointer, got: {note!r}")
    # The old generic phrasing must be gone, not just supplemented.
    assert "suggest checking committed pipeline directly" not in note, (
        f"expected the old vague-pointer phrasing to be replaced, not kept "
        f"alongside the new instruction, got: {note!r}")
    print("  ✓ late-phase guidance names a concrete follow-up question, "
          "old vague-pointer phrasing is gone")


def test_early_phase_has_neither_pivot_nor_commit_question_guidance():
    """REGRESSION GUARD: early phase carries neither the late-phase
    named-commits pivot nor the commit-question guidance — these are
    LATE-phase-only instructions."""
    print("\n[TEST] early phase has no late-phase commit-question guidance")
    early_fixture = copy.deepcopy(BASE_FIXTURE)
    early_fixture["coverage"]["phase"] = "early"
    early_fixture["current_week"] = 2

    result = asyncio.run(_run(early_fixture))
    note = result["_synthesis_note"]
    assert "which deals are in commit" not in note.lower(), (
        f"early phase should carry no commit-question guidance, got: {note!r}")
    print("  ✓ early phase carries no commit-question guidance")


def main():
    tests = [
        test_by_stage_order_annotated_with_stage_names,
        test_synthesis_note_always_carries_stage_claims_guidance,
        test_late_phase_names_concrete_follow_up_question_not_vague_pointer,
        test_early_phase_has_neither_pivot_nor_commit_question_guidance,
    ]

    failed = []
    for test in tests:
        try:
            test()
        except Exception as e:
            failed.append((test.__name__, str(e)))
            print(f"\n  ❌ FAILED: {e}")

    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = len(tests) - len(failed)
    print(f"\nTotal tests: {len(tests)}")
    print(f"  ✓ Passed: {passed}")

    if failed:
        print(f"  ✗ Failed: {len(failed)}")
        for name, error in failed:
            print(f"  - {name}")
            print(f"    {error[:200]}")
        return 1

    print("\n✅ All stage-claims / late-phase commit-question tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
