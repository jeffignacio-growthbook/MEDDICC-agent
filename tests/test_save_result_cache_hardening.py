"""
Tests for hardening save_result_cache() against a serialization failure
in any one handler's cache_payload.

Confirmed during PR #114's scoping: save_result_cache()'s json.dumps()
call had no try/except, and neither did its caller save_thread(). Both
handlers currently in the cache_payload opt-in list (query_pipeline_
coverage, query_rep_attainment) are serialization-safe today — this was
never an active bug — but it was a landmine for the next handler added
to that list without the same check.

Diagnosis (this session) overturned the original framing: the cache
write happens BEFORE save_thread()'s own conversation_threads commit,
not after — that commit is the function's LAST statement. So an
uncaught exception in the cache write didn't just skip the cache, it
aborted save_thread() before history/entity context were ever
persisted, with the user already having received their Slack reply
(save_thread() runs as a FastAPI background task, after send_to_zap()).
The failure was entirely silent in the moment and would only surface as
a mysteriously broken follow-up turn.

Fix: wrap save_result_cache()'s write (make_result_key through
.upsert().execute(), not just json.dumps() — a transient DB error is
just as capable of raising as a bad payload) in a try/except. On
failure: log [CACHE] (matching load_result_cache/load_result_cache_
with_meta's existing tag), name the handler and the error, return None
— reusing the function's EXISTING "nothing worth caching" contract, so
save_thread()'s `if result_key:` check already does the right thing
with zero changes to save_thread() itself.

Test groups (all offline/deterministic, no live LLM/Supabase):
  - planted-bug proof: the OLD unwrapped write logic really does raise
    on a realistic bad payload (a raw datetime, the realistic failure
    case — a handler that forgot .isoformat())
  - the FIXED save_result_cache() returns None gracefully instead,
    logging [CACHE] with the handler name and the error, never reaching
    .upsert() at all (json.dumps fails before the call)
  - the full save_thread() integration: a poisoned cache_payload no
    longer aborts the function — the conversation_threads commit still
    happens (history persisted), just without a cache reference
  - regression: real query_pipeline_coverage (including PR #115's
    stage_name field), query_rep_attainment, and query_waterfall
    payload shapes all still cache successfully post-fix
"""
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[1]
for p in ("", "scripts", "scripts/analytics", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

if "supabase" not in sys.modules:
    _fake = types.ModuleType("supabase")
    _fake.create_client = lambda *a, **k: None
    _fake.Client = type("Client", (), {})
    sys.modules["supabase"] = _fake

from api import db as apidb  # noqa: E402


# A realistic bad payload — a handler that forgot to call .isoformat()
# on a datetime before putting it in cache_payload. Everything else is
# ordinary JSON-safe data, matching a real aggregate-handler shape.
POISONED_PAYLOAD = {
    "status": "ok",
    "fiscal_quarter": "FY2027 Q3",
    "fetched_at": datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc),  # NOT serializable
    "stage_weighting": {"by_stage_order": {"1": {"win_rate": 0.4}}},
}

PIPELINE_COVERAGE_PAYLOAD = {
    "status": "ok",
    "fiscal_quarter": "FY2027 Q3",
    "qualified_pipeline": {"raw_value": 1060000.0, "deal_count": 20},
    "stage_weighting": {
        "weighted_value": 795000.0,
        "by_stage_order": {
            "1": {"n_observed": 40, "win_rate": 0.4, "stage_name": "Discovery"},
            "2": {"n_observed": 32, "win_rate": 0.6, "stage_name": "Scoping"},
        },
    },
    "real_target": {"quota": 1550000.0, "stretch": 2100000.0, "goal": 1550000.0},
}

REP_ATTAINMENT_PAYLOAD = {
    "period": "FY2027_Q3",
    "reps": [{"owner_email": "jake@growthbook.io", "quota": 300000.0,
             "won_arr": 100000.0, "attainment_pct": 33.3}],
    "team_summary": {"closed_won_qtd": 100000.0, "total_quota": 300000.0},
}

