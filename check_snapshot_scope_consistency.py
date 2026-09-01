#!/usr/bin/env python3
"""
Check snapshot scope consistency across quarters.

BLAST RADIUS: If renewal stages counted as qualified in Q2/Q3 but not Q1,
every snapshot-based analysis crossing that boundary is affected:
- Waterfall qualified pipeline
- Week-3 conversion rates
- Coverage curves
- Anything using deals_snapshot

This determines which quarters need backfilling.
"""

import os
import sys
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from supabase import create_client
from supabase_client import select_all


def main():
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Get all snapshots
    snapshots = select_all(
        sb, 'deals_snapshot',
        columns='fiscal_quarter,pipeline_id,stage_id'
    )

    # Default pipeline qualified stages (from field_semantics.yaml)
    default_qualified_stages = {
        'appointmentscheduled', 'qualifiedtobuy', 'presentationscheduled',
        'decisionmakerboughtin', 'contractsent', '24682892', '43449439'
    }

    # Renewal pipeline stages
    renewal_stages = {
        '1297321618',  # Upcoming Renewal
        '1297321619',  # Renewal Engaged
        '1297321620',  # Pricing Presented
        '1297321622',  # Contract Sent (Renewal)
    }

    # Group by quarter and pipeline
    stats = defaultdict(lambda: {
        'total': 0,
        'default_qualified': 0,
        'renewal_stages': 0,
        'renewal_pipeline_total': 0
    })

    for snap in snapshots:
        quarter = snap.get('fiscal_quarter', 'UNKNOWN')
        pipeline_id = snap.get('pipeline_id', 'default')
        stage_id = snap.get('stage_id', '')

        key = (quarter, pipeline_id)
        stats[key]['total'] += 1

        if pipeline_id == '866608541':
            stats[key]['renewal_pipeline_total'] += 1

        if stage_id in default_qualified_stages:
            stats[key]['default_qualified'] += 1

        if stage_id in renewal_stages:
            stats[key]['renewal_stages'] += 1

    # Print results
    print("Snapshot Scope Consistency Check")
    print("="*85)
    print()
    print(f"{'Quarter':<15} {'Pipeline':<15} {'Total':>8} {'Default-Qual':>13} {'Renewal-Stgs':>13}")
    print("-"*85)

    for (quarter, pipeline_id), stat in sorted(stats.items()):
        print(f"{quarter:<15} {pipeline_id:<15} "
              f"{stat['total']:>8} "
              f"{stat['default_qualified']:>13} "
              f"{stat['renewal_stages']:>13}")

    print()
    print("="*85)
    print("BLAST RADIUS ANALYSIS")
    print("="*85)
    print()

    # Check for inconsistency
    quarters = sorted(set(q for q, _ in stats.keys()))

    print("Renewal pipeline (866608541) presence by quarter:")
    for quarter in quarters:
        default_key = (quarter, 'default')
        renewal_key = (quarter, '866608541')

        default_total = stats.get(default_key, {}).get('total', 0)
        renewal_total = stats.get(renewal_key, {}).get('total', 0)
        renewal_stages_in_default = stats.get(default_key, {}).get('renewal_stages', 0)

        if renewal_total > 0:
            print(f"  {quarter}: {renewal_total} renewal pipeline rows in snapshot")
        else:
            print(f"  {quarter}: NO renewal pipeline rows")

        if renewal_stages_in_default > 0:
            print(f"            ⚠️  ALSO {renewal_stages_in_default} renewal stages in default pipeline")

    print()
    print("="*85)
    print("FINDING")
    print("="*85)

    # Detect the boundary
    has_renewals = {}
    for quarter in quarters:
        renewal_key = (quarter, '866608541')
        has_renewals[quarter] = stats.get(renewal_key, {}).get('total', 0) > 0

    if all(has_renewals.values()):
        print("✓ All quarters have renewal pipeline in snapshots (consistent)")
    elif not any(has_renewals.values()):
        print("✓ No quarters have renewal pipeline in snapshots (consistent)")
    else:
        # Mixed
        with_renewals = [q for q in quarters if has_renewals[q]]
        without_renewals = [q for q in quarters if not has_renewals[q]]

        print(f"⚠️  SCOPE INCONSISTENCY DETECTED")
        print()
        print(f"Quarters WITH renewal pipeline: {', '.join(with_renewals)}")
        print(f"Quarters WITHOUT renewal pipeline: {', '.join(without_renewals)}")
        print()
        print("BLAST RADIUS:")
        print("  - Week-3 conversion rates (affected)")
        print("  - Waterfall qualified pipeline (affected)")
        print("  - Coverage curves (affected)")
        print("  - Any snapshot-based QoQ comparison (affected)")
        print()
        print("BACKFILL REQUIRED:")
        if without_renewals and with_renewals:
            print(f"  Quarters needing regeneration: {', '.join(with_renewals if len(without_renewals) < len(with_renewals) else without_renewals)}")

    print()
    print("="*85)
    print("DEFINITIONAL CHOICE REQUIRED")
    print("="*85)
    print()
    print("Should renewals be counted as 'qualified' pipeline?")
    print()
    print("OPTION 1: Renewals NEVER qualified")
    print("  Rationale: Qualification is new-business concept. Renewals exist")
    print("             because customer already bought. No qualification gate.")
    print("  Impact: Exclude renewal pipeline from all snapshot analytics")
    print("  Fix: is_deal_in_analytics_scope excludes renewal at snapshot time")
    print()
    print("OPTION 2: Renewals ALWAYS qualified")
    print("  Rationale: Renewal stages (Engaged, Pricing Presented) represent")
    print("             stages of progression similar to new business.")
    print("  Impact: Include renewal pipeline uniformly across all quarters")
    print("  Fix: Backfill Q1 to include renewal pipeline")
    print()
    print("RECOMMENDATION: Option 1 (never qualified)")
    print("  - Aligns with 'renewal waterfall is a design gap' finding")
    print("  - Simpler: renewal and new business are different motions")
    print("  - Current Q1 behavior (no renewals) becomes the standard")


if __name__ == '__main__':
    main()
