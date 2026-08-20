#!/usr/bin/env python3
"""
Verify today's snapshot coverage.
"""
import os
import sys
from datetime import datetime, date
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, 'scripts')
from supabase import create_client
from supabase_client import select_all

sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])

today = date.today().isoformat()
today_dt = date.today()

print("=" * 80)
print(f"SNAPSHOT VERIFICATION: {today}")
print("=" * 80)

# 1. Get today's snapshot
snapshot = select_all(sb, 'deals_snapshot',
                      columns='deal_id, pipeline_id',
                      filters=[('eq', 'snapshot_date', today)])

snapshot_default = [s for s in snapshot if s.get('pipeline_id') == 'default']
snapshot_deal_ids = set(s['deal_id'] for s in snapshot_default)

print(f"\n1. TODAY'S SNAPSHOT ({today}):")
print(f"   Total rows written: {len(snapshot):,}")
print(f"   Default pipeline: {len(snapshot_default):,}")
print(f"   Distinct deals captured: {len(snapshot_deal_ids):,}")

# 2. Calculate genuinely open today
deals = select_all(sb, 'deals',
                  columns='deal_id, create_date, close_date, pipeline_id, deal_status, stage')

genuinely_open = []
for deal in deals:
    if deal.get('pipeline_id') != 'default':
        continue
    
    create_date = deal.get('create_date')
    if not create_date:
        continue
    
    create_dt = datetime.fromisoformat(create_date).date()
    if create_dt > today_dt:
        continue
    
    # Check if closed before today
    close_date = deal.get('close_date')
    if close_date:
        close_dt = datetime.fromisoformat(close_date).date()
        if close_dt < today_dt:
            continue  # Closed before today
    
    genuinely_open.append(deal)

genuinely_open_ids = set(d['deal_id'] for d in genuinely_open)

print(f"\n2. GENUINELY OPEN TODAY:")
print(f"   Default pipeline deals (current): {len([d for d in deals if d.get('pipeline_id') == 'default']):,}")
print(f"   Created on or before {today}: {len([d for d in genuinely_open if d.get('create_date')]):,}")
print(f"   Not closed before {today}: {len(genuinely_open):,}")

# 3. Coverage analysis
in_both = snapshot_deal_ids & genuinely_open_ids
in_snapshot_only = snapshot_deal_ids - genuinely_open_ids
missing = genuinely_open_ids - snapshot_deal_ids

coverage_pct = (len(in_both) / len(genuinely_open_ids) * 100) if genuinely_open_ids else 0

print(f"\n3. COVERAGE ANALYSIS:")
print(f"   In both (correct captures): {len(in_both):,}")
print(f"   In snapshot only (shouldn't be): {len(in_snapshot_only):,}")
print(f"   Missing from snapshot: {len(missing):,}")
print(f"\n   COVERAGE RATIO: {len(snapshot_deal_ids):,} / {len(genuinely_open_ids):,} = {coverage_pct:.1f}%")

# Gate check
if coverage_pct >= 95:
    print(f"\n   ✓ PASS: Coverage {coverage_pct:.1f}% >= 95% threshold")
elif coverage_pct >= 90:
    print(f"\n   ⚠️  WARNING: Coverage {coverage_pct:.1f}% below 95% but above 90%")
else:
    print(f"\n   ✗ FAIL: Coverage {coverage_pct:.1f}% below 90% threshold")

# Investigate missing deals
if missing:
    print(f"\n4. INVESTIGATING MISSING DEALS ({len(missing):,}):")
    missing_deals = [d for d in genuinely_open if d['deal_id'] in list(missing)[:10]]
    for deal in missing_deals:
        print(f"   Deal {deal['deal_id']}: create={deal.get('create_date')}, close={deal.get('close_date')}, stage={deal.get('stage')}")

# Investigate extra deals
if in_snapshot_only:
    print(f"\n5. INVESTIGATING EXTRA DEALS ({len(in_snapshot_only):,}):")
    extra_deals = [d for d in deals if d['deal_id'] in list(in_snapshot_only)[:10]]
    for deal in extra_deals:
        create = deal.get('create_date')
        close = deal.get('close_date')
        if create:
            create_dt = datetime.fromisoformat(create).date()
            if create_dt > today_dt:
                print(f"   Deal {deal['deal_id']}: Created AFTER today ({create})")
        if close:
            close_dt = datetime.fromisoformat(close).date()
            if close_dt < today_dt:
                print(f"   Deal {deal['deal_id']}: Closed BEFORE today ({close})")

print(f"\n{'='*80}")
print("VERDICT")
print(f"{'='*80}")

if coverage_pct >= 95 and len(missing) == 0:
    print(f"\n✓ Writer is WORKING CORRECTLY")
    print(f"  {len(snapshot_deal_ids):,} deals captured")
    print(f"  {coverage_pct:.1f}% coverage (target: ≥95%)")
    print(f"  Ready for weekly scheduling")
elif coverage_pct >= 90:
    print(f"\n⚠️  Writer is MOSTLY WORKING")
    print(f"  {len(snapshot_deal_ids):,} deals captured")
    print(f"  {coverage_pct:.1f}% coverage (target: ≥95%)")
    print(f"  Investigate {len(missing):,} missing deals before scheduling")
else:
    print(f"\n✗ Writer has ISSUES")
    print(f"  Only {coverage_pct:.1f}% coverage")
    print(f"  {len(missing):,} deals missing")
    print(f"  Fix before scheduling")

