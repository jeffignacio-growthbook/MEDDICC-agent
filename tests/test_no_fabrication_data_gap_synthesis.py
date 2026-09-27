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
# Regression: a large result that ACTUALLY triggers character truncation
# ---------------------------------------------------------------------------

def _large_changes_result(n_deals: int) -> dict:
    result = copy.deepcopy(_MOVEMENT_RESULT)
    result["changes"] = [
        {
            "deal_id": f"deal-{i:03d}",
            "deal_name": f"Acme Corp Deal {i:03d}",
            "direction": "advanced",
            "prior_stage": "Discovery",
            "current_stage": "Qualified",
            "deal_value": 50000 + i * 1000,
        }
        for i in range(n_deals)
    ]
    return result


def test_planted_bug_50_deals_does_not_trigger_truncation():
    """Planted-bug baseline: 50-deal payload is ~10K chars, well under the
    20K classifier limit. The old test was NOT proving truncation resistance —
    it never triggered the character-truncation code path at all.
    This test documents that gap explicitly."""
    import json
    r = _large_changes_result(50)
    indented = json.dumps(r, indent=2)
    assert len(indented) < 20000, (
        f"50-deal payload is unexpectedly large ({len(indented)} chars). "
        "This test documents it does NOT trigger truncation."
    )


def test_planted_bug_200_deals_without_fix_drops_data_gap():
    """Planted-bug control for the real truncation scenario:
    200 deals → ~40K chars indented → character truncation fires.
    Without the front-load fix, data_gaps appears AFTER all of changes[]
    in the JSON and is silently cut by full_json[:20000].

    This test verifies that the naive truncation ([:20000] of the original
    JSON) would drop data_gaps — confirming the bug we fixed was real."""
    import json
    r = _large_changes_result(200)
    indented = json.dumps(r, indent=2, default=str)
    assert len(indented) > 20000, (
        f"200-deal payload must exceed 20K chars to trigger truncation; "
        f"got {len(indented)} chars."
    )
    # Naive character truncation: data_gaps appears after changes[] in JSON
    naive_truncated = indented[:20000]
    assert GAP_MESSAGE not in naive_truncated, (
        "Planted-bug baseline: data_gaps should NOT appear in a naive "
        "[:20000] cut of a 200-deal payload — this baseline failing means "
        "the JSON ordering assumption changed."
    )


def test_data_gap_survives_when_changes_list_triggers_real_truncation():
    """After the fix: even when the changes list is large enough to actually
    trigger character truncation (200 deals → ~40K chars), data_gaps must
    survive because _smart_truncate_for_synthesis front-loads it before cutting.

    This is the REAL truncation-resistance test — the 50-deal version never
    triggered the character-truncation code path at all."""
    r = _large_changes_result(200)

    # Loop path: structured handlers are never truncated — always safe
    loop_text = _loop_serialized(r)
    assert GAP_MESSAGE in loop_text, (
        "data_gap dropped in loop path (structured handler — should always be full)."
    )

    # Classifier path: THIS is where truncation fires. The fix must front-load
    # data_gaps so it survives the [:char_limit] cut.
    classifier_text = _classifier_serialized(r)
    assert GAP_MESSAGE in classifier_text, (
        "data_gap dropped by character truncation in classifier path. "
        "_smart_truncate_for_synthesis must front-load data_gaps before cutting.\n"
        f"Classifier text first 500 chars: {classifier_text[:500]!r}"
    )


# ---------------------------------------------------------------------------
# Fix 1: single-gap emission — no duplicate messages when valid_prior is empty
# ---------------------------------------------------------------------------

def test_single_gap_emitted_when_no_valid_prior():
    """When the oldest snapshot is more recent than the requested target date,
    exactly ONE gap message must be emitted (not two).

    Old bug: the 'no snapshot old enough' branch appended one gap, then the
    span-check below it fired unconditionally and appended a second, redundant
    message for the same situation. One message is what the model needs."""
    from api.handlers import _pm_select_snapshot_anchors
    dates = ["2026-09-17", "2026-09-24"]  # only 7 days, user wants 21
    _, _, gaps = _pm_select_snapshot_anchors(dates, requested_days=21)
    assert len(gaps) == 1, (
        f"Expected exactly 1 gap message when oldest snapshot is too recent, "
        f"got {len(gaps)}: {gaps!r}"
    )
    assert "21" in gaps[0] or "Requested" in gaps[0], (
        f"Gap message should name the requested window: {gaps[0]!r}"
    )


