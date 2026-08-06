#!/usr/bin/env python3
"""
Backfill participant_domains for existing Fireflies calls.

Reads the deal index to get active company slugs, then for each:
1. Loads the call cache
2. For each Fireflies call without participant_domains
3. Fetches meeting_attendees from Fireflies API
4. Extracts external domains
5. Updates the cache

Only processes calls for active deals (faster, more targeted).
"""
import json
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from github_memory import GitHubMemory
from fireflies_client import get_fireflies_client
import yaml


def get_external_domains(meeting_attendees: list, internal_domains: list) -> list:
    """
    Extract prospect email domains from meeting attendees.
    Excludes organizer's own company domains and common personal email providers.
    """
    skip_domains = set(internal_domains + [
        'gmail.com', 'outlook.com', 'hotmail.com',
        'yahoo.com', 'icloud.com',
        'resource.calendar.google.com',
        'calendar.google.com',
        'group.calendar.google.com',
    ])
    domains = set()
    for attendee in (meeting_attendees or []):
        email = (attendee.get('email') or '').lower().strip()
        if '@' in email:
            domain = email.split('@')[1]
            if domain and domain not in skip_domains:
                domains.add(domain)
    return sorted(list(domains))


def backfill_one_company(slug: str, memory: GitHubMemory, ff_client, internal_domains: list):
    """
    Backfill participant_domains for one company's call cache.

    Args:
        slug: Company slug
        memory: GitHubMemory instance
        ff_client: FirefliesClient instance
        internal_domains: List of internal email domains to exclude

    Returns:
        (updated_count, skipped_count, error_count)
    """
    cache = memory.load_call_cache(slug)
    if not cache:
        return (0, 0, 0)

    calls = cache.get('calls', [])
    updated = 0
    skipped = 0
    errors = 0

    for call in calls:
        # Only process Fireflies calls
        if call.get('source') != 'fireflies':
            skipped += 1
            continue

        # Skip if already has participant_domains (unless it has Google Calendar domains that need cleaning)
        existing_domains = call.get('participant_domains')
        if existing_domains:
            # Re-process if it has Google Calendar domains
            has_google_calendar = any('calendar.google.com' in d for d in existing_domains)
            if not has_google_calendar:
                skipped += 1
                continue

        call_id = call.get('id')
        if not call_id:
            skipped += 1
            continue

        try:
            # Fetch meeting_attendees from Fireflies API
            attendees = ff_client.get_meeting_attendees(call_id)

            # Extract external domains
            domains = get_external_domains(attendees, internal_domains)

            if domains:
                call['participant_domains'] = domains
                updated += 1
                print(f'      ✓ {call_id[:16]}: {domains}')
            else:
                skipped += 1

        except Exception as e:
            errors += 1
            print(f'      ⚠️  {call_id[:16]}: {e}')

    # Save updated cache if any calls were updated
    if updated > 0:
        memory.save_call_cache(slug, cache)
        print(f'   💾 Saved cache: {updated} calls updated')

    return (updated, skipped, errors)


def main():
    print("=" * 80)
    print("BACKFILL PARTICIPANT DOMAINS")
    print("=" * 80)

    # Load internal domains from config
    config_path = REPO_ROOT / 'config' / 'client.yaml'
    internal_domains = ['growthbook.io']  # default
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
                internal_domains = config.get('organization', {}).get('internal_domains', ['growthbook.io'])
                print(f"\n✓ Loaded internal domains: {internal_domains}")
        except Exception as e:
            print(f"\n⚠️  Could not load internal_domains from config: {e}")
            print(f"   Using default: {internal_domains}")
    else:
        print(f"\n⚠️  config/client.yaml not found, using default: {internal_domains}")

    # Initialize clients
    print("\n1. Initializing clients...")
    memory = GitHubMemory()
    ff_client = get_fireflies_client()

    # Test Fireflies connection
    if not ff_client.test_connection():
        print("❌ Failed to connect to Fireflies API")
        print("   Make sure FIREFLIES_API_KEY environment variable is set")
        return

    print("   ✓ Connected to Fireflies API")

    # Load deal index to get active company slugs
    print("\n2. Loading active deals...")
    index_path = memory.deals_dir / 'index.json'
    if not index_path.exists():
        print("❌ Deal index not found. Run scripts/etl_deals.py first.")
        return

    with open(index_path) as f:
        deal_index = json.load(f)

    active_slugs = set()
    for deal in deal_index.get('deals', {}).values():
        slug = deal.get('company_slug')
        if slug:
            active_slugs.add(slug)

    print(f"   Found {len(active_slugs)} active company slugs")

    # Filter to only those with call cache files (using fuzzy matching)
    slugs_with_cache = []
    for slug in active_slugs:
        # Try to load cache with fuzzy matching
        cache = memory.load_call_cache(slug)
        if cache:
            slugs_with_cache.append(slug)

    print(f"   {len(slugs_with_cache)} have call cache files (using fuzzy matching)")

    if not slugs_with_cache:
        print("\n✓ No call cache files to backfill")
        return

    # Process each company
    print(f"\n3. Backfilling participant domains...")
    total_updated = 0
    total_skipped = 0
    total_errors = 0
    companies_updated = 0

    for i, slug in enumerate(slugs_with_cache, 1):
        print(f"\n   [{i}/{len(slugs_with_cache)}] {slug}")

        updated, skipped, errors = backfill_one_company(
            slug, memory, ff_client, internal_domains
        )

        total_updated += updated
        total_skipped += skipped
        total_errors += errors

        if updated > 0:
            companies_updated += 1

        if updated == 0 and skipped == 0 and errors == 0:
            print(f'      (no Fireflies calls)')

    # Summary
    print("\n" + "=" * 80)
    print("BACKFILL COMPLETE")
    print("=" * 80)
    print(f"Companies processed: {len(slugs_with_cache)}")
    print(f"Companies updated:   {companies_updated}")
    print(f"Calls updated:       {total_updated}")
    print(f"Calls skipped:       {total_skipped}")
    print(f"Errors:              {total_errors}")
    print("=" * 80)


if __name__ == '__main__':
    main()
