"""
DATA-GAP / MISSING SNAPSHOT — NO FABRICATION: end-to-end synthesis guarantee.

Three guarantees, all tested here:

1. data_gaps survive into the dynamic-loop synthesis input
   (the result JSON the model reads, built by _serialize_tool_result_for_synthesis).
2. data_gaps survive into the classifier synthesis input
   (_smart_truncate_for_synthesis(_cap_rows_for_synthesis(result))).
3. For the dynamic-loop path, the system prompt that accompanies the result
   (DYNAMIC_SYSTEM_PROMPT) contains the hard no-fabrication rule — so the
   model receives BOTH the gap signal and the prohibition together.

This mirrors the disclosure-survival suite (test_quarter_health_disclosure_survival.py):
it tests prompt construction, not LLM output. The guarantee is:
  "The model is told about the gap AND told not to fabricate" — the only
  offline-verifiable part of the no-fabrication contract.

Scenario: shaped like the real January-comparison case.
  User asks "deal changes in the last 4 weeks".
  Available snapshots only go back 7 days (one week).
  _pm_view_deal_changes emits a data_gap disclosing the shortfall.
  That disclosure must reach the model in both routing paths.

Why this matters:
  Without this test, we can only confirm the rule text lives in the prompt string.
  We cannot confirm that a real data_gap (from a real handler call) survives the
  two serialization/truncation steps that sit between the handler result and the
  model's context window. A gap that is silently dropped means the model writes
  an answer with zero prohibition signal and no gap signal — pure fabrication risk.
"""
import copy
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
logging.disable(logging.CRITICAL)

import api.router as router
import api.evaluator as evaluator


# ---------------------------------------------------------------------------
# Fixture: a realistic query_pipeline_movement result with a data_gap
# ---------------------------------------------------------------------------

GAP_MESSAGE = (
    "Requested 28-day window (2026-09-08 to 2026-10-06) exceeds available history. "
    "Oldest snapshot: 2026-09-30. Showing 7-day window (2026-09-30 to 2026-10-06) only."
)

