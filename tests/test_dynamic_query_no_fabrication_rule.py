"""
DYNAMIC_SYSTEM_PROMPT must contain a hard no-fabrication rule for data gaps.

The dynamic-query loop uses DYNAMIC_SYSTEM_PROMPT as its system context.
When tool results contain data_gaps (e.g., "NO SNAPSHOT EXISTS for date X"),
the model must NOT fabricate, interpolate, or estimate a number for that date.

The synthesis-path handler (_VOICE_BASE) already contains the
COMPOSITION GRID — NO ESTIMATION RULE. The dynamic-query loop
had only the weaker "Never invent numbers" line with no hard-prohibition
block naming the specific pattern (data_gap → decline, not estimate).

This test suite verifies the hard rule is present and machine-checkable.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api.router as router


def _dsp() -> str:
    return router.DYNAMIC_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Presence checks — the rule must be in the prompt at all
# ---------------------------------------------------------------------------

def test_dynamic_prompt_contains_no_fabrication_keyword():
    """A hard 'no fabrication' rule must exist in DYNAMIC_SYSTEM_PROMPT —
    not just 'Never invent numbers' but an explicit prohibition block
    covering data-gap / missing-snapshot scenarios."""
    dsp = _dsp()
    keywords = ["fabricat", "NO FABRICATION", "no fabrication",
                "hard prohibition", "HARD PROHIBITION"]
    assert any(kw.lower() in dsp.lower() for kw in keywords), (
        "DYNAMIC_SYSTEM_PROMPT has no hard-prohibition / no-fabrication "
        "language for data-gap scenarios. Add a DATA-GAP / MISSING SNAPSHOT "
        "— NO FABRICATION RULE block mirroring _VOICE_BASE."
    )


def test_dynamic_prompt_prohibits_interpolation():
    """The rule must explicitly prohibit interpolation and estimation."""
    dsp = _dsp()
    forbidden_patterns = ["interpolat", "estimat"]
    assert any(fp in dsp.lower() for fp in forbidden_patterns), (
        "DYNAMIC_SYSTEM_PROMPT must explicitly name 'interpolat' or 'estimat' "
        "as prohibited in the no-fabrication rule, so the model recognises "
        "hedged guesses (~ / est. / approximately) as violations."
    )


def test_dynamic_prompt_instructs_to_decline_not_estimate():
    """The rule must say a plain decline is preferable to any fabricated number."""
    dsp = _dsp()
    decline_phrases = ["plain decline", "decline", "say so plainly", "say so plain",
                       "prefer.*decline", "rather than.*estimat"]
    import re
    assert any(re.search(p, dsp, re.IGNORECASE) for p in decline_phrases), (
        "DYNAMIC_SYSTEM_PROMPT must instruct the model that a plain decline "
        "('no data for that date') is always preferable to a fabricated number."
    )


def test_dynamic_prompt_covers_data_gap_scenario():
    """The rule must mention 'data_gap' or 'data gap' or 'missing snapshot'
    so it is clearly tied to the tool-result field name."""
    dsp = _dsp()
    assert any(kw in dsp.lower() for kw in ["data_gap", "data gap", "missing snapshot"]), (
        "DYNAMIC_SYSTEM_PROMPT no-fabrication rule must reference 'data_gap' "
        "or 'missing snapshot' by name to link it to the tool-result field."
    )


# ---------------------------------------------------------------------------
# Regression — the weaker original rules must still be present
# ---------------------------------------------------------------------------

def test_dynamic_prompt_still_has_never_invent_numbers():
    """The original 'Never invent numbers' line must survive the addition."""
    dsp = _dsp()
    assert "never invent numbers" in dsp.lower(), (
        "'Never invent numbers' rule was removed — it must be preserved alongside "
        "the new hard-prohibition block."
    )


if __name__ == "__main__":
    test_dynamic_prompt_contains_no_fabrication_keyword()
    print("PASS: no-fabrication keyword present")
    test_dynamic_prompt_prohibits_interpolation()
    print("PASS: interpolation/estimation explicitly prohibited")
    test_dynamic_prompt_instructs_to_decline_not_estimate()
    print("PASS: plain decline preferred over fabrication")
    test_dynamic_prompt_covers_data_gap_scenario()
    print("PASS: data_gap / missing snapshot scenario named")
    test_dynamic_prompt_still_has_never_invent_numbers()
    print("PASS: original never-invent-numbers preserved")
    print("\nAll tests passed.")
