"""
Tests for Phase 2 of the explain_prior_answer fix: scoped tool_results
caching + citation-only consumption.

Phase 1 (PR #113) built explain_prior_answer grounded strictly in
prior_answer_context (the prior turn's RENDERED PROSE). Tonight's live
test of that fix hit a wall on "the exact per-stage multipliers aren't
printed above ... I'd need to re-run the query" — the data existed in
query_pipeline_coverage's tool_results when it ran, but was never
persisted anywhere, so explain_prior_answer had nothing to cite.

This phase adds: (1) query_pipeline_coverage and query_rep_attainment opt
into cache_payload (same pattern query_waterfall already used — see
MODEL_HIDDEN_KEYS), with their FULL result dict, no field exclusions,
since both are aggregate-only by construction (no per-deal row ever
appears in either output); (2) a citation-only read path — fetch the
cached structured fields, correlate them to the prior turn (not just
"most recent for this thread"), and splice them into the explanation
prompt as read-only material to quote, never recompute from; (3) an
explicit heuristic/real-target carry-forward instruction in the citation
prompt itself, not just implicit in the source data's own labeling.

Also fixes a gate in save_result_cache() that was silently dropping any
dict-shaped (no list-valued keys) payload — tuned for query_waterfall's
"deals": [...] shape, it incidentally defeated both new handlers' cache
writes before this fix (the write would have looked like it worked while
never persisting).

Test groups:
  OFFLINE (deterministic, no live LLM/Supabase — always runnable in CI):
    - Both handlers set cache_payload with the full result dict
    - save_result_cache no longer silently drops dict-only payloads
      (with a planted-bug control reproducing the old, broken gate)
    - load_result_cache_with_meta returns handler_name/question/payload
    - _cache_matches_prior_turn's correlation logic, including the
      500-char truncation edge case
    - build_explain_prior_answer_response splices cached fields as
      citation-only material, enforces "quote, never recompute", and
      enforces the heuristic carry-forward instruction
    - query_waterfall's existing load_result_cache/cached_result path is
      completely untouched

  LIVE (calls the real generator client — matches tests/
  test_explain_prior_answer_routing.py's existing convention for
  classifier-accuracy claims; requires ANTHROPIC_API_KEY/network and
  will fail in a credential-less sandbox, same as those 3 tests do
  today. Deliberately excluded from .github/workflows/gate-tests.yml's
  curated script list for the same reason those 3 are — validated by
  whatever runs with real credentials, not this offline suite or the
  merge gate):
    - the heuristic/real-target carry-forward instruction (test #6 of
      the Phase 2 plan) actually holds in a REAL model's OUTPUT, not
      just in the prompt sent to it. The offline test above
      (test_builder_enforces_heuristic_carry_forward_instruction) only
      confirms the instruction reaches the model via a mocked client —
      it cannot and does not confirm a real model complies. This is
      the 4th live-dependent test for this fix, alongside the original
      3 from PR #113's explain_prior_answer routing work — NOT folded
      into the offline/deterministic count above.

  NOT AUTOMATED HERE (task item 10): the full live re-ask — "how did you
  come up with the $795K / the per-stage multipliers" against a REAL
  prior Slack turn with a REAL result_cache row — needs an actual Slack
  conversation to populate the cache; there is no synthetic way to
  reproduce that from this sandbox. Run directly against the deployed app
  once Slack access is available.
"""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

