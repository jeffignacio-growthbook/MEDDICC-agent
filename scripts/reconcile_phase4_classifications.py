#!/usr/bin/env python3
"""
Phase 4 Reconciliation: Verify won/lost classification is behavior-preserving.

Compares OLD hardcoded logic vs NEW field_semantics logic for every deal.
"""

import sys
from pathlib import Path
from collections import defaultdict

# Add paths
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

from db import get_supabase
from field_semantics import is_won, is_lost, is_open

def old_classification(stage: str) -> str:
    """OLD hardcoded logic from Phase 3."""
    if stage in ('closedwon', '1297321623'):
        return 'won'
    elif stage in ('closedlost', '1297321624', '68509551'):
        return 'lost'
    else:
        return 'open'

def new_classification(stage: str) -> str:
    """NEW field_semantics logic from Phase 4."""
    if is_won(stage):
        return 'won'
    elif is_lost(stage):
        return 'lost'
    elif is_open(stage):
        return 'open'
    else:
        return 'unknown'  # Should never happen

def main():
    print("=" * 80)
    print("PHASE 4 RECONCILIATION: Won/Lost Classification Validation")
    print("=" * 80)
    print()

    # Get Supabase client
    sb = get_supabase()

    # Run OLD logic SQL query
    print("Running OLD logic SQL query...")
    old_result = sb.table('deals').execute()

    # Manually compute old logic aggregates
    old_counts = defaultdict(lambda: {'count': 0, 'arr': 0})
    new_counts = defaultdict(lambda: {'count': 0, 'arr': 0})

    differences = []

    for deal in old_result.data:
        stage = deal.get('stage', '')
        arr = deal.get('arr_usd') or 0

        old_class = old_classification(stage)
        new_class = new_classification(stage)

        old_counts[old_class]['count'] += 1
        old_counts[old_class]['arr'] += arr

        new_counts[new_class]['count'] += 1
        new_counts[new_class]['arr'] += arr

        # Track differences
        if old_class != new_class:
            differences.append({
                'deal_id': deal.get('deal_id'),
                'company': deal.get('company_name'),
                'stage': stage,
                'arr_usd': arr,
                'old_classification': old_class,
                'new_classification': new_class
            })

    print(f"Analyzed {len(old_result.data)} deals")
    print()

    # Display comparison table
    print("CLASSIFICATION COMPARISON:")
    print()
    print("Outcome      | OLD Logic              | NEW Logic              | Match")
    print("-" * 80)

    all_outcomes = sorted(set(list(old_counts.keys()) + list(new_counts.keys())))

    matches = True
    for outcome in all_outcomes:
        old_count = old_counts[outcome]['count']
        old_arr = old_counts[outcome]['arr']
        new_count = new_counts[outcome]['count']
        new_arr = new_counts[outcome]['arr']

        match_symbol = "✓" if (old_count == new_count and old_arr == new_arr) else "✗"
        if old_count != new_count or old_arr != new_arr:
            matches = False

        print(f"{outcome:12} | {old_count:6} deals ${old_arr:>10,.0f} | {new_count:6} deals ${new_arr:>10,.0f} | {match_symbol}")

    print("-" * 80)
    print()

    # Report results
    if matches and len(differences) == 0:
        print("✅ PHASE 4 CONFIRMED BEHAVIOR-PRESERVING")
        print()
        print("All deal classifications match exactly between OLD and NEW logic.")
        print("Won/lost/open counts and ARR totals are identical.")
        print("Safe to proceed to Phase 5.")
        return 0
    else:
        print("❌ CLASSIFICATION DIFFERENCES DETECTED")
        print()
        print(f"Found {len(differences)} deals with different classifications:")
        print()

        print("Deal ID          | Company              | Stage                | ARR      | OLD    | NEW")
        print("-" * 100)
        for diff in differences[:20]:  # Show first 20
            print(f"{diff['deal_id'][:16]:16} | {diff['company'][:20]:20} | {diff['stage'][:20]:20} | ${diff['arr_usd']:>7,.0f} | {diff['old_classification']:6} | {diff['new_classification']:6}")

        if len(differences) > 20:
            print(f"... and {len(differences) - 20} more")

        print()
        print("DO NOT PROCEED TO PHASE 5 until differences are resolved.")
        print()
        print("Analysis:")
        # Group differences by stage to identify patterns
        by_stage = defaultdict(list)
        for diff in differences:
            by_stage[diff['stage']].append(diff)

        print(f"\nDifferences by stage:")
        for stage, diffs in sorted(by_stage.items()):
            print(f"  {stage}: {len(diffs)} deals")
            print(f"    Old: {diffs[0]['old_classification']} → New: {diffs[0]['new_classification']}")

        return 1

if __name__ == '__main__':
    sys.exit(main())
