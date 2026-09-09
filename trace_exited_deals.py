#!/usr/bin/env python3
"""
Trace the 6 exited deals in Case 1 (ROW/SMB week 2026-04-13) to see:
1. Are they still in new snapshot but with different region/segment?
2. Are they closed won/lost?
3. Are they being detected by the hybrid won/lost function?
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'scripts/analytics'))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

from supabase_client import select_all
from deal_status_history import get_deal_status_as_of
from datetime import date

print("Tracing 6 exited deals from ROW/SMB week 2026-04-13")
print("=" * 70)

prev_week = '2026-04-06'
test_week = '2026-04-13'
region = 'ROW'
segment = 'SMB'

# Load snapshots
prev_snap = select_all(sb, 'deals_snapshot', '*',
                      filters=[('eq', 'snapshot_date', prev_week)])
new_snap = select_all(sb, 'deals_snapshot', '*',
                     filters=[('eq', 'snapshot_date', test_week)])

prev_dict = {d['deal_id']: d for d in prev_snap}
new_dict = {d['deal_id']: d for d in new_snap}

# Filter to ROW/SMB
def in_group(snap):
    return [d for d in snap
            if (d.get('region') or 'UNKNOWN') == region
            and (d.get('segment') or 'Unknown') == segment
            and d.get('deal_status') == 'active']  # Match waterfall filter

prev_group = in_group(prev_snap)
new_group = in_group(new_snap)

prev_ids = set(d['deal_id'] for d in prev_group)
new_ids = set(d['deal_id'] for d in new_group)
exited = prev_ids - new_ids

print(f"Found {len(exited)} deals that exited ROW/SMB group")
print(f"Beginning value (from waterfall): $37,871")
print(f"Lost value (from waterfall): $17,871")
print(f"Missing: ${37_871 - 17_871:,} ($20,000)")
print()

# Load deal status data for hybrid detection
deal_status_data = select_all(sb, 'deals', 'deal_id,close_date,stage',
                              filters=[('in_', 'deal_id', list(exited))])
deal_status_map = {d['deal_id']: d for d in deal_status_data}

new_date = date.fromisoformat(test_week)

print("Tracing each exited deal:")
print("-" * 70)

total_exited_value = 0
won_detected = []
lost_detected = []
moved_group = []
unknown = []

for deal_id in exited:
    p = prev_dict.get(deal_id)
    n = new_dict.get(deal_id)

    if not p:
        continue

    prev_value = p.get('deal_value') or 0
    total_exited_value += prev_value

    print(f"\nDeal {deal_id} (value: ${prev_value:,.0f}):")
    print(f"  Prev: region={p.get('region')}, segment={p.get('segment')}, status={p.get('deal_status')}")

    if n:
        print(f"  New:  region={n.get('region')}, segment={n.get('segment')}, status={n.get('deal_status')}")

        # Check if it moved to different group
        if (n.get('region') != p.get('region') or n.get('segment') != p.get('segment')):
            print(f"  → Deal moved to {n.get('region')}/{n.get('segment')} group")
            moved_group.append((deal_id, prev_value))
        elif n.get('deal_status') != 'active':
            # Check hybrid detection
            deal_data = deal_status_map.get(deal_id, {})
            close_date_str = deal_data.get('close_date')
            current_stage = deal_data.get('stage')

            close_date = None
            if close_date_str:
                try:
                    close_date = date.fromisoformat(close_date_str[:10])
                except:
                    pass

            detected_status = get_deal_status_as_of(
                sb, deal_id, new_date,
                close_date=close_date,
                current_stage=current_stage
            )

            print(f"  Snapshot status: {n.get('deal_status')}")
            print(f"  Hybrid detected: {detected_status}")

            if detected_status == 'won':
                print(f"  → Detected as WON")
                won_detected.append((deal_id, prev_value))
            elif detected_status == 'lost':
                print(f"  → Detected as LOST")
                lost_detected.append((deal_id, prev_value))
            else:
                print(f"  → Status unclear")
                unknown.append((deal_id, prev_value))
    else:
        print(f"  New:  NOT IN SNAPSHOT")
        print(f"  → Deal disappeared from all snapshots")
        unknown.append((deal_id, prev_value))

print()
print("=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"Total exited value: ${total_exited_value:,.2f}")
print()
print(f"Moved to different group: {len(moved_group)} deals, ${sum(v for _, v in moved_group):,.2f}")
for deal_id, value in moved_group:
    print(f"  - {deal_id}: ${value:,.0f}")

print()
print(f"Detected as won: {len(won_detected)} deals, ${sum(v for _, v in won_detected):,.2f}")
for deal_id, value in won_detected:
    print(f"  - {deal_id}: ${value:,.0f}")

print()
print(f"Detected as lost: {len(lost_detected)} deals, ${sum(v for _, v in lost_detected):,.2f}")
for deal_id, value in lost_detected:
    print(f"  - {deal_id}: ${value:,.0f}")

print()
print(f"Unknown/unclear: {len(unknown)} deals, ${sum(v for _, v in unknown):,.2f}")
for deal_id, value in unknown:
    print(f"  - {deal_id}: ${value:,.0f}")

print()
print("RECONCILIATION CHECK:")
print(f"  Waterfall lost_value: $17,871")
print(f"  Detected lost (hybrid): ${sum(v for _, v in lost_detected):,.2f}")
print(f"  Difference: ${abs(17_871 - sum(v for _, v in lost_detected)):,.2f}")
