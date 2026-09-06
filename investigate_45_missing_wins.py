#!/usr/bin/env python3
"""
Investigate 45 Missing Wins

Context: Found 72 total wins, but only 27 appear in qualification-week cohorts.
45 wins (62.5%) never qualified in snapshot weeks 1-13.

Task: Categorize the 45 missing wins:
1. Excluded-stage-to-late-qualification: In Meeting Set/Review weeks 1-13, then qualified+closed after
2. Fast-track: Very short cycle (< 7 days create to close), entered already-won
3. Late qualification: Not in snapshots weeks 1-13, qualified after week 13

Output: Breakdown with example deal names per category
"""

import os
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent))

from scripts.analytics.point_in_time import is_deal_in_analytics_scope, load_scope_config
from api.field_semantics import is_won, stage_bucket
from api.db import get_supabase


FISCAL_QUARTERS = [
    ('FY2026 Q3', '2025-11-01', '2026-01-31'),
    ('FY2026 Q4', '2026-02-01', '2026-04-30'),
    ('FY2027 Q1', '2026-05-01', '2026-07-31'),
]

PIPELINE_ID = 'default'

EXCLUDED_STAGES = {
    '79653122': 'Meeting Set',
    'decisionmakerboughtin': 'Review',
    '68509551': 'Disqualified',
}


def fetch_all_rows(supabase, table, select_cols, filters, page_size=1000):
    """Fetch all rows with pagination."""
    all_rows = []
    offset = 0
    while True:
        query = supabase.table(table).select(select_cols)
        for col, val in filters.items():
            query = query.eq(col, val)
        result = query.range(offset, offset + page_size - 1).execute()
        rows = result.data
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return all_rows


def days_between(start_str, end_str):
    """Calculate days between two date strings."""
    if not start_str or not end_str:
        return None
    try:
        start = datetime.fromisoformat(start_str[:10])
        end = datetime.fromisoformat(end_str[:10])
        return (end - start).days
    except:
        return None