WATERFALL_PAYLOAD = {
    "deals": [{"deal_id": "1", "company_name": "Acme", "deal_value": 100000,
              "stage": "closedwon", "deal_status": "won"}],
}


def _mock_result_cache_sb():
    chain = MagicMock()
    chain.upsert.return_value = chain
    chain.execute.return_value = MagicMock(data=[{"result_key": "rc_test"}])
    sb = MagicMock()
    sb.table = MagicMock(return_value=chain)
    return sb, chain


# ══════════════════════════════════════════════════════════════
# Planted-bug proof: the OLD unwrapped write really does raise
# ══════════════════════════════════════════════════════════════

def test_planted_bug_old_unwrapped_write_raises_on_datetime_payload():
    """Reproduces the pre-fix save_result_cache() body (no try/except)
    inline against POISONED_PAYLOAD. Must raise — proves the
    vulnerability this fix closes was real, not hypothetical."""
    print("\n[TEST] planted bug: old unwrapped write raises on a raw datetime")
    import json as _json

    def _old_unwrapped_write(payload):
        # Verbatim shape of the pre-2026-10-03 body: json.dumps inline,
        # no try/except anywhere in the function.
        return _json.dumps({
            "result_key": "rc_x",
            "payload": _json.dumps(payload),
        })

    raised = False
    try:
        _old_unwrapped_write(POISONED_PAYLOAD)
    except TypeError:
        raised = True

    assert raised, (
        "Test setup error: the planted bad payload didn't actually "
        "reproduce a serialization failure — this control doesn't "
        "demonstrate anything")
    print("  ✓ old unwrapped write raises TypeError on a raw datetime, as expected")


# ══════════════════════════════════════════════════════════════
# Fixed save_result_cache(): graceful None, never reaches .upsert()
# ══════════════════════════════════════════════════════════════

def test_save_result_cache_returns_none_on_serialization_failure():
    print("\n[TEST] save_result_cache returns None on a poisoned payload, doesn't raise")
    sb, chain = _mock_result_cache_sb()

    key = apidb.save_result_cache(sb, "T123", "some_future_handler",
                                  "a question", POISONED_PAYLOAD)

    assert key is None, f"expected None on serialization failure, got {key!r}"
    chain.upsert.assert_not_called()
    print("  ✓ returns None, no exception, .upsert() never reached "
          "(json.dumps fails before the call)")


def test_save_result_cache_logs_handler_name_and_error():
    print("\n[TEST] failure log names the handler and the error, tagged [CACHE]")
    sb, _ = _mock_result_cache_sb()

    with patch("api.db.logging.getLogger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        apidb.save_result_cache(sb, "T123", "some_future_handler",
                                "a question", POISONED_PAYLOAD)

    mock_logger.error.assert_called_once()
    logged = mock_logger.error.call_args[0][0]
    assert "[CACHE]" in logged
    assert "some_future_handler" in logged
    assert "save failed" in logged
    print(f"  ✓ logged: {logged!r}")


# ══════════════════════════════════════════════════════════════
# save_thread() integration: a poisoned cache doesn't abort the commit
# ══════════════════════════════════════════════════════════════

def _mock_save_thread_sb():
    """entity_registry empty (no entities to extract — keeps this test
    focused on the cache-write failure, not entity extraction) and
    conversation_threads.upsert() trivially succeeds."""
    entity_registry_chain = MagicMock()
    entity_registry_chain.select.return_value = entity_registry_chain
    entity_registry_chain.execute.return_value = MagicMock(data=[])

    conv_chain = MagicMock()
    conv_chain.upsert.return_value = conv_chain
    conv_chain.execute.return_value = MagicMock(data=[{"thread_ts": "T123"}])

    def _table(name):
        if name == "entity_registry":
            return entity_registry_chain
        if name == "conversation_threads":
            return conv_chain
        raise AssertionError(f"unexpected table: {name}")

    sb = MagicMock()
    sb.table = MagicMock(side_effect=_table)
    return sb, conv_chain


