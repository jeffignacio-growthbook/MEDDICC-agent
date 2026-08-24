#!/usr/bin/env python3
"""
Smoke test suite for the CRO agent.
Runs after every deploy to catch silent failures before
they reach Ryan.

Usage:
  RAILWAY_URL=https://... python scripts/smoke_test.py
  RAILWAY_URL=https://... python scripts/smoke_test.py --verbose

Exit code 0 = all passed. Non-zero = failures detected.
"""

import os, sys, json, time, asyncio
import httpx

RAILWAY_URL = os.environ.get("RAILWAY_URL", "")
TIMEOUT = 90  # seconds per question
ZAP_REPLY_URL = os.environ.get("ZAP_REPLY_URL", "")

# The channel_id the agent echoes back to the Zap IS the Slack routing target,
# so this must never be a real channel. Default to an obvious sandbox marker;
# set SMOKE_TEST_CHANNEL (workflow var/secret) to the real sandbox channel.
SMOKE_TEST_CHANNEL = os.environ.get("SMOKE_TEST_CHANNEL", "sandbox-smoke-test")

# Each test: (question, handler_hint, required_content)
# required_content: strings that MUST appear in the answer
# (case-insensitive). Empty list = just check non-empty.
TESTS = [
    (
        "what is our pipeline this week?",
        "query_waterfall",
        ["pipeline", "$"],
    ),
    (
        "show me the Skyscanner deal",
        "query_deal",
        ["Skyscanner", "/10"],
    ),
    (
        "what does a 6 mean for champion?",
        "query_rubric",
        ["champion", "6"],
    ),
    (
        "which deals are at risk?",
        "query_deals_at_risk",
        [],  # may legitimately be empty
    ),
    (
        "what are our top objections this quarter?",
        "query_objections",
        ["objection"],
    ),
    (
        "show me ARR by customer",
        "query_arr",
        ["$", "ARR"],
    ),
    (
        "why did we lose our last three deals?",
        "query_win_loss",
        ["lost", "data"],
    ),
    (
        "what competitors keep coming up in our calls?",
        "query_competitive_intel",
        ["competitor", "Statsig"],
    ),
]

captured_replies = {}  # thread_ts → answer text

async def send_question(client: httpx.AsyncClient,
                         question: str,
                         test_id: str) -> str:
    """POST a question to Railway and capture the reply."""
    thread_ts = f"smoke_{test_id}_{int(time.time())}"
    resp = await client.post(
        f"{RAILWAY_URL}/slack/question",
        json={
            "text": question,
            "user_id": "smoke_test",
            "channel_id": SMOKE_TEST_CHANNEL,
            "thread_ts": thread_ts,
            "ts": thread_ts,
        },
        timeout=30,
    )
    assert resp.status_code == 200, \
        f"POST failed: {resp.status_code}"
    return thread_ts

async def run_tests(verbose: bool = False) -> list:
    results = []
    async with httpx.AsyncClient() as client:
        # Health check first
        health = await client.get(f"{RAILWAY_URL}/health",
                                   timeout=10)
        if health.status_code != 200:
            print(f"❌ Health check failed: {health.status_code}")
            sys.exit(1)
        print(f"✓ Health check passed\n")

        for i, (question, handler, required) in enumerate(TESTS):
            test_id = f"t{i}"
            if verbose:
                print(f"Testing: {question}")

            start = time.time()
            try:
                thread_ts = await send_question(
                    client, question, test_id)
                # Poll conversation_threads for the reply
                # (simpler than setting up a full Zapier mock)
                answer = await poll_for_reply(
                    thread_ts, timeout=TIMEOUT)
                elapsed = time.time() - start

                # Check required content
                failures = []
                if not answer:
                    failures.append("empty response")
                elif "don't have data" in answer.lower() and required:
                    failures.append("unanswerable when data expected")
                else:
                    for term in required:
                        if term.lower() not in answer.lower():
                            failures.append(
                                f"missing '{term}' in answer")

                if failures:
                    print(f"❌ [{handler}] {question[:50]}")
                    for f in failures:
                        print(f"     → {f}")
                    if verbose:
                        print(f"     Answer: {answer[:200]}")
                    results.append(("FAIL", question,
                                    failures, answer))
                else:
                    print(f"✓  [{handler}] "
                          f"{question[:50]} ({elapsed:.1f}s)")
                    results.append(("PASS", question,
                                    [], answer))

            except Exception as e:
                import traceback
                print(f"❌ [{handler}] {question[:50]}: {e}")
                print(f"     Traceback: {traceback.format_exc()}")
                results.append(("ERROR", question, [str(e)], ""))

    return results

async def poll_for_reply(thread_ts: str,
                          timeout: int = 90) -> str:
    """Poll conversation_threads for the agent's reply."""
    import os
    from supabase import create_client
    sb = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"])

    deadline = time.time() + timeout
    poll_count = 0
    while time.time() < deadline:
        await asyncio.sleep(3)
        poll_count += 1
        r = sb.table("conversation_threads")\
              .select("history")\
              .eq("thread_ts", thread_ts)\
              .execute()
        print(f"     Poll {poll_count}: found {len(r.data) if r.data else 0} records")
        if r.data:
            history = json.loads(
                r.data[0].get("history", "[]")
            ) if isinstance(
                r.data[0].get("history"), str
            ) else (r.data[0].get("history") or [])
            assistant_msgs = [
                m["content"] for m in history
                if m.get("role") == "assistant"
            ]
            print(f"     History has {len(history)} messages, {len(assistant_msgs)} from assistant")
            if assistant_msgs:
                return assistant_msgs[-1]
    print(f"     Timeout after {poll_count} polls")
    return ""

def main():
    if not RAILWAY_URL:
        print("Set RAILWAY_URL environment variable")
        sys.exit(1)

    verbose = "--verbose" in sys.argv
    results = asyncio.run(run_tests(verbose))

    passed = sum(1 for r in results if r[0] == "PASS")
    failed = sum(1 for r in results if r[0] != "PASS")

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")

    if failed:
        sys.exit(1)
    else:
        print("All smoke tests passed ✓")
        sys.exit(0)

if __name__ == "__main__":
    main()
