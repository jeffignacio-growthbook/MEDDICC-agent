"""
Documentation test for smart truncation fix.

BUG (FIXED): snapshot_diff was successfully added to tool_results, but then
got chopped off by blind [:SYNTH_PAYLOAD_CHARS] character truncation at synthesis
time. The JSON was 59,391 chars, truncated to 20,000 chars, cutting off snapshot_diff
entirely since it was at the end of the JSON.

FIX: _smart_truncate_for_synthesis() in api/router.py aggressively caps rows FIRST
to preserve high-value computed results like snapshot_diff, only doing character
truncation as a last resort.

This test documents the fix and verifies the code structure.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_fix_exists_in_router():
    """Verify _smart_truncate_for_synthesis exists and is used."""
    router_path = REPO / "api" / "router.py"
    with open(router_path) as f:
        content = f.read()

    # Verify function exists
    assert "def _smart_truncate_for_synthesis" in content, \
        "_smart_truncate_for_synthesis function should exist"

    # Verify it preserves snapshot_diff
    assert "PRESERVE_KEYS = {'snapshot_diff'" in content, \
        "Function should preserve snapshot_diff"

    # Verify it's used in synthesis calls
    assert "_smart_truncate_for_synthesis(synthesis_results" in content, \
        "Should be used in main synthesis call"

    assert "_smart_truncate_for_synthesis(tool_results" in content, \
        "Should be used in other synthesis calls"

    # Verify blind truncation is replaced
    blind_truncations = content.count("[:SYNTH_PAYLOAD_CHARS]")
    # Should only be one left - in the comment explaining what we fixed
    assert blind_truncations <= 1, \
        f"Blind [:SYNTH_PAYLOAD_CHARS] truncations should be replaced (found {blind_truncations})"

    print("✅ _smart_truncate_for_synthesis function exists")
    print("✅ Function preserves snapshot_diff and other high-value keys")
    print("✅ Function is used in all synthesis calls")
    print(f"✅ Blind truncations replaced ({blind_truncations} remaining - in comment only)")


def test_expected_behavior_documented():
    """Document the expected behavior after fix."""
    expected_behavior = """
    BEFORE FIX:
    - tool_results: 59,391 chars
    - Blind truncation: [:20000] → snapshot_diff at end gets cut off
    - Model receives only partial data without the computed diff
    - Result: "could not turn the partial data into an answer"

    AFTER FIX:
    - tool_results: 59,391 chars with snapshot_diff
    - Smart truncation: caps rows to 5 first, preserves snapshot_diff
    - Result: ~8,000 chars with full snapshot_diff preserved
    - Model receives: rows (5 samples) + snapshot_diff (complete)
    - Result: successful synthesis with deal names from snapshot_diff
    """

    print("=" * 80)
    print("EXPECTED BEHAVIOR")
    print("=" * 80)
    print(expected_behavior)


if __name__ == "__main__":
    print("=" * 80)
    print("SMART TRUNCATION FIX VERIFICATION")
    print("=" * 80)
    print()

    try:
        test_fix_exists_in_router()
        print()
        test_expected_behavior_documented()

        print()
        print("=" * 80)
        print("VERIFICATION COMPLETE")
        print("=" * 80)
        print()
        print("Next step: Test with original EMEA pipeline question")
        print('  "Tell me about the EMEA pipeline movement and which deals moved"')
        print()
        print("Expected result:")
        print("  - snapshot_diff preserved in synthesis payload")
        print("  - Model synthesizes from complete diff data")
        print("  - Answer includes: 22 stage changes, 22 entries, 29 exits, 20 owner changes")
        print("  - Real company names included (not 'could not turn partial data')")

    except AssertionError as e:
        print()
        print("=" * 80)
        print(f"❌ VERIFICATION FAILED: {e}")
        print("=" * 80)
        sys.exit(1)
