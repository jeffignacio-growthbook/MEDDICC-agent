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


def build_rows_for_quarter(quarter_key: str, quarter_data: dict) -> list:
    """Pure row-building logic for one quarter, no I/O.

    Returns the list of rep rows plus ONE computed team row (sum of the
    rep rows it just built — never a separately hand-typed team_total).
    Exposed as its own function (not inlined in main()) so it can be
    unit-tested against a mock/fake Supabase client without touching the
    network — see tests/test_seed_targets_rows.py.
    """
    period = quarter_key.replace('fy', 'FY').replace('_q', '_Q').upper()
    basis = quarter_data.get('basis', 'incremental_arr')

    reps = quarter_data.get('reps', {})
    rows = []
    team_total = 0

    for email, rep_data in reps.items():
        target = rep_data['target'] if isinstance(rep_data, dict) else rep_data
        role = rep_data.get('role', 'ae') if isinstance(rep_data, dict) else 'ae'

        # Get display name from email (first part before @)
        entity_name = email.split('@')[0].replace('.', ' ').title()

        row = {
            "period": period,
            "level": "rep",
            "entity_name": entity_name,
            "entity_email": email,
            "role": role,
            "metric": basis,  # "incremental_arr"
            "target_value": target,
            "parent_entity": "AM Team" if role == "am" else "AE Team",
        }
        rows.append(row)
        team_total += target

    # Team row is COMPUTED as the sum of the rep rows just built above —
    # never read from a separate hand-typed `team_total` YAML key (that
    # key was removed from config/targets.yaml specifically to make this
    # the only way a team figure can be produced, so it can never drift
    # from the rows it's supposed to equal).
    team_row = {
        "period": period,
        "level": "team",
        "entity_name": "GrowthBook Team",
        "entity_email": None,
        "role": None,
        "metric": basis,
        "target_value": team_total,
        "parent_entity": "GrowthBook",
    }
    rows.append(team_row)

    return rows


def main():
    """Load targets from config/targets.yaml and upsert to rep_targets table."""
    load_dotenv(Path(__file__).parent.parent / '.env')

    from supabase_client import SupabaseWriter
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
        rows_to_upsert = build_rows_for_quarter(quarter_key, quarter_data)
        period = rows_to_upsert[-1]["period"]  # team row is appended last
        team_total = rows_to_upsert[-1]["target_value"]
        basis = quarter_data.get('basis', 'incremental_arr')

        print(f"Period: {period}")
        print(f"  Team total (computed): ${team_total:,}")
        print(f"  Basis: {basis}")
        print()

        for row in rows_to_upsert[:-1]:
            ramp_note = ""
            rep_cfg = quarter_data.get('reps', {}).get(row["entity_email"])
            if isinstance(rep_cfg, dict) and rep_cfg.get('ramp'):
                ramp_note = " (ramp)"
            print(f"  ✓ {row['entity_email']} [{row['role']}]: "
                  f"${row['target_value']:,}{ramp_note}")

        print(f"  ✓ Team total: ${team_total:,}")
        print()

        # Upsert all rows for this quarter
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
