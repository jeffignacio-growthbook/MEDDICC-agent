"""
Property History Active Deals Check

Diagnostic to determine why 444/444 active deals show 0% notes_last_updated coverage:

Option 1: property_history fetch was scoped only to closed deals (simple fix: re-run fetch)
Option 2: Active deals genuinely don't have notes_last_updated updates in HubSpot (live hygiene gap)

This script checks:
1. How many distinct deal_ids are in property_history
2. Do any match the 444 active deal_ids?
3. If they match, do they have notes_last_updated entries specifically?
"""

import os
from collections import defaultdict
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Supabase setup
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_active_deals():
    """Fetch all active deal_ids"""
    response = sb.table('deals').select(
        'deal_id, company_name, stage, segment'
    ).eq('deal_status', 'active').execute()

    return response.data

def get_property_history_deal_ids():
    """Get all distinct deal_ids present in property_history"""
    # Fetch in batches to handle large table
    all_deal_ids = set()
    offset = 0
    batch_size = 1000

    while True:
        response = sb.table('property_history').select(
            'deal_id'
        ).range(offset, offset + batch_size - 1).execute()

        if not response.data:
            break

        for row in response.data:
            all_deal_ids.add(row['deal_id'])

        if len(response.data) < batch_size:
            break

        offset += batch_size
        print(f"  Fetched {offset} rows from property_history...")

    return all_deal_ids

def get_property_history_for_deals(deal_ids, property_name=None):
    """
    Get property_history entries for specific deal_ids.
    Optionally filter by property_name.
    """
    results = defaultdict(list)

    # Query in batches (Supabase has limits on IN clause size)
    batch_size = 100
    deal_id_list = list(deal_ids)

    for i in range(0, len(deal_id_list), batch_size):
        batch = deal_id_list[i:i + batch_size]

        query = sb.table('property_history').select(
            'deal_id, property_name, changed_at'
        ).in_('deal_id', batch)

        if property_name:
            query = query.eq('property_name', property_name)

        response = query.execute()

        for row in response.data:
            results[row['deal_id']].append({
                'property_name': row['property_name'],
                'changed_at': row['changed_at']
            })

    return results

