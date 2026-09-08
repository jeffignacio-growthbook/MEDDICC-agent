#!/usr/bin/env python3
"""
Fetch property history for ACTIVE deals and persist to Supabase

Expands property_history table to include active pipeline deals (444 deals).
Uses same proven fetch logic as closed deals script.

UNIQUE(deal_id, property_name, changed_at) makes this safe to run alongside
existing closed deals data (upsert behavior).
"""
import os
import sys
import requests
import time
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / 'api'))
from db import get_supabase

HUBSPOT_API_KEY = os.getenv('HUBSPOT_API_KEY')
if not HUBSPOT_API_KEY:
    print("❌ HUBSPOT_API_KEY not set")
    sys.exit(1)

def fetch_and_persist_deal_history(sb, deal_id, deal_info):
    """
    Fetch property history from HubSpot and write to Supabase immediately.

    Returns: (success: bool, nlu_changes: int, dealstage_changes: int)
    """
    url = f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}"
    params = {
        'properties': 'notes_last_updated,dealstage',
        'propertiesWithHistory': 'notes_last_updated,dealstage'
    }
    headers = {
        'Authorization': f'Bearer {HUBSPOT_API_KEY}',
        'Content-Type': 'application/json'
    }

    # Rate limit: 5 calls per second
    time.sleep(0.2)

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)

        if response.status_code != 200:
            return (False, 0, 0)

        data = response.json()
        history = data.get('propertiesWithHistory', {})

        nlu_history = history.get('notes_last_updated', [])
        dealstage_history = history.get('dealstage', [])

        # Write notes_last_updated history to Supabase
        nlu_rows = []
        for change in nlu_history:
            ts_str = change.get('timestamp')
            value = change.get('value')
            source_type = change.get('sourceType', 'unknown')

            if ts_str:
                nlu_rows.append({
                    'deal_id': str(deal_id),
                    'property_name': 'notes_last_updated',
                    'changed_at': ts_str,
                    'old_value': None,
                    'new_value': value,
                    'source_type': source_type
                })

        # Write dealstage history to Supabase
        dealstage_rows = []
        for change in dealstage_history:
            ts_str = change.get('timestamp')
            value = change.get('value')
            source_type = change.get('sourceType', 'unknown')

            if ts_str:
                dealstage_rows.append({
                    'deal_id': str(deal_id),
                    'property_name': 'dealstage',
                    'changed_at': ts_str,
                    'old_value': None,
                    'new_value': value,
                    'source_type': source_type
                })

        # Batch insert to Supabase (upsert via UNIQUE constraint)
        all_rows = nlu_rows + dealstage_rows

        if all_rows:
            sb.table('property_history').upsert(
                all_rows,
                on_conflict='deal_id,property_name,changed_at'
            ).execute()

        return (True, len(nlu_rows), len(dealstage_rows))

    except Exception as e:
        print(f"  Error fetching {deal_id}: {e}")
        return (False, 0, 0)

