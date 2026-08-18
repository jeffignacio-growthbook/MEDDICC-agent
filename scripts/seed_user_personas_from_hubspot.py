#!/usr/bin/env python3
"""
Seed user personas from HubSpot Users API + deal ownership inference.

Since HubSpot doesn't provide role data, we infer roles from:
1. Deal ownership patterns (AEs have active deals)
2. Config overrides (executives, RevOps)
3. Everything else = 'other' (self-registers via DM)

Slack IDs are added lazily on first message (email-based lookup).
"""

import os
import sys
import json
import argparse
import requests
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from supabase_client import SupabaseWriter

HUBSPOT_API_KEY = os.getenv('HUBSPOT_API_KEY')

# Role inference thresholds based on deal ownership
DEAL_COUNT_THRESHOLDS = {
    'ae': 10,      # 10+ active deals = likely an AE
    'sdr': 5,      # 1-9 active deals might be SDR or junior AE
}

# Config overrides - emails that map to specific roles
ROLE_OVERRIDES = {
    'jeff.ignacio@growthbook.io': ('vp_revops', 'VP Revenue Operations'),
    'graham@growthbook.io': ('cro', 'CRO'),  # superAdmin in HubSpot
    'jake.stangl@growthbook.io': ('sdr', 'Sales Development Representative'),  # SDR with deals
    # Add other known executives here
}

# Role to role_group mapping
ROLE_TO_GROUP = {
    'cro': 'executive',
    'vp_sales': 'sales_leadership',
    'vp_revops': 'operational',
    'sdl': 'sales_leadership',
    'ae': 'ic',
    'am': 'ic',
    'sdr': 'ic',
    'revops': 'operational',
    'other': 'other',
}


def fetch_hubspot_users() -> list[dict]:
    """Fetch all active HubSpot users."""
    if not HUBSPOT_API_KEY:
        raise ValueError('HUBSPOT_API_KEY environment variable required')

    url = 'https://api.hubapi.com/settings/v3/users'
    headers = {'Authorization': f'Bearer {HUBSPOT_API_KEY}'}

    all_users = []
    after = None

    while True:
        params = {'limit': 100}
        if after:
            params['after'] = after

        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()
        users = data.get('results', [])
        all_users.extend(users)

        # Check for next page
        paging = data.get('paging', {})
        next_page = paging.get('next', {})
        after = next_page.get('after')

        if not after:
            break

    return all_users


def get_deal_ownership_stats(sb) -> dict:
    """
    Get deal ownership stats from Supabase deals table.
    Returns: {email: {'deal_count': N, 'total_value': $X}}
    """
    from supabase_client import select_all

    rows = select_all(sb, 'deals',
        columns='owner_email,deal_value',
        filters=[('eq', 'deal_status', 'active')]
    )

    stats = {}
    for row in rows:
        email = row.get('owner_email')
        if not email:
            continue

        if email not in stats:
            stats[email] = {'deal_count': 0, 'total_value': 0}

        stats[email]['deal_count'] += 1
        stats[email]['total_value'] += row.get('deal_value') or 0

    return stats


def infer_role_from_deals(email: str, deal_stats: dict) -> tuple[str, str]:
    """
    Infer role from deal ownership patterns.

    Returns: (role, title)
    """
    # Check config overrides first
    if email in ROLE_OVERRIDES:
        return ROLE_OVERRIDES[email]

    # Check deal ownership
    stats = deal_stats.get(email, {})
    deal_count = stats.get('deal_count', 0)

    if deal_count >= DEAL_COUNT_THRESHOLDS['ae']:
        # Likely an AE
        return ('ae', 'Account Executive')
    elif deal_count > 0:
        # Has some deals but not many - could be SDR or junior AE
        # Default to AE since SDRs typically hand off deals
        return ('ae', 'Account Executive')
    else:
        # No deals - could be SDR, AM, support, or other
        # Let them self-register
        return ('other', 'Team Member')


def main():
    """Seed user personas from HubSpot users."""
    parser = argparse.ArgumentParser(
        description='Seed user personas from HubSpot Users API'
    )
    parser.add_argument('--dry-run', action='store_true',
                       help='Print personas without writing to database')
    args = parser.parse_args()

    print(f"\nSeeding user personas from HubSpot Users API")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"\n{'='*80}")

    # Fetch HubSpot users
    print("\n1. Fetching HubSpot users...")
    hubspot_users = fetch_hubspot_users()
    print(f"   Found {len(hubspot_users)} HubSpot users")

    # Get deal ownership stats for role inference
    print("\n2. Analyzing deal ownership patterns...")
    supabase = SupabaseWriter().client
    deal_stats = get_deal_ownership_stats(supabase)
    print(f"   {len(deal_stats)} users have active deals")

    # Build personas
    print("\n3. Mapping users to personas...")
    personas = []
    role_counts = {'ae': 0, 'sdr': 0, 'vp_revops': 0, 'cro': 0, 'other': 0}

    for user in hubspot_users:
        email = user.get('email', '').strip().lower()
        if not email:
            continue

        first_name = user.get('firstName', '')
        last_name = user.get('lastName', '')
        name = f"{first_name} {last_name}".strip()

        # Infer role
        role, title = infer_role_from_deals(email, deal_stats)
        role_group = ROLE_TO_GROUP.get(role, 'other')

        personas.append({
            'email': email,
            'slack_user_id': None,  # Added lazily on first message
            'name': name,
            'role': role,
            'role_group': role_group,
            'title': title,
            'source': 'hubspot',
        })

        role_counts[role] = role_counts.get(role, 0) + 1

        # Print mapping
        deal_info = deal_stats.get(email, {})
        deals = deal_info.get('deal_count', 0)
        print(f"  {name:30} {email:35} → {role:10} ({deals} deals)")

    print(f"\n{'='*80}")
    print(f"Total personas: {len(personas)}")
    print(f"\nRole distribution:")
    for role, count in sorted(role_counts.items(), key=lambda x: -x[1]):
        if count > 0:
            print(f"  {role:15} {count:3}")

    if args.dry_run:
        print("\n✓ DRY RUN COMPLETE (no data written)")
        return

    # Write to database
    print(f"\n4. Writing to user_personas table...")
    for p in personas:
        try:
            # Upsert by email (primary key)
            supabase.table('user_personas').upsert(
                p,
                on_conflict='email'
            ).execute()
        except Exception as e:
            print(f"  ✗ Failed to write {p['name']}: {e}")

    print(f"✓ {len(personas)} personas written to Supabase")

    # Verification query
    print(f"\n5. Verification:")
    result = supabase.table('user_personas').select(
        'email,name,role,role_group,slack_user_id,source'
    ).execute()

    rows = result.data
    print(f"  {len(rows)} rows in user_personas table")
    print(f"  {sum(1 for r in rows if r.get('slack_user_id'))} have Slack IDs")
    print(f"  {sum(1 for r in rows if not r.get('slack_user_id'))} awaiting first message")


if __name__ == '__main__':
    main()