def test_save_thread_completes_normally_despite_cache_serialization_failure():
    """THE INTEGRATION PROOF. save_thread() must not raise, and the
    conversation_threads commit (history + entities) must still happen
    — only the cache reference is skipped."""
    print("\n[TEST] save_thread() completes normally despite a poisoned cache_payload")
    sb, conv_chain = _mock_save_thread_sb()

    tool_results = {"cache_payload": dict(POISONED_PAYLOAD)}

    raised = False
    try:
        apidb.save_thread(sb, "T123", "C1", history=[],
                          question="how's coverage?",
                          answer="Coverage is 0.75x.",
                          tool_results=tool_results,
                          handler_name="query_pipeline_coverage")
    except Exception as e:
        raised = True
        raise AssertionError(f"save_thread() raised despite the fix: {e}") from e

    assert not raised
    conv_chain.upsert.assert_called_once()
    upserted = conv_chain.upsert.call_args[0][0]
    import json as _json
    saved_history = _json.loads(upserted["history"])

    roles = [m.get("role") for m in saved_history]
    assert "user" in roles and "assistant" in roles, \
        "history commit must still include the user/assistant turn"
    assert not any(m.get("role") == apidb.CACHE_ROLE for m in saved_history), \
        "no cache reference should be appended when the cache write failed"
    print("  ✓ save_thread() did not raise; conversation_threads commit happened "
          "with history intact and no CACHE_ROLE entry")


# ══════════════════════════════════════════════════════════════
# Regression: real handler payload shapes still cache successfully
# ══════════════════════════════════════════════════════════════

def test_pipeline_coverage_payload_still_caches_including_stage_name():
    """Includes PR #115's stage_name field — confirms that addition
    didn't introduce anything unserializable."""
    print("\n[TEST] regression: query_pipeline_coverage payload (with stage_name) still caches")
    sb, chain = _mock_result_cache_sb()
    key = apidb.save_result_cache(sb, "T123", "query_pipeline_coverage",
                                  "how's coverage?", PIPELINE_COVERAGE_PAYLOAD)
    assert key is not None
    chain.upsert.assert_called_once()
    print("  ✓ query_pipeline_coverage payload (incl. stage_name) still persists")


def test_rep_attainment_payload_still_caches():
    print("\n[TEST] regression: query_rep_attainment payload still caches")
    sb, chain = _mock_result_cache_sb()
    key = apidb.save_result_cache(sb, "T123", "query_rep_attainment",
                                  "how's the team tracking?", REP_ATTAINMENT_PAYLOAD)
    assert key is not None
    chain.upsert.assert_called_once()
    print("  ✓ query_rep_attainment payload still persists")


def test_waterfall_payload_still_caches():
    print("\n[TEST] regression: query_waterfall's list-shaped payload still caches")
    sb, chain = _mock_result_cache_sb()
    key = apidb.save_result_cache(sb, "T123", "query_waterfall",
                                  "show me pipeline", WATERFALL_PAYLOAD)
    assert key is not None
    chain.upsert.assert_called_once()
    print("  ✓ query_waterfall payload still persists")


def main():
    tests = [
        test_planted_bug_old_unwrapped_write_raises_on_datetime_payload,
        test_save_result_cache_returns_none_on_serialization_failure,
        test_save_result_cache_logs_handler_name_and_error,
        test_save_thread_completes_normally_despite_cache_serialization_failure,
        test_pipeline_coverage_payload_still_caches_including_stage_name,
        test_rep_attainment_payload_still_caches,
        test_waterfall_payload_still_caches,
    ]
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
    print(f"\nTotal tests: {len(tests)}")
    print(f"  ✓ Passed: {passed}")
    if failed:
        print(f"  ✗ Failed: {len(failed)}")
        for name, error in failed:
            print(f"  - {name}")
            print(f"    {error[:200]}")
        return 1
    print("\n✅ All save_result_cache hardening tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
