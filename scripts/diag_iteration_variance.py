#!/usr/bin/env python3
"""
ITEM 3 (instrumented) — does the evaluator regeneration loop move the scores?

The determinism work (temperature 0, score = f(evidence)) was characterised on
SINGLE-PASS generation: the harness called generate() once. The nightly runs
the full loop — on a deal that fails the evaluator it regenerates up to 3 times,
and build_initial_messages() feeds the evaluator's `required_changes` back into
the generator ("You must fix these issues …"). So iterations 2-3 score from
evidence PLUS the evaluator's objections — a second input the characterisation
never varied. The stored score for a failed deal is iteration 3's.

This replays the real generate→evaluate loop for a few multi-iteration deals,
capturing the parsed component scores at EVERY iteration, and reports how far
they move and whether any move crosses a band boundary (yellow↔red changes the
coaching conversation; that is the thing at stake).

Read-only w.r.t. the DB (writes nothing back); makes generator/evaluator LLM
calls. Needs SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY.
Env: RUN_DATE (default 2026-08-23), VARIANCE_MAX_DEALS (default 3).
"""
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

# Line-buffer stdout so per-deal output survives a kill — CI block-buffers
# stdout, and this step makes slow LLM calls that can outlast a job timeout;
# without this a killed run flushes nothing (backfill lesson).
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

TODAY = os.getenv("RUN_DATE", "2026-08-23")
MAX_DEALS = int(os.getenv("VARIANCE_MAX_DEALS", "3"))
LIVESPORT = "62160567676"
CALL_EVIDENCE_CHAR_BUDGET = 120_000

_COMPONENT_MAP = {
    "Metrics": "metrics", "Economic Buyer": "economic_buyer",
    "Decision Criteria": "decision_criteria", "Decision Process": "decision_process",
    "Identified Pain": "pain", "Champion": "champion", "Competition": "competition",
}
_ORDER = ["metrics", "economic_buyer", "decision_criteria", "decision_process",
          "pain", "champion", "competition"]


def extract_scores(md):
    """Parse '<Component> … Score: N/10' per component — same shape as
    hubspot_deals._extract_scores_from_analysis, inlined to avoid needing a
    HubSpot client."""
    out = {}
    for label, key in _COMPONENT_MAP.items():
        m = re.search(rf'{re.escape(label)}.*?\*{{0,2}}Score\*{{0,2}}:\s*(\d+)/10',
                      md, re.DOTALL | re.IGNORECASE)
        out[key] = int(m.group(1)) if m else None
    return out


def band(score):
    if score is None:
        return "unread"
    return "red" if score <= 3 else "yellow" if score <= 6 else "green"


def _active_deals():
    idx = json.load(open(REPO / "memory" / "deals" / "index.json"))
    deals = idx.get("deals") if isinstance(idx.get("deals"), dict) else idx
    return {k: v for k, v in deals.items() if isinstance(v, dict) and v.get("deal_id")}


def _all_calls_text(sb, deal_id):
    from supabase_client import select_all
    rows = select_all(sb, "calls", columns="deal_id,call_date,summary,title",
                      filters=[("eq", "deal_id", str(deal_id))])
    dated = []
    for r in rows:
        summ = (r.get("summary") or "").strip()
        if summ:
            dated.append((str(r.get("call_date") or ""), summ))
    dated.sort(key=lambda x: x[0])
    used, kept = 0, []
    for dt, summ in reversed(dated):
        block = f"## Call — {dt or 'unknown date'}\n\n{summ}"
        if used + len(block) > CALL_EVIDENCE_CHAR_BUDGET and kept:
            continue
        used += len(block); kept.append(block)
    kept.reverse()
    return "\n\n---\n\n".join(kept), len(dated)


def _neutral_state(company):
    return {"company": company, "calls_reviewed": 0,
            "meddicc_state": {k: {"status": "unknown", "evidence": "", "score": 0}
                              for k in _ORDER},
            "key_context": "neutral (probe): prior state must not influence the score"}


def _deal_context(entry):
    return {"deal": {"properties": {"closedate": entry.get("close_date", "Unknown"),
                                    "incremental_arr": entry.get("arr", "0"),
                                    "dealname": entry.get("deal_name", entry.get("company_name"))}},
            "company": {"properties": {"name": entry.get("company_name", "Unknown")}},
            "contacts": []}


