#!/usr/bin/env python3
"""
Verify the "boundary crossing" hypothesis for UNKNOWN group mismatches.

For 2-3 sample weeks with UNKNOWN mismatches:
1. Identify the specific deals causing the mismatch
2. Check if they moved between UNKNOWN and real region/segment groups
3. Confirm the arithmetic matches the reported mismatch
"""

import os
from dotenv import load_dotenv

load_dotenv()

from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

import sys
sys.path.insert(0, 'scripts')
from supabase_client import select_all

print("Verifying boundary crossing hypothesis")
print("=" * 70)

# Get UNKNOWN group mismatches
result = sb.table('waterfall_weekly')\
    .select('week_ending, region, segment, beginning_value, ending_value, net_change')\
    .eq('region', 'UNKNOWN')\
    .execute()

mismatches = []
for row in result.data:
    expected = row['beginning_value'] + row['net_change']
    actual = row['ending_value']
    if abs(expected - actual) > 0.01:
        mismatches.append({
            'week': row['week_ending'],
            'region': row['region'],
            'segment': row['segment'],
            'beginning': row['beginning_value'],
            'ending': row['ending_value'],
            'net_change': row['net_change'],
            'expected_ending': expected,
            'mismatch': actual - expected
        })

print(f"\nFound {len(mismatches)} UNKNOWN group weeks with mismatches")
print(f"Analyzing 3 samples:\n")

