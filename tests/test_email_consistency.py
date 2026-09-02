#!/usr/bin/env python3
"""
Email consistency guards — catches identity mismatches at seed time.

After three hours debugging christian@growthbook.io vs christian.liebenow@growthbook.io,
these tests catch email convention drift before it surfaces in production queries.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

# Add scripts and api to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'api'))

import yaml
from supabase_client import select_all
from db import get_supabase


def test_target_emails_resolve_to_known_owners():
    """
    Every entity_email in rep_targets exists in user_personas and appears
    in deals.owner_email. A target for an email nobody owns is unjoinable.

    This caught: christian@growthbook.io in personas, christian.liebenow@growthbook.io
    in targets → query_rep_attainment filter produced empty set.
    """
    sb = get_supabase()

    # Load target emails from rep_targets table
    target_rows = select_all(sb, "rep_targets",
        columns="entity_email,period,level,role",
        filters=[]
    )

    target_emails = set(t["entity_email"] for t in target_rows if t.get("entity_email"))

    # Load persona emails
    persona_rows = select_all(sb, "user_personas",
        columns="email,name,role",
        filters=[]
    )
    persona_emails = set(p["email"] for p in persona_rows if p.get("email"))

    # Check every target email exists in personas
    missing_in_personas = target_emails - persona_emails

    assert not missing_in_personas, (
        f"Target emails not found in user_personas: {missing_in_personas}. "
        f"These targets are unjoinable. Either add personas or fix email in targets."
    )

    print(f"✓ All {len(target_emails)} target emails found in user_personas")

    # TODO: Enable this check once deals.owner_email is populated
    # deals = select_all(sb, "deals", columns="owner_email", filters=[])
    # deal_emails = set(d["owner_email"] for d in deals if d.get("owner_email"))
    # missing_in_deals = target_emails - deal_emails
    #
    # if missing_in_deals:
    #     print(f"⚠ Warning: {len(missing_in_deals)} target emails never appear in deals.owner_email")
    #     print(f"   This may indicate targets were set for reps with no deals yet")


def test_config_team_roster_matches_personas():
    """
    Every email in config/client.yaml team roster exists in user_personas.
    Prevents client.yaml using christian@growthbook.io while personas has
    christian.liebenow@growthbook.io.
    """
    sb = get_supabase()

    # Load team roster from config
    config_path = Path(__file__).parent.parent / 'config' / 'client.yaml'
    with open(config_path) as f:
        config = yaml.safe_load(f)

    roster_emails = set()
    if config.get('team', {}).get('members'):
        roster_emails = set(
            m['email'] for m in config['team']['members']
            if m.get('email')
        )

    # Load persona emails
    persona_rows = select_all(sb, "user_personas",
        columns="email",
        filters=[]
    )
    persona_emails = set(p["email"] for p in persona_rows if p.get("email"))

    # Check roster emails exist in personas
    missing = roster_emails - persona_emails

    assert not missing, (
        f"Team roster emails not in user_personas: {missing}. "
        f"Either seed personas from roster or update roster emails to match personas."
    )

    print(f"✓ All {len(roster_emails)} roster emails found in user_personas")


def test_targets_yaml_matches_personas():
    """
    Every rep email in config/targets.yaml exists in user_personas.
    Prevents targets.yaml using christian.liebenow@growthbook.io while personas
    has christian@growthbook.io.
    """
    sb = get_supabase()

    # Load targets from config
    targets_path = Path(__file__).parent.parent / 'config' / 'targets.yaml'
    with open(targets_path) as f:
        targets_config = yaml.safe_load(f)

    targets_emails = set()
    if targets_config.get('targets'):
        for quarter_key, quarter_data in targets_config['targets'].items():
            if quarter_data.get('reps'):
                targets_emails.update(quarter_data['reps'].keys())

    # Load persona emails
    persona_rows = select_all(sb, "user_personas",
        columns="email",
        filters=[]
    )
    persona_emails = set(p["email"] for p in persona_rows if p.get("email"))

    # Check targets emails exist in personas
    missing = targets_emails - persona_emails

    assert not missing, (
        f"Targets config emails not in user_personas: {missing}. "
        f"Run scripts/seed_personas_from_config.py or update targets.yaml to match personas."
    )

    print(f"✓ All {len(targets_emails)} targets config emails found in user_personas")


if __name__ == "__main__":
    print("Email Consistency Guards")
    print("=" * 80)

    try:
        test_target_emails_resolve_to_known_owners()
        test_config_team_roster_matches_personas()
        test_targets_yaml_matches_personas()

        print()
        print("✓ All email consistency checks passed")
        sys.exit(0)

    except AssertionError as e:
        print()
        print(f"✗ Email consistency check failed:")
        print(f"  {e}")
        sys.exit(1)
    except Exception as e:
        print()
        print(f"✗ Test error: {e}")
        raise