def main():
    supabase = get_supabase()
    excluded_pipelines, stage_cfg = load_scope_config()

    print("=" * 80)
    print("INVESTIGATION: 45 MISSING WINS")
    print("=" * 80)
    print()

    # Step 1: Get all 72 wins from reconciliation
    print("Step 1: Identify all 72 wins")
    print("-" * 80)

    all_wins = []

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        deals_resp = supabase.table('deals') \
            .select('deal_id, company_name, stage, close_date, create_date, pipeline_id') \
            .eq('pipeline_id', PIPELINE_ID) \
            .gte('close_date', start_date) \
            .lte('close_date', end_date) \
            .execute()

        for deal in deals_resp.data:
            stage = deal.get('stage')
            if stage and is_won(str(stage)):
                all_wins.append({
                    'deal_id': str(deal['deal_id']),
                    'company_name': deal.get('company_name'),
                    'close_date': deal.get('close_date'),
                    'create_date': deal.get('create_date'),
                    'quarter': quarter_id,
                    'quarter_start': start_date,
                    'quarter_end': end_date
                })

    print(f"Found {len(all_wins)} total wins")
    print()

    # Step 2: Get the 27 wins captured in qualification cohorts
    print("Step 2: Identify 27 wins captured in qualification cohorts")
    print("-" * 80)

    captured_win_ids = set()

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        # Fetch all snapshots
        snapshots = fetch_all_rows(
            supabase,
            'deals_snapshot',
            'deal_id, week_of_quarter, stage_id, pipeline_id',
            {'fiscal_quarter': quarter_id, 'pipeline_id': PIPELINE_ID}
        )

        # Find deals with qualification weeks
        snapshots_by_deal = defaultdict(list)
        for snap in snapshots:
            snapshots_by_deal[str(snap['deal_id'])].append(snap)

        deal_qualification_weeks = {}
        for deal_id, snaps in snapshots_by_deal.items():
            snaps.sort(key=lambda x: x.get('week_of_quarter', 99))
            for snap in snaps:
                if is_deal_in_analytics_scope(
                    stage_at_date=snap.get('stage_id'),
                    pipeline_id=snap.get('pipeline_id'),
                    excluded_pipelines=excluded_pipelines,
                    stage_cfg=stage_cfg
                ):
                    deal_qualification_weeks[deal_id] = snap.get('week_of_quarter')
                    break

        # Check which ones won in-quarter
        if deal_qualification_weeks:
            deal_ids = list(deal_qualification_weeks.keys())
            deals_resp = supabase.table('deals') \
                .select('deal_id, stage, close_date') \
                .in_('deal_id', deal_ids) \
                .execute()

            for deal in deals_resp.data:
                stage = deal.get('stage')
                close_date = deal.get('close_date')
                if stage and is_won(str(stage)):
                    if close_date and start_date <= close_date <= end_date:
                        captured_win_ids.add(str(deal['deal_id']))

    print(f"Found {len(captured_win_ids)} wins in qualification cohorts")
    print()

    # Step 3: Identify the 45 missing wins
    print("Step 3: Identify missing wins")
    print("-" * 80)

    all_win_ids = set(w['deal_id'] for w in all_wins)
    missing_win_ids = all_win_ids - captured_win_ids

    print(f"Missing wins: {len(missing_win_ids)}")
    print()

    if len(missing_win_ids) != 45:
        print(f"⚠️  Expected 45 missing, found {len(missing_win_ids)}")
        print()

    # Step 4: Investigate each missing win
    print("Step 4: Investigate each missing win")
    print("-" * 80)
    print()

    categories = {
        'excluded_to_late_qual': [],
        'fast_track': [],
        'late_qual_after_week13': [],
        'never_in_snapshots': [],
        'other': []
    }

    for win in all_wins:
        deal_id = win['deal_id']
        if deal_id not in missing_win_ids:
            continue

        company = win['company_name']
        close_date = win['close_date']
        create_date = win['create_date']
        quarter_id = win['quarter']

        # Calculate cycle length
        cycle_days = days_between(create_date, close_date)

        # Check if deal appears in ANY snapshot for this quarter
        snapshots = fetch_all_rows(
            supabase,
            'deals_snapshot',
            'deal_id, week_of_quarter, stage_id',
            {'fiscal_quarter': quarter_id, 'pipeline_id': PIPELINE_ID, 'deal_id': deal_id}
        )

        if not snapshots:
            # Never in snapshots
            categories['never_in_snapshots'].append({
                'deal_id': deal_id,
                'company': company,
                'close_date': close_date,
                'create_date': create_date,
                'cycle_days': cycle_days,
                'reason': 'Not in any snapshot week 1-13'
            })
            continue

        # Categorize based on cycle length first
        if cycle_days is not None and cycle_days < 7:
            categories['fast_track'].append({
                'deal_id': deal_id,
                'company': company,
                'close_date': close_date,
                'create_date': create_date,
                'cycle_days': cycle_days,
                'reason': f'Fast-track: {cycle_days} day cycle'
            })
            continue

        # Check if deal was ever qualified in snapshots
        was_ever_qualified = False
        was_in_excluded_stages = False
        stages_seen = set()

        for snap in snapshots:
            stage_id = str(snap.get('stage_id', ''))
            stages_seen.add(stage_id)

            if is_deal_in_analytics_scope(
                stage_at_date=stage_id,
                pipeline_id=PIPELINE_ID,
                excluded_pipelines=excluded_pipelines,
                stage_cfg=stage_cfg
            ):
                was_ever_qualified = True

            if stage_id in EXCLUDED_STAGES:
                was_in_excluded_stages = True

        if was_in_excluded_stages and not was_ever_qualified:
            # In excluded stages all quarter, never qualified in snapshots
            categories['excluded_to_late_qual'].append({
                'deal_id': deal_id,
                'company': company,
                'close_date': close_date,
                'create_date': create_date,
                'cycle_days': cycle_days,
                'stages_seen': list(stages_seen),
                'reason': 'In excluded stages weeks 1-13, qualified after'
            })
        elif not was_ever_qualified:
            # In snapshots but never qualified
            categories['late_qual_after_week13'].append({
                'deal_id': deal_id,
                'company': company,
                'close_date': close_date,
                'create_date': create_date,
                'cycle_days': cycle_days,
                'stages_seen': list(stages_seen),
                'reason': 'In snapshots but never qualified, must have qualified after week 13'
            })
        else:
            # Other case
            categories['other'].append({
                'deal_id': deal_id,
                'company': company,
                'close_date': close_date,
                'create_date': create_date,
                'cycle_days': cycle_days,
                'stages_seen': list(stages_seen),
                'reason': 'Unknown - was qualified in snapshots but not captured?'
            })

    # REPORT
    print()
    print("=" * 80)
    print("CATEGORIZATION OF 45 MISSING WINS")
    print("=" * 80)
    print()

    for category, label in [
        ('fast_track', 'Fast-track (< 7 day cycles)'),
        ('excluded_to_late_qual', 'Excluded stages → Late qualification'),
        ('late_qual_after_week13', 'Late qualification (after week 13)'),
        ('never_in_snapshots', 'Never in snapshots'),
        ('other', 'Other/Unknown')
    ]:
        deals = categories[category]
        count = len(deals)

        print(f"{label}")
        print("-" * 80)
        print(f"Count: {count}")

        if count > 0:
            print()
            print("Examples:")
            for deal in deals[:5]:  # Show first 5
                print(f"  {deal['company']:40s} | {deal['close_date']} | {deal['cycle_days']} days | {deal['deal_id']}")
                print(f"    → {deal['reason']}")

        print()

    # Summary
    print()
    print("=" * 80)
    print("SUMMARY & IMPLICATIONS")
    print("=" * 80)
    print()

    total_categorized = sum(len(categories[c]) for c in categories)
    print(f"Total missing wins categorized: {total_categorized}")
    print()

    for category, label in [
        ('fast_track', 'Fast-track'),
        ('excluded_to_late_qual', 'Excluded → Late qual'),
        ('late_qual_after_week13', 'Late qual after week 13'),
        ('never_in_snapshots', 'Never in snapshots'),
        ('other', 'Other')
    ]:
        count = len(categories[category])
        pct = count / total_categorized * 100 if total_categorized > 0 else 0
        print(f"{label:30s}: {count:>3d} ({pct:>5.1f}%)")

    print()
    print("IMPLICATIONS:")
    print()

    # Determine dominant category
    max_category = max(categories.keys(), key=lambda k: len(categories[k]))
    max_count = len(categories[max_category])
    max_pct = max_count / total_categorized * 100 if total_categorized > 0 else 0

    if max_category == 'fast_track' and max_pct > 40:
        print("✓ DOMINANT: Fast-track deals (< 7 day cycles)")
        print("  → These are a different population (retroactive/already-won entries)")
        print("  → RECOMMENDATION: Exclude from conversion rate denominator entirely")
        print("  → They shouldn't be force-fit into qualification-week buckets")
    elif max_category == 'late_qual_after_week13' and max_pct > 40:
        print("✓ DOMINANT: Late qualification (after week 13)")
        print("  → Quarter's analysis window too short (ends at week 13)")
        print("  → RECOMMENDATION: Extend snapshot window or reconsider quarter boundaries")
        print("  → Many deals qualify in final weeks of quarter")
    elif max_category == 'excluded_to_late_qual' and max_pct > 40:
        print("✓ DOMINANT: Excluded stages → Late qualification")
        print("  → Real finding about deal behavior (stay in Meeting Set/Review, then fast-close)")
        print("  → RECOMMENDATION: Worth its own callout in analysis")
        print("  → Not a methodology issue, but a sales process pattern")
    else:
        print("~ MIXED: No single dominant category")
        print("  → Multiple factors contributing to missing wins")
        print("  → May need different fixes per category")

    print()


if __name__ == '__main__':
    main()
