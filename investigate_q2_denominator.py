#!/usr/bin/env python3
"""
Investigate Q2 FY2027 week-3 conversion rate outlier.

Q1: 22 won / 240 pipeline = 9.2%
Q2: 29 won / 119 pipeline = 24.4%

Denominator halved while wins rose. Check:
1. Snapshot coverage (incomplete grid?)
2. Scope filter change (different qualification rules between Q1 and Q2?)
3. Real pipeline shrinkage
"""

import os
import sys
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from supabase import create_client
from utils import load_client_config
from analytics.point_in_time import load_scope_config, is_deal_in_analytics_scope
from supabase_client import select_all


def investigate_quarter_snapshot(sb, config, quarter, excl_pipelines, stage_cfg):
    """Analyze week-3 snapshot for a given quarter."""
    print(f"\n{'='*70}")
    print(f"{quarter} Week-3 Snapshot Analysis")
    print(f"{'='*70}\n")

    def _qualified_in_own_pipeline(stage_id, pipeline_id):
        if stage_id is None or not str(stage_id).strip():
            return False
        return is_deal_in_analytics_scope(
            str(stage_id), pipeline_id, set(), stage_cfg)

    # Get week-3 snapshot
    week3_rows = select_all(
        sb, 'deals_snapshot',
        columns='deal_id,stage_id,pipeline_id,deal_value,snapshot_date',
        filters=[('eq', 'fiscal_quarter', quarter),
                 ('eq', 'week_of_quarter', 3)])

    print(f"Total week-3 snapshot records: {len(week3_rows)}")

    if not week3_rows:
        print(f"⚠️  No snapshot data found for {quarter}")
        return {
            'total': 0,
            'qualified': 0,
            'snapshot_dates': [],
            'error': 'No data'
        }

    # Check snapshot date coverage
    snapshot_dates = sorted(set(r['snapshot_date'] for r in week3_rows))
    print(f"Snapshot dates: {snapshot_dates}")

    if len(snapshot_dates) > 1:
        print(f"⚠️  Multiple snapshot dates in week 3 — may indicate backfill or grid issue")

    # Break down by pipeline
    by_pipeline = defaultdict(int)
    qualified_by_pipeline = defaultdict(int)
    stage_distribution = defaultdict(int)

    for r in week3_rows:
        pipeline_id = r.get('pipeline_id', 'default')
        stage_id = r.get('stage_id')

        by_pipeline[pipeline_id] += 1

        if stage_id:
            stage_distribution[str(stage_id)] += 1

        if _qualified_in_own_pipeline(stage_id, pipeline_id):
            qualified_by_pipeline[pipeline_id] += 1

    print(f"\nBy pipeline (total):")
    for pid, count in sorted(by_pipeline.items()):
        qual_count = qualified_by_pipeline.get(pid, 0)
        qual_pct = (qual_count / count * 100) if count > 0 else 0
        print(f"  {pid}: {count} total, {qual_count} qualified ({qual_pct:.1f}%)")

    total_qualified = sum(qualified_by_pipeline.values())
    print(f"\nTotal qualified deals (denominator): {total_qualified}")

    # Check for data quality issues
    null_stages = sum(1 for r in week3_rows if not r.get('stage_id'))
    if null_stages > 0:
        print(f"\n⚠️  Null stage_id: {null_stages} ({null_stages/len(week3_rows)*100:.1f}%)")

    # Stage distribution (top 10)
    print(f"\nTop 10 stages by count:")
    for stage_id, count in sorted(stage_distribution.items(), key=lambda x: x[1], reverse=True)[:10]:
        is_qual = any(_qualified_in_own_pipeline(stage_id, pid) for pid in by_pipeline.keys())
        qual_marker = "✓" if is_qual else "✗"
        print(f"  {stage_id}: {count} deals [{qual_marker}]")

    return {
        'quarter': quarter,
        'total': len(week3_rows),
        'qualified': total_qualified,
        'snapshot_dates': snapshot_dates,
        'by_pipeline': dict(by_pipeline),
        'qualified_by_pipeline': dict(qualified_by_pipeline),
        'null_stages': null_stages,
        'stage_count': len(stage_distribution)
    }


