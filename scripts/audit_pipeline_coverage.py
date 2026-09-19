#!/usr/bin/env python3
"""
Audit-only script for the "pipeline health/coverage" primitive scoping
question (NORTH_STAR.md CRO Priority #2). Report only — no primitive
built, no writes.

Static code reading already established (see chat) that the premise
"no handler computes pipeline$/quota$ coverage" is FALSE:
  - query_pipeline() (api/handlers.py) computes and returns
    coverage_ratio/quarterly_target itself, Q3-scoped.
  - query_coverage() (api/handlers.py) is a SEPARATE, dedicated handler
    for the same concept across company/team/rep levels, already
    registered in api/router.py's intent map.
  - query_rep_attainment() computes a DIFFERENT ratio (attainment =
    won/quota), not coverage.
  - rep_targets table (migration 019) is real schema with a write path
    (scripts/seed_targets.py, config/targets.yaml) and has been
    live-verified before (canonical_questions.yaml q005, "Verified
    Sep 3": target=$1,550,000, won_arr=$197,400).
  - scripts/verify_coverage_ratio.py (pre-existing, not written this
    audit) already documents a live-observed anomaly: an 18.6x
    coverage ratio against a $1M target flagged as implausible,
    with an unresolved metric-scoping question (does the company-level
    target's 'total_arr' metric include renewals, while pipeline is
    incremental-ARR-only?).

This script runs three things live to close the remaining unknowns:
1. EXACTLY what scripts/verify_coverage_ratio.py already checks, to
   confirm (or update) the current state of that flagged discrepancy.
2. Live calls to query_pipeline() and query_coverage() for real example
   output (audit task 1).
3. A raw rep_targets population count/dump for the current quarter
   (audit task 3), independent of what the two handlers choose to
   surface.

READ-ONLY throughout. No writes.
"""
import sys
import json
import asyncio
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "api"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def part1_rep_targets_raw(sb, current_quarter):
    print("=" * 80)
    print(f"PART 1: rep_targets raw population check for {current_quarter}")
    print("=" * 80)

    rows = sb.table("rep_targets").select(
        "id,period,level,entity_name,entity_email,role,metric,target_value,set_at"
    ).eq("period", current_quarter).execute().data

    print(f"Total rows for {current_quarter}: {len(rows)}")
    if not rows:
        print(">>> ZERO rows for the current quarter. Whatever query_pipeline/"
              "query_coverage/query_rep_attainment return for THIS quarter will "
              "be a data_gap, regardless of code correctness.")
        # Check other periods to see if the table has ANY data at all
        any_rows = sb.table("rep_targets").select("period").limit(2000).execute().data
        periods = sorted({r["period"] for r in any_rows})
        print(f"Periods with ANY rep_targets data (any quarter): {periods}")
        return rows

    by_level_metric = {}
    for r in rows:
        key = f"{r.get('level')}/{r.get('metric')}"
        by_level_metric.setdefault(key, []).append(r)

    for key, group in sorted(by_level_metric.items()):
        total = sum(g.get("target_value") or 0 for g in group)
        print(f"  {key}: {len(group)} rows, sum=${total:,.0f}")
        for g in group[:3]:
            print(f"    - {g.get('entity_name')}: ${g.get('target_value'):,.0f} "
                  f"(role={g.get('role')}, set_at={g.get('set_at')})")

    return rows


def part2_verify_coverage_ratio_live(sb, current_quarter):
    print("\n" + "=" * 80)
    print("PART 2: verify_coverage_ratio.py's own checks, run live, current data")
    print("=" * 80)

    all_targets = sb.table("rep_targets").select(
        "id,period,level,entity_name,entity_email,metric,target_value"
    ).eq("period", current_quarter).execute().data

    company_total_arr = [r for r in all_targets
                          if r.get("level") == "company" and r.get("metric") == "total_arr"]
    company_incremental = [r for r in all_targets
                            if r.get("level") == "company" and r.get("metric") == "incremental_arr"]
    team_incremental = [r for r in all_targets
                        if r.get("level") == "team" and r.get("metric") == "incremental_arr"]

    print(f"company/total_arr targets: {len(company_total_arr)} "
          f"{[t.get('target_value') for t in company_total_arr]}")
    print(f"company/incremental_arr targets: {len(company_incremental)} "
          f"{[t.get('target_value') for t in company_incremental]}")
    print(f"team/incremental_arr targets: {len(team_incremental)} "
          f"{[t.get('target_value') for t in team_incremental]}")

    if company_total_arr and team_incremental:
        ct = company_total_arr[0].get("target_value")
        tt = team_incremental[0].get("target_value")
        print(f"\nCompany total_arr target: ${ct:,.0f}")
        print(f"Team incremental_arr target: ${tt:,.0f}")
        if ct != tt:
            print(f">>> STILL A DISCREPANCY between company/total_arr and "
                  f"team/incremental_arr targets: ${abs(ct-tt):,.0f} difference. "
                  f"This is the metric-scoping question verify_coverage_ratio.py "
                  f"originally flagged — confirming whether it's resolved or still live.")
        else:
            print(">>> Company total_arr and team incremental_arr targets now MATCH — "
                  "the originally-flagged discrepancy appears resolved.")
    elif not company_total_arr:
        print("\n>>> No company/total_arr target row exists this quarter at all "
              "(the exact row verify_coverage_ratio.py's original check depended on).")


def part3_live_handler_calls():
    print("\n" + "=" * 80)
    print("PART 3: live query_pipeline() and query_coverage() output")
    print("=" * 80)

    from db import get_supabase
    import handlers

    sb = get_supabase()

    async def run():
        print("\n--- query_pipeline(params={}, sb) ---")
        try:
            result = await handlers.query_pipeline({}, sb)
            printable = {k: v for k, v in result.items() if k not in ("deals",)}
            print(json.dumps(printable, indent=2, default=str)[:4000])
        except Exception as e:
            print(f"ERROR calling query_pipeline: {e}")

        print("\n--- query_coverage(params={}, sb) ---")
        try:
            result = await handlers.query_coverage({}, sb)
            print(json.dumps(result, indent=2, default=str)[:4000])
        except Exception as e:
            print(f"ERROR calling query_coverage: {e}")

        print("\n--- query_rep_attainment(params={}, sb) (for contrast: attainment != coverage) ---")
        try:
            result = await handlers.query_rep_attainment({}, sb)
            printable = {k: v for k, v in result.items() if k != "reps"}
            print(json.dumps(printable, indent=2, default=str)[:3000])
        except Exception as e:
            print(f"ERROR calling query_rep_attainment: {e}")

    asyncio.run(run())


def main():
    from db import get_supabase
    from time_resolver import current_quarter_label

    sb = get_supabase()
    current_quarter = current_quarter_label()
    print(f"Current quarter label: {current_quarter}\n")

    part1_rep_targets_raw(sb, current_quarter)
    part2_verify_coverage_ratio_live(sb, current_quarter)
    part3_live_handler_calls()

    print("\n" + "=" * 80)
    print("DONE")
    print("=" * 80)


if __name__ == "__main__":
    main()