# One deal visible in the short window (not a fabricated earlier reading)
_MOVEMENT_RESULT = {
    "snap_dates": ["2026-09-30", "2026-10-06"],
    "changes": [
        {
            "deal_id": "deal-jan",
            "deal_name": "Acme Corp",
            "direction": "advanced",
            "prior_stage": "Discovery",
            "current_stage": "Qualified",
            "deal_value": 120000,
        }
    ],
    "data_gaps": [GAP_MESSAGE],
    "total_advanced": 1,
    "total_regressed": 0,
    "_synthesis_note": "Window is 7 days, not 28 as requested — see data_gaps.",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _loop_serialized(result=None, handler="query_pipeline_movement"):
    """Serialize the way the dynamic loop does: _serialize_tool_result_for_synthesis."""
    r = copy.deepcopy(result or _MOVEMENT_RESULT)
    with patch.dict(evaluator.STRUCTURED_HANDLERS, {handler: ["rows", "data_gaps", "snapshot_dates"]}):
        text, _ = router._serialize_tool_result_for_synthesis(r, handler)
    return text


def _classifier_serialized(result=None):
    """Serialize the way the classifier synthesis does:
    _smart_truncate_for_synthesis(_cap_rows_for_synthesis(result))."""
    r = copy.deepcopy(result or _MOVEMENT_RESULT)
    capped = router._cap_rows_for_synthesis(r)
    return router._smart_truncate_for_synthesis(capped)


# ---------------------------------------------------------------------------
# Point 1: data_gaps survive into the dynamic-loop synthesis input
# ---------------------------------------------------------------------------

def test_data_gap_survives_loop_serialization():
    """The gap message must be present in the JSON the dynamic loop
    builds as the tool-result message the model reads."""
    text = _loop_serialized()
    assert GAP_MESSAGE in text, (
        "data_gap message was dropped by _serialize_tool_result_for_synthesis.\n"
        f"Expected substring:\n  {GAP_MESSAGE!r}\n"
        f"Serialized text (first 500 chars):\n  {text[:500]!r}"
    )


def test_data_gaps_key_survives_loop_serialization():
    """'data_gaps' key itself must be present so the model knows to look for it."""
    text = _loop_serialized()
    assert '"data_gaps"' in text or "'data_gaps'" in text, (
        "'data_gaps' key was dropped from the serialized loop tool result."
    )


# ---------------------------------------------------------------------------
# Point 2: data_gaps survive into the classifier synthesis input
# ---------------------------------------------------------------------------

def test_data_gap_survives_classifier_serialization():
    """The gap message must survive _cap_rows_for_synthesis +
    _smart_truncate_for_synthesis (the classifier synthesis path)."""
    text = _classifier_serialized()
    assert GAP_MESSAGE in text, (
        "data_gap message was dropped during classifier synthesis serialization.\n"
        f"Expected substring:\n  {GAP_MESSAGE!r}\n"
        f"Serialized text (first 500 chars):\n  {text[:500]!r}"
    )


def test_cap_rows_does_not_strip_data_gaps():
    """_cap_rows_for_synthesis must not remove the data_gaps key —
    it is not a row array (deal_ids, rows, etc.) so it must be untouched."""
    r = copy.deepcopy(_MOVEMENT_RESULT)
    capped = router._cap_rows_for_synthesis(r)
    assert "data_gaps" in capped, (
        "'data_gaps' key was removed by _cap_rows_for_synthesis. "
        "It is not a deal-row array and must survive row capping."
    )
    assert capped["data_gaps"] == [GAP_MESSAGE], (
        "data_gaps content was altered by _cap_rows_for_synthesis."
    )


def test_synthesis_note_survives_classifier_serialization():
    """_synthesis_note (the human-readable disclosure) must also survive
    both serialization steps."""
    text = _classifier_serialized()
    assert "7 days, not 28" in text, (
        "_synthesis_note was dropped during classifier synthesis serialization."
    )


# ---------------------------------------------------------------------------
# Point 3: DYNAMIC_SYSTEM_PROMPT contains the hard rule alongside the gap
# ---------------------------------------------------------------------------

def test_dynamic_system_prompt_has_no_fabrication_block():
    """DYNAMIC_SYSTEM_PROMPT must contain the DATA-GAP — NO FABRICATION
    block so the model receives the prohibition at the same time as the gap signal."""
    dsp = router.DYNAMIC_SYSTEM_PROMPT
    assert "NO FABRICATION" in dsp or "no fabrication" in dsp.lower(), (
        "DYNAMIC_SYSTEM_PROMPT has no NO FABRICATION block — model sees the "
        "data_gap but has no prohibition rule."
    )


def test_dynamic_system_prompt_names_data_gap_scenario():
    """The rule must reference 'data_gap' or 'data gaps' so the model links
    the rule to the tool-result field name."""
    dsp = router.DYNAMIC_SYSTEM_PROMPT
    assert "data_gap" in dsp or "data gaps" in dsp.lower(), (
        "DYNAMIC_SYSTEM_PROMPT no-fabrication rule does not name 'data_gap' — "
        "the model cannot link the field to the rule."
    )


def test_dynamic_system_prompt_prohibits_interpolation_and_estimation():
    """The rule must name interpolation and estimation explicitly as prohibited."""
    dsp = router.DYNAMIC_SYSTEM_PROMPT
    assert "interpolat" in dsp.lower() and "estimat" in dsp.lower(), (
        "DYNAMIC_SYSTEM_PROMPT must explicitly name 'interpolat' and 'estimat' "
        "as prohibited in the no-fabrication rule."
    )


# ---------------------------------------------------------------------------
# Compound test: both gap signal AND prohibition are simultaneously visible
# in the loop path (the only path where DYNAMIC_SYSTEM_PROMPT is the system)
# ---------------------------------------------------------------------------

def test_gap_signal_and_rule_both_present_in_loop_synthesis_context():
    """The compound guarantee: the model receives the gap signal (in the tool
    result) AND the prohibition rule (in the system prompt) in the same turn.

    This is the offline-verifiable half of the no-fabrication contract:
      model context = DYNAMIC_SYSTEM_PROMPT (has the rule) +
                      serialized tool result (has the gap)
    Both must be true simultaneously. A gap with no rule is ignored.
    A rule with no gap signal is unreachable (the model has nothing to refuse)."""
    tool_result_text = _loop_serialized()
    system_prompt = router.DYNAMIC_SYSTEM_PROMPT

    # Gap signal reaches the model
    assert GAP_MESSAGE in tool_result_text, (
        "Gap signal missing from tool result — model cannot know data is absent."
    )
    # Rule reaches the model
    assert any(kw in system_prompt.lower() for kw in ["no fabrication", "hard prohibition", "fabricat"]), (
        "No-fabrication rule missing from DYNAMIC_SYSTEM_PROMPT — model has no instruction."
    )
    # Rule explicitly covers the data_gap field name
    assert "data_gap" in system_prompt or "data gaps" in system_prompt.lower(), (
        "DYNAMIC_SYSTEM_PROMPT rule does not link to 'data_gap' field name — "
        "the model may not recognise the field as the triggering condition."
    )


# ---------------------------------------------------------------------------
# Regression: a large result with many deals still preserves the gap
# ---------------------------------------------------------------------------

def test_data_gap_survives_when_changes_list_is_large():
    """When the changes list is large (would trigger row-capping), data_gaps
    must not be sacrificed. Row-capping targets deal arrays, not metadata."""
    large_result = copy.deepcopy(_MOVEMENT_RESULT)
    large_result["changes"] = [
        {
            "deal_id": f"deal-{i}",
            "deal_name": f"Deal {i}",
            "direction": "advanced",
            "prior_stage": "Discovery",
            "current_stage": "Qualified",
            "deal_value": 50000,
        }
        for i in range(50)  # 50 deals — beyond any row cap
    ]
    # Loop path
    loop_text = _loop_serialized(large_result)
    assert GAP_MESSAGE in loop_text, (
        "data_gap dropped in loop path when changes list is large."
    )
    # Classifier path
    classifier_text = _classifier_serialized(large_result)
    assert GAP_MESSAGE in classifier_text, (
        "data_gap dropped in classifier path when changes list is large (row-cap side-effect)."
    )


if __name__ == "__main__":
    test_data_gap_survives_loop_serialization()
    print("PASS: data_gap survives loop serialization")
    test_data_gaps_key_survives_loop_serialization()
    print("PASS: data_gaps key present in loop serialization")
    test_data_gap_survives_classifier_serialization()
    print("PASS: data_gap survives classifier serialization")
    test_cap_rows_does_not_strip_data_gaps()
    print("PASS: _cap_rows_for_synthesis leaves data_gaps intact")
    test_synthesis_note_survives_classifier_serialization()
    print("PASS: _synthesis_note survives classifier serialization")
    test_dynamic_system_prompt_has_no_fabrication_block()
    print("PASS: DYNAMIC_SYSTEM_PROMPT has no-fabrication block")
    test_dynamic_system_prompt_names_data_gap_scenario()
    print("PASS: DYNAMIC_SYSTEM_PROMPT names data_gap scenario")
    test_dynamic_system_prompt_prohibits_interpolation_and_estimation()
    print("PASS: DYNAMIC_SYSTEM_PROMPT prohibits interpolation and estimation")
    test_gap_signal_and_rule_both_present_in_loop_synthesis_context()
    print("PASS: gap signal + rule both present in loop synthesis context")
    test_data_gap_survives_when_changes_list_is_large()
    print("PASS: data_gap survives large changes list (row-cap safety)")
    print("\nAll tests passed.")
