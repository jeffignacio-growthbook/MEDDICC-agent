#!/usr/bin/env python3
"""
Acceptance gate for the pin-score-to-iteration-1 change.

Runs the FULL agent loop (generate → evaluate → regenerate → pin) N times on a
deal that FAILS the evaluator and regenerates — LiveSport, the deal this whole
thread started from and which went to iteration 3 in run #37. Pass-on-iteration-1
deals were already deterministic; a regenerating deal is the real test.

PASS criterion: the stored (pinned) component scores — Champion above all — are
identical across all N runs. If Champion comes back the same value every run
instead of swinging 5→2, the pin holds where it matters.

Needs SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY.
Env: PIN_DEAL_ID (default LiveSport 62160567676), PIN_RUNS (default 5).
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

DEAL_ID = os.getenv("PIN_DEAL_ID", "62160567676")
RUNS = int(os.getenv("PIN_RUNS", "5"))
CALL_BUDGET = 120_000
_ORDER = ["metrics", "economic_buyer", "decision_criteria", "decision_process",
          "pain", "champion", "competition"]


def _index_entry(deal_id):
    idx = json.load(open(REPO / "memory" / "deals" / "index.json"))
    deals = idx.get("deals") if isinstance(idx.get("deals"), dict) else idx
    return deals.get(deal_id, {})


def _all_calls_text(sb, deal_id):
    from supabase_client import select_all
    rows = select_all(sb, "calls", columns="deal_id,call_date,summary",
                      filters=[("eq", "deal_id", str(deal_id))])
    dated = sorted(((str(r.get("call_date") or ""), (r.get("summary") or "").strip())
                    for r in rows if (r.get("summary") or "").strip()),
                   key=lambda x: x[0])
    used, kept = 0, []
    for dt, summ in reversed(dated):
        block = f"## Call — {dt or 'unknown date'}\n\n{summ}"
        if used + len(block) > CALL_BUDGET and kept:
            continue
        used += len(block); kept.append(block)
    kept.reverse()
    return "\n\n---\n\n".join(kept), len(dated)


def main():
    from supabase_client import SupabaseWriter
    from meddicc_agent import run_agent, _extract_component_scores
    sb = SupabaseWriter().client

    entry = _index_entry(DEAL_ID)
    company = entry.get("company_name", DEAL_ID)
    calls_text, ncalls = _all_calls_text(sb, DEAL_ID)
    ctx = {"deal": {"properties": {"closedate": entry.get("close_date", "Unknown"),
                                   "incremental_arr": entry.get("arr", "0"),
                                   "dealname": entry.get("deal_name", company)}},
           "company": {"properties": {"name": company}}, "contacts": []}
    state = {"company": company, "calls_reviewed": 0,
             "meddicc_state": {k: {"status": "unknown", "evidence": "", "score": 0} for k in _ORDER},
             "key_context": "neutral (characterization): prior state must not influence the score"}

    print("=" * 78)
    print(f"PINNED-PIPELINE CHARACTERIZATION — {company} (deal {DEAL_ID}), "
          f"{ncalls} calls, {RUNS} full-loop runs")
    print("=" * 78)
    if not calls_text.strip():
        print("No call text — cannot characterize."); return 2

    runs = []
    for i in range(1, RUNS + 1):
        result = run_agent(calls_text, state, ctx, company=company)
        stored = _extract_component_scores(result["draft"])   # what downstream reads
        runs.append({"pinned": result.get("pinned_scores") or {}, "stored": stored,
                     "iters": result["iterations"], "passed": result["passed"],
                     "scores_pinned": result.get("scores_pinned"),
                     "mism": result.get("pin_mismatches")})
        print(f"\nrun {i}: iters={result['iterations']} passed={result['passed']} "
              f"pinned={result.get('scores_pinned')} mismatches={result.get('pin_mismatches')}")
        print("  stored (what HubSpot/Supabase parse): " +
              "  ".join(f"{k[:4]}={stored.get(k)}" for k in _ORDER))

    # Verdict: are the stored scores identical across all runs?
    print("\n" + "=" * 78)
    all_stable = True
    for k in _ORDER:
        vals = Counter(r["stored"].get(k) for r in runs)
        stable = len(vals) == 1
        all_stable = all_stable and stable
        flag = "" if stable else "  ⚠️ NOT STABLE"
        print(f"  {k:16} across {RUNS} runs: {dict(vals)}{flag}")
    champ = Counter(r["stored"].get("champion") for r in runs)
    print("\n" + "=" * 78)
    if all_stable:
        print(f"PASS — every component identical across {RUNS} full-loop runs. "
              f"Champion = {list(champ)[0]} every run (no 5→2 swing).")
    else:
        print(f"FAIL — at least one component moved across runs. Champion: {dict(champ)}. "
              "The pin is not holding end-to-end; investigate before the Ryan conversation.")
    print("=" * 78)
    return 0 if all_stable else 1


if __name__ == "__main__":
    sys.exit(main())