def test_no_gap_emitted_when_window_exactly_matches():
    """When the anchor snapshot lands exactly on the target date (≤ 2-day
    tolerance), no gap is emitted — clean window, no disclosure needed."""
    from api.handlers import _pm_select_snapshot_anchors
    dates = ["2026-09-03", "2026-09-10", "2026-09-17", "2026-09-24"]
    # requested_days=21, target = Sep 24 - 21 = Sep 3 — exact match
    _, _, gaps = _pm_select_snapshot_anchors(dates, requested_days=21)
    assert gaps == [], f"Expected no gaps for exact anchor match, got: {gaps!r}"


def test_single_gap_emitted_when_valid_prior_but_span_drifts():
    """When a valid prior IS found but the actual span differs by > 2 days,
    exactly ONE span-mismatch gap is emitted (the 'oldest snapshot' branch
    did not fire)."""
    from api.handlers import _pm_select_snapshot_anchors
    # Snapshots: Aug 10, Aug 24. requested_days=14 → target=Aug 10 (Sep 24-14).
    # Wait, let me use: current=Sep 24, requested=14 → target=Sep 10.
    # Only Aug 24 is ≤ Sep 10 → prior=Aug 24, actual=31 days, |31-14|>2 → gap.
    dates = ["2026-08-24", "2026-09-24"]
    _, _, gaps = _pm_select_snapshot_anchors(dates, requested_days=14)
    assert len(gaps) == 1, (
        f"Expected exactly 1 gap for span mismatch, got {len(gaps)}: {gaps!r}"
    )
    assert "14" in gaps[0] or "Requested" in gaps[0] or "days" in gaps[0], gaps[0]


# ---------------------------------------------------------------------------
# Fix 2: synthesis prompt generality — both gap shapes must be covered
# ---------------------------------------------------------------------------

def test_voice_base_has_general_data_gaps_surface_rule():
    """_VOICE_BASE must instruct the model to surface ANY data_gaps entry
    verbatim, not only the 'NO SNAPSHOT EXISTS for [date]' shape.

    The original rule was pattern-matched to that specific string, so
    window-shortfall messages ('Requested N-day window, but oldest snapshot
    is...') were silently absorbed — the model reported results without
    disclosing the window shortfall to the user."""
    vb = router._VOICE_BASE
    # Must have the general rule — look for the always/verbatim instruction
    assert "verbatim" in vb.lower(), (
        "_VOICE_BASE lacks a 'verbatim' instruction for data_gaps — "
        "the rule only fires on specific message shapes."
    )
    assert "always" in vb.lower(), (
        "_VOICE_BASE lacks an 'always' qualifier for data_gaps surfacing."
    )


def test_voice_base_covers_window_shortfall_gap_shape():
    """_VOICE_BASE must mention the window-shortfall pattern explicitly
    so the model recognises 'Requested N-day window' as a gap to surface."""
    vb = router._VOICE_BASE
    assert "window" in vb.lower() and ("shortfall" in vb.lower() or "shorter" in vb.lower()), (
        "_VOICE_BASE does not name the window-shortfall gap shape — "
        "the model may still silently absorb 'Requested N-day window' messages."
    )


def test_dynamic_system_prompt_surfaces_data_gaps_verbatim():
    """DYNAMIC_SYSTEM_PROMPT must instruct the model to surface every data_gaps
    entry verbatim — not just prohibit fabrication when a gap is present."""
    dsp = router.DYNAMIC_SYSTEM_PROMPT
    assert "verbatim" in dsp.lower(), (
        "DYNAMIC_SYSTEM_PROMPT lacks a 'verbatim' surfacing instruction — "
        "the model receives the prohibition but not the explicit surfacing directive."
    )


# ---------------------------------------------------------------------------
# Both gap shapes survive serialization — the "NO SNAPSHOT EXISTS" case
# ---------------------------------------------------------------------------

# Second gap message shape: the waterfall/composition 'NO SNAPSHOT EXISTS'
_NO_SNAPSHOT_GAP = (
    "NO SNAPSHOT EXISTS for 2026-09-01. "
    "The earliest real snapshot in the requested range is 2026-09-08 "
    "(marked is_start_anchor=True in the grid). "
    "NEVER estimate, interpolate, or derive counts for 2026-09-01 or any "
    "date not present in the grid. Report real counts from 2026-09-08 with "
    "a clear disclosure that this is the earliest real data point."
)

_MOVEMENT_WITH_NO_SNAPSHOT_GAP = {
    "snap_dates": ["2026-09-08", "2026-10-06"],
    "changes": [
        {
            "deal_id": "deal-x",
            "deal_name": "Omega Corp",
            "direction": "advanced",
            "prior_stage": "Discovery",
            "current_stage": "Qualified",
            "deal_value": 80000,
        }
    ],
    "data_gaps": [_NO_SNAPSHOT_GAP],
    "total_advanced": 1,
    "total_regressed": 0,
    "_synthesis_note": "Earliest real snapshot is Sep 8, not Sep 1 — see data_gaps.",
}


