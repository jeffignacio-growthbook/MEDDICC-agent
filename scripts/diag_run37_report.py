#!/usr/bin/env python3
"""
Read-only report for run #37 (the first clean nightly after the crash fix):

  ITEM 1 — exact evaluator pass count from analyses.passed across the deals
           scored today, plus the iterations histogram (the real numbers the
           broken "0/39" summary counter obscured).
  ITEM 2 helper — coverage reconciliation: one honest number for active-deal
           coverage (active / with-calls / analysed-today / passed-today),
           so 96/166 and the older 357/422 stop being two competing figures.

Never writes. Needs SUPABASE_URL + SUPABASE_SERVICE_KEY.
`TODAY` overridable via RUN_DATE (YYYY-MM-DD) for reuse on a later run.
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

TODAY = os.getenv("RUN_DATE", "2026-08-23")


def _active_deals():
    idx = json.load(open(REPO / "memory" / "deals" / "index.json"))
    deals = idx.get("deals") if isinstance(idx.get("deals"), dict) else idx
    return {k: v for k, v in deals.items() if isinstance(v, dict) and v.get("deal_id")}


def main():
    from supabase_client import SupabaseWriter, select_all
    sb = SupabaseWriter().client

    # ── ITEM 1: pass count + iterations from today's analyses ────────────────
    rows = select_all(sb, "analyses",
                      columns="deal_id,company_name,passed,iterations,overall_score,"
                              "champion_score,analyzed_at",
                      filters=[("gte", "analyzed_at", TODAY)])
    # One run today (#37); if a deal somehow has >1 row, keep the latest.
    latest = {}
    for r in rows:
        did = str(r.get("deal_id"))
        if did not in latest or str(r.get("analyzed_at") or "") > str(latest[did].get("analyzed_at") or ""):
            latest[did] = r
    rows = list(latest.values())

    passed = [r for r in rows if r.get("passed")]
    failed = [r for r in rows if not r.get("passed")]
    iters = Counter(int(r.get("iterations") or 0) for r in rows)

    print("=" * 76)
    print(f"ITEM 1 — EVALUATOR PASS COUNT (analyses since {TODAY})")
    print("=" * 76)
    print(f"deals scored today: {len(rows)}")
    n = max(1, len(rows))
    print(f"  PASSED evaluator: {len(passed)}  ({100*len(passed)//n}%)")
    print(f"  FAILED evaluator: {len(failed)}  ({100*len(failed)//n}%)")
    print("\niterations to finish (all deals, pass or fail):")
    for k in sorted(iters):
        print(f"  {k} iteration(s): {iters[k]}")
    # Pass rate by iteration count — shows whether passes are iteration-1 (the
    # single-pass regime the determinism harness measured) or later.
    p_by_iter = Counter(int(r.get("iterations") or 0) for r in passed)
    print("\nPASSED deals by iteration reached:")
    for k in sorted(p_by_iter):
        print(f"  passed at/by iteration {k}: {p_by_iter[k]}")
    print("\nsample of FAILED deals (deal_id | overall/70 | champion | iters):")
    for r in sorted(failed, key=lambda x: (x.get("overall_score") or 0))[:12]:
        print(f"  {str(r.get('deal_id')):14} {str(r.get('overall_score'))+'/70':8} "
              f"champ={r.get('champion_score')} iters={r.get('iterations')} "
              f"{str(r.get('company_name'))[:26]}")

    # ── ITEM 2 helper: coverage reconciliation ───────────────────────────────
    active = _active_deals()
    call_rows = select_all(sb, "calls", columns="deal_id")
    call_ids = {str(c.get("deal_id")) for c in call_rows
                if c.get("deal_id") not in (None, "", "None")}
    active_with_calls = [d for d in active if d in call_ids]
    scored_today_ids = set(latest.keys())
    active_scored_today = [d for d in active if d in scored_today_ids]
    active_passed_today = [d for d in active
                           if d in {str(r["deal_id"]) for r in passed}]

    print("\n" + "=" * 76)
    print("ITEM 2 (coverage reconciliation) — ONE honest active-coverage number")
    print("=" * 76)
    print(f"  active deals (current index):        {len(active)}")
    print(f"  …with >=1 call in Supabase:          {len(active_with_calls)} "
          f"({100*len(active_with_calls)//max(1,len(active))}% of active)")
    print(f"  …scored in run #37 (analysis today): {len(active_scored_today)}")
    print(f"  …passed the evaluator today:         {len(active_passed_today)}")
    print()
    print("  Reconciliation vs the older 357-unscored / 422 figure:")
    print("  - 422 was a PRIOR deal universe (pre-ETL-refresh snapshot); the")
    print("    active set is now {} deals, a different denominator.".format(len(active)))
    print("  - '85% unscored of 422' and 'coverage of 166 active' are not the")
    print("    same population. The honest current number is active-deal")
    print("    coverage: {}/{} active deals are scoreable (have calls)."
          .format(len(active_with_calls), len(active)))
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
