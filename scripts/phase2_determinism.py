#!/usr/bin/env python3
"""
Phase 2 determinism check (PROGRESSIVE_SCORING_SPEC).

Score ONE call N times at temperature 0 and report the spread. Per-call scoring
is a much smaller, better-posed task than the batch scorer, so it should be
essentially deterministic; if a component wobbles, the prompt is ambiguous. This
also exercises PASS 1 (the selection gate) for stability — a flapping gate would
be its own nondeterminism, upstream of the scores.

Scored as a FIRST call (prior_state=None): fixed input, no upstream variance, so
any spread is the scorer's own. Needs ANTHROPIC_API_KEY + SUPABASE_*.
Env: PHASE2_DEAL_ID (default Livesport 62160567676), PHASE2_RUNS (default 5),
PHASE2_CALL_DATE (pick a specific call by date; default = the largest transcript,
which advances the most components and so stresses determinism hardest).
"""
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

import call_scorer as cs  # noqa: E402

DEAL_ID = os.getenv("PHASE2_DEAL_ID", "62160567676")
RUNS = int(os.getenv("PHASE2_RUNS", "5"))
CALL_DATE = os.getenv("PHASE2_CALL_DATE", "")


def _pick_call(sb):
    """Return (call_id, call_date, text, source). Default: the deal's largest
    transcript; or the call matching PHASE2_CALL_DATE."""
    from supabase_client import select_all
    calls = select_all(sb, "calls", columns="call_id,call_date,summary",
                        filters=[("eq", "deal_id", str(DEAL_ID))])
    calls = [c for c in calls if c.get("call_date")]
    if not calls:
        return None
    ids = [c["call_id"] for c in calls]
    tx = {r["call_id"]: r for r in select_all(
        sb, "call_transcripts",
        columns="call_id,transcript,transcript_quality,char_count",
        filters=[("in_", "call_id", ids)])}
    cands = []
    for c in calls:
        t = tx.get(c["call_id"])
        if t and (t.get("transcript") or "").strip() and t.get("transcript_quality") in ("full", "partial"):
            cands.append((c["call_id"], c["call_date"], t["transcript"].strip(), "transcript", len(t["transcript"])))
        elif (c.get("summary") or "").strip():
            cands.append((c["call_id"], c["call_date"], c["summary"].strip(), "summary", len(c["summary"])))
    if not cands:
        return None
    if CALL_DATE:
        for cid, d, text, src, n in cands:
            if str(d).startswith(CALL_DATE):
                return cid, d, text, src
    cid, d, text, src, _ = max(cands, key=lambda x: x[4])  # largest
    return cid, d, text, src


def main():
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — cannot score"); return 2
    try:
        from api.db import get_supabase
        sb = get_supabase()
    except Exception:
        from supabase_client import SupabaseWriter
        sb = SupabaseWriter().client
    from llm_client import LLMClient
    client = LLMClient.from_config("generator")

    picked = _pick_call(sb)
    if not picked:
        print(f"No scoreable call for deal {DEAL_ID}"); return 2
    call_id, call_date, text, source = picked

    print("=" * 78)
    print(f"PHASE 2 DETERMINISM — {RUNS}x on one call, temperature 0")
    print(f"deal={DEAL_ID}  call={call_id} ({call_date}, {source}, {len(text)} chars)  "
          f"scorer={cs.SCORER_VERSION}")
    print("=" * 78)

    runs = []       # list of {component: score}
    gates = []      # list of frozenset(advanced)
    for i in range(1, RUNS + 1):
        r = cs.score_call(text, {"company": "Livesport"}, prior_state=None, client=client)
        scores = {k: r["components"][k]["score"] for k in cs.COMPONENT_KEYS}
        runs.append(scores)
        gates.append(tuple(sorted(r["advanced"])))
        shown = " ".join(f"{k[:4]}={scores[k] if scores[k] is not None else '·'}" for k in cs.COMPONENT_KEYS)
        print(f"run {i}: advanced={sorted(r['advanced'])}")
        print(f"       {shown}")

    print("\n" + "-" * 78)
    print(f"{'component':20}{'mode':>6}{'spread':>8}   distribution")
    unstable = []
    for k in cs.COMPONENT_KEYS:
        vals = [r[k] for r in runs]
        dist = Counter("·" if v is None else v for v in vals)
        nums = [v for v in vals if isinstance(v, int)]
        spread = (max(nums) - min(nums)) if nums else 0
        # A component null in some runs and scored in others is also instability.
        mixed_null = ("·" in dist and len(dist) > 1)
        if spread > 0 or mixed_null:
            unstable.append(k)
        mode = dist.most_common(1)[0][0]
        diststr = " ".join(f"{v}x{c}" for v, c in sorted(dist.items(), key=lambda x: str(x[0])))
        flag = "" if (spread == 0 and not mixed_null) else "   <-- moves"
        print(f"{k:20}{str(mode):>6}{spread:>8}   {diststr}{flag}")

    gate_stable = len(set(gates)) == 1
    print("\n" + "-" * 78)
    print(f"gate selection across {RUNS} runs: "
          + ("IDENTICAL " + str(sorted(set(gates[0]))) if gate_stable
             else f"VARIES — {sorted(set(gates))}"))
    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    if not unstable and gate_stable:
        print(f"DETERMINISTIC — identical scores and identical gate selection across {RUNS} runs.")
    else:
        who = ", ".join(unstable) if unstable else "(scores stable)"
        g = "stable" if gate_stable else "VARIES"
        print(f"NONDETERMINISTIC — components moving: {who}; gate {g}.")
        print("Per the spec, a single-call wobble means the prompt is ambiguous — tighten it.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
