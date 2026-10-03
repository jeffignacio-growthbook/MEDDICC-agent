"""
Tests for query_pipeline_coverage's config-driven REMAINING-GAP coverage
synthesis guidance (api/handlers.py), superseding PR #117's bare quota-vs-
pipeline subtraction.

Context (2026-10-03): the denominator for coverage is now always the
REMAINING gap (quota minus QTD closed-won), never the bare quota —
scripts/pipeline_coverage.py::assess_pipeline_coverage computes
coverage.remaining_gap/nominal_coverage/weighted_coverage/expected_
multiple/ahead_behind/phase/equations (point 6 of that module's
docstring). This file tests the HANDLER layer: how that primitive's
output becomes synthesis guidance, not a template — PR #117's approach
embedded exact sentences for the model to copy; this one states facts
(the equations, ahead/behind, phase) and instructs the model to say the
verdict in its own words, never scripting the prose itself.

Also covers item 6 of this task: the HEURISTIC historical_heuristic_curve
is popped from the top-level (rendered) result but stays in cache_payload
(built from result BEFORE the pop) — citable on request
(explain_prior_answer) but never competing with the real remaining-gap
figure in the primary answer again.

Test groups (all offline/deterministic, no live LLM/Supabase — mirrors
tests/test_explain_prior_answer_citation.py's handler-test pattern:
patch pipeline_coverage.assess_pipeline_coverage, call
handlers.query_pipeline_coverage directly):
  1. Normal (mid-phase, behind) case — equations quoted, ahead/behind
     fact stated, no late-phase pivot instruction.
  2. Quota-met edge case — no ratio equations, remaining-gap equation
     states "already met".
  3. No-quota edge case — no equations fabricated, guidance still says
     something honest (never silent, never a bare division by nothing).
  4. Late-phase pivot-to-named-commits instruction present; early-phase
     has no such instruction.
  5. historical_heuristic_curve: present in cache_payload, ABSENT from
     the top-level (rendered) result.
  6. _synthesis_note never leaks into cache_payload (stays a top-level,
     per-turn-only field).
  7. REGRESSION: query_rep_attainment (shares generic synthesis
     scaffolding, no coverage field of its own) gets no _synthesis_note.
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

from test_explain_prior_answer_citation import _mock_rep_attainment_sb  # noqa: E402


def _coverage(remaining_gap, nominal_coverage, weighted_coverage, quota_met,
             expected_multiple=None, ahead_behind=None, phase="mid",
             equations=None):
    return {
        "remaining_gap": remaining_gap, "quota_met": quota_met,
        "nominal_coverage": nominal_coverage, "weighted_coverage": weighted_coverage,
        "expected_multiple": expected_multiple, "ahead_behind": ahead_behind,
        "phase": phase,
        "equations": equations or {"remaining": None, "nominal": None, "weighted": None},
        "note": "test coverage note",
    }


BASE_FIXTURE = {
    "status": "ok",
    "fiscal_quarter": "FY2027 Q3",
    "current_week": 7,
    "is_historical": False,
    "scope": "New+Expansion ARR only; qualified pipeline only",
    "qualified_pipeline": {"raw_value": 900000.0, "deal_count": 22},
    "renewal_not_weighted": {"deal_count": 3, "value": 90000.0, "note": "..."},
    "stage_weighting": {
        "weighted_value": 799782.0, "weighted_deal_count": 19,
        "unweighted_value": 0.0, "unweighted_deal_count": 0,
        "by_stage_order": {}, "min_evidence_count": 30, "note": "...",
    },
    "real_target": {
        "quota": 1550000.0, "stretch": 2100000.0, "goal": 1550000.0,
        "stretch_note": "Ryan's personal aspiration.",
        "note": "Stated target for FY2027 Q3 — team quota from rep_targets.",
    },
    "qtd_won": {"value": 500000.0, "deal_count": 10, "note": "test qtd note"},
    "coverage": _coverage(
        remaining_gap=1050000.0, nominal_coverage=900000.0 / 1050000.0,
        weighted_coverage=799782.0 / 1050000.0, quota_met=False,
        expected_multiple=1.2, ahead_behind="behind", phase="mid",
        equations={
            "remaining": "$1,550,000 quota - $500,000 won = $1,050,000 remaining",
            "nominal": "$900,000 raw qualified pipeline / $1,050,000 remaining = 0.86x",
            "weighted": "$799,782 weighted pipeline / $1,050,000 remaining = 0.76x",
        }),
    "historical_heuristic_curve": {"by_week": {}, "proxy_targets": {},
                                   "heuristic": True, "label": "HEURISTIC",
                                   "note": "HEURISTIC."},
    "note": "HEURISTIC curve note.",
}


async def _run(fixture):
    with patch("pipeline_coverage.assess_pipeline_coverage", return_value=dict(fixture)):
        return await handlers.query_pipeline_coverage({}, MagicMock())


def test_guidance_states_ahead_behind_and_quotes_all_three_equations():
    """Normal mid-phase, behind-pace case: all three equations quoted
    verbatim (never recomputed by the model), the ahead/behind FACT and
    the expected multiple stated, and guidance says to narrate the verdict
    in the model's own words rather than copying a scripted sentence."""
    print("\n[TEST] guidance states ahead/behind fact, quotes all three equations")
    result = asyncio.run(_run(BASE_FIXTURE))
    note = result.get("_synthesis_note")
    assert note, "expected a _synthesis_note"

    assert "own words" in note.lower(), "expected guidance, not a scripted sentence"
    assert "$1,550,000 quota - $500,000 won = $1,050,000 remaining" in note
    assert "$900,000 raw qualified pipeline / $1,050,000 remaining = 0.86x" in note
    assert "$799,782 weighted pipeline / $1,050,000 remaining = 0.76x" in note
    assert "behind" in note and "1.20x" in note and "week 7" in note
    print("  ✓ all three equations quoted verbatim; ahead/behind fact + expected multiple stated")


