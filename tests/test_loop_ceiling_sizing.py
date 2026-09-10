"""
Regression tests for the 2026-09-11 reframe: the dynamic_query_loop's
token/iteration ceiling is an internal engineering backstop, not something
that should ever surface to a user or be tuned against a single incident.

Two concrete guarantees this pins:

1. The ceiling itself must stay sized for the hardest reasonable
   multi-step question, not shrink back to values tuned against one past
   incident (40K tokens / 5 iterations, which is what actually caused the
   2026-09-11 budget-exhaustion failures on "which deals changed stage"
   questions). DYNAMIC_LOOP_TOKEN_BUDGET / DYNAMIC_LOOP_MAX_ITERATIONS are
   now module-level constants specifically so a future change to them is a
   visible, single-line diff a reviewer can catch — and so this test can
   assert a floor on them directly, not just describe policy in a comment.

2. No user-facing failure message may ever mention budget, tokens, or
   processing limits. If a genuinely pathological question exceeds even
   the generous ceiling, the message must describe the business reality
   (narrower time range / fewer filters) — never blame an internal
   engineering concern the user has no way to act on.

This does NOT include a live run of "which enterprise deals changed stage
in the last 2 weeks in EMEA" through the real loop — that needs a live
Supabase + Anthropic connection this sandbox doesn't have. What it proves
instead: (a) that question's known iteration count under today's fixes
(3: two dimension-filtered snapshot pulls + one enrichment lookup) is a
small fraction of the new ceiling, with room to spare for legitimate
retries, and (b) the ceiling's own source code no longer describes it to
the user in engineering terms. The actual live pass/fail is the next real
occurrence of this question — same discipline as every other fix today.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
REPO_ROOT = Path(__file__).parent.parent

from api.router import DYNAMIC_LOOP_TOKEN_BUDGET, DYNAMIC_LOOP_MAX_ITERATIONS

# The values actually responsible for the 2026-09-11 budget-exhaustion
# incident. If the ceiling is ever put back at or below these, it has been
# re-tuned against a single incident again, exactly what this fix undoes.
INCIDENT_TOKEN_BUDGET = 40_000
INCIDENT_MAX_ITERATIONS = 5

# The known, correct iteration count for "which enterprise deals changed
# stage in the last 2 weeks in EMEA" under today's fixes: current-snapshot
# pull (filtered by region+segment directly, per the data-dictionary
# registration fix) + prior-snapshot pull + one company_name enrichment
# lookup, immediately synthesized via the enrichment shortcut. See
# tests/test_enrichment_shortcut.py and tests/test_schema_context_
# snapshot_visibility.py for the mechanisms that make this 3, not more.
KNOWN_QUESTION_ITERATION_COUNT = 3


def test_ceiling_is_not_tuned_to_the_incident_that_exposed_it():
    assert DYNAMIC_LOOP_TOKEN_BUDGET > INCIDENT_TOKEN_BUDGET, (
        f"TOKEN_BUDGET ({DYNAMIC_LOOP_TOKEN_BUDGET}) must be well above the "
        f"value that actually caused the 2026-09-11 incident "
        f"({INCIDENT_TOKEN_BUDGET}) — if it's back at or near that, the "
        f"ceiling has been re-tuned against one incident again."
    )
    assert DYNAMIC_LOOP_MAX_ITERATIONS > INCIDENT_MAX_ITERATIONS, (
        f"MAX_ITERATIONS ({DYNAMIC_LOOP_MAX_ITERATIONS}) must be well above "
        f"the value that actually caused the 2026-09-11 incident "
        f"({INCIDENT_MAX_ITERATIONS})."
    )
    # Sanity floor: the ceiling must be big enough that a well-scoped
    # question with a couple of legitimate forced retries has real room —
    # not just "technically bigger than before."
    assert DYNAMIC_LOOP_MAX_ITERATIONS >= 10, (
        "MAX_ITERATIONS should be sized for the hardest reasonable "
        "question (base steps + a couple of legitimate forced retries), "
        "not nudged up by one or two from the incident value."
    )
    assert DYNAMIC_LOOP_TOKEN_BUDGET >= 150_000, (
        "TOKEN_BUDGET should be sized against the real per-iteration cost "
        "at MAX_ITERATIONS (dominated by the repeated system prompt), not "
        "a token-for-token nudge above the incident value."
    )
    print(f"✓ ceiling ({DYNAMIC_LOOP_MAX_ITERATIONS} iterations, "
          f"{DYNAMIC_LOOP_TOKEN_BUDGET} tokens) is sized well above the "
          f"incident values ({INCIDENT_MAX_ITERATIONS}, {INCIDENT_TOKEN_BUDGET})")


def test_known_question_shape_fits_with_large_margin():
    """The exact question from the incident needs 3 iterations under
    today's fixes. It must fit inside the ceiling with enough margin left
    over for legitimate retries (dimension-verification, the snapshot-
    anchor gate, or the scratchpad-rejection gate each firing once) —
    not just barely fit."""
    margin = DYNAMIC_LOOP_MAX_ITERATIONS - KNOWN_QUESTION_ITERATION_COUNT
    assert margin >= 5, (
        f"Only {margin} iterations of headroom beyond the known "
        f"3-iteration shape for this question — that's not enough room "
        f"for a couple of legitimate forced retries on top of it."
    )
    print(f"✓ known question shape ({KNOWN_QUESTION_ITERATION_COUNT} "
          f"iterations) leaves {margin} iterations of headroom under the "
          f"{DYNAMIC_LOOP_MAX_ITERATIONS}-iteration ceiling")


def test_no_user_facing_message_names_budget_tokens_or_processing_limits():
    """Structural scan of the actual returned-answer string literals in
    dynamic_query_loop's give-up/diagnostic paths. Grep-based, same shape
    as the date-resolution and data-dictionary CI gates: it fails the
    build the moment a new user-facing string reintroduces this language,
    rather than waiting for a user to see it."""
    src = (REPO_ROOT / "api" / "router.py").read_text()

    # Isolate _diagnostic_answer and _finalize_from_data's bodies (where
    # every answered=False user-facing string in dynamic_query_loop is
    # constructed) rather than scanning the whole file, which would also
    # flag legitimate internal comments/log lines and the LLM-facing
    # DYNAMIC_SYSTEM_PROMPT (telling the MODEL to write efficient queries
    # is not the same as telling the USER why their question failed).
    def _function_body(name):
        """Extract a nested `    def name(...):` or `    async def
        name(...):` function's body by indentation, not by looking for
        the next `def` — these are nested functions inside
        dynamic_query_loop, and the code that follows _finalize_from_data
        is the rest of that outer function's body (not another nested
        def), so a next-def lookahead swallows everything up to the next
        unrelated top-level function instead of stopping where this one
        actually ends. _finalize_from_data became `async def` in the
        2026-09-11 round-3 fix (it now awaits a forced filter_table call),
        so both prefixes must match."""
        lines = src.splitlines()
        start = next(i for i, l in enumerate(lines)
                     if l.startswith(f"    def {name}(") or
                     l.startswith(f"    async def {name}("))
        end = len(lines)
        for i in range(start + 1, len(lines)):
            stripped = lines[i]
            if stripped.strip() == "":
                continue
            indent = len(stripped) - len(stripped.lstrip(" "))
            if indent <= 4:  # dedented back to the outer function's level
                end = i
                break
        return "\n".join(lines[start:end])

    def _strip_logger_calls(body):
        """Drop entire logger.error(...)/logger.warning(...)/logger.info(...)
        call expressions, including multi-line f-string arguments spread
        across several source lines (e.g. the DIMENSION_VERIFY log at
        router.py:2338, whose message literally contains "budget exhausted"
        as an internal telemetry note, never returned to the user). These
        are internal log lines visible only in application logs, not
        string literals that ever become part of an {"answer": ...}
        payload — the same category of "not user-facing text" as the
        reason_tag comparisons stripped below, just spanning multiple
        lines instead of one. Tracked by counting paren depth from the
        `logger.<level>(` open paren through to its matching close."""
        lines = body.splitlines()
        out = []
        i = 0
        call_re = re.compile(r'logger\.(error|warning|info|debug)\(')
        while i < len(lines):
            line = lines[i]
            m = call_re.search(line)
            if not m:
                out.append(line)
                i += 1
                continue
            # Found the start of a logger call. Walk forward counting
            # parens (from the open paren onward) until they balance.
            depth = 0
            j = i
            started = False
            while j < len(lines):
                segment = lines[j][m.start() if j == i else 0:]
                for ch in segment:
                    if ch == "(":
                        depth += 1
                        started = True
                    elif ch == ")":
                        depth -= 1
                if started and depth <= 0:
                    break
                j += 1
            # Keep any text on the start line before the logger call, drop
            # the rest of the call (including its continuation lines).
            prefix = lines[i][:m.start()]
            if prefix.strip():
                out.append(prefix)
            i = j + 1
        return "\n".join(out)

    def _strip_non_constructive_text(body):
        """Remove the function's own docstring (legitimately allowed to
        explain the internal concept being hidden from the user — see
        _diagnostic_answer's docstring, which says "never mention budget"
        while, unavoidably, mentioning it), internal tag comparisons like
        `reason_tag == "budget_exhausted"` (a control-flow check against an
        internal telemetry tag, never shown to the user), and internal
        logger.*() calls (application-log text, never part of a returned
        answer) — leaving only the string literals actually assembled into
        a returned answer."""
        # Drop the first triple-quoted docstring right after the def line
        # (async or not — _finalize_from_data became `async def` in the
        # 2026-09-11 round-3 fix).
        body = re.sub(r'^(    (?:async )?def \w+\([^)]*\)[^:]*:\s*\n)\s*""".*?"""',
                       r'\1', body, count=1, flags=re.DOTALL)
        body = _strip_logger_calls(body)
        # Drop lines that are tag comparisons/lookups, not text construction.
        body = "\n".join(
            line for line in body.splitlines()
            if "reason_tag ==" not in line and "reason_tag=" not in line
        )
        # Drop pure comment lines. They're never user-facing text, but a
        # contraction in one ("didn't", "isn't") reads to the naive
        # string-literal regex below as an opening single-quote — which
        # then greedily matches through to the next real apostrophe or
        # quote anywhere later in the function, sweeping in unrelated
        # real string literals (and any banned term they contain) as a
        # false positive. Full-line comments carry no risk of hiding a
        # real returned string, so dropping them outright is safe.
        body = "\n".join(
            line for line in body.splitlines()
            if not line.strip().startswith("#")
        )
        return body

    banned_terms = ["budget", "token", "processing limit"]
    for fn_name in ("_diagnostic_answer", "_finalize_from_data"):
        body = _strip_non_constructive_text(_function_body(fn_name))
        string_literals = re.findall(r'(?:f?"([^"\\]*(?:\\.[^"\\]*)*)"|'
                                      r"f?'([^'\\]*(?:\\.[^'\\]*)*)')", body)
        flat_strings = " ".join(s for pair in string_literals for s in pair if s)
        for term in banned_terms:
            assert term not in flat_strings.lower(), (
                f"{fn_name}() constructs a user-facing string containing "
                f"{term!r} — token/budget/processing-limit language must "
                f"never reach the user. Reframe in business terms (e.g. "
                f"'needs a narrower time range or fewer filters').\n"
                f"Matched context: {flat_strings[:2000]!r}"
            )
    print("✓ no user-facing string in _diagnostic_answer/_finalize_from_data "
          "mentions budget, tokens, or processing limits")


if __name__ == "__main__":
    test_ceiling_is_not_tuned_to_the_incident_that_exposed_it()
    test_known_question_shape_fits_with_large_margin()
    test_no_user_facing_message_names_budget_tokens_or_processing_limits()
    print("\n✅ All tests passed")
