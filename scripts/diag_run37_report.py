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
    # Two "active" universes exist and must be reconciled honestly:
    #   • deals table, deal_status='active'  → the raw active count (this is the
    #     ~422 figure; it INCLUDES off-ladder stages: Meeting Set / renewal /
    #     terminal, which are not analyzable opportunities).
    #   • nightly index.json                 → the deals the nightly actually
    #     iterates (~166); ≈ the analyzable pipeline.
    index = _active_deals()
    deals_active = select_all(sb, "deals", columns="deal_id,stage,deal_status",
                              filters=[("eq", "deal_status", "active")])
    call_rows = select_all(sb, "calls", columns="deal_id")
    call_ids = {str(c.get("deal_id")) for c in call_rows
                if c.get("deal_id") not in (None, "", "None")}
    idx_with_calls = [d for d in index if d in call_ids]
    scored_today_ids = set(latest.keys())
    idx_scored_today = [d for d in index if d in scored_today_ids]
    idx_passed_today = [d for d in index if d in {str(r["deal_id"]) for r in passed}]

    print("\n" + "=" * 76)
    print("ITEM 2 (coverage reconciliation) — reconciling 96/166 with the 422 figure")
    print("=" * 76)
    print(f"  deals table, deal_status='active':   {len(deals_active)}  "
          f"(RAW active — includes off-ladder: Meeting Set / renewal / terminal)")
    print(f"  nightly index (what the nightly runs): {len(index)}  "
          f"(≈ the analyzable pipeline)")
    print(f"    …of the index, with >=1 call:        {len(idx_with_calls)} "
          f"({100*len(idx_with_calls)//max(1,len(index))}%)")
    print(f"    …scored in run #37:                  {len(idx_scored_today)}")
    print(f"    …passed the evaluator today:         {len(idx_passed_today)}")
    print()
    print("  The 357-unscored/422 figure counted the RAW active set (422),")
    print("  most of which is off-ladder (renewals/terminal/meeting-set) and was")
    print("  never an analyzable opportunity. The honest coverage number is over")
    print("  the analyzable pipeline the nightly targets: {}/{} have calls, {} were"
          .format(len(idx_with_calls), len(index), len(idx_scored_today)))
    print("  scored in run #37, {} passed the evaluator.".format(len(idx_passed_today)))
    print("  (Gap to watch: index {} vs raw-active {} — confirm the index isn't"
          .format(len(index), len(deals_active)))
    print("   silently dropping analyzable opportunities.)")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
