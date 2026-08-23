#!/usr/bin/env python3
"""
Diagnostic (FIX_MEDDICC_SCORE_PRESENTATION, PART 4): read LiveSport's stored
MEDDICC row and show the corrected synthesis.

Needs Supabase (all stages) + ANTHROPIC_API_KEY (final synthesis stage only).
Runs in CI, not the dev container. Read-only — writes nothing.

Prints:
  1. every analyses row for the LiveSport deal (7 components, overall, analyzed_at)
     + the count, so we can tell whether the Slack answer used the latest row.
  2. what query_rubric_scores_bulk now returns (labelled overall).
  3. the re-synthesised answer with the corrected prompt — expect 7 components,
     no Paper Process, overall as X/70.
"""
import os
import sys
import json
import asyncio
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

COMPANY = os.getenv("DIAGNOSE_COMPANY", "LiveSport")
_COMPONENTS = ["metrics_score", "economic_buyer_score", "decision_criteria_score",
               "decision_process_score", "pain_score", "champion_score",
               "competition_score"]


def main():
    from api.db import get_supabase
    from supabase_client import select_all
    sb = get_supabase()

    print("=" * 72)
    print(f"LIVESPORT STORED ROW — company match '{COMPANY}'")
    print("=" * 72)

    deals = select_all(sb, "deals", columns="deal_id,company_name",
                       filters=[("ilike", "company_name", f"%{COMPANY}%")])
    print(f"\nmatched deals: {[(d['deal_id'], d['company_name']) for d in deals]}")
    deal_ids = [d["deal_id"] for d in deals]
    if not deal_ids:
        print("no matching deal — cannot continue")
        return

    cols = "deal_id,company_name,overall_score," + ",".join(_COMPONENTS) + ",analyzed_at,passed"
    rows = select_all(sb, "analyses", columns=cols,
                      filters=[("in_", "deal_id", deal_ids)])
    rows.sort(key=lambda r: str(r.get("analyzed_at") or ""), reverse=True)
    print(f"\n{len(rows)} analysis row(s) for this deal (newest first):")
    for i, r in enumerate(rows):
        comp = {c.replace("_score", ""): r.get(c) for c in _COMPONENTS}
        comp_sum = sum(v for v in comp.values() if isinstance(v, (int, float)))
        tag = "  <-- LATEST" if i == 0 else ""
        print(f"  [{r.get('analyzed_at')}] overall_score={r.get('overall_score')} "
              f"(components sum={comp_sum}) passed={r.get('passed')}{tag}")
        print(f"      {comp}")

    print("\n" + "=" * 72)
    print("HANDLER OUTPUT — query_rubric_scores_bulk (labelled overall)")
    print("=" * 72)
    from api import handlers
    result = asyncio.run(handlers.query_rubric_scores_bulk(
        {"company": COMPANY}, sb))
    print(json.dumps(result, indent=2, default=str)[:2500])

    print("\n" + "=" * 72)
    print("CORRECTED SYNTHESIS — 'score the LiveSport deal on MEDDICC'")
    print("=" * 72)
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — skipping synthesis stage")
        return
    try:
        from llm_client import LLMClient
        from api.router import build_synthesis_prompt
        gen = LLMClient.from_config(role="generator")
        resp = gen.complete(
            messages=[{"role": "user",
                       "content": "Question: score the LiveSport deal on MEDDICC\n\n"
                                  f"Data:\n{json.dumps(result, default=str)[:3000]}"}],
            system=build_synthesis_prompt(None),
            max_tokens=600)
        print("\n" + resp.text.strip())
    except Exception as e:
        import traceback
        print(f"synthesis stage failed: {e}")
        print(traceback.format_exc())


if __name__ == "__main__":
    main()
