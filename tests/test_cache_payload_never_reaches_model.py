#!/usr/bin/env python3
"""
cache_payload is for thread follow-ups, never for the model.

query_waterfall returns cache_payload (every deal closing in the period,
with deal_value and arr_usd), commented "Retained, NOT shown". Only
save_thread() stripped it, after synthesis. Live on 2026-09-24 ("how has
pipeline moved this quarter?") the model read those raw rows and computed
"Wins to date ~$374K": arithmetic on deal_value/arr_usd with no stated
basis, contradicting the waterfall's own $80K won.

Now every model-facing serializer drops it (router._model_view), and the
returned payload keeps it so save_thread can still cache and extract
entities from it.

Runs the real query_waterfall (fake Supabase), plants a sentinel deal in
its cache_payload, and checks both synthesis paths plus the returned
payload.
"""
import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.router as router  # noqa: E402
import test_waterfall_basis_and_disclosure as wf  # noqa: E402
from canary_harness import run_canary_case  # noqa: E402

SENTINEL = "CACHE_PAYLOAD_SENTINEL_777"


def _result_with_sentinel():
    r = wf._run_handler()
    assert "cache_payload" in r, "query_waterfall no longer returns cache_payload"
    r["cache_payload"]["deals"].append(
        {"deal_id": "999", "company_name": SENTINEL, "deal_value": 374000,
         "arr_usd": 374000, "stage": "closedwon", "deal_status": "won"})
    return r


def test_dynamic_loop_synthesis_never_sees_cache_payload():
    r = _result_with_sentinel()
    rep = run_canary_case("show me this quarter's pipeline waterfall", "query_waterfall",
                          {}, r, time_window=wf.TW)
    assert rep["tool_executed"]
    assert SENTINEL not in rep["synthesis_text"], "cache_payload reached the dynamic loop's model"
    assert '"cache_payload"' not in rep["synthesis_text"]
    returned = json.dumps(rep["result"].get("tool_results", {}), default=str)
    assert SENTINEL in returned, "save_thread needs cache_payload in the returned payload"
    print("✓ dynamic loop: cache_payload absent from the synthesis input, still in the "
          "returned payload for save_thread")


def test_classifier_path_synthesis_never_sees_cache_payload():
    r = _result_with_sentinel()
    payload = router._smart_truncate_for_synthesis(
        router._cap_rows_for_synthesis(copy.deepcopy(r)), router.SYNTH_PAYLOAD_CHARS)
    assert SENTINEL not in payload and '"cache_payload"' not in payload
    assert "cache_payload" in r, "the caller's dict must not be mutated"
    print("✓ classifier path: cache_payload absent from the synthesis input; caller's dict intact")


def test_everything_else_still_reaches_the_model():
    r = _result_with_sentinel()
    rep = run_canary_case("show me this quarter's pipeline waterfall", "query_waterfall",
                          {}, r, time_window=wf.TW)
    missing = [k for k in rep["keys_missing_from_synthesis"]
               if k not in ("cache_payload", "__canary_field__")]
    assert not missing, missing
    assert rep["channels"]["synthesis_input"], "the canary (every other key) must still get through"
    print("✓ every other key of the result still reaches the model")


if __name__ == "__main__":
    test_dynamic_loop_synthesis_never_sees_cache_payload()
    test_classifier_path_synthesis_never_sees_cache_payload()
    test_everything_else_still_reaches_the_model()
    print("\n✅ All tests passed")
