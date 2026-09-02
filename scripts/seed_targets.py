#!/usr/bin/env python3
"""
Seed rep_targets table from config/targets.yaml.

Config is the source of truth (edited by humans).
Table is the query target (efficient joins).
This script keeps them in sync.

Run at onboarding or after editing config/targets.yaml:
    python scripts/seed_targets.py

Same pattern as seed_personas_from_config.py.
"""
import sys
from pathlib import Path
import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from supabase_client import SupabaseWriter

def main():
    """Load targets from config/targets.yaml and upsert to rep_targets table."""
    load_dotenv(Path(__file__).parent.parent / '.env')

    writer = SupabaseWriter()

    # Load targets config
    targets_path = Path(__file__).parent.parent / 'config' / 'targets.yaml'
    with open(targets_path) as f:
        targets_config = yaml.safe_load(f)

    print("Seeding rep_targets from config/targets.yaml")
    print("=" * 70)
    print()

    targets = targets_config.get('targets', {})

    if not targets:
        print("No targets configured in targets.yaml")
        return

    total_rows = 0

    for quarter_key, quarter_data in targets.items():
        # Parse quarter key (e.g., "fy2027_q3" → "FY2027_Q3")
        period = quarter_key.replace('fy', 'FY').replace('_q', '_Q').upper()

        team_total = quarter_data.get('team_total')
        basis = quarter_data.get('basis', 'incremental_arr')

        print(f"Period: {period}")
        print(f"  Team total: ${team_total:,}")
        print(f"  Basis: {basis}")
        print()

        # Individual rep targets
        reps = quarter_data.get('reps', {})
        rows_to_upsert = []

        for email, rep_data in reps.items():
            target = rep_data['target'] if isinstance(rep_data, dict) else rep_data
            is_ramp = isinstance(rep_data, dict) and rep_data.get('ramp', False)

            # Get display name from email (first part before @)
            entity_name = email.split('@')[0].replace('.', ' ').title()

            # Upsert to rep_targets
            # metric = "incremental_arr" matches the basis
            row = {
                "period": period,
                "level": "rep",
                "entity_name": entity_name,
                "entity_email": email,
                "role": "ae",
                "metric": basis,  # "incremental_arr"
                "target_value": target,
                "parent_entity": "AE Team",
            }

            rows_to_upsert.append(row)

            print(f"  ✓ {email}: ${target:,}" + (" (ramp)" if is_ramp else ""))

        # Add team total row
        team_row = {
            "period": period,
            "level": "team",
            "entity_name": "AE Team",
            "entity_email": None,
            "role": "ae",
            "metric": basis,
            "target_value": team_total,
            "parent_entity": "GrowthBook",
        }
        rows_to_upsert.append(team_row)
        print(f"  ✓ AE Team total: ${team_total:,}")

        # Note non-quota roles (don't create rows for them)
        non_quota = quarter_data.get('non_quota_roles', [])
        if non_quota:
            print()
            print(f"  Non-quota roles (no target rows):")
            for email in non_quota:
                print(f"    - {email}")

        print()

        # Upsert all rows for this quarter
        if rows_to_upsert:
            for row in rows_to_upsert:
                try:
                    writer.client.table('rep_targets').upsert(
                        row,
                        on_conflict='period,level,entity_name,metric'
                    ).execute()
                    total_rows += 1
                except Exception as e:
                    print(f"  ✗ Failed to upsert {row['entity_name']}: {e}")

        print()

    print("=" * 70)
    print(f"SUCCESS: Seeded {total_rows} target rows")
    print()
    print("Rep targets are now queryable:")
    print("  SELECT * FROM rep_targets")
    print("  WHERE period = 'FY2027_Q3' AND level = 'rep';")
    print()

if __name__ == '__main__':
    main()