def main():
    print("=" * 80)
    print("PROPERTY_HISTORY ACTIVE DEALS DIAGNOSTIC")
    print("=" * 80)

    # Step 1: Get active deals
    print("\nStep 1: Fetching active deals...")
    active_deals = get_active_deals()
    active_deal_ids = set(d['deal_id'] for d in active_deals)
    print(f"Total active deals: {len(active_deals)}")

    # Step 2: Get all deal_ids in property_history
    print("\nStep 2: Fetching all deal_ids from property_history...")
    property_history_deal_ids = get_property_history_deal_ids()
    print(f"Distinct deal_ids in property_history: {len(property_history_deal_ids)}")

    # Step 3: Check overlap
    print("\nStep 3: Checking overlap...")
    active_in_property_history = active_deal_ids & property_history_deal_ids
    active_not_in_property_history = active_deal_ids - property_history_deal_ids

    print(f"Active deal_ids present in property_history: {len(active_in_property_history)}/{len(active_deal_ids)}")
    print(f"Active deal_ids NOT in property_history: {len(active_not_in_property_history)}/{len(active_deal_ids)}")

    # Decision point
    if len(active_in_property_history) == 0:
        print("\n" + "=" * 80)
        print("DIAGNOSIS: FETCH SCOPE ISSUE")
        print("=" * 80)
        print("\n✅ SIMPLE EXPLANATION:")
        print("   Zero active deal_ids appear in property_history at all.")
        print("   This confirms the fetch was scoped only to closed deals.")
        print("\nRESOLUTION:")
        print("   Re-run property_history fetch against active deal population.")
        print("   Coverage should resolve to ~63% (similar to closed deals).")
        print("\nNO LIVE DATA HYGIENE ISSUE - just need to expand fetch scope.")

    else:
        print("\n" + "=" * 80)
        print("DIAGNOSIS: CHECKING FOR LIVE DATA ISSUE")
        print("=" * 80)
        print(f"\n{len(active_in_property_history)} active deals DO appear in property_history.")
        print("Checking if they have notes_last_updated entries specifically...")

        # Step 4: Check for notes_last_updated specifically
        print("\nStep 4: Checking notes_last_updated coverage for active deals...")
        active_property_history = get_property_history_for_deals(active_in_property_history)

        active_with_notes = set()
        active_without_notes = set()

        for deal_id in active_in_property_history:
            entries = active_property_history.get(deal_id, [])
            property_names = set(e['property_name'] for e in entries)

            if 'notes_last_updated' in property_names:
                active_with_notes.add(deal_id)
            else:
                active_without_notes.add(deal_id)

        print(f"\nActive deals in property_history: {len(active_in_property_history)}")
        print(f"  With notes_last_updated: {len(active_with_notes)}")
        print(f"  Without notes_last_updated: {len(active_without_notes)}")

        # Check what properties they DO have
        if active_without_notes:
            print(f"\nSampling properties for active deals WITHOUT notes_last_updated (first 5):")
            sample_ids = list(active_without_notes)[:5]

            for deal_id in sample_ids:
                entries = active_property_history.get(deal_id, [])
                property_names = set(e['property_name'] for e in entries)

                # Get deal name for context
                deal_info = next((d for d in active_deals if d['deal_id'] == deal_id), None)
                company_name = deal_info['company_name'] if deal_info else 'Unknown'

                print(f"\n  {company_name} (deal_id: {deal_id}):")
                print(f"    Has {len(entries)} property_history entries")
                print(f"    Properties tracked: {', '.join(sorted(property_names)[:10])}")
                if len(property_names) > 10:
                    print(f"    ... and {len(property_names) - 10} more")

        # Final diagnosis
        if len(active_with_notes) == 0 and len(active_in_property_history) > 0:
            print("\n" + "=" * 80)
            print("DIAGNOSIS: LIVE DATA HYGIENE ISSUE")
            print("=" * 80)
            print("\n❌ Active deals ARE in property_history but have NO notes_last_updated entries.")
            print("   This suggests active deals aren't getting notes_last_updated updates in HubSpot.")
            print("\nPOSSIBLE CAUSES:")
            print("   1. Notes/activities not being logged for active deals")
            print("   2. notes_last_updated field not being updated when activities occur")
            print("   3. Sync issue between HubSpot activities and property updates")
            print("\nRESOLUTION:")
            print("   This is a live data quality / process issue, not a fetch problem.")
            print("   Signal 3 coverage gap is genuine - active deals lack activity tracking.")

        elif len(active_with_notes) > 0:
            coverage_pct = len(active_with_notes) / len(active_deals) * 100
            print("\n" + "=" * 80)
            print("DIAGNOSIS: PARTIAL COVERAGE")
            print("=" * 80)
            print(f"\n⚠️  {len(active_with_notes)}/{len(active_deals)} active deals ({coverage_pct:.1f}%) have notes_last_updated.")
            print(f"   {len(active_not_in_property_history)} active deals not in property_history at all.")
            print(f"   {len(active_without_notes)} active deals in property_history but no notes_last_updated.")
            print("\nMIXED ISSUE:")
            print("   1. Some active deals not fetched (expand fetch scope)")
            print("   2. Some active deals fetched but lack notes_last_updated (data hygiene)")
            print("\nRESOLUTION:")
            print("   Re-run fetch for unfetched deals, then assess remaining coverage gap.")

    # Additional context: check closed deals for comparison
    print("\n" + "=" * 80)
    print("COMPARISON: CLOSED DEALS")
    print("=" * 80)

    print("\nFetching closed deals for baseline comparison...")
    closed_deals = sb.table('deals').select(
        'deal_id'
    ).in_('deal_status', ['won', 'lost']).execute()

    closed_deal_ids = set(d['deal_id'] for d in closed_deals.data)
    closed_in_property_history = closed_deal_ids & property_history_deal_ids

    print(f"Total closed deals: {len(closed_deal_ids)}")
    print(f"Closed deal_ids in property_history: {len(closed_in_property_history)}/{len(closed_deal_ids)}")
    print(f"Coverage: {len(closed_in_property_history)/len(closed_deal_ids)*100:.1f}%")

    if len(closed_in_property_history) > 0 and len(active_in_property_history) == 0:
        print("\n✅ This confirms property_history fetch was scoped only to closed deals.")
        print("   Closed deals present, active deals completely absent.")

if __name__ == '__main__':
    main()
