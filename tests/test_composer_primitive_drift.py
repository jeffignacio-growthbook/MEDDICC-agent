"""
Tests for api/composer.py's "AVAILABLE PRIMITIVES" list — the fix for a
real production bug: "who's on track to hit quota?" got escalated out of
the correct governed handler (query_rep_attainment) into the composer's
plan-then-execute fallback, whose _DECOMPOSE_PROMPT hand-maintained a
primitive whitelist that had drifted from reality. It listed a primitive
that never existed, "query_rep_scorecard" (the closest real thing,
scripts/rep_scorecard.py::assess_rep_scorecard, is an internal helper of
query_quarter_health, never its own primitive), and omitted the real
handler, "query_rep_attainment". A plan naming the fake primitive sent
api/agent_loop.py::run_agent_loop's call_primitive() to a name
getattr(handlers, ...) can't find, so it fell back to a raw
fetch_data/filter_table sum over deals.deal_value — producing
$349,375/23% instead of the correct $520,060/33.6%.

Fix (api/composer.py): the prompt's primitive list is now generated from
the SAME source api/agent_loop.py::KNOWN_PRIMITIVES already derives from
(HANDLER_DESCRIPTIONS minus _NON_PRIMITIVE_INTENTS), via
_build_available_primitives_block(), instead of being hand-copied.

Invariants asserted here:
  1. Every primitive name in the built block — other than the two
     explicit sentinels "dynamic_query" and "_computed", which are not
     calculators and are documented as excluded from this check — resolves
     to a real, callable attribute on api.handlers (getattr(handlers, name,
     None) is not None and callable(...)).
  2. The set of non-sentinel primitive names in the block is EXACTLY
     api.agent_loop.KNOWN_PRIMITIVES (not just a subset) — the prompt
     offers every governed primitive the agent loop can actually call, and
     nothing it can't.
  3. "query_rep_scorecard" (the planted bug's fake primitive) is absent.
  4. "query_rep_attainment" (the real handler the production bug needed) is
     present.
  5. Planted-bug control: reintroducing a fake primitive into the block
     makes assertion 1 fail with a message naming it — proving the test
     actually catches this class of bug, not just confirming today's
     clean state. Reverted immediately after, then re-asserted green.
"""
import re
import sys
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in ("", "scripts", "scripts/analytics", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

# router/agent_loop import supabase at module load; stub it, matching the
# convention in tests/test_explain_prior_answer_routing.py.
if "supabase" not in sys.modules:
    _fake = types.ModuleType("supabase")
    _fake.create_client = lambda *a, **k: None
    _fake.Client = type("Client", (), {})
    sys.modules["supabase"] = _fake

import api.handlers as handlers  # noqa: E402
from api.agent_loop import KNOWN_PRIMITIVES  # noqa: E402
from api.composer import (  # noqa: E402
    _build_available_primitives_block,
    _PRIMITIVE_LIST_SENTINELS,
    _valid_plan,
)

# A line in the block looks like: "  query_foo                     - desc"
_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+-\s")


def _primitive_names_in_block(block: str) -> list[str]:
    names = []
    for line in block.splitlines():
        m = _LINE_RE.match(line)
        if m:
            names.append(m.group(1))
    return names


class TestComposerPrimitiveDrift(unittest.TestCase):

    def test_fake_primitive_is_gone(self):
        """The planted bug's fake primitive must never be offered again."""
        block = _build_available_primitives_block()
        self.assertNotIn(
            "query_rep_scorecard", block,
            "query_rep_scorecard is not a real handler (no "
            "async def query_rep_scorecard exists in api/handlers.py) — "
            "it must not appear in the composer's primitive list.",
        )

    def test_real_handler_is_present(self):
        """query_rep_attainment — the handler the production bug needed —
        must be offered."""
        block = _build_available_primitives_block()
        names = _primitive_names_in_block(block)
        self.assertIn("query_rep_attainment", names)

    def test_every_listed_primitive_is_callable_on_handlers(self):
        """Every non-sentinel name in the block resolves to a real,
        callable attribute on api.handlers — nothing in the prompt can
        resolve to a non-callable name."""
        block = _build_available_primitives_block()
        names = _primitive_names_in_block(block)
        self.assertTrue(names, "parsed no primitive names out of the block at all")

        checked = [n for n in names if n not in _PRIMITIVE_LIST_SENTINELS]
        self.assertTrue(checked, "every name was a sentinel — parsing is broken")

        not_callable = []
        for name in checked:
            fn = getattr(handlers, name, None)
            if fn is None or not callable(fn):
                not_callable.append(name)

        self.assertEqual(
            not_callable, [],
            f"primitive(s) in the composer's prompt do not resolve to a "
            f"real callable on api.handlers: {not_callable}",
        )

    def test_listed_primitive_set_matches_known_primitives_exactly(self):
        """The non-sentinel primitive names in the block are EXACTLY
        KNOWN_PRIMITIVES — a documented design choice (see composer.py's
        _build_available_primitives_block docstring), not merely a subset,
        so the composer never withholds a governed primitive run_agent_loop
        could actually call, and never offers one it can't."""
        block = _build_available_primitives_block()
        names = {n for n in _primitive_names_in_block(block)
                  if n not in _PRIMITIVE_LIST_SENTINELS}
        self.assertEqual(
            names, set(KNOWN_PRIMITIVES),
            "composer's primitive list has drifted from "
            "agent_loop.KNOWN_PRIMITIVES again — "
            f"missing: {set(KNOWN_PRIMITIVES) - names}, "
            f"extra: {names - set(KNOWN_PRIMITIVES)}",
        )

    def test_planted_bug_control_fake_primitive_caught(self):
        """Reintroduce a fake primitive into a block and confirm the
        callability check (the same logic as the real test above, applied
        to a deliberately-corrupted block) fails with a clear message
        naming it — proving this test suite actually catches the bug
        class, then confirm the real (uncorrupted) block is clean."""
        block = _build_available_primitives_block()
        corrupted = block + "\n  query_rep_scorecard            - FAKE planted primitive"

        names = _primitive_names_in_block(corrupted)
        checked = [n for n in names if n not in _PRIMITIVE_LIST_SENTINELS]
        not_callable = [n for n in checked
                        if getattr(handlers, n, None) is None
                        or not callable(getattr(handlers, n, None))]

        self.assertIn(
            "query_rep_scorecard", not_callable,
            "planted-bug control failed to reproduce: the test did not "
            "catch a reintroduced fake primitive",
        )

        # Revert — confirm the real block is green again.
        not_callable_clean = [n for n in _primitive_names_in_block(block)
                               if n not in _PRIMITIVE_LIST_SENTINELS
                               and (getattr(handlers, n, None) is None
                                    or not callable(getattr(handlers, n, None)))]
        self.assertEqual(not_callable_clean, [])

    def test_valid_plan_rejects_fake_primitive(self):
        """_valid_plan() itself (defense in depth, not just the prompt
        text) rejects a plan naming a primitive outside KNOWN_PRIMITIVES —
        so even an LLM that ignores the prompt and hallucinates
        query_rep_scorecard anyway can't get a plan through."""
        bad_plan = {
            "question": "who's on track to hit quota?",
            "sub_parts": [
                {"name": "attainment", "primitive": "query_rep_scorecard",
                 "rationale": "fake"},
            ],
        }
        self.assertFalse(_valid_plan(bad_plan))

    def test_valid_plan_accepts_real_primitive(self):
        good_plan = {
            "question": "who's on track to hit quota?",
            "sub_parts": [
                {"name": "attainment", "primitive": "query_rep_attainment",
                 "rationale": "real"},
            ],
        }
        self.assertTrue(_valid_plan(good_plan))


if __name__ == "__main__":
    unittest.main()
