#!/usr/bin/env python3
"""
Refined check: actual won/lost deals vs forecast close dates.
Many deals have close_date set but status=active (these are forecasts, not actual closes).
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

from supabase_client import select_all

print("=" * 70)
print("EMEA Actual Closes Check (Aug 17 - Sep 8)")
print("=" * 70)
print()

# Get all EMEA deals
deals_emea = select_all(sb, 'deals',
                        'deal_id,company_name,deal_status,close_date,deal_value,segment,stage,create_date',
                        filters=[('eq', 'region', 'EMEA')])

# Check property_history for actual won/lost status changes in the window
print("Checking property_history for dealstage changes...")
property_history = select_all(sb, 'property_history', 'deal_id,property,value,timestamp',
                              filters=[
                                  ('eq', 'property', 'dealstage'),
                                  ('gte', 'timestamp', '2026-08-17'),
                                  ('lte', 'timestamp', '2026-09-08T23:59:59')
                              ])

print(f"Found {len(property_history)} dealstage changes in window")
print()

# Filter to EMEA deals and won/lost stages
emea_deal_ids = set(d['deal_id'] for d in deals_emea)
won_lost_stages = ['closedwon', 'closedlost']

actual_closes = []
for ph in property_history:
    if ph['deal_id'] in emea_deal_ids and ph['value'] in won_lost_stages:
        actual_closes.append(ph)

print(f"EMEA deals that actually closed won/lost: {len(actual_closes)}")
if actual_closes:
    # Group by deal and show the most recent status
    by_deal = {}
    for ph in actual_closes:
        deal_id = ph['deal_id']
        if deal_id not in by_deal or ph['timestamp'] > by_deal[deal_id]['timestamp']:
            by_deal[deal_id] = ph

    print(f"Unique deals: {len(by_deal)}")
    for deal_id, ph in sorted(by_deal.items(), key=lambda x: x[1]['timestamp']):
        deal = next((d for d in deals_emea if d['deal_id'] == deal_id), None)
        if deal:
            print(f"  {deal_id}: {deal['company_name'][:30]:30s} ${deal.get('deal_value') or 0:>10,.0f} → {ph['value']:15s} at {ph['timestamp']}")
else:
    print("  None found - no actual closes via property_history")

print()
print("-" * 70)
print("Alternative check: deals with status=won/lost in deals table")
print("-" * 70)

won_deals = [d for d in deals_emea if d['deal_status'] == 'won']
lost_deals = [d for d in deals_emea if d['deal_status'] == 'lost']

print(f"Total EMEA won deals: {len(won_deals)}")
print(f"Total EMEA lost deals: {len(lost_deals)}")
print()

# But we need to know WHEN they closed - check if close_date is in window
won_in_window = [d for d in won_deals if d.get('close_date') and '2026-08-17' <= d['close_date'] <= '2026-09-08']
lost_in_window = [d for d in lost_deals if d.get('close_date') and '2026-08-17' <= d['close_date'] <= '2026-09-08']

print(f"Won in window (by close_date): {len(won_in_window)}")
for d in won_in_window[:5]:
    print(f"  {d['deal_id']}: {d['company_name'][:30]:30s} ${d.get('deal_value') or 0:>10,.0f} closed {d['close_date']}")

print()
print(f"Lost in window (by close_date): {len(lost_in_window)}")
for d in lost_in_window[:5]:
    print(f"  {d['deal_id']}: {d['company_name'][:30]:30s} ${d.get('deal_value') or 0:>10,.0f} closed {d['close_date']}")

print()
print("=" * 70)
print("WATERFALL WEEK DATES")
print("=" * 70)
print("Note: Waterfall computes weekly changes, not daily")
print("Last 2 weeks means: 2026-08-24 vs 2026-08-17, and 2026-09-07 vs 2026-08-28")
print()
print("From waterfall output:")
print("  2026-08-17: SMB arr_change -$30K, Unknown lost $75K")
print("  2026-08-24: No movement")
print("  2026-08-28: Mid-Market won $20K, SMB lost $100K")
print("  2026-09-07: No movement")
print("  2026-09-08: No movement")
print()
print("The Slack query 'last 2 weeks' would be Aug 24→Sep 7 period")
print("In this period: $20K won, $100K lost on Aug 28")
print("But then Sep 7 shows $0 everywhere")

print()
print("=" * 70)
print("DIAGNOSIS")
print("=" * 70)

if len(actual_closes) == 0:
    print("✓ GENUINE FLATNESS (via property_history)")
    print("  No dealstage changes to won/lost in Aug 17 - Sep 8")
    print("  The flatness is REAL, not a sync issue")
elif len(won_in_window) > 0 or len(lost_in_window) > 0:
    print("✗ POTENTIAL SYNC ISSUE")
    print(f"  Found {len(won_in_window)} won and {len(lost_in_window)} lost deals")
    print("  But need to check if these are captured in earlier waterfalls")
    print("  (deals may have closed before Aug 17)")
else:
    print("? UNCLEAR - need deeper investigation")
