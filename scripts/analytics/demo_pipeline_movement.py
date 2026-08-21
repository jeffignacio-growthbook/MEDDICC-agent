#!/usr/bin/env python3
"""
Live demonstration of query_pipeline_movement against the real deals_snapshot.

Runs in GitHub Actions (the dev container cannot reach Supabase). Prints the
actual numbers for each of the four views, plus a routing check that confirms
the intent classifier selects query_pipeline_movement for the four example
questions.

Usage (in CI, with SUPABASE_URL / SUPABASE_SERVICE_KEY [+ ANTHROPIC_API_KEY]):
    PYTHONPATH=scripts:api:scripts/analytics:. \
        python3 scripts/analytics/demo_pipeline_movement.py
"""

import os
import sys
import json
import asyncio
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
for p in ("scripts", "api", "scripts/analytics", "."):
    sys.path.insert(0, str(REPO / p))


def _sb():
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


def _show(title, result, *, keys):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)
    for k in keys:
        if k in result:
            print(f"{k}: {json.dumps(result[k], default=str)}")


def run_views(sb):
    from handlers import query_pipeline_movement

    # A quarter that is fully backfilled on the clean Monday grid.
    Q = "FY2027 Q2"

    mv = asyncio.run(query_pipeline_movement(
        {"view": "movement", "fiscal_quarter": Q}, sb))
    _show(f"VIEW 1 — movement ({Q}, last two snapshots)", mv,
          keys=["snapshot_source", "snapshot_dates", "totals", "summary",
                "confidence", "by_stage", "scope_statement", "data_gaps"])
    # Drill-down fix: movement now carries entity-bearing rows + per-stage ids
    print(f"entity rows for thread context: {len(mv.get('rows', []))} "
          f"(each carries deal_id) — was 0 before the fix")
    disc = next((s for s in mv.get("by_stage", []) if s["stage"] == "Discovery"), None)
    if disc:
        print(f"by_stage['Discovery'].deal_ids: {len(disc.get('deal_ids', []))} ids "
              f"(count={disc['current']})")

    # Direct drill-down: "which deals are in Discovery?"
    sd = asyncio.run(query_pipeline_movement(
        {"view": "stage_deals", "fiscal_quarter": Q, "stage": "Discovery"}, sb))
    _show(f"VIEW 1b — stage_deals ({Q}, stage=Discovery)", sd,
          keys=["snapshot_source", "snapshot_dates", "stage", "count", "data_gaps"])
    print(f"sample rows: {json.dumps(sd.get('rows', [])[:3], default=str)}")

    comp = asyncio.run(query_pipeline_movement(
        {"view": "composition", "fiscal_quarter": Q, "weeks": 4}, sb))
    _show(f"VIEW 2 — composition ({Q}, last 4 weeks)", comp,
          keys=["snapshot_source", "snapshot_dates", "weeks", "data_gaps"])

    dc = asyncio.run(query_pipeline_movement(
        {"view": "deal_changes", "fiscal_quarter": Q}, sb))
    # changes can be long; print the summary and a sample
    dc_sample = {**dc, "changes": dc.get("changes", [])[:10]}
    _show(f"VIEW 3 — deal_changes ({Q}, last two snapshots)", dc_sample,
          keys=["snapshot_source", "snapshot_dates", "summary",
                "changes", "data_gaps"])
    print(f"(total changes: {len(dc.get('changes', []))})")

    cv = asyncio.run(query_pipeline_movement(
        {"view": "curve", "fiscal_quarter": Q}, sb))
    _show(f"VIEW 4 — curve ({Q}, count by week-of-quarter)", cv,
          keys=["snapshot_source", "curve", "query_stats", "data_gaps"])

    # Issue 5 — curve efficiency: before/after rows+pages actually scanned.
    from supabase_client import select_all
    old_cols = ("deal_id,snapshot_date,pipeline_id,stage_id,stage_order,"
                "close_date,owner_email,deal_status,snapshot_source,"
                "backfill_confidence,fiscal_quarter,week_of_quarter")
    before = select_all(sb, "deals_snapshot", columns=old_cols,
                        filters=[("eq", "fiscal_quarter", Q)])
    print("\n" + "=" * 72)
    print(f"CURVE EFFICIENCY ({Q})")
    print("=" * 72)
    print(f"  BEFORE: full 12 cols, all pipelines — rows={len(before)}, "
          f"pages={(len(before)//1000)+1}")
    print(f"  AFTER : slim 10 cols, renewal excluded server-side — "
          f"rows={cv['query_stats']['rows_loaded']}, "
          f"pages={cv['query_stats']['pages_loaded']}")

    # Issue 2/3 — deal_changes on FY2027 Q3: new deals must show as
    # new_to_pipeline WITH company names, not as stage entries.
    dcq3 = asyncio.run(query_pipeline_movement(
        {"view": "deal_changes", "fiscal_quarter": "FY2027 Q3"}, sb))
    _show("VIEW 3b — deal_changes (FY2027 Q3, Aug 10 → Aug 17)", dcq3,
          keys=["snapshot_source", "snapshot_dates", "summary", "data_gaps"])
    newbies = [c for c in dcq3.get("changes", [])
               if c["direction"] == "new_to_pipeline"]
    print(f"  new_to_pipeline deals ({len(newbies)}) — named, not stage entries:")
    for c in newbies[:8]:
        print(f"    {c['deal_id']}  {c.get('company_name')!r}  "
              f"owner={c['owner_email']}  prior_stage={c['prior_stage']} "
              f"current_stage={c['current_stage']}")
    left = [c for c in dcq3.get("changes", []) if c["direction"] == "left_pipeline"]
    if left:
        print(f"  left_pipeline sample (with reason): "
              f"{json.dumps(left[:3], default=str)}")

    # Bonus: the current quarter has TWO grids — show the grid guard firing.
    cur = asyncio.run(query_pipeline_movement(
        {"view": "movement", "fiscal_quarter": "FY2027 Q3"}, sb))
    _show("GRID GUARD — current quarter (FY2027 Q3, two point-in-time grids)", cur,
          keys=["snapshot_source", "snapshot_dates", "totals", "summary", "data_gaps"])