# Pick 3 diverse samples
samples = [mismatches[0], mismatches[len(mismatches)//2], mismatches[-1]] if len(mismatches) >= 3 else mismatches

for i, sample in enumerate(samples[:3], 1):
    week = sample['week']
    print(f"\n{'='*70}")
    print(f"Sample {i}: Week ending {week}")
    print(f"{'='*70}")
    print(f"  Beginning:       ${sample['beginning']:,.2f}")
    print(f"  Net change:      ${sample['net_change']:,.2f}")
    print(f"  Expected ending: ${sample['expected_ending']:,.2f}")
    print(f"  Actual ending:   ${sample['ending']:,.2f}")
    print(f"  Mismatch:        ${sample['mismatch']:,.2f}")

    # Get snapshots for this week and previous week
    # Find previous week
    all_weeks = sorted(set([m['week'] for m in mismatches]))
    week_idx = all_weeks.index(week)
    prev_week = all_weeks[week_idx - 1] if week_idx > 0 else None

    if not prev_week:
        print(f"\n  ⚠️  Cannot find previous week to compare")
        continue

    print(f"\nComparing snapshots: {prev_week} → {week}")

    # Load both snapshots
    prev_snap = select_all(sb, 'deals_snapshot', 'deal_id, deal_value, region, segment',
                          filters=[('eq', 'snapshot_date', prev_week)])
    new_snap = select_all(sb, 'deals_snapshot', 'deal_id, deal_value, region, segment',
                         filters=[('eq', 'snapshot_date', week)])

    prev_dict = {d['deal_id']: d for d in prev_snap}
    new_dict = {d['deal_id']: d for d in new_snap}

    # Find deals that changed region/segment groups
    boundary_crossers = []

    for deal_id in set(prev_dict.keys()) | set(new_dict.keys()):
        p = prev_dict.get(deal_id)
        n = new_dict.get(deal_id)

        if p and n:
            p_region = p.get('region') or 'UNKNOWN'
            n_region = n.get('region') or 'UNKNOWN'
            p_segment = p.get('segment') or 'Unknown'
            n_segment = n.get('segment') or 'Unknown'

            p_group = f"{p_region}/{p_segment}"
            n_group = f"{n_region}/{n_segment}"

            # Check if crossed between UNKNOWN and real region
            p_is_unknown = p_region == 'UNKNOWN'
            n_is_unknown = n_region == 'UNKNOWN'

            if p_is_unknown != n_is_unknown:
                boundary_crossers.append({
                    'deal_id': deal_id,
                    'prev_group': p_group,
                    'new_group': n_group,
                    'value': n.get('deal_value') or p.get('deal_value') or 0,
                    'direction': 'UNKNOWN→Real' if p_is_unknown else 'Real→UNKNOWN'
                })

    print(f"\nBoundary crossing deals: {len(boundary_crossers)}")

    if boundary_crossers:
        # Calculate impact on UNKNOWN group
        unknown_to_real = [d for d in boundary_crossers if d['direction'] == 'UNKNOWN→Real']
        real_to_unknown = [d for d in boundary_crossers if d['direction'] == 'Real→UNKNOWN']

        unknown_to_real_value = sum(d['value'] for d in unknown_to_real)
        real_to_unknown_value = sum(d['value'] for d in real_to_unknown)

        print(f"\n  Deals leaving UNKNOWN group: {len(unknown_to_real)}")
        print(f"    Total value: ${unknown_to_real_value:,.2f}")
        if unknown_to_real[:3]:
            print(f"    Sample deals:")
            for d in unknown_to_real[:3]:
                print(f"      {d['deal_id']}: ${d['value']:,.0f} - {d['prev_group']} → {d['new_group']}")

        print(f"\n  Deals joining UNKNOWN group: {len(real_to_unknown)}")
        print(f"    Total value: ${real_to_unknown_value:,.2f}")
        if real_to_unknown[:3]:
            print(f"    Sample deals:")
            for d in real_to_unknown[:3]:
                print(f"      {d['deal_id']}: ${d['value']:,.0f} - {d['prev_group']} → {d['new_group']}")

        # Calculate expected impact on UNKNOWN group
        # Beginning should include deals that WERE in UNKNOWN at prev_week
        # Ending should include deals that ARE in UNKNOWN at week
        # Net impact from boundary crossing: +real_to_unknown - unknown_to_real

        boundary_net_impact = real_to_unknown_value - unknown_to_real_value

        print(f"\n  Net impact from boundary crossing: ${boundary_net_impact:,.2f}")
        print(f"  Actual mismatch:                   ${sample['mismatch']:,.2f}")
        print(f"  Difference:                        ${abs(boundary_net_impact - sample['mismatch']):,.2f}")

        # Check if boundary crossing explains the mismatch
        explained_pct = abs(boundary_net_impact) / abs(sample['mismatch']) * 100 if sample['mismatch'] != 0 else 0

        if abs(boundary_net_impact - sample['mismatch']) < 0.01:
            print(f"\n  ✓ CONFIRMED: Boundary crossing FULLY explains the mismatch")
        elif explained_pct > 90:
            print(f"\n  ✓ MOSTLY CONFIRMED: Boundary crossing explains {explained_pct:.1f}% of mismatch")
        elif explained_pct > 50:
            print(f"\n  ⚠️  PARTIALLY CONFIRMED: Boundary crossing explains {explained_pct:.1f}% of mismatch")
            print(f"      Remaining ${abs(sample['mismatch'] - boundary_net_impact):,.2f} unexplained")
        else:
            print(f"\n  ✗ NOT CONFIRMED: Boundary crossing only explains {explained_pct:.1f}% of mismatch")
            print(f"      Mismatch is likely due to OTHER causes")
    else:
        print(f"\n  ✗ NO boundary crossing deals found")
        print(f"     Mismatch of ${sample['mismatch']:,.2f} is NOT explained by boundary crossing")
        print(f"     This indicates a different cause")

print(f"\n\n{'='*70}")
print("CONCLUSION:")
print("="*70)

# Count how many samples were fully explained
fully_explained = 0
partially_explained = 0
not_explained = 0

for sample in samples[:3]:
    week = sample['week']
    all_weeks = sorted(set([m['week'] for m in mismatches]))
    week_idx = all_weeks.index(week)
    prev_week = all_weeks[week_idx - 1] if week_idx > 0 else None

    if not prev_week:
        continue

    # Recalculate (simplified check)
    prev_snap = select_all(sb, 'deals_snapshot', 'deal_id, deal_value, region',
                          filters=[('eq', 'snapshot_date', prev_week)])
    new_snap = select_all(sb, 'deals_snapshot', 'deal_id, deal_value, region',
                         filters=[('eq', 'snapshot_date', week)])

    prev_dict = {d['deal_id']: d for d in prev_snap}
    new_dict = {d['deal_id']: d for d in new_snap}

    boundary_value = 0
    for deal_id in set(prev_dict.keys()) | set(new_dict.keys()):
        p = prev_dict.get(deal_id)
        n = new_dict.get(deal_id)

        if p and n:
            p_unknown = (p.get('region') or 'UNKNOWN') == 'UNKNOWN'
            n_unknown = (n.get('region') or 'UNKNOWN') == 'UNKNOWN'

            if p_unknown != n_unknown:
                value = n.get('deal_value') or p.get('deal_value') or 0
                if p_unknown:
                    boundary_value -= value  # Left UNKNOWN
                else:
                    boundary_value += value  # Joined UNKNOWN

    explained_pct = abs(boundary_value) / abs(sample['mismatch']) * 100 if sample['mismatch'] != 0 else 0

    if explained_pct > 90:
        fully_explained += 1
    elif explained_pct > 50:
        partially_explained += 1
    else:
        not_explained += 1

total_checked = fully_explained + partially_explained + not_explained

if fully_explained == total_checked:
    print("✓ HYPOTHESIS CONFIRMED")
    print(f"  All {total_checked} sampled weeks' UNKNOWN mismatches are fully explained")
    print(f"  by deals crossing between UNKNOWN and real region groups")
    print(f"  This is expected behavior when historical snapshots lack enrichment")
elif fully_explained + partially_explained == total_checked:
    print("⚠️  HYPOTHESIS MOSTLY CONFIRMED")
    print(f"  {fully_explained}/{total_checked} weeks fully explained by boundary crossing")
    print(f"  {partially_explained}/{total_checked} weeks partially explained")
    print(f"  This suggests boundary crossing is the PRIMARY but not SOLE cause")
else:
    print("✗ HYPOTHESIS NOT CONFIRMED")
    print(f"  Only {fully_explained + partially_explained}/{total_checked} weeks explained by boundary crossing")
    print(f"  {not_explained}/{total_checked} weeks NOT explained - indicates OTHER bugs")