def pick_deals(sb):
    """Multi-iteration deals from today's run (iterations>=2), LiveSport first."""
    from supabase_client import select_all
    rows = select_all(sb, "analyses",
                      columns="deal_id,company_name,passed,iterations,overall_score,"
                              "champion_score,analyzed_at",
                      filters=[("gte", "analyzed_at", TODAY)])
    latest = {}
    for r in rows:
        did = str(r.get("deal_id"))
        if did not in latest or str(r.get("analyzed_at") or "") > str(latest[did].get("analyzed_at") or ""):
            latest[did] = r
    multi = [r for r in latest.values() if int(r.get("iterations") or 0) >= 2]
    multi.sort(key=lambda r: (r.get("deal_id") != LIVESPORT, r.get("deal_id")))
    return multi[:MAX_DEALS], latest


def main():
    from supabase_client import SupabaseWriter
    from meddicc_agent import (generate, evaluate, load_claude_md,
                               load_evaluator_rubric)
    from llm_client import LLMClient
    sb = SupabaseWriter().client
    index = _active_deals()
    claude_md = load_claude_md()
    rubric = load_evaluator_rubric()
    gen = LLMClient.from_config("generator")
    ev = LLMClient.from_config("evaluator")

    picks, latest = pick_deals(sb)
    print("=" * 78)
    print("ITEM 3 — evaluator-loop score variance (iteration 1 vs final)")
    print(f"replaying the real generate→evaluate loop for {len(picks)} multi-"
          "iteration deal(s) from today's run")
    print("=" * 78)
    if not picks:
        print("No multi-iteration deals found today — nothing to instrument.")
        return 0

    for r in picks:
        did = str(r["deal_id"])
        entry = index.get(did, {"company_name": r.get("company_name")})
        company = entry.get("company_name") or r.get("company_name") or did
        calls_text, ncalls = _all_calls_text(sb, did)
        print(f"\n{'─'*78}\n{company}  (deal {did})  — {ncalls} calls  "
              f"| run#37 stored: overall={r.get('overall_score')}/70 "
              f"champ={r.get('champion_score')} iters={r.get('iterations')} "
              f"passed={r.get('passed')}")
        if not calls_text.strip():
            print("  (no call text in Supabase — skipping)")
            continue

        state = _neutral_state(company)
        ctx = _deal_context(entry)
        feedback = None
        per_iter = []
        for it in range(1, 4):
            draft = generate(calls_text, state, ctx, feedback, claude_md, gen,
                             tracker=None, company=company)
            scores = extract_scores(draft)
            ev_res = evaluate(draft, calls_text, state, rubric, ev,
                              tracker=None, company=company)
            passed = bool(ev_res.get("pass"))
            per_iter.append((it, scores, passed))
            print(f"  iter {it}: passed={passed}  " +
                  "  ".join(f"{k[:4]}={scores.get(k)}({band(scores.get(k))[0]})"
                            for k in _ORDER))
            if passed:
                break
            feedback = ev_res.get("required_changes")

        # movement iter1 → final
        first, final = per_iter[0][1], per_iter[-1][1]
        print(f"  ── movement iter1 → iter{per_iter[-1][0]}:")
        moved, crossed = 0, 0
        for k in _ORDER:
            a, b = first.get(k), final.get(k)
            if a is None or b is None:
                continue
            d = b - a
            if d != 0:
                moved += 1
                cross = band(a) != band(b)
                crossed += 1 if cross else 0
                flag = f"  ⚠️ BAND {band(a)}→{band(b)}" if cross else ""
                print(f"       {k:16} {a}→{b} ({d:+d}){flag}")
        if moved == 0:
            print("       (no component moved — loop stable for this deal)")
        else:
            print(f"     → {moved} component(s) moved, {crossed} crossed a band boundary")

    print("\n" + "=" * 78)
    print("Read the per-deal movement above: any band crossing between iteration 1")
    print("and the stored final iteration is a score change the determinism")
    print("characterisation (single-pass only) never measured.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
