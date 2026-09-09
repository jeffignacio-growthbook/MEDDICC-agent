#!/usr/bin/env python3
"""
Reconcile new EMEA answer against previously verified Aug 28 finding.

KNOWN TRUTH (verified 2 days ago):
- Aug 28: $20K won (Mid-Market) + $100K lost (SMB) = $120K total activity

NEW ANSWER CLAIMS:
- Week of Aug 24: net $0 across all segments
- Week of Aug 28 (partial): -$20K Mid-Market only, remaining segments pending

QUESTIONS:
1. Where is the $100K SMB loss?
2. Is "partial week" real or invented?
3. Do week boundaries align?
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
print("RECONCILE NEW EMEA ANSWER vs VERIFIED AUG 28 DATA")
print("=" * 70)
print()

print("VERIFIED TRUTH (from Sept 7 investigation):")
print("  Aug 28 week_ending:")
print("    - Mid-Market: $20K won")
print("    - SMB: $100K lost")
print("    - Total: $120K activity")
print()

print("NEW ANSWER CLAIMS (Sept 9 rerun):")
print("  Week of Aug 24: net $0 across all segments")
print("  Week of Aug 28 (partial): -$20K Mid-Market only")
print()

print("=" * 70)
print("PULL ACTUAL WATERFALL DATA")
print("=" * 70)
print()

# Get EMEA waterfall for all Aug weeks
emea_aug = select_all(sb, 'waterfall_weekly',
    'week_ending,region,segment,beginning_value,ending_value,' +
    'won_value,lost_value,new_pipeline_value,net_change,' +
    'newly_qualified_value,newly_qualified_count',
    filters=[
        ('eq', 'region', 'EMEA'),
        ('gte', 'week_ending', '2026-08-17'),
        ('lte', 'week_ending', '2026-08-31')
    ])

print(f"Found {len(emea_aug)} EMEA rows for Aug 17-31")
print()

# Group by week_ending
from collections import defaultdict
by_week = defaultdict(list)
for row in emea_aug:
    by_week[row['week_ending']].append(row)

for week in sorted(by_week.keys()):
    rows = by_week[week]
    print(f"Week ending {week}: {len(rows)} rows (segments)")

    total_won = sum(r.get('won_value', 0) or 0 for r in rows)
    total_lost = sum(r.get('lost_value', 0) or 0 for r in rows)
    total_new = sum(r.get('new_pipeline_value', 0) or 0 for r in rows)
    total_qualified = sum(r.get('newly_qualified_value', 0) or 0 for r in rows)

    print(f"  Totals: won=${total_won:,.0f} lost=${total_lost:,.0f} " +
          f"new=${total_new:,.0f} qualified=${total_qualified:,.0f}")

    if total_won > 0 or total_lost > 0 or total_new > 0:
        print(f"  By segment:")
        for r in sorted(rows, key=lambda x: x['segment']):
            seg = r['segment']
            won = r.get('won_value', 0) or 0
            lost = r.get('lost_value', 0) or 0
            new = r.get('new_pipeline_value', 0) or 0

            if won > 0 or lost > 0 or new > 0:
                print(f"    {seg:15s}: won=${won:>10,.0f} lost=${lost:>10,.0f} new=${new:>10,.0f}")
    print()

print("=" * 70)
print("RECONCILIATION CHECK")
print("=" * 70)
print()

# Find Aug 28 week
aug_28_rows = by_week.get('2026-08-28', [])

if not aug_28_rows:
    print("❌ NO AUG 28 DATA FOUND")
    print("   This is a serious issue - verified data from 2 days ago is missing")
else:
    print(f"✅ Aug 28 week exists: {len(aug_28_rows)} rows")
    print()

    # Check for the verified $20K won + $100K lost
    midmarket = [r for r in aug_28_rows if r['segment'] == 'Mid-Market'][0] if any(r['segment'] == 'Mid-Market' for r in aug_28_rows) else None
    smb = [r for r in aug_28_rows if r['segment'] == 'SMB'][0] if any(r['segment'] == 'SMB' for r in aug_28_rows) else None

    if midmarket:
        mm_won = midmarket.get('won_value', 0) or 0
        print(f"  Mid-Market won: ${mm_won:,.0f}")
        if abs(mm_won - 20000) < 1:
            print("    ✅ Matches verified $20K won")
        else:
            print(f"    ❌ MISMATCH: Expected $20K, got ${mm_won:,.0f}")
    else:
        print("  ❌ Mid-Market row missing")

    print()

    if smb:
        smb_lost = smb.get('lost_value', 0) or 0
        print(f"  SMB lost: ${smb_lost:,.0f}")
        if abs(smb_lost - 100000) < 1:
            print("    ✅ Matches verified $100K lost")
        else:
            print(f"    ❌ MISMATCH: Expected $100K, got ${smb_lost:,.0f}")
    else:
        print("  ❌ SMB row missing")

print()
print("=" * 70)
print("CHECK: Is Aug 28 'Partial Week'?")
print("=" * 70)
print()

# A complete week should have all segments (Enterprise, Mid-Market, SMB, Unknown)
expected_segments = {'Enterprise', 'Mid-Market', 'SMB', 'Unknown'}
actual_segments = {r['segment'] for r in aug_28_rows}

print(f"Expected segments: {sorted(expected_segments)}")
print(f"Actual segments:   {sorted(actual_segments)}")
print()

if actual_segments == expected_segments:
    print("✅ COMPLETE WEEK - All 4 segments present")
    print()
    print('The "partial week" claim in the answer is INCORRECT.')
    print("This is synthesis invention, not data reality.")
elif len(actual_segments) < len(expected_segments):
    print(f"⚠️  INCOMPLETE WEEK - Only {len(actual_segments)} of 4 segments")
    print(f"   Missing: {expected_segments - actual_segments}")
    print()
    print('The "partial week" claim is CORRECT - real data gap.')
else:
    print(f"Unexpected segment count: {len(actual_segments)}")

print()
print("=" * 70)
print("CHECK: Week Boundary Alignment")
print("=" * 70)
print()

# Check if "Week of Aug 24" vs "Week of Aug 28" refers to same or different waterfall rows
aug_24_rows = by_week.get('2026-08-24', [])

if aug_24_rows:
    print(f"2026-08-24 week_ending exists: {len(aug_24_rows)} rows")

    total_24 = sum(r.get('net_change', 0) or 0 for r in aug_24_rows)
    print(f"  Net change: ${total_24:,.0f}")

    if abs(total_24) < 1:
        print("  ✅ Confirms '$0 net change' for Aug 24 week")
    else:
        print(f"  ❌ MISMATCH: Answer says $0, data shows ${total_24:,.0f}")
else:
    print("No 2026-08-24 week_ending found")

print()
print("Week boundary interpretation:")
print('  "Week of Aug 24" likely refers to week_ending 2026-08-24')
print('  "Week of Aug 28" likely refers to week_ending 2026-08-28')
print("  These are DIFFERENT weeks (4 days apart)")
print()

print("=" * 70)
print("VERDICT")
print("=" * 70)
print()

if aug_28_rows and midmarket and smb:
    mm_won = midmarket.get('won_value', 0) or 0
    smb_lost = smb.get('lost_value', 0) or 0

    verified_total = 20000 + 100000  # $120K
    actual_total = mm_won + smb_lost

    if abs(actual_total - verified_total) < 1:
        print("✅ DATA RECONCILES")
        print(f"   Verified: $20K won + $100K lost = $120K")
        print(f"   Actual: ${mm_won:,.0f} won + ${smb_lost:,.0f} lost = ${actual_total:,.0f}")
        print()

        # But check if answer reported it correctly
        print("❌ BUT ANSWER INCOMPLETE")
        print('   Answer said: "Aug 28: -$20K Mid-Market only"')
        print(f'   Should say: "Aug 28: +$20K Mid-Market won, -$100K SMB lost"')
        print()
        print("   The $100K SMB loss is MISSING from the answer.")
        print("   This is either:")
        print("     1. Synthesis dropping the SMB segment, or")
        print("     2. 'Partial week' masking complete data")
    else:
        print("❌ DATA DOES NOT RECONCILE")
        print(f"   Expected: $120K total activity")
        print(f"   Found: ${actual_total:,.0f}")
        print()
        print("   This is a regression - verified data has changed.")
else:
    print("❌ CANNOT VERIFY - Missing Aug 28 data or segments")

print()
print("RECOMMENDATION:")
print("  Do NOT trust this answer until synthesis correctly reports:")
print("  'Aug 28: +$20K Mid-Market won, -$100K SMB lost = -$80K net'")
