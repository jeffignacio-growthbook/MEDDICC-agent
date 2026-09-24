#!/usr/bin/env python3
"""
Live routing eval: which tool does the dynamic loop's model pick for each
pipeline phrase?

Runs the real dynamic_query_loop (real system prompt and tool list, real
Supabase for schema and roster, real generator model) up to its FIRST model
call, records the tool the model chose, and stops there: no tool runs, and
query_cost_log is not written.

Phrases: tests/test_pipeline_routing_split.EXPECTED (asserted) plus the
questions asked live on 2026-09-24 (the movement one asserted, the other
reported).

    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... ANTHROPIC_API_KEY=... \\
        python scripts/eval_dynamic_routing.py [--repeats N]

Exit 1 if any asserted phrase routes to the wrong tool on any repeat.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "api"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import api.router as router  # noqa: E402
from llm_client import LLMClient  # noqa: E402
from test_pipeline_routing_split import EXPECTED  # noqa: E402

LIVE = {
    "how has pipeline moved this quarter?": "query_pipeline_movement",
}
PROBES = ["what does our pipeline look like this quarter?", "pipeline"]

TIME_WINDOW = {"label": "FY2027 Q3", "start": "2026-08-01", "end": "2026-10-31"}


class _Stop(Exception):
    pass


class FirstCallOnly:
    """Forwards the loop's first model call to the real client, records the
    parsed tool choice, then stops the loop."""

    def __init__(self, real):
        self.real = real
        self.choice = None
        self.raw = None

    def complete(self, messages=None, system=None, max_tokens=None, **kw):
        resp = self.real.complete(messages=messages, system=system, max_tokens=max_tokens, **kw)
        self.raw = resp.text
        parsed = router._extract_json(resp.text) or {}
        self.choice = parsed.get("tool") or ("<answer>" if parsed.get("answer") else "<unparsed>")
        raise _Stop()


def route_once(question, sb, generator, classifier, roster_text):
    client = FirstCallOnly(generator)
    try:
        asyncio.run(router.dynamic_query_loop(
            question=question, history=[], params={"time_window": TIME_WINDOW}, sb=sb,
            client=client, roster_text=roster_text, classifier_client=classifier))
    except _Stop:
        pass
    return client.choice, client.raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=2)
    args = ap.parse_args()

    router._log_query_cost = lambda *a, **k: None       # eval traffic stays out of the log
    sb = router.get_supabase()
    generator = LLMClient.from_config(role="generator")
    classifier = LLMClient.from_config(role="classifier")
    roster = sb.table("user_personas").select("name,email,role").execute().data or []
    roster_text = "\n".join(f"- {r['name']} — {r['email']} ({r['role']})" for r in roster)

    asserted = {**EXPECTED, **LIVE}
    wrong, rows = [], []
    for q in list(asserted) + PROBES:
        picks = [route_once(q, sb, generator, classifier, roster_text)[0] for _ in range(args.repeats)]
        want = asserted.get(q)
        ok = want is None or all(p == want for p in picks)
        rows.append({"question": q, "expected": want, "picked": picks, "ok": ok})
        if not ok:
            wrong.append(q)
        print(f"{'OK ' if ok else 'BAD'} {q!r:52} expected={want or '(probe)':25} picked={picks}", flush=True)

    n = len(asserted)
    print(f"\n{n - len(wrong)}/{n} asserted phrases routed correctly on all {args.repeats} repeats")
    print(json.dumps(rows))
    sys.exit(1 if wrong else 0)


if __name__ == "__main__":
    main()