REPO = Path(__file__).resolve().parents[1]
for p in ("", "scripts", "scripts/analytics", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

if "supabase" not in sys.modules:
    _fake = types.ModuleType("supabase")
    _fake.create_client = lambda *a, **k: None
    _fake.Client = type("Client", (), {})
    sys.modules["supabase"] = _fake

from api import router  # noqa: E402
from api.router import (  # noqa: E402
    build_explain_prior_answer_response,
    _cache_matches_prior_turn,
)
from api import db as apidb  # noqa: E402
from api import handlers  # noqa: E402


# ── Realistic fixture matching tonight's $795K / 0.75x scenario ────────
STAGE_WEIGHTING_FIXTURE = {
    "weighted_value": 795000.0,
    "weighted_deal_count": 18,
    "unweighted_value": 42000.0,
    "unweighted_deal_count": 2,
    "by_stage_order": {
        "1": {"n_observed": 40, "classified": 35, "unclassified": 5,
              "won": 14, "lost": 15, "slipped": 6, "win_rate": 0.4,
              "reason": None},
        "2": {"n_observed": 32, "classified": 30, "unclassified": 2,
              "won": 18, "lost": 10, "slipped": 2, "win_rate": 0.6,
              "reason": None},
    },
    "min_evidence_count": 30,
    "note": "Deals at a stage whose historical close-rate cohort is below "
            "min_evidence_count are excluded from the weighted total.",
}
REAL_TARGET_FIXTURE = {
    "quota": 1550000.0, "stretch": 2100000.0, "goal": 1550000.0,
    "stretch_note": "Ryan's personal aspiration — NOT additive on top of quota.",
    "note": "Stated target for FY2027 Q3 — team quota from rep_targets. "
            "This is the REAL stated target, NEVER a heuristic.",
}
HISTORICAL_HEURISTIC_CURVE_FIXTURE = {
    "by_week": {"7": {"mean_ratio": 2.0, "median_ratio": 2.0, "n_quarters": 4}},
    "proxy_targets": {"FY2027 Q2": {"value": 1000000, "prior_year_label": "FY2026 Q2",
                                    "prior_year_actual": 500000,
                                    "prior_year_deal_count": 17,
                                    "evidence_gated": True}},
    "heuristic": True,
    "label": "HEURISTIC",
    "note": "HEURISTIC: calibrated against a 2x-prior-year-actual PROXY target, "
            "not a real historical quota.",
    "current_week_ratio": {"mean_ratio": 2.0, "median_ratio": 2.0, "n_quarters": 4},
}
PIPELINE_COVERAGE_FIXTURE = {
    "status": "ok",
    "fiscal_quarter": "FY2027 Q3",
    "current_week": 7,
    "is_historical": False,
    "scope": "New+Expansion ARR only; qualified pipeline only",
    "qualified_pipeline": {"raw_value": 1060000.0, "deal_count": 20},
    "renewal_not_weighted": {"deal_count": 3, "value": 90000.0, "note": "..."},
    "stage_weighting": STAGE_WEIGHTING_FIXTURE,
    "real_target": REAL_TARGET_FIXTURE,
    "gap_to_goal": {
        "raw_pipeline_vs_goal": {"status": "short", "amount": 490000.0,
                                  "text": "$490,000 short of target"},
        "weighted_pipeline_vs_goal": {"status": "short", "amount": 755000.0,
                                      "text": "$755,000 short of target"},
    },
    "historical_heuristic_curve": HISTORICAL_HEURISTIC_CURVE_FIXTURE,
    "note": "HEURISTIC: the historical_heuristic_curve above is calibrated "
            "against a PROXY target, never a real historical quota.",
}

PRIOR_ANSWER_FIXTURE = (
    "Pipeline coverage for FY2027 Q3 is $795,000 weighted against a "
    "$1,550,000 quota, a 0.75x coverage ratio."
)
FOLLOWUP_QUESTION = "how did you come up with the $795K / the per-stage multipliers?"


# ══════════════════════════════════════════════════════════════
# Handlers set cache_payload with the full result, no exclusions
# ══════════════════════════════════════════════════════════════

async def _run_query_pipeline_coverage(fixture):
    with patch("pipeline_coverage.assess_pipeline_coverage", return_value=dict(fixture)):
        return await handlers.query_pipeline_coverage({}, MagicMock())


def test_pipeline_coverage_handler_sets_full_cache_payload():
    """cache_payload must equal every other top-level field — no exclusions,
    per the pinned field list (nothing in this primitive is per-deal data)."""
    print("\n[TEST] query_pipeline_coverage sets cache_payload = full result")
    import asyncio
    result = asyncio.run(_run_query_pipeline_coverage(PIPELINE_COVERAGE_FIXTURE))

    assert "cache_payload" in result, "cache_payload key missing from result"
    cached = result["cache_payload"]
    for key in PIPELINE_COVERAGE_FIXTURE:
        assert key in cached, f"pinned field {key!r} missing from cache_payload"
        assert cached[key] == PIPELINE_COVERAGE_FIXTURE[key], \
            f"cache_payload[{key!r}] does not match the real result"
    # by_stage_order specifically — this is the exact field tonight's
    # live test needed and didn't have.
    assert cached["stage_weighting"]["by_stage_order"]["1"]["win_rate"] == 0.4
    print("  ✓ cache_payload carries every pinned field verbatim, including by_stage_order")


def test_pipeline_coverage_handler_no_cache_payload_on_error():
    """An error result (status != 'ok') must not get cache_payload — there's
    nothing trustworthy to cite."""
    print("\n[TEST] query_pipeline_coverage: no cache_payload on error")
    import asyncio
    with patch("pipeline_coverage.assess_pipeline_coverage",
               side_effect=RuntimeError("boom")):
        result = asyncio.run(handlers.query_pipeline_coverage({}, MagicMock()))
    assert result.get("status") == "error"
    assert "cache_payload" not in result
    print("  ✓ error path carries no cache_payload")


def _mock_rep_attainment_sb(targets_data, deals_data, personas_data):
    """A Supabase mock whose .table(name).select(...).eq(...)... chain
    returns canned data per table name."""
    def _table(name):
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.gte.return_value = chain
        chain.lte.return_value = chain
        chain.in_.return_value = chain  # select_all() uses .in_() for an "in" filter
        chain.range.return_value = chain  # select_all() pages via .range()
        if name == "rep_targets":
            chain.execute.return_value = MagicMock(data=targets_data)
        elif name == "deals":
            chain.execute.return_value = MagicMock(data=deals_data)
        elif name == "user_personas":
            chain.execute.return_value = MagicMock(data=personas_data)
        else:
            chain.execute.return_value = MagicMock(data=[])
        return chain
    sb = MagicMock()
    sb.table = MagicMock(side_effect=_table)
    return sb


def test_rep_attainment_handler_sets_full_cache_payload_normal_path():
    """Normal path (quotas exist): cache_payload must equal the full
    result (period, reps[], team_summary), no exclusions — bounded by
    team size, never per-deal rows."""
    print("\n[TEST] query_rep_attainment sets cache_payload = full result (normal path)")
    import asyncio

    targets = [{"entity_email": "jake@growthbook.io", "metric": "quota", "target_value": 300000},
               {"entity_email": "jake@growthbook.io", "metric": "stretch", "target_value": 400000}]
    deals = [{"owner_email": "jake@growthbook.io", "new_arr": 100000, "expansion_arr": 0,
             "pipeline_id": "default"}]
    personas = [{"email": "jake@growthbook.io", "display_name": "Jake", "name": "Jake"}]

    sb = _mock_rep_attainment_sb(targets, deals, personas)

    with patch("utils.get_fiscal_quarter", return_value=(__import__("datetime").date(2026, 8, 1),
                                                         __import__("datetime").date(2026, 10, 31),
                                                         "FY2027 Q3")), \
         patch("api.handlers._resolve_owner_email", return_value=(None, None)), \
         patch("api.handlers._resolve_tw", return_value={"start": "2026-08-01",
                                                          "end": "2026-10-31",
                                                          "label": "FY2027 Q3"}):
        result = asyncio.run(handlers.query_rep_attainment({}, sb))

    assert "cache_payload" in result, "cache_payload key missing"
    cached = result["cache_payload"]
    assert cached["period"] == result["period"]
    assert cached["reps"] == result["reps"]
    assert cached["team_summary"] == result["team_summary"]
    assert len(cached["reps"]) == 1
    assert cached["reps"][0]["owner_email"] == "jake@growthbook.io"
    print("  ✓ cache_payload carries period/reps/team_summary verbatim")


def test_rep_attainment_handler_sets_cache_payload_data_gap_path():
    """Data-gap path (no quotas set): still cache_payload — the 'why does
    it say 0 attainment' follow-up needs the note field too."""
    print("\n[TEST] query_rep_attainment sets cache_payload = full result (data-gap path)")
    import asyncio

    sb = _mock_rep_attainment_sb([], [], [])

    with patch("utils.get_fiscal_quarter", return_value=(__import__("datetime").date(2026, 8, 1),
                                                         __import__("datetime").date(2026, 10, 31),
                                                         "FY2027 Q3")), \
         patch("api.handlers._resolve_owner_email", return_value=(None, None)), \
         patch("api.handlers._resolve_tw", return_value={"start": "2026-08-01",
                                                          "end": "2026-10-31",
                                                          "label": "FY2027 Q3"}):
        result = asyncio.run(handlers.query_rep_attainment({}, sb))

    assert "cache_payload" in result
    assert "note" in result["cache_payload"]
    assert "quotas not set" in result["cache_payload"]["note"]
    print("  ✓ data-gap path still caches, including the explanatory note")


# ══════════════════════════════════════════════════════════════
# save_result_cache no longer silently drops dict-only payloads
# ══════════════════════════════════════════════════════════════

def _mock_result_cache_sb():
    chain = MagicMock()
    chain.upsert.return_value = chain
    chain.execute.return_value = MagicMock(data=[{"result_key": "rc_test"}])
    sb = MagicMock()
    sb.table = MagicMock(return_value=chain)
    return sb, chain


def test_save_result_cache_persists_dict_only_payload():
    """A dict-shaped payload with no list-valued keys (query_pipeline_
    coverage's/query_rep_attainment's shape) must still get written —
    the old row_count>0-via-list gate would have silently dropped it."""
    print("\n[TEST] save_result_cache persists dict-only (no-list) payloads")
    sb, chain = _mock_result_cache_sb()

    key = apidb.save_result_cache(sb, "T123", "query_pipeline_coverage",
                                  "how's coverage?", dict(PIPELINE_COVERAGE_FIXTURE))

    assert key is not None, "dict-only payload was dropped (row_count gate regression)"
    chain.upsert.assert_called_once()
    print("  ✓ dict-only payload is written, not silently dropped")


def test_planted_bug_old_gate_would_have_dropped_dict_only_payload():
    """PLANTED-DISCREPANCY PROOF: reproduce the OLD gate logic (row_count
    over list-valued keys only) against the same dict-only payload and
    confirm it WOULD have returned 'drop it' — proving the fix above is
    actually load-bearing, not a no-op."""
    print("\n[TEST] planted bug: old list-only gate would have dropped this payload")
    payload = dict(PIPELINE_COVERAGE_FIXTURE)

    old_row_count = 0
    for v in payload.values():
        if isinstance(v, list):
            old_row_count += len(v)

    if old_row_count != 0:
        raise AssertionError(
            "Test setup error: the fixture unexpectedly contains a "
            "top-level list — this control no longer demonstrates the bug")
    print("  ✓ old gate (row_count over list-valued keys) computes 0 for this "
          "payload and would have returned None — confirms the fix is load-bearing")


# ══════════════════════════════════════════════════════════════
# load_result_cache_with_meta
# ══════════════════════════════════════════════════════════════

def _mock_load_cache_sb(rows):
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.gt.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = MagicMock(data=rows)
    sb = MagicMock()
    sb.table = MagicMock(return_value=chain)
    return sb


def test_load_result_cache_with_meta_returns_handler_and_question():
    print("\n[TEST] load_result_cache_with_meta returns handler_name/question/payload")
    sb = _mock_load_cache_sb([{
        "result_key": "rc_1", "handler_name": "query_pipeline_coverage",
        "question": "how's coverage?", "payload": dict(PIPELINE_COVERAGE_FIXTURE),
        "row_count": 0, "created_at": "2026-10-02T00:00:00Z",
        "expires_at": "2026-10-02T00:30:00Z",
    }])
    hit = apidb.load_result_cache_with_meta(sb, "T123")
    assert hit is not None
    assert hit["handler_name"] == "query_pipeline_coverage"
    assert hit["question"] == "how's coverage?"
    assert hit["payload"]["stage_weighting"]["by_stage_order"]["1"]["win_rate"] == 0.4
    print("  ✓ returns handler_name, question, and the unpacked payload")


def test_load_result_cache_with_meta_returns_none_when_no_live_cache():
    print("\n[TEST] load_result_cache_with_meta returns None for an empty thread")
    sb = _mock_load_cache_sb([])
    assert apidb.load_result_cache_with_meta(sb, "T_empty") is None
    print("  ✓ no live cache -> None")


# ══════════════════════════════════════════════════════════════
# _cache_matches_prior_turn correlation logic
# ══════════════════════════════════════════════════════════════

def test_cache_matches_prior_turn_exact_match():
    print("\n[TEST] _cache_matches_prior_turn: exact match -> True")
    cache_hit = {"question": "how's coverage?"}
    assert _cache_matches_prior_turn(cache_hit, "how's coverage?") is True
    print("  ✓ exact question match correlates")


def test_cache_matches_prior_turn_mismatch():
    print("\n[TEST] _cache_matches_prior_turn: different question -> False")
    cache_hit = {"question": "how's coverage?"}
    assert _cache_matches_prior_turn(cache_hit, "what's our win rate?") is False
    print("  ✓ different question does not correlate (stale/unrelated cache rejected)")


def test_cache_matches_prior_turn_no_cache_hit():
    print("\n[TEST] _cache_matches_prior_turn: no cache_hit -> False")
    assert _cache_matches_prior_turn(None, "how's coverage?") is False
    print("  ✓ no cache -> False")


def test_cache_matches_prior_turn_no_prior_question():
    print("\n[TEST] _cache_matches_prior_turn: prior_question=None -> False")
    cache_hit = {"question": "how's coverage?"}
    assert _cache_matches_prior_turn(cache_hit, None) is False
    print("  ✓ unknown prior question -> False (never guess a correlation)")


def test_cache_matches_prior_turn_truncation_matches():
    """question is stored truncated to 500 chars by save_result_cache().
    A long prior_question must still correlate against its own truncated
    stored form, or long questions would never match their own cache."""
    print("\n[TEST] _cache_matches_prior_turn: 500-char truncation handled correctly")
    long_question = "how's coverage? " + ("x" * 600)
    cache_hit = {"question": long_question[:500]}
    assert _cache_matches_prior_turn(cache_hit, long_question) is True
    print("  ✓ long question still correlates against its truncated stored form")


# ══════════════════════════════════════════════════════════════
# build_explain_prior_answer_response — citation-only splicing
# ══════════════════════════════════════════════════════════════

def _mock_generator(response_text="placeholder"):
    client = MagicMock()
    resp = MagicMock()
    resp.text = response_text
    client.complete.return_value = resp
    return client


def test_builder_splices_cached_fields_as_citation_only():
    """The exact by_stage_order figures must reach the prompt — this is
    the concrete fix for tonight's 'wasn't printed above' gap."""
    print("\n[TEST] builder splices cached by_stage_order figures into the prompt")
    client = _mock_generator("The $795K comes from stage 1 deals weighted at "
                             "a 0.4 win rate and stage 2 at 0.6.")
    result = build_explain_prior_answer_response(
        FOLLOWUP_QUESTION, PRIOR_ANSWER_FIXTURE, client,
        cached_fields=dict(PIPELINE_COVERAGE_FIXTURE))

    sent_prompt = client.complete.call_args.kwargs["messages"][0]["content"]
    assert "Cached computation details" in sent_prompt
    assert '"win_rate": 0.4' in sent_prompt
    assert '"win_rate": 0.6' in sent_prompt
    assert '"n_observed": 40' in sent_prompt
    assert "never recompute from them" in sent_prompt
    assert "Do NOT recompute, re-derive, or adjust" in sent_prompt
    assert result == "The $795K comes from stage 1 deals weighted at a 0.4 win rate and stage 2 at 0.6."
    print("  ✓ exact cached figures (0.4, 0.6, n_observed=40) reach the prompt, "
          "with an explicit never-recompute instruction")


def test_builder_enforces_heuristic_carry_forward_instruction():
    """The heuristic/real-target carry-forward rule must be an EXPLICIT
    instruction in the prompt, not just implicit in the source JSON's own
    'heuristic'/'label' fields."""
    print("\n[TEST] builder enforces heuristic carry-forward instruction explicitly")
    client = _mock_generator()
    build_explain_prior_answer_response(
        FOLLOWUP_QUESTION, PRIOR_ANSWER_FIXTURE, client,
        cached_fields=dict(PIPELINE_COVERAGE_FIXTURE))

    sent_prompt = client.complete.call_args.kwargs["messages"][0]["content"]
    sent_system = client.complete.call_args.kwargs["system"]
    assert "HEURISTIC" in sent_prompt
    assert "describe it as a heuristic / proxy projection in your explanation" in sent_prompt
    assert "heuristic" in sent_system.lower()
    assert "never as a real target" in sent_system.lower()
    print("  ✓ heuristic carry-forward rule is an explicit instruction in both "
          "the user prompt and the system prompt")


def test_builder_backward_compatible_no_cached_fields():
    """cached_fields=None (the PR #113 default) must produce no 'Cached
    computation details' section at all — pure prose-only behavior,
    unchanged from before this phase."""
    print("\n[TEST] builder is backward compatible when no cache is available")
    client = _mock_generator()
    build_explain_prior_answer_response(
        FOLLOWUP_QUESTION, PRIOR_ANSWER_FIXTURE, client)

    sent_prompt = client.complete.call_args.kwargs["messages"][0]["content"]
    # The static instructions reference "a 'Cached computation details'
    # section" conditionally ("if ... appears above") regardless of
    # whether one exists this turn — that's fine, it's an IF-present
    # instruction. What must be absent is the actual POPULATED section
    # _format_cached_fields_section() emits, which has this unique opening:
    assert "never recompute from them):" not in sent_prompt, \
        "a populated cached-fields section leaked in despite cached_fields=None"
    assert PRIOR_ANSWER_FIXTURE in sent_prompt
    assert FOLLOWUP_QUESTION in sent_prompt
    print("  ✓ no cache -> no populated cached-fields section; prose-only prompt unchanged")


# ══════════════════════════════════════════════════════════════
# query_waterfall's existing cached_result consumption — untouched
# ══════════════════════════════════════════════════════════════

def test_load_result_cache_contract_unchanged():
    """load_result_cache() (the function query_waterfall's existing
    'cached_result' follow-up path depends on) must still return the RAW
    payload directly — not wrapped in a handler_name/question dict like
    load_result_cache_with_meta. The router's existing consumer does
    `tool_results = cached` directly; wrapping it would silently break
    that path."""
    print("\n[TEST] load_result_cache's contract (raw payload, not wrapped) is unchanged")
    waterfall_payload = {"deals": [{"deal_id": "1", "company_name": "Acme",
                                   "deal_value": 100000, "arr_usd": 100000,
                                   "stage": "closedwon", "deal_status": "won"}]}
    sb = _mock_load_cache_sb([{
        "result_key": "rc_2", "handler_name": "query_waterfall",
        "question": "show me pipeline", "payload": waterfall_payload,
        "row_count": 1, "created_at": "2026-10-02T00:00:00Z",
        "expires_at": "2026-10-02T00:30:00Z",
    }])
    cached = apidb.load_result_cache(sb, "T123")
    assert cached == waterfall_payload, \
        "load_result_cache must return the raw payload directly, unwrapped"
    assert "handler_name" not in cached, \
        "load_result_cache must NOT start wrapping its return in metadata"
    print("  ✓ load_result_cache still returns the raw payload directly — "
          "query_waterfall's cached_result consumer is untouched")


def test_waterfall_cache_payload_still_gated_by_row_count_or_dict_logic():
    """query_waterfall's own cache_payload (a 'deals': [...] list) must
    still persist correctly after the save_result_cache gate change —
    confirms the fix didn't just ADD dict support, it preserved the
    original list-shaped path too."""
    print("\n[TEST] query_waterfall's list-shaped cache_payload still persists")
    sb, chain = _mock_result_cache_sb()
    payload = {"deals": [{"deal_id": "1", "company_name": "Acme"}]}
    key = apidb.save_result_cache(sb, "T123", "query_waterfall",
                                  "show me pipeline", payload)
    assert key is not None
    chain.upsert.assert_called_once()
    print("  ✓ list-shaped payloads (query_waterfall's existing shape) still persist")


# ══════════════════════════════════════════════════════════════
# LIVE — real generator call. See module docstring: the offline test
# above (test_builder_enforces_heuristic_carry_forward_instruction) only
# confirms the instruction reaches the model via a mock; it cannot
# confirm a real model complies. This is the 4th live-dependent test for
# this fix (alongside the 3 in test_explain_prior_answer_routing.py),
# excluded from gate-tests.yml's curated list for the same reason those
# are, and expected to fail here (no ANTHROPIC_API_KEY in this sandbox).
# ══════════════════════════════════════════════════════════════

HEURISTIC_FOLLOWUP_QUESTION = (
    "what's that historical curve you compare against, and is the "
    "$1,000,000 figure for FY2026 Q2 a real quota?"
)


def test_live_heuristic_carry_forward_holds_in_real_model_output():
    """
    Phase 2 plan item #6. PRIOR_ANSWER_FIXTURE's prose never mentions the
    historical curve at all — the only way the model can answer this
    follow-up is by citing historical_heuristic_curve from cached_fields.
    The real output must then still call it a heuristic/proxy, not
    present prior_year_actual/proxy_targets as if they were a real quota.
    """
    print("\n[TEST] LIVE: heuristic carry-forward holds in a real model's output")
    from llm_client import LLMClient

    client = LLMClient.from_config(role="generator")
    result = build_explain_prior_answer_response(
        HEURISTIC_FOLLOWUP_QUESTION, PRIOR_ANSWER_FIXTURE, client,
        cached_fields=dict(PIPELINE_COVERAGE_FIXTURE))

    print(f"  model output: {result[:300]}")
    lowered = result.lower()
    assert "heuristic" in lowered or "proxy" in lowered, (
        f"REGRESSION: real model output cited historical_heuristic_curve "
        f"without calling it a heuristic/proxy — got: {result!r}")
    assert "real quota" not in lowered and "actual quota" not in lowered, (
        f"REGRESSION: real model output presented the heuristic curve's "
        f"figure as if it were a real/actual quota — got: {result!r}")
    print("  ✓ real model output labels the cited curve a heuristic/proxy, "
          "never presents it as a real quota")


def main():
    offline_tests = [
        test_pipeline_coverage_handler_sets_full_cache_payload,
        test_pipeline_coverage_handler_no_cache_payload_on_error,
        test_rep_attainment_handler_sets_full_cache_payload_normal_path,
        test_rep_attainment_handler_sets_cache_payload_data_gap_path,
        test_save_result_cache_persists_dict_only_payload,
        test_planted_bug_old_gate_would_have_dropped_dict_only_payload,
        test_load_result_cache_with_meta_returns_handler_and_question,
        test_load_result_cache_with_meta_returns_none_when_no_live_cache,
        test_cache_matches_prior_turn_exact_match,
        test_cache_matches_prior_turn_mismatch,
        test_cache_matches_prior_turn_no_cache_hit,
        test_cache_matches_prior_turn_no_prior_question,
        test_cache_matches_prior_turn_truncation_matches,
        test_builder_splices_cached_fields_as_citation_only,
        test_builder_enforces_heuristic_carry_forward_instruction,
        test_builder_backward_compatible_no_cached_fields,
        test_load_result_cache_contract_unchanged,
        test_waterfall_cache_payload_still_gated_by_row_count_or_dict_logic,
    ]
    live_tests = [
        test_live_heuristic_carry_forward_holds_in_real_model_output,
    ]
    tests = offline_tests + live_tests
    failed = []
    for t in tests:
        try:
            t()
        except Exception as e:
            failed.append((t.__name__, str(e)))
            print(f"\n  ❌ FAILED: {e}")

    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    passed = len(tests) - len(failed)
    print(f"\nTotal tests: {len(tests)} ({len(offline_tests)} offline, "
          f"{len(live_tests)} live)")
    print(f"  ✓ Passed: {passed}")
    if failed:
        print(f"  ✗ Failed: {len(failed)}")
        for name, error in failed:
            print(f"  - {name}")
            print(f"    {error[:200]}")
        return 1
    print("\n✅ All explain_prior_answer citation tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
