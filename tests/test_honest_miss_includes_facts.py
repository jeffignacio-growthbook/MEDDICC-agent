"""
2026-09-11: fixing PENDING_WORK.md Low Priority #9 item 2 (eval_bestseller_
incident.py crashing on a type mismatch in _honest_miss()) surfaced a
second, independent, pre-existing gap hiding behind that crash: even once
the crash was fixed, _honest_miss()'s real output never actually stated
what came back, despite _result_summary() (api/router.py:86) — its own
sibling, computed one line above it in the only real call site
(api/router.py:5123-5129) and used there ONLY for the internal log line —
being explicitly docstring'd as "for the honest-miss message." The
user-facing text and the log describing the same event said different
things. This has been true since both functions were authored together
in commit b75a3c1 (2026-09-06); the eval assertion checking for this
never actually ran until tonight, because the type-mismatch crash always
short-circuited before reaching it.

This is a real, deliberate user-facing behavior change, not just a bug
fix — worth its own dedicated regression lock rather than relying only on
eval_bestseller_incident.py's broader incident-fix sweep.

BEFORE (generic, no facts):
    entity_count=0 -> "I couldn't answer that confidently. Try asking
                        about a specific deal or company, and I'll pull
                        its details directly."
    entity_count=2 -> "I couldn't work out the answer for those 2 deals
                        — I found them but couldn't confirm what you
                        asked about. Try naming one specifically and
                        I'll pull its details."

AFTER (states the same facts the log already knows):
    entity_count=0, tool_results={"deals": []}
        -> "I couldn't answer that confidently — no matching rows came
            back. Try asking about a specific deal or company, and I'll
            pull its details directly."
    entity_count=2, tool_results={"deals": []}
        -> "I couldn't work out the answer for those 2 deals — no
            matching rows came back. Try naming one specifically and
            I'll pull its details."
    entity_count=0, tool_results={"scores": [1, 2]}
        -> "I couldn't answer that confidently — 2 rows came back. Try
            asking about a specific deal or company, and I'll pull its
            details directly."
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

from api.router import _honest_miss, _result_summary


def test_honest_miss_states_empty_result_fact():
    msg = _honest_miss("query_deal_health", 0, {"deals": []})
    assert "no matching rows came back" in msg, (
        f"expected the fact _result_summary computes for an empty list — got: {msg!r}")
    assert "couldn't answer" in msg.lower()
    print("✓ empty-result honest-miss states the fact, not a generic miss")


def test_honest_miss_states_row_count_fact():
    msg = _honest_miss("query_deal_health", 0, {"scores": [1, 2]})
    assert "2 rows came back" in msg, f"expected the real row count — got: {msg!r}"
    print("✓ non-empty-result honest-miss states the real row count")


def test_honest_miss_entity_scoped_still_states_the_fact():
    """The entity-scoped branch (a follow-up about specific deals) must not
    lose the fact-stating behavior just because it also names the deal
    count."""
    msg = _honest_miss("query_deal_health", 2, {"deals": []})
    assert "2 deals" in msg
    assert "no matching rows came back" in msg, (
        f"entity-scoped branch dropped the fact — got: {msg!r}")
    print("✓ entity-scoped honest-miss still states the fact alongside the deal count")


def test_honest_miss_message_matches_the_log_line_fact():
    """The user-facing message and the internal log line describing the
    same below-floor event (api/router.py:5125-5129) must agree on the
    facts — not silently diverge the way they did before this fix."""
    tool_results = {"rows": [1, 2, 3]}
    logged_fact = _result_summary(tool_results)
    msg = _honest_miss("query_pipeline", 0, tool_results)
    assert logged_fact in msg, (
        f"user-facing message ({msg!r}) doesn't contain the same fact "
        f"the log line computes ({logged_fact!r})")
    print("✓ the user-facing message states the same fact the log line already knows")


def test_honest_miss_still_has_no_speculative_language():
    """Regression guard: adding real facts must not reopen the door to
    speculative causes the original design explicitly forbade."""
    SPECULATION = ["might not exist", "might be", "may be", "could be",
                   "possibly", "perhaps", "named differently", "below a",
                   "below the score", "threshold"]
    msg = _honest_miss("query_deal_health", 0, {"deals": []}).lower()
    hits = [s for s in SPECULATION if s in msg]
    assert not hits, f"honest-miss message contains speculative language: {hits}"
    print("✓ honest-miss still avoids speculative language after adding facts")


if __name__ == "__main__":
    tests = [
        test_honest_miss_states_empty_result_fact,
        test_honest_miss_states_row_count_fact,
        test_honest_miss_entity_scoped_still_states_the_fact,
        test_honest_miss_message_matches_the_log_line_fact,
        test_honest_miss_still_has_no_speculative_language,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"✗ {t.__name__}: {e}")
    if failed:
        print(f"\n{failed}/{len(tests)} tests FAILED")
        sys.exit(1)
    print(f"\n✅ All {len(tests)} tests passed")
