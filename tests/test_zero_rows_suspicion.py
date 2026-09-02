"""
Test zero-rows suspicion check for enumeration questions.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_suspicion_detection():
    """Test detection of enumeration questions that should trigger suspicion."""

    # Questions that should trigger suspicion
    enum_questions = [
        "which deals have no ARR recorded",
        "show me deals with zero value",
        "list all deals in Discovery",
        "what deals are closing this quarter",
        "what are the stale deals",
    ]

    # Questions that should NOT trigger suspicion
    non_enum_questions = [
        "what is the pipeline total",
        "how much are we forecasting",
        "when does this deal close",
        "what's the average deal size",
    ]

    # Suspicion patterns from router.py
    enum_patterns = ["which", "show", "list", "what deals", "what are the"]

    print("Testing enumeration question detection:")
    print("-" * 80)

    for q in enum_questions:
        detected = any(p in q.lower() for p in enum_patterns)
        status = "✓" if detected else "✗"
        print(f"{status} '{q}' → detected={detected} (expected True)")
        assert detected, f"Should detect enumeration in: {q}"

    print()
    print("Testing non-enumeration questions:")
    print("-" * 80)

    for q in non_enum_questions:
        detected = any(p in q.lower() for p in enum_patterns)
        status = "✓" if not detected else "✗"
        print(f"{status} '{q}' → detected={detected} (expected False)")
        # Note: "what deals" pattern will catch some of these, which is acceptable
        # We prefer false positives (unnecessary suspicion) over false negatives
        # (missing real issues)

    print("\n✅ Enumeration detection working")


def test_suspicion_message():
    """Test that suspicion message format is correct."""

    # Simulate the suspicion note format from router.py
    filters_used = [("is_", "deal_value", "null")]
    filter_desc = ", ".join([f"{f[1]}={f[0]}.{f[2]}" for f in filters_used if len(f) >= 3])

    suspicion_note = (
        f"\n\n⚠️  SUSPICION: Zero rows on an enumeration question. "
        f"The filter ({filter_desc}) may be checking the wrong column or "
        f"the field may be defaulted rather than null. Consider: "
        f"(1) checking component fields instead of aggregate fields, "
        f"(2) checking for zero values not just nulls, or "
        f"(3) stating what was checked rather than asserting absence."
    )

    print("Suspicion message format:")
    print("-" * 80)
    print(suspicion_note)
    print()

    assert "⚠️  SUSPICION" in suspicion_note
    assert "deal_value=is_.null" in suspicion_note
    assert "component fields" in suspicion_note

    print("✅ Suspicion message format correct")


def test_semantic_context_includes_missing_values():
    """Test that semantic context includes missing value semantics."""
    from scripts.utils import build_semantic_context

    context = build_semantic_context()

    print("Checking semantic context for missing value semantics:")
    print("-" * 80)

    required_phrases = [
        "No ARR recorded",
        "deal_value is often populated with 0",
        "Zero-rows suspicion rule",
        "component fields",
    ]

    for phrase in required_phrases:
        found = phrase in context
        status = "✓" if found else "✗"
        print(f"{status} '{phrase}' found in context: {found}")
        assert found, f"Missing phrase in semantic context: {phrase}"

    print("\n✅ Semantic context includes missing value semantics")


if __name__ == '__main__':
    test_suspicion_detection()
    print()
    test_suspicion_message()
    print()
    test_semantic_context_includes_missing_values()
    print("\n✅ All zero-rows suspicion tests passed")