def main():
    sb = get_supabase()

    print("=" * 80)
    print("FETCH PROPERTY HISTORY: ACTIVE DEALS")
    print("=" * 80)
    print()

    # Fetch ACTIVE deals (not closed)
    print("Fetching active deals from Supabase...")
    active_deals = sb.table('deals').select(
        'deal_id,company_name,stage,deal_status'
    ).eq('deal_status', 'active').execute().data

    print(f"Total active deals: {len(active_deals)}")
    print()

    # Check how many already have property_history (in case of partial re-run)
    print("Checking for existing property_history coverage...")
    active_deal_ids = [d['deal_id'] for d in active_deals]

    # Query existing coverage in batches
    existing_coverage = set()
    batch_size = 100
    for i in range(0, len(active_deal_ids), batch_size):
        batch = active_deal_ids[i:i + batch_size]
        existing = sb.table('property_history').select(
            'deal_id'
        ).in_('deal_id', batch).execute()

        existing_coverage.update(row['deal_id'] for row in existing.data)

    print(f"Deals already in property_history: {len(existing_coverage)}/{len(active_deals)}")
    print(f"Deals to fetch: {len(active_deals) - len(existing_coverage)}")
    print()

    print(f"Fetching property history from HubSpot and writing to Supabase...")
    print(f"This will take ~{len(active_deals) * 0.2 / 60:.1f} minutes with rate limiting (5 calls/sec)")
    print()

    stats = {
        'total_deals': len(active_deals),
        'success': 0,
        'errors': 0,
        'nlu_changes_total': 0,
        'dealstage_changes_total': 0,
        'deals_with_nlu_history': 0,
        'deals_with_dealstage_history': 0,
        'skipped_existing': 0
    }

    start_time = time.time()

    for i, deal in enumerate(active_deals):
        deal_id = deal['deal_id']

        # Skip if already has coverage (for partial re-runs)
        if deal_id in existing_coverage:
            stats['skipped_existing'] += 1
            continue

        if (i + 1) % 50 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            remaining = (len(active_deals) - i - 1) / rate if rate > 0 else 0
            print(f"  Progress: {i+1}/{len(active_deals)} ({100*(i+1)/len(active_deals):.1f}%) - ETA: {remaining:.0f}s")

        success, nlu_count, dealstage_count = fetch_and_persist_deal_history(sb, deal_id, deal)

        if success:
            stats['success'] += 1
            stats['nlu_changes_total'] += nlu_count
            stats['dealstage_changes_total'] += dealstage_count

            if nlu_count > 0:
                stats['deals_with_nlu_history'] += 1
            if dealstage_count > 0:
                stats['deals_with_dealstage_history'] += 1
        else:
            stats['errors'] += 1

    elapsed = time.time() - start_time

    print()
    print("=" * 80)
    print("FETCH COMPLETE")
    print("=" * 80)
    print()
    print(f"Time elapsed: {elapsed:.1f}s ({len(active_deals)/elapsed:.1f} deals/sec)" if elapsed > 0 else "Time elapsed: 0s")
    print()
    print(f"Deals processed: {stats['total_deals']}")
    print(f"  Success: {stats['success']}")
    print(f"  Errors: {stats['errors']}")
    print(f"  Skipped (already in DB): {stats['skipped_existing']}")
    print()
    print(f"Property changes written:")
    print(f"  notes_last_updated: {stats['nlu_changes_total']} changes")
    print(f"  dealstage: {stats['dealstage_changes_total']} changes")
    print()
    print(f"Active deals with history:")
    print(f"  notes_last_updated: {stats['deals_with_nlu_history']}/{stats['total_deals']} ({100*stats['deals_with_nlu_history']/stats['total_deals']:.1f}%)")
    print(f"  dealstage: {stats['deals_with_dealstage_history']}/{stats['total_deals']} ({100*stats['deals_with_dealstage_history']/stats['total_deals']:.1f}%)")
    print()

    # Verify coverage improvement
    print("=" * 80)
    print("COVERAGE VERIFICATION")
    print("=" * 80)
    print()

    # Re-check coverage after fetch
    final_coverage = set()
    for i in range(0, len(active_deal_ids), batch_size):
        batch = active_deal_ids[i:i + batch_size]
        existing = sb.table('property_history').select(
            'deal_id'
        ).in_('deal_id', batch).execute()

        final_coverage.update(row['deal_id'] for row in existing.data)

    print(f"Active deals in property_history:")
    print(f"  Before: {len(existing_coverage)}/{len(active_deals)} ({100*len(existing_coverage)/len(active_deals):.1f}%)")
    print(f"  After: {len(final_coverage)}/{len(active_deals)} ({100*len(final_coverage)/len(active_deals):.1f}%)")
    print(f"  Improvement: +{len(final_coverage) - len(existing_coverage)} deals")
    print()

    # Check notes_last_updated specifically
    nlu_coverage = set()
    for i in range(0, len(active_deal_ids), batch_size):
        batch = active_deal_ids[i:i + batch_size]
        existing = sb.table('property_history').select(
            'deal_id'
        ).in_('deal_id', batch).eq('property_name', 'notes_last_updated').execute()

        nlu_coverage.update(row['deal_id'] for row in existing.data)

    print(f"Active deals with notes_last_updated:")
    print(f"  {len(nlu_coverage)}/{len(active_deals)} ({100*len(nlu_coverage)/len(active_deals):.1f}%)")
    print()

    if len(nlu_coverage) > 0:
        print("✅ Signal 3 coverage for active deals now available")
        print(f"   Expected to enable Signal 3 evaluation on ~{100*len(nlu_coverage)/len(active_deals):.0f}% of active pipeline")
    else:
        print("⚠️  No active deals have notes_last_updated history")
        print("   This suggests a live data hygiene issue (activities not being logged)")

    print()
    print("=" * 80)
    print("✅ ACTIVE DEALS PROPERTY HISTORY FETCH COMPLETE")
    print("=" * 80)
    print()
    print("Next: Re-run Signal 3 threshold comparison to see actual active pipeline coverage")

if __name__ == '__main__':
    main()
