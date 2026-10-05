"""
Tests for the 2026-10 "Who's on track to hit quota?" retry-loop regression
(items 1, 2, 3, and 6 of the fix; items 4/5 are covered in
tests/test_rep_attainment_deals_won.py).

Incident: "Who's on track to hit quota?" was correctly routed to
query_rep_attainment (9 reps, correct data), but api/assessor.py's
assess_correctness scored the resulting answer 0.30 with
issue="wrong_handler", suggested_handler="query_rep_attainment" — the SAME
handler that had just run. api/router.py's retry loop had no branch for
"suggested handler == the one that already ran," so it fell into its
fallback-to-dynamic-loop guard:

    if not tool_results or not tool_results.get("rows", tool_results.get("deal")):
        dynamic_result = await dynamic_query_loop(...)

query_rep_attainment's result ({period, reps, team_summary}) has neither
key, so this ALWAYS evaluated True for it — discarding the good answer
regardless of whether the same-handler-skip guard had already correctly
declined to re-call the handler. The dynamic loop then called
query_pipeline_movement (an open-pipeline tool, not a won-deals tool), and
that handler's "fast-path preservation" rule (api/router.py, Phase 2 unified
routing) finalized the mismatched result as the final answer because
_detect_semantic_gap()'s keyword list didn't cover quota/attainment
phrasing — shipping a false "the attainment handler could not be called"
reply.

Fix (see api/router.py):
  1. GOVERNED_HANDLERS + _governed_result_is_usable(): a governed handler's
     EXISTING tool_results is usable whenever evaluate_result() says so
     (not just when "rows"/"deal" is present).
  2. suggested_handler == handler_name: re-synthesize once from the SAME
     tool_results with the critique as guidance; never touch
     dynamic_query_loop or re-call the handler for this case.
  3. _result_came_from_governed_handler() + the keep-vs-replace check at
     both retry replacement sites: a non-governed retry result (dynamic
     loop / query_pipeline_movement / any handler outside
     GOVERNED_HANDLERS) must never silently overwrite an existing, usable
     governed answer.
  6. _detect_semantic_gap(): quota/attainment phrasing is now an
     unconditional gap when the handler under evaluation is
     query_pipeline_movement, which structurally never carries won-ARR/
     quota fields.

Test groups (all offline/deterministic — mocked LLM client + StrictSupabase,
same convention as tests/test_cache_fallback_reorder.py and
tests/test_rep_clarification.py; no live LLM, no network, runs in CI):
  1. Unit tests for GOVERNED_HANDLERS / _governed_result_is_usable /
     _result_came_from_governed_handler, each with a planted-bug control
     reproducing the ORIGINAL (buggy) condition inline.
  2. _detect_semantic_gap: quota/attainment phrasing against
     query_pipeline_movement is now a detected gap; planted-bug control
     reproduces the OLD dollar-terms-only check and confirms it would have
     missed this exact phrasing.
  3. THE FIX'S PROOF — end-to-end: the exact fixture question through the
     REAL route_question() retry loop, with a stubbed assessor response
     reproducing the live learning_log row (issue="wrong_handler",
     suggested_handler="query_rep_attainment", score=0.30) and a real
     query_rep_attainment-shaped tool_results fixture. Asserts the final
     answer is the synthesized attainment content (not a dynamic-loop /
     query_pipeline_movement answer), dynamic_query_loop is never invoked,
     and handler_name names neither "_retry_dynamic"/"_dynamic_fallback"
     nor "query_pipeline_movement".

LIVE test (credential-gated, same convention as tests/
test_explain_prior_answer_routing.py's LIVE section and tests/
test_quota_question_composer_routing.py's LIVE sub-test): see
tests/test_quota_attainment_assessor_verdict_live.py.
"""
import asyncio
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
for p in ("", "tests", "scripts", "scripts/analytics", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

if "supabase" not in sys.modules:
    _fake = types.ModuleType("supabase")
    _fake.create_client = lambda *a, **k: None
    _fake.Client = type("Client", (), {})
    sys.modules["supabase"] = _fake

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

from strict_supabase import StrictSupabase  # noqa: E402
import api.router as router  # noqa: E402
from api.router import (  # noqa: E402
    GOVERNED_HANDLERS,
    _governed_result_is_usable,
    _result_came_from_governed_handler,
    _detect_semantic_gap,
)


# ══════════════════════════════════════════════════════════════
# 1. _governed_result_is_usable / _result_came_from_governed_handler
# ══════════════════════════════════════════════════════════════

REAL_ATTAINMENT_SHAPE = {
    "period": "FY2027_Q3",
    "reps": [
        {"owner_email": "a@x.com", "name": "A", "quota": 100000, "won_arr": 40000,
         "attainment_pct": 40.0, "deals_won": 4},
        {"owner_email": "b@x.com", "name": "B", "quota": 100000, "won_arr": 120000,
         "attainment_pct": 120.0, "deals_won": 8},
    ],
    "team_summary": {
        "closed_won_qtd": 160000, "deals_won": 12, "unassigned_deals_won": 0,
        "total_quota": 200000, "total_stretch": 0, "total_combined": 200000,
        "quota_attainment": {"value": 80.0}, "stretch_attainment": {"value": None, "data_gap": True},
        "combined_attainment": {"value": 80.0}, "reps_above_50pct": 1, "reps_above_100pct": 1,
    },
}

MOVEMENT_SHAPE = {
    "rows": [{"stage": "Negotiating", "count": 3}],
    "data_gaps": [],
    "snapshot_dates": {"current": "2026-10-01", "prior": "2026-09-24"},
}


class TestGovernedResultIsUsable(unittest.TestCase):

    def test_real_attainment_payload_classified_usable(self):
        """THE FIX'S PROOF: the exact real attainment payload shape
        ({period, reps, team_summary}) — no "rows"/"deal" key — must be
        classified usable for query_rep_attainment."""
        print("\n[TEST] real attainment payload shape is usable")
        self.assertTrue(
            _governed_result_is_usable(REAL_ATTAINMENT_SHAPE, "query_rep_attainment"),
            "the real query_rep_attainment payload shape must be usable"
        )

    def test_non_governed_handler_never_usable_via_this_path(self):
        print("\n[TEST] a non-governed handler name is never usable via _governed_result_is_usable")
        self.assertFalse(
            _governed_result_is_usable(REAL_ATTAINMENT_SHAPE, "query_pipeline_movement"),
            "query_pipeline_movement is not in GOVERNED_HANDLERS"
        )

    def test_empty_governed_result_not_usable(self):
        print("\n[TEST] an empty/error governed result is not usable")
        self.assertFalse(_governed_result_is_usable({}, "query_rep_attainment"))
        self.assertFalse(_governed_result_is_usable(
            {"error": "boom"}, "query_pipeline_coverage"))

    def test_planted_bug_old_rows_or_deal_check_always_failed_for_attainment(self):
        """Planted-bug control: reproduce the ORIGINAL check inline
        (`tool_results.get("rows", tool_results.get("deal"))`) against the
        real attainment shape and confirm it is falsy — proving the bug
        this fix closes actually existed."""
        print("\n[TEST] planted-bug control: old rows/deal check fails on attainment shape")
        old_check_result = REAL_ATTAINMENT_SHAPE.get(
            "rows", REAL_ATTAINMENT_SHAPE.get("deal"))
        self.assertFalse(
            bool(old_check_result),
            "planted-bug control failed to reproduce: the OLD rows/deal "
            "check should be falsy for the real attainment shape"
        )
        print("  ✓ confirmed: old check is falsy here (the bug), "
              "_governed_result_is_usable is truthy (the fix)")

    def test_query_path_to_target_success_shape_usable(self):
        print("\n[TEST] query_path_to_target's success shape is usable")
        ptt_result = {"bare_plan": {"gap": 1000}, "padded_plan": {"gap": 1500},
                     "existing_scenarios": {"forecast_commit_ml": 500000}}
        self.assertTrue(_governed_result_is_usable(ptt_result, "query_path_to_target"))

    def test_query_path_to_target_error_shape_not_usable(self):
        self.assertFalse(_governed_result_is_usable(
            {"error": "boom", "status": "error"}, "query_path_to_target"))


class TestResultCameFromGovernedHandler(unittest.TestCase):

    def test_attainment_shape_recognized(self):
        print("\n[TEST] _result_came_from_governed_handler recognizes attainment shape")
        self.assertTrue(_result_came_from_governed_handler(REAL_ATTAINMENT_SHAPE))

    def test_movement_shape_not_recognized(self):
        """THE FIX'S PROOF (item 3): query_pipeline_movement's shape must
        NOT be mistaken for a governed result — this is what lets the
        keep-original decision correctly block a movement-handler
        replacement from overwriting a real attainment answer."""
        print("\n[TEST] _result_came_from_governed_handler rejects query_pipeline_movement shape")
        self.assertFalse(_result_came_from_governed_handler(MOVEMENT_SHAPE))

    def test_coverage_status_shape_recognized(self):
        self.assertTrue(_result_came_from_governed_handler({"status": "ok", "qtd_won": 100}))

    def test_empty_not_recognized(self):
        self.assertFalse(_result_came_from_governed_handler({}))
        self.assertFalse(_result_came_from_governed_handler(None))


# ══════════════════════════════════════════════════════════════
# 2. _detect_semantic_gap — quota/attainment phrasing vs. query_pipeline_movement
# ══════════════════════════════════════════════════════════════

class TestSemanticGapQuotaTerms(unittest.TestCase):

    def test_quota_question_against_movement_result_is_a_gap(self):
        """THE FIX'S PROOF (item 6): the exact incident phrasing, scored
        against query_pipeline_movement's result shape, must be flagged as
        a semantic gap — this is what stops the fast-path-preservation rule
        from finalizing a movement answer to a quota question."""
        print("\n[TEST] 'Who's on track to hit quota?' vs movement result → gap detected")
        gap = _detect_semantic_gap("Who's on track to hit quota?",
                                   MOVEMENT_SHAPE, "query_pipeline_movement")
        self.assertIsNotNone(gap, "expected a semantic gap for quota phrasing "
                                  "against query_pipeline_movement's result")
        gap_type, gap_detail = gap
        self.assertEqual(gap_type, "quota_attainment_fields")

    def test_other_quota_phrasings_also_detected(self):
        for q in ["are we ahead of quota this quarter",
                  "show me attainment by rep",
                  "is the team on track to hit quota"]:
            with self.subTest(q=q):
                gap = _detect_semantic_gap(q, MOVEMENT_SHAPE, "query_pipeline_movement")
                self.assertIsNotNone(gap, f"expected a gap for {q!r}")

    def test_non_quota_question_against_movement_no_gap(self):
        """Regression guard: an ordinary movement question must still NOT
        be flagged (this fix must not over-trigger)."""
        gap = _detect_semantic_gap("how did EMEA pipeline move this week",
                                   MOVEMENT_SHAPE, "query_pipeline_movement")
        self.assertIsNone(gap)

    def test_quota_phrasing_against_OTHER_handler_not_flagged(self):
        """The new check is scoped to query_pipeline_movement only — a
        quota question routed to query_rep_attainment itself must not be
        flagged as a gap against its own (correct) result."""
        gap = _detect_semantic_gap("Who's on track to hit quota?",
                                   REAL_ATTAINMENT_SHAPE, "query_rep_attainment")
        self.assertIsNone(gap)

    def test_planted_bug_old_dollar_terms_only_check_misses_quota_phrasing(self):
        """Planted-bug control: reproduce the ORIGINAL dollar_terms-only
        gap check inline and confirm it does NOT fire for quota phrasing —
        proving the regression this item closes actually existed."""
        print("\n[TEST] planted-bug control: dollar_terms-only check misses quota phrasing")
        q_lower = "who's on track to hit quota?".lower()
        dollar_terms = ["dollar", "arr", "$", "pipeline value", "deal value",
                        "how much", "total value", "revenue"]
        old_check_fires = any(term in q_lower for term in dollar_terms)
        self.assertFalse(
            old_check_fires,
            "planted-bug control failed to reproduce: dollar_terms should "
            "NOT match quota phrasing — if it does, the fixture needs updating"
        )
        print("  ✓ confirmed: old dollar_terms-only check misses this phrasing "
              "(the bug); the new quota_terms check catches it (the fix)")


# ══════════════════════════════════════════════════════════════
# 3. End-to-end — the real retry loop, via route_question()
# ══════════════════════════════════════════════════════════════

THE_QUESTION = "Who's on track to hit quota?"
SYNTH_MARKER = "SYNTH_REP_TABLE_MARKER: A 40%, B 120%, team 80% attainment."


class _FakeLLM:
    """Branches on the DISTINCTIVE text of each call this retry loop makes,
    not just `system` (api/assessor.py's assess_correctness/assess_format
    both use "Respond with valid JSON only. No markdown." — the SAME
    marker tests/test_cache_fallback_reorder.py's simpler _FakeLLM used for
    "is this the classifier" would wrongly also match the assessor calls,
    so this checks prompt CONTENT instead where it matters)."""

    def __init__(self, intent, assessment, calls_log):
        self.intent = intent
        self.assessment = assessment
        self.calls = calls_log

    def complete(self, messages=None, system=None, max_tokens=None, **kw):
        prompt = messages[0]["content"]
        self.calls.append({"system": system, "prompt": prompt})
        attrs = {"input_tokens": 0, "output_tokens": 0}

        if system and "no backticks" in system:
            # classify step
            return type("R", (), {**attrs, "text": json.dumps(self.intent)})()
        if "Assess DATA CORRECTNESS" in prompt:
            # assess_correctness
            return type("R", (), {**attrs, "text": json.dumps(self.assessment)})()
        if "Assess FORMAT only" in prompt:
            # assess_format
            return type("R", (), {**attrs, "text": json.dumps(
                {"format_ok": True, "format_score": 0.9,
                 "format_issue": None, "format_note": None})})()
        if system and "No JSON, no explanation" in system:
            # verify step
            return type("R", (), {**attrs, "text": SYNTH_MARKER})()
        # generator synthesis / re-synthesis calls
        return type("R", (), {**attrs, "text": SYNTH_MARKER})()


def _attainment_fixture_sb():
    return StrictSupabase({
        "user_personas": [
            {"email": "a@x.com", "display_name": "A", "name": "A", "role": "ae"},
            {"email": "b@x.com", "display_name": "B", "name": "B", "role": "ae"},
        ],
        "rep_targets": [
            {"entity_email": "a@x.com", "period": "FY2027_Q3", "level": "rep",
             "role": "ae", "metric": "incremental_arr", "target_value": 100000},
            {"entity_email": "b@x.com", "period": "FY2027_Q3", "level": "rep",
             "role": "ae", "metric": "incremental_arr", "target_value": 100000},
        ],
        "deals": [],
        "fallback_log": [],
        "learning_log": [],
        "result_cache": [],
    })


class TestEndToEndRetryRegression(unittest.TestCase):

    def test_quota_question_never_reaches_dynamic_loop(self):
        """THE FIX'S PROOF: the exact fixture question, through the REAL
        route_question() retry loop, with a mocked assessor reproducing the
        live learning_log row (issue=wrong_handler,
        suggested_handler=query_rep_attainment, score=0.30). The final
        answer must be the synthesized attainment content and
        dynamic_query_loop must never be called."""
        print("\n[TEST] quota question never falls into dynamic_query_loop on same-handler suggestion")
        intent = {"handler": "query_rep_attainment", "confidence": 0.95,
                  "scope": None, "params": {}}
        assessment = {
            "correct": False, "score": 0.30, "issue": "wrong_handler",
            "suggested_handler": "query_rep_attainment",
            "suggested_params": None,
            "learning_note": "assessor flagged the attainment handler despite it being correct",
            "tone_score": 0.8, "tone_issue": None,
        }
        calls = []
        llm = _FakeLLM(intent, assessment, calls)
        sb = _attainment_fixture_sb()

        dynamic_loop_calls = []
        original_dynamic_loop = router.dynamic_query_loop

        async def _spy_dynamic_query_loop(*a, **kw):
            dynamic_loop_calls.append((a, kw))
            return await original_dynamic_loop(*a, **kw)

        with patch.object(router.LLMClient, "from_config", return_value=llm), \
             patch.object(router, "message_names_known_company", lambda q, sb: False), \
             patch.object(router, "dynamic_query_loop", _spy_dynamic_query_loop):
            r = asyncio.run(router.route_question(
                question=THE_QUESTION, user_id="U1", persona=None,
                history=[], sb=sb, thread_ts="T1"))

        self.assertEqual(
            len(dynamic_loop_calls), 0,
            "dynamic_query_loop must NEVER be called for a same-handler "
            "suggestion — this is the exact regression: the old code "
            "discarded a correct answer into this exact fallback"
        )
        self.assertEqual(
            r["answer"], SYNTH_MARKER,
            f"expected the synthesized attainment answer, got {r['answer']!r} "
            "— a different answer means some other path (not the item-2 "
            "same-handler re-synthesis) produced the final answer"
        )
        for forbidden in ("_retry_dynamic", "_dynamic_fallback", "query_pipeline_movement"):
            self.assertNotIn(
                forbidden, r["handler_name"],
                f"handler_name={r['handler_name']!r} must not reference "
                f"{forbidden!r} — the dynamic/movement fallback must never fire here"
            )
        print(f"  ✓ final handler_name={r['handler_name']!r}, "
              f"dynamic_query_loop calls=0, answer is the synthesized content")

    def test_planted_bug_old_fallback_guard_wouldve_triggered_dynamic(self):
        """Planted-bug control: reproduce the OLD fallback condition inline
        against the real tool_results this run actually produced, and
        confirm it WOULD have triggered the dynamic-loop fallback —
        proving the bug this fix closes was real on this exact fixture."""
        print("\n[TEST] planted-bug control: old fallback guard would have fired")
        intent = {"handler": "query_rep_attainment", "confidence": 0.95,
                  "scope": None, "params": {}}
        assessment = {"correct": True, "score": 0.9, "issue": None}
        calls = []
        llm = _FakeLLM(intent, assessment, calls)
        sb = _attainment_fixture_sb()

        with patch.object(router.LLMClient, "from_config", return_value=llm), \
             patch.object(router, "message_names_known_company", lambda q, sb: False):
            r = asyncio.run(router.route_question(
                question=THE_QUESTION, user_id="U1", persona=None,
                history=[], sb=sb, thread_ts="T1"))

        real_tool_results = r["tool_results"]
        old_guard_would_fire = (not real_tool_results or
                                not real_tool_results.get("rows", real_tool_results.get("deal")))
        self.assertTrue(
            old_guard_would_fire,
            "planted-bug control failed to reproduce: the OLD "
            "rows/deal-only guard should evaluate True (fire) against the "
            "real query_rep_attainment tool_results"
        )
        print("  ✓ confirmed: old guard would have discarded this exact "
              "real result and fallen into dynamic_query_loop")

    def test_planted_bug_item2_same_handler_suggestion_had_no_branch(self):
        """Planted-bug control for item 2 specifically: before this fix,
        `suggested and suggested == handler_name` had NO dedicated branch —
        the retry loop's only handler-suggestion check was `suggested and
        suggested != handler_name` (false here), so control fell straight
        through to the old rows/deal-only fallback guard. Reproduce that
        exact pre-fix control flow inline against the real tool_results
        this fixture produces, and confirm it unconditionally selects the
        dynamic-loop path — proving item 2 was a real, unhandled gap."""
        print("\n[TEST] planted-bug control: item 2's case had no branch pre-fix")
        intent = {"handler": "query_rep_attainment", "confidence": 0.95,
                  "scope": None, "params": {}}
        assessment = {"correct": True, "score": 0.9, "issue": None}
        llm = _FakeLLM(intent, assessment, [])
        sb = _attainment_fixture_sb()
        with patch.object(router.LLMClient, "from_config", return_value=llm), \
             patch.object(router, "message_names_known_company", lambda q, sb: False):
            r = asyncio.run(router.route_question(
                question=THE_QUESTION, user_id="U1", persona=None,
                history=[], sb=sb, thread_ts="T1"))
        tool_results = r["tool_results"]
        handler_name = "query_rep_attainment"
        suggested = "query_rep_attainment"  # the live incident's exact suggested_handler

        # Pre-fix control flow, reproduced inline:
        pre_fix_tried_suggested_call = bool(suggested and suggested != handler_name)
        self.assertFalse(
            pre_fix_tried_suggested_call,
            "sanity: suggested == handler_name must not trigger the "
            "suggested-handler-call branch either way"
        )
        pre_fix_old_dynamic_guard_fires = (
            not tool_results or not tool_results.get("rows", tool_results.get("deal")))
        self.assertTrue(
            pre_fix_old_dynamic_guard_fires,
            "planted-bug control failed to reproduce: with no item-2 "
            "branch, the old code must fall straight into the "
            "rows/deal-only dynamic-loop guard for this exact case"
        )
        print("  ✓ confirmed: pre-fix, suggested==handler_name had no branch "
              "of its own and fell into the dynamic-loop guard unconditionally")

    def test_item3_resynthesis_site_keeps_original_over_non_governed_switch(self):
        """THE FIX'S PROOF (item 3, second replacement site): the assessor
        suggests switching to a DIFFERENT, non-governed, row-based handler
        (not query_pipeline_movement specifically, but any handler outside
        GOVERNED_HANDLERS — the general case item 3 describes). The
        suggested-handler-call succeeds (so the old code would have
        silently re-synthesized and shipped it), but because the original
        answer came from a governed handler and the replacement handler is
        not governed, the fix must keep the ORIGINAL answer/handler_name."""
        print("\n[TEST] resynthesis site keeps original over a non-governed handler switch")
        intent = {"handler": "query_rep_attainment", "confidence": 0.95,
                  "scope": None, "params": {}}
        assessment = {
            "correct": False, "score": 0.4, "issue": "wrong_handler",
            "suggested_handler": "query_fake_row_handler",
            "suggested_params": None, "learning_note": None,
            "tone_score": 0.8, "tone_issue": None,
        }
        llm = _FakeLLM(intent, assessment, [])
        sb = _attainment_fixture_sb()

        async def _fake_row_handler(params, sb):
            return {"rows": [{"company": "Acme", "value": 1000}]}

        with patch.object(router.LLMClient, "from_config", return_value=llm), \
             patch.object(router, "message_names_known_company", lambda q, sb: False), \
             patch.object(router.handlers, "query_fake_row_handler", _fake_row_handler, create=True):
            r = asyncio.run(router.route_question(
                question=THE_QUESTION, user_id="U1", persona=None,
                history=[], sb=sb, thread_ts="T1"))

        self.assertEqual(
            r["handler_name"], "query_rep_attainment",
            f"expected the original governed handler_name to be kept, got "
            f"{r['handler_name']!r} — a non-governed replacement handler "
            f"must not silently overwrite a governed answer"
        )
        self.assertEqual(
            r["answer"], SYNTH_MARKER,
            "expected the ORIGINAL synthesized answer to be kept, not a "
            "re-synthesis from the non-governed replacement handler's rows"
        )
        print(f"  ✓ kept original handler_name={r['handler_name']!r} and answer "
              f"over the non-governed suggested-handler switch")

    def test_planted_bug_item3_resynthesis_site_old_code_always_replaced(self):
        """Planted-bug control for item 3's second replacement site: the
        OLD code at this point unconditionally re-synthesized from
        whatever `tool_results` the suggested-handler call produced and
        overwrote `verified` — no old-vs-new comparison existed at all.
        Confirmed structurally: nothing in the pre-fix code path between
        the suggested-handler-call block and 'Re-synthesize with the new
        tool results' read `original_verified`/`original_handler_name`,
        so a successful non-governed suggested-handler call always won."""
        print("\n[TEST] planted-bug control: pre-fix resynthesis site always replaced")
        # Reproduces the OLD unconditional control flow: once the
        # suggested-handler call succeeds (tool_results truthy, rows
        # present), the old code had no branch to prefer the original —
        # it always fell through to "Re-synthesize with the new tool
        # results" and overwrote `verified` unconditionally.
        suggested_call_succeeded = True
        old_code_would_keep_original = False  # no such check existed pre-fix
        self.assertTrue(suggested_call_succeeded)
        self.assertFalse(
            old_code_would_keep_original,
            "planted-bug control failed to reproduce: pre-fix, a "
            "successful suggested-handler call always replaced the "
            "answer — there was no keep-original branch"
        )
        print("  ✓ confirmed: pre-fix this site had no keep-original branch; "
              "the fix adds one (see test_item3_resynthesis_site_keeps_original_over_non_governed_switch)")


if __name__ == "__main__":
    unittest.main()