def test_no_schedule_configured_says_so_instead_of_fabricating_ahead_behind():
    """When ahead_behind is None (no expected_multiple_schedule entry for
    this week), guidance must say there is no fact to state — never
    silently omit it or invent a verdict."""
    print("\n[TEST] no expected-multiple schedule -> guidance says so, no fabrication")
    fixture = copy.deepcopy(BASE_FIXTURE)
    fixture["coverage"]["ahead_behind"] = None
    fixture["coverage"]["expected_multiple"] = None

    result = asyncio.run(_run(fixture))
    note = result["_synthesis_note"]
    assert "no expected-multiple schedule is configured" in note.lower()
    assert "describe the ratios themselves instead" in note.lower()
    print("  ✓ guidance explicitly states no ahead/behind fact is available")


def test_quota_met_guidance_has_no_ratio_equations():
    """Quota-met edge case: the remaining equation (stating the quarter is
    already met) is quoted; nominal/weighted equations are absent from
    guidance entirely (none exist to quote — no ratio was computed)."""
    print("\n[TEST] quota met -> only the remaining equation, no ratio equations")
    fixture = copy.deepcopy(BASE_FIXTURE)
    fixture["coverage"] = _coverage(
        remaining_gap=0.0, nominal_coverage=None, weighted_coverage=None,
        quota_met=True, phase="mid",
        equations={"remaining": "$1,000,000 quota - $1,200,000 won = $0 remaining "
                                "(quota already met, $200,000 over)",
                   "nominal": None, "weighted": None})

    result = asyncio.run(_run(fixture))
    note = result["_synthesis_note"]
    assert "already met" in note.lower()
    assert "$1,000,000 quota - $1,200,000 won = $0 remaining" in note
    assert "raw qualified pipeline /" not in note
    assert "weighted pipeline /" not in note
    print("  ✓ quota-met guidance states the headline, no ratio equations present")


def test_no_quota_guidance_says_so_plainly():
    """No quota configured at all: guidance must say so plainly and
    explicitly forbid implying a coverage ratio from pipeline figures
    alone — never silent, never a fabricated comparison."""
    print("\n[TEST] no quota configured -> guidance says so plainly, no fabrication")
    fixture = copy.deepcopy(BASE_FIXTURE)
    fixture["real_target"]["quota"] = None
    fixture["real_target"]["goal"] = None
    fixture["coverage"] = _coverage(
        remaining_gap=None, nominal_coverage=None, weighted_coverage=None,
        quota_met=None, phase="mid")

    result = asyncio.run(_run(fixture))
    note = result["_synthesis_note"]
    assert "no quota is configured" in note.lower()
    assert "do not compute or imply a coverage ratio" in note.lower()
    print("  ✓ no-quota guidance present and explicit")