def run_routing():
    """Confirm the classifier routes the four example questions to the handler."""
    print("\n" + "=" * 72)
    print("ROUTING — does the classifier select query_pipeline_movement?")
    print("=" * 72)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — skipping live routing check.")
        return
    from llm_client import LLMClient
    from router import build_intent_prompt, _extract_json
    from time_resolver import current_quarter_label

    client = LLMClient.from_config(role="classifier")
    today = "2026-08-20"
    cq = current_quarter_label()

    questions = [
        "How has pipeline moved over the last four weeks?",
        "What's the stage breakdown this quarter versus last?",
        "Which deals moved stage since last week?",
        "Show me the coverage curve for FY2027 Q2",
    ]
    passed = 0
    for q in questions:
        prompt = build_intent_prompt(today=today, current_quarter=cq,
                                     history="[]", question=q)
        resp = client.complete(
            messages=[{"role": "user", "content": prompt}],
            system="Respond with valid JSON only.",
            max_tokens=300,
        )
        parsed = _extract_json(resp.text) or {}
        handler = parsed.get("handler")
        view = (parsed.get("params") or {}).get("view")
        ok = handler == "query_pipeline_movement"
        passed += ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {q!r} -> handler={handler} view={view}")
    print(f"routing: {passed}/{len(questions)} routed to query_pipeline_movement")


def main():
    sb = _sb()
    run_views(sb)
    try:
        run_routing()
    except Exception as e:
        print(f"\n[routing check errored: {e}]")
    print("\nDONE.")


if __name__ == "__main__":
    main()