def test_no_snapshot_exists_gap_survives_loop_serialization():
    """The 'NO SNAPSHOT EXISTS' gap shape must survive loop-path serialization.
    Both gap shapes — window shortfall AND missing snapshot — must reach the model."""
    text = _loop_serialized(result=_MOVEMENT_WITH_NO_SNAPSHOT_GAP)
    assert "NO SNAPSHOT EXISTS" in text, (
        "'NO SNAPSHOT EXISTS' gap was dropped by _serialize_tool_result_for_synthesis.\n"
        f"Serialized text (first 500 chars):\n  {text[:500]!r}"
    )


def test_no_snapshot_exists_gap_survives_classifier_serialization():
    """The 'NO SNAPSHOT EXISTS' gap shape must survive the classifier path
    (_cap_rows_for_synthesis + _smart_truncate_for_synthesis)."""
    text = _classifier_serialized(result=_MOVEMENT_WITH_NO_SNAPSHOT_GAP)
    assert "NO SNAPSHOT EXISTS" in text, (
        "'NO SNAPSHOT EXISTS' gap was dropped during classifier synthesis serialization.\n"
        f"Serialized text (first 500 chars):\n  {text[:500]!r}"
    )


def test_both_gap_shapes_survive_loop_path():
    """Both gap shapes — window shortfall (GAP_MESSAGE) and 'NO SNAPSHOT EXISTS'
    — must survive loop-path serialization simultaneously. If either is dropped,
    the model will fabricate for that scenario."""
    window_shortfall_result = copy.deepcopy(_MOVEMENT_RESULT)
    window_shortfall_result["data_gaps"].append(_NO_SNAPSHOT_GAP)
    text = _loop_serialized(result=window_shortfall_result)
    assert GAP_MESSAGE in text, (
        "Window-shortfall gap dropped from loop serialization with both shapes present."
    )
    assert "NO SNAPSHOT EXISTS" in text, (
        "'NO SNAPSHOT EXISTS' gap dropped from loop serialization with both shapes present."
    )


def test_both_gap_shapes_survive_classifier_path():
    """Both gap shapes survive the classifier path simultaneously."""
    combined_result = copy.deepcopy(_MOVEMENT_RESULT)
    combined_result["data_gaps"].append(_NO_SNAPSHOT_GAP)
    text = _classifier_serialized(result=combined_result)
    assert GAP_MESSAGE in text, (
        "Window-shortfall gap dropped from classifier path with both shapes present."
    )
    assert "NO SNAPSHOT EXISTS" in text, (
        "'NO SNAPSHOT EXISTS' gap dropped from classifier path with both shapes present."
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
    test_planted_bug_50_deals_does_not_trigger_truncation()
    print("PASS: 50-deal baseline confirms truncation was never triggered")
    test_planted_bug_200_deals_without_fix_drops_data_gap()
    print("PASS: planted-bug confirms naive [:20000] cut drops data_gaps")
    test_data_gap_survives_when_changes_list_triggers_real_truncation()
    print("PASS: data_gap survives real character truncation (200 deals)")
    # Fix 1: single-gap emission
    test_single_gap_emitted_when_no_valid_prior()
    print("PASS: single gap emitted when no valid prior (no double message)")
    test_no_gap_emitted_when_window_exactly_matches()
    print("PASS: no gap emitted when anchor matches within 2 days")
    test_single_gap_emitted_when_valid_prior_but_span_drifts()
    print("PASS: single gap emitted when valid prior found but span drifts")
    # Fix 2: synthesis prompt generality
    test_voice_base_has_general_data_gaps_surface_rule()
    print("PASS: _VOICE_BASE has general always-surface-verbatim rule")
    test_voice_base_covers_window_shortfall_gap_shape()
    print("PASS: _VOICE_BASE explicitly covers window-shortfall gap shape")
    test_dynamic_system_prompt_surfaces_data_gaps_verbatim()
    print("PASS: DYNAMIC_SYSTEM_PROMPT instructs verbatim surfacing")
    # Both shapes survive serialization
    test_no_snapshot_exists_gap_survives_loop_serialization()
    print("PASS: NO SNAPSHOT EXISTS gap survives loop serialization")
    test_no_snapshot_exists_gap_survives_classifier_serialization()
    print("PASS: NO SNAPSHOT EXISTS gap survives classifier serialization")
    test_both_gap_shapes_survive_loop_path()
    print("PASS: both gap shapes survive loop path simultaneously")
    test_both_gap_shapes_survive_classifier_path()
    print("PASS: both gap shapes survive classifier path simultaneously")
    print("\nAll tests passed.")
