"""
Compare Signal 3 flagged deal counts: 7-day vs 14-day threshold

Sanity check after updating Signal 3 threshold from 7 to 14 days.
Shows how many active deals would be flagged under each threshold.
"""

import os
from datetime import datetime, timezone
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
    """Fetch all active deals from deals table"""
    response = sb.table('deals').select(
        'deal_id, company_name, stage, segment, deal_status'
    ).eq('deal_status', 'active').execute()

    return response.data

def get_all_deals():
    """Fetch all deals (for broader comparison if active has no data)"""
    response = sb.table('deals').select(
        'deal_id, company_name, stage, segment, deal_status'
    ).execute()

    return response.data

def get_last_activity_date(deal_id):
    """Get most recent notes_last_updated timestamp for a deal"""
    response = sb.table('property_history').select(
        'changed_at'
    ).eq('deal_id', deal_id).eq(
        'property_name', 'notes_last_updated'
    ).order('changed_at', desc=True).limit(1).execute()

    if not response.data:
        return None

    return datetime.fromisoformat(response.data[0]['changed_at'].replace('Z', '+00:00'))

def main():
    print("Comparing Signal 3 Threshold Impact: 7 Days vs 14 Days")
    print("=" * 70)

    # Get active deals
    active_deals = get_active_deals()
    print(f"\nTotal active deals: {len(active_deals)}")

    # If no active deals have activity data, check all deals for comparison
    check_all_deals = False

    # Current time
    now = datetime.now(timezone.utc)

    # Track flagging under each threshold
    flagged_7_days = []
    flagged_14_days = []
    no_activity_data = []

    # Check each deal
    for deal in active_deals:
        deal_id = deal['deal_id']
        last_activity = get_last_activity_date(deal_id)

        if last_activity is None:
            no_activity_data.append(deal)
            continue

        days_since_activity = (now - last_activity).days

        # Check 7-day threshold
        if days_since_activity > 7:
            flagged_7_days.append({
                'deal': deal,
                'days_since_activity': days_since_activity
            })

        # Check 14-day threshold
        if days_since_activity > 14:
            flagged_14_days.append({
                'deal': deal,
                'days_since_activity': days_since_activity
            })

    # Report results
    print(f"\n{'=' * 70}")
    print("RESULTS")
    print("=" * 70)

    print(f"\nDeals with NO activity data: {len(no_activity_data)}")
    print(f"  (Signal 3 cannot evaluate - routes to no_signal classification)")

    print(f"\nDeals flagged at 7-day threshold: {len(flagged_7_days)}")
    print(f"Deals flagged at 14-day threshold: {len(flagged_14_days)}")

    reduction = len(flagged_7_days) - len(flagged_14_days)
    if len(flagged_7_days) > 0:
        reduction_pct = (reduction / len(flagged_7_days)) * 100
        print(f"\nReduction: {reduction} deals ({reduction_pct:.1f}% fewer flags at 14 days)")
    else:
        reduction_pct = 0.0

    # Show deals that would be flagged at 7 but not at 14
    flagged_7_only = [f for f in flagged_7_days if f not in flagged_14_days]

    if flagged_7_only:
        print(f"\n{'=' * 70}")
        print(f"DEALS FLAGGED AT 7 DAYS BUT NOT AT 14 DAYS ({len(flagged_7_only)} deals)")
        print("=" * 70)
        print("\nThese deals have 8-14 days since last activity:")

        for item in sorted(flagged_7_only, key=lambda x: x['days_since_activity']):
            deal = item['deal']
            days = item['days_since_activity']
            print(f"\n  {deal['company_name']}")
            print(f"    Stage: {deal['stage']}")
            print(f"    Segment: {deal.get('segment', 'Unknown')}")
            print(f"    Days since activity: {days}")

    # Show deals that would still be flagged at 14 days
    if flagged_14_days:
        print(f"\n{'=' * 70}")
        print(f"DEALS STILL FLAGGED AT 14 DAYS ({len(flagged_14_days)} deals)")
        print("=" * 70)
        print("\nThese deals have >14 days since last activity:")

        for item in sorted(flagged_14_days, key=lambda x: -x['days_since_activity'])[:10]:
            deal = item['deal']
            days = item['days_since_activity']
            print(f"\n  {deal['company_name']}")
            print(f"    Stage: {deal['stage']}")
            print(f"    Segment: {deal.get('segment', 'Unknown')}")
            print(f"    Days since activity: {days}")

        if len(flagged_14_days) > 10:
            print(f"\n  ... and {len(flagged_14_days) - 10} more deals")

    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print("=" * 70)
    print(f"\n7-day threshold: {len(flagged_7_days)} deals flagged")
    print(f"14-day threshold: {len(flagged_14_days)} deals flagged")
    print(f"Difference: {reduction} fewer deals flagged (-{reduction_pct:.1f}%)")
    print(f"\nNo activity data: {len(no_activity_data)} deals")
    coverage = ((len(active_deals) - len(no_activity_data)) / len(active_deals) * 100) if len(active_deals) > 0 else 0
    print(f"  Coverage: {coverage:.1f}%")

    # If active deals have no activity data, check all deals for comparison
    if len(no_activity_data) == len(active_deals):
        print(f"\n{'=' * 70}")
        print("NOTE: All active deals have no activity data.")
        print("Checking ALL deals (including closed) for threshold comparison...")
        print("=" * 70)

        all_deals = get_all_deals()
        print(f"\nTotal deals (all statuses): {len(all_deals)}")

        flagged_7_all = []
        flagged_14_all = []
        no_activity_all = []

        for deal in all_deals:
            deal_id = deal['deal_id']
            last_activity = get_last_activity_date(deal_id)

            if last_activity is None:
                no_activity_all.append(deal)
                continue

            days_since_activity = (now - last_activity).days

            if days_since_activity > 7:
                flagged_7_all.append({
                    'deal': deal,
                    'days_since_activity': days_since_activity
                })

            if days_since_activity > 14:
                flagged_14_all.append({
                    'deal': deal,
                    'days_since_activity': days_since_activity
                })

        print(f"\nALL DEALS (including closed):")
        print(f"  With activity data: {len(all_deals) - len(no_activity_all)}")
        print(f"  No activity data: {len(no_activity_all)}")
        print(f"\n  Flagged at 7 days: {len(flagged_7_all)}")
        print(f"  Flagged at 14 days: {len(flagged_14_all)}")

        reduction_all = len(flagged_7_all) - len(flagged_14_all)
        if len(flagged_7_all) > 0:
            reduction_pct_all = (reduction_all / len(flagged_7_all)) * 100
            print(f"  Reduction: {reduction_all} deals ({reduction_pct_all:.1f}% fewer flags at 14 days)")

        # Show sample of deals in 8-14 day range
        flagged_7_only_all = [f for f in flagged_7_all if f not in flagged_14_all]
        if flagged_7_only_all:
            print(f"\n  Sample deals with 8-14 days since activity (first 5):")
            for item in sorted(flagged_7_only_all, key=lambda x: x['days_since_activity'])[:5]:
                deal = item['deal']
                days = item['days_since_activity']
                print(f"    {deal['company_name']}: {days} days ({deal['deal_status']})")

if __name__ == '__main__':
    main()
