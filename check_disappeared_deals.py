#!/usr/bin/env python3
"""
Check the 6 deals that disappeared from ROW/SMB snapshot.
Are they in the deals table? What's their current status?
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

print("Checking 6 disappeared deals")
print("=" * 70)

disappeared_deals = [
    '38816659085',  # $20,000 - the missing one
    '16895554409',  # $17,871 - detected as lost
    '44545878048',  # $0
    '50904222822',  # $0
    '44496605767',  # $0
    '45960155911',  # $0
]

# Check if they exist in deals table
deals_data = select_all(sb, 'deals', 'deal_id,deal_status,close_date,stage,deal_value,segment,region',
                        filters=[('in_', 'deal_id', disappeared_deals)])

print(f"Found {len(deals_data)} of {len(disappeared_deals)} deals in deals table:")
print()

deals_dict = {d['deal_id']: d for d in deals_data}

for deal_id in disappeared_deals:
    d = deals_dict.get(deal_id)
    if d:
        print(f"Deal {deal_id}:")
        print(f"  Status: {d.get('deal_status')}")
        print(f"  Close date: {d.get('close_date')}")
        print(f"  Stage: {d.get('stage')}")
        print(f"  Value: ${d.get('deal_value'):,.0f}" if d.get('deal_value') else "  Value: None")
        print(f"  Region: {d.get('region')}")
        print(f"  Segment: {d.get('segment')}")
    else:
        print(f"Deal {deal_id}: NOT FOUND in deals table")
    print()

# Check all snapshots for deal 38816659085 (the $20K one)
print("=" * 70)
print("Checking snapshot history for deal 38816659085 ($20K missing)")
print("-" * 70)

snapshots = select_all(sb, 'deals_snapshot', 'snapshot_date,deal_value,deal_status,region,segment',
                      filters=[('eq', 'deal_id', '38816659085')])

if snapshots:
    print(f"Found {len(snapshots)} snapshots:")
    for s in sorted(snapshots, key=lambda x: x['snapshot_date']):
        print(f"  {s['snapshot_date']}: value=${s.get('deal_value') or 0:,.0f}, status={s.get('deal_status')}, {s.get('region')}/{s.get('segment')}")
else:
    print("No snapshots found for this deal")

# Check property_history for deal 38816659085
print()
print("Checking property_history for deal 38816659085:")
print("-" * 70)

property_history = select_all(sb, 'property_history', 'property,value,timestamp',
                              filters=[('eq', 'deal_id', '38816659085')])

if property_history:
    print(f"Found {len(property_history)} property changes:")
    # Group by property
    by_property = {}
    for ph in property_history:
        prop = ph['property']
        if prop not in by_property:
            by_property[prop] = []
        by_property[prop].append(ph)

    for prop in sorted(by_property.keys()):
        print(f"\n  {prop}:")
        for ph in sorted(by_property[prop], key=lambda x: x['timestamp']):
            print(f"    {ph['timestamp']}: {ph['value']}")
else:
    print("No property_history found for this deal")

print()
print("=" * 70)
print("DIAGNOSIS")
print("=" * 70)
print("If deal 38816659085 has close_date or dealstage history around 2026-04-13,")
print("it should have been detected as won/lost by the hybrid function.")