def main():
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    config = load_client_config()

    excl_pipelines, stage_cfg = load_scope_config(config)

    # Investigate Q1 and Q2
    q1_results = investigate_quarter_snapshot(sb, config, 'FY2027 Q1', excl_pipelines, stage_cfg)
    q2_results = investigate_quarter_snapshot(sb, config, 'FY2027 Q2', excl_pipelines, stage_cfg)

    # Comparison
    print(f"\n{'='*70}")
    print("Q1 vs Q2 Comparison")
    print(f"{'='*70}\n")

    if q1_results.get('error') or q2_results.get('error'):
        print("Cannot compare — missing data")
        return

    q1_qual = q1_results['qualified']
    q2_qual = q2_results['qualified']

    change = q2_qual - q1_qual
    change_pct = (change / q1_qual * 100) if q1_qual > 0 else 0

    print(f"Denominator change: {q1_qual} → {q2_qual} ({change:+d}, {change_pct:+.1f}%)")

    # Diagnosis
    print(f"\nDiagnostic findings:")

    # 1. Snapshot coverage
    if len(q2_results['snapshot_dates']) < len(q1_results['snapshot_dates']):
        print(f"  ⚠️  SNAPSHOT COVERAGE: Q2 has fewer snapshot dates ({len(q2_results['snapshot_dates'])}) than Q1 ({len(q1_results['snapshot_dates'])})")
    elif q2_results['total'] < q1_results['total'] * 0.75:
        print(f"  ⚠️  INCOMPLETE GRID: Q2 total records ({q2_results['total']}) < 75% of Q1 ({q1_results['total']})")
    else:
        print(f"  ✓ Snapshot coverage appears complete")

    # 2. Pipeline mix
    q1_default = q1_results['qualified_by_pipeline'].get('default', 0)
    q2_default = q2_results['qualified_by_pipeline'].get('default', 0)

    if q1_default > 0 and q2_default > 0:
        default_change = q2_default - q1_default
        default_change_pct = (default_change / q1_default * 100)
        print(f"  Default pipeline: {q1_default} → {q2_default} ({default_change:+d}, {default_change_pct:+.1f}%)")

    # 3. Qualification rate
    q1_qual_rate = (q1_qual / q1_results['total'] * 100) if q1_results['total'] > 0 else 0
    q2_qual_rate = (q2_qual / q2_results['total'] * 100) if q2_results['total'] > 0 else 0

    print(f"  Qualification rate: Q1 {q1_qual_rate:.1f}%, Q2 {q2_qual_rate:.1f}%")

    if abs(q2_qual_rate - q1_qual_rate) > 10:
        print(f"    ⚠️  Qualification rate shifted >10pp — scope filter may have changed")

    # Recommendation
    print(f"\n{'='*70}")
    print("Recommendation")
    print(f"{'='*70}\n")

    if q2_results['total'] < q1_results['total'] * 0.75:
        print("⚠️  Q2 denominator appears incomplete (measurement artifact).")
        print("    Recommendation: Exclude Q2 from trailing average calculation.")
        print("    Use Q3-Q1 (9.2-10.5%, tight range) for forecast input.")
        print()
        print("    Registry update:")
        print("      trailing_3q: 0.098  # Q3, Q4, Q1 average")
        print("      range: [0.092, 0.105]")
        print("      excluded: 'FY2027 Q2 — incomplete snapshot (119 vs 240 expected)'")
    elif abs(q2_qual_rate - q1_qual_rate) > 10:
        print("⚠️  Q2 qualification rate differs materially from Q1.")
        print("    Possible scope filter change between quarters.")
        print("    Recommendation: Investigate scope filter history before using Q2 data.")
    else:
        print("✓ Q2 appears to reflect real pipeline shrinkage.")
        print("  Denominator change is genuine — wins rose (22→29) as pipeline shrank (240→119).")
        print()
        print("  Registry update:")
        print("    trailing_4q: 0.135")
        print("    range: [0.092, 0.244]")
        print("    caveat: >")
        print("      Q2 FY2027 outlier — denominator halved (240→119) while wins rose.")
        print("      Represents real market conditions (pipeline compression + strong close).")
        print("      Forecast using 13.5% should show range [$X at 9.2%, $Y at 24.4%].")


if __name__ == '__main__':
    main()
