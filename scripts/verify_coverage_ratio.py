#!/usr/bin/env python3
"""
Verify coverage ratio calculation before Slack presentation.

18.6x coverage against $1M target is implausible. Check:
1. Is $1M the correct company-wide target?
2. Is target scoped to same metric as pipeline (incremental ARR)?
3. Does it reconcile with known rep targets?
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from time_resolver import current_quarter_label

def verify_coverage():
    sb = get_supabase()
    current_quarter = current_quarter_label()

    print("=" * 80)
    print("COVERAGE RATIO VERIFICATION")
    print("=" * 80)
    print(f"Current quarter: {current_quarter}")
    print()

    # Pull ALL rep_targets for current quarter
    all_targets = sb.table("rep_targets").select(
        "id,period,level,entity_name,entity_email,metric,target_value"
    ).eq("period", current_quarter).execute()

    print(f"Total rows in rep_targets for {current_quarter}: {len(all_targets.data)}")
    print()

    # Group by level and metric
    by_level = {}
    for row in all_targets.data:
        level = row.get("level")
        metric = row.get("metric")
        key = f"{level}_{metric}"

        if key not in by_level:
            by_level[key] = []
        by_level[key].append(row)

    print("TARGETS BY LEVEL AND METRIC:")
    print()
    for key, rows in sorted(by_level.items()):
        print(f"  {key}: {len(rows)} rows")
        total = sum(r.get("target_value") or 0 for r in rows)
        print(f"    Total target: ${total:,.0f}")
        for row in rows[:3]:
            print(f"      - {row.get('entity_name')}: ${row.get('target_value'):,.0f}")
        if len(rows) > 3:
            print(f"      ... and {len(rows) - 3} more")
        print()

    # Check company-level total_arr target
    company_total_arr = [
        r for r in all_targets.data
        if r.get("level") == "company" and r.get("metric") == "total_arr"
    ]

    if company_total_arr:
        print("COMPANY-LEVEL total_arr TARGET:")
        for row in company_total_arr:
            print(f"  entity_name: {row.get('entity_name')}")
            print(f"  target_value: ${row.get('target_value'):,.0f}")
            print(f"  set_at: {row.get('set_at')}")
        print()
    else:
        print("⚠️  No company-level total_arr target found!")
        print()

    # Check rep-level targets and sum
    rep_targets = [
        r for r in all_targets.data
        if r.get("level") == "rep"
    ]

    if rep_targets:
        print("REP-LEVEL TARGETS:")
        print(f"  Total reps with targets: {len(rep_targets)}")
        rep_total = sum(r.get("target_value") or 0 for r in rep_targets)
        print(f"  Sum of rep targets: ${rep_total:,.0f}")
        print()
        print("  Sample rep targets:")
        for row in sorted(rep_targets, key=lambda r: r.get("target_value") or 0, reverse=True)[:5]:
            print(f"    - {row.get('entity_name')}: ${row.get('target_value'):,.0f} ({row.get('metric')})")
        print()

    # Cross-check against q005 verified value
    print("=" * 80)
    print("CROSS-CHECK AGAINST Q005 (Team Attainment)")
    print("=" * 80)
    print()
    print("q005 verified value (from canonical_questions.yaml):")
    print("  won_arr: $197,400")
    print("  target: $1,550,000")
    print("  attainment_pct: 12.7%")
    print()

    # Compare
    if company_total_arr:
        company_target = company_total_arr[0].get("target_value")
        print(f"Company-level target from rep_targets: ${company_target:,.0f}")
        print(f"Team target from q005: $1,550,000")
        print()

        if company_target != 1550000:
            print("⚠️  DISCREPANCY: Company target doesn't match q005 team target!")
            print(f"  Difference: ${abs(company_target - 1550000):,.0f}")
            print()

    # Calculate correct coverage ratio
    pipeline_value = 18565953

    print("=" * 80)
    print("COVERAGE RATIO CALCULATION")
    print("=" * 80)
    print()
    print(f"Pipeline (incremental ARR): ${pipeline_value:,.0f}")
    print()

    if company_total_arr:
        company_target = company_total_arr[0].get("target_value")
        coverage = pipeline_value / company_target
        print(f"Company target (rep_targets): ${company_target:,.0f}")
        print(f"Coverage ratio: {coverage:.1f}x")
        print()

        if coverage > 10:
            print("⚠️  IMPLAUSIBLE: Coverage ratio > 10x is unusually high!")
            print("    Typical healthy pipeline coverage: 3-5x")
            print()

    # Use q005 target as comparison
    q005_target = 1550000
    coverage_q005 = pipeline_value / q005_target
    print(f"Team target (q005): ${q005_target:,.0f}")
    print(f"Coverage ratio: {coverage_q005:.1f}x")
    print()

    if coverage_q005 > 10:
        print("⚠️  IMPLAUSIBLE: Coverage ratio > 10x is unusually high!")
        print("    Typical healthy pipeline coverage: 3-5x")
        print()

    # Check if target is for incremental ARR or total bookings
    print("=" * 80)
    print("METRIC SCOPING CHECK")
    print("=" * 80)
    print()
    print("Pipeline metric: incremental ARR (expansion_arr + new_arr)")
    print(f"Target metric: {company_total_arr[0].get('metric') if company_total_arr else 'unknown'}")
    print()

    if company_total_arr and company_total_arr[0].get('metric') == 'total_arr':
        print("⚠️  POTENTIAL MISMATCH:")
        print("    Pipeline = incremental ARR (expansion + new business)")
        print("    Target = total_arr (may include renewals)")
        print()
        print("    If target includes renewal base, coverage calculation is wrong.")
        print("    Need to clarify: does 'total_arr' target mean incremental only or all bookings?")
        print()

if __name__ == "__main__":
    verify_coverage()
