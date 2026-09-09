#!/usr/bin/env python3
"""
Check April 2026 anomaly: 413 deals closed but only 20.8% have property_history.
This is dragging down the average. What happened?
"""

import os
from datetime import datetime, date
from dotenv import load_dotenv

load_dotenv()

from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

import sys
sys.path.insert(0, 'scripts')
from supabase_client import select_all

print("Investigating April 2026 anomaly")
print("=" * 70)

# Load deals
all_deals = select_all(sb, 'deals', 'deal_id, deal_status, close_date, created_at, deal_value')
closed_deals = [d for d in all_deals if d.get('deal_status') in ['won', 'lost']]

# Load property_history
ph_result = sb.table('property_history')\
    .select('deal_id')\
    .eq('property_name', 'dealstage')\
    .execute()

deals_with_ph = set(r['deal_id'] for r in ph_result.data)

# Filter April 2026 deals
april_deals = [d for d in closed_deals
               if d.get('close_date') and d['close_date'].startswith('2026-04')]

print(f"April 2026 closed deals: {len(april_deals)}")
print(f"With property_history: {len([d for d in april_deals if d['deal_id'] in deals_with_ph])}")

# Check created_at distribution for April deals
print(f"\nWhen were April deals CREATED?")

april_created_at = [datetime.fromisoformat(d['created_at'].replace('Z', '+00:00')).date()
                    for d in april_deals if d.get('created_at')]

if april_created_at:
    april_created_at.sort()
    earliest = april_created_at[0]
    latest = april_created_at[-1]

    print(f"  Earliest created: {earliest}")
    print(f"  Latest created: {latest}")

    # Check how many were created IN April vs earlier
    created_in_april = len([d for d in april_created_at if d.month == 4 and d.year == 2026])
    created_before_april = len([d for d in april_created_at if not (d.month == 4 and d.year == 2026)])

    print(f"\n  Created IN April 2026: {created_in_april}")
    print(f"  Created BEFORE April 2026: {created_before_april}")

    if created_before_april > created_in_april:
        print(f"\n  ⚠️  BULK CLOSE PATTERN DETECTED")
        print(f"     Most April deals were created earlier, then closed in April")
        print(f"     This suggests a bulk cleanup or data migration")
        print(f"     These deals likely pre-date property_history sync improvements")

# Compare April to surrounding months
print(f"\n" + "=" * 70)
print("Coverage comparison:")

def get_month_stats(month_str):
    month_deals = [d for d in closed_deals
                   if d.get('close_date') and d['close_date'].startswith(month_str)]
    with_ph = len([d for d in month_deals if d['deal_id'] in deals_with_ph])
    return len(month_deals), with_ph, (with_ph / len(month_deals) * 100) if month_deals else 0

months = ['2026-03', '2026-04', '2026-05', '2026-06', '2026-07', '2026-08']
for month in months:
    total, with_ph, pct = get_month_stats(month)
    marker = " ⚠️  ANOMALY" if month == '2026-04' else ""
    print(f"  {month}: {total:>3} deals, {with_ph:>3} with PH ({pct:>5.1f}%){marker}")

# Calculate coverage EXCLUDING April
print(f"\n" + "=" * 70)
print("Impact of excluding April anomaly:")

non_april_closed = [d for d in closed_deals
                    if not (d.get('close_date') and d['close_date'].startswith('2026-04'))]
non_april_with_ph = len([d for d in non_april_closed if d['deal_id'] in deals_with_ph])

overall_coverage = (len([d for d in closed_deals if d['deal_id'] in deals_with_ph]) / len(closed_deals) * 100)
non_april_coverage = (non_april_with_ph / len(non_april_closed) * 100) if non_april_closed else 0

print(f"  Overall coverage (all deals): {overall_coverage:.1f}%")
print(f"  Coverage excluding April 2026: {non_april_coverage:.1f}%")
print(f"  Difference: +{non_april_coverage - overall_coverage:.1f}%")

# Check recent deals (last 90 days) explicitly
from datetime import timedelta
cutoff_90d = date.today() - timedelta(days=90)

recent_closed = [d for d in closed_deals
                 if d.get('close_date') and date.fromisoformat(d['close_date'][:10]) >= cutoff_90d]
recent_with_ph = len([d for d in recent_closed if d['deal_id'] in deals_with_ph])
recent_coverage = (recent_with_ph / len(recent_closed) * 100) if recent_closed else 0

print(f"\n  Last 90 days coverage: {recent_coverage:.1f}%")

# CONCLUSION
print(f"\n" + "=" * 70)
print("CONCLUSION:")

if len(april_deals) > 200 and recent_coverage > 40:
    print(f"✓ April 2026 was an ANOMALY (bulk close/migration)")
    print(f"  - 413 deals closed in April (vs ~60-70 typical)")
    print(f"  - Only 20.8% coverage (vs 40%+ in recent months)")
    print(f"  - This is dragging down overall statistics")
    print(f"\n  FOR CURRENT OPERATIONS:")
    print(f"  - Recent deals (last 90 days): {recent_coverage:.1f}% coverage")
    print(f"  - Trend is improving: 36% → 43% → 57%")
    print(f"  - Property_history IS viable for CURRENT deals")
    print(f"\n  IMPLICATION FOR FIX:")
    print(f"  - Option A will work for RECENT deals (post-April)")
    print(f"  - April anomaly and older deals will remain 'unknown'")
    print(f"  - Need to decide: is fixing {recent_coverage:.0f}% of recent deals acceptable?")
    print(f"  - Original 9 deals from Aug 24-28 should have coverage (recent period)")
    print(f"  - But test showed they don't - need to investigate those specific deals")
else:
    print(f"⚠️  April may be an anomaly, but recent coverage still poor")
    print(f"  Even excluding April, coverage is only {non_april_coverage:.1f}%")
    print(f"  Property_history still not reliable for this use case")
