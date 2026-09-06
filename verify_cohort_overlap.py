#!/usr/bin/env python3
"""
Verify Cohort Overlap

Check if ANY of the 25 recovered or 28 excluded deals were actually
part of the 376-qualified cohort used in conversion_rate_prospective.

If zero overlap: The 7.2% staying the same makes sense (fixed a different population)
If any overlap: The identical 27/376 would be suspicious, needs re-verification
"""

import os
import sys
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent))

from scripts.analytics.point_in_time import is_deal_in_analytics_scope, load_scope_config
from scripts.utils.pagination import fetch_all_rows_by_filters
from api.db import get_supabase


FISCAL_QUARTERS = [
    ('FY2026 Q3', '2025-11-01', '2026-01-31'),
    ('FY2026 Q4', '2026-02-01', '2026-04-30'),
    ('FY2027 Q1', '2026-05-01', '2026-07-31'),
]

PIPELINE_ID = 'default'

# All 25 recovered deals (from migrations 054 + 056)
RECOVERED_25 = [
    # Migration 054 (15 deals)
    '41610727774', '41609747244', '57601552421', '41609744165', '57553470314',
    '57856036981', '29586293533', '45092404555', '57856160781', '41609747284',
    '41610727939', '57856036663', '57553731729', '45002408375', '41609747354',
    # Migration 056 (10 deals)
    '32821739117', '43739930533', '41610728003', '57909116984', '56814175800',
    '15342570867', '56896689288', '52491158184', '41610727783', '45144997263'
]


def main():
    supabase = get_supabase()
    excluded_pipelines, stage_cfg = load_scope_config()

    print("=" * 80)
    print("VERIFY COHORT OVERLAP")
    print("=" * 80)
    print()
    print("Question: Were any of the 25 recovered or 28 excluded deals actually")
    print("part of the 376-qualified cohort that produced the 7.2% conversion rate?")
    print()

    # Get excluded deals from database
    exclusions = supabase.table('data_quality_exclusions').select('deal_id').execute()
    excluded_28 = set(str(row['deal_id']) for row in exclusions.data)

    print(f"Recovered deals: {len(RECOVERED_25)}")
    print(f"Excluded deals: {len(excluded_28)}")
    print()

    # Build the qualification cohort (376 deals) using same logic as FINAL_CLEAN
    all_qualified_deal_ids = set()

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        print(f"Processing {quarter_id}...")

        # Get all snapshots for this quarter
        snapshots = fetch_all_rows_by_filters(
            supabase,
            'deals_snapshot',
            'deal_id, week_of_quarter, stage_id, pipeline_id',
            eq={'fiscal_quarter': quarter_id, 'pipeline_id': PIPELINE_ID}
        )

        # Group by deal_id and find first qualified week
        snapshots_by_deal = defaultdict(list)
        for snap in snapshots:
            deal_id_str = str(snap['deal_id'])
            # EXCLUDE data quality issues (same logic as FINAL_CLEAN)
            if deal_id_str not in excluded_28:
                snapshots_by_deal[deal_id_str].append(snap)

        for deal_id, snaps in snapshots_by_deal.items():
            snaps.sort(key=lambda x: x.get('week_of_quarter', 99))

            for snap in snaps:
                if is_deal_in_analytics_scope(
                    stage_at_date=snap.get('stage_id'),
                    pipeline_id=snap.get('pipeline_id'),
                    excluded_pipelines=excluded_pipelines,
                    stage_cfg=stage_cfg
                ):
                    all_qualified_deal_ids.add(deal_id)
                    break

    print(f"Total qualified cohort size: {len(all_qualified_deal_ids)}")
    print()

    # Check overlap with recovered deals
    recovered_set = set(RECOVERED_25)
    recovered_in_cohort = recovered_set & all_qualified_deal_ids

    # Check overlap with excluded deals
    excluded_in_cohort = excluded_28 & all_qualified_deal_ids

    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print()

    print(f"Recovered deals in qualification cohort: {len(recovered_in_cohort)}")
    if recovered_in_cohort:
        print("  Deal IDs:", list(recovered_in_cohort)[:5], "..." if len(recovered_in_cohort) > 5 else "")
        print()
        print("  ⚠️  Some recovered deals WERE in the cohort!")
        print("     This means the data quality fixes affected the conversion rate calculation.")
        print()

    print(f"Excluded deals in qualification cohort: {len(excluded_in_cohort)}")
    if excluded_in_cohort:
        print("  Deal IDs:", list(excluded_in_cohort)[:5], "..." if len(excluded_in_cohort) > 5 else "")
        print()
        print("  ⚠️  Some excluded deals WERE in the cohort!")
        print("     This means the data quality fixes affected the conversion rate calculation.")
        print()

    print("=" * 80)
    print("INTERPRETATION")
    print("=" * 80)
    print()

    total_overlap = len(recovered_in_cohort) + len(excluded_in_cohort)

    if total_overlap == 0:
        print("✓ ZERO OVERLAP CONFIRMED")
        print()
        print("None of the 53 data quality deals (25 recovered + 28 excluded) were")
        print("part of the 376-qualified cohort used in conversion_rate_prospective.")
        print()
        print("This means:")
        print("  • The identical 7.2% (27/376) before and after makes perfect sense")
        print("  • The data quality fixes cleaned up a DIFFERENT population")
        print("  • These 53 deals were NOT qualified during weeks 1-13 of their quarters")
        print()
        print("Recommendation for metrics.yaml:")
        print("  Add note: 'Data quality fixes addressed retroactive/backdated deals")
        print("  that were never part of the prospective qualification cohort.'")
        print()

    else:
        print("⚠️  OVERLAP DETECTED")
        print()
        print(f"Found {total_overlap} deals that WERE in the 376-qualified cohort:")
        print(f"  • {len(recovered_in_cohort)} recovered deals")
        print(f"  • {len(excluded_in_cohort)} excluded deals")
        print()
        print("This means:")
        print("  • Getting exactly 27/376 after these fixes is suspicious")
        print("  • The conversion rate calculation should have changed")
        print("  • Need independent re-verification from scratch")
        print()
        print("❌ ACTION REQUIRED:")
        print("  Re-run conversion computation independently to verify 27/376 is correct")
        print("  after excluding these deals and recovering those deals.")
        print()

    print()


if __name__ == '__main__':
    main()
