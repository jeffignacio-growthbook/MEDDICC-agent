#!/usr/bin/env python3
"""
Recompute Wins in Migration

Of the 72 total wins across FY2026 Q3, Q4, and FY2027 Q1:
How many fall within the Aug 9 migration set (created_at = 2026-08-09)?

This determines the true scope of pre_migration_deals in metrics.yaml.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent))

from api.db import get_supabase
from api.field_semantics import is_won


FISCAL_QUARTERS = [
    ('FY2026 Q3', '2025-11-01', '2026-01-31'),
    ('FY2026 Q4', '2026-02-01', '2026-04-30'),
    ('FY2027 Q1', '2026-05-01', '2026-07-31'),
]

PIPELINE_ID = 'default'


def main():
    supabase = get_supabase()

    print("=" * 80)
    print("RECOMPUTE: WINS IN AUG 9 MIGRATION")
    print("=" * 80)
    print()

    print("Objective: Of 72 total wins, how many are from Aug 9 migration?")
    print("This determines pre_migration_deals count for metrics.yaml")
    print()

    all_wins = []
    aug9_wins = []
    non_aug9_wins = []

    for quarter_id, start_date, end_date in FISCAL_QUARTERS:
        print(f"\n{quarter_id} ({start_date} to {end_date})")
        print("-" * 80)

        # Get all deals closed in quarter
        deals_resp = supabase.table('deals') \
            .select('deal_id, company_name, stage, close_date, created_at, arr_usd, pipeline_id, deal_status') \
            .eq('pipeline_id', PIPELINE_ID) \
            .gte('close_date', start_date) \
            .lte('close_date', end_date) \
            .execute()

        quarter_wins = []

        for deal in deals_resp.data:
            stage = deal.get('stage')
            if not stage or not is_won(str(stage)):
                continue

            quarter_wins.append({
                'deal_id': str(deal['deal_id']),
                'company_name': deal.get('company_name'),
                'close_date': deal.get('close_date'),
                'created_at': deal.get('created_at'),
                'arr_usd': deal.get('arr_usd'),
                'quarter': quarter_id
            })

        # Separate Aug 9 from others
        q_aug9 = [w for w in quarter_wins if '2026-08-09' in (w['created_at'] or '')]
        q_non_aug9 = [w for w in quarter_wins if '2026-08-09' not in (w['created_at'] or '')]

        print(f"Total wins: {len(quarter_wins)}")
        print(f"  Aug 9 migration: {len(q_aug9)}")
        print(f"  Non-migration: {len(q_non_aug9)}")

        if q_aug9:
            print()
            print(f"Aug 9 migration wins in {quarter_id}:")
            for win in sorted(q_aug9, key=lambda x: x['company_name']):
                company = (win['company_name'] or 'Unknown')[:30]
                arr = f"${win['arr_usd']:,.0f}" if win['arr_usd'] else "$0"
                print(f"  - {company:30s}  {arr:>15s}  {win['close_date']}")

        all_wins.extend(quarter_wins)
        aug9_wins.extend(q_aug9)
        non_aug9_wins.extend(q_non_aug9)

    # Summary
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()

    print(f"Total wins across all quarters: {len(all_wins)}")
    print(f"Aug 9 migration wins: {len(aug9_wins)}")
    print(f"Non-migration wins: {len(non_aug9_wins)}")
    print()

    pct_migration = (len(aug9_wins) / len(all_wins) * 100) if all_wins else 0

    print(f"Migration wins: {pct_migration:.1f}% of total")
    print()

    # Expected vs actual
    print("Reconciliation:")
    print(f"  Expected total wins: 72")
    print(f"  Actual total wins: {len(all_wins)}")

    if len(all_wins) != 72:
        diff = len(all_wins) - 72
        print(f"  ⚠️  Difference: {diff:+d} wins")
        print()
        if diff > 0:
            print("  Possible reasons for extra wins:")
            print("    - Pipeline filter may be broader than original analysis")
            print("    - Won deals added since original count")
            print("    - Stage mapping difference")
        else:
            print("  Possible reasons for missing wins:")
            print("    - Pipeline filter may be narrower than original analysis")
            print("    - Won deals removed/changed stage")
            print("    - Stage mapping difference")
    else:
        print(f"  ✓ Matches expected count")

    print()

    # ARR breakdown
    aug9_arr = sum(w['arr_usd'] for w in aug9_wins if w['arr_usd'])
    non_aug9_arr = sum(w['arr_usd'] for w in non_aug9_wins if w['arr_usd'])
    total_arr = aug9_arr + non_aug9_arr

    print("ARR Breakdown:")
    print(f"  Aug 9 migration: ${aug9_arr:,.0f}")
    print(f"  Non-migration: ${non_aug9_arr:,.0f}")
    print(f"  Total: ${total_arr:,.0f}")
    print()

    if total_arr > 0:
        pct_migration_arr = (aug9_arr / total_arr * 100)
        print(f"Migration wins represent {pct_migration_arr:.1f}% of total ARR")

    print()

    # Per-quarter breakdown
    print()
    print("Per-Quarter Breakdown:")
    print("-" * 80)
    print(f"{'Quarter':12s} | {'Total':>6s} | {'Aug 9':>6s} | {'Non-Aug9':>9s} | {'Aug9%':>7s}")
    print("-" * 80)

    for quarter_id, _, _ in FISCAL_QUARTERS:
        q_all = [w for w in all_wins if w['quarter'] == quarter_id]
        q_aug9 = [w for w in aug9_wins if w['quarter'] == quarter_id]
        q_non = [w for w in non_aug9_wins if w['quarter'] == quarter_id]

        pct = (len(q_aug9) / len(q_all) * 100) if q_all else 0

        print(f"{quarter_id:12s} | {len(q_all):>6d} | {len(q_aug9):>6d} | {len(q_non):>9d} | {pct:>6.1f}%")

    print()

    # Recommendations for metrics.yaml
    print()
    print("=" * 80)
    print("RECOMMENDATION FOR metrics.yaml")
    print("=" * 80)
    print()

    print(f"pre_migration_deals:")
    print(f"  count: {len(aug9_wins)}")
    print(f"  description: \"Deals migrated from Copper CRM on Aug 9, 2026\"")
    print(f"  total_wins_analyzed: {len(all_wins)}")
    print(f"  migration_percentage: {pct_migration:.1f}%")
    print()

    print("Exclusion criterion to use:")
    print("  WHERE created_at >= '2026-08-09 00:00:00'")
    print("    AND created_at <= '2026-08-09 23:59:59'")
    print()

    print("OR, if source markers found (from find_copper_source_markers.py):")
    print("  WHERE hs_object_source = 'IMPORT' (or equivalent marker)")
    print()

    # Detail for documentation
    print()
    print("Details for documentation:")
    print("-" * 80)
    print()

    print(f"1. Total qualified-won deals analyzed: {len(all_wins)}")
    print(f"2. Pre-migration deals (Aug 9): {len(aug9_wins)} ({pct_migration:.1f}%)")
    print(f"3. Native HubSpot deals: {len(non_aug9_wins)} ({100-pct_migration:.1f}%)")
    print()
    print("4. By quarter:")
    for quarter_id, _, _ in FISCAL_QUARTERS:
        q_aug9 = [w for w in aug9_wins if w['quarter'] == quarter_id]
        q_all = [w for w in all_wins if w['quarter'] == quarter_id]
        print(f"   {quarter_id}: {len(q_aug9)}/{len(q_all)} migration wins")
    print()

    print("5. ARR impact:")
    print(f"   Migration deals: ${aug9_arr:,.0f} ({pct_migration_arr:.1f}% of total ARR)")
    print(f"   Native deals: ${non_aug9_arr:,.0f}")
    print()

    if len(aug9_wins) > 20:
        print("6. ⚠️  SIGNIFICANT MIGRATION IMPACT")
        print(f"   {len(aug9_wins)} migration wins is a substantial portion of {len(all_wins)} total")
        print("   These deals may distort conversion metrics if not properly categorized")
        print("   Recommend treating as separate cohort in analysis")

    print()

    # Export findings
    output_file = 'wins_in_migration_recomputed.txt'
    with open(output_file, 'w') as f:
        f.write("Wins in Aug 9 Migration - Recomputed\n")
        f.write("=" * 80 + "\n\n")

        f.write(f"Total wins: {len(all_wins)}\n")
        f.write(f"Aug 9 migration: {len(aug9_wins)} ({pct_migration:.1f}%)\n")
        f.write(f"Non-migration: {len(non_aug9_wins)}\n\n")

        f.write("Per Quarter:\n")
        for quarter_id, _, _ in FISCAL_QUARTERS:
            q_all = [w for w in all_wins if w['quarter'] == quarter_id]
            q_aug9 = [w for w in aug9_wins if w['quarter'] == quarter_id]
            f.write(f"  {quarter_id}: {len(q_aug9)}/{len(q_all)} migration wins\n")

        f.write("\n")
        f.write(f"ARR: ${aug9_arr:,.0f} migration, ${non_aug9_arr:,.0f} native\n")

        f.write("\nAug 9 Migration Wins:\n")
        for win in sorted(aug9_wins, key=lambda x: (x['quarter'], x['company_name'])):
            f.write(f"  {win['quarter']:12s} {win['company_name']:30s} ${win['arr_usd'] or 0:>12,.0f}\n")

    print(f"Full findings written to: {output_file}")
    print()


if __name__ == '__main__':
    main()
