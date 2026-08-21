#!/usr/bin/env python3
"""
Part 1 acceptance gate (FIX_MEDDICC_SCORING_PIPELINE): run the SAME deal five
times and report every component score for each run.

Acceptance: identical component scores across all five runs. "Less variance" is
not the same as "deterministic" — only identical scores make the number mean
anything (the caution: a score that looked like a judgment was a sample).

Evidence source: Livesport's calls from Supabase (deal 62160567676), falling
back to the committed call cache. The evidence is frozen; the only thing being
tested is whether the score is now a function of it.

Needs ANTHROPIC_API_KEY (+ SUPABASE_* if sourcing calls from Supabase). CI only.
"""
import os
import re
import sys
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

LIVESPORT_DEAL_ID = "62160567676"
N_RUNS = 5
COMPONENT_MAP = {
    "Metrics": "metrics", "Economic Buyer": "economic_buyer",
    "Decision Criteria": "decision_criteria",
    "Decision Process": "decision_process", "Identified Pain": "pain",
    "Champion": "champion", "Competition": "competition",
}


def _extract_scores(text):
    """Same regex hubspot_deals._extract_scores_from_analysis uses."""
    out = {}
    for comp, key in COMPONENT_MAP.items():
        m = re.search(rf"{re.escape(comp)}.*?\*{{0,2}}Score\*{{0,2}}:\s*(\d+)/10",
                      text, re.DOTALL | re.IGNORECASE)
        out[key] = int(m.group(1)) if m else None
    return out


def _load_calls():
    """(source, [(date, summary), ...]) oldest→newest."""
    try:
        from api.db import get_supabase
        from supabase_client import select_all
        sb = get_supabase()
        rows = select_all(sb, "calls",
                          columns="deal_id,call_date,summary,title",
                          filters=[("eq", "deal_id", LIVESPORT_DEAL_ID)])
        pairs = [(r.get("call_date") or "", r.get("summary") or "")
                 for r in rows if (r.get("summary") or "").strip()]
        if pairs:
            pairs.sort(key=lambda x: x[0])
            return "supabase", pairs
    except Exception as e:
        print(f"[calls] Supabase load failed ({e}); falling back to cache")
    cache = REPO / "memory" / "calls" / "livesport-growthbook.json"
    d = json.loads(cache.read_text())
    pairs = [(c.get("date") or "", c.get("summary") or "")
             for c in d.get("calls", []) if (c.get("summary") or "").strip()]
    pairs.sort(key=lambda x: x[0])
    return "cache", pairs


def main():
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — cannot run the live determinism test")
        return 2

    source, pairs = _load_calls()
    print("=" * 72)
    print(f"SCORING DETERMINISM — Livesport, {N_RUNS} runs, temperature 0")
    print(f"evidence: {len(pairs)} call(s) from {source} "
          f"({', '.join(d for d, _ in pairs)})")
    print("=" * 72)
    if not pairs:
        print("no calls found — cannot run")
        return 2

    all_calls_text = "\n\n---\n\n".join(
        f"## Call — {d or 'unknown date'}\n\n{s}" for d, s in pairs)

    deal_context = {
        "deal": {"properties": {"amount": "260000", "closedate": "2027-01-01"}},
        "company": {"properties": {"name": "Livesport"}},
        "contacts": [{}, {}, {}],
    }
    # Neutral prior state, held identical across runs. If scoring is a pure
    # function of the calls, this never moves the numbers.
    cumulative_state = {"company": "Livesport", "calls_reviewed": 0,
                        "meddicc_state": {}, "key_context": ""}

    from meddicc_agent import run_agent

    runs = []
    for i in range(1, N_RUNS + 1):
        print(f"\n--- run {i}/{N_RUNS} ---")
        result = run_agent(call_summary=all_calls_text,
                           cumulative_state=cumulative_state,
                           deal_context=deal_context, company="Livesport")
        scores = _extract_scores(result["draft"] or "")
        overall = sum(v for v in scores.values() if isinstance(v, int))
        runs.append({"scores": scores, "overall": overall,
                     "passed": result.get("passed"),
                     "iterations": result.get("iterations")})
        print(f"  scores={scores} overall={overall}/70 "
              f"passed={result.get('passed')} iters={result.get('iterations')}")

    print("\n" + "=" * 72)
    print("PER-COMPONENT SPREAD ACROSS RUNS")
    print("=" * 72)
    keys = list(COMPONENT_MAP.values())
    hdr = f"{'component':20}" + "".join(f"r{i+1:<4}" for i in range(N_RUNS)) + "spread"
    print(hdr)
    all_identical = True
    for k in keys:
        vals = [r["scores"].get(k) for r in runs]
        nums = [v for v in vals if isinstance(v, int)]
        spread = (max(nums) - min(nums)) if nums else None
        if spread != 0:
            all_identical = False
        cells = "".join(f"{str(v):<5}" for v in vals)
        flag = "" if spread == 0 else "  <-- VARIES"
        print(f"{k:20}{cells}spread={spread}{flag}")
    overalls = [r["overall"] for r in runs]
    if len(set(overalls)) != 1:
        all_identical = False
    print(f"\noverall/70 across runs: {overalls}")
    print(f"passed across runs:    {[r['passed'] for r in runs]}")

    print("\n" + "=" * 72)
    if all_identical:
        print("RESULT: ✅ DETERMINISTIC — identical component scores across all runs")
    else:
        print("RESULT: ❌ NOT deterministic — components still vary (see above). "
              "The score is not yet a pure function of the evidence.")
    print("=" * 72)
    return 0 if all_identical else 1


if __name__ == "__main__":
    sys.exit(main())
