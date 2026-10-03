"""
Tests for the gap-to-goal ARITHMETIC fix in query_pipeline_coverage's
rendered output.

Live test confirmed tonight's (2026-10-03) computations are correct
($1,550,000 - $799,782 = $750,218), but the rendered table only showed the
final delta ("$750,218 short of target"), never the subtraction itself.
For a report whose core point IS the gap, the gap's own derivation should
be shown, not just asserted.

Diagnosis: gap_to_goal's own .text field (scripts/pipeline_coverage.py's
_gap_to_goal()) only ever states the result ("$X short of target" / "$X
over target") — it never carried the quota/value operands, and nothing in
api/router.py's generic synthesis scaffolding (_VOICE_BASE, TABLE_FORMAT_
RULE) instructs the model to show arithmetic for any handler. The
established mechanism for handler-specific synthesis instructions is the
`_synthesis_note` field (_VOICE_BASE: "ALWAYS follow the instructions in
this field when present") — query_waterfall already uses it (its
_headline_instruction); query_pipeline_coverage had none at all.

Fix: query_pipeline_coverage's handler (api/handlers.py) now builds the
full equation strings in CODE (never left to the model to compute, so the
equation itself can't contain an arithmetic error) from real_target.quota,
qualified_pipeline.raw_value, stage_weighting.weighted_value, and
gap_to_goal's own status/amount — for BOTH the raw and weighted
comparisons — and instructs the model via _synthesis_note to include them
verbatim. Scoped to display/prompt only; gap_to_goal's own computation is
untouched.

Test groups (all offline/deterministic, no live LLM/Supabase — mirrors
tests/test_explain_prior_answer_citation.py's handler-test pattern:
patch pipeline_coverage.assess_pipeline_coverage, call
handlers.query_pipeline_coverage directly):
  1. Tonight's exact numbers reproduced as a fixture — _synthesis_note
     contains the explicit equation for both raw and weighted.
  2. Direction wording is correct for an "over target" result too.
  3. No quota configured (gap_to_goal fields are None) — no fabricated
     equation, no crash.
  4. _synthesis_note never leaks into cache_payload (stays a top-level,
     per-turn-only field, same convention as query_waterfall's).
  5. REGRESSION: query_rep_attainment (shares the same generic synthesis
     scaffolding, no gap_to_goal field of its own) gets no _synthesis_note
     at all — this fix is scoped to query_pipeline_coverage only.
"""
import sys
import types
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


# ── tonight's exact incident numbers ────────────────────────────────────
TONIGHT_FIXTURE = {
    "status": "ok",
    "fiscal_quarter": "FY2027 Q3",
    "current_week": 9,
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
    "gap_to_goal": {
        "raw_pipeline_vs_goal": {"status": "short", "amount": 650000.0,
                                  "text": "$650,000 short of target"},
        "weighted_pipeline_vs_goal": {"status": "short", "amount": 750218.0,
                                      "text": "$750,218 short of target"},
    },
    "historical_heuristic_curve": {"by_week": {}, "proxy_targets": {},
                                   "heuristic": True, "label": "HEURISTIC",
                                   "note": "HEURISTIC."},
    "note": "HEURISTIC curve note.",
}


async def _run(fixture):
    with patch("pipeline_coverage.assess_pipeline_coverage", return_value=dict(fixture)):
        return await handlers.query_pipeline_coverage({}, MagicMock())


def test_synthesis_note_shows_explicit_subtraction_for_both_comparisons():
    """THE FIX'S PROOF — tonight's exact numbers. _synthesis_note must
    contain the full equation, not just the delta, for BOTH raw and
    weighted."""
    print("\n[TEST] _synthesis_note shows explicit gap-to-goal subtraction "
          "(raw and weighted)")
    result = asyncio.run(_run(TONIGHT_FIXTURE))

    note = result.get("_synthesis_note")
    assert note, "expected a _synthesis_note instructing the model to show the arithmetic"

    weighted_equation = "$1,550,000 quota - $799,782 weighted pipeline = $750,218 short"
    raw_equation = "$1,550,000 quota - $900,000 raw qualified pipeline = $650,000 short"
    assert weighted_equation in note, (
        f"REGRESSION: expected the explicit weighted equation in _synthesis_note, "
        f"got:\n{note}")
    assert raw_equation in note, (
        f"REGRESSION: expected the explicit raw equation in _synthesis_note, "
        f"got:\n{note}")
    print(f"  ✓ weighted equation present: {weighted_equation!r}")
    print(f"  ✓ raw equation present: {raw_equation!r}")


def test_over_target_direction_wording():
    """When pipeline EXCEEDS quota, the equation must read value - quota =
    amount over (not quota - value, which would be a negative, confusing
    read) — direction must follow gap_to_goal's own status, not be
    hardcoded to the short-target case."""
    print("\n[TEST] 'over target' equation reads value - quota = amount over")
    import copy
    fixture = copy.deepcopy(TONIGHT_FIXTURE)
    fixture["stage_weighting"]["weighted_value"] = 2000000.0
    fixture["gap_to_goal"]["weighted_pipeline_vs_goal"] = {
        "status": "over", "amount": 450000.0, "text": "$450,000 over target"}

    result = asyncio.run(_run(fixture))
    note = result["_synthesis_note"]
    expected = "$2,000,000 weighted pipeline - $1,550,000 quota = $450,000 over"
    assert expected in note, f"expected {expected!r} in:\n{note}"
    print(f"  ✓ over-target equation present: {expected!r}")


def test_no_synthesis_note_fabricated_without_a_quota():
    """No team quota configured (real_target.quota is None) — gap_to_goal's
    own fields are None too (per _gap_to_goal's None-propagation). Must not
    fabricate an equation, must not crash building the note."""
    print("\n[TEST] no quota configured -> no fabricated equation, no crash")
    import copy
    fixture = copy.deepcopy(TONIGHT_FIXTURE)
    fixture["real_target"]["quota"] = None
    fixture["real_target"]["goal"] = None
    fixture["gap_to_goal"]["raw_pipeline_vs_goal"] = None
    fixture["gap_to_goal"]["weighted_pipeline_vs_goal"] = None

    result = asyncio.run(_run(fixture))
    assert "_synthesis_note" not in result, (
        f"expected no _synthesis_note when there is no quota to subtract "
        f"against, got: {result.get('_synthesis_note')!r}")
    print("  ✓ no _synthesis_note fabricated when quota/gap data is unavailable")


def test_synthesis_note_not_leaked_into_cache_payload():
    """_synthesis_note is a per-turn synthesis instruction, not citable
    structured data — must stay a top-level sibling of cache_payload, the
    same convention query_waterfall's _headline_instruction already
    follows, never copied INTO cache_payload itself."""
    print("\n[TEST] _synthesis_note stays out of cache_payload")
    result = asyncio.run(_run(TONIGHT_FIXTURE))
    assert "_synthesis_note" in result
    assert "_synthesis_note" not in result["cache_payload"], (
        "the gap-arithmetic instruction leaked into cache_payload — it "
        "must stay a top-level, per-turn-only field")
    print("  ✓ _synthesis_note present at top level, absent from cache_payload")


def test_rep_attainment_gets_no_synthesis_note_regression():
    """REGRESSION GUARD (task item 7): query_rep_attainment shares the same
    generic synthesis scaffolding (_VOICE_BASE/TABLE_FORMAT_RULE) but has
    no gap_to_goal field of its own — this fix must not have added a
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