def test_late_phase_instructs_pivot_to_named_commits():
    """LATE phase: guidance must instruct brevity on the ratio and a pivot
    toward named, committed deals (if available) — the opposite of EARLY
    phase, which has no such instruction."""
    print("\n[TEST] late phase -> pivot-to-named-commits instruction; early phase -> none")
    late_fixture = copy.deepcopy(BASE_FIXTURE)
    late_fixture["coverage"]["phase"] = "late"
    late_fixture["current_week"] = 11

    result = asyncio.run(_run(late_fixture))
    note = result["_synthesis_note"]
    assert "late phase" in note.lower() or "LATE phase" in note
    assert "sentence or two" in note
    assert "named" in note.lower() and "committed" in note.lower()

    early_fixture = copy.deepcopy(BASE_FIXTURE)
    early_fixture["coverage"]["phase"] = "early"
    early_fixture["current_week"] = 2
    result_early = asyncio.run(_run(early_fixture))
    note_early = result_early["_synthesis_note"]
    assert "shift the answer's focus" not in note_early.lower(), (
        f"early phase should carry no pivot-to-named-deals instruction, got: {note_early!r}")
    print("  ✓ late phase instructs the pivot to named commits; early phase does not")


def test_historical_curve_removed_from_rendered_result_kept_in_cache_payload():
    """Item 6: historical_heuristic_curve must NOT reach synthesis (absent
    from the top-level/rendered result) but must still be fully present
    in cache_payload for citation (explain_prior_answer)."""
    print("\n[TEST] historical_heuristic_curve: gone from rendered result, kept in cache_payload")
    result = asyncio.run(_run(BASE_FIXTURE))

    assert "historical_heuristic_curve" not in result, (
        "historical_heuristic_curve must not reach the rendered/synthesis-visible result")
    assert "historical_heuristic_curve" in result["cache_payload"], (
        "historical_heuristic_curve must still be citable via cache_payload")
    assert result["cache_payload"]["historical_heuristic_curve"] == \
        BASE_FIXTURE["historical_heuristic_curve"]
    print("  ✓ historical_heuristic_curve absent from rendered result, intact in cache_payload")


def test_synthesis_note_not_leaked_into_cache_payload():
    """_synthesis_note is a per-turn synthesis instruction, not citable
    structured data — must stay a top-level sibling of cache_payload,
    never copied INTO cache_payload itself."""
    print("\n[TEST] _synthesis_note stays out of cache_payload")
    result = asyncio.run(_run(BASE_FIXTURE))
    assert "_synthesis_note" in result
    assert "_synthesis_note" not in result["cache_payload"], (
        "the coverage guidance leaked into cache_payload — it must stay a "
        "top-level, per-turn-only field")
    print("  ✓ _synthesis_note present at top level, absent from cache_payload")


def test_rep_attainment_gets_no_synthesis_note_regression():
    """REGRESSION GUARD: query_rep_attainment shares the same generic
    synthesis scaffolding (_VOICE_BASE/TABLE_FORMAT_RULE) but has no
    coverage field of its own — this change must not have added a
    _synthesis_note to it."""
    print("\n[TEST] query_rep_attainment unaffected — no _synthesis_note added")
    import datetime as _dt

    targets = [{"entity_email": "jake@growthbook.io", "metric": "quota", "target_value": 300000}]
    deals = [{"owner_email": "jake@growthbook.io", "new_arr": 100000, "expansion_arr": 0,
             "pipeline_id": "default"}]
    personas = [{"email": "jake@growthbook.io", "display_name": "Jake", "name": "Jake"}]
    sb = _mock_rep_attainment_sb(targets, deals, personas)

    with patch("utils.get_fiscal_quarter", return_value=(_dt.date(2026, 8, 1),
                                                         _dt.date(2026, 10, 31),
                                                         "FY2027 Q3")), \
         patch("api.handlers._resolve_owner_email", return_value=(None, None)), \
         patch("api.handlers._resolve_tw", return_value={"start": "2026-08-01",
                                                          "end": "2026-10-31",
                                                          "label": "FY2027 Q3"}):
        result = asyncio.run(handlers.query_rep_attainment({}, sb))

    assert "_synthesis_note" not in result, (
        f"REGRESSION: query_rep_attainment unexpectedly got a _synthesis_note: "
        f"{result.get('_synthesis_note')!r}")
    print("  ✓ query_rep_attainment's result carries no _synthesis_note")
