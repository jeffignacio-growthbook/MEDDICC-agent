#!/usr/bin/env python3
"""
Characterize scoring determinism across deals (FIX_MEDDICC_SCORING_PIPELINE
follow-up): quantify how often and how widely each MEDDICC component moves,
run-over-run at temperature 0, on LiveSport AND a few other deals.

The question this answers: is champion unstable ONLY on LiveSport (a
borderline-evidence case → ensemble the generator) or do components wobble
across deals (band boundaries too tight for the evidence the generator can
extract → fix the rubric)? Different findings, different fixes; do not spend 3x
on ensembling until the numbers say which.

Not an acceptance gate — a measurement. Needs ANTHROPIC_API_KEY + SUPABASE_*.
Env knobs: PRIMARY_RUNS (default 15), SECONDARY_RUNS (default 8),
SECONDARY_DEALS (default 2).
"""
import os
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

LIVESPORT_DEAL_ID = "62160567676"
PRIMARY_RUNS = int(os.getenv("PRIMARY_RUNS", "15"))
SECONDARY_RUNS = int(os.getenv("SECONDARY_RUNS", "8"))
SECONDARY_DEALS = int(os.getenv("SECONDARY_DEALS", "2"))
COMPONENT_MAP = {
    "Metrics": "metrics", "Economic Buyer": "economic_buyer",
    "Decision Criteria": "decision_criteria",
    "Decision Process": "decision_process", "Identified Pain": "pain",
    "Champion": "champion", "Competition": "competition",
}
_SCORE_COLS = {v + "_score": v for v in COMPONENT_MAP.values()}


def _extract_scores(text):
    # Use the shared, format-tolerant extractor (Score\D*?(\d+)\s*/\s*10) so a
    # markdown variation like '**Score:**' is not misread as a parse miss and
    # mistaken for score nondeterminism. Same function the pin + downstream use.
    from meddicc_agent import _extract_component_scores
    return _extract_component_scores(text or "")


def _calls_for(sb, deal_id):
    from supabase_client import select_all
    rows = select_all(sb, "calls", columns="deal_id,call_date,summary",
                      filters=[("eq", "deal_id", deal_id)])
    pairs = [(r.get("call_date") or "", r.get("summary") or "")
             for r in rows if (r.get("summary") or "").strip()]
    pairs.sort(key=lambda x: x[0])
    return pairs


def _pick_secondary(sb):
    """Deals (besides LiveSport) with the most call evidence AND a passed
    analysis — real, scoreable deals, so instability there means something."""
    from supabase_client import select_all
    calls = select_all(sb, "calls", columns="deal_id")
    by_deal = Counter(c.get("deal_id") for c in calls if c.get("deal_id"))
    passed = {a.get("deal_id") for a in
              select_all(sb, "analyses", columns="deal_id,passed")
              if a.get("passed")}
    names = {d["deal_id"]: d.get("company_name") for d in
             select_all(sb, "deals", columns="deal_id,company_name")}
    ranked = [did for did, n in by_deal.most_common()
              if did != LIVESPORT_DEAL_ID and n >= 3 and did in passed]
    return [(did, names.get(did) or did) for did in ranked[:SECONDARY_DEALS]]


def _characterize(sb, deal_id, company, n_runs):
    from meddicc_agent import generate, load_claude_md
    from llm_client import LLMClient
    pairs = _calls_for(sb, deal_id)
    if not pairs:
        print(f"\n### {company} ({deal_id}): no calls — skipped")
        return
    all_calls = "\n\n---\n\n".join(
        f"## Call — {d or 'unknown'}\n\n{s}" for d, s in pairs)
    deal_ctx = {"deal": {"properties": {"amount": "0", "closedate": "2027-01-01"}},
                "company": {"properties": {"name": company}}, "contacts": [{}]}
    cum = {"company": company, "calls_reviewed": 0, "meddicc_state": {}, "key_context": ""}
    gen = LLMClient.from_config("generator")
    md = load_claude_md()

    runs = []
    for i in range(n_runs):
        draft = generate(all_calls, cum, deal_ctx, None, md, gen, None, company)
        runs.append(_extract_scores(draft or ""))
    print(f"\n### {company} ({deal_id}) — {n_runs} runs, {len(pairs)} calls")
    print(f"{'component':20} mode  spread  distribution")
    unstable = []
    for key in COMPONENT_MAP.values():
        vals = [r.get(key) for r in runs]
        nums = [v for v in vals if isinstance(v, int)]
        if not nums:
            print(f"{key:20} —     —       (unparsed)")
            continue
        dist = Counter(nums)
        mode = dist.most_common(1)[0][0]
        spread = max(nums) - min(nums)
        if spread > 0:
            unstable.append((key, spread))
        diststr = " ".join(f"{v}×{c}" for v, c in sorted(dist.items()))
        flag = "" if spread == 0 else "  <-- moves"
        print(f"{key:20} {mode:<5} {spread:<7} {diststr}{flag}")
    overalls = [sum(v for v in r.values() if isinstance(v, int)) for r in runs]
    print(f"overall/70 distribution: {dict(sorted(Counter(overalls).items()))}")
    return {"company": company, "unstable": unstable}


def main():
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — cannot characterize"); return 2
    from api.db import get_supabase
    sb = get_supabase()
    print("=" * 76)
    print(f"SCORING DETERMINISM CHARACTERIZATION — temperature 0")
    print(f"primary={PRIMARY_RUNS} runs, secondary={SECONDARY_RUNS} runs × "
          f"{SECONDARY_DEALS} deals")
    print("=" * 76)

    results = []
    r = _characterize(sb, LIVESPORT_DEAL_ID, "Livesport", PRIMARY_RUNS)
    if r:
        results.append(r)
    for did, name in _pick_secondary(sb):
        r = _characterize(sb, did, name, SECONDARY_RUNS)
        if r:
            results.append(r)

    print("\n" + "=" * 76)
    print("VERDICT")
    print("=" * 76)
    any_unstable = False
    champ_only = True
    for r in results:
        if r["unstable"]:
            any_unstable = True
            comps = ", ".join(f"{c}(±{s})" for c, s in r["unstable"])
            print(f"  {r['company']:24} unstable: {comps}")
            if any(c != "champion" for c, _ in r["unstable"]):
                champ_only = False
        else:
            print(f"  {r['company']:24} fully stable (spread 0 all components)")
    print()
    if not any_unstable:
        print("READING: fully deterministic across all deals sampled.")
    elif champ_only:
        print("READING: only champion moves. Borderline-evidence case → the fix\n"
              "is generator ensembling (median of N), not the rubric.")
    else:
        print("READING: components beyond champion move, and/or across deals →\n"
              "band boundaries are too tight for the evidence the generator can\n"
              "extract. The fix is in the rubric, not (only) ensembling.")
    print("=" * 76)


if __name__ == "__main__":
    main()
