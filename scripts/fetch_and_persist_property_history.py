#!/usr/bin/env python3
"""
Fetch property history from HubSpot and persist to Supabase

Reuses the validation script's proven fetch logic (737/737 success, 0 errors)
and adds immediate write to property_history table.

UNIQUE(deal_id, property_name, changed_at) makes re-runs safe (upsert behavior).
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
from field_semantics import is_won

HUBSPOT_API_KEY = os.getenv('HUBSPOT_API_KEY')
if not HUBSPOT_API_KEY:
    print("❌ HUBSPOT_API_KEY not set")
    sys.exit(1)

def parse_date(date_str):
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except:
        return None

def fetch_and_persist_deal_history(sb, deal_id, deal_info):
    """
    Fetch property history from HubSpot and write to Supabase immediately.

    Returns: (success: bool, nlu_changes: int, dealstage_changes: int)
    """
    # Fetch from HubSpot API (same as validation script)
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
                    'old_value': None,  # HubSpot doesn't provide old value for this field
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
                    'old_value': None,  # Could extract from previous change, but not critical
                    'new_value': value,
                    'source_type': source_type
                })

        # Batch insert to Supabase (upsert via UNIQUE constraint)
        all_rows = nlu_rows + dealstage_rows

        if all_rows:
            # Use upsert to handle duplicates gracefully
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
    print("FETCH AND PERSIST PROPERTY HISTORY")
    print("=" * 80)
    print()

    # Fetch closed deals (same as validation)
    print("Fetching closed deals from Supabase...")
    all_deals = sb.table('deals').select(
        'deal_id,company_name,stage,deal_status'
    ).execute().data

    closed_deals = []
    for deal in all_deals:
        if is_won(deal.get('stage')):
            deal['outcome'] = 'won'
            closed_deals.append(deal)
        elif deal.get('deal_status') == 'lost':
            deal['outcome'] = 'lost'
            closed_deals.append(deal)

    print(f"Total closed deals: {len(closed_deals)}")
    print()

    print(f"Fetching property history from HubSpot and writing to Supabase...")
    print("This will take ~2.5 minutes with rate limiting (5 calls/sec)")
    print()

    stats = {
        'total_deals': len(closed_deals),
        'success': 0,
        'errors': 0,
        'nlu_changes_total': 0,
        'dealstage_changes_total': 0,
        'deals_with_nlu_history': 0,
        'deals_with_dealstage_history': 0
    }

    start_time = time.time()

    for i, deal in enumerate(closed_deals):
        deal_id = deal['deal_id']

        if (i + 1) % 50 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed
            remaining = (len(closed_deals) - i - 1) / rate
            print(f"  Progress: {i+1}/{len(closed_deals)} ({100*(i+1)/len(closed_deals):.1f}%) - ETA: {remaining:.0f}s")

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
    print(f"Time elapsed: {elapsed:.1f}s ({len(closed_deals)/elapsed:.1f} deals/sec)")
    print()
    print(f"Deals processed: {stats['total_deals']}")
    print(f"  Success: {stats['success']}")
    print(f"  Errors: {stats['errors']}")
    print()
    print(f"Property changes written:")
    print(f"  notes_last_updated: {stats['nlu_changes_total']} changes")
    print(f"  dealstage: {stats['dealstage_changes_total']} changes")
    print()
    print(f"Deals with history:")
    print(f"  notes_last_updated: {stats['deals_with_nlu_history']}/{stats['total_deals']} ({100*stats['deals_with_nlu_history']/stats['total_deals']:.1f}%)")
    print(f"  dealstage: {stats['deals_with_dealstage_history']}/{stats['total_deals']} ({100*stats['deals_with_dealstage_history']/stats['total_deals']:.1f}%)")
    print()

    # Verify row counts in Supabase
    print("Verifying data in Supabase...")

    nlu_count_db = sb.table('property_history').select('*', count='exact').eq('property_name', 'notes_last_updated').limit(0).execute()
    dealstage_count_db = sb.table('property_history').select('*', count='exact').eq('property_name', 'dealstage').limit(0).execute()

    print(f"  notes_last_updated rows in DB: {nlu_count_db.count}")
    print(f"  dealstage rows in DB: {dealstage_count_db.count}")
    print()

    if nlu_count_db.count == stats['nlu_changes_total']:
        print("✅ notes_last_updated row count matches")
    else:
        print(f"⚠️  notes_last_updated row count mismatch: {nlu_count_db.count} in DB vs {stats['nlu_changes_total']} fetched")

    if dealstage_count_db.count == stats['dealstage_changes_total']:
        print("✅ dealstage row count matches")
    else:
        print(f"⚠️  dealstage row count mismatch: {dealstage_count_db.count} in DB vs {stats['dealstage_changes_total']} fetched")

    print()
    print("=" * 80)
    print("✅ PROPERTY HISTORY PERSISTED TO SUPABASE")
    print("=" * 80)
    print()
    print("Next: Run Signal 2/3 derivation as SQL against property_history table")

if __name__ == '__main__':
    main()
