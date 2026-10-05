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
        # MUST stay "AE Team" — this is the literal entity_name the live
        # rep_targets table's FY2027_Q3 team row already has (confirmed
        # against production). The live unique constraint is
        # UNIQUE(period, level, entity_name, metric), so upserting any
        # other string here (e.g. "GrowthBook Team") does NOT update that
        # existing row — it INSERTS A SECOND team row for the same
        # period, leaving the real one untouched and making every reader
        # that does .eq("level","team")...data[0] (no further filter)
        # non-deterministic about which one it gets. See main()'s
        # pre-upsert guard below, which aborts instead of silently
        # creating that second row. The name is legacy/historical, not a
        # claim that the number is AE-only — it now includes am-role
        # quotas too (role=None on this row; see config/client.yaml's
        # quota_roles comment for the metric-unification history).
        "entity_name": "AE Team",
        "entity_email": None,
        "role": None,
        "metric": basis,
        "target_value": team_total,
        "parent_entity": "GrowthBook",
    }
    rows.append(team_row)

    return rows


class TeamRowCollisionError(Exception):
    """Raised when writing this period's rows would create (or has
    created) more than one level='team' row for the same
    (period, metric) — see check_collision_guard()/check_post_write_guard()."""


def _format_row(row: dict) -> str:
    return (f"period={row.get('period')!r} level={row.get('level')!r} "
            f"entity_name={row.get('entity_name')!r} "
            f"metric={row.get('metric')!r} "
            f"target_value={row.get('target_value')!r}")


def check_collision_guard(sb_client, period: str, incoming_team_row: dict) -> None:
    """Pre-write guard: abort (raise) before touching the DB for this
    period if a live 'team' row already exists for (period, metric)
    whose entity_name differs from the one we are about to write.

    sb_client: a Supabase client exposing .table(...).select(...)
        .eq(...).eq(...).eq(...).execute() -> object with `.data` (a
        list of dict rows). A real SupabaseWriter().client or a test
        fake with the same shape.
    period: e.g. "FY2027_Q3".
    incoming_team_row: the team row build_rows_for_quarter() just built
        for this period (the one about to be upserted).

    Does nothing (returns normally) when:
      - no existing team row for (period, metric), or
      - the existing team row's entity_name already matches.

    Raises TeamRowCollisionError, printing both rows side by side,
    when an existing team row's entity_name does NOT match.
    """
    metric = incoming_team_row["metric"]
    resp = sb_client.table('rep_targets').select(
        'period,level,entity_name,metric,target_value'
    ).eq('period', period).eq('level', 'team').eq('metric', metric).execute()
    existing_rows = resp.data or []

    for existing in existing_rows:
        if existing.get('entity_name') != incoming_team_row['entity_name']:
            msg = (
                f"\n{'!' * 70}\n"
                f"ABORTING — team-row collision guard tripped for {period}.\n"
                f"A live 'team' row already exists for this period+metric "
                f"with a DIFFERENT entity_name than the one this run is "
                f"about to write. Upserting would NOT update the existing "
                f"row (the live unique constraint is "
                f"UNIQUE(period, level, entity_name, metric)) — it would "
                f"INSERT A SECOND team row for the same period, leaving "
                f"the real one untouched.\n\n"
                f"  EXISTING (live):  {_format_row(existing)}\n"
                f"  ABOUT TO WRITE:   {_format_row(incoming_team_row)}\n\n"
                f"Nothing was written for {period}. Fix config/targets.yaml "
                f"(or this script) so the entity_name matches the existing "
                f"live row, then re-run.\n"
                f"{'!' * 70}\n"
            )
            print(msg)
            raise TeamRowCollisionError(msg)


def check_post_write_guard(sb_client, period: str, metric: str) -> None:
    """Post-write guard: after upserting this period's rows, confirm
    there is still exactly one level='team' row for (period, metric).
    If more than one exists, abort/report the same way — this is the
    "did we just create the collision" check, for cases the pre-write
    guard couldn't have known about (e.g. a concurrent write)."""
    resp = sb_client.table('rep_targets').select(
        'period,level,entity_name,metric,target_value'
    ).eq('period', period).eq('level', 'team').eq('metric', metric).execute()
    existing_rows = resp.data or []
    if len(existing_rows) > 1:
        rows_str = "\n".join(f"  - {_format_row(r)}" for r in existing_rows)
        msg = (
            f"\n{'!' * 70}\n"
            f"ABORTING — post-write check found {len(existing_rows)} "
            f"'team' rows for period={period!r} metric={metric!r} "
            f"(expected exactly 1):\n{rows_str}\n"
            f"{'!' * 70}\n"
        )
        print(msg)
        raise TeamRowCollisionError(msg)


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
        team_row = rows_to_upsert[-1]
        basis = quarter_data.get('basis', 'incremental_arr')

        print(f"Period: {period}")
        print(f"  Team total (computed): ${team_total:,}")
        print(f"  Basis: {basis}")
        print()

        # Collision guard (live-DB-facing): before writing ANYTHING for
        # this period, check whether a 'team' row already exists for
        # (period, metric) with a DIFFERENT entity_name than the one
        # we're about to write. The live unique constraint is
        # UNIQUE(period, level, entity_name, metric) — a mismatched name
        # does not update the existing row, it inserts a second team row
        # for the same period, and every reader that does
        # .eq("level","team")...data[0] (no name/role filter) then
        # becomes non-deterministic about which team row it gets. This
        # is general — it guards every future quarter/config change,
        # not just the FY2027_Q3 "GrowthBook Team" incident that
        # motivated it.
        check_collision_guard(writer.client, period, team_row)

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

        # Post-write guard: confirm this write did not just create a
        # second 'team' row for this period+metric (e.g. a concurrent
        # write, or a guard gap the pre-write check couldn't catch).
        check_post_write_guard(writer.client, period, team_row["metric"])

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
