#!/usr/bin/env python3
"""
Seed user personas from config/client.yaml team roster.

Reads team roster from client config and creates user_personas records
with inferred personas based on role/title.

Usage:
  python seed_user_personas.py
  python seed_user_personas.py --dry-run
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from utils import load_client_config
from supabase_client import SupabaseWriter


# Persona inference rules based on role/title keywords
PERSONA_RULES = {
    "executive": [
        "ceo", "cto", "cfo", "coo", "cro", "cmo",
        "president", "vp", "vice president", "head of",
        "chief", "founder", "co-founder"
    ],
    "sales_leadership": [
        "director of sales", "sales director", "sales manager",
        "sales lead", "account executive manager", "ae manager",
        "sales ops manager", "revenue operations manager"
    ],
    "operational": [
        "operations", "ops manager", "revenue ops", "revops",
        "sales ops", "analyst", "data analyst", "business ops"
    ],
    "ic": [
        "account executive", "ae ", " ae", "sales rep", "sdr",
        "business development", "bdr", "account manager"
    ]
}


def infer_persona(role: str, title: str = None) -> str:
    """
    Infer persona from role/title using keyword matching.

    Args:
        role: User's role (from config)
        title: User's title (optional)

    Returns:
        Persona string: executive | sales_leadership | operational | ic | other
    """
    combined = f"{role or ''} {title or ''}".lower()

    for persona, keywords in PERSONA_RULES.items():
        if any(kw in combined for kw in keywords):
            return persona

    return "other"


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Seed user personas from team roster config'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print personas without writing to database'
    )

    return parser.parse_args()


def main():
    """Seed user personas from config."""
    args = parse_args()
    config = load_client_config()

    # Get team roster from config
    team = config.get("team", {})
    roster = team.get("roster", [])

    if not roster:
        print("⚠️  No team roster found in config/client.yaml")
        print("Add a team.roster section with Slack user IDs and roles")
        return

    print(f"\nSeeding user personas from config")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"\n{'='*80}")

    personas = []

    for member in roster:
        slack_id = member.get("slack_user_id")
        if not slack_id:
            print(f"⚠️  Skipping member without slack_user_id: {member}")
            continue

        role = member.get("role", "")
        title = member.get("title")
        email = member.get("email")
        name = member.get("name")

        # Infer persona
        persona = infer_persona(role, title)

        personas.append({
            "slack_user_id": slack_id,
            "email": email,
            "display_name": name,
            "persona": persona,
            "source": "admin_seed"
        })

        # Print inference
        print(f"\n{name or slack_id}")
        print(f"  Role: {role}")
        if title:
            print(f"  Title: {title}")
        print(f"  → Persona: {persona}")

    print(f"\n{'='*80}")
    print(f"Total personas: {len(personas)}")

    if args.dry_run:
        print("\n✓ DRY RUN COMPLETE (no data written)")
        return

    # Write to database
    supabase = SupabaseWriter().client

    for p in personas:
        try:
            # Upsert (update if exists)
            supabase.table('user_personas').upsert(
                p,
                on_conflict='slack_user_id'
            ).execute()
            print(f"  ✓ {p['display_name']} ({p['persona']})")
        except Exception as e:
            print(f"  ✗ Failed to write {p['display_name']}: {e}")

    print(f"\n✓ Personas written to Supabase")


if __name__ == '__main__':
    main()
